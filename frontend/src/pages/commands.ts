import { del, get, patch, post } from "../api.js";
import { busy, confirmDialog, debounce, duration, h, mount, sheet, toast } from "../dom.js";
import { icon } from "../icons.js";
import { autoRepliesPanel } from "./autoreplies.js";
import { card, empty, pageHead } from "./shared.js";
import { timersPanel } from "./timers.js";
import type { Page } from "./types.js";

interface Cmd { id: number; name: string; response: string; userlevel: string; cooldown: number; user_cooldown: number; enabled: boolean; aliases: string[] | string; uses?: number }
interface Builtin { name: string; category: string; syntax: string; description: string; userlevel: string }

const aliasList = (c: Cmd) => (Array.isArray(c.aliases) ? c.aliases : String(c.aliases || "").split(",").filter(Boolean));
const VARIABLES = ["$(user)", "$(touser)", "$(args)", "$(1)", "$(count)", "$(uptime)", "$(time)", "$(random 1 100)", "$(choose a|b)", "$(math 2+2)", "$(quote)", "$(urlfetch https://...)"];
// Starting points only. Each becomes an ordinary custom command once saved, so every one of them really works.
const TEMPLATES: { name: string; response: string; label: string }[] = [
  { label: "Help", name: "help", response: "Hi $(user)! Type !commands to see everything I can do." },
  { label: "Rules", name: "rules", response: "Be kind, no spam, no links without asking a mod. Thanks for keeping chat friendly!" },
  { label: "Socials", name: "socials", response: "Follow the channel and turn on notifications so you never miss a stream!" },
  { label: "Discord", name: "discord", response: "Join the community: paste your invite link here." },
];
type Tab = "commands" | "timers" | "replies";

