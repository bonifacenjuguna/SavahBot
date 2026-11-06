import { del, get, post } from "../api.js";
import { busy, h, mount, toast } from "../dom.js";
import { refreshStatus } from "../state.js";
import type { Page } from "./types.js";

interface Scenario { name: string; label?: string; description?: string; summary?: string; running: boolean }

export const demo: Page = {
  id: "demo",
  title: "Demo",
  render(root) {
    const box = h("div");
    const load = async () => {
      const d = await get<{ status: { ambient: boolean; channel: string }; scenarios: Scenario[]; active: boolean }>("/api/demo");
      const live = !d.active;
      mount(box,
        live ? h("div", { class: "banner" }, "You are in live mode. Switch to demo to run simulated scenarios.",
          h("button", { class: "btn small primary", onclick: (e: Event) => busy(e.currentTarget as HTMLButtonElement, async () => { await post("/api/mode", { mode: "demo" }); await refreshStatus(); await load(); }) }, "Switch to demo")) : null,
        h("section", { class: "block flush" }, h("header", null, h("h2", null, "Background chat"),
          h("label", { class: "check" }, h("input", { type: "checkbox", checked: d.status.ambient, disabled: live, onchange: (e: Event) => void post("/api/demo/ambient", { on: (e.target as HTMLInputElement).checked }).catch((x) => toast(x.message, "error")) }), "Friendly viewers chatting")),
          h("ul", { class: "list" }, d.scenarios.map((s) => h("li", { class: "row between" },
            h("span", null, h("strong", null, s.label ?? s.name.replace(/_/g, " ")), h("div", { class: "muted small" }, s.description ?? s.summary ?? "")),
            h("button", { class: "btn small primary", disabled: live || s.running, onclick: (e: Event) => busy(e.currentTarget as HTMLButtonElement, async () => { await post("/api/demo/scenario", { name: s.name }); await load(); }, "Scenario started. Watch the Desk.") }, s.running ? "Running" : "Run"))))),
        h("section", { class: "block" }, h("header", null, h("h2", null, "Clean up")), h("div", { class: "body row between" }, h("span", { class: "muted" }, "Remove all simulated chat and actions from the database."),
          h("button", { class: "btn danger", onclick: (e: Event) => busy(e.currentTarget as HTMLButtonElement, async () => { await del("/api/chat/demo"); }, "Demo data cleared") }, "Clear demo data"))));
    };
    mount(root, h("div", { class: "page-head" }, h("h1", null, "Demo"), h("p", null, `Everything here is simulated: no YouTube or Telegram traffic, no quota used.Moderation, commands and approvals behave exactly as they do live.`)), box);
    void load().catch((e) => toast(e.message, "error"));
    const t = window.setInterval(() => void load().catch(() => undefined), 8000);
    return () => window.clearInterval(t);
  },
};
