import { del, get, post } from "../api.js";
import { busy, h, mount, toast, toastAction } from "../dom.js";
import { icon } from "../icons.js";
import { refreshStatus } from "../state.js";
import { areaNav } from "./kit.js";
import { pageHead } from "./shared.js";
import type { Page } from "./types.js";
import { confirmAct } from "./widgets.js";
import { navigate } from "../router.js";

interface Scenario { name: string; label?: string; description?: string; summary?: string; running: boolean }

/** What each scenario is meant to show, so a run is a lesson and not just noise on the Desk. Unknown scenarios fall back to their own description. */
const INFO: Record<string, { icon: string; group: string; expect: string; time?: string }> = {
  friendly_chat: { icon: "message", group: "normal", expect: "Nothing is flagged. A good check that the bot leaves normal chat alone.", time: "about 20 seconds" },
  commands: { icon: "terminal", group: "normal", expect: "The bot answers each command in chat. Look for its replies on the Desk.", time: "about 8 seconds" },
  spam_raid: { icon: "users", group: "attacks", expect: "The raid detector flags the near-identical lines from six new accounts.", time: "about 6 seconds" },
  flood: { icon: "zap", group: "attacks", expect: "The sender is caught by the speed limit after a few quick messages.", time: "2 seconds" },
  bot_timing: { icon: "timer", group: "attacks", expect: "The account is flagged for posting at an exact rhythm, as a script would.", time: "about 35 seconds" },
  link_spammer: { icon: "external", group: "attacks", expect: "A new account with a banned phrase and a link scores high enough to be acted on." },
  caps_flood: { icon: "alert", group: "tone", expect: "The shouting and stretched letters are picked up by the caps and repetition checks." },
  disguised_words: { icon: "eyeOff", group: "tone", expect: "A banned phrase is caught even with leetspeak, odd spacing or look-alike letters." },
  mixed: { icon: "rocket", group: "full", expect: "Friendly chat, commands, disguised words and a raid, one after another.", time: "about 45 seconds" },
};
const GROUPS: { id: string; title: string; text: string }[] = [
  { id: "full", title: "Full run", text: "Everything back to back. The quickest way to see the whole bot work." },
  { id: "attacks", title: "Spam and raids", text: "Behaviour that comes from many accounts or from scripts." },
  { id: "tone", title: "Tone and disguises", text: "What one viewer can type to get around a word filter." },
  { id: "normal", title: "Normal chat", text: "Friendly viewers and commands. Nothing should go wrong." },
];

