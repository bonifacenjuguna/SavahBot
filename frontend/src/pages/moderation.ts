import { del, get, patch, post } from "../api.js";
import { busy, dateTime, h, mount, toast } from "../dom.js";
import * as feed from "../events.js";
import { status, refreshStatus } from "../state.js";
import { icon } from "../icons.js";
import { actionLabel, approvalList, statusChip, type Action } from "./shared.js";
import type { Page } from "./types.js";

interface Phrase { id: number; phrase: string; is_regex: boolean; weight: number; enabled: boolean }

export const moderation: Page = {
  id: "moderation",
  title: "Moderation",
  render(root) {
    const modeSel = h("select", { "aria-label": "Moderation mode" },
      [["off", "Off: only log"], ["suggest", "Suggest: ask me first"], ["auto", "Auto: act, then tell me"]].map(([v, l]) => h("option", { value: v, selected: status?.hub.mod_mode === v }, l)));
    modeSel.onchange = () => busy(modeSel as unknown as HTMLButtonElement, async () => { await patch("/api/settings", { values: { mod_mode: modeSel.value } }); await refreshStatus(); }, "Moderation mode saved");

    const pending = h("div"), history = h("div"), phrases = h("div"), tester = h("div");
    const loadPending = async () => mount(pending, approvalList((await get<{ items: Action[] }>("/api/moderation/pending")).items, async () => { await loadPending(); await loadHistory(); }));
    const loadHistory = async () => {
      const r = await get<{ items: Action[] }>("/api/moderation/history?limit=60");
      mount(history, r.items.length
        ? h("div", { class: "table-wrap" }, h("table", { class: "cards" }, h("thead", null, h("tr", null, ["When", "Who", "Action", "Outcome", "Why"].map((c) => h("th", null, c)))),
          h("tbody", null, r.items.map((a) => h("tr", null, h("td", { "data-label": "When" }, dateTime(a.ts)), h("td", { "data-label": "Who" }, a.author_name, a.demo ? h("span", { class: "chip" }, "demo") : null),
            h("td", { "data-label": "Action" }, actionLabel(a)), h("td", { "data-label": "Outcome" }, statusChip(a.status), a.error ? h("div", { class: "reasons" }, a.error) : null),
            h("td", { class: "small muted", "data-label": "Why" }, a.reasons.join(", ")))))))
        : h("div", { class: "empty" }, "No moderation actions yet."));
    };

    const loadPhrases = async () => {
      const r = await get<{ items: Phrase[] }>("/api/blacklist");
      const phrase = h("input", { type: "text", placeholder: "Word, phrase or regex", required: true, maxLength: 200 });
      const regex = h("input", { type: "checkbox" });
      const weight = h("input", { type: "number", min: 0, max: 100, value: "0", title: "Score added when matched. 0 uses the default." });
      const add = h("button", { class: "btn primary", type: "submit" }, icon("plus", 14), "Add");
      mount(phrases,
        h("form", { class: "body row", onsubmit: (e: Event) => { e.preventDefault(); busy(add, async () => { await post("/api/blacklist", { phrase: phrase.value, is_regex: regex.checked, weight: Number(weight.value) }); await loadPhrases(); }); } },
          h("div", { class: "grow" }, phrase), h("label", { class: "check" }, regex, "Regex"), h("div", { style: "width:90px" }, weight), add),
        r.items.length ? h("ul", { class: "list" }, r.items.map((p) => h("li", { class: "row between" },
          h("span", null, h("span", { class: p.enabled ? "mono" : "mono muted" }, p.phrase), " ", p.is_regex ? h("span", { class: "chip" }, "regex") : null, p.weight ? h("span", { class: "chip" }, `+${p.weight}`) : null),
          h("span", { class: "row" },
            h("label", { class: "check small" }, h("input", { type: "checkbox", checked: p.enabled, onchange: (e: Event) => void patch(`/api/blacklist/${p.id}`, { enabled: (e.target as HTMLInputElement).checked }).catch((x) => toast(x.message, "error")) }), "On"),
            h("button", { class: "btn small danger", onclick: (e: Event) => busy(e.currentTarget as HTMLButtonElement, async () => { await del(`/api/blacklist/${p.id}`); await loadPhrases(); }) }, icon("trash", 14), "Remove")))))
          : h("div", { class: "empty" }, "No blocked phrases."));
    };

    const text = h("textarea", { placeholder: "Paste a chat message to see how it would score", maxLength: 1000 });
    const level = h("select", null, ["everyone", "member", "regular", "mod"].map((l) => h("option", { value: l }, l)));
    const result = h("div", { class: "small" });
    const test = h("button", { class: "btn primary", type: "submit" }, "Score it");
    mount(tester, h("form", { class: "body stack", onsubmit: (e: Event) => {
      e.preventDefault();
      busy(test, async () => {
        const r = await post<{ verdict: any; note: string }>("/api/moderation/test", { text: text.value, level: level.value });
        const v = r.verdict;
        mount(result, h("p", null, h("strong", null, `Score ${v.score}: ${v.action}`), v.duration ? ` (${v.duration}s)` : "", v.exempt ? " (exempt)" : ""),
          v.signals.length ? h("ul", null, v.signals.map((s: any) => h("li", null, `${s.name} +${s.weight}`, s.detail ? ` (${s.detail})` : ""))) : h("p", { class: "muted" }, "No signals fired."),
          h("p", { class: "muted" }, r.note));
      });
    } }, text, h("div", { class: "row" }, h("label", { class: "field" }, "Chatter level", level), test), result));

    mount(root,
      h("div", { class: "page-head" }, h("h1", null, "Moderation"), h("label", { class: "field" }, "Mode", modeSel)),
      h("div", { class: "cols" },
        h("div", { class: "stack" },
          h("section", { class: "block flush" }, h("header", null, h("h2", null, "Waiting for you")), pending),
          h("section", { class: "block flush" }, h("header", null, h("h2", null, "History")), history)),
        h("div", { class: "stack" },
          h("section", { class: "block flush" }, h("header", null, h("h2", null, "Blocked phrases"), h("span", { class: "muted small" }, "Matches survive spacing, symbols and look-alike letters")), phrases),
          h("section", { class: "block flush" }, h("header", null, h("h2", null, "Try a message")), tester))),
    );
    const all = () => Promise.all([loadPending(), loadHistory()]).catch((e) => toast(e.message, "error"));
    void all();
    void loadPhrases().catch((e) => toast(e.message, "error"));
    const offs = [feed.on("mod_pending", all), feed.on("mod_resolved", all)];
    return () => offs.forEach((f) => f());
  },
};
