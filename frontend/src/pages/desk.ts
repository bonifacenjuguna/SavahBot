import { get, post } from "../api.js";
import { ago, busy, clock, h, mount, toast } from "../dom.js";
import * as feed from "../events.js";
import { icon } from "../icons.js";
import { ring, sparkline } from "../charts.js";
import { onStatus, status, type Status } from "../state.js";
import { approvalList, card, empty, pageHead, paneTabs, type Action } from "./shared.js";
import type { Page } from "./types.js";

interface Line { author_name: string; text: string; level: string; ts: number; verdict: string | null; score: number | null; reasons?: string[]; demo?: boolean }
type Filter = "all" | "flagged" | "blocked";

const kindOf = (m: Line): Filter | "ok" => (m.verdict === "allow" || !m.verdict ? "ok" : m.verdict === "flag" ? "flagged" : "blocked");

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
      if (filter === "flagged" && kindOf(m) === "ok") return false;   // flagged = everything moderation reacted to
      if (filter === "blocked" && kindOf(m) !== "blocked") return false;
      if (needle && !(`${m.author_name} ${m.text}`.toLowerCase().includes(needle))) return false;
      return true;
    };
    const redraw = () => {
      updateCounts();
      list.replaceChildren(...lines.filter(visible).map(lineEl));
      if (!list.childElementCount) list.appendChild(empty("message", lines.length ? "No chat lines match this filter." : "No chat yet. Lines appear here as they arrive."));
      list.scrollTop = list.scrollHeight;
      stick = true;
      jump.hidden = true;
    };
    const push = (m: Line) => {
      lines.push(m);
      queueMicrotask(updateCounts);
      if (lines.length > MAX) lines.shift();
      if (!visible(m)) return;
      list.querySelector(".empty")?.remove();
      list.appendChild(lineEl(m));
      while (list.childElementCount > MAX) list.firstElementChild?.remove();
      if (stick) list.scrollTop = list.scrollHeight;
    };
    const add = (m: Line) => {
      arrivals.push(m.ts);
      if (arrivals.length > 4000) arrivals.splice(0, arrivals.length - 4000);
      if (paused) { queue.push(m); updatePause(); return; }
      push(m);
    };

    // ----- toolbar: filters, search, pause
    const count = (f: Filter) => lines.filter((m) => (f === "flagged" ? kindOf(m) !== "ok" : kindOf(m) === "blocked")).length;
    const updateCounts = () => (["flagged", "blocked"] as Filter[]).forEach((f) => { const n = filterBtns[f === "flagged" ? 1 : 2].querySelector(".n") as HTMLElement; const v = count(f); n.hidden = v === 0; n.textContent = String(v); });
    const filterBtns = (["all", "flagged", "blocked"] as Filter[]).map((f) =>
      h("button", { type: "button", "aria-pressed": String(f === filter), onclick: () => { filter = f; filterBtns.forEach((b, i) => b.setAttribute("aria-pressed", String((["all", "flagged", "blocked"] as Filter[])[i] === f))); redraw(); } }, f[0].toUpperCase() + f.slice(1), h("span", { class: "n", hidden: true }, "")));
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

    // ----- expandable chat (desktop). The same DOM node grows to a large workspace, so history, scrolling,
    // typed text and live updates all carry on untouched. A placeholder keeps the page layout from jumping.
    const expandBtn = h("button", { class: "btn small ghost chat-expand", type: "button", "aria-expanded": "false", "aria-label": "Expand chat", title: "Expand chat (Esc closes)" }, icon("maximize", 16), h("span", null, "Expand"));
    const chatPane = card("message", "Chat", h("div", { class: "chat-inner" }, toolbar, h("div", { class: "feed-wrap" }, list, jump), form), { flush: true, cls: "chat-card", actions: expandBtn });
    const backdrop = h("div", { class: "chat-backdrop", hidden: true });
    let holder: HTMLElement | null = null;
    let expanded = false;
    let animating = false;
    const calm = () => typeof matchMedia === "function" && matchMedia("(prefers-reduced-motion: reduce)").matches;
    const flip = async (from: DOMRect, to: DOMRect, reverse = false) => {
      if (calm() || typeof chatPane.animate !== "function") return;
      const dx = from.left - to.left, dy = from.top - to.top, sx = from.width / to.width, sy = from.height / to.height;
      const small = `translate(${dx}px, ${dy}px) scale(${sx}, ${sy})`;
      animating = true;
      try {
        await chatPane.animate(reverse ? [{ transform: "none" }, { transform: small }] : [{ transform: small }, { transform: "none" }],
          { duration: 300, easing: "cubic-bezier(0.2, 0.8, 0.2, 1)" }).finished;
      } catch { /* an interrupted animation is harmless */ }
      animating = false;
    };
    const setExpanded = async (on: boolean) => {
      if (on === expanded || animating) return;
      const atBottom = list.scrollHeight - list.scrollTop - list.clientHeight < 40;
      const first = chatPane.getBoundingClientRect();
      expanded = on;
      expandBtn.setAttribute("aria-expanded", String(on));
      expandBtn.setAttribute("aria-label", on ? "Close expanded chat" : "Expand chat");
      mount(expandBtn, icon(on ? "minimize" : "maximize", 16), h("span", null, on ? "Close" : "Expand"));
      if (on) {
        holder = h("div", { class: "chat-holder", style: `height:${first.height}px` });
        chatPane.before(holder);
        backdrop.hidden = false;
        document.body.classList.add("chat-open");
        chatPane.classList.add("is-expanded");
        chatPane.setAttribute("role", "dialog");
        chatPane.setAttribute("aria-label", "Chat workspace");
        await flip(first, chatPane.getBoundingClientRect());
      } else {
        const last = holder?.getBoundingClientRect() ?? first;
        backdrop.hidden = true;
        await flip(last, first, true);
        chatPane.classList.remove("is-expanded");
        chatPane.removeAttribute("role");
        chatPane.removeAttribute("aria-label");
        document.body.classList.remove("chat-open");
        holder?.remove();
        holder = null;
      }
      if (atBottom) list.scrollTop = list.scrollHeight;
      expandBtn.focus({ preventScroll: true });
    };
    expandBtn.addEventListener("click", () => void setExpanded(!expanded));
    backdrop.addEventListener("pointerdown", () => void setExpanded(false));
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape" && expanded && !document.querySelector(".overlay")) { e.preventDefault(); void setExpanded(false); } };
    document.addEventListener("keydown", onKey);
    // leaving the expanded state if the window shrinks to a size where the layout is a single column
    const narrow = typeof matchMedia === "function" ? matchMedia("(max-width: 999px)") : null;
    const onNarrow = () => { if (narrow?.matches && expanded) { chatPane.classList.remove("is-expanded"); backdrop.hidden = true; document.body.classList.remove("chat-open"); holder?.remove(); holder = null; expanded = false; mount(expandBtn, icon("maximize", 16), h("span", null, "Expand")); expandBtn.setAttribute("aria-expanded", "false"); } };
    narrow?.addEventListener("change", onNarrow);
    document.body.appendChild(backdrop);
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
      feed.on("chat", (e) => { if (Boolean(e.data.demo) === (status?.hub.mode === "demo")) add(e.data); }),
      feed.on("mod_pending", () => void loadPending()),
      feed.on("mod_resolved", () => void loadPending()),
      feed.on("mod_expired", () => void loadPending()),
    ];
    offs.push(onStatus(() => renderFacts()));
    const t = window.setInterval(renderFacts, 5000);
    return () => {
      offs.forEach((f) => f()); window.clearInterval(t);
      document.removeEventListener("keydown", onKey); narrow?.removeEventListener("change", onNarrow);
      backdrop.remove(); document.body.classList.remove("chat-open");
    };
  },
};
