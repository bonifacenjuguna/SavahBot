import { get, post } from "../api.js";
import { busy, h, mount, sheet, toast } from "../dom.js";
import { icon } from "../icons.js";
import { empty, pageHead } from "./shared.js";
import type { Page } from "./types.js";

interface Var { name: string; value: string; kind: "text" | "link" | "number"; note: string; uses: number }
interface Listing { variables: Var[]; builtin: { name: string; help: string }[] }

const KIND_HINT: Record<string, string> = { text: "Any words", link: "A web address, checked before saving", number: "A number such as 1500" };

function editor(existing: Var | null, taken: string[], done: () => void): void {
  const name = h("input", { type: "text", value: existing?.name ?? "", maxlength: 32, placeholder: "TikTok", autocapitalize: "off", spellcheck: false }) as HTMLInputElement;
  const value = h("input", { type: "text", value: existing?.value ?? "", maxlength: 500, placeholder: "https://tiktok.com/@you" }) as HTMLInputElement;
  const note = h("input", { type: "text", value: existing?.note ?? "", maxlength: 120, placeholder: "Optional reminder for yourself" }) as HTMLInputElement;
  const kind = h("select", null, ...(["text", "link", "number"] as const).map((k) => h("option", { value: k, selected: k === (existing?.kind ?? "text") }, k))) as HTMLSelectElement;
  const live = h("p", { class: "muted small wrap" });
  const hint = h("p", { class: "muted small" });
  const paint = () => {
    const n = name.value.trim().replace(/^\$\(|\)$/g, "");
    live.textContent = `In chat: "Find me on $(${n || "name"})" becomes "Find me on ${value.value || "…"}"`;
    hint.textContent = KIND_HINT[kind.value] + (!existing && taken.includes(n.toLowerCase()) ? ". That name is already used: saving will replace it." : "");
  };
  [name, value, kind].forEach((el) => el.addEventListener("input", paint));
  paint();
  const save = h("button", { class: "btn primary", type: "button" }, "Save variable");
  save.onclick = () => void busy(save, async () => {
    try { await post("/api/variables", { name: name.value, value: value.value, kind: kind.value, note: note.value }); toast("Variable saved"); box.close(); done(); }
    catch (e) { toast(e instanceof Error ? e.message : "Could not save"); }
  });
  const box = sheet(existing ? `Edit $(${existing.name})` : "New variable", h("div", { class: "stack" },
    h("label", { class: "field" }, "Name", name), h("label", { class: "field" }, "Type", kind), hint, h("label", { class: "field" }, "Value", value), h("label", { class: "field" }, "Note", note), live, save));
}

async function render(body: HTMLElement): Promise<void> {
  const data = await get<Listing>("/api/variables");
  const names = data.variables.map((v) => v.name.toLowerCase());
  const reload = () => void render(body).catch(() => mount(body, empty("alert", "Variables could not load.")));
  const remove = async (v: Var, force = false): Promise<void> => {
    try { await post("/api/variables/delete", { name: v.name, force }); toast("Deleted"); reload(); }
    catch (e) {
      const msg = e instanceof Error ? e.message : "Could not delete";
      if (!force && /still used/.test(msg)) { if (confirm(`${msg}`)) await remove(v, true); } else toast(msg);
    }
  };
  const rows = data.variables.map((v) => h("div", { class: "row between", style: "align-items:center;gap:12px;padding:10px 0;border-top:1px solid var(--line)" },
    h("div", { style: "min-width:0" }, h("strong", null, `$(${v.name})`), h("div", { class: "muted small wrap" }, v.value), h("div", { class: "muted small" }, `${v.kind}${v.uses ? ` · used in ${v.uses} place${v.uses === 1 ? "" : "s"}` : " · not used yet"}${v.note ? ` · ${v.note}` : ""}`)),
    h("div", { class: "row", style: "gap:6px" },
      h("button", { class: "btn ghost small", type: "button", onclick: () => editor(v, names, reload) }, "Edit"),
      h("button", { class: "btn ghost small", type: "button", "aria-label": `Delete ${v.name}`, onclick: () => void remove(v) }, icon("trash", 15)))));
  mount(body,
    h("div", { class: "sp-card" }, h("div", { class: "row between" }, h("h3", null, "Your variables"), h("button", { class: "btn small primary", type: "button", onclick: () => editor(null, names, reload) }, icon("plus", 15), "New")),
      h("p", { class: "muted small" }, "Type $(Name) in a command, timer, auto reply or a message you send as the bot, and it is replaced by the value. Change it here once and everything follows."),
      rows.length ? h("div", null, ...rows) : empty("sparkle", "No variables yet. Try one called TikTok with your link.")),
    h("div", { class: "sp-card" }, h("h3", null, "Built in, so not available as names"),
      h("p", { class: "muted small" }, "These already do something, so a variable cannot use their name."),
      h("div", { class: "stack" }, ...data.builtin.map((b) => h("div", { class: "muted small" }, h("code", null, `$(${b.name})`), ` ${b.help}`)))));
}

export const variables: Page = {
  id: "variables", title: "Variables", icon: "sparkle", blurb: "Your own $(names) for commands and messages",
  render(root) {
    const body = h("div", { class: "stack" }, h("p", { class: "muted" }, "Loading…"));
    mount(root, h("div", { class: "page" }, pageHead("sparkle", "Variables", "Short names for things you repeat, like links.", h("a", { class: "btn small", href: "/settings" }, "Back to Settings")), body));
    void render(body).catch(() => mount(body, empty("alert", "Variables could not load.")));
  },
};

/** A row of tap-to-insert chips for the user's own variables, shown under any text box that is rendered by the bot. Hidden when there are none. */
export function variableChips(input: HTMLInputElement | HTMLTextAreaElement): HTMLElement {
  const box = h("div", { class: "row wrap", style: "gap:6px;margin-top:6px" });
  void get<Listing>("/api/variables").then((d) => {
    if (!d.variables.length) return;
    mount(box, h("span", { class: "muted small" }, "Insert:"), ...d.variables.map((v) => h("button", { class: "btn ghost small", type: "button", onclick: () => {
      const at = input.selectionStart ?? input.value.length, tok = `$(${v.name})`;
      input.value = input.value.slice(0, at) + tok + input.value.slice(input.selectionEnd ?? at);
      input.focus(); input.setSelectionRange(at + tok.length, at + tok.length); input.dispatchEvent(new Event("input", { bubbles: true }));
    } }, `$(${v.name})`)));
  }).catch(() => undefined);
  return box;
}
