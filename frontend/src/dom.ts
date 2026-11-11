import { icon } from "./icons.js";
import { toastMode, toastSecs } from "./appearance.js";

export type Child = Node | string | number | null | undefined | false | Child[];
type Props = Record<string, unknown> | null;

/** Tiny element builder: h("button", { class: "btn", onclick: fn }, "Save"). Text is always set as text, never HTML. */
export function h<K extends keyof HTMLElementTagNameMap>(tag: K, props?: Props, ...kids: Child[]): HTMLElementTagNameMap[K] {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(props ?? {})) {
    if (v === undefined || v === null || v === false) continue;
    if (k === "class") el.className = String(v);
    else if (k.startsWith("on") && typeof v === "function") el.addEventListener(k.slice(2).toLowerCase(), v as EventListener);
    else if (k in el && k !== "list" && k !== "form") (el as unknown as Record<string, unknown>)[k] = v;
    else el.setAttribute(k, v === true ? "" : String(v));
  }
  append(el, kids);
  return el;
}

export function append(parent: Node, kids: Child[]): void {
  for (const kid of kids) {
    if (kid === null || kid === undefined || kid === false) continue;
    if (Array.isArray(kid)) append(parent, kid);
    else parent.appendChild(kid instanceof Node ? kid : document.createTextNode(String(kid)));
  }
}

export function clear(el: Element): void {
  while (el.firstChild) el.removeChild(el.firstChild);
}

export function mount(el: Element, ...kids: Child[]): void {
  clear(el);
  append(el, kids);
}

let toastHost: HTMLElement | null = null;
function host(): HTMLElement {
  if (!toastHost) {
    toastHost = h("div", { class: "toasts", role: "status", "aria-live": "polite" });
    document.body.appendChild(toastHost);
  }
  return toastHost;
}

// ---- pop-up notices (1.3.3) ----------------------------------------------------------------------------------------
// Settings → Appearance decides whether they show, where (top or bottom) and for how long. Each one can be swiped left or right
// (or tapped) to send it away, and the same message arriving again folds into one toast with a counter instead of stacking up.
const timers = new WeakMap<HTMLElement, number>();
const byKey = new Map<string, HTMLElement>();

function leave(t: HTMLElement, dir = 0): void {
  if (!t.isConnected || t.dataset.leaving) return;
  t.dataset.leaving = "1";
  window.clearTimeout(timers.get(t));
  const key = t.dataset.key;
  if (key && byKey.get(key) === t) byKey.delete(key);
  t.style.transition = "transform .18s ease, opacity .18s ease";
  t.style.opacity = "0";
  t.style.transform = dir ? `translateX(${dir * 110}%)` : "scale(.97)";
  window.setTimeout(() => t.remove(), 190);
}
function arm(t: HTMLElement, ms: number): void {
  window.clearTimeout(timers.get(t));
  timers.set(t, window.setTimeout(() => leave(t), ms));
}

/** Swipe sideways past a third of the width (or flick) to dismiss; a short drag springs back; a plain tap dismisses too. */
function swipeable(t: HTMLElement, ms: number): void {
  let id = -1, x0 = 0, y0 = 0, dx = 0, at = 0, drag = false;
  const reset = () => { t.style.transition = "transform .18s ease, opacity .18s ease"; t.style.transform = ""; t.style.opacity = ""; };
  t.addEventListener("pointerdown", (e) => {
    if ((e.target as HTMLElement).closest("button")) return;       // the Undo button is a button, not part of the gesture
    id = e.pointerId; x0 = e.clientX; y0 = e.clientY; dx = 0; at = performance.now(); drag = false;
    window.clearTimeout(timers.get(t));                           // keeps the toast while a finger is on it
  });
  t.addEventListener("pointermove", (e) => {
    if (e.pointerId !== id) return;
    dx = e.clientX - x0;
    if (!drag && Math.abs(dx) > 8 && Math.abs(dx) > Math.abs(e.clientY - y0)) { drag = true; try { t.setPointerCapture(id); } catch { /* not capturable */ } t.style.transition = "none"; }
    if (drag) { t.style.transform = `translateX(${dx}px)`; t.style.opacity = String(Math.max(0.2, 1 - Math.abs(dx) / (t.offsetWidth * 0.9))); }
  });
  const end = (e: PointerEvent) => {
    if (e.pointerId !== id) return;
    id = -1;
    const speed = Math.abs(dx) / Math.max(1, performance.now() - at);        // px per ms
    if (drag && (Math.abs(dx) > t.offsetWidth * 0.33 || (Math.abs(dx) > 40 && speed > 0.5))) { leave(t, dx < 0 ? -1 : 1); return; }
    if (drag) reset();
    else if (e.type === "pointerup" && Math.abs(dx) < 6 && !t.classList.contains("has-action") && !(e.target as HTMLElement).closest("button")) { leave(t); return; }
    arm(t, ms);
  };
  t.addEventListener("pointerup", end);
  t.addEventListener("pointercancel", (e) => { if (e.pointerId === id) { drag = false; reset(); end(e); } });
}

