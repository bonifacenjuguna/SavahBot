/** 1.1.4 building blocks used by several pages: date-range filter, area switcher, tiles and the zoom-to-fill effect. */
import { h, mount, sheet, type Child } from "../dom.js";
import { icon } from "../icons.js";
import { tabRail } from "../nav.js";

// ------------------------------------------------------------------ date range
export interface RangeValue {
  /** Epoch seconds, inclusive. Undefined means no lower limit. */
  since?: number;
  /** Epoch seconds, exclusive. Undefined means no upper limit. */
  until?: number;
  /** Short words for headings and empty states, e.g. "Today" or "3 Nov to 5 Nov". */
  label: string;
  /** True when a limit is set. */
  active: boolean;
}

type Preset = "any" | "today" | "yesterday" | "7d" | "30d" | "custom";
const PRESET_LABEL: Record<Preset, string> = { any: "Any time", today: "Today", yesterday: "Yesterday", "7d": "7 days", "30d": "30 days", custom: "Custom" };

const startOfDay = (d: Date): number => new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime() / 1000;
const dayInput = (d: Date): string => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
const parseDay = (v: string): Date | null => { const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(v); return m ? new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3])) : null; };
const short = (d: Date): string => d.toLocaleDateString([], { month: "short", day: "numeric" });

/** Computes the range for a preset, in the browser's own timezone. Exported so it can be reasoned about on its own. */
export function presetRange(p: Preset, now: Date = new Date()): RangeValue {
  const today = startOfDay(now);
  const day = 86400;
  switch (p) {
    case "today": return { since: today, label: "Today", active: true };
    case "yesterday": return { since: today - day, until: today, label: "Yesterday", active: true };
    case "7d": return { since: today - 6 * day, label: "Last 7 days", active: true };
    case "30d": return { since: today - 29 * day, label: "Last 30 days", active: true };
    default: return { label: "", active: false };
  }
}

/** A range from two day strings. `to` is inclusive (the whole day counts); returns null if either is missing or from is after to. */
export function customRange(from: string, to: string): RangeValue | null {
  const a = parseDay(from), b = parseDay(to);
  if (!a && !b) return null;
  if (a && b && a > b) return null;
  const since = a ? startOfDay(a) : undefined;
  const until = b ? startOfDay(new Date(b.getFullYear(), b.getMonth(), b.getDate() + 1)) : undefined;
  const label = a && b ? (from === to ? short(a) : `${short(a)} to ${short(b)}`) : a ? `From ${short(a)}` : `Until ${short(b!)}`;
  return { since, until, label, active: true };
}

export const rangeQuery = (r: RangeValue): string => `${r.since !== undefined ? `&since=${Math.floor(r.since)}` : ""}${r.until !== undefined ? `&until=${Math.floor(r.until)}` : ""}`;

export interface DateRangeControl { el: HTMLElement; value(): RangeValue; reset(): void }

/** Preset chips plus a custom From/To. Calls `onChange` only with a valid range. */
export function dateRange(opts: { anyLabel?: string; presets?: Preset[]; label?: string }, onChange: (v: RangeValue) => void): DateRangeControl {
  const presets = opts.presets ?? ["any", "today", "yesterday", "7d", "30d", "custom"];
  let current: Preset = "any";
  let value: RangeValue = { label: "", active: false };
  const today = dayInput(new Date());
  const from = h("input", { type: "date", max: today, "aria-label": "From date" });
  const to = h("input", { type: "date", max: today, "aria-label": "To date" });
  const note = h("p", { class: "small", role: "alert", style: "color:var(--bad)" });
  const custom = h("div", { class: "dr-custom", hidden: true }, h("label", { class: "field" }, "From", from), h("label", { class: "field" }, "To", to), note);
  const chips = presets.map((p) => h("button", { type: "button", class: "dr-chip", "aria-pressed": String(p === current), "data-p": p }, p === "any" ? opts.anyLabel ?? PRESET_LABEL.any : PRESET_LABEL[p]));
  const sync = () => chips.forEach((b) => b.setAttribute("aria-pressed", String(b.getAttribute("data-p") === current)));
  const apply = () => {
    note.textContent = "";
    if (current === "custom") {
      const r = customRange(from.value, to.value);
      if (from.value && to.value && !r) { note.textContent = "The start date is after the end date."; return; }
      if (!r) return;           // nothing picked yet: wait
      value = r;
    } else value = presetRange(current);
    onChange(value);
  };
  chips.forEach((b) => b.addEventListener("click", () => {
    current = b.getAttribute("data-p") as Preset;
    custom.hidden = current !== "custom";
    sync();
    if (current === "custom") { from.focus({ preventScroll: true }); apply(); } else apply();
  }));
  from.addEventListener("change", apply);
  to.addEventListener("change", apply);
  const el = h("div", { class: "daterange", role: "group", "aria-label": opts.label ?? "Date range" },
    h("div", { class: "dr-chips scroll-x" }, icon("calendar", 15), chips), custom);
  return {
    el,
    value: () => value,
    reset: () => { current = "any"; value = { label: "", active: false }; from.value = ""; to.value = ""; custom.hidden = true; note.textContent = ""; sync(); },
  };
}

