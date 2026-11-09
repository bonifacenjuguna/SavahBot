/** 1.1.5 widget kit shared by Notebook, Community, Insights, Demo and the Moderation tools. Plain DOM, no dependencies. */
import { h, type Child } from "../dom.js";
import { icon } from "../icons.js";

export const plural = (n: number, one: string, many = `${one}s`): string => `${n.toLocaleString()} ${n === 1 ? one : many}`;
export const sentence = (t: string): string => (t ? t[0].toUpperCase() + t.slice(1) : t);

// ------------------------------------------------------------------ segmented control
export interface Seg<T extends string> { el: HTMLElement; set(v: T): void; get(): T }

/** A row of mutually exclusive buttons. `onChange` fires only on a real change by the person. */
export function seg<T extends string>(label: string, options: { id: T; label: string; icon?: string }[], value: T, onChange: (v: T) => void): Seg<T> {
  let current = value;
  const buttons = options.map((o) => h("button", { type: "button", "data-id": o.id, "aria-pressed": String(o.id === current) }, o.icon ? icon(o.icon, 15) : null, o.label));
  const paint = () => buttons.forEach((b) => {
    const on = b.getAttribute("data-id") === current;
    b.setAttribute("aria-pressed", String(on));
    if (on) queueMicrotask(() => { try { b.scrollIntoView({ block: "nearest", inline: "center" }); } catch { /* old browsers: the bar simply stays where it is */ } });
  });
  buttons.forEach((b) => b.addEventListener("click", () => { const v = b.getAttribute("data-id") as T; if (v === current) return; current = v; paint(); onChange(v); }));
  const el = h("div", { class: "seg-control", role: "group", "aria-label": label }, buttons);
  return { el, set: (v) => { current = v; paint(); }, get: () => current };
}

// ------------------------------------------------------------------ small controls
/** Icon-only action with a text label for screen readers and a tooltip. */
export function iconAct(name: string, label: string, onclick: (e: Event) => void, tone: "" | "danger" | "accent" = ""): HTMLButtonElement {
  return h("button", { class: `icon-act${tone ? " " + tone : ""}`, type: "button", "aria-label": label, title: label, onclick }, icon(name, 18));
}

/**
 * A destructive button that asks once. The first tap turns it into "Sure?" for three seconds; the second tap does the work.
 * Used where an undo is not possible, e.g. quotes, whose numbers viewers type into chat.
 */
export function confirmAct(opts: { icon: string; label: string; confirmText?: string; onConfirm: () => Promise<unknown> | void; text?: string }): HTMLButtonElement {
  let armed = false;
  let timer = 0;
  const b = h("button", { class: `icon-act danger${opts.text ? " with-text" : ""}`, type: "button", "aria-label": opts.label, title: opts.label });
  const paint = () => {
    b.classList.toggle("armed", armed);
    b.replaceChildren(icon(armed ? "check" : opts.icon, 18), ...(armed ? [h("span", null, opts.confirmText ?? "Sure?")] : opts.text ? [h("span", null, opts.text)] : []));
    b.setAttribute("aria-label", armed ? `${opts.label}: tap again to confirm` : opts.label);
  };
  b.addEventListener("click", () => {
    if (!armed) { armed = true; paint(); timer = window.setTimeout(() => { armed = false; paint(); }, 3000); return; }
    window.clearTimeout(timer);
    armed = false;
    b.disabled = true;
    Promise.resolve(opts.onConfirm()).finally(() => { b.disabled = false; paint(); });
  });
  paint();
  return b;
}

/** Letters on a calm, name-based colour. Colours are fixed lightness so white text stays readable in both themes. */
export function avatar(name: string, size = 38): HTMLElement {
  const clean = name.replace(/^@/, "").trim() || "?";
  const words = clean.split(/[\s._-]+/).filter(Boolean);
  const letters = (words.length > 1 ? words[0][0] + words[1][0] : clean.slice(0, 2)).toUpperCase();
  let hash = 0;
  for (const ch of clean) hash = (hash * 31 + ch.charCodeAt(0)) >>> 0;
  return h("span", { class: "avatar", "aria-hidden": "true", style: `--h:${hash % 360};--s:${size}px` }, letters);
}

