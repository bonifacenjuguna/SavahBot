import { del, get, post } from "../api.js";
import { busy, h, mount, toast } from "../dom.js";
import type { Page } from "./types.js";

export const community: Page = {
  id: "community",
  title: "Community",
  render(root) {
    const quotesBox = h("div"), regBox = h("div");
    const loadQuotes = async () => {
      const r = await get<{ items: { id: number; body: string; author: string }[] }>("/api/quotes");
      const body = h("input", { type: "text", required: true, maxLength: 500, placeholder: "A memorable line" });
      const author = h("input", { type: "text", maxLength: 100, placeholder: "Who said it" });
      const add = h("button", { class: "btn primary", type: "submit" }, "Add quote");
      mount(quotesBox, h("form", { class: "body stack", onsubmit: (e: Event) => { e.preventDefault(); busy(add, async () => { await post("/api/quotes", { body: body.value, author: author.value }); await loadQuotes(); }); } }, body, h("div", { class: "row" }, h("div", { class: "grow" }, author), add)),
        r.items.length ? h("ul", { class: "list" }, r.items.map((q) => h("li", { class: "row between" }, h("span", null, `#${q.id} “${q.body}”`, q.author ? h("span", { class: "muted" }, ` by ${q.author}`) : null),
          h("button", { class: "btn small danger", onclick: (e: Event) => busy(e.currentTarget as HTMLButtonElement, async () => { await del(`/api/quotes/${q.id}`); await loadQuotes(); }) }, "Delete")))) : h("div", { class: "empty" }, "No quotes yet. Viewers can also use !addquote."));
    };
    const loadReg = async () => {
      const r = await get<{ items: { id: number; ident: string; label: string }[] }>("/api/regulars");
      const ident = h("input", { type: "text", required: true, maxLength: 200, placeholder: "YouTube channel ID or display name" });
      const label = h("input", { type: "text", maxLength: 100, placeholder: "Note (optional)" });
      const add = h("button", { class: "btn primary", type: "submit" }, "Add regular");
      mount(regBox, h("form", { class: "body stack", onsubmit: (e: Event) => { e.preventDefault(); busy(add, async () => { await post("/api/regulars", { ident: ident.value, label: label.value }); await loadReg(); }); } },
        h("p", { class: "muted small" }, "Regulars are trusted: they get softer moderation and can use regular-only commands. Chatters also earn this automatically over time."), ident, h("div", { class: "row" }, h("div", { class: "grow" }, label), add)),
        r.items.length ? h("ul", { class: "list" }, r.items.map((x) => h("li", { class: "row between" }, h("span", null, h("span", { class: "mono" }, x.ident), x.label ? h("span", { class: "muted" }, `  ${x.label}`) : null),
          h("button", { class: "btn small danger", onclick: (e: Event) => busy(e.currentTarget as HTMLButtonElement, async () => { await del(`/api/regulars/${x.id}`); await loadReg(); }) }, "Remove")))) : h("div", { class: "empty" }, "No regulars yet."));
    };
    mount(root, h("div", { class: "page-head" }, h("h1", null, "Community")), h("div", { class: "cols" },
      h("section", { class: "block flush" }, h("header", null, h("h2", null, "Quotes")), quotesBox), h("section", { class: "block flush" }, h("header", null, h("h2", null, "Regulars")), regBox)));
    void loadQuotes().catch((e) => toast(e.message, "error"));
    void loadReg().catch((e) => toast(e.message, "error"));
  },
};
