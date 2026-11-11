import { apiBase, del, get, getToken, patch } from "../api.js";
import { debounce, h, mount, sheet, toast } from "../dom.js";
import { icon } from "../icons.js";
import { empty } from "./shared.js";

/** One livestream, as the backend describes it (backend/app/sessions.py). */
export interface Stream {
  id: string; started: number; ended: number | null; title: string; label: string; video_id: string; platform: string; demo: boolean;
  messages: number; chatters: number; flagged: number; deleted: number; timeouts: number; bans: number; peak_per_min: number;
  top: { name: string; lines: number }[]; resumed: boolean; live: boolean; duration: number;
}

// ------------------------------------------------------------------ words for dates and lengths of time
const same = (a: Date, b: Date) => a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate();
const timeOf = (ts: number) => new Date(ts * 1000).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });

/** "Today", "Yesterday", or "Mon 9 Nov" (with the year when it is not this year). */
export function dayLabel(ts: number, now = new Date()): string {
  const d = new Date(ts * 1000);
  if (same(d, now)) return "Today";
  if (same(d, new Date(now.getFullYear(), now.getMonth(), now.getDate() - 1))) return "Yesterday";
  return d.toLocaleDateString([], { weekday: "short", day: "numeric", month: "short", ...(d.getFullYear() !== now.getFullYear() ? { year: "numeric" } : {}) });
}

/** "1h 15m", "42m", "35s". */
export function spanText(sec: number): string {
  const s = Math.max(0, Math.round(sec));
  if (s < 60) return `${s}s`;
  const hh = Math.floor(s / 3600), mm = Math.floor((s % 3600) / 60);
  return hh ? `${hh}h${mm ? ` ${mm}m` : ""}` : `${mm}m`;
}

/** "12:47 PM to 2:02 PM", or "from 12:47 PM" while it runs. A stream that crossed midnight says so. */
export function whenText(s: Pick<Stream, "started" | "ended">): string {
  const a = timeOf(s.started);
  if (s.ended === null) return `from ${a}`;
  const crossed = !same(new Date(s.started * 1000), new Date(s.ended * 1000));
  return `${a} to ${timeOf(s.ended)}${crossed ? ` (${dayLabel(s.ended)})` : ""}`;
}

export const streamName = (s: Pick<Stream, "label" | "title" | "demo">): string => s.label || s.title || (s.demo ? "Demo stream" : "Untitled stream");

const n = (v: number) => v.toLocaleString();
const stat = (ic: string, text: string, cls = "") => h("span", { class: `st-stat ${cls}` }, icon(ic, 13), text);

/** The small facts shown under a stream's name, in the same order everywhere. */
export function statRow(s: Stream): HTMLElement {
  return h("div", { class: "st-stats" },
    stat("message", `${n(s.messages)} line${s.messages === 1 ? "" : "s"}`),
    stat("users", `${n(s.chatters)} chatter${s.chatters === 1 ? "" : "s"}`),
    s.flagged ? stat("flag", `${n(s.flagged)} flagged`, "warn") : null,
    s.deleted + s.timeouts + s.bans ? stat("shield", `${n(s.deleted + s.timeouts + s.bans)} actions`) : null,
    s.peak_per_min ? stat("activity", `peak ${n(s.peak_per_min)}/min`) : null);
}

// ------------------------------------------------------------------ the history sheet
interface Opts {
  /** The stream running right now, if any. */
  current?: string | null;
  /** Read this stream's chat in the Desk. */
  open: (s: Stream) => void;
  /** Called after a stream was renamed or deleted, so the Desk can refresh its banner. */
  changed?: (s: Stream | null, id: string) => void;
}

async function download(path: string, filename: string): Promise<void> {
  const res = await fetch(apiBase() + path, { headers: { Authorization: `Bearer ${getToken()}` } });
  if (!res.ok) throw new Error(`Could not export (${res.status}).`);
  const blob = await res.blob();
  const a = h("a", { href: URL.createObjectURL(blob), download: filename });
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 2000);
}

