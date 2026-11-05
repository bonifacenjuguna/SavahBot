import { del, get, post } from "../api.js";
import { busy, h, mount, toast } from "../dom.js";
import { icon } from "../icons.js";
import { refreshStatus } from "../state.js";
import { areaNav } from "./kit.js";
import { card, pageHead } from "./shared.js";
import type { Page } from "./types.js";

interface Scenario { name: string; label?: string; description?: string; summary?: string; running: boolean }

const ICONS: Record<string, string> = { raid: "users", link: "external", caps: "alert", bot: "bot", disguise: "ban", spam: "flag" };
const pick = (name: string) => Object.entries(ICONS).find(([k]) => name.toLowerCase().includes(k))?.[1] ?? "flask";

export const demo: Page = {
  id: "demo",
  title: "Demo",
  icon: "flask",
  blurb: "Run simulated chat scenarios",
  render(root) {
    const box = h("div", { class: "stack" });
    const load = async () => {
      const d = await get<{ status: { ambient: boolean; channel: string }; scenarios: Scenario[]; active: boolean }>("/api/demo");
      const live = !d.active;
      mount(box,
        live ? h("div", { class: "banner" }, icon("info", 18), h("span", { class: "grow" }, "You are in live mode. Switch to demo to run simulated scenarios."),
          h("button", { class: "btn small primary", onclick: (e: Event) => busy(e.currentTarget as HTMLButtonElement, async () => { await post("/api/mode", { mode: "demo" }); await refreshStatus(); await load(); }) }, icon("flask", 15), "Switch to demo")) : null,
        card("message", "Background chat", h("div", { class: "body row between" }, h("span", { class: "muted" }, "Friendly viewers chatting while you test."),
          h("label", { class: "check" }, h("input", { type: "checkbox", class: "switch", checked: d.status.ambient, disabled: live, "aria-label": "Friendly viewers chatting", onchange: (e: Event) => void post("/api/demo/ambient", { on: (e.target as HTMLInputElement).checked }).catch((x) => toast(x.message, "error")) }), "Friendly viewers chatting")), { flush: true }),
        h("div", { class: "kpis", style: "margin:0;grid-template-columns:repeat(auto-fill,minmax(250px,1fr))" }, d.scenarios.map((s) =>
          h("div", { class: "kpi" },
            h("div", { class: "kpi-top" }, h("strong", { style: "color:var(--ink);font-size:1rem;text-transform:capitalize" }, s.label ?? s.name.replace(/_/g, " ")), icon(pick(s.name), 20)),
            h("div", { class: "kpi-sub", style: "min-height:2.6em" }, s.description ?? s.summary ?? ""),
            h("button", { class: "btn small primary", style: "margin-top:6px", disabled: live || s.running, onclick: (e: Event) => busy(e.currentTarget as HTMLButtonElement, async () => { await post("/api/demo/scenario", { name: s.name }); await load(); }, "Scenario started. Watch the Desk.") }, icon(s.running ? "activity" : "play", 15), s.running ? "Running" : "Run")))),
        card("trash", "Clean up", h("div", { class: "body row between" }, h("span", { class: "muted" }, "Remove all simulated chat and actions from the database."),
          h("button", { class: "btn danger", onclick: (e: Event) => busy(e.currentTarget as HTMLButtonElement, async () => { await del("/api/chat/demo"); }, "Demo data cleared") }, icon("trash", 16), "Clear demo data")), { flush: true }));
    };
    mount(root, pageHead("flask", "Demo", "Everything here is simulated: no YouTube or Telegram traffic, no quota used. Moderation, commands and approvals behave exactly as they do live.", h("a", { class: "btn ghost", href: "#/desk" }, icon("desk", 16), "Open Desk")), areaNav("demo"), box);
    void load().catch((e) => toast(e.message, "error"));
    const t = window.setInterval(() => void load().catch(() => undefined), 8000);
    return () => window.clearInterval(t);
  },
};
