import { del, get, patch } from "../api.js";
import { h, mount, toast } from "../dom.js";
import { refreshStatus } from "../state.js";
import type { Page } from "./types.js";

interface Setting {
  name: string; env: string; group: string; description: string; type: string; default: unknown; value: unknown;
  is_set: boolean; secret: boolean; source: string; editable: boolean; options: string[] | null; reserved: boolean;
}

export const settings: Page = {
  id: "settings",
  title: "Settings",
  render(root) {
    const box = h("div", { class: "block flush" });
    const search = h("input", { type: "text", placeholder: "Search settings", "aria-label": "Search settings" });
    let items: Setting[] = [];

    const control = (s: Setting): HTMLElement => {
      const save = async (value: string | number | boolean) => {
        try { await patch("/api/settings", { values: { [s.name]: value } }); toast("Saved"); void refreshStatus(); }
        catch (e) { toast((e as Error).message, "error"); }
      };
      if (!s.editable) return h("span", { class: "muted small" }, s.secret ? (s.is_set ? "Set in environment" : "Not set") : `Set with ${s.env} in Railway`, s.secret ? null : h("div", { class: "mono" }, String(s.value ?? "")));
      if (s.secret) { const i = h("input", { type: "password", placeholder: s.is_set ? "Set (type to replace)" : "Not set", autocomplete: "off" }); i.onchange = () => { if (i.value) void save(i.value); }; return i; }
      if (s.type === "bool") return h("input", { type: "checkbox", checked: Boolean(s.value), "aria-label": s.name, onchange: (e: Event) => void save((e.target as HTMLInputElement).checked) });
      if (s.options) { const sel = h("select", null, s.options.map((o) => h("option", { value: o, selected: s.value === o }, o))); sel.onchange = () => void save(sel.value); return sel; }
      const num = s.type === "int" || s.type === "float";
      const i = h("input", { type: num ? "number" : "text", value: String(s.value ?? ""), step: s.type === "float" ? "any" : undefined });
      i.onchange = () => void save(num ? Number(i.value) : i.value);
      return i;
    };

    const draw = () => {
      const q = search.value.trim().toLowerCase();
      const shown = items.filter((s) => !q || s.name.includes(q) || s.env.toLowerCase().includes(q) || s.description.toLowerCase().includes(q));
      const groups = new Map<string, Setting[]>();
      shown.forEach((s) => groups.set(s.group, [...(groups.get(s.group) ?? []), s]));
      mount(box, [...groups].map(([g, list]) => h("details", { class: "group", open: Boolean(q) },
        h("summary", null, g, h("span", { class: "muted small" }, `${list.length}`)),
        list.map((s) => h("div", { class: "setting" },
          h("div", null, h("div", { class: "mono" }, s.env), h("div", { class: "muted small" }, s.description),
            s.source === "dashboard" ? h("button", { class: "btn small ghost", style: "margin-top:6px", onclick: async () => { await del(`/api/settings/${s.name}`); await load(); } }, "Reset to default") : null),
          h("div", null, control(s), h("div", { class: "muted small" }, s.reserved ? "Reserved for a future feature" : `Source: ${s.source}`)))))),
        shown.length ? null : h("div", { class: "empty" }, "No settings match."));
    };
    const load = async () => { items = (await get<{ items: Setting[] }>("/api/settings")).items; draw(); };
    search.oninput = draw;
    mount(root, h("div", { class: "page-head" }, h("h1", null, "Settings"), h("p", null, "Changes made here apply immediately and override the environment until you reset them. Secrets are never shown.")),
      h("div", { style: "margin-bottom:14px;max-width:420px" }, search), box);
    void load().catch((e) => toast(e.message, "error"));
  },
};
