import { get } from "../api.js";
import { ago, duration, h, mount, toast } from "../dom.js";
import { columnChart, compact, donut, gauge, hbars, type Slice, type Tone } from "../charts.js";
import * as feed from "../events.js";
import { icon, type IconName } from "../icons.js";
import { onStatus, status, type Status } from "../state.js";
import { RANGES, actionLabel, approvalList, bucketLabel, downloadCsv, kpi, statusChip, type Action, type Summary } from "./shared.js";
import type { Page } from "./types.js";

const OUTCOME_TONE: Record<string, Tone> = { executed: "ok", failed: "bad", pending: "demo", rejected: "standby", expired: "standby" };

function healthRow(ic: IconName, label: string, detail: string, kind: "ok" | "warn" | "bad" | ""): HTMLElement {
  return h("li", { class: "health" }, icon(ic, 18), h("span", { class: "grow" }, h("b", null, label), h("div", { class: "muted small" }, detail)), h("span", { class: `chip ${kind}` }, kind === "ok" ? "OK" : kind === "bad" ? "Problem" : kind === "warn" ? "Check" : "Idle"));
}

function health(s: Status | null): HTMLElement {
  if (!s) return h("div", { class: "empty" }, "Waiting for the backend.");
  const yt = s.youtube, tg = s.telegram;
  const stream = s.hub.mode === "demo" ? healthRow("broadcast", "Stream", "Demo mode: simulated chat", "") : s.hub.stream_live ? healthRow("broadcast", "Stream", s.hub.stream_title || "On air", "ok") : healthRow("broadcast", "Stream", "Waiting for a live stream", "warn");
  return h("ul", { class: "list" },
    stream,
    healthRow("youtube", "YouTube", yt.last_error || (yt.connected ? `Connected, state: ${yt.state}` : "Not connected"), yt.last_error ? "bad" : yt.connected ? "ok" : "warn"),
    healthRow("telegram", "Telegram", tg.last_error || (!tg.configured ? "No bot token" : tg.owner_bound ? `Ready as @${tg.bot_username ?? "bot"}` : "Send /claim to the bot"), tg.last_error ? "bad" : tg.configured && tg.owner_bound ? "ok" : "warn"),
    healthRow("database", "Database", s.database, "ok"),
    healthRow("bolt", "Live feed", `${s.sse_clients} dashboard${s.sse_clients === 1 ? "" : "s"} connected`, s.sse_clients > 0 ? "ok" : "warn"),
    healthRow("clock", "Uptime", duration(s.uptime), "ok"));
}

