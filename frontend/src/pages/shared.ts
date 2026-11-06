import { post } from "../api.js";
import { busy, dateTime, duration, h, shortTime } from "../dom.js";
import { compact, sparkline, type Tone } from "../charts.js";
import { icon, type IconName } from "../icons.js";

export interface Action {
  id: number; ts: number; author_name: string; action: string; duration: number | null; score: number; reasons: string[];
  status: string; body: string; error: string; demo: boolean;
}

/** Shape of GET /api/analytics. */
export interface Summary {
  hours: number; bucket_seconds: number;
  totals: Record<string, number>;
  timeline: { t: number; messages: number; flagged: number }[];
  top_chatters: { name: string; messages: number }[];
  actions_by_type: Record<string, number>; outcomes: Record<string, number>;
  signals: { name: number | string; count: number }[]; levels: Record<string, number>;
}

export const RANGES: [number, string][] = [[1, "Last hour"], [6, "Last 6 hours"], [24, "Last 24 hours"], [72, "Last 3 days"], [168, "Last 7 days"]];

/** Axis and tooltip time: clock time for short ranges, date and time for long ones. */
export const bucketLabel = (hours: number, t: number): string => (hours <= 24 ? shortTime(t) : dateTime(t));

/** Statuses of a moderation action, as a coloured chip. */
export function statusChip(status: string): HTMLElement {
  return h("span", { class: `chip ${status === "executed" ? "ok" : status === "failed" ? "bad" : status === "pending" ? "warn" : ""}` }, status);
}

export function actionLabel(a: Action): string {
  return a.action === "timeout" && a.duration ? `timeout ${duration(a.duration)}` : a.action;
}

export function approvalList(items: Action[], reload: () => Promise<void> | void): HTMLElement {
  if (!items.length) return h("div", { class: "empty" }, "Nothing is waiting. Requests appear here when the bot wants to delete, time out or ban someone.");
  const decide = (id: number, verb: "approve" | "reject") => (e: Event) =>
    busy(e.currentTarget as HTMLButtonElement, async () => { await post(`/api/moderation/${id}/${verb}`); await reload(); });
  const all = (verb: "approve" | "reject") => (e: Event) =>
    busy(e.currentTarget as HTMLButtonElement, async () => { await post(`/api/moderation/${verb}-all`); await reload(); });
  return h("ul", { class: "list" },
    items.length > 1 ? h("li", { class: "row" }, h("button", { class: "btn small primary", onclick: all("approve") }, icon("check", 14), "Approve all"), h("button", { class: "btn small ghost", onclick: all("reject") }, icon("x", 14), "Reject all")) : null,
    items.map((a) =>
      h("li", { class: "approval" },
        h("div", { class: "row between" }, h("strong", null, a.author_name), h("span", { class: "chip warn" }, `${actionLabel(a)} · score ${a.score}`)),
        a.body ? h("q", null, a.body) : null,
        h("div", { class: "reasons" }, a.reasons.join(", ")),
        h("div", { class: "row" }, h("button", { class: "btn small primary", onclick: decide(a.id, "approve") }, icon("check", 14), "Approve"),
          h("button", { class: "btn small ghost", onclick: decide(a.id, "reject") }, icon("x", 14), "Reject"), h("span", { class: "muted small" }, dateTime(a.ts))))),
  );
}

/** A headline number with an optional trend line. Becomes a link when `href` is given. */
export function kpi(ic: IconName, label: string, value: number, t: Tone, trend?: number[], href?: string): HTMLElement {
  return h(href ? "a" : "div", { class: `kpi ${t}`, href },
    h("div", { class: "kpi-top" }, icon(ic, 18), h("span", null, label)),
    h("b", null, compact(value)),
    trend ? sparkline(trend, t) : h("span", { class: "spark-gap" }));
}

/** Download a timeline as CSV (built in the browser; nothing is sent anywhere). */
export function downloadCsv(s: Summary): void {
  const rows = ["time,messages,flagged", ...s.timeline.map((b) => `${new Date(b.t * 1000).toISOString()},${b.messages},${b.flagged}`)];
  const url = URL.createObjectURL(new Blob([rows.join("\n")], { type: "text/csv" }));
  const a = h("a", { href: url, download: `savahbot-activity-${s.hours}h.csv` });
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
