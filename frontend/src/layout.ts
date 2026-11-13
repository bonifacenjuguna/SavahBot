/** Drag and arrange cards (1.4.0).
 *
 * A page creates one `pageLayout("desk")`, puts its `button` in the page header, and calls `arrange([container, ...])` once its cards are on screen.
 * Every direct child of a container that carries a `data-card` id is a movable card. Cards can be moved inside their own container (snap-to-grid
 * reorder: the others slide out of the way, nothing overlaps).
 *
 * What is saved is only the ORDER of card ids, once for "desktop" (a keyboard and a wide screen) and once for "mobile" (phones and tablets), on the
 * server, so it follows you to every device. A card that is not in the saved order (a new one) goes to the end; an id that no longer exists is
 * ignored. A saved layout can therefore never hide a card.
 *
 * Ways in: the "Edit layout" button, or press and hold a card's title on a touch screen. Ways to move: drag the handle or the title, or focus the
 * handle and use the arrow keys. Ways out: Done (saves), Cancel (puts everything back), Reset (back to the default order, kept when you press Done).
 */
import { get, post } from "./api.js";
import { h, toast } from "./dom.js";
import { icon } from "./icons.js";
import { hasKeyboard } from "./ui.js";

export type LayoutKind = "desktop" | "mobile";
export type LayoutStore = Record<LayoutKind, Record<string, string[]>>;

export const LAYOUT_PAGES: { id: string; title: string }[] = [
  { id: "desk", title: "Desk" }, { id: "insights", title: "Insights" }, { id: "notifications", title: "Notifications" }, { id: "weather", title: "Weather" },
];

// ------------------------------------------------------------------ the saved layouts (shared by every page)
const blank = (): LayoutStore => ({ desktop: {}, mobile: {} });
let store: LayoutStore = blank();
let loaded = false;
let inflight: Promise<void> | null = null;

/** Phones and tablets share the "mobile" layout. The same test the keyboard shortcuts use. */
export const layoutKind = (): LayoutKind => (hasKeyboard() ? "desktop" : "mobile");

function clean(raw: unknown): LayoutStore {
  const out = blank();
  if (raw && typeof raw === "object") {
    for (const kind of ["desktop", "mobile"] as const) {
      const part = (raw as Record<string, unknown>)[kind];
      if (!part || typeof part !== "object") continue;
      for (const [page, order] of Object.entries(part as Record<string, unknown>)) {
        if (Array.isArray(order)) out[kind][page] = order.filter((x): x is string => typeof x === "string");
      }
    }
  }
  return out;
}

/** Fetches the layouts once (the cache is reused until `force`). Never throws: with no answer, pages simply show their default order. */
export function loadLayouts(force = false): Promise<void> {
  if (loaded && !force) return Promise.resolve();
  inflight ??= get<{ layouts: unknown }>("/api/layouts").then((r) => { store = clean(r.layouts); loaded = true; }).catch(() => undefined).finally(() => { inflight = null; });
  return inflight;
}

export function currentLayouts(): LayoutStore { return store; }
export function setLayouts(raw: unknown): void { store = clean(raw); loaded = true; }

// ------------------------------------------------------------------ helpers
const itemsOf = (group: HTMLElement): HTMLElement[] => Array.from(group.children).filter((c): c is HTMLElement => c instanceof HTMLElement && !!c.dataset.card);

/** Moving a node through the DOM resets the scroll position of everything inside it (the chat list, for one). Put it back afterwards. */
function keepScroll(el: HTMLElement, move: () => void): void {
  const saved: [Element, number][] = [];
  el.querySelectorAll("*").forEach((n) => { if (n.scrollTop > 0) saved.push([n, n.scrollTop]); });
  move();
  for (const [n, top] of saved) n.scrollTop = top;
}

/** Puts `items` into the order `sorted` while leaving every other child of the container exactly where it was. */
function place(items: HTMLElement[], sorted: HTMLElement[]): void {
  if (items.length !== sorted.length || items.every((el, i) => el === sorted[i])) return;
  const marks = items.map((el) => { const m = document.createComment(""); el.replaceWith(m); return m; });
  sorted.forEach((el, i) => keepScroll(el, () => marks[i].replaceWith(el)));
}

const titleOf = (el: HTMLElement): string => el.dataset.label || el.querySelector(":scope > header h2")?.textContent?.trim() || "this card";
const reduced = (): boolean => matchMedia("(prefers-reduced-motion: reduce)").matches;

