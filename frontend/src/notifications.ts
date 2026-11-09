/** The bell. Since 1.2.0 the server owns notifications: this file only shows them, so the bell, the Notifications page and push all agree. */
import * as feed from "./events.js";
import { get, post } from "./api.js";
import { h, mount, sheet, toast } from "./dom.js";
import { icon } from "./icons.js";
import type { Status } from "./state.js";
import { dateRange, type RangeValue } from "./pages/kit.js";

export type Kind = "info" | "ok" | "warn" | "bad";
export interface Notice { id: number; ts: number; kind: Kind; icon: string; title: string; text: string; href?: string; read: boolean; count: number; category: string }
interface Row { id: number; ts: number; kind: Kind; icon: string; title: string; body: string; route: string; read: boolean; count: number; category: string }

const MAX = 100;
let items: Notice[] = [];
let unread = 0;
let loaded = false;
const subs = new Set<() => void>();
const conv = (r: Row): Notice => ({ id: r.id, ts: r.ts, kind: r.kind, icon: r.icon, title: r.title, text: r.body, href: r.route, read: r.read, count: r.count, category: r.category });
const changed = (): void => subs.forEach((f) => f());

export const notices = (): Notice[] => items;
export const unreadCount = (): number => unread;
export function onNotices(fn: () => void): () => void { subs.add(fn); return () => subs.delete(fn); }

export async function refresh(): Promise<void> {
  try {
    const r = await get<{ items: Row[]; unread: number }>(`/api/notify/inbox?limit=${MAX}`);
    items = r.items.map(conv); unread = r.unread; loaded = true; changed();
  } catch { /* offline or signed out: keep what is shown */ }
}
export function markAllRead(): void {
  items.forEach((n) => (n.read = true)); unread = 0; changed();
  void post("/api/notify/read", { ids: null }).catch(() => refresh());
}
export function markRead(id: number): void {
  const n = items.find((x) => x.id === id);
  if (!n || n.read) return;
  n.read = true; unread = Math.max(0, unread - 1); changed();
  void post("/api/notify/read", { ids: [id] }).catch(() => refresh());
}
export function clearAll(): void {
  items = []; unread = 0; changed();
  void post("/api/notify/delete", { ids: null }).catch(() => refresh());
}

// ------------------------------------------------------------------ live updates
/** Loads the inbox and keeps it current from the live feed. Returns a function that stops listening. `getStatus` is kept for the caller's signature. */
export function startNotifications(_getStatus: () => Status | null): () => void {
  void refresh();
  const offs: (() => void)[] = [];
  offs.push(feed.on("notify", (e) => {
    const d = e.data as { id: number; title: string; body: string; route: string; kind: Kind; icon: string; category: string; folded?: boolean } | undefined;
    if (!d) return;
    const prev = items.find((x) => x.id === d.id);
    if (prev) { prev.count += 1; prev.title = d.title; prev.text = d.body; prev.ts = Date.now() / 1000; if (prev.read) { prev.read = false; unread += 1; } items = [prev, ...items.filter((x) => x !== prev)]; }
    else { items = [{ id: d.id, ts: Date.now() / 1000, kind: d.kind, icon: d.icon, title: d.title, text: d.body, href: d.route, read: false, count: 1, category: d.category }, ...items].slice(0, MAX); unread += 1; }
    changed();
    if (document.visibilityState === "visible" && d.category !== "stream.mode") toast(d.title, d.kind === "bad" ? "error" : "ok");
  }));
  offs.push(feed.onConnection((up) => { if (up) void refresh(); }));
  const vis = () => { if (document.visibilityState === "visible") void refresh(); };
  document.addEventListener("visibilitychange", vis);
  offs.push(() => document.removeEventListener("visibilitychange", vis));
  return () => offs.forEach((f) => f());
}

// ------------------------------------------------------------------ panel
const ago = (ts: number): string => {
  const s = Math.max(0, Date.now() / 1000 - ts);
  if (s < 45) return "just now";
  if (s < 3600) return `${Math.max(1, Math.round(s / 60))} min ago`;
  if (s < 86400) return `${Math.round(s / 3600)} h ago`;
  return new Date(ts * 1000).toLocaleDateString([], { month: "short", day: "numeric" });
};

