import { tabRail } from "../nav.js";
import { pageLayout } from "../layout.js";
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
    const levelBox = h("div", { class: "stack mod-levels" });
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
    const pending = h("div", { class: "mod-scroll" }), history = h("div");
    const queueCount = h("span", { class: "chip warn", hidden: true });
    let historyItems: Action[] = [];
    let hFilter = "all";
    let hNeedle = "";
    let hRange: RangeValue = { label: "", active: false };
    let hMore = false;
    const PAGE = 500;   // the most the server sends in one go; History scrolls inside its card, so there is no Load more button
    const loadPending = async () => {
      const items = (await get<{ items: Action[] }>("/api/moderation/pending")).items;
      queueCount.hidden = !items.length;
      queueCount.textContent = `${items.length} waiting`;
      mount(pending, approvalList(items, async () => { await loadPending(); await loadHistory(); }));
    };

    const historyTable = (rows: Action[]): HTMLElement => rows.length
      ? h("div", { class: "table-wrap" }, h("table", { class: "cards mod-table" },
        h("thead", null, h("tr", null, [["When", "mh-when"], ["Who", "mh-who"], ["Action", "mh-act"], ["Outcome", "mh-out"], ["Why", "mh-why"], ["", "mh-go"]].map(([c, k]) => h("th", { class: k }, c)))),
        h("tbody", null, rows.map((a) => {
          const why = a.reasons.join(", ");
          return h("tr", null,
            h("td", { class: "mh-when", "data-label": "When" }, dateTime(a.ts)),
            h("td", { class: "mh-who", "data-label": "Who" }, h("div", { class: "mh-name" }, h("strong", null, a.author_name), a.demo ? h("span", { class: "chip" }, "demo") : null),
              a.body ? h("div", { class: "mh-msg", title: a.body }, a.body) : null),
            h("td", { class: "mh-act", "data-label": "Action" }, h("span", { class: `chip tier-${a.action}` }, actionLabel(a))),
            h("td", { class: "mh-out", "data-label": "Outcome" }, h("div", null, h("span", { class: `chip ${chipFor(a.status)}` }, a.status), a.error ? h("div", { class: "reasons" }, a.error) : null)),
            h("td", { class: "mh-why small muted", "data-label": "Why" }, h("span", { class: "mh-clamp", title: why }, why || "-")),
            h("td", { class: "mh-go small", "data-label": "Review" }, h("button", { class: "btn small ghost", type: "button", onclick: () => openWhy(a) }, icon("sparkle", 14), "Why and teach")));
        }))))
      : empty("history", hRange.active || hNeedle || hFilter !== "all" ? `No actions match${hRange.active ? ` for ${hRange.label.toLowerCase()}` : ""}.` : "No moderation actions yet.");
    const historyBody = h("div");
    const summary = h("div", { class: "muted small hist-summary" });
    const drawHistory = () => {
      mount(historyBody, historyTable(historyItems));
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
    const queueCard = card("inbox", "Waiting for you", pending, { flush: true, actions: queueCount, cls: "mod-queue" });
    const historyCard = card("history", "History", history, { flush: true, cls: "mod-history" });
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
    tabRail(tabs, "mod-tabs");

    // 1.4.2: the cards can be dragged into the order you like (Edit layout, same as Desk and the other pages)
    const lay = pageLayout("moderation");
    const rules = h("div", { class: "mod-rules", "data-card": "rules", "data-label": "Rules and tools" }, lab.el, phrasesTool.el);
    const grid = h("div", { class: "mod-grid" }, queueCard, rules, historyCard);
    mount(root,
      pageHead("shield", "Moderation", "Decide what the bot does, review what it did, and tune what it looks for.", h("div", { class: "row" }, lay.button)),
      card("sliders", "Mode", h("div", { class: "body mod-mode" }, h("strong", { class: "mod-sub" }, "What should the bot do?"), modeBox, levelBox)),
      tabs,
      grid);
    lay.arrange([grid, rules]);      // the queue, the rules column and History can swap places; the two rule tools can swap inside the rules column

    const all = () => Promise.all([loadPending(), loadHistory()]).catch((e) => toast(e.message, "error"));
    void all();
    void phrasesTool.load().catch((e) => toast(e.message, "error"));
    const offs = [feed.on("mod_pending", all), feed.on("mod_resolved", all), onStatus((st) => { if (st.hub.mod_mode !== mode) { mode = st.hub.mod_mode; drawMode(); } })];
    return () => { lay.dispose(); offs.forEach((f) => f()); };
  },
};
