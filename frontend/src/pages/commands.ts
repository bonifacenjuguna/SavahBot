import { del, get, patch, post } from "../api.js";
import { busy, debounce, duration, h, mount, toast } from "../dom.js";
import type { Page } from "./types.js";

interface Cmd { id: number; name: string; response: string; userlevel: string; cooldown: number; user_cooldown: number; enabled: boolean; aliases: string[] | string }
interface Timer { id: number; name: string; message: string; interval_seconds: number; min_lines: number; enabled: boolean }

const aliasList = (c: Cmd) => (Array.isArray(c.aliases) ? c.aliases : String(c.aliases || "").split(",").filter(Boolean));

export const commands: Page = {
  id: "commands",
  title: "Commands",
  render(root) {
    const listBox = h("div"), timerBox = h("div"), formBox = h("div");
    let levels: string[] = ["everyone", "member", "regular", "mod", "owner"];
    let builtin: string[] = [];

    const editor = (c?: Cmd) => {
      const name = h("input", { type: "text", value: c?.name ?? "", required: true, maxLength: 33, placeholder: "!hello" });
      const resp = h("textarea", { required: true, maxLength: 2000, placeholder: "Welcome $(user)! Stream has been live for $(uptime)." }, c?.response ?? "");
      const lvl = h("select", null, levels.map((l) => h("option", { value: l, selected: (c?.userlevel ?? "everyone") === l }, l)));
      const cd = h("input", { type: "number", min: 0, value: String(c?.cooldown ?? 5) });
      const ucd = h("input", { type: "number", min: 0, value: String(c?.user_cooldown ?? 10) });
      const al = h("input", { type: "text", value: c ? aliasList(c).join(", ") : "", placeholder: "hi, hey" });
      const en = h("input", { type: "checkbox", checked: c?.enabled ?? true });
      const prev = h("div", { class: "reasons", "aria-live": "polite" });
      const doPreview = debounce(async () => {
        if (!resp.value.trim()) return mount(prev, "");
        try { mount(prev, "Preview: ", (await post<{ output: string }>("/api/commands/preview", { template: resp.value, user: "Viewer", level: "everyone", args: "a b" })).output); }
        catch (e) { mount(prev, (e as Error).message); }
      }, 350);
      resp.addEventListener("input", doPreview);
      const save = h("button", { class: "btn primary", type: "submit" }, c ? "Save changes" : "Add command");
      mount(formBox, h("form", { class: "body stack", onsubmit: (e: Event) => {
        e.preventDefault();
        const body = { name: name.value, response: resp.value, userlevel: lvl.value, cooldown: Number(cd.value), user_cooldown: Number(ucd.value), enabled: en.checked,
          aliases: al.value.split(",").map((s) => s.trim()).filter(Boolean) };
        busy(save, async () => { c ? await patch(`/api/commands/${c.id}`, body) : await post("/api/commands", body); await load(); editor(); }, "Saved");
      } },
        h("div", { class: "form-grid" }, h("label", { class: "field" }, "Name", name), h("label", { class: "field" }, "Who can use it", lvl),
          h("label", { class: "field" }, "Cooldown (seconds, everyone)", cd), h("label", { class: "field" }, "Cooldown (seconds, per person)", ucd),
          h("label", { class: "field wide" }, "Aliases (comma separated)", al), h("label", { class: "field wide" }, "Reply", resp)),
        prev, h("p", { class: "muted small" }, "Variables: $(user) $(touser) $(args) $(1) $(count) $(uptime) $(time) $(random 1 100) $(choose a|b) $(math 2+2) $(quote) $(urlfetch https://...)"),
        h("div", { class: "row" }, h("label", { class: "check" }, en, "Enabled"), save, c ? h("button", { class: "btn ghost", type: "button", onclick: () => editor() }, "Cancel") : null)));
      if (c) void doPreview();
    };

    const load = async () => {
      const r = await get<{ items: Cmd[]; builtin: string[]; levels: string[] }>("/api/commands");
      levels = r.levels; builtin = r.builtin;
      mount(listBox, h("div", { class: "table-wrap" }, h("table", null, h("thead", null, h("tr", null, ["Command", "Reply", "Who", ""].map((c) => h("th", null, c)))),
        h("tbody", null, r.items.map((c) => h("tr", null,
          h("td", null, h("span", { class: c.enabled ? "mono" : "mono muted" }, "!" + c.name), aliasList(c).length ? h("div", { class: "muted small" }, aliasList(c).map((a) => "!" + a).join(" ")) : null),
          h("td", { style: "max-width:380px;overflow-wrap:anywhere" }, c.response),
          h("td", null, h("span", { class: "chip" }, c.userlevel), h("div", { class: "muted small" }, `${duration(c.cooldown)} / ${duration(c.user_cooldown)}`)),
          h("td", { class: "row" }, h("button", { class: "btn small ghost", onclick: () => { editor(c); formBox.scrollIntoView({ behavior: "smooth", block: "nearest" }); } }, "Edit"),
            h("button", { class: "btn small danger", onclick: (e: Event) => busy(e.currentTarget as HTMLButtonElement, async () => { await del(`/api/commands/${c.id}`); await load(); }) }, "Delete"))))))),
        h("div", { class: "body muted small" }, "Built in: ", builtin.map((b) => "!" + b).join(" ")));
    };

    const loadTimers = async () => {
      const r = await get<{ items: Timer[] }>("/api/timers");
      const name = h("input", { type: "text", required: true, placeholder: "social" });
      const msg = h("input", { type: "text", required: true, maxLength: 500, placeholder: "Follow the channel!" });
      const iv = h("input", { type: "number", min: 1, value: "15", title: "Minutes" });
      const ml = h("input", { type: "number", min: 0, value: "5", title: "Chat lines since the last post" });
      const add = h("button", { class: "btn primary", type: "submit" }, "Add timer");
      mount(timerBox, h("form", { class: "body stack", onsubmit: (e: Event) => { e.preventDefault(); busy(add, async () => { await post("/api/timers", { name: name.value, message: msg.value, interval_seconds: Number(iv.value) * 60, min_lines: Number(ml.value) }); await loadTimers(); }, "Timer added (off until you enable it)"); } },
        h("div", { class: "form-grid" }, h("label", { class: "field" }, "Name", name), h("label", { class: "field" }, "Every (minutes)", iv), h("label", { class: "field" }, "After this many chat lines", ml), h("label", { class: "field wide" }, "Message", msg)), add),
        r.items.length ? h("ul", { class: "list" }, r.items.map((t) => h("li", { class: "row between" },
          h("span", null, h("strong", null, t.name), " ", h("span", { class: "muted small" }, `every ${duration(t.interval_seconds)}, after ${t.min_lines} lines`), h("div", { class: "small" }, t.message)),
          h("span", { class: "row" }, h("label", { class: "check small" }, h("input", { type: "checkbox", checked: t.enabled, onchange: (e: Event) => void patch(`/api/timers/${t.id}`, { enabled: (e.target as HTMLInputElement).checked }).catch((x) => toast(x.message, "error")) }), "On"),
            h("button", { class: "btn small danger", onclick: (e: Event) => busy(e.currentTarget as HTMLButtonElement, async () => { await del(`/api/timers/${t.id}`); await loadTimers(); }) }, "Delete")))))
          : h("div", { class: "empty" }, "No timers yet."));
    };

    mount(root, h("div", { class: "page-head" }, h("h1", null, "Commands and timers"), h("p", null, "Commands answer viewers. Timers post on their own, only while the stream is live and chat is active.")),
      h("div", { class: "cols" },
        h("div", { class: "stack" }, h("section", { class: "block flush" }, h("header", null, h("h2", null, "Commands")), listBox),
          h("section", { class: "block flush" }, h("header", null, h("h2", null, "Timers")), timerBox)),
        h("section", { class: "block flush" }, h("header", null, h("h2", null, "Add or edit a command")), formBox)));
    editor();
    void load().catch((e) => toast(e.message, "error"));
    void loadTimers().catch((e) => toast(e.message, "error"));
  },
};
