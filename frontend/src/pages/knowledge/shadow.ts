import { get, post } from "../../api.js";
import { busy, dateTime, h, mount, toast } from "../../dom.js";
import { icon } from "../../icons.js";
import { empty } from "../shared.js";
import { SIGNAL, avatar, invite, niceName, plural, seg } from "../widgets.js";
import { DET_ICON, type DetectorInfo, modeChip, n0, pct, setSetting } from "./common.js";

interface Det extends DetectorInfo { hits: number; differs: number; authors: number; agreed: number; disagreed: number; precision: number | null }
interface Finding { id: number; ts: number; author_name: string; author_id: string; body: string; detector: string; signal: string; weight: number; detail: string; would: string; actual: string; label: string; demo: number }
interface Report { hours: number; detectors: Det[]; recent: Finding[]; total: number; series: { t: number; hits: number; differs: number }[]; bucket: number }

const RANGES: [number, string][] = [[24, "24 hours"], [72, "3 days"], [168, "7 days"], [720, "30 days"]];
const ACTION: Record<string, string> = { allow: "allow it", flag: "flag it", delete: "delete it", timeout: "time out", ban: "ban" };

export function renderShadow(root: HTMLElement, query: URLSearchParams): void {
  let hours = 168;
  let detector = query.get("detector") ?? "";
  let onlyDiffers = false;
  let limit = 30;
  let rep: Report | null = null;
  const top = h("div");
  const list = h("div");
  const more = h("div", { class: "row center" });

  const rangeSeg = seg("Time range", RANGES.map(([v, l]) => ({ id: String(v), label: l })), String(hours), (v) => { hours = Number(v); limit = 30; void load(); });

  const bars = (r: Report): HTMLElement => {
    const max = Math.max(1, ...r.series.map((p) => p.hits));
    return h("div", { class: "sh-bars", role: "img", "aria-label": `Shadow findings over time. ${r.series.reduce((a, p) => a + p.hits, 0)} findings in total.` },
      r.series.slice(-60).map((p) => h("span", { class: "sh-bar", title: `${new Date(p.t * 1000).toLocaleString([], { month: "short", day: "numeric", hour: "numeric" })}: ${p.hits} findings, ${p.differs} would change the outcome` },
        h("i", { class: "all", style: `height:${Math.max(4, (p.hits / max) * 100)}%` }), h("i", { class: "chg", style: `height:${(p.differs / max) * 100}%` }))));
  };

  const detCard = (d: Det): HTMLElement => {
    const labelled = d.agreed + d.disagreed;
    const ready = labelled >= 5 && (d.precision ?? 0) >= 0.85;
    const verdict = d.hits === 0 ? ["", "Nothing found yet."] : labelled < 5 ? ["", `Needs more of your decisions to judge (${labelled} so far).`] : ready ? ["ok", "Mostly right where you decided. Ready to switch on."] : (d.precision ?? 0) < 0.6 ? ["bad", "Often wrong where you decided. Keep it in shadow, or lower its sensitivity."] : ["warn", "Mixed. Keep watching."];
    const go = h("button", { class: `btn small ${ready ? "primary" : "ghost"}`, type: "button", disabled: d.mode === "active" }, icon("zap", 14), d.mode === "active" ? "Active" : "Switch to Active");
    go.addEventListener("click", () => busy(go, async () => { if (!(await setSetting(`intel_${d.id}_mode`, "active", `${d.title}: active`))) return; await load(); }));
    return h("article", { class: `sh-det ${verdict[0]}` },
      h("div", { class: "det-top" }, h("span", { class: "scn-ico" }, icon(DET_ICON[d.id] ?? "sliders", 20)), h("div", { class: "scn-title" }, h("strong", null, d.title), modeChip(d.mode))),
      h("div", { class: "kn-figs tight" }, h("div", { class: "fig" }, h("b", null, n0(d.hits)), h("span", null, "findings")), h("div", { class: "fig" }, h("b", null, n0(d.differs)), h("span", null, "would change it")), h("div", { class: "fig" }, h("b", null, pct(d.precision)), h("span", null, "right where you decided"))),
      h("p", { class: `muted small sh-verdict ${verdict[0]}` }, verdict[1]),
      h("div", { class: "row between" }, h("button", { class: "link-quiet", type: "button", onclick: () => { detector = detector === d.id ? "" : d.id; limit = 30; void load(); } }, icon("search", 14), detector === d.id ? "Showing only these" : "Show only these"), go));
  };

  const drawTop = (r: Report) => {
    const changed = r.detectors.reduce((a, d) => a + d.differs, 0), hits = r.detectors.reduce((a, d) => a + d.hits, 0);
    mount(top, h("div", { class: "stack" },
      h("section", { class: "wb mind" }, h("div", { class: "mind-top" }, h("div", null, h("h2", null, hits ? `${plural(changed, "message")} would have gone differently` : "No shadow findings yet"),
        h("p", { class: "lede" }, hits ? `In this time, detectors in Shadow mode found something in ${plural(hits, "message")}. The orange bars mark where a detector would have changed what happened, had it been Active. Nothing here has affected chat.` : "Detectors in Shadow mode record what they would do, without doing it. When chat has activity, it appears here.")), rangeSeg.el), r.series.length ? bars(r) : null,
        h("div", { class: "legend-inline" }, h("span", null, h("i", { class: "sw s1" }), "Findings"), h("span", null, h("i", { class: "sw s2" }), "Would change the outcome"))),
      h("div", { class: "sh-dets" }, r.detectors.filter((d) => d.mode !== "off" || d.hits).map(detCard))));
  };

  const teachBtn = (f: Finding, l: "spam" | "ham") => {
    const b = h("button", { class: `btn small ${l === "spam" ? "bad-btn" : "ok-btn"}${f.label === l ? " on" : ""}`, type: "button", "aria-pressed": String(f.label === l) }, icon(l === "spam" ? "ban" : "check", 14), l === "spam" ? "Spam" : "Fine");
    b.addEventListener("click", () => busy(b, async () => { await post("/api/intel/teach", { label: l, text: f.body, author: f.author_name }); f.label = l; await load(false); }, l === "spam" ? "Learned: spam" : "Learned: fine"));
    return b;
  };
  const drawList = (r: Report) => {
    if (!r.recent.length) { mount(list, invite("eyeOff", "No findings to show", onlyDiffers ? "Nothing would have changed the outcome in this time." : "Shadow detectors have not found anything in this time range.")); mount(more, null); return; }
    mount(list, h("ul", { class: "findings" }, r.recent.map((f) => h("li", { class: f.would !== f.actual ? "differs" : "" },
      avatar(f.author_name, 34),
      h("div", { class: "fd-main" },
        h("div", { class: "row between nowrap" }, h("strong", { class: "wrap" }, f.author_name || "Someone"), h("span", { class: "muted small" }, dateTime(f.ts))),
        h("p", { class: "fd-body wrap" }, f.body),
        h("div", { class: "chip-row tight" }, h("span", { class: "chip accent" }, niceName(SIGNAL, f.signal), f.weight ? ` ${f.weight > 0 ? "+" : ""}${f.weight}` : ""), f.would !== f.actual ? h("span", { class: "chip warn" }, `Bot ${f.actual === "allow" ? "let it through" : f.actual}, shadow would ${ACTION[f.would] ?? f.would}`) : h("span", { class: "chip" }, "Would not change the outcome"), f.demo ? h("span", { class: "chip" }, "demo") : null),
        f.detail ? h("span", { class: "muted small wrap" }, f.detail) : null,
        h("div", { class: "row" }, teachBtn(f, "spam"), teachBtn(f, "ham"), f.label ? h("span", { class: "muted small" }, f.label === "spam" ? "You said spam" : "You said fine") : null))))));
    mount(more, r.total > r.recent.length ? h("button", { class: "btn ghost", type: "button", onclick: () => { limit += 30; void load(false); } }, `Show more (${n0(r.total - r.recent.length)} left)`) : null);
  };
  const filters = h("div", { class: "row between wrap-row" },
    h("label", { class: "check small" }, h("input", { type: "checkbox", class: "switch", "aria-label": "Only findings that would change the outcome", onchange: (e: Event) => { onlyDiffers = (e.target as HTMLInputElement).checked; limit = 30; void load(false); } }), "Only ones that would change the outcome"));

  const load = async (redrawTop = true) => {
    const q = new URLSearchParams({ hours: String(hours), limit: String(limit) });
    if (detector) q.set("detector", detector);
    if (onlyDiffers) q.set("differs", "1");
    rep = await get<Report>(`/api/intel/shadow?${q.toString()}`);
    if (redrawTop) drawTop(rep);
    drawList(rep);
  };
  mount(root, h("div", { class: "stack" }, top,
    h("section", { class: "nb-list" }, h("h3", { class: "coll-title" }, icon("eyeOff", 14), "What they found"), filters, list, more)));
  void load().catch((e) => { toast(e.message, "error"); mount(top, empty("alert", "Could not load the report.")); });
}