// ------------------------------------------------------------------ one page's layout
export interface PageLayout {
  /** Put this in the page header. Hidden until the page has cards to arrange. */
  button: HTMLButtonElement;
  /** Applies the saved order to these containers. Call it each time the page's cards are (re)built. Ends any edit in progress without saving. */
  arrange(groups: HTMLElement[], opts?: { prefix?: string }): void;
  readonly editing: boolean;
  /** Runs after Done or Cancel, so a page that held back a refresh while you were editing can catch up. */
  onExit(fn: () => void): void;
  dispose(): void;
}

export function pageLayout(page: string): PageLayout {
  let groups: HTMLElement[] = [];
  let prefix = "";
  let editing = false;
  let defaults = new Map<HTMLElement, HTMLElement[]>();
  let snapshot = new Map<HTMLElement, HTMLElement[]>();
  const ids = new Map<HTMLElement, string>();
  let bar: HTMLElement | null = null;
  let say: HTMLElement | null = null;
  let hint: HTMLElement | null = null;
  let watch = 0;
  let exitFn: (() => void) | null = null;
  let mq: MediaQueryList | null = null;
  let mo: MutationObserver | null = null;
  const offs: (() => void)[] = [];

  const button = h("button", { class: "btn small layout-btn", type: "button", "aria-pressed": "false", hidden: true, title: "Drag the cards on this page into the order you like" },
    icon("grid", 15), h("span", null, "Edit layout")) as HTMLButtonElement;
  button.addEventListener("click", () => (editing ? finish(true) : enter()));

  const idOf = (el: HTMLElement): string => ids.get(el) ?? "";
  const orderOf = (g: HTMLElement): HTMLElement[] => itemsOf(g);
  const allIds = (): string[] => groups.flatMap((g) => orderOf(g).map(idOf));
  const savedOrder = (): string[] => store[layoutKind()][page] ?? [];

  /** Gives every card an id that is unique on this page ("overview_this-device"). */
  function index(): void {
    ids.clear();
    const used = new Set<string>();
    for (const g of groups) for (const el of itemsOf(g)) {
      let id = (prefix + el.dataset.card).replace(/[^a-z0-9_-]/gi, "-").toLowerCase().slice(0, 36);
      for (let n = 2; used.has(id); n++) id = `${id.replace(/-\d+$/, "").slice(0, 34)}-${n}`;
      used.add(id);
      ids.set(el, id);
    }
  }

  /** Sorts each container by the saved order. Cards the saved order does not know keep their default order, after the known ones. */
  function applySaved(): void {
    const pos = new Map(savedOrder().map((id, i) => [id, i] as const));
    for (const g of groups) {
      const items = defaults.get(g) ?? itemsOf(g);
      const sorted = items.map((el, i) => ({ el, i, p: pos.get(idOf(el)) ?? Infinity })).sort((a, b) => a.p - b.p || a.i - b.i).map((x) => x.el);
      place(orderOf(g), sorted);
    }
  }

  function arrange(next: HTMLElement[], opts: { prefix?: string } = {}): void {
    if (editing) finish(false, true);
    groups = next;
    prefix = opts.prefix ?? "";
    index();
    defaults = new Map(groups.map((g) => [g, itemsOf(g)]));
    applySaved();
    button.hidden = allIds().length < 2;
    watchChildren();
    if (!loaded) void loadLayouts().then(() => { if (!editing && groups === next) applySaved(); });
    mq?.removeEventListener("change", onMedia);
    mq = matchMedia("(max-width: 719px), (pointer: coarse)");
    mq.addEventListener("change", onMedia);
  }

  /** A page may rebuild some of its cards after it arranged them (a section that repaints itself). Notice, and arrange the new ones the same way. */
  function watchChildren(): void {
    mo?.disconnect();
    mo = new MutationObserver(() => {
      if (editing) return;
      const now = groups.flatMap(itemsOf), known = new Set(ids.keys());
      if (now.length === known.size && now.every((el) => known.has(el))) return;
      index();
      defaults = new Map(groups.map((g) => [g, itemsOf(g)]));
      applySaved();
      button.hidden = allIds().length < 2;
      mo?.takeRecords();                                  // the moves made just above are ours; do not react to them
    });
    for (const g of groups) mo.observe(g, { childList: true });
  }

  /** The window changed between "desktop" and "mobile": go back to the default order and apply that kind's saved one. */
  function onMedia(): void {
    if (!groups.some((g) => g.isConnected)) { mq?.removeEventListener("change", onMedia); return; }
    if (editing) finish(false, true);
    for (const g of groups) place(orderOf(g), defaults.get(g) ?? orderOf(g));
    applySaved();
  }

  // ---------------------------------------------------------------- edit mode
  function enter(): void {
    if (editing || !groups.length) return;
    editing = true;
    snapshot = new Map(groups.map((g) => [g, orderOf(g)]));
    document.body.classList.add("arranging");
    button.setAttribute("aria-pressed", "true");
    for (const g of groups) {
      g.classList.add("arr-group");
      for (const el of orderOf(g)) decorate(el);
      const down = (e: PointerEvent) => onDown(e, g);
      g.addEventListener("pointerdown", down);
      const key = (e: KeyboardEvent) => onKey(e, g);
      g.addEventListener("keydown", key);
      offs.push(() => { g.removeEventListener("pointerdown", down); g.removeEventListener("keydown", key); });
    }
    bar = h("div", { class: "arr-bar", role: "region", "aria-label": "Arranging cards" },
      hint = h("span", { class: "arr-hint" }, "Drag a card by its handle or title. Arrow keys work on a focused handle."),
      h("span", { class: "arr-actions" },
        h("button", { class: "btn small", type: "button", onclick: resetOrder, title: "Back to the default order. Press Done to keep it." }, icon("undo", 15), "Reset"),
        h("button", { class: "btn small", type: "button", onclick: () => finish(false) }, "Cancel"),
        h("button", { class: "btn small primary", type: "button", onclick: () => finish(true) }, icon("check", 15), "Done")),
      say = h("span", { class: "sr-only", role: "status", "aria-live": "polite" }));
    document.body.appendChild(bar);
    const esc = (e: KeyboardEvent) => { if (e.key === "Escape" && !drag && !document.querySelector(".sheet, .popover, .palette")) { e.preventDefault(); finish(false); } };
    document.addEventListener("keydown", esc);
    offs.push(() => document.removeEventListener("keydown", esc));
    // if the page is left while editing (the address changed), clean up
    watch = window.setInterval(() => { if (!groups.some((g) => g.isConnected)) finish(false, true); }, 500);
    button.querySelector("span")!.textContent = "Done";
    announce("Layout editing is on.");
  }

  function decorate(el: HTMLElement): void {
    el.classList.add("arr-item");
    const hasHead = !!el.querySelector(":scope > header");
    const title = titleOf(el);
    const handle = h("button", { class: "arr-handle", type: "button", "aria-label": `Move ${title}. Drag it, or use the arrow keys.`, title: "Drag to move" }, icon("grip", 18));
    if (hasHead) el.appendChild(handle);
    else el.prepend(h("div", { class: "arr-colbar" }, handle, h("span", { class: "muted small" }, title)));
  }

  function undecorate(): void {
    for (const g of groups) {
      g.classList.remove("arr-group");
      g.querySelectorAll(":scope > .arr-colbar").forEach((n) => n.remove());
      for (const el of itemsOf(g)) {
        el.classList.remove("arr-item", "arr-dragging");
        el.style.transform = el.style.transition = "";
        el.querySelectorAll(":scope > .arr-handle").forEach((n) => n.remove());
      }
    }
  }

  function leave(): void {
    editing = false;
    window.clearInterval(watch);
    offs.splice(0).forEach((f) => f());
    undecorate();
    bar?.remove(); bar = say = hint = null;
    document.body.classList.remove("arranging");
    button.setAttribute("aria-pressed", "false");
    const label = button.querySelector("span"); if (label) label.textContent = "Edit layout";
  }

  /** `save` keeps the arrangement; otherwise everything goes back to how it was when editing began. `quiet` skips the exit callback (a re-arrange is under way). */
  function finish(save: boolean, quiet = false): void {
    if (!editing) return;
    stopDrag(false);
    if (!save) {
      for (const g of groups) place(orderOf(g), snapshot.get(g) ?? orderOf(g));
      leave();
      if (!quiet) exitFn?.();
      return;
    }
    const order = allIds();
    const isDefault = groups.every((g) => { const d = defaults.get(g) ?? []; const c = orderOf(g); return d.length === c.length && d.every((el, i) => el === c[i]); });
    const kind = layoutKind();
    void post<{ layouts: unknown }>("/api/layouts/save", { kind, page, order: isDefault ? [] : order })
      .then((r) => { setLayouts(r.layouts); toast("Layout saved"); })
      .catch((e: unknown) => toast(e instanceof Error ? e.message : "The layout could not be saved. It is shown here but will not be there next time.", "error"));
    leave();
    if (!quiet) exitFn?.();
  }

  function resetOrder(): void {
    for (const g of groups) place(orderOf(g), defaults.get(g) ?? orderOf(g));
    if (hint) hint.textContent = "Default order restored. Press Done to keep it, or Cancel to go back.";
    announce("Default order restored.");
  }

  function announce(text: string): void { if (say) { say.textContent = ""; window.setTimeout(() => { if (say) say.textContent = text; }, 30); } }

  // ---------------------------------------------------------------- moving with the keyboard
  /** Moves `item` to `to` (an index among its container's cards), sliding the others. */
  function moveTo(g: HTMLElement, item: HTMLElement, to: number): void {
    const items = orderOf(g);
    const from = items.indexOf(item);
    to = Math.max(0, Math.min(items.length - 1, to));
    if (from < 0 || from === to) return;
    flip(items, () => keepScroll(item, () => { const t = items[to]; if (from < to) t.after(item); else t.before(item); }));
  }

  function onKey(e: KeyboardEvent, g: HTMLElement): void {
    const handle = (e.target as HTMLElement).closest(".arr-handle");
    if (!handle) return;
    const item = (handle.closest(".arr-colbar") ? handle.closest(".arr-colbar")!.parentElement : handle.parentElement) as HTMLElement | null;
    if (!item || item.parentElement !== g) return;
    const i = orderOf(g).indexOf(item), n = orderOf(g).length;
    let to = -1;
    if (e.key === "ArrowUp" || e.key === "ArrowLeft") to = i - 1;
    else if (e.key === "ArrowDown" || e.key === "ArrowRight") to = i + 1;
    else if (e.key === "Home") to = 0;
    else if (e.key === "End") to = n - 1;
    else return;
    e.preventDefault();
    e.stopPropagation();
    if (to < 0 || to >= n || to === i) { announce(to < 0 ? "Already first." : "Already last."); return; }
    moveTo(g, item, to);
    (handle as HTMLElement).focus({ preventScroll: true });
    item.scrollIntoView({ block: "nearest", behavior: reduced() ? "auto" : "smooth" });
    announce(`${titleOf(item)} moved to position ${orderOf(g).indexOf(item) + 1} of ${n}.`);
  }

  // ---------------------------------------------------------------- moving with a pointer
  interface Drag { item: HTMLElement; group: HTMLElement; pid: number; grabX: number; grabY: number; x: number; y: number; lastSwap: number; raf: number }
  let drag: Drag | null = null;

  /** FLIP: run `change` (which reorders the DOM) and slide the given cards from where they were to where they are now. */
  function flip(cards: HTMLElement[], change: () => void): void {
    const first = cards.map((c) => c.getBoundingClientRect());
    cards.forEach((c) => { c.style.transition = "none"; c.style.transform = ""; });
    change();
    const last = cards.map((c) => c.getBoundingClientRect());
    cards.forEach((c, i) => {
      const dx = first[i].left - last[i].left, dy = first[i].top - last[i].top;
      if (dx || dy) c.style.transform = `translate(${dx}px, ${dy}px)`;
    });
    void document.body.offsetWidth;                       // commit the starting positions
    const ms = reduced() ? 0 : 190;
    cards.forEach((c) => { c.style.transition = ms ? `transform ${ms}ms cubic-bezier(.2,.7,.2,1)` : "none"; c.style.transform = ""; });
    if (ms) window.setTimeout(() => cards.forEach((c) => { if (c !== drag?.item) c.style.transition = ""; }), ms + 40);
  }

  function onDown(e: PointerEvent, g: HTMLElement): void {
    if (drag || (e.pointerType === "mouse" && e.button !== 0)) return;
    const grip = (e.target as HTMLElement).closest(".arr-handle, .arr-item > header") as HTMLElement | null;
    if (!grip) return;
    const item = (grip.classList.contains("arr-handle") ? (grip.closest(".arr-colbar") ? grip.closest(".arr-colbar")!.parentElement : grip.parentElement) : grip.parentElement) as HTMLElement | null;
    if (!item || item.parentElement !== g || !item.classList.contains("arr-item")) return;
    e.preventDefault();
    const r = item.getBoundingClientRect();
    drag = { item, group: g, pid: e.pointerId, grabX: e.clientX - r.left, grabY: e.clientY - r.top, x: e.clientX, y: e.clientY, lastSwap: 0, raf: 0 };
    item.classList.add("arr-dragging");
    document.body.classList.add("arr-drag-active");
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
    window.addEventListener("pointercancel", onUp);
    drag.raf = requestAnimationFrame(tick);
  }

  function follow(): void {
    if (!drag) return;
    const it = drag.item;
    it.style.transition = "none";
    it.style.transform = "";
    const r = it.getBoundingClientRect();
    it.style.transform = `translate(${drag.x - drag.grabX - r.left}px, ${drag.y - drag.grabY - r.top}px)`;
  }

  /** The card under the pointer, if it is another card of the same container. */
  function swapIfOver(): void {
    if (!drag || performance.now() - drag.lastSwap < 150) return;
    const it = drag.item, items = orderOf(drag.group), others = items.filter((x) => x !== it);
    const over = others.find((s) => { const r = s.getBoundingClientRect(); return r.width > 0 && drag!.x >= r.left && drag!.x <= r.right && drag!.y >= r.top && drag!.y <= r.bottom; });
    if (!over) return;
    drag.lastSwap = performance.now();
    flip(others, () => keepScroll(it, () => { it.style.transform = ""; if (items.indexOf(it) < items.indexOf(over)) over.after(it); else over.before(it); }));
    follow();
  }

  function onMove(e: PointerEvent): void {
    if (!drag || e.pointerId !== drag.pid) return;
    e.preventDefault();
    drag.x = e.clientX; drag.y = e.clientY;
    follow();
    swapIfOver();
  }

  /** While the pointer is held near the top or bottom edge the page scrolls, so a card can be taken a long way. */
  function tick(): void {
    if (!drag) return;
    const edge = 70, speed = 16;
    const y = drag.y;
    let dy = 0;
    if (y < edge) dy = -Math.ceil(((edge - Math.max(0, y)) / edge) * speed);
    else if (y > window.innerHeight - edge) dy = Math.ceil(((y - (window.innerHeight - edge)) / edge) * speed);
    if (dy) { window.scrollBy(0, dy); follow(); swapIfOver(); }
    drag.raf = requestAnimationFrame(tick);
  }

  function onUp(e: PointerEvent): void {
    if (!drag || e.pointerId !== drag.pid) return;
    const it = drag.item, n = orderOf(drag.group).indexOf(it) + 1, total = orderOf(drag.group).length;
    stopDrag(true);
    announce(`${titleOf(it)} placed at position ${n} of ${total}.`);
  }

  /** Ends a drag. With `settle` the card glides into its slot; without it (cancelling) it just snaps. */
  function stopDrag(settle: boolean): void {
    if (!drag) return;
    const it = drag.item;
    cancelAnimationFrame(drag.raf);
    window.removeEventListener("pointermove", onMove);
    window.removeEventListener("pointerup", onUp);
    window.removeEventListener("pointercancel", onUp);
    document.body.classList.remove("arr-drag-active");
    drag = null;
    if (settle && !reduced()) {
      it.style.transition = "transform 170ms cubic-bezier(.2,.7,.2,1), box-shadow 170ms";
      it.style.transform = "";
      window.setTimeout(() => { it.style.transition = ""; it.classList.remove("arr-dragging"); }, 190);
    } else {
      it.style.transition = it.style.transform = "";
      it.classList.remove("arr-dragging");
    }
  }

  // ---------------------------------------------------------------- press and hold (touch): enters edit mode from a card's title
  const press = (e: PointerEvent) => {
    if (editing || e.pointerType === "mouse" || !groups.some((g) => g.isConnected)) return;
    const head = (e.target as HTMLElement).closest(".block > header") as HTMLElement | null;
    const item = head?.parentElement as HTMLElement | null;
    if (!head || !item || !item.dataset.card || !groups.some((g) => item.parentElement === g)) return;
    const x0 = e.clientX, y0 = e.clientY;
    const stop = () => { window.clearTimeout(t); window.removeEventListener("pointermove", mv); window.removeEventListener("pointerup", stop); window.removeEventListener("pointercancel", stop); window.removeEventListener("scroll", stop, true); };
    const mv = (m: PointerEvent) => { if (Math.hypot(m.clientX - x0, m.clientY - y0) > 8) stop(); };
    const t = window.setTimeout(() => { stop(); enter(); try { navigator.vibrate?.(15); } catch { /* not supported */ } }, 550);
    window.addEventListener("pointermove", mv); window.addEventListener("pointerup", stop); window.addEventListener("pointercancel", stop); window.addEventListener("scroll", stop, true);
  };
  document.addEventListener("pointerdown", press);
  // a long press on a title must not open the system's text menu
  const noMenu = (e: Event) => { if (!editing && matchMedia("(pointer: coarse)").matches && (e.target as HTMLElement).closest?.(".block > header") && groups.some((g) => g.contains(e.target as Node))) e.preventDefault(); };
  document.addEventListener("contextmenu", noMenu);

  function dispose(): void {
    if (editing) finish(false, true);
    document.removeEventListener("pointerdown", press);
    document.removeEventListener("contextmenu", noMenu);
    mq?.removeEventListener("change", onMedia);
    mo?.disconnect();
    groups = [];
  }

  return { button, arrange, get editing() { return editing; }, onExit: (fn) => { exitFn = fn; }, dispose };
}
