import { h, mount } from "./dom.js";
import { icon } from "./icons.js";

/** A date range as picked in the UI: local calendar days written YYYY-MM-DD, "" meaning open on that side. */
export interface DateRange { from: string; to: string }

const DAY_RE = /^(\d{4})-(\d{2})-(\d{2})$/;

/** Local midnight of a YYYY-MM-DD string, or null if it is not a real calendar date (e.g. 2026-02-31). */
export function parseDay(value: string): Date | null {
  const m = DAY_RE.exec(value);
  if (!m) return null;
  const d = new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]));
  return d.getFullYear() === Number(m[1]) && d.getMonth() === Number(m[2]) - 1 && d.getDate() === Number(m[3]) ? d : null;
}

export function toDay(d: Date): string {
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}

export function isActive(r: DateRange): boolean { return Boolean(r.from || r.to); }

/** Returns a message if the range cannot be used, otherwise null. */
export function validateRange(r: DateRange): string | null {
  if (r.from && !parseDay(r.from)) return "The start date is not a valid date.";
  if (r.to && !parseDay(r.to)) return "The end date is not a valid date.";
  if (r.from && r.to && r.from > r.to) return "The start date must not be after the end date.";
  return null;
}

/** Unix-seconds bounds for the API: `since` is local midnight of the first day, `until` local midnight after the last day (exclusive). */
export function rangeToQuery(r: DateRange): { since?: number; until?: number } {
  const out: { since?: number; until?: number } = {};
  const a = r.from ? parseDay(r.from) : null;
  const b = r.to ? parseDay(r.to) : null;
  if (a) out.since = a.getTime() / 1000;
  if (b) out.until = new Date(b.getFullYear(), b.getMonth(), b.getDate() + 1).getTime() / 1000;
  return out;
}

export function rangeLabel(r: DateRange): string {
  const fmt = (v: string) => { const d = parseDay(v); return d ? d.toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" }) : v; };
  if (r.from && r.to) return r.from === r.to ? fmt(r.from) : `${fmt(r.from)} to ${fmt(r.to)}`;
  return r.from ? `From ${fmt(r.from)}` : r.to ? `Up to ${fmt(r.to)}` : "All dates";
}

const PRESETS: { id: string; label: string; make: (today: Date) => DateRange }[] = [
  { id: "today", label: "Today", make: (t) => ({ from: toDay(t), to: toDay(t) }) },
  { id: "yesterday", label: "Yesterday", make: (t) => { const y = new Date(t.getFullYear(), t.getMonth(), t.getDate() - 1); return { from: toDay(y), to: toDay(y) }; } },
  { id: "7d", label: "7 days", make: (t) => ({ from: toDay(new Date(t.getFullYear(), t.getMonth(), t.getDate() - 6)), to: toDay(t) }) },
  { id: "30d", label: "30 days", make: (t) => ({ from: toDay(new Date(t.getFullYear(), t.getMonth(), t.getDate() - 29)), to: toDay(t) }) },
];

export interface DateFilter { el: HTMLElement; get: () => DateRange; clear: () => void }

/**
 * Date and range filter: quick presets, a start and an end date, a visible summary and a Clear button.
 * `onChange` only fires with a valid range, so callers never have to handle bad input themselves.
 * One date in both fields selects that single day.
 */
export function dateFilter(onChange: (r: DateRange) => void, initial: DateRange = { from: "", to: "" }): DateFilter {
  let range: DateRange = { ...initial };
  const today = () => { const n = new Date(); return new Date(n.getFullYear(), n.getMonth(), n.getDate()); };
  const from = h("input", { type: "date", value: range.from, max: toDay(today()), "aria-label": "From date" });
  const to = h("input", { type: "date", value: range.to, max: toDay(today()), "aria-label": "To date" });
  const note = h("div", { class: "df-note small", role: "status", "aria-live": "polite" });
  const presets = h("div", { class: "seg-control", role: "group", "aria-label": "Quick ranges" });
  const clearBtn = h("button", { class: "btn small ghost", type: "button" }, icon("x", 15), "Clear");
  const el = h("div", { class: "datefilter" },
    h("div", { class: "df-row" }, icon("calendar", 16), presets,
      h("label", { class: "df-field" }, h("span", { class: "small muted" }, "From"), from),
      h("label", { class: "df-field" }, h("span", { class: "small muted" }, "To"), to), clearBtn), note);

  const draw = () => {
    const error = validateRange(range);
    from.setAttribute("aria-invalid", String(Boolean(error)));
    to.setAttribute("aria-invalid", String(Boolean(error)));
    el.classList.toggle("invalid", Boolean(error));
    el.classList.toggle("active", isActive(range) && !error);
    clearBtn.hidden = !isActive(range);
    note.textContent = error ?? (isActive(range) ? `Showing ${rangeLabel(range)}` : "");
    note.hidden = !note.textContent;
    mount(presets, PRESETS.map((p) => {
      const t = p.make(today());
      return h("button", { type: "button", "aria-pressed": String(range.from === t.from && range.to === t.to), onclick: () => set(t) }, p.label);
    }));
  };
  const set = (r: DateRange) => {
    range = { ...r };
    from.value = r.from; to.value = r.to;
    draw();
    if (!validateRange(range)) onChange({ ...range });
  };
  const fromInputs = () => set({ from: from.value, to: to.value });
  from.addEventListener("change", fromInputs);
  to.addEventListener("change", fromInputs);
  clearBtn.addEventListener("click", () => set({ from: "", to: "" }));
  draw();
  return { el, get: () => ({ ...range }), clear: () => set({ from: "", to: "" }) };
}
