/**
 * Navigation helpers shared by every page:
 *  - "On this page": a floating chip that names the section you are in and opens a list of all of them
 *  - a thin reading-progress line and a Back to top button
 *  - recent pages (for the quick switcher)
 *  - folded(): long lists show the first few rows, then a "Show all" sheet with search and an end
 */
import { h, mount, sheet } from "./dom.js";
import { icon } from "./icons.js";

const REDUCED = () => matchMedia("(prefers-reduced-motion: reduce)").matches;
const topOffset = () => (parseFloat(getComputedStyle(document.documentElement).getPropertyValue("--topbar-h")) || 56) + 12;

// ------------------------------------------------------------------ recent pages
const RECENT_KEY = "savahbot.recent";
export function recentPages(): string[] {
  try { const v = JSON.parse(localStorage.getItem(RECENT_KEY) || "[]"); return Array.isArray(v) ? v.filter((x) => typeof x === "string").slice(0, 6) : []; } catch { return []; }
}
export function trackRecent(id: string): void {
  try { localStorage.setItem(RECENT_KEY, JSON.stringify([id, ...recentPages().filter((x) => x !== id)].slice(0, 6))); } catch { /* private mode: recents are a convenience */ }
}

// ------------------------------------------------------------------ on this page + progress + back to top
interface Section { label: string; el: HTMLElement }
const SELECTOR = ".page-head h1, .block > header h2, .sp-card > h3, .k-card > header h2, [data-jump]";

function scan(root: HTMLElement): Section[] {
  const seen = new Set<HTMLElement>();
  const out: Section[] = [];
  root.querySelectorAll<HTMLElement>(SELECTOR).forEach((n) => {
    const target = (n.closest(".block, .sp-card, .k-card") as HTMLElement | null) ?? n;
    const label = (n.getAttribute("data-jump") || n.textContent || "").replace(/\s+/g, " ").trim();
    if (!label || seen.has(target) || target.closest("[hidden]") || target.getClientRects().length === 0) return;
    seen.add(target);
    out.push({ label: label.slice(0, 60), el: target });
  });
  return out;
}

/** Call once per page render; returns a function that removes everything again. */
export function installPageNav(content: HTMLElement): () => void {
  let sections: Section[] = [];
  let current = 0;
  let sheetRef: { close: () => void } | null = null;
  const bar = h("div", { class: "read-progress", "aria-hidden": "true" });
  const chipLabel = h("span", { class: "jump-label" });
  const chip = h("button", { class: "jump-chip", type: "button", "aria-haspopup": "dialog", hidden: true, onclick: () => openList() }, icon("list", 16), chipLabel, icon("chevronUp", 14));
  const top = h("button", { class: "to-top", type: "button", "aria-label": "Back to top", title: "Back to top", hidden: true, onclick: () => window.scrollTo({ top: 0, behavior: REDUCED() ? "auto" : "smooth" }) }, icon("arrowUp", 18));
  const dock = h("div", { class: "jump-dock" }, top, chip);
  document.body.append(bar, dock);

  const goTo = (s: Section) => {
    const y = s.el.getBoundingClientRect().top + window.scrollY - topOffset();
    window.scrollTo({ top: Math.max(0, y), behavior: REDUCED() ? "auto" : "smooth" });
  };
  function openList(): void {
    if (sheetRef) return;
    const list = h("div", { class: "jump-list", role: "list" }, sections.map((s, i) => h("button", { class: "jump-item", type: "button", role: "listitem", "aria-current": i === current ? "true" : undefined,
      onclick: () => { sheetRef?.close(); goTo(s); } }, h("span", { class: "jump-n" }, String(i + 1)), h("span", null, s.label))));
    sheetRef = sheet("On this page", list, () => { sheetRef = null; });
  }
  function update(): void {
    const max = document.documentElement.scrollHeight - window.innerHeight;
    const y = window.scrollY;
    bar.style.transform = `scaleX(${max > 0 ? Math.min(1, Math.max(0, y / max)) : 0})`;
    top.hidden = y < 700;
    const line = topOffset() + 8;
    let idx = 0;
    sections.forEach((s, i) => { if (s.el.getBoundingClientRect().top <= line) idx = i; });
    if (max - y < 4 && sections.length) idx = sections.length - 1;
    current = idx;
    if (sections[idx]) chipLabel.textContent = sections[idx].label;
  }
  let raf = 0;
  const onScroll = () => { if (!raf) raf = requestAnimationFrame(() => { raf = 0; update(); }); };
  let timer = 0;
  const rescan = () => {
    window.clearTimeout(timer);
    timer = window.setTimeout(() => {
      sections = scan(content);
      chip.hidden = sections.length < 3;      // a short page needs no map
      update();
    }, 250);
  };
  const mo = new MutationObserver(rescan);
  mo.observe(content, { childList: true, subtree: true });
  window.addEventListener("scroll", onScroll, { passive: true });
  window.addEventListener("resize", onScroll);
  rescan();
  return () => {
    mo.disconnect();
    window.clearTimeout(timer);
    window.removeEventListener("scroll", onScroll);
    window.removeEventListener("resize", onScroll);
    sheetRef?.close();
    bar.remove();
    dock.remove();
  };
}

// ------------------------------------------------------------------ long lists with an end
export interface FoldOpts<T> { noun: string; title: string; initial?: number; chunk?: number; text?: (t: T) => string }

/**
 * The first rows of a long list, then one "Show all N" row. The full list opens in a sheet with search, loads 40 rows at a time
 * and ends with a clear "That is everything" line, so a page always has a bottom.
 */
export function folded<T>(items: T[], make: (t: T) => Node, o: FoldOpts<T>): Node[] {
  const first = o.initial ?? 6;
  const head = items.slice(0, first).map(make);
  if (items.length <= first) return head;
  const open = h("button", { class: "fold-more", type: "button", onclick: () => {
    const chunk = o.chunk ?? 40;
    let shown = 0;
    let needle = "";
    const body = h("div", { class: "fold-list" });
    const search = o.text ? h("input", { class: "input", type: "search", placeholder: `Search ${o.noun}`, "aria-label": `Search ${o.noun}`, oninput: (e: Event) => { needle = (e.target as HTMLInputElement).value.trim().toLowerCase(); shown = 0; draw(); } }) as HTMLInputElement : null;
    const draw = () => {
      const pool = needle && o.text ? items.filter((t) => o.text!(t).toLowerCase().includes(needle)) : items;
      shown = Math.min(pool.length, Math.max(shown, chunk));
      mount(body, pool.length ? [
        ...pool.slice(0, shown).map(make),
        shown < pool.length
          ? h("button", { class: "fold-more", type: "button", onclick: () => { shown += chunk; draw(); } }, `Show ${Math.min(chunk, pool.length - shown)} more`, h("span", { class: "muted small" }, `${shown} of ${pool.length}`))
          : h("p", { class: "fold-end muted small" }, `That is everything: ${pool.length} ${o.noun}.`)]
        : h("p", { class: "fold-end muted" }, `No ${o.noun} match.`));
    };
    draw();
    sheet(o.title, h("div", { class: "stack", style: "gap:10px" }, search, body));
  } }, h("span", null, `Show all ${items.length} ${o.noun}`), icon("chevronRight", 16));
  return [...head, open];
}
