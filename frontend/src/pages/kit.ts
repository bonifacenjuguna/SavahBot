/** 1.1.2 building blocks used by several pages: date-range filter, area switcher, tiles and the zoom-to-fill effect. */
import { h, mount, type Child } from "../dom.js";
import { icon } from "../icons.js";

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
  manage: { title: "Manage", items: [{ id: "notebook", title: "Notebook", icon: "notebook" }, { id: "community", title: "Community", icon: "users" }, { id: "insights", title: "Insights", icon: "chart" }, { id: "demo", title: "Demo", icon: "flask" }] },
  system: { title: "System", items: [{ id: "setup", title: "Setup", icon: "plug" }, { id: "settings", title: "Settings", icon: "sliders" }] },
};
export const areaOf = (pageId: string): string | null => Object.keys(AREAS).find((k) => AREAS[k].items.some((i) => i.id === pageId)) ?? null;

/** Switcher shown at the top of Manage and System pages so they feel like one place, with the same way around on every screen. */
export function areaNav(pageId: string): HTMLElement | null {
  const key = areaOf(pageId);
  if (!key) return null;
  const area = AREAS[key];
  return h("nav", { class: "area-nav", "aria-label": area.title },
    h("a", { class: "an-back", href: "#/more", "aria-label": "All sections" }, icon("grid", 16), h("span", null, "More")),
    h("div", { class: "an-items scroll-x" }, area.items.map((i) => h("a", { href: `#/${i.id}`, "aria-current": i.id === pageId ? "page" : undefined }, icon(i.icon, 16), i.title))));
}