// ------------------------------------------------------------------ areas (Manage and System)
export interface AreaItem { id: string; title: string; icon: string }
export const AREAS: Record<string, { title: string; items: AreaItem[] }> = {
  manage: { title: "Manage", items: [{ id: "notebook", title: "Notebook", icon: "notebook" }, { id: "community", title: "Community", icon: "users" }, { id: "bans", title: "Bans", icon: "ban" }, { id: "security", title: "Security", icon: "shield" }, { id: "notifications", title: "Notifications", icon: "bell" }, { id: "weather", title: "Weather", icon: "cloudSun" }, { id: "backup", title: "Backup", icon: "database" }, { id: "insights", title: "Insights", icon: "chart" }, { id: "demo", title: "Demo", icon: "flask" }] },
  system: { title: "System", items: [{ id: "setup", title: "Setup", icon: "plug" }, { id: "settings", title: "Settings", icon: "sliders" }] },
};
export const areaOf = (pageId: string): string | null => Object.keys(AREAS).find((k) => AREAS[k].items.some((i) => i.id === pageId)) ?? null;

/** Switcher shown at the top of Manage and System pages so they feel like one place, with the same way around on every screen. */
export function areaNav(pageId: string): HTMLElement | null {
  const key = areaOf(pageId);
  if (!key) return null;
  const area = AREAS[key];
  const items = h("div", { class: "an-items scroll-x" }, area.items.map((i) => h("a", { href: `/${i.id}`, "aria-current": i.id === pageId ? "page" : undefined }, icon(i.icon, 16), i.title)));
  tabRail(items, `area:${key}`);     // the strip opens with this page's tab in the middle, every time
  const all = h("button", { class: "an-all", type: "button", "aria-label": "All pages in this section", title: "All pages", onclick: () => {
    const box = sheet(area.title, h("div", { class: "tile-grid" }, area.items.map((i) => tile({ icon: i.icon, title: i.title, href: `/${i.id}`, current: i.id === pageId }))));
    // a followed tile changes the address, which redraws the page: close the sheet with it
    document.querySelector(".sheet")?.addEventListener("click", (e) => { if ((e.target as HTMLElement).closest("a.tile")) box.close(); });
  } }, icon("dots", 18));
  return h("nav", { class: "area-nav", "aria-label": area.title },
    h("a", { class: "an-back", href: "/more", "aria-label": "All sections" }, icon("menu", 16), h("span", null, "More")),
    h("div", { class: "an-wrap" }, items), all);
}

// ------------------------------------------------------------------ small pieces
export function tile(opts: { icon: string; title: string; text?: string; href?: string; onclick?: () => void; meta?: Child; tone?: string; current?: boolean }): HTMLElement {
  const kids = [h("span", { class: "tile-ico" }, icon(opts.icon, 22)), h("span", { class: "tile-text" }, h("strong", null, opts.title), opts.text ? h("span", null, opts.text) : null, opts.meta ? h("span", { class: "tile-meta" }, opts.meta) : null), icon("chevronRight", 16, "tile-go")];
  const cls = `tile${opts.tone ? " " + opts.tone : ""}`;
  return opts.href
    ? h("a", { class: cls, href: opts.href, "aria-current": opts.current ? "page" : undefined }, ...kids)
    : h("button", { class: cls, type: "button", onclick: opts.onclick }, ...kids);
}

export function stat(label: string, value: string, sub?: string): HTMLElement {
  return h("div", { class: "mini-stat" }, h("span", { class: "ms-v" }, value), h("span", { class: "ms-l" }, label), sub ? h("span", { class: "ms-s" }, sub) : null);
}

export function mountInto(el: Element, ...kids: Child[]): void { mount(el, ...kids); }

// ------------------------------------------------------------------ zoom to fill
export interface Zoom { open(): void; close(): void; isOpen(): boolean; toggle(): void }

/**
 * Lifts `card` out of the page (a placeholder keeps the page from jumping) and lets it fill the workspace; the whole screen on a phone.
 * 1.1.3: the card is placed once, with no size or position animation. Only opacity and transform animate, which the phone's GPU handles
 * without re-laying-out the live chat on every frame, so it no longer stutters or freezes. There is no scrim blur, and no timer can race
 * with a quick second tap: open and close always leave a clean state. Esc closes it; the page behind is locked while it is open.
 */
