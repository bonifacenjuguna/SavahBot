/** Small dependency-free SVG charts. Colours come from CSS variables so light and dark themes both work. */
import { h } from "./dom.js";

const NS = "http://www.w3.org/2000/svg";
function s(tag: string, attrs: Record<string, string | number> = {}, text?: string): SVGElement {
  const e = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, String(v));
  if (text !== undefined) e.textContent = text;
  return e;
}

export const SERIES = ["s1", "s2", "s3", "s4", "s5", "s6"];

/** Tiny trend line with a soft area fill. Stretches to its container. */
export function sparkline(values: number[], cls = "s1"): SVGElement {
  const w = 100, hgt = 32;
  const svg = s("svg", { viewBox: `0 0 ${w} ${hgt}`, preserveAspectRatio: "none", class: `spark ${cls}`, "aria-hidden": "true" });
  const data = values.length > 1 ? values : [0, 0];
  const max = Math.max(...data, 1);
  const step = w / (data.length - 1);
  const pts = data.map((v, i) => [i * step, hgt - 2 - (v / max) * (hgt - 6)] as const);
  const line = pts.map(([x, y], i) => `${i ? "L" : "M"}${x.toFixed(2)} ${y.toFixed(2)}`).join("");
  svg.appendChild(s("path", { d: `${line}L${w} ${hgt}L0 ${hgt}Z`, class: "spark-area" }));
  svg.appendChild(s("path", { d: line, class: "spark-line", "vector-effect": "non-scaling-stroke" }));
  return svg;
}

export interface Point { t: number; a: number; b: number }

function niceMax(v: number): number {
  if (v <= 4) return 4;
  const p = Math.pow(10, Math.floor(Math.log10(v)));
  for (const m of [1, 2, 2.5, 5, 10]) if (v <= m * p) return m * p;
  return 10 * p;
}

/** Responsive area chart: series A as a filled area, series B (a share of A) as an overlaid area. Hover or touch for details. */
export function areaChart(points: Point[], opts: { labelA: string; labelB: string; fmt: (t: number) => string; ariaLabel: string }): HTMLElement {
  const wrap = h("div", { class: "chart", role: "img", "aria-label": opts.ariaLabel });
  const tip = h("div", { class: "chart-tip", hidden: true });
  wrap.appendChild(tip);
  let svg: SVGElement | null = null;

  const draw = () => {
    const width = Math.max(240, Math.floor(wrap.clientWidth));
    const height = width < 480 ? 190 : 240;
    const m = { l: 34, r: 8, t: 10, b: 24 };
    const iw = width - m.l - m.r, ih = height - m.t - m.b;
    svg?.remove();
    const g = s("svg", { viewBox: `0 0 ${width} ${height}`, width, height, class: "chart-svg" });
    const maxA = niceMax(Math.max(...points.map((p) => p.a), 1));
    const x = (i: number) => m.l + (points.length > 1 ? (i / (points.length - 1)) * iw : iw / 2);
    const y = (v: number) => m.t + ih - (v / maxA) * ih;

    for (let k = 0; k <= 4; k++) {
      const v = (maxA / 4) * k, yy = y(v);
      g.appendChild(s("line", { x1: m.l, x2: width - m.r, y1: yy, y2: yy, class: "grid" }));
      g.appendChild(s("text", { x: m.l - 6, y: yy + 4, "text-anchor": "end", class: "axis" }, String(Math.round(v * 10) / 10)));
    }
    const ticks = Math.min(width < 480 ? 3 : 6, points.length);
    for (let k = 0; k < ticks && points.length > 1; k++) {
      const i = Math.round((k / Math.max(1, ticks - 1)) * (points.length - 1));
      g.appendChild(s("text", { x: x(i), y: height - 6, "text-anchor": k === 0 ? "start" : k === ticks - 1 ? "end" : "middle", class: "axis" }, opts.fmt(points[i].t)));
    }
    const path = (key: "a" | "b") => points.map((p, i) => `${i ? "L" : "M"}${x(i).toFixed(1)} ${y(p[key]).toFixed(1)}`).join("");
    if (points.length) {
      const base = m.t + ih;
      g.appendChild(s("path", { d: `${path("a")}L${x(points.length - 1)} ${base}L${x(0)} ${base}Z`, class: "area-a" }));
      g.appendChild(s("path", { d: path("a"), class: "line-a" }));
      g.appendChild(s("path", { d: `${path("b")}L${x(points.length - 1)} ${base}L${x(0)} ${base}Z`, class: "area-b" }));
      g.appendChild(s("path", { d: path("b"), class: "line-b" }));
    }
    const cursor = s("line", { y1: m.t, y2: m.t + ih, class: "cursor", visibility: "hidden" });
    const dot = s("circle", { r: 4, class: "dot", visibility: "hidden" });
    g.appendChild(cursor);
    g.appendChild(dot);

    const move = (ev: PointerEvent) => {
      if (!points.length) return;
      const rect = g.getBoundingClientRect();
      const px = ((ev.clientX - rect.left) / rect.width) * width;
      const i = Math.max(0, Math.min(points.length - 1, Math.round(((px - m.l) / iw) * (points.length - 1))));
      const p = points[i];
      cursor.setAttribute("x1", String(x(i))); cursor.setAttribute("x2", String(x(i))); cursor.setAttribute("visibility", "visible");
      dot.setAttribute("cx", String(x(i))); dot.setAttribute("cy", String(y(p.a))); dot.setAttribute("visibility", "visible");
      tip.hidden = false;
      tip.replaceChildren(h("strong", null, opts.fmt(p.t)), h("div", null, `${opts.labelA}: ${p.a}`), h("div", null, `${opts.labelB}: ${p.b}`));
      const tw = tip.offsetWidth;
      tip.style.left = `${Math.max(4, Math.min(width - tw - 4, x(i) - tw / 2))}px`;
    };
    const leave = () => { cursor.setAttribute("visibility", "hidden"); dot.setAttribute("visibility", "hidden"); tip.hidden = true; };
    g.addEventListener("pointermove", move);
    g.addEventListener("pointerdown", move);
    g.addEventListener("pointerleave", leave);
    wrap.insertBefore(g, tip);
    svg = g;
  };

  let last = 0;
  const ro = new ResizeObserver(() => { const w = wrap.clientWidth; if (w && Math.abs(w - last) > 1) { last = w; draw(); } });
  ro.observe(wrap);
  queueMicrotask(() => { if (!last && wrap.clientWidth) { last = wrap.clientWidth; draw(); } });
  return wrap;
}

