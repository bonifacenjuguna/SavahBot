import { del, get, patch } from "../api.js";
import { h, mount, toast } from "../dom.js";
import { icon } from "../icons.js";
import { refreshStatus } from "../state.js";
import { areaNav } from "./kit.js";
import { empty, pageHead } from "./shared.js";
import { renderKnowledge } from "./knowledge/index.js";
import { settingsTabs } from "./knowledge/common.js";
import type { Page } from "./types.js";

interface Setting {
  name: string; env: string; group: string; description: string; type: string; default: unknown; value: unknown;
  is_set: boolean; secret: boolean; source: string; editable: boolean; options: string[] | null; reserved: boolean;
}

export const settings: Page = {
  id: "settings",
  title: "Settings",
  icon: "sliders",
  blurb: "Every option, and the bot's Knowledge",
  render(root, query) {
    if (query.get("tab") === "knowledge") { renderKnowledge(root, query); return; }
    const box = h("div", { class: "block flush" });
    const search = h("input", { type: "search", placeholder: "Search settings", "aria-label": "Search settings" });
    const changedOnly = h("input", { type: "checkbox", class: "switch", "aria-label": "Only settings changed from the default" });
    const summary = h("span", { class: "muted small" }, "");
    let items: Setting[] = [];
    const openGroups = new Set<string>();

    const control = (s: Setting): HTMLElement => {
      const save = async (value: string | number | boolean) => {
        try { await patch("/api/settings", { values: { [s.name]: value } }); toast("Saved"); void refreshStatus(); }
        catch (e) { toast((e as Error).message, "error"); }
      };
      if (!s.editable) return h("span", { class: "muted small" }, s.secret ? (s.is_set ? "Set in environment" : "Not set") : `Set with ${s.env} in Railway`, s.secret ? null : h("div", { class: "mono" }, String(s.value ?? "")));
      if (s.secret) { const i = h("input", { type: "password", placeholder: s.is_set ? "Set (type to replace)" : "Not set", autocomplete: "off", "aria-label": s.env }); i.onchange = () => { if (i.value) void save(i.value); }; return i; }
      if (s.type === "bool") return h("input", { type: "checkbox", class: "switch", checked: Boolean(s.value), "aria-label": s.name, onchange: (e: Event) => void save((e.target as HTMLInputElement).checked) });
      if (s.options) { const sel = h("select", { "aria-label": s.env }, s.options.map((o) => h("option", { value: o, selected: s.value === o }, o))); sel.onchange = () => void save(sel.value); return sel; }
      const num = s.type === "int" || s.type === "float";
      const i = h("input", { type: num ? "number" : "text", value: String(s.value ?? ""), step: s.type === "float" ? "any" : undefined, "aria-label": s.env });
      i.onchange = () => void save(num ? Number(i.value) : i.value);
      return i;
    };

    const draw = () => {
      const q = search.value.trim().toLowerCase();
      const shown = items.filter((s) => (!q || s.name.includes(q) || s.env.toLowerCase().includes(q) || s.description.toLowerCase().includes(q)) && (!changedOnly.checked || s.source === "dashboard"));
      summary.textContent = `${shown.length} of ${items.length} settings${items.some((s) => s.source === "dashboard") ? `, ${items.filter((s) => s.source === "dashboard").length} changed here` : ""}`;
      const groups = new Map<string, Setting[]>();
      shown.forEach((s) => groups.set(s.group, [...(groups.get(s.group) ?? []), s]));
      mount(box, [...groups].map(([g, list]) => h("details", { class: "group", open: Boolean(q) || changedOnly.checked || openGroups.has(g), ontoggle: (e: Event) => { const d = e.target as HTMLDetailsElement; if (d.open) openGroups.add(g); else openGroups.delete(g); } },
        h("summary", null, h("span", { class: "row nowrap", style: "gap:8px" }, icon("chevronRight", 16), g), h("span", { class: "chip" }, `${list.length}`)),
        list.map((s) => h("div", { class: "setting" },
          h("div", null, h("div", { class: "mono" }, s.env), h("div", { class: "muted small" }, s.description),
            s.source === "dashboard" ? h("button", { class: "btn small ghost", style: "margin-top:6px", onclick: async () => { await del(`/api/settings/${s.name}`); await load(); } }, icon("refresh", 14), "Reset to default") : null),
          h("div", null, control(s), h("div", { class: "muted small" }, s.reserved ? "Reserved for a future feature" : `Source: ${s.source}`)))))),
        shown.length ? null : empty("search", "No settings match."));
    };
    const load = async () => { items = (await get<{ items: Setting[] }>("/api/settings")).items; draw(); };
    search.oninput = draw;
    changedOnly.onchange = draw;
    mount(root, pageHead("sliders", "Settings", "Changes made here apply immediately and override the environment until you reset them. Secrets are never shown."), areaNav("settings"), settingsTabs("options"),
      h("div", { class: "row between", style: "margin-bottom:14px" },
        h("div", { class: "input-icon", style: "flex:1 1 280px;max-width:420px" }, icon("search", 16), search),
        h("label", { class: "check small" }, changedOnly, "Changed from default only"), summary),
      box);
    void load().catch((e) => toast(e.message, "error"));
  },
};