export const commands: Page = {
  id: "commands",
  title: "Commands",
  icon: "terminal",
  blurb: "Chat commands, timers and automatic replies",
  render(root, query) {
    let tab: Tab = (["commands", "timers", "replies"].includes(query.get("tab") ?? "") ? query.get("tab") : "commands") as Tab;
    let levels = ["everyone", "member", "regular", "mod", "owner"];
    let catalog: Builtin[] = [];
    let items: Cmd[] = [];
    let needle = "";
    const picked = new Set<number>();
    const timers = timersPanel(), replies = autoRepliesPanel();
    const tabBox = h("div", { class: "scroll-x" }), panel = h("div"), head = h("div");

    // ----- editor
    const editor = (c?: Cmd, preset?: { name: string; response: string }) => {
      const name = h("input", { type: "text", value: c?.name ?? preset?.name ?? "", required: true, maxLength: 33, placeholder: "!hello" });
      const resp = h("textarea", { required: true, maxLength: 2000, placeholder: "Welcome $(user)! Stream has been live for $(uptime)." }, c?.response ?? preset?.response ?? "");
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
      const form = h("form", { class: "stack tight", onsubmit: (e: Event) => {
        e.preventDefault();
        const body = { name: name.value, response: resp.value, userlevel: lvl.value, cooldown: Number(cd.value), user_cooldown: Number(ucd.value), enabled: en.checked, aliases: al.value.split(",").map((s) => s.trim()).filter(Boolean) };
        busy(save, async () => { c ? await patch(`/api/commands/${c.id}`, body) : await post("/api/commands", body); await load(); holder.close(); }, "Saved");
      } },
        h("div", { class: "form-grid" }, h("label", { class: "field" }, "Name", name), h("label", { class: "field" }, "Who can use it", lvl),
          h("label", { class: "field" }, "Cooldown (seconds, everyone)", cd), h("label", { class: "field" }, "Cooldown (seconds, per person)", ucd),
          h("label", { class: "field wide" }, "Aliases (comma separated)", al), h("label", { class: "field wide" }, "Reply", resp)),
        h("div", null, h("div", { class: "muted small", style: "margin-bottom:6px" }, "Tap a variable to insert it"),
          h("div", { class: "row", style: "gap:6px" }, VARIABLES.map((v) => h("button", { class: "chip", type: "button", style: "cursor:pointer", onclick: () => insert(v) }, v)))),
        prev,
        h("div", { class: "row between" }, h("label", { class: "check" }, en, "Enabled"), h("span", { class: "row" },
          c ? h("button", { class: "btn danger", type: "button", onclick: async () => { if (await confirmDialog(`Delete !${c.name}?`, "Viewers can no longer use it.", "Delete", "danger")) { await del(`/api/commands/${c.id}`); await load(); holder.close(); } } }, icon("trash", 15), "Delete") : null,
          h("button", { class: "btn ghost", type: "button", onclick: () => holder.close() }, "Cancel"), save)));
      holder.close = sheet(c ? `Edit !${c.name}` : "New command", form).close;
      if (c || preset) void doPreview();
    };

    // ----- commands tab
    const bulk = async (action: string) => {
      const ids = Array.from(picked);
      if (action === "delete" && !(await confirmDialog(`Delete ${ids.length} command${ids.length === 1 ? "" : "s"}?`, "Viewers can no longer use them.", "Delete", "danger"))) return;
      try { await post("/api/commands/bulk", { ids, action }); picked.clear(); await load(); toast("Done"); } catch (e) { toast((e as Error).message, "error"); }
    };
    const commandsView = () => {
      const bar = h("div", { class: "bulkbar", hidden: true }), rowsBox = h("div");
      const drawBar = () => {
        bar.hidden = picked.size === 0;
        if (picked.size) mount(bar, h("strong", null, `${picked.size} selected`),
          h("button", { class: "btn small ghost", type: "button", onclick: () => void bulk("enable") }, "Enable"), h("button", { class: "btn small ghost", type: "button", onclick: () => void bulk("disable") }, "Disable"),
          h("button", { class: "btn small danger", type: "button", onclick: () => void bulk("delete") }, icon("trash", 14), "Delete"), h("button", { class: "btn small ghost", type: "button", onclick: () => { picked.clear(); drawRows(); } }, "Clear"));
      };
      const drawRows = () => {
        const r = items.filter((c) => !needle || `${c.name} ${c.response} ${aliasList(c).join(" ")}`.toLowerCase().includes(needle));
        mount(rowsBox, r.length ? h("ul", { class: "list" }, r.map((c) => h("li", { class: `timer-row${c.enabled ? "" : " off"}` },
          h("input", { type: "checkbox", checked: picked.has(c.id), "aria-label": `Select !${c.name}`, onchange: (e: Event) => { (e.target as HTMLInputElement).checked ? picked.add(c.id) : picked.delete(c.id); drawBar(); } }),
          h("div", { class: "grow" },
            h("div", { class: "row", style: "gap:6px" }, h("span", { class: "mono" }, "!" + c.name), aliasList(c).map((a) => h("span", { class: "chip mono" }, "!" + a)), h("span", { class: "chip" }, c.userlevel), c.uses ? h("span", { class: "chip" }, `used ${c.uses}×`) : null),
            h("div", { class: "appr-msg" }, c.response),
            h("div", { class: "muted small" }, `Cooldown ${duration(c.cooldown)} everyone, ${duration(c.user_cooldown)} per person`)),
          h("div", { class: "timer-actions" },
            h("input", { type: "checkbox", class: "switch", checked: c.enabled, "aria-label": `Enable !${c.name}`, onchange: (e: Event) => { const v = (e.target as HTMLInputElement).checked; void patch(`/api/commands/${c.id}`, { enabled: v }).then(() => { c.enabled = v; drawRows(); }).catch((x) => { (e.target as HTMLInputElement).checked = !v; toast(x.message, "error"); }); } }),
            h("button", { class: "icon-btn sm", type: "button", title: "Edit", "aria-label": `Edit !${c.name}`, onclick: () => editor(c) }, icon("pencil", 17))))))
          : items.length ? empty("search", "No commands match.")
            : h("div", { class: "empty" }, icon("terminal", 28), h("span", null, "No custom commands yet. Start from a template below, or add your own.")));
        drawBar();
      };
      const search = h("input", { type: "search", placeholder: "Search commands", "aria-label": "Search commands", value: needle });
      search.addEventListener("input", () => { needle = search.value.trim().toLowerCase(); drawRows(); });
      drawRows();
      const groups = Array.from(new Set(catalog.map((b) => b.category)));
      return h("div", { class: "stack" },
        card("terminal", "Your commands", h("div", null,
          h("div", { class: "toolbar" }, h("div", { class: "input-icon" }, icon("search", 16), search), h("span", { class: "chip" }, `${items.length} custom`)),
          h("div", { class: "body tight-y" }, h("div", { class: "muted small", style: "margin-bottom:6px" }, "Start from a template"), h("div", { class: "row", style: "gap:6px" }, TEMPLATES.filter((t) => !items.some((c) => c.name === t.name)).map((t) => h("button", { class: "chip", type: "button", style: "cursor:pointer", onclick: () => editor(undefined, t) }, icon("plus", 12), t.label)))),
          bar, rowsBox), { flush: true }),
        card("bot", "Built in", h("div", null, groups.map((g) => h("div", { class: "builtin-group" },
          h("div", { class: "muted small group-title" }, g),
          h("ul", { class: "list" }, catalog.filter((b) => b.category === g).map((b) =>
            h("li", { class: "builtin-row" }, h("span", { class: "mono" }, b.syntax), h("span", { class: "muted small grow" }, b.description), h("span", { class: "chip" }, b.userlevel === "mod" ? "mods" : "everyone"))))))),
          { flush: true, actions: h("span", { class: "muted small" }, "Part of the bot, cannot be edited") }));
    };

    // ----- tabs
    const tabs: { id: Tab; label: string; icon: string }[] = [{ id: "commands", label: "Commands", icon: "terminal" }, { id: "timers", label: "Timers", icon: "timer" }, { id: "replies", label: "Auto-replies", icon: "message" }];
    const drawTabs = () => mount(tabBox, h("div", { class: "seg-control tabs", role: "tablist" }, tabs.map((t) => h("button", { type: "button", role: "tab", "aria-selected": String(tab === t.id), onclick: () => select(t.id) }, icon(t.icon, 15), t.label))));
    const drawHead = () => mount(head, pageHead("terminal", "Commands and automation", "Commands answer viewers. Timers post by themselves while a stream is live. Auto-replies are being prepared.",
      tab === "commands" ? h("button", { class: "btn primary", type: "button", onclick: () => editor() }, icon("plus", 16), "New command") : null));
    const drawPanel = () => {
      if (tab === "commands") mount(panel, commandsView());
      else if (tab === "timers") { mount(panel, card("timer", "Timers", timers.el, { flush: true })); void timers.load().catch((e) => toast(e.message, "error")); }
      else { mount(panel, card("message", "Automatic replies", replies.el, { flush: true })); void replies.load().catch((e) => toast(e.message, "error")); }
    };
    const select = (id: Tab) => { tab = id; history.replaceState(null, "", `#/commands?tab=${id}`); drawTabs(); drawHead(); drawPanel(); };
    const load = async () => {
      const r = await get<{ items: Cmd[]; levels: string[]; catalog: Builtin[] }>("/api/commands");
      levels = r.levels; items = r.items; catalog = r.catalog ?? [];
      for (const id of Array.from(picked)) if (!items.some((c) => c.id === id)) picked.delete(id);
      if (tab === "commands") drawPanel();
    };

    mount(root, head, h("div", { style: "margin-bottom:14px" }, tabBox), panel);
    drawHead(); drawTabs(); drawPanel();
    void load().catch((e) => toast(e.message, "error"));
    const poll = window.setInterval(() => { if (tab === "timers") void timers.load().catch(() => undefined); }, 15000);   // keeps "next post" and line counts fresh
    return () => window.clearInterval(poll);
  },
};
