import { del, get, patch, post } from "../api.js";
import { busy, debounce, duration, h, mount, sheet, toast } from "../dom.js";
import { icon } from "../icons.js";
import { card, empty, pageHead } from "./shared.js";
import type { Page } from "./types.js";

interface Cmd { id: number; name: string; response: string; userlevel: string; cooldown: number; user_cooldown: number; enabled: boolean; aliases: string[] | string }
interface Timer { id: number; name: string; message: string; interval_seconds: number; min_lines: number; enabled: boolean }

const aliasList = (c: Cmd) => (Array.isArray(c.aliases) ? c.aliases : String(c.aliases || "").split(",").filter(Boolean));
const VARIABLES = ["$(user)", "$(touser)", "$(args)", "$(1)", "$(count)", "$(uptime)", "$(time)", "$(random 1 100)", "$(choose a|b)", "$(math 2+2)", "$(quote)", "$(urlfetch https://...)"];

export const commands: Page = {
  id: "commands",
  title: "Commands",
  icon: "terminal",
  blurb: "Chat commands and timed messages",
  render(root) {
    const listBox = h("div"), timerBox = h("div");
    let levels: string[] = ["everyone", "member", "regular", "mod", "owner"];
    let builtin: string[] = [];
    let items: Cmd[] = [];
    let needle = "";

    // ----- command editor (bottom sheet on phones, dialog on larger screens)
    const editor = (c?: Cmd) => {
      const name = h("input", { type: "text", value: c?.name ?? "", required: true, maxLength: 33, placeholder: "!hello" });
      const resp = h("textarea", { required: true, maxLength: 2000, placeholder: "Welcome $(user)! Stream has been live for $(uptime)." }, c?.response ?? "");
      const lvl = h("select", null, levels.map((l) => h("option", { value: l, selected: (c?.userlevel ?? "everyone") === l }, l)));
      const cd = h("input", { type: "number", min: 0, value: String(c?.cooldown ?? 5) });
      const ucd = h("input", { type: "number", min: 0, value: String(c?.user_cooldown ?? 10) });
      const al = h("input", { type: "text", value: c ? aliasList(c).join(", ") : "", placeholder: "hi, hey" });
      const en = h("input", { type: "checkbox", class: "switch", checked: c?.enabled ?? true, "aria-label": "Enabled" });
      const prev = h("div", { class: "reasons", "aria-live": "polite" });
      const doPreview = debounce(async () => {
        if (!resp.value.trim()) return mount(prev, "");
        try { mount(prev, icon("message", 14), " Preview: ", (await post<{ output: string }>("/api/commands/preview", { template: resp.value, user: "Viewer", level: "everyone", args: "a b" })).output); }
        catch (e) { mount(prev, (e as Error).message); }
      }, 350);
      resp.addEventListener("input", doPreview);
      const insert = (v: string) => {
        const s = resp.selectionStart ?? resp.value.length, e = resp.selectionEnd ?? s;
        resp.value = resp.value.slice(0, s) + v + resp.value.slice(e);
        resp.focus();
        resp.setSelectionRange(s + v.length, s + v.length);
        doPreview();
      };
      const save = h("button", { class: "btn primary", type: "submit" }, icon("check", 16), c ? "Save changes" : "Add command");
      const holder: { close: () => void } = { close: () => undefined };
      const form = h("form", { class: "stack", onsubmit: (e: Event) => {
        e.preventDefault();
        const body = { name: name.value, response: resp.value, userlevel: lvl.value, cooldown: Number(cd.value), user_cooldown: Number(ucd.value), enabled: en.checked,
          aliases: al.value.split(",").map((s) => s.trim()).filter(Boolean) };
        busy(save, async () => { c ? await patch(`/api/commands/${c.id}`, body) : await post("/api/commands", body); await load(); holder.close(); }, "Saved");
      } },
        h("div", { class: "form-grid" }, h("label", { class: "field" }, "Name", name), h("label", { class: "field" }, "Who can use it", lvl),
          h("label", { class: "field" }, "Cooldown (seconds, everyone)", cd), h("label", { class: "field" }, "Cooldown (seconds, per person)", ucd),
          h("label", { class: "field wide" }, "Aliases (comma separated)", al), h("label", { class: "field wide" }, "Reply", resp)),
        h("div", null, h("div", { class: "muted small", style: "margin-bottom:6px" }, "Tap a variable to insert it"),
          h("div", { class: "row", style: "gap:6px" }, VARIABLES.map((v) => h("button", { class: "chip", type: "button", style: "cursor:pointer", onclick: () => insert(v) }, v)))),
        prev,
        h("div", { class: "row between" }, h("label", { class: "check" }, en, "Enabled"), h("span", { class: "row" }, h("button", { class: "btn ghost", type: "button", onclick: () => holder.close() }, "Cancel"), save)));
      holder.close = sheet(c ? `Edit !${c.name}` : "New command", form).close;
      if (c) void doPreview();
    };

    // ----- command list
    const drawList = () => {
      const search = h("input", { type: "search", placeholder: "Search commands", "aria-label": "Search commands", value: needle });
      search.addEventListener("input", () => { needle = search.value.trim().toLowerCase(); drawRows(); });
      const rowsBox = h("div");
      const drawRows = () => {
        const r = items.filter((c) => !needle || `${c.name} ${c.response} ${aliasList(c).join(" ")}`.toLowerCase().includes(needle));
        mount(rowsBox, r.length ? h("div", { class: "table-wrap" }, h("table", { class: "cards" }, h("thead", null, h("tr", null, ["On", "Command", "Reply", "Who", ""].map((c) => h("th", null, c)))),
          h("tbody", null, r.map((c) => h("tr", null,
            h("td", { "data-label": "On" }, h("input", { type: "checkbox", class: "switch", checked: c.enabled, "aria-label": `Enable !${c.name}`, onchange: (e: Event) => void patch(`/api/commands/${c.id}`, { enabled: (e.target as HTMLInputElement).checked }).then(() => { c.enabled = !c.enabled; }).catch((x) => toast(x.message, "error")) })),
            h("td", { "data-label": "Command" }, h("div", null, h("span", { class: "mono" }, "!" + c.name), aliasList(c).length ? h("div", { class: "muted small" }, aliasList(c).map((a) => "!" + a).join(" ")) : null)),
            h("td", { style: "max-width:380px;overflow-wrap:anywhere", "data-label": "Reply" }, c.response),
            h("td", { "data-label": "Who" }, h("div", null, h("span", { class: "chip" }, c.userlevel), h("div", { class: "muted small" }, `${duration(c.cooldown)} / ${duration(c.user_cooldown)}`))),
            h("td", { "data-label": "" }, h("div", { class: "row", style: "gap:6px" }, h("button", { class: "btn small ghost", "aria-label": `Edit !${c.name}`, onclick: () => editor(c) }, icon("pencil", 15), "Edit"),
              h("button", { class: "btn small danger", "aria-label": `Delete !${c.name}`, onclick: (e: Event) => busy(e.currentTarget as HTMLButtonElement, async () => { await del(`/api/commands/${c.id}`); await load(); }) }, icon("trash", 15), "Delete"))))))))
          : empty("terminal", items.length ? "No commands match." : "No commands yet. Add your first one."));
      };
      drawRows();
      mount(listBox,
        h("div", { class: "toolbar" }, h("div", { class: "input-icon" }, icon("search", 16), search), h("span", { class: "chip" }, `${items.length} custom`)),
        rowsBox,
        builtin.length ? h("div", { class: "body" }, h("div", { class: "muted small", style: "margin-bottom:6px" }, "Built in"), h("div", { class: "row", style: "gap:6px" }, builtin.map((b) => h("span", { class: "chip mono" }, "!" + b)))) : null);
    };
    const load = async () => {
      const r = await get<{ items: Cmd[]; builtin: string[]; levels: string[] }>("/api/commands");
      levels = r.levels; builtin = r.builtin; items = r.items;
      drawList();
    };

    // ----- timers
    const loadTimers = async () => {
      const r = await get<{ items: Timer[] }>("/api/timers");
      const name = h("input", { type: "text", required: true, placeholder: "social" });
      const msg = h("input", { type: "text", required: true, maxLength: 500, placeholder: "Follow the channel!" });
      const iv = h("input", { type: "number", min: 1, value: "15", title: "Minutes" });
      const ml = h("input", { type: "number", min: 0, value: "5", title: "Chat lines since the last post" });
      const add = h("button", { class: "btn primary", type: "submit" }, icon("plus", 16), "Add timer");
      mount(timerBox, h("form", { class: "body stack", onsubmit: (e: Event) => { e.preventDefault(); busy(add, async () => { await post("/api/timers", { name: name.value, message: msg.value, interval_seconds: Number(iv.value) * 60, min_lines: Number(ml.value) }); await loadTimers(); }, "Timer added (off until you enable it)"); } },
        h("div", { class: "form-grid" }, h("label", { class: "field" }, "Name", name), h("label", { class: "field" }, "Every (minutes)", iv), h("label", { class: "field" }, "After this many chat lines", ml), h("label", { class: "field wide" }, "Message", msg)), add),
        r.items.length ? h("ul", { class: "list" }, r.items.map((t) => h("li", { class: "row between nowrap" },
          h("span", { class: "grow" }, h("strong", null, t.name), " ", h("span", { class: "muted small" }, `every ${duration(t.interval_seconds)}, after ${t.min_lines} lines`), h("div", { class: "small" }, t.message)),
          h("span", { class: "row nowrap" }, h("input", { type: "checkbox", class: "switch", checked: t.enabled, "aria-label": `Enable timer ${t.name}`, onchange: (e: Event) => void patch(`/api/timers/${t.id}`, { enabled: (e.target as HTMLInputElement).checked }).catch((x) => toast(x.message, "error")) }),
            h("button", { class: "btn small danger", "aria-label": `Delete timer ${t.name}`, onclick: (e: Event) => busy(e.currentTarget as HTMLButtonElement, async () => { await del(`/api/timers/${t.id}`); await loadTimers(); }) }, icon("trash", 15), "Delete")))))
          : empty("timer", "No timers yet."));
    };

    mount(root,
      pageHead("terminal", "Commands and timers", "Commands answer viewers. Timers post on their own, only while the stream is live and chat is active.",
        h("button", { class: "btn primary", type: "button", onclick: () => editor() }, icon("plus", 16), "New command")),
      h("div", { class: "cols" },
        card("terminal", "Commands", listBox, { flush: true }),
        card("timer", "Timers", timerBox, { flush: true })));
    void load().catch((e) => toast(e.message, "error"));
    void loadTimers().catch((e) => toast(e.message, "error"));
  },
};
