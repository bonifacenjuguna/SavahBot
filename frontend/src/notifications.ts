/** Notification center. Separate from Moderation: moderation is a work queue, notifications are a log of what happened. */
import * as feed from "./events.js";
import { h, mount, sheet } from "./dom.js";
import { icon } from "./icons.js";
import { onStatus, type Status } from "./state.js";

export type Kind = "info" | "ok" | "warn" | "bad";
export interface Notice { id: string; ts: number; kind: Kind; icon: string; title: string; text: string; href?: string; read: boolean; key?: string; count: number }

const STORE = "savahbot.notices";
const MAX = 50;
let items: Notice[] = load();
const subs = new Set<() => void>();

function load(): Notice[] {
  try { const v = JSON.parse(localStorage.getItem(STORE) ?? "[]"); return Array.isArray(v) ? v.slice(0, MAX) : []; } catch { return []; }
}
function save(): void { try { localStorage.setItem(STORE, JSON.stringify(items)); } catch { /* private mode */ } }
function changed(): void { save(); subs.forEach((f) => f()); }

export const notices = (): Notice[] => items;
export const unreadCount = (): number => items.filter((n) => !n.read).length;
export function onNotices(fn: () => void): () => void { subs.add(fn); return () => subs.delete(fn); }
export function markAllRead(): void { items.forEach((n) => (n.read = true)); changed(); }
export function markRead(id: string): void { const n = items.find((x) => x.id === id); if (n && !n.read) { n.read = true; changed(); } }
export function clearAll(): void { items = []; changed(); }

export function push(n: { kind: Kind; icon: string; title: string; text?: string; href?: string; key?: string; plural?: (count: number) => string }): void {
  const now = Date.now() / 1000;
  const prev = n.key ? items.find((x) => x.key === n.key && !x.read && now - x.ts < 300) : undefined;
  if (prev) {  // many similar events in a row become one entry with a count
    prev.count += 1;
    prev.ts = now;
    if (n.plural) prev.title = n.plural(prev.count);
    prev.text = n.text ?? prev.text;
    items = [prev, ...items.filter((x) => x !== prev)];
  } else {
    items = [{ id: `${Date.now()}-${Math.random().toString(36).slice(2, 7)}`, ts: now, kind: n.kind, icon: n.icon, title: n.title, text: n.text ?? "", href: n.href, read: false, key: n.key, count: 1 }, ...items].slice(0, MAX);
  }
  changed();
}

