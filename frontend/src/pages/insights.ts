import { get } from "../api.js";
import { downloadCsv, h, mount, sheet, toast } from "../dom.js";
import { icon } from "../icons.js";
import { areaChart, donut, hbars, sparkline } from "../charts.js";
import { expandable, openChartDetail } from "../chart-detail.js";
import { areaNav } from "./kit.js";
import { personCard } from "../chat-actions.js";
import { card, empty, pageHead } from "./shared.js";
import type { Page } from "./types.js";
import { SIGNAL, avatar, plural, sentence } from "./widgets.js";

interface Bucket { t: number; messages: number; flagged: number }
interface Summary {
  hours: number; bucket_seconds: number;
  totals: Record<string, number>;
  timeline: Bucket[];
  top_chatters: { name: string; messages: number; author_id?: string; platform?: string }[];
  actions_by_type: Record<string, number>; outcomes: Record<string, number>;
  signals: { name: number | string; count: number }[]; levels: Record<string, number>;
}

const RANGES: [number, string, string][] = [[1, "1h", "Last hour"], [6, "6h", "Last 6 hours"], [24, "24h", "Last 24 hours"], [72, "3d", "Last 3 days"], [168, "7d", "Last 7 days"]];
const hm = (t: number) => new Date(t * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
const dm = (t: number) => new Date(t * 1000).toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
const n0 = (n: number) => n.toLocaleString();

/** What the internal names mean, in words a person running a stream would use. */
const LEVEL: Record<string, string> = { everyone: "Viewers", member: "Members", regular: "Regulars", bot: "Bots", mod: "Moderators" };
const OUTCOME: Record<string, string> = { simulated: "Simulated", expired: "Expired", logged: "Logged only", pending: "Waiting", rejected: "Rejected", executed: "Done", approved: "Approved", failed: "Failed" };
const ACTION: Record<string, string> = { delete: "Deletes", ban: "Bans", flag: "Flags", timeout: "Timeouts" };
const nice = (map: Record<string, string>, k: string) => map[k] ?? sentence(String(k).replace(/_/g, " "));

/** Percentage change, or null when there is nothing to compare with. */
export function change(now: number, before: number): { text: string; dir: "up" | "down" | "flat" } | null {
  if (before <= 0) return now > 0 ? { text: "new", dir: "up" } : null;
  const pct = Math.round(((now - before) / before) * 100);
  return pct === 0 ? { text: "no change", dir: "flat" } : { text: `${pct > 0 ? "+" : "−"}${Math.abs(pct)}%`, dir: pct > 0 ? "up" : "down" };
}

/** Totals for the stretch just before the one on screen, taken from a call that covers twice the range. */
export function previousTotals(wide: Summary, cur: Summary): { messages: number; flagged: number } | null {
  const first = cur.timeline[0]?.t;
  if (first === undefined || !wide.timeline.length) return null;
  let messages = 0, flagged = 0;
  for (const b of wide.timeline) if (b.t < first) { messages += b.messages; flagged += b.flagged; }
  return { messages, flagged };
}

export const insights: Page = {
  id: "insights",
  title: "Insights",
  icon: "chart",
  blurb: "Charts of chat and moderation",
  render(root) {
    const body = h("div", { class: "stack ins" });
    let hours = 24;
    let last: Summary | null = null;
    let seq = 0;

    const rangeBtns = RANGES.map(([v, short, long]) => h("button", { type: "button", title: long, "aria-label": long, "aria-pressed": String(v === hours), onclick: () => { hours = v; rangeBtns.forEach((b, i) => b.setAttribute("aria-pressed", String(RANGES[i][0] === v))); void load().catch((e) => toast(e.message, "error")); } }, short));
    const range = h("div", { class: "scroll-x" }, h("div", { class: "seg-control", role: "group", "aria-label": "Time range" }, rangeBtns));
    const exportBtn = h("button", { class: "btn ghost", type: "button", onclick: () => {
      if (!last) return;
      downloadCsv(`savahbot-activity-${last.hours}h.csv`, [["Time", "Messages", "Flagged"], ...last.timeline.map((b) => [new Date(b.t * 1000).toISOString(), b.messages, b.flagged])]);
    } }, icon("download", 16), "Export CSV");
    const refreshBtn = h("button", { class: "btn ghost", type: "button", "aria-label": "Refresh", onclick: () => void load().then(() => toast("Updated")).catch((e) => toast(e.message, "error")) }, icon("refresh", 16));

    const kpi = (cls: string, ic: string, label: string, value: string, sub?: string, spark?: SVGElement, delta?: { text: string; dir: "up" | "down" | "flat"; good: boolean | null } | null, series?: string[]) =>
      h("div", { class: `kpi ${cls}${series ? " chart-card-open" : ""}`, ...(series ? { role: "button", tabindex: 0, "aria-label": `${label}: open a bigger chart`, onclick: () => openChartDetail(label, series), onkeydown: (e: KeyboardEvent) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); openChartDetail(label, series); } } } : {}) }, h("div", { class: "kpi-top" }, h("span", null, label), icon(ic, 18)), h("div", { class: "kpi-val" }, value),
        delta ? h("div", { class: `kpi-delta ${delta.dir}${delta.good === true ? " good" : delta.good === false ? " worse" : ""}` }, delta.text, h("span", { class: "muted" }, " vs the period before")) : null,
        sub ? h("div", { class: "kpi-sub" }, sub) : null, spark ?? null);

    /** Plain sentences about what the numbers say, most useful first. */
    const highlights = (s: Summary, ctx: { peak: number; peakAt: number; fmt: (t: number) => string; flagRate: number }): HTMLElement => {
      const rows: { icon: string; text: string; tone?: string; href?: string }[] = [];
      const t = s.totals;
      if (ctx.peak > 0) rows.push({ icon: "trending", text: `Chat peaked at ${ctx.peak < 10 ? ctx.peak.toFixed(1) : Math.round(ctx.peak)} messages a minute around ${ctx.fmt(ctx.peakAt)}.` });
      const reasons = s.signals.reduce((a, x) => a + x.count, 0);
      if (s.signals[0] && reasons) rows.push({ icon: "flag", text: `${nice(SIGNAL, String(s.signals[0].name))} was the most common trigger, behind ${Math.round((s.signals[0].count / reasons) * 100)}% of the bot's reasons to react.` });
      const top = s.top_chatters[0];
      const real = (t.messages ?? 0) - (s.levels.bot ?? 0);
      if (top && s.top_chatters.length >= 3 && real > 0) rows.push({ icon: "user", text: `${top.name} sent ${Math.round((top.messages / real) * 100)}% of the messages from people.` });
      if (t.pending) rows.push({ icon: "inbox", text: `${plural(t.pending, "request")} ${t.pending === 1 ? "is" : "are"} waiting for your decision.`, tone: "warn", href: "/moderation" });
      else if (t.messages && ctx.flagRate >= 10) rows.push({ icon: "alert", text: "More than 1 in 10 messages was flagged. Look at Moderation for a pattern.", tone: "warn", href: "/moderation" });
      else if (t.messages && ctx.flagRate < 2) rows.push({ icon: "checkCircle", text: "Chat is calm. Fewer than 2% of messages needed attention.", tone: "ok" });
      if (!rows.length) return empty("chart", "Nothing stands out yet. Insights appear once chat has some activity.");
      return h("ul", { class: "notes-list" }, rows.slice(0, 4).map((r) => {
        const inner = [h("span", { class: `nl-ico ${r.tone ?? ""}` }, icon(r.icon, 17)), h("span", { class: "nl-text" }, r.text), r.href ? icon("chevronRight", 16, "tile-go") : null];
        return h("li", null, r.href ? h("a", { href: r.href }, inner) : h("div", null, inner));
      }));
    };

    /** 24 bars, one per hour of the day (your clock), added up over the range. Only worth showing for a day or more. */
    const hourStrip = (s: Summary): HTMLElement => {
      const per = new Array<number>(24).fill(0);
      for (const b of s.timeline) per[new Date(b.t * 1000).getHours()] += b.messages;
      const max = Math.max(...per, 1);
      const peakHour = per.indexOf(Math.max(...per));
      const label = (hr: number) => new Date(2000, 0, 1, hr).toLocaleTimeString([], { hour: "numeric" });
      const note = h("p", { class: "muted small" }, per[peakHour] ? `Busiest around ${label(peakHour)}, with ${n0(per[peakHour])} messages over this range.` : "No messages in this range.");
      const tip = h("div", { class: "hs-tip", hidden: true, "aria-hidden": "true" });
      const bars = per.map((v, hr) => h("span", { class: `hs-bar${hr === peakHour && v > 0 ? " peak" : ""}`, title: `${label(hr)}: ${n0(v)} messages` }, h("i", { style: `height:${Math.max(3, Math.round((v / max) * 100))}%` })));
      const wrap = h("div", { class: "hs-bars" }, ...bars, tip);
      let on = -1;
      /** Touch and hold, then drag across: the bar under the finger lights up and says its hour and count. */
      const show = (hr: number) => {
        if (hr === on) return;
        on = hr;
        bars.forEach((b, i) => b.classList.toggle("hot", i === hr));
        tip.hidden = false;
        tip.replaceChildren(h("strong", null, label(hr)), h("span", null, `${n0(per[hr])} message${per[hr] === 1 ? "" : "s"}`));
        const wr = wrap.getBoundingClientRect(), br = bars[hr].getBoundingClientRect(), tw = tip.offsetWidth;
        tip.style.left = `${Math.max(0, Math.min(wr.width - tw, br.left - wr.left + br.width / 2 - tw / 2))}px`;
      };
      const clear = () => { on = -1; bars.forEach((b) => b.classList.remove("hot")); tip.hidden = true; };
      const at = (ev: PointerEvent) => {
        const r = wrap.getBoundingClientRect();
        show(Math.max(0, Math.min(23, Math.floor(((ev.clientX - r.left) / r.width) * 24))));
      };
      // The chosen bar stays lit when you let go. It only clears when you tap somewhere else, or when you leave or refresh the page.
      wrap.addEventListener("pointerdown", (ev) => { try { wrap.setPointerCapture(ev.pointerId); } catch { /* not every browser captures */ } at(ev); });
      wrap.addEventListener("pointermove", (ev) => { if (ev.pointerType !== "mouse" || ev.buttons) at(ev); });
      const away = (ev: Event) => { if (!wrap.isConnected) { document.removeEventListener("pointerdown", away, true); return; } if (!wrap.contains(ev.target as Node)) clear(); };
      document.addEventListener("pointerdown", away, true);
      return h("div", { class: "hour-strip", role: "img", "aria-label": `Messages by hour of day. The busiest hour is ${label(peakHour)}.` }, wrap,
        h("div", { class: "hs-axis" }, [0, 6, 12, 18].map((hr) => h("span", { style: `left:${(hr / 24) * 100}%` }, label(hr)))), note);
    };

    /** Gold, silver and bronze for the top three: a small shield with the place number, nothing more. */
    const MEDAL = ["#E3B341", "#AEB6C2", "#C98A52"];
    const badge = (place: number): SVGElement => {
      const NS = "http://www.w3.org/2000/svg";
      const svg = document.createElementNS(NS, "svg");
      svg.setAttribute("viewBox", "0 0 24 28"); svg.setAttribute("width", "22"); svg.setAttribute("height", "26"); svg.setAttribute("class", `medal m${place}`); svg.setAttribute("role", "img");
      svg.setAttribute("aria-label", ["First", "Second", "Third"][place - 1] + " place");
      const shield = document.createElementNS(NS, "path");
      shield.setAttribute("d", "M12 1.5 21 4.6v8.1c0 6-3.9 10.6-9 13-5.1-2.4-9-7-9-13V4.6z");
      shield.setAttribute("fill", MEDAL[place - 1]);
      const rim = document.createElementNS(NS, "path");
      rim.setAttribute("d", "M12 4.2 18.8 6.6v6.1c0 4.6-2.8 8.2-6.8 10.4-4-2.2-6.8-5.8-6.8-10.4V6.6z");
      rim.setAttribute("fill", "none"); rim.setAttribute("stroke", "rgba(0,0,0,.28)"); rim.setAttribute("stroke-width", "1");
      const t = document.createElementNS(NS, "text");
      t.setAttribute("x", "12"); t.setAttribute("y", "16.6"); t.setAttribute("text-anchor", "middle"); t.setAttribute("font-size", "11"); t.setAttribute("font-weight", "800"); t.setAttribute("fill", "#1b1300");
      t.textContent = String(place);
      svg.append(shield, rim, t);
      return svg;
    };

    const rank = (rows: { name: string; messages: number; author_id?: string; platform?: string }[], total: number): HTMLElement => {
      if (!rows.length) return empty("users", "Nobody has chatted in this range.");
      const max = Math.max(...rows.map((r) => r.messages), 1);
      return h("ol", { class: "rank" }, rows.map((r, i) => {
        const open = () => void personCard({ author_id: r.author_id, platform: r.platform, author_name: r.name });
        const can = !!r.author_id;
        return h("li", can ? { class: "rk-open", role: "button", tabindex: 0, "aria-label": `${r.name}: see their messages`, onclick: open, onkeydown: (e: KeyboardEvent) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); open(); } } } : null,
          i < 3 ? h("span", { class: "rk-n rk-medal" }, badge(i + 1) as unknown as Node) : h("span", { class: "rk-n" }, String(i + 1)), avatar(r.name, 32),
          h("div", { class: "rk-main" }, h("div", { class: "row between nowrap" }, h("strong", { class: "wrap" }, r.name), h("span", { class: "muted small" }, `${n0(r.messages)}${total ? ` (${Math.round((r.messages / total) * 100)}%)` : ""}`)),
            h("span", { class: "track" }, h("i", { class: "s1", style: `width:${Math.max(3, (r.messages / max) * 100)}%` }))));
      }));
    };

    const load = async () => {
      const mine = ++seq;
      const wideHours = Math.min(hours * 2, 24 * 14);
      const [s, wide] = await Promise.all([get<Summary>(`/api/analytics?hours=${hours}`), get<Summary>(`/api/analytics?hours=${wideHours}`).catch(() => null)]);
      if (mine !== seq) return;   // a newer range was chosen while this one loaded
      last = s;
      const t = s.totals;
      const msgs = t.messages ?? 0, flagged = t.flagged_messages ?? 0;
      const flagRate = msgs ? Math.round((flagged / msgs) * 1000) / 10 : 0;
      const perMin = (n: number) => n / Math.max(1, s.bucket_seconds / 60);
      const peakBucket = s.timeline.reduce<Bucket | null>((a, b) => (!a || b.messages > a.messages ? b : a), null);
      const peak = peakBucket ? perMin(peakBucket.messages) : 0;
      const avg = msgs / Math.max(1, s.hours * 60);
      const fmt = (x: number) => (s.hours <= 24 ? hm(x) : dm(x));
      const prev = wide && wideHours > hours ? previousTotals(wide, s) : null;
      const dMsg = prev ? change(msgs, prev.messages) : null;
      const dFlag = prev ? change(flagged, prev.flagged) : null;
      const levelSlices = Object.entries(s.levels).sort((a, b) => b[1] - a[1]).map(([name, value]) => ({ name: nice(LEVEL, name), value }));
      const outcomeSlices = Object.entries(s.outcomes).sort((a, b) => b[1] - a[1]).map(([name, value]) => ({ name: nice(OUTCOME, name), value }));
      const anyData = msgs > 0 || (t.actions ?? 0) > 0;
      const people = (s.levels.bot ?? 0) ? msgs - (s.levels.bot ?? 0) : msgs;

      mount(body,
        h("div", { class: "kpis", style: "margin-bottom:0" },
          kpi("", "message", "Messages", n0(msgs), `${avg < 10 ? avg.toFixed(1) : Math.round(avg)} per minute on average`, sparkline(s.timeline.map((b) => b.messages)), dMsg && { ...dMsg, good: dMsg.dir === "flat" ? null : dMsg.dir === "up" }, ["messages", "chatters"]),
          kpi("", "users", "Chatters", n0(t.chatters ?? 0), "Distinct people"),
          kpi(flagged ? "warn" : "", "flag", "Flagged", n0(flagged), `${flagRate}% of messages`, sparkline(s.timeline.map((b) => b.flagged), "s2"), dFlag && { ...dFlag, good: dFlag.dir === "flat" ? null : dFlag.dir === "down" }, ["flagged", "deleted"]),
          kpi("", "shield", "Actions", n0(t.actions ?? 0), "Deletes, timeouts, bans"),
          kpi(t.pending ? "warn" : "", "inbox", "Waiting", n0(t.pending ?? 0), t.pending ? "Needs a decision" : "All clear"),
          kpi("", "trending", "Peak rate", `${peak < 10 ? peak.toFixed(1) : Math.round(peak)}/min`, "Busiest moment in range")),
        card("sparkle", "What stood out", highlights(s, { peak, peakAt: peakBucket?.t ?? 0, fmt, flagRate }), { flush: true }),
        expandable(card("activity", "Chat activity", h("div", null,
          anyData ? areaChart(s.timeline.map((b) => ({ t: b.t, a: b.messages, b: b.flagged })), { labelA: "Messages", labelB: "Flagged", fmt, ariaLabel: `Messages over the ${RANGES.find((r) => r[0] === hours)?.[2].toLowerCase() ?? "selected range"}` }) : empty("chart", "No chat in this range yet. Try Demo mode to see charts fill in."),
          h("div", { class: "legend-inline" }, h("span", null, h("i", { class: "sw s1" }), "Messages"), h("span", null, h("i", { class: "sw s2" }), "Flagged"))),
          { flush: true, actions: h("span", { class: "muted small" }, `One point every ${s.bucket_seconds >= 3600 ? "hour" : `${Math.round(s.bucket_seconds / 60)} min`}`) }), () => openChartDetail("Chat activity", ["messages", "flagged"], hours > 48 ? "30d" : "7d")),
        s.hours >= 24 && msgs > 0 ? card("clock", "Busiest hours", hourStrip(s), { flush: true }) : null,
        h("div", { class: "cols even" },
          card("users", "Who is chatting", levelSlices.length ? donut(levelSlices, { center: n0(msgs), sub: "messages", ariaLabel: "Messages by chatter level" }) : empty("users", "Nothing to show yet."), { flush: true }),
          expandable(card("shield", "What the bot did", outcomeSlices.length ? donut(outcomeSlices, { center: n0(t.actions ?? 0), sub: "actions", ariaLabel: "Moderation actions by outcome" }) : empty("shield", "No moderation actions in this range."), { flush: true }), () => openChartDetail("What the bot did", ["deleted", "timeouts", "bans"], "30d"))),
        h("div", { class: "cols even" },
          card("user", "Most active chatters", rank(s.top_chatters, people), { flush: true }),
          h("div", { class: "stack" },
            card("flag", "What triggered moderation", hbars(s.signals.map((x) => ({ name: nice(SIGNAL, String(x.name)), count: x.count })), "s2"), { flush: true }),
            card("ban", "Actions by type", hbars(Object.entries(s.actions_by_type).map(([name, count]) => ({ name: nice(ACTION, name), count })), "s4"), { flush: true }))));
    };
    const streams = h("div", { class: "ins-streams" });
    const openStream = async (id: string, when: string) => {
      const d = await get<{ sample: boolean; series: { ts: number; likes: number | null; viewers: number | null }[] }>(`/api/live/streams/${encodeURIComponent(id)}`);
      const v = d.series.map((p) => p.viewers ?? 0), l = d.series.filter((p) => p.likes !== null).map((p) => p.likes as number);
      sheet(`Stream from ${when}`, h("div", { class: "stack" },
        d.sample ? h("p", { class: "muted small" }, "Sample data: Demo mode has no real streams.") : null,
        h("div", null, h("strong", null, "People watching"), h("div", { class: "muted small" }, v.length ? `peak ${Math.max(...v).toLocaleString()}` : "none recorded"), v.length > 1 ? h("div", { style: "height:70px" }, sparkline(v)) : null),
        h("div", null, h("strong", null, "Likes"), h("div", { class: "muted small" }, l.length ? `${Math.max(...l).toLocaleString()} at the end` : "hidden by the creator or not recorded"), l.length > 1 ? h("div", { style: "height:70px" }, sparkline(l)) : null)));
    };
    const loadStreams = async () => {
      const r = await get<{ sample?: boolean; items: { video_id: string; started: number; ended: number; peak_viewers: number | null; likes: number | null; samples: number }[] }>("/api/live/streams");
      const fmt = (t: number) => new Date(t * 1000).toLocaleString([], { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
      mount(streams, card("activity", "Past streams", r.items.length
        ? h("div", { class: "table-wrap" }, r.sample ? h("p", { class: "muted small", style: "padding:8px 14px 0" }, "Sample data: Demo mode has no real streams. Click a row to see its graph.") : null, h("table", { class: "cards" }, h("thead", null, h("tr", null, ["Started", "Length", "Peak watching", "Likes"].map((c) => h("th", null, c)))),
          h("tbody", null, r.items.map((x) => h("tr", { style: "cursor:pointer", tabindex: "0", role: "button", "aria-label": "Show the graph for this stream", onclick: () => void openStream(x.video_id, fmt(x.started)), onkeydown: (e: KeyboardEvent) => { if (e.key === "Enter") void openStream(x.video_id, fmt(x.started)); } }, h("td", { "data-label": "Started" }, fmt(x.started)), h("td", { "data-label": "Length" }, `${Math.max(1, Math.round((x.ended - x.started) / 60))} min`),
            h("td", { "data-label": "Peak watching" }, x.peak_viewers === null ? "n/a" : x.peak_viewers.toLocaleString()), h("td", { "data-label": "Likes" }, x.likes === null ? "hidden" : x.likes.toLocaleString()))))))
        : empty("activity", "Likes and viewers are recorded while you are live. Streams show up here afterwards."), { flush: true }));
    };
    mount(root, pageHead("chart", "Insights", "How busy chat is, who is talking, and what the bot reacted to.", h("div", { class: "row" }, range, refreshBtn, exportBtn)), areaNav("insights"), body, streams);
    void loadStreams().catch(() => undefined);
    void load().catch((e) => toast(e.message, "error"));
    const t = window.setInterval(() => void load().catch(() => undefined), 30000);
    return () => window.clearInterval(t);
  },
};
