/** Shared pieces of the Knowledge section: view list, detector facts, small formatters and the settings call. */
import { patch } from "../../api.js";
import { h, toast } from "../../dom.js";
import { icon } from "../../icons.js";
import { refreshStatus } from "../../state.js";

export type View = "overview" | "packs" | "detectors" | "learning" | "shadow";
export const VIEWS: { id: View; title: string; icon: string; blurb: string }[] = [
  { id: "overview", title: "Overview", icon: "target", blurb: "The bot's mind at a glance" },
  { id: "packs", title: "Packs", icon: "package", blurb: "What it knows, by category" },
  { id: "detectors", title: "Detectors", icon: "sliders", blurb: "How it uses that knowledge" },
  { id: "learning", title: "Learning", icon: "sparkle", blurb: "What it learned from you" },
  { id: "shadow", title: "Shadow report", icon: "eyeOff", blurb: "What it would have done" },
];

export type Mode = "off" | "shadow" | "active";
export const MODES: { id: Mode; label: string; help: string }[] = [
  { id: "off", label: "Off", help: "Does not run at all." },
  { id: "shadow", label: "Shadow", help: "Runs and is logged. Never acts on chat." },
  { id: "active", label: "Active", help: "Adds points to the message score." },
];
export const DET_ICON: Record<string, string> = { packs: "package", fuzzy: "search", learning: "sparkle", links: "external", reputation: "star", scam: "alert", shape: "activity", evasion: "eyeOff", names: "user" };

export interface DetectorInfo {
  id: string; title: string; signal: string; description: string; needs_history: boolean; mode: Mode; weight: number; sensitivity: number;
  hits?: number; differs?: number; authors?: number;
}

export const pct = (x: number | null | undefined): string => (x === null || x === undefined ? "none yet" : `${Math.round(x * 100)}%`);
export const n0 = (n: number): string => n.toLocaleString();

export function modeChip(mode: Mode): HTMLElement {
  return h("span", { class: `chip mode-${mode}` }, icon(mode === "active" ? "zap" : mode === "shadow" ? "eyeOff" : "x", 12), MODES.find((m) => m.id === mode)?.label ?? mode);
}

/** Saves one setting the same way the main Settings page does, and tells the person. */
export async function setSetting(name: string, value: string | number | boolean, done = "Saved"): Promise<boolean> {
  try {
    await patch("/api/settings", { values: { [name]: value } });
    toast(done);
    void refreshStatus();
    return true;
  } catch (e) {
    toast((e as Error).message, "error");
    return false;
  }
}

export const hrefFor = (view: View, extra: Record<string, string> = {}): string => {
  const q = new URLSearchParams({ tab: "knowledge", view, ...extra });
  return `#/settings?${q.toString()}`;
};

/** The two-way switch at the top of Settings: every option, or the bot's knowledge. */
export function settingsTabs(active: "options" | "knowledge"): HTMLElement {
  return h("nav", { class: "seg-control settings-tabs", "aria-label": "Settings sections" },
    h("a", { href: "#/settings", "aria-current": active === "options" ? "page" : undefined }, icon("sliders", 16), "Options"),
    h("a", { href: "#/settings?tab=knowledge", "aria-current": active === "knowledge" ? "page" : undefined }, icon("sparkle", 16), "Knowledge"));
}

/** A small line chart in plain SVG: values 0 to 1 over time, with a dashed line for 'no better than guessing'. */
export function lineChart(points: { label: string; v: number }[], opts: { height?: number; guide?: number; aria: string }): SVGElement {
  const W = 600, H = opts.height ?? 140, pad = 8;
  const NS = "http://www.w3.org/2000/svg";
  const el = (name: string, attrs: Record<string, string>): SVGElement => { const e = document.createElementNS(NS, name); for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v); return e; };
  const svg = el("svg", { viewBox: `0 0 ${W} ${H}`, class: "linechart", role: "img", "aria-label": opts.aria, preserveAspectRatio: "none" });
  const y = (v: number) => pad + (1 - v) * (H - pad * 2);
  if (opts.guide !== undefined) svg.appendChild(el("line", { x1: "0", x2: String(W), y1: String(y(opts.guide)), y2: String(y(opts.guide)), class: "lc-guide" }));
  if (points.length >= 2) {
    const step = (W - pad * 2) / (points.length - 1);
    const xy = points.map((p, i) => `${pad + i * step},${y(p.v)}`);
    svg.appendChild(el("polygon", { points: `${pad},${H - pad} ${xy.join(" ")} ${pad + (points.length - 1) * step},${H - pad}`, class: "lc-area" }));
    svg.appendChild(el("polyline", { points: xy.join(" "), class: "lc-line", fill: "none" }));
    points.forEach((p, i) => { const c = el("circle", { cx: String(pad + i * step), cy: String(y(p.v)), r: "3", class: "lc-dot" }); const t = el("title", {}); t.textContent = `${p.label}: ${Math.round(p.v * 100)}%`; c.appendChild(t); svg.appendChild(c); });
  } else if (points.length === 1) {
    svg.appendChild(el("circle", { cx: String(W / 2), cy: String(y(points[0].v)), r: "4", class: "lc-dot" }));
  }
  return svg;
}