export const demo: Page = {
  id: "demo",
  title: "Demo",
  icon: "flask",
  blurb: "Run simulated chat scenarios",
  render(root) {
    const box = h("div", { class: "stack" });
    let signature = "";
    let alive = true;

    const draw = (d: { status: { ambient: boolean; channel: string }; scenarios: Scenario[]; active: boolean }) => {
      const live = !d.active;
      const running = d.scenarios.filter((s) => s.running);
      const run = (s: Scenario) => (e: Event) => busy(e.currentTarget as HTMLButtonElement, async () => {
        await post("/api/demo/scenario", { name: s.name });
        await load();
        toastAction(`${s.label ?? s.name.replace(/_/g, " ")} started`, "Open Desk", () => { navigate("/desk"); }, 6000);
      });
      const cardFor = (s: Scenario) => {
        const meta = INFO[s.name];
        const label = s.label ?? s.name.replace(/_/g, " ");
        return h("article", { class: `scn${s.running ? " is-running" : ""}` },
          h("div", { class: "scn-top" }, h("span", { class: "scn-ico" }, icon(meta?.icon ?? "flask", 22)), h("div", { class: "scn-title" }, h("strong", null, label), h("span", { class: "muted small" }, meta?.time ? `Takes ${meta.time}` : "Over in a moment"))),
          h("p", { class: "scn-what" }, s.description ?? s.summary ?? ""),
          meta ? h("p", { class: "scn-expect" }, icon("target", 15), h("span", null, h("b", null, "You should see "), meta.expect)) : null,
          s.running ? h("div", { class: "scn-live", role: "status" }, h("span", { class: "scn-bar" }, h("i", null)), h("a", { href: "/desk" }, "Running. Watch the Desk")) : null,
          h("button", { class: `btn ${meta?.group === "full" ? "primary" : "ghost"} block-btn`, disabled: live || s.running, onclick: run(s) }, icon(s.running ? "activity" : "play", 16), s.running ? "Running" : "Run this scenario"));
      };
      const known = new Set(Object.keys(INFO));
      const sections = GROUPS.map((g) => ({ g, items: d.scenarios.filter((s) => INFO[s.name]?.group === g.id) })).filter((x) => x.items.length);
      const other = d.scenarios.filter((s) => !known.has(s.name));
      if (other.length) sections.push({ g: { id: "other", title: "More scenarios", text: "" }, items: other });

      mount(box,
        live ? h("div", { class: "banner" }, icon("info", 18), h("span", { class: "grow" }, "You are in live mode. Switch to demo to run simulated scenarios."),
          h("button", { class: "btn small primary", onclick: (e: Event) => busy(e.currentTarget as HTMLButtonElement, async () => { await post("/api/mode", { mode: "demo" }); await refreshStatus(); await load(); }) }, icon("flask", 15), "Switch to demo")) : null,
        h("section", { class: "wb demo-bench", "aria-label": "Playground" },
          h("div", { class: "demo-bench-top" },
            h("div", null, h("h2", null, "Playground"), h("p", { class: "lede" }, running.length ? `${running.length} running now. Open the Desk to watch the bot react.` : "Pick a scenario below, then open the Desk to watch the bot react.")),
            h("a", { class: "btn ghost", href: "/desk" }, icon("desk", 16), "Open Desk")),
          h("label", { class: "ambient" }, h("span", { class: "ambient-text" }, h("strong", null, "Friendly background chat"), h("span", { class: "muted small" }, "Keeps a few viewers chatting while you test, so the Desk feels alive.")),
            h("input", { type: "checkbox", class: "switch", checked: d.status.ambient, disabled: live, "aria-label": "Friendly background chat", onchange: (e: Event) => void post("/api/demo/ambient", { on: (e.target as HTMLInputElement).checked }).catch((x) => toast(x.message, "error")) }))),
        sections.map(({ g, items }) => h("section", { class: "coll", "aria-label": g.title }, h("div", { class: "coll-head" }, h("h3", { class: "coll-title" }, g.title), g.text ? h("p", { class: "muted small" }, g.text) : null), h("div", { class: "scn-grid" }, items.map(cardFor)))),
        h("section", { class: "danger-zone" }, h("div", null, h("strong", null, "Clean up"), h("p", { class: "muted small" }, "Remove all simulated chat and actions from the database. Real chat is never touched.")),
          h("button", { class: "btn small", type: "button", disabled: live, title: "Adds a few hours of sample chat and bans so Insights, Bans and charts have something to show", onclick: (e: Event) => busy(e.currentTarget as HTMLButtonElement, async () => { try { const r = await post<{ chat_lines: number; bans: number }>("/api/demo/sample"); toast(`Added ${r.chat_lines} chat lines and ${r.bans} bans (demo only)`); } catch (er) { toast((er as Error).message, "error"); } }) }, icon("flask", 15), "Add sample history"),
          confirmAct({ icon: "trash", label: "Clear demo data", text: "Clear demo data", confirmText: "Tap again to clear", onConfirm: async () => { try { await del("/api/chat/demo"); toast("Demo data cleared"); } catch (e) { toast((e as Error).message, "error"); } } })));
    };

    const load = async () => {
      const d = await get<{ status: { ambient: boolean; channel: string }; scenarios: Scenario[]; active: boolean }>("/api/demo");
      const sig = JSON.stringify([d.active, d.status.ambient, d.scenarios.map((s) => [s.name, s.running])]);
      if (sig === signature) return;           // nothing changed: leave the page alone so buttons never flicker under a finger
      signature = sig;
      if (alive) draw(d);
    };
    mount(root, pageHead("flask", "Demo", "Everything here is simulated: no YouTube or Telegram traffic, no quota used. Moderation, commands and approvals behave exactly as they do live."), areaNav("demo"), box);
    void load().catch((e) => toast(e.message, "error"));
    const t = window.setInterval(() => void load().catch(() => undefined), 4000);
    return () => { alive = false; window.clearInterval(t); };
  },
};