function present(message: string, kind: "ok" | "error", action?: { label: string; run: () => void | Promise<unknown> }, actionMs?: number): void {
  const mode = toastMode();
  if (mode === "off" || (mode === "errors" && kind !== "error" && !action)) return;
  const secs = toastSecs();
  const ms = action ? Math.max(actionMs ?? 7000, secs * 1000) : kind === "error" ? Math.max(6000, secs * 2000) : secs * 1000;     // errors stay twice as long as notices
  const key = action ? "" : `${kind}:${message}`;
  const prev = key ? byKey.get(key) : undefined;
  if (prev && prev.isConnected && !prev.dataset.leaving) {          // the same message again: count it instead of adding a copy
    const n = Number(prev.dataset.n || "1") + 1;
    prev.dataset.n = String(n);
    let badge = prev.querySelector(".toast-n");
    if (!badge) { badge = h("span", { class: "toast-n" }); prev.appendChild(badge); }
    badge.textContent = `×${n}`;
    arm(prev, ms);
    return;
  }
  const t = h("div", { class: `toast ${kind}${action ? " has-action" : ""}` }, icon(kind === "error" ? "alert" : "check", 18), h("span", { class: "grow" }, message));
  if (action) {
    const b = h("button", { class: "toast-act", type: "button" }, action.label);
    b.addEventListener("click", () => {
      b.disabled = true;
      Promise.resolve().then(action.run).catch((e: unknown) => toast(e instanceof Error ? e.message : String(e), "error")).finally(() => leave(t));
    });
    t.appendChild(b);
  } else { t.dataset.key = key; byKey.set(key, t); }
  const box = host();
  box.appendChild(t);
  while (box.childElementCount > 4) { const old = box.firstElementChild as HTMLElement; leave(old); box.removeChild(old); }
  swipeable(t, ms);
  arm(t, ms);
}

export function toast(message: string, kind: "ok" | "error" = "ok"): void { present(message, kind); }

/** A toast with one button, e.g. "Note deleted" with Undo. It stays a little longer so there is time to tap it. */
export function toastAction(message: string, label: string, run: () => void | Promise<unknown>, ms = 7000): void { present(message, "ok", { label, run }, ms); }

