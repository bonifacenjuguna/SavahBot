import { get, post } from "../api.js";
import { busy, clock, h, mount, toast } from "../dom.js";
import * as feed from "../events.js";
import { icon } from "../icons.js";
import { status } from "../state.js";
import { approvalList } from "./shared.js";
import type { Page } from "./types.js";

interface Line { author_name: string; text: string; level: string; ts: number; verdict: string | null; score: number | null; reasons?: string[]; demo?: boolean }

type Filter = "all" | "flagged" | "blocked" | "staff";
const FILTERS: [Filter, string][] = [["all", "All"], ["flagged", "Flagged"], ["blocked", "Blocked"], ["staff", "Staff"]];

export const desk: Page = {
  id: "desk",
  title: "Desk",
  render(root) {
    const list = h("div", { class: "feed", tabindex: 0, "aria-label": "Live chat", role: "log", "data-filter": "all" });
    const pendingBox = h("div");
    const facts = h("div", { class: "facts" });
    const newCount = h("span", null, "");
    const jump = h("button", { class: "btn small primary jump", type: "button", hidden: true, onclick: () => { list.scrollTop = list.scrollHeight; } }, icon("arrowDown", 14), newCount);
    const queueTab = h("span", { class: "count", hidden: true }, "");
    let stick = true;
    let unread = 0;
    let query = "";
    list.addEventListener("scroll", () => {
      stick = list.scrollTop + list.clientHeight >= list.scrollHeight - 30;
      if (stick) { unread = 0; jump.hidden = true; }
    });

    const matches = (el: HTMLElement) => !query || (el.dataset.text ?? "").includes(query);
    const add = (m: Line) => {
      const cls = m.verdict === "allow" || !m.verdict ? "" : m.verdict === "flag" ? " flagged" : " blocked";
      const staff = m.level === "owner" || m.level === "mod";
      const badge = m.level === "owner" ? icon("crown", 13) : m.level === "mod" ? icon("wrench", 13) : m.level === "member" ? icon("star", 13) : null;
      const line = h("div", { class: `line${cls}${staff ? " staff" : ""}`, "data-text": `${m.author_name} ${m.text}`.toLowerCase() },
        h("time", null, clock(m.ts)),
        h("div", null,
          h("span", { class: `who ${m.level}`, title: m.level === "everyone" ? undefined : m.level }, badge, m.author_name),
          h("span", { class: "text" }, m.text),
          m.verdict && m.verdict !== "allow" ? h("div", { class: "reasons" }, `${m.verdict} (score ${m.score ?? 0})${m.reasons?.length ? ": " + m.reasons.join(", ") : ""}`) : null));
      line.hidden = !matches(line);
      list.appendChild(line);
      while (list.childElementCount > 400) list.firstElementChild?.remove();
      if (stick) list.scrollTop = list.scrollHeight;
      else if (!line.hidden) { unread++; newCount.textContent = `${unread} new`; jump.hidden = false; }
    };

    const setFilter = (f: Filter) => {
      list.setAttribute("data-filter", f);
      chips.forEach(([id, b]) => b.setAttribute("aria-pressed", String(id === f)));
      if (stick) list.scrollTop = list.scrollHeight;
    };
    const chips = FILTERS.map(([id, label]) => [id, h("button", { type: "button", class: "chipbtn", "aria-pressed": String(id === "all"), onclick: () => setFilter(id) }, label)] as [Filter, HTMLButtonElement]);
    const search = h("input", { type: "search", placeholder: "Search chat", "aria-label": "Search chat", class: "feed-search" });
    search.addEventListener("input", () => {
      query = search.value.trim().toLowerCase();
      list.querySelectorAll<HTMLElement>(".line").forEach((l) => (l.hidden = !matches(l)));
    });

    let pendingCount = 0;
    const loadPending = async () => {
      const r = await get<{ items: any[] }>("/api/moderation/pending");
      pendingCount = r.items.length;
      queueTab.hidden = pendingCount === 0;
      queueTab.textContent = String(pendingCount);
      mount(pendingBox, approvalList(r.items, loadPending));
    };
    const renderFacts = () => {
      const s = status;
      if (!s) return;
      mount(facts,
        h("div", null, h("b", null, String(s.hub.lines)), h("span", null, "chat lines this session")),
        h("div", null, h("b", null, s.hub.mod_mode), h("span", null, "moderation mode")),
        h("div", null, h("b", null, String(s.hub.blacklist_size)), h("span", null, "blocked phrases")),
      );
    };

    const input = h("input", { type: "text", maxLength: 500, placeholder: "Say something as the bot", "aria-label": "Message to send" });
    const send = h("button", { class: "btn primary", type: "submit" }, icon("send", 16), h("span", { class: "label-sm" }, "Send"));
    const form = h("form", { class: "say", onsubmit: (e: Event) => {
      e.preventDefault();
      const text = input.value.trim();
      if (!text) return;
      busy(send, async () => { await post("/api/chat/send", { text }); input.value = ""; });
    } }, input, send);

    // Phones show one panel at a time (chat or the approval queue); wider screens show both side by side.
    const cols = h("div", { class: "cols desk-cols", "data-view": "chat" });
    const setView = (v: "chat" | "queue") => {
      cols.setAttribute("data-view", v);
      tabChat.setAttribute("aria-pressed", String(v === "chat"));
      tabQueue.setAttribute("aria-pressed", String(v === "queue"));
      if (v === "chat") list.scrollTop = list.scrollHeight;
    };
    const tabChat = h("button", { type: "button", "aria-pressed": "true", onclick: () => setView("chat") }, icon("desk", 16), "Chat");
    const tabQueue = h("button", { type: "button", "aria-pressed": "false", onclick: () => setView("queue") }, icon("shield", 16), "Waiting", queueTab);

    mount(cols,
      h("section", { class: "block flush chat-block" },
        h("header", null, h("h2", null, "Chat"), h("div", { class: "feed-tools" }, search, h("div", { class: "chipbar", role: "group", "aria-label": "Filter chat" }, chips.map(([, b]) => b)))),
        h("div", { class: "feed-wrap" }, list, jump), form),
      h("div", { class: "stack queue-block" },
        h("section", { class: "block flush" }, h("header", null, h("h2", null, "Waiting for you")), pendingBox),
        h("section", { class: "block" }, h("header", null, h("h2", null, "Session")), facts)));

    mount(root,
      h("div", { class: "page-head desk-head" }, h("h1", null, "Desk"), h("p", null, "Live chat, and the moderation requests that need your decision.")),
      status?.hub.mode === "demo" ? h("div", { class: "banner demo" }, icon("flask", 18), "Demo mode: this chat is simulated. Open Demo to run a scenario.") : null,
      h("div", { class: "segment desk-tabs", role: "group", "aria-label": "Panel" }, tabChat, tabQueue),
      cols,
    );

    get<{ items: Line[] }>("/api/chat/recent?limit=150").then((r) => { r.items.forEach(add); list.scrollTop = list.scrollHeight; }).catch((e) => toast(e.message, "error"));
    void loadPending().catch((e) => toast(e.message, "error"));
    renderFacts();
    const offs = [
      feed.on("chat", (e) => add(e.data)),
      feed.on("mod_pending", () => void loadPending()),
      feed.on("mod_resolved", () => void loadPending()),
      feed.on("mod_expired", () => void loadPending()),
    ];
    const t = window.setInterval(renderFacts, 5000);
    return () => { offs.forEach((f) => f()); window.clearInterval(t); };
  },
};
