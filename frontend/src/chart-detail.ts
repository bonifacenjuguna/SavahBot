/** The big chart: tap a chart card to open it. Long ranges (from the kept daily totals), series toggles, compare with the
 *  previous period, a crosshair you can drag or move with the arrow keys, a data table, and CSV / PNG export. */
import { get } from "./api.js";
import { h, mount, sheet, toast } from "./dom.js";
import { icon } from "./icons.js";

const NS = "http://www.w3.org/2000/svg";
const s = (tag: string, attrs: Record<string, string | number> = {}, text?: string): SVGElement => {
  const e = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, String(v));
  if (text !== undefined) e.textContent = text;
  return e;
};

export interface SeriesDef { key: string; label: string; color: string; dash: string }
export const HISTORY_SERIES: SeriesDef[] = [
  { key: "messages", label: "Messages", color: "var(--accent)", dash: "" },
  { key: "flagged", label: "Flagged", color: "var(--demo)", dash: "6 3" },
  { key: "chatters", label: "People chatting", color: "var(--ok)", dash: "2 3" },
  { key: "deleted", label: "Deleted", color: "var(--bad)", dash: "8 3 2 3" },
  { key: "timeouts", label: "Timeouts", color: "var(--warn)", dash: "1 4" },
  { key: "bans", label: "Bans", color: "var(--live)", dash: "10 4" },
];
interface Pt { t: number; [k: string]: number }
interface Hist { res: "hour" | "day"; step: number; points: Pt[] }
const RANGES: { id: string; label: string; days: number }[] = [
  { id: "1d", label: "24 h", days: 1 }, { id: "7d", label: "7 days", days: 7 }, { id: "30d", label: "30 days", days: 30 },
  { id: "90d", label: "90 days", days: 90 }, { id: "1y", label: "1 year", days: 365 }, { id: "all", label: "All", days: 1826 },
];
const nf = (n: number): string => n.toLocaleString();

