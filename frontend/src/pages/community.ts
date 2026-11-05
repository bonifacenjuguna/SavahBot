import { del, get, post } from "../api.js";
import { busy, h, mount, toast } from "../dom.js";
import { icon } from "../icons.js";
import { card, empty, pageHead } from "./shared.js";
import type { Page } from "./types.js";

export const community: Page = {
  id: "community",
  title: "Community",
  icon: "users",
  blurb: "Quotes and trusted regulars",
  render(root) {
    const quotesBox = h("div"), regBox = h("div");
    const countQ = h("span", { class: "chip" }, "0"), countR = h("span", { class: "chip" }, "0");
    const loadQuotes = async () => {
      const r = await get<{ items: { id: number; body: string; author: string }[] }>("/api/quotes");
      countQ.textContent = String(r.items.length);
      const body = h("input", { type: "text", required: true, maxLength: 500, placeholder: "A memorable line", "aria-label": "Quote" });
      const author = h("input", { type: "text", maxLength: 100, placeholder: "Who said it", "aria-label": "Author" });
      const add = h("button", { class: "btn primary", type: "submit" }, icon("plus", 16), "Add quote");
      mount(quotesBox, h("form", { class: "body stack", onsubmit: (e: Event) => { e.preventDefault(); busy(add, async () => { await post("/api/quotes", { body: body.value, author: author.value }); await loadQuotes(); }); } }, body, h("div", { class: "row" }, h("div", { class: "grow" }, author), add)),
        r.items.length ? h("ul", { class: "list" }, r.items.map((q) => h("li", { class: "row between nowrap" },
          h("span", { class: "grow" }, h("span", { class: "chip mono" }, `#${q.id}`), ` “${q.body}”`, q.author ? h("span", { class: "muted" }, ` by ${q.author}`) : null),
          h("button", { class: "btn small danger", "aria-label": `Delete quote ${q.id}`, onclick: (e: Event) => busy(e.currentTarget as HTMLButtonElement, async () => { await del(`/api/quotes/${q.id}`); await loadQuotes(); }) }, icon("trash", 15), "Delete")))) : empty("quote", "No quotes yet. Viewers can also use !addquote."));
    };
    const loadReg = async () => {
      const r = await get<{ items: { id: number; ident: string; label: string }[] }>("/api/regulars");
      countR.textContent = String(r.items.length);
      const ident = h("input", { type: "text", required: true, maxLength: 200, placeholder: "YouTube channel ID or display name", "aria-label": "Channel ID or name" });
      const label = h("input", { type: "text", maxLength: 100, placeholder: "Note (optional)", "aria-label": "Note" });
      const add = h("button", { class: "btn primary", type: "submit" }, icon("star", 16), "Add regular");
      mount(regBox, h("form", { class: "body stack", onsubmit: (e: Event) => { e.preventDefault(); busy(add, async () => { await post("/api/regulars", { ident: ident.value, label: label.value }); await loadReg(); }); } },
        h("p", { class: "muted small" }, "Regulars are trusted: they get softer moderation and can use regular-only commands. Chatters also earn this automatically over time."), ident, h("div", { class: "row" }, h("div", { class: "grow" }, label), add)),
        r.items.length ? h("ul", { class: "list" }, r.items.map((x) => h("li", { class: "row between nowrap" }, h("span", { class: "grow" }, icon("star", 14), " ", h("span", { class: "mono" }, x.ident), x.label ? h("span", { class: "muted" }, `  ${x.label}`) : null),
          h("button", { class: "btn small danger", "aria-label": `Remove ${x.ident}`, onclick: (e: Event) => busy(e.currentTarget as HTMLButtonElement, async () => { await del(`/api/regulars/${x.id}`); await loadReg(); }) }, icon("x", 15), "Remove")))) : empty("users", "No regulars yet."));
    };
    mount(root, pageHead("users", "Community", "The quotes your chat remembers and the viewers you trust."), h("div", { class: "cols even" },
      card("quote", "Quotes", quotesBox, { flush: true, actions: countQ }), card("star", "Regulars", regBox, { flush: true, actions: countR })));
    void loadQuotes().catch((e) => toast(e.message, "error"));
    void loadReg().catch((e) => toast(e.message, "error"));
  },
};
