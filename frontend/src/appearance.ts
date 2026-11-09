/** Appearance preferences kept on this device: accent colour, density and motion. Theme (light/dark) lives in ui.ts. */
export type Accent = "default" | "teal" | "violet" | "rose" | "amber" | "green";
export type Density = "comfortable" | "compact";
export type Motion = "system" | "reduce";
export type TextSize = "normal" | "large" | "larger";

export const ACCENTS: { id: Accent; label: string; swatch: string }[] = [
  { id: "default", label: "Indigo", swatch: "#2442d6" },
  { id: "teal", label: "Teal", swatch: "#0f766e" },
  { id: "violet", label: "Violet", swatch: "#6d3fd1" },
  { id: "rose", label: "Rose", swatch: "#c02657" },
  { id: "amber", label: "Amber", swatch: "#9a5200" },
  { id: "green", label: "Green", swatch: "#15803d" },
];

const KEYS = { accent: "savahbot.accent", density: "savahbot.density", motion: "savahbot.motion", text: "savahbot.text" } as const;
const read = (k: string): string => { try { return localStorage.getItem(k) ?? ""; } catch { return ""; } };
const write = (k: string, v: string, fallback: string): void => { try { if (v === fallback) localStorage.removeItem(k); else localStorage.setItem(k, v); } catch { /* private mode: lasts for this visit */ } };

export const accentPref = (): Accent => (ACCENTS.some((a) => a.id === read(KEYS.accent)) ? (read(KEYS.accent) as Accent) : "default");
export const densityPref = (): Density => (read(KEYS.density) === "compact" ? "compact" : "comfortable");
export const textPref = (): TextSize => (read(KEYS.text) === "large" || read(KEYS.text) === "larger" ? (read(KEYS.text) as TextSize) : "normal");
export const motionPref = (): Motion => (read(KEYS.motion) === "reduce" ? "reduce" : "system");

function set(attr: string, value: string, off: string): void {
  const root = document.documentElement;
  if (value === off) root.removeAttribute(attr); else root.setAttribute(attr, value);
}
export function setAccent(a: Accent): void { write(KEYS.accent, a, "default"); set("data-accent", a, "default"); window.dispatchEvent(new Event("themechange")); }
export function setDensity(d: Density): void { write(KEYS.density, d, "comfortable"); set("data-density", d, "comfortable"); }
export function setMotion(m: Motion): void { write(KEYS.motion, m, "system"); set("data-motion", m, "system"); }
export function setText(t: TextSize): void { write(KEYS.text, t, "normal"); set("data-text", t, "normal"); }
export function initAppearance(): void { set("data-text", textPref(), "normal"); set("data-accent", accentPref(), "default"); set("data-density", densityPref(), "comfortable"); set("data-motion", motionPref(), "system"); }