// ------------------------------------------------------------------ sources
/** Listens to the live feed and to status changes. Returns a function that stops listening. */
export function startNotifications(getStatus: () => Status | null): () => void {
  const offs: (() => void)[] = [];
  const live = () => getStatus()?.hub.mode === "live";

  offs.push(feed.on("mod_pending", (e) => {
    if (e.data?.merged) return;
    push({ kind: "warn", icon: "inbox", key: "pending", title: "Approval needed", text: `${e.data?.author ?? "Someone"}: ${e.data?.action ?? "action"}${e.data?.score ? ` (score ${e.data.score})` : ""}`, href: "#/moderation",
      plural: (c) => `${c} approval requests` });
  }));
  offs.push(feed.on("mod_resolved", (e) => {
    if (e.data?.status === "failed") push({ kind: "bad", icon: "alert", title: "Moderation action failed", text: `${e.data?.action ?? "Action"} for ${e.data?.author ?? "a chatter"} did not go through.`, href: "#/moderation" });
  }));
  offs.push(feed.on("mod_expired", (e) => {
    const n = Number(e.data?.count ?? 1);
    push({ kind: "warn", icon: "clock", title: "Approval requests expired", text: `${n} request${n === 1 ? "" : "s"} timed out without a decision.`, href: "#/moderation" });
  }));
  offs.push(feed.on("stream", (e) => {
    if (!live()) return;
    push(e.data?.live ? { kind: "ok", icon: "radio", title: "Stream is live", text: e.data?.title || "The bot is attached to the chat.", href: "#/desk" } : { kind: "info", icon: "power", title: "Stream ended", text: "The bot is waiting for the next stream.", href: "#/desk" });
  }));
  offs.push(feed.on("mode", (e) => {
    push({ kind: "info", icon: e.data?.mode === "live" ? "radio" : "flask", title: e.data?.mode === "live" ? "Switched to Live" : "Switched to Demo", text: e.data?.mode === "live" ? "Real YouTube chat." : "Simulated chat. Nothing is sent.", key: "mode" });
  }));
  offs.push(feed.on("reminder", (e) => push({ kind: "ok", icon: "bell", title: "Reminder", text: String(e.data?.text ?? ""), href: "#/notebook" })));
  offs.push(feed.on("timer_done", (e) => push({ kind: "info", icon: "timer", title: "Timer finished", text: `"${e.data?.name ?? "A timer"}" posted its last message and switched itself off.`, href: "#/commands?tab=timers" })));

  // problems that show up in the status rather than as events
  let prev: Status | null = null;
  let quotaDay = "";
  let quotaLevel = 0;
  offs.push(onStatus((s) => {
    if (prev) {
      if (s.youtube.last_error && s.youtube.last_error !== prev.youtube.last_error) push({ kind: "bad", icon: "youtube", title: "YouTube problem", text: s.youtube.last_error, href: "#/setup", key: "yt-error" });
      if (s.youtube.last_action_error && s.youtube.last_action_error !== prev.youtube.last_action_error) push({ kind: "bad", icon: "ban", title: "YouTube refused an action", text: s.youtube.last_action_error, href: "#/setup" });
      if (s.telegram.last_error && s.telegram.last_error !== prev.telegram.last_error) push({ kind: "bad", icon: "telegram", title: "Telegram problem", text: s.telegram.last_error, href: "#/setup", key: "tg-error" });
      if (prev.youtube.connected && !s.youtube.connected) push({ kind: "warn", icon: "plug", title: "YouTube disconnected", text: "Reconnect your Google account to keep moderating.", href: "#/setup" });
    }
    const q = s.youtube.quota;
    if (q.day !== quotaDay) { quotaDay = q.day; quotaLevel = Math.floor(q.fraction * 100) >= 90 ? 90 : Math.floor(q.fraction * 100) >= 75 ? 75 : 0; }
    else if (s.hub.mode === "live") {
      const lvl = q.fraction >= 0.9 ? 90 : q.fraction >= 0.75 ? 75 : 0;
      if (lvl > quotaLevel) { quotaLevel = lvl; push({ kind: lvl >= 90 ? "bad" : "warn", icon: "gauge", title: `YouTube quota at ${lvl}%`, text: `${q.used} of ${q.daily} units used today.`, href: "#/setup" }); }
    }
    prev = s;
  }));
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
  const list = h("div", { class: "notice-list" });
  const filter = h("div", { class: "seg-control", role: "group", "aria-label": "Show" },
    [["All", false], ["Unread", true]].map(([l, v]) => h("button", { type: "button", "aria-pressed": String(onlyUnread === v), onclick: (e: Event) => { onlyUnread = v as boolean; Array.from((e.currentTarget as HTMLElement).parentElement!.children).forEach((b, i) => b.setAttribute("aria-pressed", String((i === 1) === onlyUnread))); draw(); } }, String(l))));
  const readAll = h("button", { class: "btn small ghost", type: "button", onclick: () => markAllRead() }, icon("check", 15), "Read all");
  const clear = h("button", { class: "btn small ghost", type: "button", onclick: () => clearAll() }, icon("trash", 15), "Clear");
  function draw(): void {
    const shown = items.filter((n) => !onlyUnread || !n.read);
    readAll.disabled = unreadCount() === 0;
    clear.disabled = items.length === 0;
    mount(list, shown.length ? shown.map((n) => {
      const open = () => { markRead(n.id); if (n.href) { close(); location.hash = n.href; } };
      return h("button", { class: `notice ${n.kind}${n.read ? "" : " unread"}`, type: "button", onclick: open },
        h("span", { class: "notice-ico" }, icon(n.icon, 18)),
        h("span", { class: "notice-body" }, h("strong", null, n.title), n.text ? h("span", { class: "small muted" }, n.text) : null, h("span", { class: "small muted" }, ago(n.ts))),
        n.read ? null : h("i", { class: "notice-dot", "aria-label": "Unread" }));
    }) : h("div", { class: "empty" }, icon("checkCircle", 30), h("span", null, onlyUnread ? "No unread notifications." : "You are all caught up. Events like stream start, reminders and problems appear here.")));
  }
  draw();
  const off = onNotices(draw);
  const el = h("div", { class: "notice-panel" }, h("div", { class: "notice-tools" }, filter, h("span", { class: "tb-spacer" }), readAll, clear), list);
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
