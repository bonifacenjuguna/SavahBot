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

const KEYS = { accent: "savahbot.accent", density: "savahbot.density", motion: "savahbot.motion", text: "savahbot.text", toastMode: "savahbot.toast.mode", toastPos: "savahbot.toast.pos", toastSecs: "savahbot.toast.secs" } as const;
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
export function initAppearance(): void { set("data-toast-pos", toastPos(), "bottom"); set("data-text", textPref(), "normal"); set("data-accent", accentPref(), "default"); set("data-density", densityPref(), "comfortable"); set("data-motion", motionPref(), "system"); }

// ---------------------------------------------------------------- pop-up notices (toasts), 1.3.3
/** The small messages that slide in over the page ("Saved", "Copied", errors). Kept on this device. */
export type ToastMode = "all" | "errors" | "off";
export type ToastPos = "bottom" | "top";
export const TOAST_SECS = { min: 1, max: 15, def: 3 } as const;
export const toastMode = (): ToastMode => (read(KEYS.toastMode) === "errors" || read(KEYS.toastMode) === "off" ? (read(KEYS.toastMode) as ToastMode) : "all");
export const toastPos = (): ToastPos => (read(KEYS.toastPos) === "top" ? "top" : "bottom");
export const toastSecs = (): number => { const n = Number(read(KEYS.toastSecs)); return Number.isFinite(n) && n >= TOAST_SECS.min && n <= TOAST_SECS.max ? n : TOAST_SECS.def; };
export function setToastMode(m: ToastMode): void { write(KEYS.toastMode, m, "all"); }
export function setToastPos(p: ToastPos): void { write(KEYS.toastPos, p, "bottom"); set("data-toast-pos", p, "bottom"); }
export function setToastSecs(n: number): void { write(KEYS.toastSecs, String(Math.round(n)), String(TOAST_SECS.def)); }
