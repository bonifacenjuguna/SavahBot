import { del, get, post } from "../api.js";
import { busy, h, mount, toast } from "../dom.js";
import { icon } from "../icons.js";
import { areaNav } from "./kit.js";
import { pageHead, paneTabs } from "./shared.js";
import type { Page } from "./types.js";
import { avatar, confirmAct, figures, iconAct, invite, plural } from "./widgets.js";

interface Quote { id: number; body: string; author: string }
interface Regular { id: number; ident: string; label: string }

const copy = (text: string, done = "Copied") => { void navigator.clipboard?.writeText(text).then(() => toast(done)).catch(() => toast("Your browser blocked copying.", "error")); };

export const community: Page = {
  id: "community",
  title: "Community",
  icon: "users",
  blurb: "Quotes and trusted regulars",
  render(root, query) {
    let quotes: Quote[] = [];
    let regulars: Regular[] = [];
    let needle = "";
    let spot: Quote | null = null;

    // ================================================================== quotes
    const qBody = h("input", { type: "text", required: true, maxLength: 500, placeholder: "A line your chat will remember", "aria-label": "Quote", autocomplete: "off" });
    const qAuthor = h("input", { type: "text", maxLength: 100, placeholder: "Who said it", "aria-label": "Who said it", autocomplete: "off" });
    const qAdd = h("button", { class: "btn primary", type: "submit" }, icon("plus", 16), "Add quote");
    const quoteForm = h("form", { class: "wb-form", onsubmit: (e: Event) => {
      e.preventDefault();
      busy(qAdd, async () => { await post("/api/quotes", { body: qBody.value, author: qAuthor.value }); qBody.value = ""; await loadQuotes(); qBody.focus(); }, "Quote added");
    } }, qBody, h("div", { class: "wb-row" }, h("div", { class: "grow" }, qAuthor), qAdd));
    const quoteBench = h("section", { class: "wb", "aria-label": "Add a quote" }, h("h2", null, "Add a quote"), quoteForm);

    const spotlight = h("div");
    const drawSpotlight = () => {
      if (!quotes.length) { mount(spotlight, null); return; }
      if (!spot || !quotes.some((q) => q.id === spot!.id)) spot = quotes[Math.floor(Math.random() * quotes.length)];
      const s = spot;
      mount(spotlight, h("figure", { class: "spot" },
        h("span", { class: "spot-mark", "aria-hidden": "true" }, icon("quote", 30)),
        h("blockquote", null, s.body),
        h("figcaption", null, s.author ? `by ${s.author}` : "Unknown", h("span", { class: "muted" }, `   !quote ${s.id}`)),
        quotes.length > 1 ? h("button", { class: "btn small ghost", type: "button", onclick: () => { const others = quotes.filter((q) => q.id !== s.id); spot = others[Math.floor(Math.random() * others.length)]; drawSpotlight(); } }, icon("shuffle", 15), "Another") : null));
    };

    const quoteList = h("div");
    const drawQuotes = () => {
      const list = quotes.filter((q) => !needle || `${q.body} ${q.author} #${q.id}`.toLowerCase().includes(needle));
      if (!quotes.length) { mount(quoteList, invite("quote", "No quotes yet", "Save the lines your chat laughs about. Viewers can pull one up with !quote, and add one with !addquote.")); return; }
      if (!list.length) { mount(quoteList, invite("search", "No quotes match", "Try another word or a quote number.")); return; }
      mount(quoteList, h("ul", { class: "q-list" }, list.map((q) => h("li", { class: "q-item" },
        h("span", { class: "q-id", title: "Viewers type this number after !quote" }, `#${q.id}`),
        h("div", { class: "q-main" }, h("p", { class: "q-text" }, `“${q.body}”`), q.author ? h("span", { class: "muted small" }, `by ${q.author}`) : null),
        h("div", { class: "acts" },
          iconAct("terminal", `Copy the command to show quote ${q.id}`, () => copy(`!quote ${q.id}`, `Copied !quote ${q.id}`)),
          iconAct("copy", "Copy the quote text", () => copy(q.body)),
          confirmAct({ icon: "trash", label: `Delete quote ${q.id}`, onConfirm: async () => { try { await del(`/api/quotes/${q.id}`); await loadQuotes(); toast("Quote deleted"); } catch (e) { toast((e as Error).message, "error"); } } }))))));
    };
    const loadQuotes = async () => { quotes = (await get<{ items: Quote[] }>("/api/quotes")).items; drawFigures(); drawSpotlight(); drawQuotes(); tabs.refreshBadges(); };

    // ================================================================== regulars
    const rIdent = h("input", { type: "text", required: true, maxLength: 200, placeholder: "YouTube channel ID or display name", "aria-label": "Channel ID or name", autocomplete: "off" });
    const rLabel = h("input", { type: "text", maxLength: 100, placeholder: "Note (optional)", "aria-label": "Note", autocomplete: "off" });
    const rAdd = h("button", { class: "btn primary", type: "submit" }, icon("userPlus", 16), "Add regular");
    const many = h("textarea", { rows: 4, placeholder: "One per line. Add a note after a comma:\nUCxxxxxxxxxxxxxxxxxxxxxx, Mod friend\nSomeName", "aria-label": "Several regulars, one per line" }) as HTMLTextAreaElement;
    const manyBtn = h("button", { class: "btn", type: "button" }, icon("userPlus", 16), "Add all");
    const manyBox = h("div", { class: "wb-more", hidden: true }, many, h("div", { class: "row" }, manyBtn, h("span", { class: "muted small" }, "People already on the list are skipped.")));
    const moreBtn = h("button", { class: "link-quiet", type: "button", "aria-expanded": "false", onclick: () => { manyBox.hidden = !manyBox.hidden; moreBtn.setAttribute("aria-expanded", String(!manyBox.hidden)); moreBtn.textContent = manyBox.hidden ? "Add several at once" : "Add one at a time"; singleRow.hidden = !manyBox.hidden; } }, "Add several at once");
    const singleRow = h("div", { class: "wb-single" }, rIdent, h("div", { class: "wb-row" }, h("div", { class: "grow" }, rLabel), rAdd));
    manyBtn.addEventListener("click", () => busy(manyBtn, async () => {
      const have = new Set(regulars.map((r) => r.ident.toLowerCase()));
      const rows = many.value.split("\n").map((l) => l.trim()).filter(Boolean).map((l) => { const i = l.indexOf(","); return i < 0 ? { ident: l, label: "" } : { ident: l.slice(0, i).trim(), label: l.slice(i + 1).trim() }; }).filter((r) => r.ident);
      const fresh = rows.filter((r, i) => !have.has(r.ident.toLowerCase()) && rows.findIndex((x) => x.ident.toLowerCase() === r.ident.toLowerCase()) === i);
      if (!rows.length) throw new Error("Type or paste at least one name.");
      for (const r of fresh) await post("/api/regulars", r);
      many.value = "";
      await loadReg();
      toast(fresh.length ? `Added ${plural(fresh.length, "regular")}${rows.length > fresh.length ? `, skipped ${rows.length - fresh.length}` : ""}` : "They are all on the list already");
    }));
    const regForm = h("form", { class: "wb-form", onsubmit: (e: Event) => {
      e.preventDefault();
      busy(rAdd, async () => { await post("/api/regulars", { ident: rIdent.value, label: rLabel.value }); rIdent.value = ""; rLabel.value = ""; await loadReg(); rIdent.focus(); }, "Regular added");
    } }, singleRow, manyBox, h("div", { class: "wb-foot" }, h("span", { class: "muted small" }, "Chatters also earn this on their own over time."), moreBtn));
    const regBench = h("section", { class: "wb", "aria-label": "Add a regular" }, h("h2", null, "Add a regular"), h("p", { class: "lede" }, "Regulars are trusted. They get softer moderation and can use regular-only commands."), regForm);

    const regList = h("div");
    const looksLikeId = (s: string) => /^UC[\w-]{20,}$/.test(s);
    const drawReg = () => {
      const list = regulars.filter((r) => !needle || `${r.ident} ${r.label}`.toLowerCase().includes(needle));
      if (!regulars.length) { mount(regList, invite("users", "No regulars yet", "Add the viewers you trust. They will be treated more gently by moderation.")); return; }
      if (!list.length) { mount(regList, invite("search", "No regulars match", "Try another name or note.")); return; }
      mount(regList, h("ul", { class: "r-list" }, list.map((r) => h("li", { class: "r-item" },
        avatar(r.label || r.ident, 40),
        h("div", { class: "r-main" }, h("strong", { class: looksLikeId(r.ident) ? "mono wrap" : "wrap" }, r.label || r.ident), r.label ? h("span", { class: `muted small${looksLikeId(r.ident) ? " mono" : ""} wrap` }, r.ident) : null),
        h("div", { class: "acts" }, h("span", { class: "chip ok" }, icon("star", 12), "Trusted"),
          confirmAct({ icon: "x", label: `Remove ${r.ident}`, onConfirm: async () => { try { await del(`/api/regulars/${r.id}`); await loadReg(); toast("Removed from regulars"); } catch (e) { toast((e as Error).message, "error"); } } }))))));
    };
    const loadReg = async () => { regulars = (await get<{ items: Regular[] }>("/api/regulars")).items; drawFigures(); drawReg(); tabs.refreshBadges(); };

    // ================================================================== layout
    const figs = h("div");
    const drawFigures = () => mount(figs, figures([{ value: String(quotes.length), label: quotes.length === 1 ? "quote saved" : "quotes saved" }, { value: String(regulars.length), label: regulars.length === 1 ? "trusted regular" : "trusted regulars" }]));
    drawFigures();
    const find = h("input", { type: "search", placeholder: "Search quotes and regulars", "aria-label": "Search quotes and regulars", autocomplete: "off" });
    find.addEventListener("input", () => { needle = find.value.trim().toLowerCase(); drawQuotes(); drawReg(); });

    const quotePane = h("div", { class: "stack" }, quoteBench, spotlight, h("section", { class: "nb-list", "aria-label": "Saved quotes" }, h("h3", { class: "coll-title" }, icon("quote", 14), "All quotes"), quoteList));
    const regPane = h("div", { class: "stack" }, regBench, h("section", { class: "nb-list", "aria-label": "Regulars" }, h("h3", { class: "coll-title" }, icon("star", 14), "Regulars"), regList));
    const tabs = paneTabs([{ id: "quotes", label: "Quotes" }, { id: "regulars", label: "Regulars" }], { quotes: quotePane, regulars: regPane }, query.get("pane") === "regulars" ? "regulars" : "quotes") as HTMLElement & { refreshBadges(): void };
    mount(root, pageHead("users", "Community", "The quotes your chat remembers and the viewers you trust."), areaNav("community"), figs,
      h("div", { class: "toolbar-solo" }, h("div", { class: "input-icon grow" }, icon("search", 16), find)), tabs, h("div", { class: "nb-cols even" }, quotePane, regPane));
    drawSpotlight(); drawQuotes(); drawReg();
    void loadQuotes().catch((e) => toast(e.message, "error"));
    void loadReg().catch((e) => toast(e.message, "error"));
    if (query.get("add") === "quote") queueMicrotask(() => qBody.focus());
  },
};