function panelContent(close: () => void): { el: HTMLElement; stop: () => void } {
  let onlyUnread = false;
  let range: RangeValue = { label: "", active: false };
  const dates = dateRange({ presets: ["any", "today", "yesterday", "7d", "custom"], label: "Notification dates" }, (v) => { range = v; draw(); });
  const list = h("div", { class: "notice-list" });
  const filter = h("div", { class: "seg-control", role: "group", "aria-label": "Show" },
    [["All", false], ["Unread", true]].map(([l, v]) => h("button", { type: "button", "aria-pressed": String(onlyUnread === v), onclick: (e: Event) => { onlyUnread = v as boolean; Array.from((e.currentTarget as HTMLElement).parentElement!.children).forEach((b, i) => b.setAttribute("aria-pressed", String((i === 1) === onlyUnread))); draw(); } }, String(l))));
  const readAll = h("button", { class: "btn small ghost", type: "button", onclick: () => markAllRead() }, icon("check", 15), "Read all");
  const clear = h("button", { class: "btn small ghost", type: "button", onclick: () => clearAll() }, icon("trash", 15), "Clear");
  function draw(): void {
    const shown = items.filter((n) => (!onlyUnread || !n.read) && (range.since === undefined || n.ts >= range.since) && (range.until === undefined || n.ts < range.until));
    readAll.disabled = unreadCount() === 0;
    clear.disabled = items.length === 0;
    mount(list, shown.length ? shown.map((n) => {
      const open = () => { markRead(n.id); if (n.href) { close(); location.hash = n.href; } };
      return h("button", { class: `notice ${n.kind}${n.read ? "" : " unread"}`, type: "button", onclick: open },
        h("span", { class: "notice-ico" }, icon(n.icon, 18)),
        h("span", { class: "notice-body" }, h("strong", null, n.title), n.text ? h("span", { class: "small muted" }, n.text) : null, h("span", { class: "small muted" }, ago(n.ts))),
        n.read ? null : h("i", { class: "notice-dot", "aria-label": "Unread" }));
    }) : h("div", { class: "empty" }, icon("checkCircle", 30), h("span", null, range.active ? `Nothing for ${range.label.toLowerCase()}.` : onlyUnread ? "No unread notifications." : loaded ? "You are all caught up. Events like stream start, reminders and problems appear here." : "Loading…")));
  }
  draw();
  const off = onNotices(draw);
  const foot = h("a", { class: "btn small ghost", href: "#/notifications", onclick: () => close() }, icon("sliders", 15), "Notification settings");
  const el = h("div", { class: "notice-panel" }, h("div", { class: "notice-tools" }, filter, h("span", { class: "tb-spacer" }), readAll, clear), dates.el, list, h("div", { class: "notice-foot" }, foot));
  return { el, stop: off };
}

let popover: { close: () => void } | null = null;

/** Opens the notification panel: a dropdown under the bell on wide screens, a bottom sheet on phones. */
export function openNotifications(anchor: HTMLElement): void {
  if (popover) { popover.close(); return; }
  const phone = matchMedia("(max-width: 719px)").matches;
  if (phone) {
    const holder: { close: () => void } = { close: () => undefined };
    const { el, stop } = panelContent(() => holder.close());
    const s = sheet("Notifications", el, () => { stop(); popover = null; });
    holder.close = s.close;
    popover = s;
    return;
  }
  const holder: { close: () => void } = { close: () => undefined };
  const { el, stop } = panelContent(() => holder.close());
  const box = h("div", { class: "popover", role: "dialog", "aria-label": "Notifications" }, h("header", null, h("h2", null, "Notifications")), el);
  const rect = anchor.getBoundingClientRect();
  box.style.top = `${Math.round(rect.bottom + 8)}px`;
  box.style.right = `${Math.max(12, Math.round(window.innerWidth - rect.right - 8))}px`;
  const onDown = (e: Event) => { if (!box.contains(e.target as Node) && !anchor.contains(e.target as Node)) holder.close(); };
  const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") holder.close(); };
  holder.close = () => { box.remove(); stop(); document.removeEventListener("pointerdown", onDown, true); document.removeEventListener("keydown", onKey, true); anchor.setAttribute("aria-expanded", "false"); popover = null; };
  document.body.appendChild(box);
  document.addEventListener("pointerdown", onDown, true);
  document.addEventListener("keydown", onKey, true);
  anchor.setAttribute("aria-expanded", "true");
  popover = holder;
}
