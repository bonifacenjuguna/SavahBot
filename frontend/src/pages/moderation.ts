import { get, patch, post } from "../api.js";
import { busy, dateTime, debounce, downloadCsv, h, mount, toast } from "../dom.js";
import * as feed from "../events.js";
import { icon } from "../icons.js";
import { onStatus, status, refreshStatus } from "../state.js";
import { dateRange, rangeQuery, type RangeValue } from "./kit.js";
import { actionLabel, approvalList, card, chipFor, empty, pageHead, type Action } from "./shared.js";
import { phraseTool, testLab } from "./modtools.js";
import { openWhy } from "./whysheet.js";
import type { Page } from "./types.js";

const MODES: { id: string; icon: string; title: string; text: string }[] = [
  { id: "off", icon: "list", title: "Off", text: "Only log. Nothing is flagged for action." },
  { id: "suggest", icon: "bell", title: "Suggest", text: "Ask me first. Requests wait on the Desk." },
  { id: "auto", icon: "zap", title: "Auto", text: "Act, then tell me what was done." },
];

export const moderation: Page = {
  id: "moderation",
  title: "Moderation",
  icon: "shield",
  blurb: "Approvals, history and blocked phrases",
  render(root, query) {
    // ----- mode
    let mode: string = status?.hub.mod_mode ?? "off";
    const modeBox = h("div", { class: "mode-cards" });
    const drawMode = () => mount(modeBox, MODES.map((m) => {
      const b = h("button", { class: "mode-card", type: "button", "aria-pressed": String(mode === m.id) }, icon(m.icon, 22), h("strong", null, m.title), h("span", null, m.text));
      b.onclick = () => busy(b as HTMLButtonElement, async () => { await patch("/api/settings", { values: { mod_mode: m.id } }); mode = m.id; drawMode(); await refreshStatus(); }, "Moderation mode saved");
      return b;
    }));
    drawMode();

    // ----- auto levels: ready-made thresholds, shown under the mode cards
    interface Lv { current: string; levels: { id: string; label: string; blurb: string }[] }
    const levelBox = h("div", { class: "stack", style: "margin-top:12px" });
    const drawLevels = async () => {
      try {
        const d = await get<Lv>("/api/moderation/level");
        mount(levelBox, h("strong", null, "How strict should auto be?"),
          h("div", { class: "mode-cards" }, d.levels.map((l) => {
            const b = h("button", { class: "mode-card", type: "button", "aria-pressed": String(d.current === l.id) }, h("strong", null, l.label), h("span", null, l.blurb));
            b.onclick = () => busy(b as HTMLButtonElement, async () => { await post("/api/moderation/level", { level: l.id }); await drawLevels(); }, `${l.label} level applied`);
            return b;
          })),
          h("p", { class: "muted small" }, d.current === "custom" ? "Custom: you changed some thresholds yourself. Pick a level to reset them to a ready-made set. Word lists and exemptions are never touched." : "Levels change only the score thresholds, strikes and which actions may run by themselves. Your word lists and exemptions stay as they are."));
      } catch { mount(levelBox, ""); }
    };
    void drawLevels();

    // ----- queue and history
    const pending = h("div"), history = h("div");
    let historyItems: Action[] = [];
    let hFilter = "all";
    let hNeedle = "";
    let hRange: RangeValue = { label: "", active: false };
    let hMore = false;
    const PAGE = 60;
    const loadPending = async () => mount(pending, approvalList((await get<{ items: Action[] }>("/api/moderation/pending")).items, async () => { await loadPending(); await loadHistory(); }));

    const historyTable = (rows: Action[]): HTMLElement => rows.length
      ? h("div", { class: "table-wrap" }, h("table", { class: "cards" }, h("thead", null, h("tr", null, ["When", "Who", "Action", "Outcome", "Why", ""].map((c) => h("th", null, c)))),
        h("tbody", null, rows.map((a) => h("tr", null,
          h("td", { "data-label": "When" }, dateTime(a.ts)),
          h("td", { "data-label": "Who" }, h("span", null, a.author_name, a.demo ? h("span", { class: "chip", style: "margin-left:6px" }, "demo") : null)),
          h("td", { "data-label": "Action" }, actionLabel(a)),
          h("td", { "data-label": "Outcome" }, h("div", null, h("span", { class: `chip ${chipFor(a.status)}` }, a.status), a.error ? h("div", { class: "reasons" }, a.error) : null)),
          h("td", { class: "small muted", "data-label": "Why" }, a.reasons.join(", ") || "-"),
          h("td", { class: "small", "data-label": "Review" }, h("button", { class: "btn small ghost", type: "button", onclick: () => openWhy(a) }, icon("sparkle", 14), "Why and teach")))))))
      : empty("history", hRange.active || hNeedle || hFilter !== "all" ? `No actions match${hRange.active ? ` for ${hRange.label.toLowerCase()}` : ""}.` : "No moderation actions yet.");
    const historyBody = h("div");
    const summary = h("div", { class: "muted small hist-summary" });
    const moreBtn = h("button", { class: "btn small ghost", type: "button", onclick: (e: Event) => busy(e.currentTarget as HTMLButtonElement, async () => { await fetchHistory(historyItems.length); }) }, icon("arrowDown", 15), "Load more");
    const drawHistory = () => {
      mount(historyBody, historyTable(historyItems), hMore ? h("div", { class: "body" }, moreBtn) : null);
      summary.textContent = historyItems.length ? `${historyItems.length} action${historyItems.length === 1 ? "" : "s"}${hRange.active ? ` · ${hRange.label}` : ""}${hMore ? " (more available)" : ""}` : "";
    };
    const STATUSES = ["all", "pending", "executed", "simulated", "approved", "rejected", "failed", "expired"];
    const fetchHistory = async (offset = 0) => {
      const qs = `limit=${PAGE}&offset=${offset}${hFilter !== "all" ? `&status=${hFilter}` : ""}${hNeedle ? `&q=${encodeURIComponent(hNeedle)}` : ""}${rangeQuery(hRange)}`;
      const rows = (await get<{ items: Action[] }>(`/api/moderation/history?${qs}`)).items;
      historyItems = offset ? [...historyItems, ...rows] : rows;
      hMore = rows.length === PAGE;
      drawHistory();
    };
    const filterBar = h("div", { class: "toolbar" });
    const reloadHistory = debounce(() => void fetchHistory().catch((e) => toast(e.message, "error")), 250);
    const dates = dateRange({ label: "History date range" }, (v) => { hRange = v; reloadHistory(); });
    const search = h("input", { type: "search", placeholder: "Search history", "aria-label": "Search history" });
    search.addEventListener("input", () => { hNeedle = search.value.trim().toLowerCase(); reloadHistory(); });
    const drawFilters = () => mount(filterBar,
      h("div", { class: "scroll-x" }, h("div", { class: "seg-control", role: "group", "aria-label": "Outcome" }, STATUSES.map((s) =>
        h("button", { type: "button", "aria-pressed": String(hFilter === s), onclick: () => { hFilter = s; drawFilters(); reloadHistory(); } }, s === "all" ? "All" : s)))),
      h("div", { class: "input-icon" }, icon("search", 16), search),
      h("button", { class: "btn small ghost", type: "button", onclick: () => downloadCsv("moderation-history.csv", [["When", "Who", "Action", "Duration (s)", "Score", "Outcome", "Reasons", "Message", "Demo"],
        ...historyItems.map((a) => [new Date(a.ts * 1000).toISOString(), a.author_name, a.action, a.duration, a.score, a.status, a.reasons.join("; "), a.body, a.demo ? "yes" : "no"])]) }, icon("download", 15), "CSV"));
    drawFilters();
    mount(history, filterBar, h("div", { class: "toolbar dates-row" }, dates.el, summary), historyBody);
    const loadHistory = async () => { await fetchHistory(); };

    // ----- rules: the two tools live in modtools.ts
    const phrasesTool = phraseTool();
    const lab = testLab({ block: (text) => { current = "phrases"; applyTabs(); phrasesTool.prefill(text); } });

    // ----- layout and narrow-screen tabs
    const queueCard = card("inbox", "Waiting for you", pending, { flush: true });
    const historyCard = card("history", "History", history, { flush: true });
    const panes: Record<string, HTMLElement[]> = { queue: [queueCard], history: [historyCard], phrases: [lab.el, phrasesTool.el] };
    const ids = Object.keys(panes);
    const names: Record<string, string> = { queue: "Queue", history: "History", phrases: "Rules" };
    let current = query.get("tab") === "rules" ? "phrases" : "queue";
    const tabs = h("div", { class: "seg-control pane-tabs", role: "tablist" }, ids.map((id) => h("button", { type: "button", role: "tab", "data-id": id, onclick: () => { current = id; applyTabs(); } }, names[id])));
    const applyTabs = () => {
      for (const [id, els] of Object.entries(panes)) els.forEach((el) => { el.classList.add("pane"); el.setAttribute("data-hidden", String(id !== current)); });
      Array.from(tabs.children).forEach((b) => b.setAttribute("aria-selected", String(b.getAttribute("data-id") === current)));
    };
    applyTabs();

    mount(root,
      pageHead("shield", "Moderation", "Decide what the bot does, review what it did, and tune what it looks for."),
      card("sliders", "Mode", h("div", { class: "body" }, modeBox, levelBox)),
      h("div", { style: "height:20px" }),
      tabs,
      h("div", { class: "cols" },
        h("div", { class: "stack" }, queueCard, historyCard),
        h("div", { class: "stack" }, lab.el, phrasesTool.el)));

    const all = () => Promise.all([loadPending(), loadHistory()]).catch((e) => toast(e.message, "error"));
    void all();
    void phrasesTool.load().catch((e) => toast(e.message, "error"));
    const offs = [feed.on("mod_pending", all), feed.on("mod_resolved", all), onStatus((st) => { if (st.hub.mod_mode !== mode) { mode = st.hub.mod_mode; drawMode(); } })];
    return () => offs.forEach((f) => f());
  },
};
