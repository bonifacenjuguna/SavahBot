/** Shared types and small helpers for the Knowledge section (Settings > Knowledge). */
import { h } from "../dom.js";
import { card } from "./shared.js";
import { SIGNAL, niceName, seg } from "./widgets.js";
import { navigate } from "../router.js";

export type Mode = "off" | "shadow" | "live";
export type View = "overview" | "packs" | "detectors" | "learning" | "live" | "test";

export interface PackInfo {
  id: string; category: string; title: string; description: string; kind: string; lang: string; signal: string; role: string;
  version: string; source: string; license: string; weight: number; fuzzy: boolean; needs_target: boolean;
  mode: Mode; default_mode: Mode; overridden: boolean; scale: number; entries: number; entries_builtin: number; entries_added: number;
  editable: boolean; language_off: boolean;
}
export interface Category { id: string; title: string; about: string; packs: PackInfo[]; entries: number; active: number }
export interface Entry { phrase: string; regex: boolean; builtin: boolean; source: string; enabled: boolean; weight: number; default_weight: number; edited: boolean }
export interface Detector {
  id: string; title: string; about: string; example: string; mode: Mode; scale: number; learned_scale: number; default_mode: Mode;
  packs: { id: string; title: string }[]; live_hits: number; shadow_hits: number;
}
export interface Shadow { ts: number; text: string; detector: string; weight: number; detail: string; author: string }
export interface Overview {
  status: { enabled: boolean; packs_total: number; packs_active: number; rules: number; typo_rules: number; domains: number; safe_phrases: number; examples: number; model_ready: boolean; build_ms: number; wave_active: boolean; waves_seen: number };
  detector_modes: Record<Mode, number>; detectors: Detector[]; next: { kind: string; text: string } | null;
  feeds: { enabled: number; total: number; entries: number; last_ok: number | null; errors: number; auto: boolean };
  recent_shadow: Shadow[]; categories: { id: string; title: string; entries: number; active: number; packs: number }[];
}
export interface Feed {
  id: string; title: string; url: string; format: string; about: string; license: string; homepage: string; custom: boolean; pack: string;
  enabled: boolean; entries: number; previous_entries: number; last_run: number | null; last_ok: number | null; status: string; error: string;
  can_rollback: boolean; next_due: number | null;
}
export interface Suggestion { id: number; kind: string; pack_id: string; body: string; detail: string; weight: number; evidence: number }
export interface LogRow { id: number; ts: number; kind: string; summary: string; undone: number }
export interface LearningData {
  stats: {
    decisions: number; approved: number; rejected: number; precision: number | null; learned_spam: number; learned_ham: number; examples: number;
    auto_changes: number; mode: string; last_refresh: number | null; scales: Record<string, number>;
    signals: { name: string; approved: number; rejected: number; precision: number | null; detector: boolean }[];
  };
  suggestions: Suggestion[]; log: LogRow[];
}

/** Names for every signal, old and new (they live in widgets.ts so the whole dashboard uses the same words). */
export const SIGNALS: Record<string, string> = SIGNAL;
export const signalName = (n: string): string => niceName(SIGNALS, n);

export const MODE_LABEL: Record<Mode, string> = { off: "Off", shadow: "Shadow", live: "Live" };
export const MODE_HELP: Record<Mode, string> = {
  off: "Does nothing.",
  shadow: "Watches and records what it would have caught, but never changes a score. Safe for trying things out.",
  live: "Adds to a message's score, like every other rule.",
};

/** Off / Shadow / Live switcher. `onChange` runs only on a real change by the person. */
export function modeSeg(label: string, value: Mode, onChange: (m: Mode) => void) {
  return seg<Mode>(label, (["off", "shadow", "live"] as Mode[]).map((m) => ({ id: m, label: MODE_LABEL[m] })), value, onChange);
}

/** Goes to a place inside Settings > Knowledge. The page redraws from the address, so the back button works. */
export function goKnowledge(view: View, extra: Record<string, string> = {}): void {
  const q = new URLSearchParams({ tab: "knowledge", view, ...extra });
  navigate(`/settings?${q.toString()}`);
}

export const pct = (v: number | null | undefined): string => (v === null || v === undefined ? "none yet" : `${Math.round(v * 100)}%`);

/** A small horizontal bar. `tone` colours it; width is a 0-1 fraction. */
export function meter(fraction: number, tone: "" | "ok" | "warn" | "bad" = ""): HTMLElement {
  const f = Math.max(0, Math.min(1, fraction));
  return h("span", { class: `kmeter${tone ? " " + tone : ""}`, role: "img", "aria-label": `${Math.round(f * 100)} percent` }, h("i", { style: `width:${(f * 100).toFixed(1)}%` }));
}

export const KIND_NAME: Record<string, string> = {
  phrases: "Phrases", facets: "Word groups", domains: "Domains", tlds: "Domain endings", words: "Words", domain_regex: "Address patterns",
  maps: "Letter map", corpus: "Training examples",
};
export const LANG_NAME: Record<string, string> = { en: "English", sw: "Swahili", sheng: "Sheng", any: "Any language" };
export const ago = (ts: number | null): string => {
  if (!ts) return "never";
  const s = Math.max(0, Date.now() / 1000 - ts);
  return s < 90 ? "just now" : s < 5400 ? `${Math.round(s / 60)} min ago` : s < 129600 ? `${Math.round(s / 3600)} h ago` : `${Math.round(s / 86400)} days ago`;
};

/** card() whose body gets the padding the rest of the dashboard's cards have (they pad children with class "body"). */
export function kcard(iconName: string | null, title: string, body: HTMLElement, opts: { flush?: boolean; actions?: HTMLElement | null; scroll?: boolean } = {}): HTMLElement {
  body.classList.add("body");
  return card(iconName, title, body, { flush: opts.flush, actions: opts.actions ?? undefined, scroll: opts.scroll });
}
