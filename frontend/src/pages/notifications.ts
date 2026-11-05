import { del, get, post } from "../api.js";
import { ago, busy, confirmDialog, h, mount, toast } from "../dom.js";
import * as feed from "../events.js";
import { icon } from "../icons.js";
import { currentMode, refreshStatus } from "../state.js";
import { empty, pageHead } from "./shared.js";
import type { Page } from "./types.js";

interface Note { id: number; ts: number; kind: string; level: string; title: string; body: string; demo: boolean; read: boolean }

const KIND: Record<string, { icon: string; label: string }> = {
  stream: { icon: "youtube", label: "Stream" },
  timer: { icon: "timer", label: "Timers" },
  reminder: { icon: "clock", label: "Reminders" },
  mode: { icon: "flask", label: "Mode" },
  system: { icon: "bot", label: "System" },
};
const FILTERS: { id: string; label: string; test: (n: Note) => boolean }[] = [
  { id: "all", label: "All", test: () => true },
  { id: "unread", label: "Unread", test: (n) => !n.read },
  { id: "warning", label: "Warnings", test: (n) => n.level === "warning" || n.level === "error" },
  { id: "stream", label: "Stream", test: (n) => n.kind === "stream" },
  { id: "timer", label: "Timers", test: (n) => n.kind === "timer" },
  { id: "reminder", label: "Reminders", test: (n) => n.kind === "reminder" },
];

function dayLabel(ts: number): string {
  const d = new Date(ts * 1000), today = new Date();
  const y = new Date(); y.setDate(today.getDate() - 1);
  if (d.toDateString() === today.toDateString()) return "Today";
  if (d.toDateString() === y.toDateString()) return "Yesterday";
  return d.toLocaleDateString([], { weekday: "long", month: "short", day: "numeric" });
}

export const notifications: Page = {
  id: "notifications",
  title: "Notifications",
  icon: "bell",
  blurb: "System events and bot activity",
  render(root) {
    let items: Note[] = [];
    let filter = "all";
    const list = h("div");
    const chips = h("div", { class: "scroll-x" });

    const markAll = h("button", { class: "btn ghost", type: "button", onclick: (e: Event) => busy(e.currentTarget as HTMLButtonElement, async () => { await post("/api/notifications/read", {}); await load(); await refreshStatus(); }) }, icon("check", 16), "Mark all read");
    const clearAll = h("button", { class: "btn ghost", type: "button", onclick: async (e: Event) => {
      const btn = e.currentTarget as HTMLButtonElement;
      if (!(await confirmDialog("Clear notifications?", `This removes every ${currentMode()} notification. Moderation history is not affected.`, "Clear", "danger"))) return;
      busy(btn, async () => { await del("/api/notifications"); await load(); await refreshStatus(); }, "Cleared");
    } }, icon("trash", 16), "Clear");

    const drawChips = () => mount(chips, h("div", { class: "seg-control", role: "group", "aria-label": "Filter notifications" }, FILTERS.map((f) => {
      const n = items.filter(f.test).length;
      return h("button", { type: "button", "aria-pressed": String(filter === f.id), onclick: () => { filter = f.id; drawChips(); draw(); } }, f.label, f.id === "unread" && n ? h("span", { class: "n" }, String(n)) : null);
    })));

    const row = (n: Note) => {
      const k = KIND[n.kind] ?? KIND.system;
      const r = h("li", { class: `note-row${n.read ? "" : " unread"}${n.level === "warning" || n.level === "error" ? " warn" : ""}` },
        h("span", { class: "note-ico" }, icon(n.level === "warning" || n.level === "error" ? "alert" : k.icon, 18)),
        h("div", { class: "grow" }, h("div", { class: "note-title" }, n.title), n.body ? h("div", { class: "muted small" }, n.body) : null),
        h("div", { class: "note-meta" }, h("span", { class: "muted small" }, ago(n.ts)), !n.read ? h("span", { class: "unread-dot", title: "Unread" }) : null));
      if (!n.read) r.addEventListener("click", () => void post("/api/notifications/read", { ids: [n.id] }).then(() => { n.read = true; drawChips(); draw(); return refreshStatus(); }).catch((e) => toast(e.message, "error")));
      return r;
    };
    const draw = () => {
      const f = FILTERS.find((x) => x.id === filter)!;
      const shown = items.filter(f.test);
      if (!shown.length) return mount(list, h("div", { class: "block" }, empty("bell", items.length
        ? "Nothing matches this filter."
        : `No notifications yet. Stream events, timer problems, reminders and mode changes appear here. Moderation requests are in Moderation.`)));
      const groups = new Map<string, Note[]>();
      for (const n of shown) { const d = dayLabel(n.ts); groups.set(d, [...(groups.get(d) ?? []), n]); }
      mount(list, h("div", { class: "stack" }, Array.from(groups).map(([day, rows]) =>
        h("section", { class: "block flush" }, h("header", null, h("h2", null, day), h("span", { class: "muted small" }, `${rows.length}`)), h("ul", { class: "list notes" }, rows.map(row))))));
      markAll.disabled = !items.some((n) => !n.read);
      clearAll.disabled = !items.length;
    };
    const load = async () => {
      items = (await get<{ items: Note[] }>("/api/notifications?limit=200")).items;
      drawChips();
      draw();
    };

    mount(root,
      pageHead("bell", "Notifications", "What the bot and the stream have been doing. Moderation requests that need a decision are in Moderation, not here.", h("div", { class: "row" }, markAll, clearAll)),
      h("div", { class: `banner${currentMode() === "demo" ? " demo" : ""}` }, icon(currentMode() === "demo" ? "flask" : "zap", 18), h("span", null, currentMode() === "demo" ? "Showing Demo notifications. Live notifications are kept separately." : "Showing Live notifications. Demo notifications are kept separately.")),
      h("div", { style: "margin-bottom:14px" }, chips),
      list);
    void load().catch((e) => toast(e.message, "error"));
    const off = feed.on("notification", () => void load().catch(() => undefined));
    return () => off();
  },
};