// ------------------------------------------------------------------ small pieces
export function tile(opts: { icon: string; title: string; text?: string; href?: string; onclick?: () => void; meta?: Child; tone?: string; current?: boolean }): HTMLElement {
  const kids = [h("span", { class: "tile-ico" }, icon(opts.icon, 22)), h("span", { class: "tile-text" }, h("strong", null, opts.title), opts.text ? h("span", null, opts.text) : null), opts.meta ? h("span", { class: "tile-meta" }, opts.meta) : null, icon("chevronRight", 16, "tile-go")];
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
export interface Zoom { open(): void; close(): void; isOpen(): boolean; toggle(): void; destroy(): void }

/** Removes anything a zoom may have left behind (placeholder, dim layer, scroll lock). Safe to call at any time. */
export function resetZoomArtifacts(): void {
  document.querySelectorAll(".zoom-scrim, .zoom-hold").forEach((e) => e.remove());
  document.body.classList.remove("zoom-open");
  if (!document.querySelector(".sheet")) document.body.classList.remove("no-scroll");
}

type Box = { left: number; top: number; width: number; height: number };

/**
 * Makes `card` grow to fill the workspace and shrink back to where it sat.
 *
 * 1.1.3: the card is placed at its FINAL size straight away and only a clip-path window is animated, so the browser lays the card out once
 * instead of on every frame (animating width and height made big chats freeze phones). Every step is idempotent, a timer guarantees the
 * state can never get stuck, and a tap during the animation just finishes it, so nothing is left behind to block the page.
 */
export function zoomToFill(card: HTMLElement, hooks: { onOpen?: () => void; onClose?: () => void } = {}): Zoom {
  type State = "closed" | "opening" | "open" | "closing";
  let state: State = "closed";
  let hold: HTMLElement | null = null;
  let scrim: HTMLElement | null = null;
  let anim: Animation | null = null;
  let guard = 0;
  let frame = 0;
  const reduce = () => matchMedia("(prefers-reduced-motion: reduce)").matches;
  const MS = 320;
  const EASE = "cubic-bezier(0.2, 0.8, 0.2, 1)";
  const px = (n: number) => `${Math.round(n)}px`;
  const place = (r: Box) => { card.style.left = px(r.left); card.style.top = px(r.top); card.style.width = px(r.width); card.style.height = px(r.height); };

  /** Where the card ends up: right of the sidebar and under the top bar; the whole screen on a phone. */
  const target = (): Box => {
    if (matchMedia("(max-width: 719px)").matches) return { left: 0, top: 0, width: window.innerWidth, height: window.innerHeight };
    const stage = document.querySelector(".stage") as HTMLElement | null;
    const top = (document.querySelector(".topbar") as HTMLElement | null)?.getBoundingClientRect().bottom ?? 0;
    const left = stage?.getBoundingClientRect().left ?? 0;
    const gap = 10;
    return { left: left + gap, top: top + gap, width: window.innerWidth - left - gap * 2, height: window.innerHeight - top - gap * 2 };
  };
  /** A clip-path that shows only `small`, expressed inside `big`. */
  const windowOf = (small: DOMRect | Box, big: Box, radius = 12): string => {
    const t = Math.max(0, small.top - big.top), l = Math.max(0, small.left - big.left);
    const r = Math.max(0, big.left + big.width - (small.left + small.width)), b = Math.max(0, big.top + big.height - (small.top + small.height));
    return `inset(${px(t)} ${px(r)} ${px(b)} ${px(l)} round ${radius}px)`;
  };
  const FULL = "inset(0px 0px 0px 0px round 18px)";

  const settle = () => { window.clearTimeout(guard); anim = null; };
  const watchdog = (fn: () => void) => { window.clearTimeout(guard); guard = window.setTimeout(fn, MS + 250); };

  const cleanup = () => {
    settle();
    window.cancelAnimationFrame(frame);
    window.removeEventListener("resize", onResize);
    document.removeEventListener("keydown", onKey, true);
    card.classList.remove("zoomed", "zoom-on");
    card.style.left = card.style.top = card.style.width = card.style.height = card.style.clipPath = "";
    hold?.remove(); hold = null;
    scrim?.remove(); scrim = null;
    resetZoomArtifacts();
    state = "closed";
  };
  const onResize = () => { if (state === "open") { window.cancelAnimationFrame(frame); frame = window.requestAnimationFrame(() => place(target())); } };
  const onKey = (e: KeyboardEvent) => {
    if (e.key === "Escape" && state !== "closed" && !document.querySelector(".sheet, .popover, .palette")) { e.stopPropagation(); api.close(); }
  };

  const api: Zoom = {
    isOpen: () => state === "opening" || state === "open",
    toggle: () => (api.isOpen() ? api.close() : api.open()),
    open() {
      if (api.isOpen()) return;
      if (state === "closing") cleanup();                    // a tap during the closing animation finishes it, then opens again
      const from = card.getBoundingClientRect();
      state = "opening";
      hold = h("div", { class: "zoom-hold", "aria-hidden": "true", style: `height:${px(from.height)}` });
      card.before(hold);
      scrim = h("div", { class: "zoom-scrim" });
      scrim.addEventListener("click", () => api.close());
      document.body.appendChild(scrim);
      document.body.classList.add("no-scroll", "zoom-open");
      const to = target();
      card.classList.add("zoomed", "zoom-on");
      place(to);
      window.addEventListener("resize", onResize);
      document.addEventListener("keydown", onKey, true);
      frame = window.requestAnimationFrame(() => scrim?.classList.add("on"));
      const done = () => { if (state === "opening") { settle(); card.style.clipPath = ""; state = "open"; } };
      if (reduce() || typeof card.animate !== "function") done();
      else {
        card.style.clipPath = windowOf(from, to);
        anim = card.animate([{ clipPath: windowOf(from, to) }, { clipPath: FULL }], { duration: MS, easing: EASE });
        anim.onfinish = done;
        watchdog(done);
      }
      hooks.onOpen?.();
    },
    close() {
      if (!api.isOpen()) return;
      if (anim) anim.cancel();
      settle();
      state = "closing";
      scrim?.classList.remove("on");
      const back = hold?.getBoundingClientRect();
      const big = card.getBoundingClientRect();
      hooks.onClose?.();
      if (reduce() || !back || typeof card.animate !== "function") { cleanup(); return; }
      anim = card.animate([{ clipPath: FULL }, { clipPath: windowOf(back, big) }], { duration: MS, easing: EASE, fill: "forwards" });
      const done = () => {
        if (state !== "closing") return;
        cleanup();
        card.animate([{ opacity: 0.4 }, { opacity: 1 }], { duration: 160, easing: "ease-out" });   // hides the swap from the zoomed layout to the card layout
      };
      anim.onfinish = done;
      watchdog(done);
    },
    destroy() { if (state !== "closed") cleanup(); },
  };
  return api;
}
