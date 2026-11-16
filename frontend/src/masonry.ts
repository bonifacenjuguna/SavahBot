/**
 * 1.4.10: true masonry for card pages on a computer.
 *
 * The old balanced columns (CSS `columns: 2`) fill the left column first, so a page of "one short card, then a long one, then more" left a hole under the
 * short card (Notifications, Security, Backup). Here the page becomes a two-column grid of 4px rows and every card spans as many rows as it is tall, so each
 * card lands in whichever column is shorter. Nothing is moved in the DOM and no card is re-created; only a `--rs` (row span) is set on each child, and a
 * ResizeObserver keeps it right while cards grow or shrink. Anything that is not a card (tabs, figures, notes) and any card that holds a table or a chart
 * takes the whole row. Below 1100px nothing is applied and phones and tablets are exactly as they were.
 */
const ROW = 4;
const SEL = ".page:has(> .block, > .sp-card), .page > .k-stack:has(> .block, > .sp-card), .page > .k-stack > .k-stack:has(> .block, > .sp-card), .main > .stack:has(> .block, > .sp-card):not(.ins):not(.pane), .masonry";
const CARD = ".block, .sp-card, .n-log";
const WIDE = ".block:has(table, .table-wrap, .wide-card)";

export function installMasonry(content: HTMLElement): () => void {
  const mq = window.matchMedia("(min-width: 1100px)");
  const managed = new Map<HTMLElement, { ro: ResizeObserver; mo: MutationObserver }>();
  let frame = 0;

  const layout = (box: HTMLElement): void => {
    const gap = parseFloat(getComputedStyle(box).columnGap) || 20;
    const kids = Array.from(box.children) as HTMLElement[];
    const cards = kids.filter((k) => k.matches(CARD));
    for (const k of kids) {
      const wide = !k.matches(CARD) || k.matches(WIDE) || cards.length === 1;
      k.toggleAttribute("data-wide", wide);
      const hgt = k.getBoundingClientRect().height;
      k.style.setProperty("--rs", String(Math.max(1, Math.ceil((hgt + gap) / ROW))));
    }
  };
  const watch = (box: HTMLElement): void => {
    const ro = new ResizeObserver(() => layout(box));
    const mo = new MutationObserver(() => { for (const k of Array.from(box.children)) ro.observe(k); layout(box); });
    for (const k of Array.from(box.children)) ro.observe(k);
    mo.observe(box, { childList: true });
    box.dataset.masonry = "1";
    managed.set(box, { ro, mo });
    layout(box);
  };
  const release = (box: HTMLElement): void => {
    managed.get(box)?.ro.disconnect();
    managed.get(box)?.mo.disconnect();
    managed.delete(box);
    delete box.dataset.masonry;
    for (const k of Array.from(box.children) as HTMLElement[]) { k.style.removeProperty("--rs"); k.removeAttribute("data-wide"); }
  };
  const scan = (): void => {
    frame = 0;
    if (!mq.matches) { Array.from(managed.keys()).forEach(release); return; }
    for (const box of Array.from(managed.keys())) if (!content.contains(box) || !box.matches(SEL)) release(box);
    for (const box of Array.from(content.querySelectorAll<HTMLElement>(SEL))) {
      if (managed.has(box) || box.matches(".page:has(.wx-day)")) continue;   // Weather has its own arrangement
      watch(box);
    }
  };
  const queue = (): void => { if (!frame) frame = window.requestAnimationFrame(scan); };

  const top = new MutationObserver(queue);
  top.observe(content, { childList: true, subtree: true });
  mq.addEventListener("change", queue);
  queue();
  return () => {
    top.disconnect();
    mq.removeEventListener("change", queue);
    if (frame) window.cancelAnimationFrame(frame);
    Array.from(managed.keys()).forEach(release);
  };
}
