import { get, post } from "../api.js";
import { busy, clock, h, mount, toast } from "../dom.js";
import * as feed from "../events.js";
import { status } from "../state.js";
import { approvalList } from "./shared.js";
import type { Page } from "./types.js";

interface Line { author_name: string; text: string; level: string; ts: number; verdict: string | null; score: number | null; reasons?: string[]; demo?: boolean }

export const desk: Page = {
  id: "desk",
  title: "Desk",
  render(root) {
    const list = h("div", { class: "feed", tabindex: 0, "aria-label": "Live chat", role: "log" });
    const pendingBox = h("div");
    const facts = h("div", { class: "facts" });
    let stick = true;
    list.addEventListener("scroll", () => (stick = list.scrollTop + list.clientHeight >= list.scrollHeight - 30));

    const add = (m: Line) => {
      const cls = m.verdict === "allow" || !m.verdict ? "" : m.verdict === "flag" ? " flagged" : " blocked";
      list.appendChild(
        h("div", { class: `line${cls}` }, h("time", null, clock(m.ts)),
          h("div", null,
            h("span", { class: `who ${m.level}` }, m.author_name),
            h("span", { class: "text" }, m.text),
            m.verdict && m.verdict !== "allow" ? h("div", { class: "reasons" }, `${m.verdict} (score ${m.score ?? 0})${m.reasons?.length ? ": " + m.reasons.join(", ") : ""}`) : null)),
      );
      while (list.childElementCount > 400) list.firstElementChild?.remove();
      if (stick) list.scrollTop = list.scrollHeight;
    };

    const loadPending = async () => {
      const r = await get<{ items: any[] }>("/api/moderation/pending");
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
    const send = h("button", { class: "btn primary", type: "submit" }, "Send");
    const form = h("form", { class: "say", onsubmit: (e: Event) => {
      e.preventDefault();
      const text = input.value.trim();
      if (!text) return;
      busy(send, async () => { await post("/api/chat/send", { text }); input.value = ""; });
    } }, input, send);

    mount(root,
      h("div", { class: "page-head" }, h("h1", null, "Desk"), h("p", null, "Live chat on the left, moderation requests that need your decision on the right.")),
      status?.hub.mode === "demo" ? h("div", { class: "banner demo" }, "Demo mode: this chat is simulated. Open Demo to run a scenario.") : null,
      h("div", { class: "cols" },
        h("section", { class: "block flush" }, h("header", null, h("h2", null, "Chat")), list, form),
        h("div", { class: "stack" },
          h("section", { class: "block flush" }, h("header", null, h("h2", null, "Waiting for you")), pendingBox),
          h("section", { class: "block" }, h("header", null, h("h2", null, "Session")), facts))),
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
