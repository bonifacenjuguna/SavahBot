import { get, post } from "../api.js";
import { ago, busy, clock, h, mount, toast } from "../dom.js";
import * as feed from "../events.js";
import { icon } from "../icons.js";
import { ring, sparkline } from "../charts.js";
import { currentMode, onStatus, status, type Status } from "../state.js";
import { approvalList, card, empty, pageHead, paneTabs, type Action } from "./shared.js";
import type { Page } from "./types.js";

interface Line { author_name: string; text: string; level: string; ts: number; verdict: string | null; score: number | null; reasons?: string[]; demo?: boolean }
type Filter = "all" | "flagged" | "blocked";

/** The one place a chat line is classified. Counts, filter chips and highlighting all use it, so they cannot disagree.
 *  flagged = the rules noticed it and only logged it. blocked = the rules wanted to delete, time out or ban (these also wait in "Waiting for you" in Suggest mode). */
const kindOf = (m: Line): Filter | "ok" => (m.verdict === "allow" || !m.verdict ? "ok" : m.verdict === "flag" ? "flagged" : "blocked");
const inMode = (m: { demo?: boolean }): boolean => Boolean(m.demo) === (currentMode() === "demo");

export const desk: Page = {
  id: "desk",
  title: "Desk",
  icon: "desk",
  blurb: "Live chat and approvals",
  render(root) {
    const MAX = 400;
    const lines: Line[] = [];
    const queue: Line[] = [];
    let filter: Filter = "all";
    let needle = "";
    let paused = false;
    let stick = true;
    let pendingItems: Action[] = [];
    const arrivals: number[] = []; // epoch seconds of chat lines, used for the live rate

    const list = h("div", { class: "feed", tabindex: 0, "aria-label": "Live chat", role: "log" });
    const jump = h("button", { class: "jump", type: "button", hidden: true, onclick: () => { stick = true; list.scrollTop = list.scrollHeight; jump.hidden = true; } }, icon("arrowDown", 15), "Latest");
    const pendingBox = h("div");
    const health = h("div");
    const kpis = h("div", { class: "kpis swipe" });

    list.addEventListener("scroll", () => {
      stick = list.scrollTop + list.clientHeight >= list.scrollHeight - 30;
      jump.hidden = stick;
    });

    // ----- chat lines
    const lineEl = (m: Line): HTMLElement => {
      const k = kindOf(m);
      const cls = k === "ok" ? "" : k === "flagged" ? " flagged" : " blocked";
      return h("div", { class: `line${cls}` }, h("time", null, clock(m.ts)),
        h("div", null,
          h("span", { class: `who ${m.level}` }, m.author_name),
          h("span", { class: "text" }, m.text),
          k !== "ok" ? h("div", { class: "reasons" }, `${m.verdict} (score ${m.score ?? 0})${m.reasons?.length ? ": " + m.reasons.join(", ") : ""}`) : null));
    };
    const visible = (m: Line): boolean => {
      if (filter !== "all" && kindOf(m) !== filter) return false;
      if (needle && !(`${m.author_name} ${m.text}`.toLowerCase().includes(needle))) return false;
      return true;
    };
    const redraw = () => {
      refreshCounts();
      list.replaceChildren(...lines.filter(visible).map(lineEl));
      if (!list.childElementCount) list.appendChild(empty("message", lines.length ? "No chat lines match this filter." : "No chat yet. Lines appear here as they arrive."));
      list.scrollTop = list.scrollHeight;
      stick = true;
      jump.hidden = true;
    };
    const push = (m: Line) => {
      lines.push(m);
      if (lines.length > MAX) lines.shift();
      refreshCounts();
      if (!visible(m)) return;
      list.querySelector(".empty")?.remove();
      list.appendChild(lineEl(m));
      while (list.childElementCount > MAX) list.firstElementChild?.remove();
      if (stick) list.scrollTop = list.scrollHeight;
    };
    const add = (m: Line) => {
      if (!inMode(m)) return;                       // never show a line that belongs to the other mode
      arrivals.push(m.ts);
      if (arrivals.length > 4000) arrivals.splice(0, arrivals.length - 4000);
      if (paused) { queue.push(m); updatePause(); return; }
      push(m);
    };

    // ----- toolbar: filters, search, pause
    const FILTERS: Filter[] = ["all", "flagged", "blocked"];
    const countFor = (f: Filter) => (f === "all" ? lines.length : lines.filter((m) => kindOf(m) === f).length);
    const filterBtns = FILTERS.map((f) =>
      h("button", { type: "button", "aria-pressed": String(f === filter), onclick: () => setFilter(f) }, f[0].toUpperCase() + f.slice(1), h("span", { class: "n alt", "data-count": f }, "")));
    const setFilter = (f: Filter) => {
      filter = f;
      filterBtns.forEach((b, i) => b.setAttribute("aria-pressed", String(FILTERS[i] === f)));
      redraw();
    };
    const refreshCounts = () => filterBtns.forEach((b, i) => { const n = countFor(FILTERS[i]); const el = b.querySelector(".n") as HTMLElement; el.textContent = String(n); el.hidden = FILTERS[i] === "all" || n === 0; });
    const search = h("input", { type: "search", placeholder: "Filter chat", "aria-label": "Filter chat", maxLength: 80 });
    search.addEventListener("input", () => { needle = search.value.trim().toLowerCase(); redraw(); });
    const pauseBtn = h("button", { class: "btn small ghost", type: "button", onclick: () => {
      paused = !paused;
      if (!paused) { queue.splice(0).forEach(push); }
      updatePause();
    } });
    const updatePause = () => {
      mount(pauseBtn, icon(paused ? "play" : "pause", 15), paused ? `Resume${queue.length ? ` (${queue.length})` : ""}` : "Pause");
      pauseBtn.setAttribute("aria-pressed", String(paused));
    };
    updatePause();
    const toolbar = h("div", { class: "toolbar" },
      h("div", { class: "seg-control", role: "group", "aria-label": "Show" }, filterBtns),
      h("div", { class: "input-icon" }, icon("search", 16), search), pauseBtn);

    // ----- send as the bot
    const input = h("input", { type: "text", maxLength: 500, placeholder: "Say something as the bot", "aria-label": "Message to send" });
    const send = h("button", { class: "btn primary", type: "submit" }, icon("send", 16), h("span", null, "Send"));
    const form = h("form", { class: "say", onsubmit: (e: Event) => {
      e.preventDefault();
      const text = input.value.trim();
      if (!text) return;
      busy(send, async () => { await post("/api/chat/send", { text }); input.value = ""; });
    } }, input, send);

    // ----- approvals
    const tabs = paneTabs([
      { id: "chat", label: "Chat" },
      { id: "queue", label: "Waiting", badge: () => pendingItems.length },
      { id: "status", label: "Status" },
    ], {}, "chat");
    const loadPending = async () => {
      const r = await get<{ items: Action[] }>("/api/moderation/pending");
      pendingItems = r.items;
      mount(pendingBox, approvalList(r.items, loadPending));
      (tabs as any).refreshBadges?.();
    };

    // ----- KPI cards and status
    const renderFacts = () => {
      const s = status;
      if (!s) return;
      const now = Date.now() / 1000;
      const perMin = arrivals.filter((t) => t >= now - 60).length;
      const buckets: number[] = Array.from({ length: 30 }, () => 0);
      for (const t of arrivals) { const i = 29 - Math.floor((now - t) / 60); if (i >= 0 && i < 30) buckets[i]++; }
      const flagged = countFor("flagged"), blocked = countFor("blocked");
      const kpi = (cls: string, ic: string, label: string, value: string, sub?: string, spark?: SVGElement, onpick?: () => void) => {
        const el = h("div", { class: `kpi ${cls}${onpick ? " pick" : ""}` }, h("div", { class: "kpi-top" }, h("span", null, label), icon(ic, 18)), h("div", { class: "kpi-val" }, value), sub ? h("div", { class: "kpi-sub" }, sub) : null, spark ?? null);
        if (onpick) { el.tabIndex = 0; el.setAttribute("role", "button"); el.addEventListener("click", onpick); el.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onpick(); } }); }
        return el;
      };
      const showChat = (f: Filter) => () => { setFilter(f); chatPane.setAttribute("data-hidden", "false"); tabs.querySelector<HTMLElement>('[data-id="chat"]')?.click(); };
      mount(kpis,
        kpi("", "activity", "Chat rate", `${perMin}/min`, "Last 30 minutes below", sparkline(buckets)),
        kpi("", "message", "Chat lines", String(s.hub.lines), "This session"),
        kpi(flagged ? "warn" : "", "flag", "Flagged", String(flagged), "Logged only. Tap to show", undefined, showChat("flagged")),
        kpi(blocked ? "bad" : "", "ban", "Blocked", String(blocked), "Delete, timeout or ban. Tap to show", undefined, showChat("blocked")),
        kpi(s.pending ? "warn" : "", "inbox", "Waiting for you", String(s.pending), s.pending ? "Needs a decision" : "All clear"),
        kpi("", "shield", "Moderation", s.hub.mod_mode, `${s.hub.blacklist_size} blocked phrases`));
      mount(health, healthBlock(s));
    };
    const healthBlock = (s: Status): HTMLElement => {
      const q = s.youtube.quota;
      const pct = Math.min(100, Math.round(q.fraction * 100));
      const row = (ic: string, title: string, text: string, chip: [string, string]) =>
        h("div", { class: "status-row" }, icon(ic, 18), h("div", { class: "grow" }, h("div", null, title), h("div", { class: "muted small" }, text)), h("span", { class: `chip ${chip[0]}` }, chip[1]));
      return h("div", null,
        h("div", { class: "health" }, ring(s.hub.mode === "demo" ? 0 : q.fraction, s.hub.mode === "demo" ? "Demo" : `${pct}%`, "YouTube quota used today", pct >= 75 ? "hot" : ""),
          h("dl", null, h("dt", null, "YouTube quota"), h("dd", null, s.hub.mode === "demo" ? "Not used in demo mode" : `${q.used} of ${q.daily} units used`),
            h("dt", null, "Last chat poll"), h("dd", null, s.hub.mode === "demo" ? "Simulated" : ago(s.youtube.last_poll)))),
        h("div", { class: "status-rows" },
          row("youtube", "YouTube", s.youtube.chat_attached ? (s.youtube.title || "Chat attached") : s.youtube.connected ? "Connected, no stream attached" : "Not connected", s.youtube.last_error ? ["bad", "Error"] : s.youtube.chat_attached ? ["ok", "Attached"] : s.youtube.connected ? ["warn", "Idle"] : ["", "Off"]),
          row("telegram", "Telegram", s.telegram.configured ? (s.telegram.bot_username ? `@${s.telegram.bot_username} (${s.telegram.mode})` : s.telegram.mode) : "No bot token", s.telegram.last_error ? ["bad", "Error"] : s.telegram.configured && s.telegram.owner_bound ? ["ok", "Ready"] : ["warn", s.telegram.configured ? "Not claimed" : "Off"]),
          row("database", "Database", s.database, ["ok", "OK"])));
    };

    mount(root,
      pageHead("desk", "Desk", "Live chat, moderation requests that need your decision, and the state of the bot.", status?.hub.mode === "demo" ? h("a", { class: "btn ghost", href: "#/demo" }, icon("flask", 16), "Run a scenario") : null),
      status?.hub.mode === "demo" ? h("div", { class: "banner demo" }, icon("flask", 18), h("span", null, "Demo mode: this chat is simulated. Open Demo to run a scenario."))
        : status && status.hub.state === "standby" ? h("div", { class: "banner" }, icon("clock", 18), h("span", null, status.youtube.connected ? "Standby: Live mode is on and waiting for your stream to start. Chat appears here once it does." : "Standby: YouTube is not connected yet. Open Setup to connect it.")) : null,
      kpis,
      tabs);

    const chatPane = card("message", "Chat", h("div", null, toolbar, h("div", { class: "feed-wrap" }, list, jump), form), { flush: true });
    const queuePane = card("inbox", "Waiting for you", pendingBox, { flush: true });
    const statusPane = card("activity", "Bot status", health, { flush: true });
    const side = h("div", { class: "stack" }, queuePane, statusPane);
    // panes are switched by the tab control on narrow screens; on wide screens both columns show
    const cols = h("div", { class: "cols" }, chatPane, side);
    root.appendChild(cols);
    // wire the narrow-screen tabs to the three blocks
    const panes: Record<string, HTMLElement> = { chat: chatPane, queue: queuePane, status: statusPane };
    const apply = (id: string) => { for (const [k, el] of Object.entries(panes)) el.setAttribute("data-hidden", String(k !== id)); for (const b of Array.from(tabs.children)) b.setAttribute("aria-selected", String(b.getAttribute("data-id") === id)); };
    for (const b of Array.from(tabs.children)) b.addEventListener("click", () => apply(b.getAttribute("data-id") ?? "chat"));
    for (const el of Object.values(panes)) el.classList.add("pane");
    apply("chat");

    get<{ items: Line[] }>("/api/chat/recent?limit=150").then((r) => { r.items.forEach(add); list.scrollTop = list.scrollHeight; if (!lines.length) redraw(); renderFacts(); }).catch((e) => toast(e.message, "error"));
    void loadPending().catch((e) => toast(e.message, "error"));
    renderFacts();
    const offs = [
      feed.on("chat", (e) => add(e.data)),
      feed.on("mod_pending", () => void loadPending()),
      feed.on("mod_resolved", () => void loadPending()),
      feed.on("mod_expired", () => void loadPending()),
    ];
    offs.push(onStatus(() => renderFacts()));
    const t = window.setInterval(renderFacts, 5000);
    return () => { offs.forEach((f) => f()); window.clearInterval(t); };
  },
};