export function clock(ts: number): string {
  return new Date(ts * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

export function dateTime(ts: number): string {
  return new Date(ts * 1000).toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

export function ago(ts: number | null | undefined): string {
  if (!ts) return "never";
  const s = Math.max(0, Date.now() / 1000 - ts);
  if (s < 5) return "just now";
  if (s < 60) return `${Math.floor(s)}s ago`;
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86400)}d ago`;
}

export function inUntil(ts: number): string {
  const s = ts - Date.now() / 1000;
  if (s < 0) return "due now";
  if (s < 90) return `in ${Math.ceil(s)}s`;
  if (s < 5400) return `in ${Math.round(s / 60)}m`;
  if (s < 172800) return `in ${Math.round(s / 3600)}h`;
  return `in ${Math.round(s / 86400)}d`;
}

export function duration(seconds: number): string {
  if (seconds < 60) return `${seconds}s`;
  if (seconds < 3600) return `${Math.round(seconds / 60)}m`;
  if (seconds < 86400) return `${(seconds / 3600).toFixed(seconds % 3600 ? 1 : 0)}h`;
  return `${Math.round(seconds / 86400)}d`;
}

export function debounce<A extends unknown[]>(fn: (...a: A) => void, ms: number): (...a: A) => void {
  let t: number | undefined;
  return (...a: A) => {
    window.clearTimeout(t);
    t = window.setTimeout(() => fn(...a), ms);
  };
}

/** Runs an async action on a button: disables it while pending and reports failures as a toast. */
export function busy(btn: HTMLButtonElement, action: () => Promise<unknown>, okMessage?: string): void {
  btn.disabled = true;
  action()
    .then(() => okMessage && toast(okMessage))
    .catch((e: unknown) => toast(e instanceof Error ? e.message : String(e), "error"))
    .finally(() => (btn.disabled = false));
}

export function copyButton(text: string, label = "Copy"): HTMLButtonElement {
  const b = h("button", { class: "btn small ghost", type: "button" }, icon("copy", 15), label);
  b.addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(text);
      toast("Copied");
    } catch {
      toast("Your browser blocked copying. Select the text and copy it by hand.", "error");
    }
  });
  return b;
}

/** Button that holds an icon and (optionally) a text label. */
export function iconButton(name: string, label: string, onclick: (e: Event) => void, cls = "btn small ghost", showLabel = true): HTMLButtonElement {
  return h("button", { class: cls, type: "button", onclick, "aria-label": label, title: label }, icon(name, 16), showLabel ? h("span", null, label) : null);
}

let openSheets = 0;

/** Modal panel: bottom sheet on phones, centred dialog on larger screens. Esc and the backdrop close it. */
/**
 * Pull a sheet down by its grip bar or its title row (or by the content when it is scrolled to the top) and let go: past a third of the way,
 * or with a quick flick, it closes; otherwise it springs back. The X button and Escape still work. Touch only, so a mouse or keyboard is unaffected.
 */
function enableDragToClose(panel: HTMLElement, overlay: HTMLElement, close: () => void): void {
  const body = panel.querySelector(".sheet-body") as HTMLElement;
  const reduced = typeof matchMedia === "function" && matchMedia("(prefers-reduced-motion: reduce)").matches;
  let y0 = 0, dy = 0, t0 = 0, active = false, armed = false;
  const start = (e: TouchEvent) => {
    if (e.touches.length !== 1 || (e.target as HTMLElement).closest("button, a, input, select, textarea")) return;
    const inBody = (e.target as HTMLElement).closest(".sheet-body") !== null;
    if (inBody && body.scrollTop > 0) return;
    armed = true; active = false; y0 = e.touches[0].clientY; dy = 0; t0 = e.timeStamp;
    panel.dataset.dragFromBody = inBody ? "1" : "";
  };
  const move = (e: TouchEvent) => {
    if (!armed) return;
    dy = e.touches[0].clientY - y0;
    if (!active) {
      if (dy > 8 && (panel.dataset.dragFromBody !== "1" || body.scrollTop === 0)) { active = true; panel.style.transition = "none"; }
      else if (dy < -8) { armed = false; return; }
      else return;
    }
    e.preventDefault();                                     // the page behind and the sheet's own scroll stay still while it is being pulled
    panel.style.transform = `translateY(${Math.max(0, dy)}px)`;
    overlay.style.setProperty("--drag", String(Math.min(1, Math.max(0, dy) / 400)));
  };
  const end = (e: TouchEvent) => {
    if (!armed) return;
    armed = false;
    if (!active) return;
    active = false;
    const fast = dy / Math.max(1, e.timeStamp - t0) > 0.6;
    panel.style.transition = reduced ? "none" : "transform 0.18s ease-out";
    if (dy > panel.offsetHeight / 3 || (fast && dy > 40)) {
      panel.style.transform = "translateY(105%)";
      window.setTimeout(close, reduced ? 0 : 170);
    } else {
      panel.style.transform = "";
      overlay.style.removeProperty("--drag");
    }
  };
  panel.addEventListener("touchstart", start, { passive: true });
  panel.addEventListener("touchmove", move, { passive: false });
  panel.addEventListener("touchend", end, { passive: true });
  panel.addEventListener("touchcancel", end, { passive: true });
}

export function sheet(title: string, body: Node, onClose?: () => void): { close: () => void } {
  const previous = document.activeElement as HTMLElement | null;
  const overlay = h("div", { class: "overlay" });
  const close = () => {
    if (!overlay.isConnected) return;
    overlay.remove();
    document.removeEventListener("keydown", onKey, true);
    if (--openSheets <= 0) { openSheets = 0; document.body.classList.remove("no-scroll"); }
    previous?.focus?.();
    onClose?.();
  };
  const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") { e.stopPropagation(); close(); } };
  const panel = h("div", { class: "sheet", role: "dialog", "aria-modal": "true", "aria-label": title, tabindex: -1 },
    h("div", { class: "sheet-grip", "aria-hidden": "true" }),
    h("header", { class: "sheet-head" }, h("h2", null, title), h("button", { class: "icon-btn", type: "button", "aria-label": "Close", onclick: close }, icon("x", 20))),
    h("div", { class: "sheet-body" }, body));
  overlay.appendChild(panel);
  enableDragToClose(panel, overlay, close);
  overlay.addEventListener("pointerdown", (e) => { if (e.target === overlay) close(); });
  document.body.appendChild(overlay);
  document.body.classList.add("no-scroll");
  openSheets++;
  document.addEventListener("keydown", onKey, true);
  // Always open at the top. Only text fields get focus, and not on touch screens (it would pop the keyboard and scroll the sheet).
  const body_ = panel.querySelector(".sheet-body") as HTMLElement;
  body_.scrollTop = 0;
  const first = panel.querySelector("input, textarea, select") as HTMLElement | null;
  const touch = typeof matchMedia === "function" && matchMedia("(pointer: coarse)").matches;
  (first && !touch ? first : panel).focus({ preventScroll: true });
  body_.scrollTop = 0;
  return { close };
}

/** Downloads rows as a CSV file (client side only). */
export function downloadCsv(filename: string, rows: (string | number | null | undefined)[][]): void {
  const esc = (v: string | number | null | undefined) => {
    let t = v === null || v === undefined ? "" : String(v);
    if (/^[=+\-@]/.test(t)) t = "'" + t; // stop spreadsheet formula injection
    return /[",\n]/.test(t) ? `"${t.replace(/"/g, '""')}"` : t;
  };
  const blob = new Blob([rows.map((r) => r.map(esc).join(",")).join("\n")], { type: "text/csv;charset=utf-8" });
  const a = h("a", { href: URL.createObjectURL(blob), download: filename });
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 2000);
}
