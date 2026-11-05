import { del, get, patch, post } from "../api.js";
import { busy, confirmDialog, h, mount, sheet, toast } from "../dom.js";
import { icon } from "../icons.js";

interface Rule { id: number; name: string; triggers: string[]; responses: string[]; match_type: string; case_sensitive: boolean; category: string; priority: number; enabled: boolean }

const MATCH: Record<string, string> = {
  phrase: "Whole message equals the trigger",
  word: "Trigger appears as a whole word or phrase",
  contains: "Trigger appears anywhere in the message",
};

/** Foundation for automatic replies. Rules are stored and testable; the bot does not send them yet, and this panel says so. */
export function autoRepliesPanel(): { el: HTMLElement; load: () => Promise<void> } {
  let items: Rule[] = [];
  const el = h("div");
  const listBox = h("div");

  const reload = async () => { items = (await get<{ items: Rule[] }>("/api/auto-replies")).items; draw(); };

  const draw = () => mount(listBox, items.length ? h("ul", { class: "list" }, items.map((r) =>
    h("li", { class: `timer-row${r.enabled ? "" : " off"}` },
      h("div", { class: "grow" },
        h("div", { class: "row", style: "gap:6px" }, h("strong", null, r.name), h("span", { class: "chip" }, r.match_type), h("span", { class: "chip" }, `priority ${r.priority}`), r.category !== "general" ? h("span", { class: "chip" }, r.category) : null, h("span", { class: "chip warn" }, r.enabled ? "Saved, not sending yet" : "Off")),
        h("div", { class: "row", style: "gap:6px;margin-top:4px" }, r.triggers.map((t) => h("span", { class: "chip mono" }, t))),
        h("div", { class: "appr-msg" }, r.responses[0] + (r.responses.length > 1 ? `  (+${r.responses.length - 1} more)` : ""))),
      h("div", { class: "timer-actions" },
        h("input", { type: "checkbox", class: "switch", checked: r.enabled, "aria-label": `Enable ${r.name}`, onchange: (e: Event) => { const v = (e.target as HTMLInputElement).checked; void patch(`/api/auto-replies/${r.id}`, { enabled: v }).then(reload).catch((x) => { (e.target as HTMLInputElement).checked = !v; toast(x.message, "error"); }); } }),
        h("button", { class: "icon-btn sm", type: "button", title: "Edit", "aria-label": `Edit ${r.name}`, onclick: () => editor(r) }, icon("pencil", 17)),
        h("button", { class: "icon-btn sm", type: "button", title: "Delete", "aria-label": `Delete ${r.name}`, onclick: async (e: Event) => { const b = e.currentTarget as HTMLButtonElement; if (await confirmDialog(`Delete "${r.name}"?`, "The rule is removed.", "Delete", "danger")) busy(b, async () => { await del(`/api/auto-replies/${r.id}`); await reload(); }); } }, icon("trash", 17))))))
    : h("div", { class: "empty" }, icon("message", 28), h("span", null, "No rules yet. A rule pairs words or phrases people type with the reply the bot should give."), h("button", { class: "btn primary small", type: "button", onclick: () => editor() }, icon("plus", 15), "New rule")));

  const editor = (r?: Rule) => {
    const name = h("input", { type: "text", value: r?.name ?? "", required: true, maxLength: 80, placeholder: "How to join" });
    const trig = h("textarea", { required: true, rows: 3, placeholder: "How do I join?\nhow to join" }, (r?.triggers ?? []).join("\n"));
    const resp = h("textarea", { required: true, rows: 3, placeholder: "You can join using the link in our description." }, (r?.responses ?? []).join("\n"));
    const type = h("select", null, Object.entries(MATCH).map(([k, v]) => h("option", { value: k, selected: (r?.match_type ?? "phrase") === k }, `${k}: ${v}`)));
    const cs = h("input", { type: "checkbox", checked: r?.case_sensitive ?? false });
    const prio = h("input", { type: "number", min: 1, max: 1000, value: String(r?.priority ?? 100) });
    const cat = h("input", { type: "text", value: r?.category ?? "general", maxLength: 40 });
    const save = h("button", { class: "btn primary", type: "submit" }, icon("check", 16), r ? "Save changes" : "Save rule");
    const holder: { close: () => void } = { close: () => undefined };
    const lines = (s: string) => s.split(/\r?\n/).map((x) => x.trim()).filter(Boolean);
    holder.close = sheet(r ? `Edit ${r.name}` : "New rule", h("form", { class: "stack tight", onsubmit: (e: Event) => {
      e.preventDefault();
      const body = { name: name.value, triggers: lines(trig.value), responses: lines(resp.value), match_type: type.value, case_sensitive: cs.checked, priority: Number(prio.value), category: cat.value || "general" };
      busy(save, async () => { r ? await patch(`/api/auto-replies/${r.id}`, body) : await post("/api/auto-replies", body); await reload(); holder.close(); }, "Saved");
    } },
      h("label", { class: "field" }, "Name", name), h("label", { class: "field" }, "Triggers (one per line)", trig), h("label", { class: "field" }, "Replies (one per line)", resp),
      h("label", { class: "field" }, "Matching", type),
      h("div", { class: "form-grid" }, h("label", { class: "field" }, "Priority (1 is checked first)", prio), h("label", { class: "field" }, "Category", cat)),
      h("label", { class: "check" }, cs, "Case sensitive"),
      h("div", { class: "row", style: "justify-content:flex-end" }, h("button", { class: "btn ghost", type: "button", onclick: () => holder.close() }, "Cancel"), save))).close;
  };

  const testIn = h("input", { type: "text", placeholder: "Type a chat message to see which rules would match", "aria-label": "Test message", maxLength: 500 });
  const testOut = h("div", { class: "small", "aria-live": "polite" });
  const testBtn = h("button", { class: "btn small ghost", type: "submit" }, icon("search", 15), "Test");
  const tester = h("form", { class: "body stack tight", onsubmit: (e: Event) => {
    e.preventDefault();
    busy(testBtn, async () => {
      const r = await post<{ matches: { name: string; trigger: string; enabled: boolean; reply: string }[] }>("/api/auto-replies/test", { text: testIn.value });
      mount(testOut, r.matches.length ? h("ul", { class: "reasons" }, r.matches.map((m) => h("li", null, `${m.name} would match "${m.trigger}"${m.enabled ? "" : " (rule is off)"}: ${m.reply}`))) : h("span", { class: "muted" }, "No rule matches that message."));
    });
  } }, h("div", { class: "row nowrap" }, h("div", { class: "grow" }, testIn), testBtn), testOut);

  mount(el,
    h("div", { class: "banner" }, icon("info", 18), h("span", { class: "grow" }, "Foundation only: rules are saved and can be tested here, but the bot does not answer chat automatically yet. Nothing below is sent to your viewers.")),
    h("div", { class: "toolbar" }, h("span", { class: "muted small" }, "Matching is already built and tested"), h("button", { class: "btn small primary", type: "button", style: "margin-left:auto", onclick: () => editor() }, icon("plus", 15), "New rule")),
    listBox, tester);
  return { el, load: reload };
}
