import { icon } from "./icons.js";

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
export function toast(message: string, kind: "ok" | "error" = "ok"): void {
  if (!toastHost) {
    toastHost = h("div", { class: "toasts", role: "status", "aria-live": "polite" });
    document.body.appendChild(toastHost);
  }
  const t = h("div", { class: `toast ${kind}` }, icon(kind === "error" ? "alert" : "check", 18), h("span", { class: "grow" }, message));
  toastHost.appendChild(t);
  while (toastHost.childElementCount > 4) toastHost.firstElementChild?.remove();
  setTimeout(() => t.remove(), kind === "error" ? 6000 : 3000);
}

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
  const panel = h("div", { class: "sheet", role: "dialog", "aria-modal": "true", "aria-label": title },
    h("div", { class: "sheet-grip", "aria-hidden": "true" }),
    h("header", { class: "sheet-head" }, h("h2", null, title), h("button", { class: "icon-btn", type: "button", "aria-label": "Close", onclick: close }, icon("x", 20))),
    h("div", { class: "sheet-body" }, body));
  overlay.appendChild(panel);
  overlay.addEventListener("pointerdown", (e) => { if (e.target === overlay) close(); });
  document.body.appendChild(overlay);
  document.body.classList.add("no-scroll");
  openSheets++;
  document.addEventListener("keydown", onKey, true);
  (panel.querySelector("input, textarea, select, button.btn") as HTMLElement | null)?.focus();
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