export interface Slice { name: string; value: number }

/** Donut with a centre total and a legend. Tap a slice (or its legend row) and it moves straight out from the centre and the centre shows its share; tap it again to put it back.
 *  Slices are real ring segments (not stroked circles), so a slice that moves keeps its exact shape and the ring never shows a gap or a shadow behind it. */
export function donut(slices: Slice[], opts: { center: string; sub: string; ariaLabel: string }): HTMLElement {
  const total = slices.reduce((a, b) => a + b.value, 0);
  const CX = 70, CY = 70, R1 = 61, R0 = 43, PUSH = 7;
  const svg = s("svg", { viewBox: `0 0 140 140`, class: "donut-svg", role: "img", "aria-label": opts.ariaLabel, focusable: "false" });
  const pt = (rad: number, a: number): string => `${(CX + rad * Math.cos(a)).toFixed(3)} ${(CY + rad * Math.sin(a)).toFixed(3)}`;
  /** One ring segment from angle a0 to a1 (radians, 0 = three o'clock). A full turn is drawn as a whole ring. */
  const ring = (a0: number, a1: number): string => {
    if (a1 - a0 >= Math.PI * 2 - 1e-4) return `M ${CX - R1} ${CY} A ${R1} ${R1} 0 1 1 ${CX + R1} ${CY} A ${R1} ${R1} 0 1 1 ${CX - R1} ${CY} Z M ${CX - R0} ${CY} A ${R0} ${R0} 0 1 0 ${CX + R0} ${CY} A ${R0} ${R0} 0 1 0 ${CX - R0} ${CY} Z`;
    const big = a1 - a0 > Math.PI ? 1 : 0;
    return `M ${pt(R1, a0)} A ${R1} ${R1} 0 ${big} 1 ${pt(R1, a1)} L ${pt(R0, a1)} A ${R0} ${R0} 0 ${big} 0 ${pt(R0, a0)} Z`;
  };
  const live = slices.filter((x) => x.value > 0).length;
  if (!total) svg.appendChild(s("circle", { cx: CX, cy: CY, r: (R0 + R1) / 2, class: "donut-track", fill: "none", "stroke-width": R1 - R0 }));
  const segs: (SVGElement | null)[] = [];
  const dir: [number, number][] = [];                       // the way each slice moves when picked: straight out from the centre
  let from = -Math.PI / 2;
  slices.forEach((sl, i) => {
    if (!total || !sl.value) { segs.push(null); return; }
    const span = (sl.value / total) * Math.PI * 2;
    const gap = live > 1 ? Math.min(0.02, span / 4) : 0;       // a hair of space between slices, never more than a quarter of a thin slice
    const seg = s("path", { d: ring(from + gap / 2, from + span - gap / 2), class: `seg ${SERIES[i % SERIES.length]}`, "fill-rule": "evenodd" });
    seg.addEventListener("click", () => pick(i));
    svg.appendChild(seg);
    segs.push(seg);
    const mid = from + span / 2;
    dir[i] = [Math.cos(mid), Math.sin(mid)];
    from += span;
  });
  const num = s("text", { x: CX, y: 72, "text-anchor": "middle", class: "donut-num" }, opts.center);
  const sub = s("text", { x: CX, y: 90, "text-anchor": "middle", class: "donut-sub" }, opts.sub);
  svg.appendChild(num);
  svg.appendChild(sub);
  const rows = slices.map((sl, i) =>
    h("li", { class: `lg-row ${SERIES[i % SERIES.length]}`, tabindex: "0", role: "button", "aria-pressed": "false", onclick: () => pick(i), onkeydown: (e: KeyboardEvent) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); pick(i); } } },
      h("i", { class: `sw ${SERIES[i % SERIES.length]}` }), h("span", { class: "grow" }, sl.name), h("b", null, String(sl.value)), h("span", { class: "muted small pct" }, total ? `${Math.round((sl.value / total) * 100)}%` : "0%")));
  let current = -1;
  function pick(i: number): void {
    current = current === i ? -1 : i;
    segs.forEach((seg, k) => {
      if (!seg) return;
      const on = k === current;
      // all movement is a CSS transform, so it animates smoothly in both directions and the slice keeps its exact shape
      (seg as SVGElement).style.transform = on ? (live > 1 ? `translate(${(dir[k][0] * PUSH).toFixed(2)}px, ${(dir[k][1] * PUSH).toFixed(2)}px) scale(1.04)` : "scale(1.04)") : "";
      seg.classList.toggle("on", on);
      seg.classList.toggle("dim", current >= 0 && !on);
    });
    rows.forEach((li, k) => { li.classList.toggle("on", k === current); li.setAttribute("aria-pressed", String(k === current)); });
    num.textContent = current >= 0 ? `${total ? Math.round((slices[current].value / total) * 100) : 0}%` : opts.center;
    sub.textContent = current >= 0 ? slices[current].name : opts.sub;
  }
  return h("div", { class: "donut" }, svg as unknown as Node, h("ul", { class: "legend" }, rows));
}