/** A list of every past stream (newest first, grouped by day) with a detail page for each one: read the chat, rename, export, delete. */
export function openStreams(opts: Opts): { close: () => void } {
  const root = h("div", { class: "streams" });
  let box: { close: () => void } = { close: () => undefined };
  let query = "";
  let items: Stream[] = [];
  let total = 0;
  let current = opts.current ?? null;
  let loading = true;

  const row = (s: Stream): HTMLElement => {
    const live = s.id === current || s.live;
    return h("button", { type: "button", class: `st-row${live ? " live" : ""}`, onclick: () => detail(s), "aria-label": `${streamName(s)}, ${dayLabel(s.started)}` },
      h("span", { class: "st-ico", "aria-hidden": "true" }, icon(live ? "radio" : s.demo ? "flask" : "youtube", 18)),
      h("span", { class: "st-main" },
        h("span", { class: "st-top" }, h("strong", { class: "st-name" }, streamName(s)), live ? h("span", { class: "chip bad" }, "On air") : null, s.resumed ? h("span", { class: "chip", title: "The connection dropped and came back; it is still one stream." }, "Reconnected") : null),
        h("span", { class: "st-when" }, `${whenText(s)} · ${spanText(s.duration)}`),
        statRow(s)),
      icon("chevronRight", 16, "st-go"));
  };

  const list = () => {
    if (loading) { mount(listBox, h("p", { class: "muted", style: "padding:12px" }, "Loading…")); return; }
    if (!items.length) { mount(listBox, empty("history", query ? "No stream matches that." : "No streams yet. Each stream you go live with is saved here, with its own chat.")); return; }
    const groups: HTMLElement[] = [];
    let last = "";
    for (const s of items) {
      const d = dayLabel(s.started);
      if (d !== last) { groups.push(h("h3", { class: "st-day" }, d)); last = d; }
      groups.push(row(s));
    }
    if (items.length < total) groups.push(h("button", { class: "btn ghost st-more", type: "button", onclick: () => void load(true) }, `Show more (${total - items.length} older)`));
    mount(listBox, groups);
  };

  const load = async (more = false) => {
    try {
      const r = await get<{ items: Stream[]; total: number; current: string | null }>(`/api/streams?limit=30&offset=${more ? items.length : 0}&q=${encodeURIComponent(query)}`);
      items = more ? [...items, ...r.items] : r.items;
      total = r.total;
      current = r.current;
    } catch (e) { toast(e instanceof Error ? e.message : "Could not load streams", "error"); }
    loading = false;
    list();
  };

  const search = h("input", { type: "search", placeholder: "Search by title or name", "aria-label": "Search streams", maxLength: 80 });
  search.addEventListener("input", debounce(() => { query = search.value.trim().toLowerCase(); void load(); }, 250));
  const listBox = h("div", { class: "st-list" });
  const home = () => {
    mount(root, h("div", { class: "input-icon" }, icon("search", 16), search),
      h("p", { class: "muted small st-note" }, "Every stream is its own chat. Going live again never continues an old one, so each stream's lines, numbers and actions stay together here."),
      listBox);
    list();
  };

  // ----- one stream
  const detail = (s0: Stream) => {
    let s = s0;
    const paint = () => {
      const name = h("h3", { class: "st-title" }, streamName(s));
      const live = s.id === current || s.live;
      mount(root,
        h("button", { class: "btn small ghost st-back", type: "button", onclick: () => { home(); void load(); } }, icon("arrowLeft", 14), "All streams"),
        h("div", { class: "st-head" }, name, h("p", { class: "muted" }, `${dayLabel(s.started)} · ${whenText(s)}`),
          s.title && s.label && s.title !== s.label ? h("p", { class: "muted small" }, s.title) : null),
        h("div", { class: "st-grid" },
          tile("clock", spanText(s.duration), live ? "so far" : "on air"),
          tile("message", n(s.messages), "chat lines"),
          tile("users", n(s.chatters), "chatters"),
          tile("activity", s.peak_per_min ? `${n(s.peak_per_min)}/min` : "none", "busiest minute"),
          tile("flag", n(s.flagged), "flagged"),
          tile("shield", `${s.deleted} · ${s.timeouts} · ${s.bans}`, "deleted · timeouts · bans")),
        s.top.length ? h("div", { class: "st-top-list" }, h("h4", null, "Most active"), h("ol", null, s.top.map((t) => h("li", null, h("span", { class: "grow" }, t.name), h("span", { class: "muted" }, `${n(t.lines)} lines`))))) : null,
        s.resumed ? h("p", { class: "muted small" }, "The connection dropped and came back during this stream. It is kept as one stream.") : null,
        h("div", { class: "row wrap", style: "gap:8px" },
          h("button", { class: "btn primary", type: "button", onclick: () => { box.close(); opts.open(s); } }, icon("message", 16), live ? "Open in Desk" : "Read the chat"),
          h("button", { class: "btn", type: "button", onclick: () => void rename() }, icon("pencil", 16), "Rename"),
          h("button", { class: "btn", type: "button", onclick: () => void download(`/api/streams/${s.id}/export`, `savahbot-stream-${new Date(s.started * 1000).toISOString().slice(0, 10)}.txt`).then(() => toast("Exported")).catch((e) => toast(e.message, "error")) }, icon("download", 16), "Export"),
          live ? null : h("button", { class: "btn danger", type: "button", onclick: () => void remove() }, icon("trash", 16), "Delete")),
        h("p", { class: "muted small" }, "Chat lines are kept for the retention period set in Settings. The numbers above are kept for good."));
    };
    const tile = (ic: string, value: string, label: string) => h("div", { class: "st-tile" }, icon(ic, 16), h("strong", null, value), h("span", { class: "muted small" }, label));
    const rename = async () => {
      const v = window.prompt("Name this stream (leave empty to use its YouTube title)", s.label || s.title);
      if (v === null) return;
      try { const r = await patch<{ item: Stream }>(`/api/streams/${s.id}`, { label: v.trim() === s.title ? "" : v.trim() }); s = r.item; opts.changed?.(s, s.id); paint(); }
      catch (e) { toast(e instanceof Error ? e.message : "Could not rename", "error"); }
    };
    const remove = async () => {
      if (!window.confirm(`Delete "${streamName(s)}" and its ${n(s.messages)} saved chat lines? This cannot be undone.`)) return;
      try { await del(`/api/streams/${s.id}`); toast("Stream deleted"); opts.changed?.(null, s.id); home(); await load(); }
      catch (e) { toast(e instanceof Error ? e.message : "Could not delete", "error"); }
    };
    paint();
  };

  home();
  void load();
  box = sheet("Streams", root);
  return box;
}
