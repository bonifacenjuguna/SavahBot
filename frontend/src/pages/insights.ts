import { get } from "../api.js";
import { dateTime, downloadCsv, h, mount, toast } from "../dom.js";
import { icon } from "../icons.js";
import { areaChart, donut, hbars, sparkline } from "../charts.js";
import { areaNav } from "./kit.js";
import { card, empty, pageHead } from "./shared.js";
import type { Page } from "./types.js";

interface Summary {
  hours: number; bucket_seconds: number;
  totals: Record<string, number>;
  timeline: { t: number; messages: number; flagged: number }[];
  top_chatters: { name: string; messages: number }[];
  actions_by_type: Record<string, number>; outcomes: Record<string, number>;
  signals: { name: number | string; count: number }[]; levels: Record<string, number>;
}

const RANGES: [number, string, string][] = [[1, "1h", "Last hour"], [6, "6h", "Last 6 hours"], [24, "24h", "Last 24 hours"], [72, "3d", "Last 3 days"], [168, "7d", "Last 7 days"]];
const hm = (t: number) => new Date(t * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });

export const insights: Page = {
  id: "insights",
  title: "Insights",
  icon: "chart",
  blurb: "Charts of chat and moderation",
  render(root) {
    const body = h("div", { class: "stack" });
    let hours = 24;
    let last: Summary | null = null;

    const rangeBtns = RANGES.map(([v, short, long]) => h("button", { type: "button", title: long, "aria-label": long, "aria-pressed": String(v === hours), onclick: () => { hours = v; rangeBtns.forEach((b, i) => b.setAttribute("aria-pressed", String(RANGES[i][0] === v))); void load().catch((e) => toast(e.message, "error")); } }, short));
    const range = h("div", { class: "scroll-x" }, h("div", { class: "seg-control", role: "group", "aria-label": "Time range" }, rangeBtns));
    const exportBtn = h("button", { class: "btn ghost", type: "button", onclick: () => {
      if (!last) return;
      downloadCsv(`savahbot-activity-${last.hours}h.csv`, [["Time", "Messages", "Flagged"], ...last.timeline.map((b) => [new Date(b.t * 1000).toISOString(), b.messages, b.flagged])]);
    } }, icon("download", 16), "Export CSV");
    const refreshBtn = h("button", { class: "btn ghost", type: "button", "aria-label": "Refresh", onclick: () => void load().then(() => toast("Updated")).catch((e) => toast(e.message, "error")) }, icon("refresh", 16));

    const kpi = (cls: string, ic: string, label: string, value: string, sub?: string, spark?: SVGElement) =>
      h("div", { class: `kpi ${cls}` }, h("div", { class: "kpi-top" }, h("span", null, label), icon(ic, 18)), h("div", { class: "kpi-val" }, value), sub ? h("div", { class: "kpi-sub" }, sub) : null, spark ?? null);

    const load = async () => {
      const s = await get<Summary>(`/api/analytics?hours=${hours}`);
      last = s;
      const t = s.totals;
      const msgs = t.messages ?? 0, flagged = t.flagged_messages ?? 0;
      const flagRate = msgs ? Math.round((flagged / msgs) * 1000) / 10 : 0;
      const perMin = (n: number) => n / Math.max(1, s.bucket_seconds / 60);
      const peak = Math.max(0, ...s.timeline.map((b) => perMin(b.messages)));
      const avg = msgs / Math.max(1, s.hours * 60);
      const fmt = (x: number) => (s.hours <= 24 ? hm(x) : dateTime(x));
      const levelSlices = Object.entries(s.levels).sort((a, b) => b[1] - a[1]).map(([name, value]) => ({ name, value }));
      const outcomeSlices = Object.entries(s.outcomes).sort((a, b) => b[1] - a[1]).map(([name, value]) => ({ name, value }));
      const anyData = msgs > 0 || (t.actions ?? 0) > 0;

      mount(body,
        h("div", { class: "kpis", style: "margin-bottom:0" },
          kpi("", "message", "Messages", String(msgs), `${avg < 10 ? avg.toFixed(1) : Math.round(avg)} per minute on average`, sparkline(s.timeline.map((b) => b.messages))),
          kpi("", "users", "Chatters", String(t.chatters ?? 0), "Distinct people"),
          kpi(flagged ? "warn" : "", "flag", "Flagged", String(flagged), `${flagRate}% of messages`, sparkline(s.timeline.map((b) => b.flagged), "s2")),
          kpi("", "shield", "Actions", String(t.actions ?? 0), "Deletes, timeouts, bans"),
          kpi(t.pending ? "warn" : "", "inbox", "Waiting", String(t.pending ?? 0), t.pending ? "Needs a decision" : "All clear"),
          kpi("", "trending", "Peak rate", `${peak < 10 ? peak.toFixed(1) : Math.round(peak)}/min`, "Busiest moment in range")),
        card("activity", "Chat activity", h("div", null,
          anyData ? areaChart(s.timeline.map((b) => ({ t: b.t, a: b.messages, b: b.flagged })), { labelA: "Messages", labelB: "Flagged", fmt, ariaLabel: `Messages over the ${RANGES.find((r) => r[0] === hours)?.[2].toLowerCase() ?? "selected range"}` }) : empty("chart", "No chat in this range yet. Try Demo mode to see charts fill in."),
          h("div", { class: "legend-inline" }, h("span", null, h("i", { class: "sw s1" }), "Messages"), h("span", null, h("i", { class: "sw s2" }), "Flagged"))),
          { flush: true, actions: h("span", { class: "muted small" }, `One point every ${s.bucket_seconds >= 3600 ? "hour" : `${Math.round(s.bucket_seconds / 60)} min`}`) }),
        h("div", { class: "cols even" },
          card("users", "Who is chatting", levelSlices.length ? donut(levelSlices, { center: String(msgs), sub: "messages", ariaLabel: "Messages by chatter level" }) : empty("users", "Nothing to show yet."), { flush: true }),
          card("shield", "Moderation outcomes", outcomeSlices.length ? donut(outcomeSlices, { center: String(t.actions ?? 0), sub: "actions", ariaLabel: "Moderation actions by outcome" }) : empty("shield", "No moderation actions in this range."), { flush: true })),
        h("div", { class: "cols even" },
          card("user", "Most active chatters", hbars(s.top_chatters.map((c) => ({ name: c.name, count: c.messages })), "s1"), { flush: true }),
          h("div", { class: "stack" },
            card("flag", "What triggered moderation", hbars(s.signals.map((x) => ({ name: String(x.name), count: x.count })), "s2"), { flush: true }),
            card("ban", "Actions by type", hbars(Object.entries(s.actions_by_type).map(([name, count]) => ({ name, count })), "s4"), { flush: true }))));
    };
    mount(root, pageHead("chart", "Insights", "How busy chat is, who is talking, and what the bot reacted to.", h("div", { class: "row" }, range, refreshBtn, exportBtn)), areaNav("insights"), body);
    void load().catch((e) => toast(e.message, "error"));
    const t = window.setInterval(() => void load().catch(() => undefined), 30000);
    return () => window.clearInterval(t);
  },
};
