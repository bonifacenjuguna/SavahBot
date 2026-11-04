import { get } from "../api.js";
import { clock, dateTime, h, mount, toast } from "../dom.js";
import type { Page } from "./types.js";

interface Summary {
  hours: number; bucket_seconds: number;
  totals: Record<string, number>;
  timeline: { t: number; messages: number; flagged: number }[];
  top_chatters: { name: string; messages: number }[];
  actions_by_type: Record<string, number>; outcomes: Record<string, number>;
  signals: { name: number | string; count: number }[]; levels: Record<string, number>;
}

function bars(rows: { name: string; count: number }[]): HTMLElement {
  if (!rows.length) return h("div", { class: "empty" }, "Nothing to show yet.");
  const max = Math.max(...rows.map((r) => r.count), 1);
  return h("div", { style: "padding:8px 0" }, rows.map((r) => h("div", { class: "hbar" }, h("span", { class: "small" }, r.name), h("i", { style: `width:${Math.max(2, (r.count / max) * 100)}%` }), h("span", { class: "small muted" }, String(r.count)))));
}

export const insights: Page = {
  id: "insights",
  title: "Insights",
  render(root) {
    const body = h("div", { class: "stack" });
    const range = h("select", { "aria-label": "Time range" }, [[1, "Last hour"], [6, "Last 6 hours"], [24, "Last 24 hours"], [72, "Last 3 days"], [168, "Last 7 days"]].map(([v, l]) => h("option", { value: String(v), selected: v === 24 }, String(l))));
    const load = async () => {
      const s = await get<Summary>(`/api/analytics?hours=${range.value}`);
      const t = s.totals;
      const max = Math.max(...s.timeline.map((b) => b.messages), 1);
      mount(body,
        h("section", { class: "block" }, h("div", { class: "facts" },
          [["messages", "Messages"], ["chatters", "Chatters"], ["flagged_messages", "Flagged"], ["actions", "Actions"], ["pending", "Waiting"]].map(([k, l]) => h("div", null, h("b", null, String(t[k] ?? 0)), h("span", null, l))))),
        h("section", { class: "block" }, h("header", null, h("h2", null, "Chat activity"), h("span", { class: "muted small" }, "Orange is the flagged share of each bar")),
          h("div", { class: "bars", role: "img", "aria-label": "Messages over time" }, s.timeline.map((b) =>
            h("div", { style: `height:${(b.messages / max) * 100}%`, title: `${s.hours <= 24 ? clock(b.t) : dateTime(b.t)}: ${b.messages} messages, ${b.flagged} flagged` }, b.flagged ? h("i", { style: `height:${(b.flagged / Math.max(b.messages, 1)) * 100}%` }) : null)))),
        h("div", { class: "cols" },
          h("section", { class: "block" }, h("header", null, h("h2", null, "Most active chatters")), bars(s.top_chatters.map((c) => ({ name: c.name, count: c.messages })))),
          h("div", { class: "stack" },
            h("section", { class: "block" }, h("header", null, h("h2", null, "What triggered moderation")), bars(s.signals.map((x) => ({ name: String(x.name), count: x.count })))),
            h("section", { class: "block" }, h("header", null, h("h2", null, "Actions")), bars(Object.entries(s.actions_by_type).map(([name, count]) => ({ name, count }))),
              bars(Object.entries(s.outcomes).map(([name, count]) => ({ name: `outcome: ${name}`, count })))))));
    };
    range.onchange = () => void load().catch((e) => toast(e.message, "error"));
    mount(root, h("div", { class: "page-head" }, h("h1", null, "Insights"), h("label", { class: "field" }, "Range", range)), body);
    void load().catch((e) => toast(e.message, "error"));
    const t = window.setInterval(() => void load().catch(() => undefined), 30000);
    return () => window.clearInterval(t);
  },
};