/** Grows a textarea with its content, up to `max` pixels. */
export function autoGrow(el: HTMLTextAreaElement, max = 360): void {
  const fit = () => { el.style.height = "auto"; el.style.height = `${Math.min(max, el.scrollHeight + 2)}px`; };
  el.addEventListener("input", fit);
  requestAnimationFrame(fit);
  (el as HTMLTextAreaElement & { refit?: () => void }).refit = fit;
}

/** "Today, 12:34 AM", "Yesterday, 9:05 PM" or "Nov 3, 4:10 PM". */
export function dayTime(ts: number, now = new Date()): string {
  const d = new Date(ts * 1000);
  const time = d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
  const day = (x: Date) => new Date(x.getFullYear(), x.getMonth(), x.getDate()).getTime();
  const diff = Math.round((day(now) - day(d)) / 86400000);
  if (diff === 0) return `Today, ${time}`;
  if (diff === 1) return `Yesterday, ${time}`;
  return `${d.toLocaleDateString([], { month: "short", day: "numeric" })}, ${time}`;
}

const URL_RE = /\bhttps?:\/\/[^\s<>"']+/gi;
/** Text with web links turned into anchors. Everything else stays text, so nothing typed can become markup. */
export function linkify(text: string): Child[] {
  const out: Child[] = [];
  let last = 0;
  for (const m of text.matchAll(URL_RE)) {
    const start = m.index ?? 0;
    let url = m[0];
    const tail = /[.,;:!?)\]]+$/.exec(url)?.[0] ?? "";
    if (tail) url = url.slice(0, -tail.length);
    if (start > last) out.push(text.slice(last, start));
    out.push(h("a", { href: url, target: "_blank", rel: "noopener noreferrer" }, url));
    last = start + url.length;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

/** A row of figures: value on top, a short label under it. */
export function figures(items: { value: string; label: string; tone?: "" | "ok" | "warn" | "bad" }[]): HTMLElement {
  return h("div", { class: "figures" }, items.map((i) => h("div", { class: `fig${i.tone ? " " + i.tone : ""}` }, h("b", null, i.value), h("span", null, i.label))));
}

/** The empty moment: say what this place is for and offer the first step. */
export function invite(iconName: string, title: string, text: string, action?: HTMLElement | null): HTMLElement {
  return h("div", { class: "invite" }, h("span", { class: "invite-ico" }, icon(iconName, 26)), h("strong", null, title), h("p", null, text), action ?? null);
}

/** Lead-in line used under a workbench heading. */
export function lede(text: string): HTMLElement { return h("p", { class: "lede" }, text); }

/** What the moderation signals mean, in words a person running a stream would use. */
export const SIGNAL: Record<string, string> = {
  blacklist: "Blocked phrase", link: "Link", new_chatter: "New chatter", caps: "Shouting", repetition: "Repetition", repeat: "Repetition",
  emotes: "Emote spam", emote: "Emote spam", symbols: "Symbol spam", length: "Very long message", mention: "Mention spam",
  rate: "Message flood", duplicate: "Repeated message", raid: "Copy-paste raid", timing: "Bot-like timing",
  knowledge: "Knowledge pack", fuzzy: "Close to a blocked phrase", learned: "Learned from your decisions", link_risk: "Risky link", reputation: "Chatter history",
  scam_pattern: "Scam pattern", bot_shape: "Bot-like shape", evasion: "Disguised text", lookalike_name: "Lookalike name",
};
export const niceName = (map: Record<string, string>, key: string): string => map[key] ?? sentence(String(key).replace(/_/g, " "));
