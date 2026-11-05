import { del, get, patch, post } from "../api.js";
import { busy, dateTime, downloadCsv, h, mount, toast } from "../dom.js";
import * as feed from "../events.js";
import { icon } from "../icons.js";
import { onStatus, status, refreshStatus } from "../state.js";
import { actionLabel, approvalList, card, chipFor, empty, pageHead, type Action } from "./shared.js";
import type { Page } from "./types.js";

interface Phrase { id: number; phrase: string; is_regex: boolean; weight: number; enabled: boolean }

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
  render(root) {
    // ----- mode
    let mode: string = status?.hub.mod_mode ?? "off";
    const modeBox = h("div", { class: "mode-cards" });
    const drawMode = () => mount(modeBox, MODES.map((m) => {
      const b = h("button", { class: "mode-card", type: "button", "aria-pressed": String(mode === m.id) }, icon(m.icon, 22), h("strong", null, m.title), h("span", null, m.text));
      b.onclick = () => busy(b as HTMLButtonElement, async () => { await patch("/api/settings", { values: { mod_mode: m.id } }); mode = m.id; drawMode(); await refreshStatus(); }, "Moderation mode saved");
      return b;
    }));
    drawMode();

    // ----- queue and history
    const pending = h("div"), history = h("div"), phrases = h("div"), tester = h("div");
    let historyItems: Action[] = [];
    let hFilter = "all";
    let hNeedle = "";
    const loadPending = async () => mount(pending, approvalList((await get<{ items: Action[] }>("/api/moderation/pending")).items, async () => { await loadPending(); await loadHistory(); }));

    const historyTable = (rows: Action[]): HTMLElement => rows.length
      ? h("div", { class: "table-wrap" }, h("table", { class: "cards" }, h("thead", null, h("tr", null, ["When", "Who", "Action", "Outcome", "Why"].map((c) => h("th", null, c)))),
        h("tbody", null, rows.map((a) => h("tr", null,
          h("td", { "data-label": "When" }, dateTime(a.ts)),
          h("td", { "data-label": "Who" }, h("span", null, a.author_name, a.demo ? h("span", { class: "chip", style: "margin-left:6px" }, "demo") : null)),
          h("td", { "data-label": "Action" }, actionLabel(a)),
          h("td", { "data-label": "Outcome" }, h("div", null, h("span", { class: `chip ${chipFor(a.status)}` }, a.status), a.error ? h("div", { class: "reasons" }, a.error) : null)),
          h("td", { class: "small muted", "data-label": "Why" }, a.reasons.join(", ") || "-"))))))
      : empty("history", historyItems.length ? "No actions match this filter." : "No moderation actions yet.");
    const historyBody = h("div");
    const drawHistory = () => {
      const rows = historyItems.filter((a) => (hFilter === "all" || a.status === hFilter) && (!hNeedle || `${a.author_name} ${a.action} ${a.reasons.join(" ")} ${a.body}`.toLowerCase().includes(hNeedle)));
      mount(historyBody, historyTable(rows));
    };
    const statuses = (): string[] => ["all", ...Array.from(new Set(historyItems.map((a) => a.status)))];
    const filterBar = h("div", { class: "toolbar" });
    const drawFilters = () => {
      const search = h("input", { type: "search", placeholder: "Search history", "aria-label": "Search history", value: hNeedle });
      search.addEventListener("input", () => { hNeedle = search.value.trim().toLowerCase(); drawHistory(); });
      mount(filterBar,
        h("div", { class: "scroll-x" }, h("div", { class: "seg-control", role: "group", "aria-label": "Outcome" }, statuses().map((s) =>
          h("button", { type: "button", "aria-pressed": String(hFilter === s), onclick: () => { hFilter = s; drawFilters(); drawHistory(); } }, s === "all" ? "All" : s)))),
        h("div", { class: "input-icon" }, icon("search", 16), search),
        h("button", { class: "btn small ghost", type: "button", onclick: () => downloadCsv("moderation-history.csv", [["When", "Who", "Action", "Duration (s)", "Score", "Outcome", "Reasons", "Message", "Demo"],
          ...historyItems.map((a) => [new Date(a.ts * 1000).toISOString(), a.author_name, a.action, a.duration, a.score, a.status, a.reasons.join("; "), a.body, a.demo ? "yes" : "no"])]) }, icon("download", 15), "CSV"));
    };
    mount(history, filterBar, historyBody);
    const loadHistory = async () => {
      historyItems = (await get<{ items: Action[] }>("/api/moderation/history?limit=60")).items;
      if (!statuses().includes(hFilter)) hFilter = "all";
      drawFilters();
      drawHistory();
    };

    // ----- blocked phrases
    let pNeedle = "";
    let phraseItems: Phrase[] = [];
    const phrase = h("input", { type: "text", placeholder: "Word, phrase or regex", required: true, maxLength: 200, "aria-label": "Phrase" });
    const regex = h("input", { type: "checkbox" });
    const weight = h("input", { type: "number", min: 0, max: 100, value: "0", title: "Score added when matched. 0 uses the default.", "aria-label": "Score weight" });
    const add = h("button", { class: "btn primary", type: "submit" }, icon("plus", 16), "Add");
    const find = h("input", { type: "search", placeholder: "Search phrases", "aria-label": "Search phrases" });
    const findBar = h("div", { class: "toolbar", hidden: true }, h("div", { class: "input-icon" }, icon("search", 16), find));
    const phraseList = h("div");
    const drawPhraseList = () => {
      const shown = phraseItems.filter((p) => !pNeedle || p.phrase.toLowerCase().includes(pNeedle));
      findBar.hidden = phraseItems.length <= 8;
      mount(phraseList, shown.length ? h("ul", { class: "list" }, shown.map((p) => h("li", { class: "row between" },
        h("span", null, h("span", { class: p.enabled ? "mono" : "mono muted" }, p.phrase), " ", p.is_regex ? h("span", { class: "chip" }, "regex") : null, p.weight ? h("span", { class: "chip" }, `+${p.weight}`) : null),
        h("span", { class: "row" },
          h("label", { class: "check small" }, h("input", { type: "checkbox", class: "switch", checked: p.enabled, "aria-label": `Enable ${p.phrase}`, onchange: (e: Event) => void patch(`/api/blacklist/${p.id}`, { enabled: (e.target as HTMLInputElement).checked }).catch((x) => toast(x.message, "error")) })),
          h("button", { class: "btn small danger", "aria-label": `Remove ${p.phrase}`, onclick: (e: Event) => busy(e.currentTarget as HTMLButtonElement, async () => { await del(`/api/blacklist/${p.id}`); await loadPhrases(); }) }, icon("trash", 15), "Remove")))))
        : empty("ban", phraseItems.length ? "No phrases match." : "No blocked phrases."));
    };
    find.addEventListener("input", () => { pNeedle = find.value.trim().toLowerCase(); drawPhraseList(); });
    const loadPhrases = async () => {
      phraseItems = (await get<{ items: Phrase[] }>("/api/blacklist")).items;
      drawPhraseList();
    };
    mount(phrases,
      h("form", { class: "body row", onsubmit: (e: Event) => { e.preventDefault(); busy(add, async () => { await post("/api/blacklist", { phrase: phrase.value, is_regex: regex.checked, weight: Number(weight.value) }); phrase.value = ""; await loadPhrases(); }); } },
        h("div", { class: "grow" }, phrase), h("label", { class: "check" }, regex, "Regex"), h("div", { style: "width:90px" }, weight), add),
      findBar, phraseList);

    // ----- message tester
    const text = h("textarea", { placeholder: "Paste a chat message to see how it would score", maxLength: 1000, "aria-label": "Message to score" });
    const level = h("select", { "aria-label": "Chatter level" }, ["everyone", "member", "regular", "mod"].map((l) => h("option", { value: l }, l)));
    const result = h("div", { class: "small", "aria-live": "polite" });
    const test = h("button", { class: "btn primary", type: "submit" }, icon("gauge", 16), "Score it");
    mount(tester, h("form", { class: "body stack", onsubmit: (e: Event) => {
      e.preventDefault();
      busy(test, async () => {
        const r = await post<{ verdict: any; note: string }>("/api/moderation/test", { text: text.value, level: level.value });
        const v = r.verdict;
        const top = Math.max(1, ...v.signals.map((s: any) => Number(s.weight) || 0));
        const tone = v.action === "allow" || v.action === "none" ? "ok" : v.action === "flag" ? "warn" : "bad";
        mount(result,
          h("div", { class: "row" }, h("span", { class: `chip ${tone}` }, v.action), h("strong", null, `Score ${v.score}`), v.duration ? h("span", { class: "muted" }, `${v.duration}s`) : null, v.exempt ? h("span", { class: "chip" }, "exempt") : null),
          v.signals.length ? h("div", { class: "hbars", style: "padding:10px 0 0" }, v.signals.map((s: any) =>
            h("div", { class: "hbar", style: "padding-left:0;padding-right:0" }, h("span", { class: "name small", title: s.detail || s.name }, s.name), h("span", { class: "track" }, h("i", { class: "s2", style: `width:${Math.max(4, ((Number(s.weight) || 0) / top) * 100)}%` })), h("span", { class: "num small" }, `+${s.weight}`))))
            : h("p", { class: "muted", style: "margin-top:8px" }, "No signals fired."),
          v.signals.some((s: any) => s.detail) ? h("ul", { class: "reasons" }, v.signals.filter((s: any) => s.detail).map((s: any) => h("li", null, `${s.name}: ${s.detail}`))) : null,
          h("p", { class: "muted", style: "margin-top:8px" }, r.note));
      });
    } }, text, h("div", { class: "row" }, h("label", { class: "field" }, "Chatter level", level), test), result));

    // ----- layout and narrow-screen tabs
    const queueCard = card("inbox", "Waiting for you", pending, { flush: true });
    const historyCard = card("history", "History", history, { flush: true });
    const phraseCard = card("ban", "Blocked phrases", phrases, { flush: true, actions: h("span", { class: "muted small" }, "Survives spacing, symbols and look-alike letters") });
    const testCard = card("gauge", "Try a message", tester, { flush: true });
    const panes: Record<string, HTMLElement[]> = { queue: [queueCard], history: [historyCard], phrases: [phraseCard, testCard] };
    const ids = Object.keys(panes);
    const names: Record<string, string> = { queue: "Queue", history: "History", phrases: "Rules" };
    let current = "queue";
    const tabs = h("div", { class: "seg-control pane-tabs", role: "tablist" }, ids.map((id) => h("button", { type: "button", role: "tab", "data-id": id, onclick: () => { current = id; applyTabs(); } }, names[id])));
    const applyTabs = () => {
      for (const [id, els] of Object.entries(panes)) els.forEach((el) => { el.classList.add("pane"); el.setAttribute("data-hidden", String(id !== current)); });
      Array.from(tabs.children).forEach((b) => b.setAttribute("aria-selected", String(b.getAttribute("data-id") === current)));
    };
    applyTabs();

    mount(root,
      pageHead("shield", "Moderation", "Decide what the bot does, review what it did, and tune what it looks for."),
      card("sliders", "Mode", h("div", { class: "body" }, modeBox)),
      h("div", { style: "height:20px" }),
      tabs,
      h("div", { class: "cols" },
        h("div", { class: "stack" }, queueCard, historyCard),
        h("div", { class: "stack" }, phraseCard, testCard)));

    const all = () => Promise.all([loadPending(), loadHistory()]).catch((e) => toast(e.message, "error"));
    void all();
    void loadPhrases().catch((e) => toast(e.message, "error"));
    const offs = [feed.on("mod_pending", all), feed.on("mod_resolved", all), onStatus((st) => { if (st.hub.mod_mode !== mode) { mode = st.hub.mod_mode; drawMode(); } })];
    return () => offs.forEach((f) => f());
  },
};
