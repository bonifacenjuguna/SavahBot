/** Small dependency-free SVG charts. Colours come from the CSS palette (variables), so light and dark themes just work. */
import { h } from "./dom.js";

const NS = "http://www.w3.org/2000/svg";
type Attrs = Record<string, string | number>;

function s<K extends keyof SVGElementTagNameMap>(tag: K, attrs: Attrs = {}): SVGElementTagNameMap[K] {
  const e = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, String(v));
  return e;
}

/** The palette names a chart may use. */
export type Tone = "accent" | "demo" | "ok" | "bad" | "standby" | "warn";
const tone = (t: Tone) => `var(--${t === "accent" ? "accent" : t})`;

export function compact(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1).replace(/\.0$/, "")}M`;
  if (n >= 1000) return `${(n / 1000).toFixed(1).replace(/\.0$/, "")}k`;
  return String(Math.round(n));
}

/** A tiny trend line for a stat card. */
export function sparkline(values: number[], t: Tone = "accent"): SVGElement {
  const svg = s("svg", { viewBox: "0 0 100 30", preserveAspectRatio: "none", class: "spark", "aria-hidden": "true", focusable: "false" });
  const data = values.length ? values : [0];
  const max = Math.max(...data, 1);
  const pts = data.map((v, i) => `${data.length > 1 ? (i / (data.length - 1)) * 100 : 50},${28 - (v / max) * 26}`);
  const line = s("polyline", { points: pts.join(" "), fill: "none", "stroke-width": 2, "stroke-linejoin": "round", "stroke-linecap": "round" });
  line.style.stroke = tone(t);
  line.style.vectorEffect = "non-scaling-stroke";
  svg.appendChild(line);
  return svg;
}

export interface BarRow { label: string; total: number; flagged: number }

/**
 * Column chart: one column per time bucket, the flagged share drawn in the demo/amber tone at the foot of each column.
 * Hover or touch shows the exact numbers. A text summary is available to screen readers.
 */
export function columnChart(rows: BarRow[], opts: { tip: (r: BarRow) => string; xLabel: (r: BarRow) => string; summary: string }): HTMLElement {
  const n = Math.max(rows.length, 1);
  const max = Math.max(...rows.map((r) => r.total), 1);
  const svg = s("svg", { viewBox: `0 0 ${n} 100`, preserveAspectRatio: "none", class: "cols-svg", "aria-hidden": "true", focusable: "false" });
  rows.forEach((r, i) => {
    const th = (r.total / max) * 100;
    const bar = s("rect", { x: i + 0.14, y: 100 - th, width: 0.72, height: Math.max(th, r.total ? 0.8 : 0) });
    bar.style.fill = tone("accent");
    svg.appendChild(bar);
    if (r.flagged) {
      const fh = Math.min(th, (r.flagged / Math.max(r.total, 1)) * th);
      const f = s("rect", { x: i + 0.14, y: 100 - fh, width: 0.72, height: fh });
      f.style.fill = tone("demo");
      svg.appendChild(f);
    }
  });
  const marker = h("div", { class: "marker", hidden: true });
  const tip = h("div", { class: "tip", hidden: true, role: "presentation" });
  const plot = h("div", { class: "plot" }, h("div", { class: "gridlines", "aria-hidden": "true" }, h("i"), h("i"), h("i")), svg, marker, tip);
  const show = (clientX: number) => {
    const box = plot.getBoundingClientRect();
    const i = Math.min(n - 1, Math.max(0, Math.floor(((clientX - box.left) / box.width) * n)));
    marker.hidden = tip.hidden = false;
    marker.style.left = `${((i + 0.5) / n) * 100}%`;
    marker.style.width = `${100 / n}%`;
    tip.textContent = rows[i] ? opts.tip(rows[i]) : "";
    const x = ((i + 0.5) / n) * 100;
    tip.style.left = `${Math.min(86, Math.max(14, x))}%`;
  };
  plot.addEventListener("pointermove", (e) => show(e.clientX));
  plot.addEventListener("pointerdown", (e) => show(e.clientX));
  plot.addEventListener("pointerleave", () => { marker.hidden = tip.hidden = true; });

  const labels = h("div", { class: "xlabels", "aria-hidden": "true" });
  const stops = Math.min(5, rows.length);
  for (let k = 0; k < stops; k++) labels.appendChild(h("span", null, rows.length ? opts.xLabel(rows[Math.round((k / Math.max(stops - 1, 1)) * (rows.length - 1))]) : ""));
  return h("div", { class: "chart", role: "img", "aria-label": opts.summary },
    h("div", { class: "yaxis", "aria-hidden": "true" }, h("span", null, compact(max)), h("span", null, compact(max / 2)), h("span", null, "0")),
    plot, labels);
}

export interface Slice { label: string; value: number; tone: Tone }

function ring(parts: { value: number; t: Tone }[], total: number, track = true): SVGElement {
  const svg = s("svg", { viewBox: "0 0 42 42", class: "ring", "aria-hidden": "true", focusable: "false" });
  if (track) {
    const bg = s("circle", { cx: 21, cy: 21, r: 15.915, fill: "none", "stroke-width": 6 });
    bg.style.stroke = "var(--line)";
    svg.appendChild(bg);
  }
  let offset = 25;
  for (const p of parts) {
    if (p.value <= 0 || total <= 0) continue;
    const len = (p.value / total) * 100;
    const c = s("circle", { cx: 21, cy: 21, r: 15.915, fill: "none", "stroke-width": 6, "stroke-dasharray": `${len} ${100 - len}`, "stroke-dashoffset": offset });
    c.style.stroke = tone(p.t);
    svg.appendChild(c);
    offset -= len;
  }
  return svg;
}

/** Proportions with a legend. */
export function donut(slices: Slice[], centre: string): HTMLElement {
  const total = slices.reduce((a, b) => a + b.value, 0);
  return h("div", { class: "donut" },
    h("div", { class: "donut-fig", role: "img", "aria-label": total ? slices.map((x) => `${x.label} ${x.value}`).join(", ") : "No data yet" },
      ring(slices.map((x) => ({ value: x.value, t: x.tone })), total),
      h("div", { class: "donut-mid" }, h("b", null, compact(total)), h("span", null, centre))),
    total
      ? h("ul", { class: "legend" }, slices.map((x) => h("li", null, h("i", { class: `sw ${x.tone}` }), h("span", { class: "grow" }, x.label), h("b", null, String(x.value)), h("span", { class: "muted small" }, `${Math.round((x.value / total) * 100)}%`))))
      : h("p", { class: "muted small" }, "Nothing to show yet."));
}

/** One value against a limit, for example today's YouTube quota. */
export function gauge(fraction: number, centre: string): HTMLElement {
  const pct = Math.max(0, Math.min(1, fraction));
  const t: Tone = pct >= 0.9 ? "bad" : pct >= 0.75 ? "demo" : "accent";
  return h("div", { class: "gauge", role: "img", "aria-label": `${Math.round(pct * 100)} percent used` },
    ring([{ value: pct * 100, t }], 100), h("div", { class: "donut-mid" }, h("b", null, `${Math.round(pct * 100)}%`), h("span", null, centre)));
}

/** Ranked horizontal bars (existing look, now with the number on the right). */
export function hbars(rows: { name: string; count: number }[], t: Tone = "accent"): HTMLElement {
  if (!rows.length) return h("div", { class: "empty" }, "Nothing to show yet.");
  const max = Math.max(...rows.map((r) => r.count), 1);
  return h("div", { class: "hbars" }, rows.map((r) => h("div", { class: "hbar" },
    h("span", { class: "small", title: r.name }, r.name),
    h("i", { class: `fill ${t}`, style: `width:${Math.max(3, (r.count / max) * 100)}%` }),
    h("span", { class: "small muted" }, String(r.count)))));
}