export function zoomToFill(card: HTMLElement, hooks: { onOpen?: () => void; onClose?: () => void } = {}): Zoom {
  let open = false;
  let hold: HTMLElement | null = null;
  let scrim: HTMLElement | null = null;
  let timer = 0;
  const px = (n: number) => `${Math.round(n)}px`;
  /** Where the card goes. On a phone: the whole screen. On a computer: the whole window with an even margin all round, centred, so it is as big as it
   *  can be and sits in the middle of what you are looking at (the old version measured the area beside the side menu and drifted left of centre). */
  const place = () => {
    const phone = matchMedia("(max-width: 719px)").matches;
    if (phone) { card.style.left = "0"; card.style.top = "0"; card.style.width = "100%"; card.style.height = "100%"; return; }
    const vw = document.documentElement.clientWidth || window.innerWidth;      // clientWidth leaves out a scrollbar, innerWidth does not
    const margin = Math.max(12, Math.min(28, Math.round(vw * 0.016)));
    const width = Math.min(vw - margin * 2, 2000);
    card.style.left = px((vw - width) / 2);
    card.style.top = px(margin);
    card.style.width = px(width);
    card.style.height = px(window.innerHeight - margin * 2);
  };
  const onResize = () => { if (open) place(); };
  const onKey = (e: KeyboardEvent) => { if (e.key === "Escape" && open && !document.querySelector(".sheet, .popover, .palette")) { e.stopPropagation(); api.close(); } };
  /** Removes everything the zoom added. Safe to call at any time, any number of times. */
  const cleanup = () => {
    window.clearTimeout(timer);
    card.classList.remove("zoomed", "zoom-in", "zoom-out");
    card.style.left = card.style.top = card.style.width = card.style.height = "";
    hold?.remove(); hold = null;
    scrim?.remove(); scrim = null;
    document.body.classList.remove("zoom-open");
    if (!document.querySelector(".sheet")) document.body.classList.remove("no-scroll");
  };

  const api: Zoom = {
    isOpen: () => open,
    toggle: () => (open ? api.close() : api.open()),
    open() {
      if (open) return;
      cleanup();                          // finish a close that is still fading, so a quick re-tap never leaves leftovers
      open = true;
      hold = h("div", { class: "zoom-hold", "aria-hidden": "true", style: `height:${px(card.getBoundingClientRect().height)}` });
      card.before(hold);
      scrim = h("div", { class: "zoom-scrim" });
      scrim.addEventListener("click", () => api.close());
      document.body.appendChild(scrim);
      card.classList.add("zoomed", "zoom-in");
      document.body.classList.add("no-scroll", "zoom-open");      // the page scrollbar goes away here, so measure after it
      place();
      window.addEventListener("resize", onResize);
      document.addEventListener("keydown", onKey, true);
      try { hooks.onOpen?.(); } catch (err) { console.error(err); }
    },
    close() {
      if (!open) return;
      open = false;
      window.removeEventListener("resize", onResize);
      document.removeEventListener("keydown", onKey, true);
      try { hooks.onClose?.(); } catch (err) { console.error(err); }   // a hook problem must never leave the card stuck open
      const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
      if (reduce) { cleanup(); return; }
      card.classList.remove("zoom-in");
      card.classList.add("zoom-out");
      scrim?.classList.add("off");
      timer = window.setTimeout(cleanup, 200);
    },
  };
  return api;
}

// ------------------------------------------------------------------ quota reset clock
/** "5h 12m" or "42m" for a number of seconds. */
export function span(sec: number): string {
  const s = Math.max(0, Math.floor(sec));
  const hh = Math.floor(s / 3600), mm = Math.floor((s % 3600) / 60);
  return hh ? `${hh}h ${mm}m` : `${Math.max(1, mm)}m`;
}

/**
 * When YouTube's daily quota resets, in the owner's own timezone. YouTube resets at midnight Pacific Time, which moves with daylight
 * saving, so the backend sends the exact moment and the browser only has to show it: e.g. "11:00 AM" in Nairobi.
 */
export function resetClock(resetsAt: number | undefined, tz: string | undefined, now = Date.now() / 1000): { clock: string; place: string; left: string } | null {
  if (!resetsAt) return null;
  const zone = tz || undefined;
  let clock: string;
  try { clock = new Date(resetsAt * 1000).toLocaleTimeString([], { hour: "numeric", minute: "2-digit", timeZone: zone }); }
  catch { clock = new Date(resetsAt * 1000).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" }); }
  const place = (zone ?? "").split("/").pop()?.replace(/_/g, " ") || "your time";
  return { clock, place, left: span(resetsAt - now) };
}