export const overview: Page = {
  id: "overview",
  title: "Overview",
  render(root) {
    const range = h("select", { "aria-label": "Time range" }, RANGES.map(([v, l]) => h("option", { value: String(v), selected: v === 24 }, l)));
    const kpis = h("div", { class: "kpis" });
    const activity = h("div"), outcomes = h("div"), quota = h("div"), healthBox = h("div"), waiting = h("div"), recent = h("div"), chatters = h("div"), signals = h("div");
    const csvBtn = h("button", { class: "btn small ghost", type: "button" }, icon("download", 14), "CSV");
    let last: Summary | null = null;

    const paintQuota = (s: Status | null) => {
      if (!s) return mount(quota, h("div", { class: "empty" }, "Waiting for the backend."));
      const q = s.youtube.quota;
      mount(quota, h("div", { class: "quota-body" }, gauge(s.hub.mode === "demo" ? 0 : q.fraction, "used"),
        h("dl", { class: "kv" },
          h("div", null, h("dt", null, "Used today"), h("dd", null, `${compact(q.used)} of ${compact(q.daily)}`)),
          h("div", null, h("dt", null, "Remaining"), h("dd", null, compact(q.remaining))),
          h("div", null, h("dt", null, "Resets"), h("dd", null, `midnight, ${q.reset_tz.split("/").pop()?.replace(/_/g, " ") ?? q.reset_tz}`)))),
        s.hub.mode === "demo" ? h("p", { class: "muted small" }, "Demo mode never uses YouTube quota.") : null);
    };
    const paintStatus = (s: Status | null) => { paintQuota(s); mount(healthBox, health(s)); };

    const loadSummary = async () => {
      const s = await get<Summary>(`/api/analytics?hours=${range.value}`);
      last = s;
      const t = s.totals;
      mount(kpis,
        kpi("desk", "Messages", t.messages ?? 0, "accent", s.timeline.map((b) => b.messages), "#/desk"),
        kpi("users", "Chatters", t.chatters ?? 0, "ok"),
        kpi("alert", "Flagged", t.flagged_messages ?? 0, "demo", s.timeline.map((b) => b.flagged), "#/insights"),
        kpi("shield", "Actions", t.actions ?? 0, "accent", undefined, "#/moderation"),
        kpi("clock", "Waiting", t.pending ?? 0, (t.pending ?? 0) > 0 ? "bad" : "standby", undefined, "#/moderation"));
      mount(activity, s.timeline.length
        ? columnChart(s.timeline.map((b) => ({ label: bucketLabel(s.hours, b.t), total: b.messages, flagged: b.flagged })), {
          tip: (r) => `${r.label}: ${r.total} message${r.total === 1 ? "" : "s"}, ${r.flagged} flagged`, xLabel: (r) => r.label,
          summary: `Messages over the last ${s.hours} hours: ${t.messages ?? 0} in total, ${t.flagged_messages ?? 0} flagged.` })
        : h("div", { class: "empty" }, "No chat in this period yet."));
      const out: Slice[] = Object.entries(s.outcomes).map(([label, value]) => ({ label, value, tone: OUTCOME_TONE[label] ?? "accent" }));
      mount(outcomes, donut(out, "actions"));
      mount(chatters, hbars(s.top_chatters.slice(0, 6).map((c) => ({ name: c.name, count: c.messages }))));
      mount(signals, hbars(s.signals.slice(0, 6).map((x) => ({ name: String(x.name), count: x.count })), "demo"));
    };
    const loadWaiting = async () => {
      const r = await get<{ items: Action[] }>("/api/moderation/pending");
      mount(waiting, approvalList(r.items.slice(0, 3), async () => { await loadWaiting(); await loadRecent(); }),
        r.items.length > 3 ? h("div", { class: "body" }, h("a", { href: "#/moderation" }, `${r.items.length - 3} more in Moderation`)) : null);
    };
    const loadRecent = async () => {
      const r = await get<{ items: Action[] }>("/api/moderation/history?limit=6");
      mount(recent, r.items.length
        ? h("ul", { class: "list" }, r.items.map((a) => h("li", { class: "row between" },
          h("span", { class: "grow" }, h("b", null, a.author_name), " ", h("span", { class: "muted" }, actionLabel(a)), h("div", { class: "muted small" }, ago(a.ts))), statusChip(a.status))))
        : h("div", { class: "empty" }, "No moderation actions yet."));
    };
    const all = () => Promise.all([loadSummary(), loadWaiting(), loadRecent()]).catch((e) => toast(e.message, "error"));

    csvBtn.onclick = () => { if (last) downloadCsv(last); };
    range.onchange = () => void loadSummary().catch((e) => toast(e.message, "error"));
    const card = (title: string, body: HTMLElement, extra?: HTMLElement | null, cls = "") =>
      h("section", { class: `block ${cls}` }, h("header", null, h("h2", null, title), extra ?? null), h("div", { class: "body" }, body));
    const cardFlush = (title: string, body: HTMLElement, extra?: HTMLElement | null, cls = "") =>
      h("section", { class: `block flush ${cls}` }, h("header", null, h("h2", null, title), extra ?? null), body);

    mount(root,
      h("div", { class: "page-head" }, h("div", null, h("h1", null, "Overview"), h("p", null, "How chat, moderation and the connections are doing right now.")), h("label", { class: "field" }, "Range", range)),
      status?.hub.mode === "demo" ? h("div", { class: "banner demo" }, icon("flask", 18), "Demo mode: this data is simulated. Switch to Live from the sidebar when you go on air.") : null,
      kpis,
      h("div", { class: "ov-grid" },
        card("Chat activity", activity, h("span", { class: "row tight" }, h("span", { class: "key" }, h("i", { class: "sw accent" }), "Messages"), h("span", { class: "key" }, h("i", { class: "sw demo" }), "Flagged"), csvBtn), "span-2"),
        card("YouTube quota", quota),
        card("Action outcomes", outcomes),
        cardFlush("Waiting for you", waiting, h("a", { class: "small", href: "#/moderation" }, "Open"), "span-2"),
        cardFlush("System health", healthBox),
        cardFlush("Recent actions", recent, h("a", { class: "small", href: "#/moderation" }, "History")),
        h("div", { class: "stack" }, card("Most active chatters", chatters), card("What triggered moderation", signals))));

    paintStatus(status);
    const offStatus = onStatus(paintStatus);
    void all();
    const offs = [feed.on("mod_pending", () => void all()), feed.on("mod_resolved", () => void all())];
    const t = window.setInterval(() => void loadSummary().catch(() => undefined), 30000);
    return () => { offStatus(); offs.forEach((f) => f()); window.clearInterval(t); };
  },
};
