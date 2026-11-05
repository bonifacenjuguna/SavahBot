import { get, patch, post } from "../api.js";
import { busy, confirmDialog, dateTime, downloadCsv, h, mount, toast } from "../dom.js";
import * as feed from "../events.js";
import { icon } from "../icons.js";
import { currentMode, onStatus, refreshStatus, status } from "../state.js";
import { libraryPanel } from "./library.js";
import { actionLabel, approvalList, card, chipFor, empty, pageHead, type Action } from "./shared.js";
import type { Page } from "./types.js";

const MODES: { id: string; title: string; text: string }[] = [
  { id: "off", title: "Off", text: "Only logs. Nothing is flagged for action." },
  { id: "suggest", title: "Suggest", text: "Asks you first. Requests wait in Waiting." },
  { id: "auto", title: "Auto", text: "Acts by itself, then tells you what it did." },
];

// Rules are the real detection signals in the backend, grouped. Each is switched and weighted through the normal settings API.
interface Rule { cat: string; title: string; text: string; key: string }
const RULES: Rule[] = [
  { cat: "Spam and flooding", title: "Message frequency", text: "Too many messages from one person in a short time.", key: "mod_rate" },
  { cat: "Spam and flooding", title: "Repeated messages", text: "The same person sending the same message again.", key: "mod_dup" },
  { cat: "Spam and flooding", title: "Copy-paste raids", text: "Near-identical text from several accounts at once.", key: "mod_sim" },
  { cat: "Spam and flooding", title: "Bot-like timing", text: "Messages arriving at machine-regular intervals.", key: "mod_interval" },
  { cat: "Words and phrases", title: "Blocked library", text: "Entries in the Library tab, including disguised spellings.", key: "mod_blacklist" },
  { cat: "Links", title: "Links and URLs", text: "Links, including 'site dot com' disguises. Allowed domains are in Settings.", key: "mod_links" },
  { cat: "Suspicious content", title: "Shouting", text: "Mostly capital letters.", key: "mod_caps" },
  { cat: "Suspicious content", title: "Symbol spam", text: "A high share of symbols and punctuation.", key: "mod_symbols" },
  { cat: "Suspicious content", title: "Emote floods", text: "Too many emotes in one message.", key: "mod_emotes" },
  { cat: "Suspicious content", title: "Repeated characters", text: "Long runs of one character, or mostly repeated words.", key: "mod_repeat" },
  { cat: "Suspicious content", title: "Very long messages", text: "Messages longer than a normal one.", key: "mod_length" },
];

type TabId = "waiting" | "flagged" | "history" | "library" | "rules" | "test";

const flaggedChip = (a: Action): [string, string] =>
  a.status === "pending" ? ["warn", "waiting"] : a.status === "logged" ? ["", "flagged"] : [chipFor(a.status), a.status];

