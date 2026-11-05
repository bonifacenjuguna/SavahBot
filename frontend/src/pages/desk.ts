import { get, post } from "../api.js";
import { ago, busy, clock, dateTime, debounce, h, mount, toast } from "../dom.js";
import * as feed from "../events.js";
import { icon } from "../icons.js";
import { ring, sparkline } from "../charts.js";
import { onStatus, status, type Status } from "../state.js";
import { dateRange, rangeQuery, zoomToFill, type RangeValue } from "./kit.js";
import { approvalList, card, empty, pageHead, paneTabs, type Action } from "./shared.js";
import type { Page } from "./types.js";

interface Line { author_name: string; text: string; level: string; ts: number; verdict: string | null; score: number | null; reasons?: string[]; demo?: boolean }
type Filter = "all" | "flagged" | "blocked";

const kindOf = (m: Line): Filter | "ok" => (m.verdict === "allow" || !m.verdict ? "ok" : m.verdict === "flag" ? "flagged" : "blocked");
const SIZES = [0.9, 1, 1.15, 1.3, 1.5];
const SIZE_KEY = "savahbot.chatsize";

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
    let range: RangeValue = { label: "", active: false };
    let saved: Line[] = [];            // rows from the database while a date range is chosen
    let savedNote = "";
    let sizeIdx = (() => { try { const v = Number(localStorage.getItem(SIZE_KEY)); return Number.isInteger(v) && v >= 0 && v < SIZES.length ? v : 1; } catch { return 1; } })();
    const arrivals: number[] = []; // epoch seconds of chat lines, used for the live rate

    const list = h("div", { class: "feed", tabindex: 0, "aria-label": "Live chat", role: "log" });
    const jump = h("button", { class: "jump", type: "button", hidden: true, onclick: () => { stick = true; list.scrollTop = list.scrollHeight; jump.hidden = true; } }, icon("arrowDown", 15), "Latest");
    const pendingBox = h("div");
    const health = h("div");
    const kpis = h("div", { class: "kpis swipe" });
    const savedMode = () => range.active;

    list.addEventListener("scroll", () => {
      stick = list.scrollTop + list.clientHeight >= list.scrollHeight - 30;
      jump.hidden = stick || savedMode();
    });

    // ----- chat lines
    const lineEl = (m: Line, withDate = false): HTMLElement => {
      const k = kindOf(m);
      const cls = k === "ok" ? "" : k === "flagged" ? " flagged" : " blocked";
      return h("div", { class: `line${cls}` }, h("time", { title: dateTime(m.ts) }, withDate ? dateTime(m.ts) : clock(m.ts)),
        h("div", null,
          h("span", { class: `who ${m.level}` }, m.author_name),
          h("span", { class: "text" }, m.text),
          k !== "ok" ? h("div", { class: "reasons" }, `${m.verdict} (score ${m.score ?? 0})${m.reasons?.length ? ": " + m.reasons.join(", ") : ""}`) : null));
    };
    const visible = (m: Line): boolean => {
      if (filter === "flagged" && kindOf(m) === "ok") return false;   // flagged = everything moderation reacted to
      if (filter === "blocked" && kindOf(m) !== "blocked") return false;
      if (needle && !(`${m.author_name} ${m.text}`.toLowerCase().includes(needle))) return false;
      return true;
    };
    const redraw = () => {
      updateCounts();
      if (savedMode()) {
        const rows = saved.filter(visible);
        list.replaceChildren(...rows.map((m) => lineEl(m, true)));
        if (!rows.length) list.appendChild(empty("calendar", savedNote || "No saved chat in this range."));
        list.scrollTop = list.scrollHeight;
        jump.hidden = true;
        return;
      }
      list.replaceChildren(...lines.filter(visible).map((m) => lineEl(m)));
      if (!list.childElementCount) list.appendChild(empty("message", lines.length ? "No chat lines match this filter." : "No chat yet. Lines appear here as they arrive."));
      list.scrollTop = list.scrollHeight;
      stick = true;
      jump.hidden = true;
    };
    let stickQueued = false;       // many lines can arrive in one frame; scroll once per frame, not once per line
    const stickSoon = () => { if (stickQueued) return; stickQueued = true; requestAnimationFrame(() => { stickQueued = false; if (stick) list.scrollTop = list.scrollHeight; }); };
    const push = (m: Line) => {
      lines.push(m);
      queueMicrotask(updateCounts);
      if (lines.length > MAX) lines.shift();
      if (savedMode() || !visible(m)) return;
      list.querySelector(".empty")?.remove();
      list.appendChild(lineEl(m));
      while (list.childElementCount > MAX) list.firstElementChild?.remove();
      if (stick) stickSoon();
    };
    const add = (m: Line) => {
      arrivals.push(m.ts);
      if (arrivals.length > 4000) arrivals.splice(0, arrivals.length - 4000);
      if (paused) { queue.push(m); updatePause(); return; }
      push(m);
    };

    // ----- saved chat (date range)
    const loadSaved = async () => {
      const verdict = filter === "all" ? "" : `&verdict=${filter}`;
      const r = await get<{ items: Line[]; retention_days: number }>(`/api/chat/search?limit=300&q=${encodeURIComponent(needleRaw())}${rangeQuery(range)}${verdict}`);
      saved = r.items;
      savedNote = `Nothing saved for ${range.label.toLowerCase()}. Chat is kept for ${r.retention_days} days.`;
      redraw();
      updateBanner(r.items.length);
    };
    const reload = () => { void loadSaved().catch((e) => toast(e.message, "error")); };
    const needleRaw = () => search.value.trim();
    const banner = h("div", { class: "saved-banner", hidden: true });
    const updateBanner = (n = saved.length) => {
      banner.hidden = !savedMode();
      if (!savedMode()) return;
      mount(banner, icon("calendar", 16), h("span", { class: "grow" }, `Saved chat · ${range.label} · ${n}${n >= 300 ? "+" : ""} line${n === 1 ? "" : "s"}`),
        h("button", { class: "btn small", type: "button", onclick: () => { dates.reset(); range = { label: "", active: false }; saved = []; updateBanner(); updatePause(); redraw(); } }, icon("radio", 14), "Back to live"));
      updatePause();
    };
    const dates = dateRange({ anyLabel: "Live", label: "Chat date range" }, (v) => { range = v; if (v.active) reload(); else { saved = []; updateBanner(); updatePause(); redraw(); } });
    const dateWrap = h("div", { class: "toolbar-dates", hidden: true }, dates.el);
    const dateBtn = h("button", { class: "btn small ghost", type: "button", "aria-expanded": "false", "aria-label": "Filter by date", title: "Filter by date", onclick: () => {
      dateWrap.hidden = !dateWrap.hidden;
      dateBtn.setAttribute("aria-expanded", String(!dateWrap.hidden));
    } }, icon("calendar", 15), h("span", { class: "hide-narrow" }, "Dates"));

    // ----- toolbar: filters, search, pause
    const count = (f: Filter) => (savedMode() ? saved : lines).filter((m) => (f === "flagged" ? kindOf(m) !== "ok" : kindOf(m) === "blocked")).length;
    const updateCounts = () => (["flagged", "blocked"] as Filter[]).forEach((f) => { const n = filterBtns[f === "flagged" ? 1 : 2].querySelector(".n") as HTMLElement; const v = count(f); n.hidden = v === 0; n.textContent = String(v); });
    const filterBtns = (["all", "flagged", "blocked"] as Filter[]).map((f) =>
      h("button", { type: "button", "aria-pressed": String(f === filter), onclick: () => { filter = f; filterBtns.forEach((b, i) => b.setAttribute("aria-pressed", String((["all", "flagged", "blocked"] as Filter[])[i] === f))); if (savedMode()) reload(); else redraw(); } }, f[0].toUpperCase() + f.slice(1), h("span", { class: "n", hidden: true }, "")));
    const search = h("input", { type: "search", placeholder: "Filter chat", "aria-label": "Filter chat", maxLength: 80 });
    const searchSaved = debounce(reload, 300);
    search.addEventListener("input", () => { needle = search.value.trim().toLowerCase(); if (savedMode()) searchSaved(); else redraw(); });
    const pauseBtn = h("button", { class: "btn small ghost", type: "button", onclick: () => {
      paused = !paused;
      if (!paused) { queue.splice(0).forEach(push); }
      updatePause();
    } });
    const updatePause = () => {
      pauseBtn.disabled = savedMode();
      mount(pauseBtn, icon(paused ? "play" : "pause", 15), h("span", { class: "hide-narrow" }, paused ? `Resume${queue.length ? ` (${queue.length})` : ""}` : "Pause"));
      pauseBtn.setAttribute("aria-pressed", String(paused));
      pauseBtn.setAttribute("aria-label", paused ? "Resume chat" : "Pause chat");
    };
    updatePause();
    const toolbar = h("div", { class: "toolbar" },
      h("div", { class: "seg-control", role: "group", "aria-label": "Show" }, filterBtns),
      h("div", { class: "input-icon" }, icon("search", 16), search), dateBtn, pauseBtn);

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
    const sideCount = h("span", { class: "n", hidden: true }, "");
    const loadPending = async () => {
      const r = await get<{ items: Action[] }>("/api/moderation/pending");
      pendingItems = r.items;
      mount(pendingBox, approvalList(r.items, loadPending));
      sideCount.hidden = !r.items.length;
      sideCount.textContent = String(r.items.length);
      (tabs as any).refreshBadges?.();
    };

    // ----- KPI cards and status
    const ratePill = h("span", { class: "rate-pill", title: "Chat lines in the last minute" }, "0/min");
    const renderFacts = () => {
      const s = status;
      if (!s) return;
      const now = Date.now() / 1000;
      const perMin = arrivals.filter((t) => t >= now - 60).length;
      ratePill.textContent = `${perMin}/min`;
      const buckets: number[] = Array.from({ length: 30 }, () => 0);
      for (const t of arrivals) { const i = 29 - Math.floor((now - t) / 60); if (i >= 0 && i < 30) buckets[i]++; }
      const flagged = lines.filter((m) => kindOf(m) !== "ok").length;
      const kpi = (cls: string, ic: string, label: string, value: string, sub?: string, spark?: SVGElement) =>
        h("div", { class: `kpi ${cls}` }, h("div", { class: "kpi-top" }, h("span", null, label), icon(ic, 18)), h("div", { class: "kpi-val" }, value), sub ? h("div", { class: "kpi-sub" }, sub) : null, spark ?? null);
      mount(kpis,
        kpi("", "activity", "Chat rate", `${perMin}/min`, "Last 30 minutes below", sparkline(buckets)),
        kpi("", "message", "Chat lines", String(s.hub.lines), "This session"),
        kpi(flagged ? "warn" : "", "flag", "Flagged", String(flagged), "In the lines on screen"),
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
      status?.hub.mode === "demo" ? h("div", { class: "banner demo" }, icon("flask", 18), h("span", null, "Demo mode: this chat is simulated. Open Demo to run a scenario.")) : null,
      kpis,
      tabs);

    // ----- the chat card, which can grow to fill the workspace
    const main = h("div", { class: "chat-main" }, toolbar, dateWrap, banner, h("div", { class: "feed-wrap" }, list, jump), form);
    const side = h("aside", { class: "zoom-side", "aria-label": "Waiting for you" },
      h("div", { class: "zs-head" }, h("h3", null, icon("inbox", 16), "Waiting for you", sideCount), h("button", { class: "icon-btn zs-close", type: "button", "aria-label": "Close the waiting list", onclick: () => chatPane.classList.remove("side-open") }, icon("x", 18))),
      h("div", { class: "zs-body" }));
    const sideToggle = h("button", { class: "btn small ghost zoom-only", type: "button", "aria-label": "Show what is waiting for you", onclick: () => chatPane.classList.toggle("side-open") }, icon("inbox", 15), h("span", { class: "hide-narrow" }, "Waiting"));
    const sizeDown = h("button", { class: "icon-btn zoom-only", type: "button", "aria-label": "Smaller text", title: "Smaller text", onclick: () => setSize(sizeIdx - 1) }, icon("textSize", 15), h("span", { class: "sz" }, "−"));
    const sizeUp = h("button", { class: "icon-btn zoom-only", type: "button", "aria-label": "Larger text", title: "Larger text", onclick: () => setSize(sizeIdx + 1) }, icon("textSize", 18), h("span", { class: "sz" }, "+"));
    const expandBtn = h("button", { class: "icon-btn expand-btn", type: "button", "aria-label": "Expand the chat to fill the screen", "aria-expanded": "false", title: "Expand chat (F)", onclick: (e: Event) => { e.preventDefault(); zoom.toggle(); } });
    const paintExpand = (open: boolean) => {
      mount(expandBtn, icon(open ? "collapse" : "expand", 18));
      expandBtn.setAttribute("aria-expanded", String(open));
      expandBtn.setAttribute("aria-label", open ? "Shrink the chat back" : "Expand the chat to fill the screen");
      expandBtn.title = open ? "Shrink chat (Esc)" : "Expand chat (F)";
    };
    paintExpand(false);
    const chatPane = card("message", "Chat", h("div", { class: "chat-body" }, main, side), { flush: true, cls: "chat-card",
      actions: h("div", { class: "row nowrap chat-tools" }, ratePill, sizeDown, sizeUp, sideToggle, expandBtn) });
    const setSize = (i: number) => {
      sizeIdx = Math.max(0, Math.min(SIZES.length - 1, i));
      chatPane.style.setProperty("--chat-scale", String(SIZES[sizeIdx]));
      sizeDown.disabled = sizeIdx === 0; sizeUp.disabled = sizeIdx === SIZES.length - 1;
      try { localStorage.setItem(SIZE_KEY, String(sizeIdx)); } catch { /* private mode */ }
    };
    setSize(sizeIdx);

    const queuePane = card("inbox", "Waiting for you", pendingBox, { flush: true });
    const queueBody = queuePane.querySelector(":scope > .body, :scope > div:not(header)") as HTMLElement | null ?? queuePane;
    const statusPane = card("activity", "Bot status", health, { flush: true });
    const sideStack = h("div", { class: "stack" }, queuePane, statusPane);

    const zoom = zoomToFill(chatPane, {
      onOpen: () => {
        paintExpand(true);
        side.querySelector(".zs-body")!.appendChild(pendingBox);     // the waiting list moves in beside the chat
        chatPane.classList.remove("side-open");
        window.requestAnimationFrame(() => { if (stick) list.scrollTop = list.scrollHeight; });
      },
      onClose: () => {
        paintExpand(false);
        chatPane.classList.remove("side-open");
        queueBody.appendChild(pendingBox);
        window.requestAnimationFrame(() => { if (stick) list.scrollTop = list.scrollHeight; });
        expandBtn.focus({ preventScroll: true });
      },
    });
    // the expand button is the only way in or out by touch (one tap); the title bar is not a hidden second button any more

    // panes are switched by the tab control on narrow screens; on wide screens both columns show
    const cols = h("div", { class: "cols" }, chatPane, sideStack);
    root.appendChild(cols);
    const panes: Record<string, HTMLElement> = { chat: chatPane, queue: queuePane, status: statusPane };
    const apply = (id: string) => { for (const [k, el] of Object.entries(panes)) el.setAttribute("data-hidden", String(k !== id)); for (const b of Array.from(tabs.children)) b.setAttribute("aria-selected", String(b.getAttribute("data-id") === id)); };
    for (const b of Array.from(tabs.children)) b.addEventListener("click", () => apply(b.getAttribute("data-id") ?? "chat"));
    for (const el of Object.values(panes)) el.classList.add("pane");
    apply("chat");

    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement | null;
      if (e.key.toLowerCase() !== "f" || e.ctrlKey || e.metaKey || e.altKey) return;
      if (t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.tagName === "SELECT" || t.isContentEditable)) return;
      if (document.querySelector(".sheet, .palette")) return;
      e.preventDefault();
      zoom.toggle();
    };
    document.addEventListener("keydown", onKey);

    get<{ items: Line[] }>("/api/chat/recent?limit=150").then((r) => { r.items.forEach(add); list.scrollTop = list.scrollHeight; if (!lines.length) redraw(); renderFacts(); }).catch((e) => toast(e.message, "error"));
    void loadPending().catch((e) => toast(e.message, "error"));
    renderFacts();
    const offs = [
      feed.on("chat", (e) => { if (Boolean(e.data.demo) === (status?.hub.mode === "demo")) add(e.data); }),
      feed.on("mod_pending", () => void loadPending()),
      feed.on("mod_resolved", () => void loadPending()),
      feed.on("mod_expired", () => void loadPending()),
    ];
    offs.push(onStatus(() => renderFacts()));
    const t = window.setInterval(renderFacts, 5000);
    return () => { offs.forEach((f) => f()); window.clearInterval(t); document.removeEventListener("keydown", onKey); if (zoom.isOpen()) zoom.close(); };
  },
};
