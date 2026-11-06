import { get } from "../api.js";
import { h, mount, toast } from "../dom.js";
import { columnChart, donut, hbars, type Slice, type Tone } from "../charts.js";
import { icon } from "../icons.js";
import { RANGES, bucketLabel, downloadCsv, kpi, type Summary } from "./shared.js";
import type { Page } from "./types.js";

const OUTCOME_TONE: Record<string, Tone> = { executed: "ok", failed: "bad", pending: "demo", rejected: "standby", expired: "standby" };
const LEVEL_TONE: Tone[] = ["accent", "ok", "demo", "bad", "standby"];

export const insights: Page = {
  id: "insights",
  title: "Insights",
  render(root) {
    const body = h("div", { class: "stack" });
    const range = h("select", { "aria-label": "Time range" }, RANGES.map(([v, l]) => h("option", { value: String(v), selected: v === 24 }, l)));
    let last: Summary | null = null;
    const csvBtn = h("button", { class: "btn small ghost", type: "button", onclick: () => { if (last) downloadCsv(last); } }, icon("download", 14), "Download CSV");
    const load = async () => {
      const s = await get<Summary>(`/api/analytics?hours=${range.value}`);
      last = s;
      const t = s.totals;
      const outcomes: Slice[] = Object.entries(s.outcomes).map(([label, value]) => ({ label, value, tone: OUTCOME_TONE[label] ?? "accent" }));
      const actions: Slice[] = Object.entries(s.actions_by_type).map(([label, value], i) => ({ label, value, tone: LEVEL_TONE[i % LEVEL_TONE.length] }));
      const levels: Slice[] = Object.entries(s.levels).map(([label, value], i) => ({ label, value, tone: LEVEL_TONE[i % LEVEL_TONE.length] }));
      const flaggedShare = t.messages ? Math.round(((t.flagged_messages ?? 0) / t.messages) * 100) : 0;
      mount(body,
        h("div", { class: "kpis" },
          kpi("desk", "Messages", t.messages ?? 0, "accent", s.timeline.map((b) => b.messages)),
          kpi("users", "Chatters", t.chatters ?? 0, "ok"),
          kpi("alert", "Flagged", t.flagged_messages ?? 0, "demo", s.timeline.map((b) => b.flagged)),
          kpi("shield", "Actions", t.actions ?? 0, "accent"),
          kpi("clock", "Waiting", t.pending ?? 0, (t.pending ?? 0) > 0 ? "bad" : "standby", undefined, "#/moderation")),
        h("section", { class: "block" }, h("header", null, h("h2", null, "Chat activity"),
          h("span", { class: "row tight" }, h("span", { class: "key" }, h("i", { class: "sw accent" }), "Messages"), h("span", { class: "key" }, h("i", { class: "sw demo" }), `Flagged (${flaggedShare}%)`), csvBtn)),
          h("div", { class: "body" }, s.timeline.length
            ? columnChart(s.timeline.map((b) => ({ label: bucketLabel(s.hours, b.t), total: b.messages, flagged: b.flagged })), {
              tip: (r) => `${r.label}: ${r.total} message${r.total === 1 ? "" : "s"}, ${r.flagged} flagged`, xLabel: (r) => r.label,
              summary: `Messages over the last ${s.hours} hours: ${t.messages ?? 0} in total, ${t.flagged_messages ?? 0} flagged.` })
            : h("div", { class: "empty" }, "No chat in this period yet."))),
        h("div", { class: "cols even" },
          h("section", { class: "block" }, h("header", null, h("h2", null, "Most active chatters")), h("div", { class: "body" }, hbars(s.top_chatters.map((c) => ({ name: c.name, count: c.messages }))))),
          h("section", { class: "block" }, h("header", null, h("h2", null, "What triggered moderation")), h("div", { class: "body" }, hbars(s.signals.map((x) => ({ name: String(x.name), count: x.count })), "demo")))),
        h("div", { class: "cols three" },
          h("section", { class: "block" }, h("header", null, h("h2", null, "Action outcomes")), h("div", { class: "body" }, donut(outcomes, "actions"))),
          h("section", { class: "block" }, h("header", null, h("h2", null, "Actions by type")), h("div", { class: "body" }, donut(actions, "actions"))),
          h("section", { class: "block" }, h("header", null, h("h2", null, "Who is chatting")), h("div", { class: "body" }, donut(levels, "messages")))));
    };
    range.onchange = () => void load().catch((e) => toast(e.message, "error"));
    mount(root, h("div", { class: "page-head" }, h("div", null, h("h1", null, "Insights"), h("p", null, "Chat activity, what triggered moderation, and how actions turned out.")), h("label", { class: "field" }, "Range", range)), body);
    void load().catch((e) => toast(e.message, "error"));
    const t = window.setInterval(() => void load().catch(() => undefined), 30000);
    return () => window.clearInterval(t);
  },
};