export const moderation: Page = {
  id: "moderation",
  title: "Moderation",
  icon: "shield",
  blurb: "Waiting requests, flagged messages, library and rules",
  render(root, query) {
    let tab: TabId = (["waiting", "flagged", "history", "library", "rules", "test"].includes(query.get("tab") ?? "") ? query.get("tab") : "waiting") as TabId;
    let mode: string = status?.hub.mod_mode ?? "off";
    let pendingItems: Action[] = [];
    let flaggedItems: Action[] = [];
    let historyItems: Action[] = [];
    let libraryTotal = 0;

    // ----- moderation mode (compact)
    const modeSeg = h("div", { class: "seg-control", role: "group", "aria-label": "Moderation mode" });
    const modeCap = h("span", { class: "muted small" });
    const drawMode = () => {
      mount(modeSeg, MODES.map((m) => h("button", { type: "button", "aria-pressed": String(mode === m.id), onclick: async (e: Event) => {
        if (mode === m.id) return;
        if (m.id === "auto" && !(await confirmDialog("Switch moderation to Auto?", "The bot will delete messages and time out viewers without asking you first. Bans still wait for you unless you changed that in Settings.", "Use Auto"))) return;
        busy(e.currentTarget as HTMLButtonElement, async () => { await patch("/api/settings", { values: { mod_mode: m.id } }); mode = m.id; drawMode(); await refreshStatus(); }, `Moderation set to ${m.title}`);
      } }, m.title)));
      mount(modeCap, MODES.find((m) => m.id === mode)?.text ?? "");
    };
    drawMode();

    // ----- tabs
    const tabBox = h("div", { class: "scroll-x" });
    const panel = h("div");
    const tabs: { id: TabId; label: string; count?: () => number }[] = [
      { id: "waiting", label: "Waiting", count: () => pendingItems.length },
      { id: "flagged", label: "Flagged", count: () => flaggedItems.length },
      { id: "history", label: "History" },
      { id: "library", label: "Library", count: () => libraryTotal },
      { id: "rules", label: "Rules" },
      { id: "test", label: "Test" },
    ];
    const drawTabs = () => mount(tabBox, h("div", { class: "seg-control tabs", role: "tablist" }, tabs.map((t) => {
      const n = t.count?.() ?? 0;
      return h("button", { type: "button", role: "tab", "aria-selected": String(tab === t.id), onclick: () => select(t.id) }, t.label, n ? h("span", { class: `n${t.id === "waiting" ? "" : " alt"}` }, String(n)) : null);
    })));
    const select = (id: TabId) => {
      tab = id;
      history.replaceState(null, "", `#/moderation?tab=${id}`);   // remembers the tab without re-drawing the page
      drawTabs();
      drawPanel();
    };

    // ----- Waiting
    const reload = async () => { await Promise.all([loadPending(), loadFlagged(), loadHistory()]); await refreshStatus(); };
    const waitingView = () => card("inbox", "Waiting for you", pendingItems.length ? approvalList(pendingItems, reload) : empty("check", "Nothing is waiting. Requests appear here when the bot wants to delete, time out or ban someone."), { flush: true });

    // ----- Flagged: built from the same records as Waiting, so the numbers always agree
    let fFilter = "all";
    let fNeedle = "";
    const flaggedView = () => {
      const list = h("div");
      const bar = h("div", { class: "toolbar" });
      const FILTERS = [["all", "All"], ["pending", "Waiting"], ["logged", "Logged only"], ["acted", "Acted on"]];
      const match = (a: Action) => fFilter === "all" || (fFilter === "acted" ? !["pending", "logged"].includes(a.status) : a.status === fFilter);
      const drawList = () => {
        const rows = flaggedItems.filter((a) => match(a) && (!fNeedle || `${a.author_name} ${a.body} ${a.reasons.join(" ")}`.toLowerCase().includes(fNeedle)));
        mount(list, rows.length ? h("ul", { class: "list flag-list" }, rows.slice(0, 80).map((a) => {
          const [tone, text] = flaggedChip(a);
          return h("li", { class: "flag-row" },
            h("div", { class: "appr-top" }, h("strong", { class: "appr-who" }, a.author_name), h("span", { class: `chip ${tone}` }, text), h("span", { class: "chip" }, `${actionLabel(a)} · ${a.score}`), h("span", { class: "grow" }), h("span", { class: "muted small" }, dateTime(a.ts)),
              a.status === "pending" ? h("button", { class: "icon-btn sm ok", type: "button", "aria-label": "Approve", title: "Approve", onclick: (e: Event) => busy(e.currentTarget as HTMLButtonElement, async () => { await post(`/api/moderation/${a.id}/approve`); await reload(); }) }, icon("check", 18)) : null,
              a.status === "pending" ? h("button", { class: "icon-btn sm", type: "button", "aria-label": "Reject", title: "Reject", onclick: (e: Event) => busy(e.currentTarget as HTMLButtonElement, async () => { await post(`/api/moderation/${a.id}/reject`); await reload(); }) }, icon("x", 18)) : null),
            a.body ? h("div", { class: "appr-msg open" }, a.body) : null,
            a.reasons.length ? h("div", { class: "reasons" }, a.reasons.join(", ")) : null);
        })) : empty("flag", flaggedItems.length ? "No flagged messages match." : `No flagged or blocked messages in ${currentMode() === "demo" ? "Demo" : "Live"} yet.`));
      };
      const search = h("input", { type: "search", placeholder: "Search flagged messages", "aria-label": "Search flagged messages", value: fNeedle });
      search.addEventListener("input", () => { fNeedle = search.value.trim().toLowerCase(); drawList(); });
      const chips = () => mount(bar,
        h("div", { class: "scroll-x" }, h("div", { class: "seg-control", role: "group", "aria-label": "Show" }, FILTERS.map(([id, text]) => h("button", { type: "button", "aria-pressed": String(fFilter === id), onclick: () => { fFilter = id; chips(); drawList(); } }, text)))),
        h("div", { class: "input-icon" }, icon("search", 16), search));
      chips();
      drawList();
      return card("flag", "Flagged and blocked", h("div", null, bar, list), { flush: true, actions: h("span", { class: "muted small" }, `${flaggedItems.length} total · ${pendingItems.length} waiting`) });
    };

    // ----- History
    let hFilter = "all";
    let hNeedle = "";
    const historyView = () => {
      const body = h("div"), bar = h("div", { class: "toolbar" });
      const statuses = ["all", ...Array.from(new Set(historyItems.map((a) => a.status)))];
      const drawBody = () => {
        const rows = historyItems.filter((a) => (hFilter === "all" || a.status === hFilter) && (!hNeedle || `${a.author_name} ${a.action} ${a.reasons.join(" ")} ${a.body}`.toLowerCase().includes(hNeedle)));
        mount(body, rows.length ? h("div", { class: "table-wrap" }, h("table", { class: "cards" }, h("thead", null, h("tr", null, ["When", "Who", "Action", "Outcome", "Why"].map((c) => h("th", null, c)))),
          h("tbody", null, rows.map((a) => h("tr", null,
            h("td", { "data-label": "When" }, dateTime(a.ts)), h("td", { "data-label": "Who" }, a.author_name),
            h("td", { "data-label": "Action" }, actionLabel(a)),
            h("td", { "data-label": "Outcome" }, h("div", null, h("span", { class: `chip ${chipFor(a.status)}` }, a.status), a.error ? h("div", { class: "reasons" }, a.error) : null)),
            h("td", { class: "small muted", "data-label": "Why" }, a.reasons.join(", ") || "-"))))))
          : empty("history", historyItems.length ? "No actions match this filter." : "No moderation actions yet."));
      };
      const search = h("input", { type: "search", placeholder: "Search history", "aria-label": "Search history", value: hNeedle });
      search.addEventListener("input", () => { hNeedle = search.value.trim().toLowerCase(); drawBody(); });
      const drawBar = () => mount(bar,
        h("div", { class: "scroll-x" }, h("div", { class: "seg-control", role: "group", "aria-label": "Outcome" }, statuses.map((s) => h("button", { type: "button", "aria-pressed": String(hFilter === s), onclick: () => { hFilter = s; drawBar(); drawBody(); } }, s === "all" ? "All" : s)))),
        h("div", { class: "input-icon" }, icon("search", 16), search),
        h("button", { class: "btn small ghost", type: "button", onclick: () => downloadCsv("moderation-history.csv", [["When", "Who", "Action", "Duration (s)", "Score", "Outcome", "Reasons", "Message", "Demo"], ...historyItems.map((a) => [new Date(a.ts * 1000).toISOString(), a.author_name, a.action, a.duration, a.score, a.status, a.reasons.join("; "), a.body, a.demo ? "yes" : "no"])]) }, icon("download", 15), "CSV"));
      drawBar();
      drawBody();
      return card("history", "History", h("div", null, bar, body), { flush: true });
    };

    // ----- Library
    const lib = libraryPanel(() => void loadLibraryCount());
    const libraryView = () => card("layers", "Library", lib.el, { flush: true, actions: h("span", { class: "muted small" }, "Matches spacing, symbols and look-alike letters") });

    // ----- Rules (the real detection signals, grouped)
    let settingsItems: { name: string; value: unknown }[] = [];
    const valueOf = (n: string) => settingsItems.find((s) => s.name === n)?.value;
    const rulesView = () => {
      const groups = Array.from(new Set(RULES.map((r) => r.cat)));
      return h("div", { class: "stack" },
        h("div", { class: "banner" }, icon("info", 18), h("span", { class: "grow" }, "Each rule adds to a message's score. Thresholds for flagging, deleting, timing out and banning are in Settings.")),
        groups.map((g) => card("sliders", g, h("ul", { class: "list" }, RULES.filter((r) => r.cat === g).map((r) => {
          const on = Boolean(valueOf(`${r.key}_enabled`)), w = valueOf(`${r.key}_weight`);
          const sw = h("input", { type: "checkbox", class: "switch", checked: on, "aria-label": `Enable ${r.title}`, onchange: (e: Event) => {
            const v = (e.target as HTMLInputElement).checked;
            void patch("/api/settings", { values: { [`${r.key}_enabled`]: v } }).then(() => toast(`${r.title} ${v ? "on" : "off"}`)).catch((x) => { (e.target as HTMLInputElement).checked = !v; toast(x.message, "error"); });
          } });
          return h("li", { class: "row between nowrap" }, h("div", { class: "grow" }, h("strong", null, r.title), h("div", { class: "muted small" }, r.text)), h("span", { class: "row nowrap" }, w !== undefined ? h("span", { class: "chip" }, `+${String(w)}`) : null, sw));
        })), { flush: true })),
        h("a", { class: "btn ghost", href: "#/settings" }, icon("sliders", 16), "All moderation settings"));
    };

    // ----- Test
    const testView = () => {
      const text = h("textarea", { placeholder: "Paste a chat message to see how it would score", maxLength: 1000, "aria-label": "Message to score" });
      const level = h("select", { "aria-label": "Chatter level" }, ["everyone", "member", "regular", "mod"].map((l) => h("option", { value: l }, l)));
      const result = h("div", { class: "small", "aria-live": "polite" });
      const test = h("button", { class: "btn primary", type: "submit" }, icon("gauge", 16), "Score it");
      return card("gauge", "Try a message", h("form", { class: "body stack", onsubmit: (e: Event) => {
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
      } }, text, h("div", { class: "row" }, h("label", { class: "field" }, "Chatter level", level), test), result), { flush: true });
    };

    const drawPanel = () => {
      const view = { waiting: waitingView, flagged: flaggedView, history: historyView, library: libraryView, rules: rulesView, test: testView }[tab]();
      mount(panel, view);
      if (tab === "library") void lib.load().catch((e) => toast(e.message, "error"));
      if (tab === "rules") void get<{ items: { name: string; value: unknown }[] }>("/api/settings").then((r) => { settingsItems = r.items; if (tab === "rules") mount(panel, rulesView()); }).catch((e) => toast(e.message, "error"));
    };

    // ----- data
    const loadPending = async () => { pendingItems = (await get<{ items: Action[] }>("/api/moderation/pending")).items; drawTabs(); if (tab === "waiting") drawPanel(); };
    const loadFlagged = async () => { flaggedItems = (await get<{ items: Action[] }>("/api/moderation/flagged")).items; drawTabs(); if (tab === "flagged") drawPanel(); };
    const loadHistory = async () => { historyItems = (await get<{ items: Action[] }>("/api/moderation/history?limit=100")).items; if (tab === "history") drawPanel(); };
    const loadLibraryCount = async () => { libraryTotal = (await get<{ items: unknown[] }>("/api/blacklist")).items.length; drawTabs(); };

    mount(root,
      pageHead("shield", "Moderation", "Decide what the bot does, review what it did, and manage what it looks for.", h("div", { class: "mod-mode" }, modeSeg, modeCap)),
      h("div", { style: "margin-bottom:14px" }, tabBox), panel);
    drawTabs();
    drawPanel();
    const all = () => reload().catch((e) => toast(e.message, "error"));
    void all();
    void loadLibraryCount().catch(() => undefined);
    const offs = [feed.on("mod_pending", all), feed.on("mod_resolved", all), feed.on("mod_logged", all), feed.on("mod_expired", all),
      onStatus((st) => { if (st.hub.mod_mode !== mode) { mode = st.hub.mod_mode; drawMode(); } })];
    return () => offs.forEach((f) => f());
  },
};