/** Circular progress. */
export function ring(fraction: number, label: string, sub: string, state: "" | "hot" = ""): HTMLElement {
  const size = 96, r = 38, c = 2 * Math.PI * r, f = Math.max(0, Math.min(1, fraction));
  const svg = s("svg", { viewBox: `0 0 ${size} ${size}`, class: `ring-svg ${state}`, role: "img", "aria-label": `${label}: ${sub}` });
  svg.appendChild(s("circle", { cx: 48, cy: 48, r, fill: "none", "stroke-width": 9, class: "ring-track" }));
  svg.appendChild(s("circle", { cx: 48, cy: 48, r, fill: "none", "stroke-width": 9, class: "ring-fill", "stroke-linecap": "round", "stroke-dasharray": `${f * c} ${c}`, transform: "rotate(-90 48 48)" }));
  svg.appendChild(s("text", { x: 48, y: 53, "text-anchor": "middle", class: "ring-num" }, label));
  return h("div", { class: "ring" }, svg as unknown as Node);
}

/** Horizontal bars (HTML so long names wrap and stay readable on phones). */
export function hbars(rows: { name: string; count: number }[], cls = "s1"): HTMLElement {
  if (!rows.length) return h("div", { class: "empty" }, "Nothing to show yet.");
  const max = Math.max(...rows.map((r) => r.count), 1);
  return h("div", { class: "hbars" }, rows.map((r) =>
    h("div", { class: "hbar" }, h("span", { class: "name small" }, r.name), h("span", { class: "track" }, h("i", { class: cls, style: `width:${Math.max(2, (r.count / max) * 100)}%` })), h("span", { class: "num small" }, String(r.count)))));
}