function fmtT(t: number, res: "hour" | "day", long = false): string {
  const d = new Date(t * 1000);
  if (res === "day") return d.toLocaleDateString(undefined, long ? { weekday: "short", day: "numeric", month: "short", year: "numeric" } : { day: "numeric", month: "short" });
  return d.toLocaleString(undefined, long ? { weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" } : { day: "numeric", month: "short", hour: "2-digit" });
}
function niceMax(v: number): number {
  if (v <= 4) return 4;
  const p = Math.pow(10, Math.floor(Math.log10(v)));
  for (const m of [1, 2, 2.5, 5, 10]) if (v <= m * p) return m * p;
  return 10 * p;
}

export function csv(points: Pt[], keys: string[], res: "hour" | "day"): string {
  const head = ["time", ...keys].join(",");
  return [head, ...points.map((p) => [new Date(p.t * 1000).toISOString(), ...keys.map((k) => p[k] ?? 0)].join(","))].join("\n");
}
function download(name: string, blob: Blob): void {
  const url = URL.createObjectURL(blob);
  const a = h("a", { href: url, download: name }) as HTMLAnchorElement;
  document.body.append(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(url), 2000);
}

/** Open the detail view. `initial` are the series switched on at first. */
export function openChartDetail(title: string, initial: string[] = ["messages", "flagged"], range = "7d"): void {
  const on = new Set(initial);
  let rangeId = range, compare = false, asTable = false, hist: Hist | null = null, prev: Hist | null = null;
  const body = h("div", { class: "cd" });
  const chartBox = h("div", { class: "cd-chart", tabindex: 0, "aria-label": "Chart. Use the left and right arrow keys to move through the points." });
  const tip = h("div", { class: "chart-tip", hidden: true });
  const stats = h("div", { class: "figures" });
  const status = h("p", { class: "muted small", role: "status" });
  const kept = h("p", { class: "muted small" });
  const sh = sheet(title, body, () => ro.disconnect());
  document.querySelector(".overlay:last-of-type .sheet")?.classList.add("wide");

  const chips = h("div", { class: "seg-control scroll-x", role: "group", "aria-label": "Range" });
  const toggles = h("div", { class: "row wrap cd-series", role: "group", "aria-label": "Series" });
  const cmp = h("label", { class: "check small" }, h("input", { type: "checkbox", onchange: (e: Event) => { compare = (e.target as HTMLInputElement).checked; void load(); } }), "Compare with the period before");
  const tableBtn = h("button", { class: "btn small", type: "button", onclick: () => { asTable = !asTable; tableBtn.firstElementChild?.replaceWith(icon(asTable ? "chart" : "list", 15)); tableBtn.lastChild!.textContent = asTable ? "Show chart" : "Show table"; draw(); } }, icon("list", 15), "Show table");
  const csvBtn = h("button", { class: "btn small", type: "button", onclick: () => { if (hist) download("savahbot-history.csv", new Blob([csv(hist.points, [...on], hist.res)], { type: "text/csv" })); } }, icon("download", 15), "CSV");
  const pngBtn = h("button", { class: "btn small", type: "button", onclick: () => void png() }, icon("download", 15), "Image");

  const paintChips = () => mount(chips, RANGES.map((r) => h("button", { type: "button", "aria-pressed": String(r.id === rangeId), onclick: () => { rangeId = r.id; paintChips(); void load(); } }, r.label)));
  const paintToggles = () => mount(toggles, HISTORY_SERIES.map((d) => {
    const b = h("button", { class: "chip cd-toggle", type: "button", "aria-pressed": String(on.has(d.key)), onclick: () => { if (on.has(d.key) && on.size === 1) return; on.has(d.key) ? on.delete(d.key) : on.add(d.key); paintToggles(); draw(); } },
      h("span", { class: "cd-key", style: `background:${d.color}` }), d.label);
    return b;
  }));

  mount(body, h("div", { class: "k-stack" }, chips, toggles, h("div", { class: "row wrap", style: "gap:10px" }, cmp, tableBtn, csvBtn, pngBtn), stats, h("div", { class: "chart cd-wrap" }, chartBox, tip), status, kept));
  paintChips(); paintToggles();

  async function fetchRange(days: number, until: number): Promise<Hist> {
    return get<Hist>(`/api/history?since=${Math.floor(until - days * 86400)}&until=${Math.floor(until)}`);
  }
  async function load(): Promise<void> {
    status.textContent = "Loading...";
    try {
      const days = RANGES.find((r) => r.id === rangeId)!.days;
      const now = Date.now() / 1000;
      hist = await fetchRange(days, now);
      if (rangeId === "all") {   // skip the empty stretch before the first data
        const first = hist.points.findIndex((p) => HISTORY_SERIES.some((d) => p[d.key] > 0));
        if (first > 0) hist.points = hist.points.slice(first);
      }
      prev = compare ? await fetchRange(days, now - days * 86400) : null;
      status.textContent = "";
    } catch (e) { status.textContent = e instanceof Error ? e.message : "Could not load history."; toast(status.textContent, "error"); }
    draw();
  }

  let selected = -1;
  function draw(): void {
    if (!hist) return;
    const pts = hist.points, keys = HISTORY_SERIES.filter((d) => on.has(d.key));
    mount(stats, keys.map((d) => {
      const tot = pts.reduce((a, p) => a + p[d.key], 0), peak = Math.max(0, ...pts.map((p) => p[d.key]));
      return h("div", { class: "fig" }, h("strong", null, d.key === "chatters" ? nf(peak) : nf(tot)), h("span", null, d.key === "chatters" ? `${d.label}, busiest ${hist!.res}` : `${d.label}, peak ${nf(peak)}`));
    }));
    if (asTable) { chartBox.replaceChildren(table(pts, keys)); return; }
    const width = Math.max(260, Math.floor(chartBox.clientWidth || 320)), height = width < 520 ? 240 : 320;
    const m = { l: 40, r: 10, t: 12, b: 28 };
    const iw = width - m.l - m.r, ih = height - m.t - m.b;
    const maxV = niceMax(Math.max(1, ...keys.map((d) => Math.max(...pts.map((p) => p[d.key]), ...(prev ? prev.points.map((p) => p[d.key]) : [0])))));
    const x = (i: number) => m.l + (pts.length > 1 ? (i / (pts.length - 1)) * iw : iw / 2);
    const y = (v: number) => m.t + ih - (v / maxV) * ih;
    const g = s("svg", { viewBox: `0 0 ${width} ${height}`, width, height, class: "chart-svg", role: "img", "aria-label": `${title}: ${keys.map((k) => k.label).join(", ")}` });
    for (let k = 0; k <= 4; k++) { const v = (maxV / 4) * k; g.append(s("line", { x1: m.l, x2: width - m.r, y1: y(v), y2: y(v), class: "grid" }), s("text", { x: m.l - 6, y: y(v) + 4, "text-anchor": "end", class: "axis" }, nf(Math.round(v)))); }
    const ticks = Math.min(width < 520 ? 4 : 7, pts.length);
    for (let k = 0; k < ticks && pts.length > 1; k++) { const i = Math.round((k / Math.max(1, ticks - 1)) * (pts.length - 1)); g.append(s("text", { x: x(i), y: height - 8, "text-anchor": k === 0 ? "start" : k === ticks - 1 ? "end" : "middle", class: "axis" }, fmtT(pts[i].t, hist.res))); }
    const line = (arr: Pt[], key: string) => arr.map((p, i) => `${i ? "L" : "M"}${x(i).toFixed(1)} ${y(p[key]).toFixed(1)}`).join("");
    for (const d of keys) {
      if (prev && prev.points.length === pts.length) g.append(s("path", { d: line(prev.points, d.key), fill: "none", stroke: d.color, "stroke-width": 1.5, opacity: 0.4, "stroke-dasharray": "2 4" }));
      g.append(s("path", { d: line(pts, d.key), fill: "none", stroke: d.color, "stroke-width": 2, "stroke-linejoin": "round", ...(d.dash ? { "stroke-dasharray": d.dash } : {}) }));
    }
    const cursor = s("line", { y1: m.t, y2: m.t + ih, class: "cursor", visibility: "hidden" });
    const dots = keys.map((d) => s("circle", { r: 4, fill: d.color, stroke: "var(--panel)", "stroke-width": 2, visibility: "hidden" }));
    g.append(cursor, ...dots);
    const show = (i: number) => {
      i = Math.max(0, Math.min(pts.length - 1, i)); selected = i;
      const p = pts[i];
      cursor.setAttribute("x1", String(x(i))); cursor.setAttribute("x2", String(x(i))); cursor.setAttribute("visibility", "visible");
      keys.forEach((d, k) => { dots[k].setAttribute("cx", String(x(i))); dots[k].setAttribute("cy", String(y(p[d.key]))); dots[k].setAttribute("visibility", "visible"); });
      tip.hidden = false;
      tip.replaceChildren(h("strong", null, fmtT(p.t, hist!.res, true)), ...keys.map((d) => h("div", null, `${d.label}: ${nf(p[d.key])}${prev && prev.points[i] ? ` (before: ${nf(prev.points[i][d.key])})` : ""}`)));
      const tw = tip.offsetWidth;
      tip.style.left = `${Math.max(4, Math.min(width - tw - 4, x(i) - tw / 2))}px`;
    };
    const hide = () => { cursor.setAttribute("visibility", "hidden"); dots.forEach((d) => d.setAttribute("visibility", "hidden")); tip.hidden = true; };
    const move = (ev: PointerEvent) => { const r = g.getBoundingClientRect(); show(Math.round((((ev.clientX - r.left) / r.width) * width - m.l) / iw * (pts.length - 1))); };
    g.addEventListener("pointermove", move); g.addEventListener("pointerdown", move); g.addEventListener("pointerleave", hide);
    chartBox.onkeydown = (e) => {
      if (e.key === "ArrowLeft") { show((selected < 0 ? pts.length : selected) - 1); e.preventDefault(); }
      else if (e.key === "ArrowRight") { show(selected + 1); e.preventDefault(); }
      else if (e.key === "Home") { show(0); e.preventDefault(); } else if (e.key === "End") { show(pts.length - 1); e.preventDefault(); }
      else if (e.key === "Escape" && selected >= 0) { hide(); selected = -1; e.stopPropagation(); }
    };
    chartBox.replaceChildren(g);
    if (!pts.some((p) => keys.some((d) => p[d.key] > 0))) chartBox.append(h("p", { class: "muted small", style: "text-align:center;padding:8px" }, "Nothing was recorded in this range."));
  }

  function table(pts: Pt[], keys: SeriesDef[]): HTMLElement {
    const rows = pts.slice().reverse().slice(0, 500);
    return h("div", { class: "table-wrap", style: "max-height:320px;overflow:auto" }, h("table", null,
      h("thead", null, h("tr", null, h("th", null, "When"), keys.map((d) => h("th", null, d.label)))),
      h("tbody", null, rows.map((p) => h("tr", null, h("td", null, fmtT(p.t, hist!.res, true)), keys.map((d) => h("td", null, nf(p[d.key])))))))
      , pts.length > 500 ? h("p", { class: "muted small" }, "Showing the newest 500 rows. Export the CSV for all of them.") : null);
  }

  async function png(): Promise<void> {
    const svg = chartBox.querySelector("svg");
    if (!svg) { toast("Switch to the chart first.", "error"); return; }
    const cs = getComputedStyle(document.documentElement);
    let xml = new XMLSerializer().serializeToString(svg);
    for (const v of ["--accent", "--demo", "--ok", "--bad", "--warn", "--live", "--panel", "--line", "--muted"]) xml = xml.split(`var(${v})`).join(cs.getPropertyValue(v).trim());
    xml = xml.replace("<svg ", `<svg xmlns="${NS}" `).replace(/class="grid"/g, `stroke="${cs.getPropertyValue("--line").trim()}"`).replace(/class="axis"/g, `fill="${cs.getPropertyValue("--muted").trim()}" font-size="11"`)
      .replace(/class="cursor"/g, 'visibility="hidden"');
    const w = Number(svg.getAttribute("width")), hh = Number(svg.getAttribute("height")), scale = 2;
    const img = new Image();
    img.onload = () => {
      const c = document.createElement("canvas"); c.width = w * scale; c.height = (hh + 28) * scale;
      const ctx = c.getContext("2d")!; ctx.scale(scale, scale);
      ctx.fillStyle = cs.getPropertyValue("--panel").trim() || "#fff"; ctx.fillRect(0, 0, w, hh + 28);
      ctx.fillStyle = cs.getPropertyValue("--ink").trim() || "#000"; ctx.font = "600 13px sans-serif"; ctx.fillText(`${title} · ${RANGES.find((r) => r.id === rangeId)!.label}`, 10, 18);
      ctx.drawImage(img, 0, 24);
      c.toBlob((b) => { if (b) download("savahbot-chart.png", b); }, "image/png");
    };
    img.onerror = () => toast("Your browser could not make the image.", "error");
    img.src = `data:image/svg+xml;charset=utf-8,${encodeURIComponent(xml)}`;
  }

  const ro = new ResizeObserver(() => { if (hist && !asTable) draw(); });
  ro.observe(chartBox);
  void get<{ daily: { rows: number; oldest: number | null }; retention: { chat_days: number } }>("/api/history/storage").then((st) => {
    kept.textContent = `Daily totals are kept forever${st.daily.oldest ? `, starting ${fmtT(st.daily.oldest, "day", true)}` : ""}. Individual chat messages are kept for ${st.retention.chat_days} days.`;
  }).catch(() => undefined);
  void load();
  void sh;
}

/** Make a chart card openable: adds a clear "Expand" button (good for touch and screen readers) and makes the chart itself tappable. */
export function expandable(card: HTMLElement, open: () => void): HTMLElement {
  const head = card.querySelector("header");
  const btn = h("button", { class: "btn small", type: "button", onclick: open, "aria-label": "Open a bigger view with more history" }, icon("expand", 15), "Expand");
  head?.append(btn);
  return card;
}
