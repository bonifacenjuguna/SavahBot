import { del, get, post } from "../api.js";
import { busy, h, mount, toast, ago } from "../dom.js";
import { icon } from "../icons.js";
import { confirmAct } from "./widgets.js";

interface Control {
  enabled: boolean; listen: boolean; send: boolean; actions: boolean; claim_open: boolean; pause_until: number;
  state: "on" | "paused" | "read-only" | "off";
  notify: { pending: boolean; reminders: boolean; stream_events: boolean };
  owner_from_env: boolean; secret_from_env: boolean;
  status: { configured: boolean; owner_bound: boolean };
}
interface Entry { ts: number; kind: string; detail: string; label: string }

const STATE_TEXT: Record<Control["state"], [string, string]> = {
  on: ["ok", "Telegram is on"],
  "read-only": ["warn", "Read-only: the bot can show things but changes nothing"],
  paused: ["warn", "Paused: the bot is silent until the pause ends"],
  off: ["error", "Telegram is off: nothing is heard or sent"],
};

/** Everything the owner can switch on or off for Telegram. Loads and redraws itself; every switch is saved straight away. */
export function telegramControl(onChange: () => void): HTMLElement {
  const root = h("div", { class: "stack" });
  let c: Control | null = null;
  let log: Entry[] = [];

  const fail = (e: unknown) => toast(e instanceof Error ? e.message : "Something went wrong");
  async function load(): Promise<void> {
    try { [c, { items: log }] = await Promise.all([get<Control>("/api/telegram/control"), get<{ items: Entry[] }>("/api/telegram/log")]); } catch (e) { fail(e); }
    draw();
  }
  async function save(body: Record<string, unknown>, done = "Saved"): Promise<void> {
    try { c = await post<Control>("/api/telegram/control", body); toast(done); onChange(); } catch (e) { fail(e); }
    await load();
  }
  const sw = (checked: boolean, label: string, on: (v: boolean) => void, disabled = false) =>
    h("input", { type: "checkbox", class: "switch", checked, disabled, "aria-label": label, onchange: (e: Event) => on((e.target as HTMLInputElement).checked) });
  const row = (title: string, hint: string, control: Node) =>
    h("div", { class: "row between", style: "align-items:center;gap:12px;padding:10px 0;border-top:1px solid var(--line)" },
      h("div", { style: "min-width:0" }, h("strong", null, title), h("div", { class: "muted small" }, hint)), control);
  const dangerRow = (title: string, hint: string, label: string, what: string, path: string, after?: (r: Record<string, unknown>) => string) =>
    row(title, hint, confirmAct({ icon: "alert", label, text: label, confirmText: "Tap again", onConfirm: async () => {
      try { const r = await post<Record<string, unknown>>(path, { confirm: true }); toast(after ? after(r) : what); await load(); onChange(); } catch (e) { fail(e); }
    } }));

  function draw(): void {
    if (!c) { mount(root, h("p", { class: "muted" }, "Loading Telegram controls…")); return; }
    const k = c, [tone, text] = STATE_TEXT[k.state];
    const off = !k.enabled;
    const pause = (m: number, label: string) => h("button", { class: "btn ghost", type: "button", onclick: (e: Event) => busy(e.currentTarget as HTMLButtonElement, () => save({ pause_minutes: m }, m ? `Paused for ${label}` : "Resumed")) }, label);
    mount(root,
      h("div", { class: `banner ${tone === "ok" ? "" : tone}` }, icon(tone === "ok" ? "check" : "alert", 18), h("span", null, text, k.pause_until ? ` (until ${new Date(k.pause_until * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })})` : "")),
      h("div", { class: "sp-card" }, h("h3", null, "Switches"),
        row("Telegram", "The master switch. Off: the webhook is removed, polling stops, nothing is heard and nothing is sent.", sw(k.enabled, "Telegram on", (v) => void save({ enabled: v }, v ? "Telegram is on" : "Telegram is off"))),
        row("Listen to commands", "Off: the bot ignores everything you type or tap, but can still send you alerts.", sw(k.listen, "Listen to commands", (v) => void save({ listen: v }), off)),
        row("Send messages", "Off: the bot sends nothing at all, not alerts and not replies.", sw(k.send, "Send messages", (v) => void save({ send: v }), off)),
        row("Allow changes", "Off = read-only. Commands like /mode, /mod, /say, /approve, /lockdown and the buttons for them are refused. Looking things up still works.", sw(k.actions, "Allow changes", (v) => void save({ actions: v }), off)),
        row("Allow claiming", "Off: nobody can make themselves the owner with /claim. Leave it off once your bot is claimed.", sw(k.claim_open, "Allow claiming", (v) => void save({ claim_open: v })))),
      h("div", { class: "sp-card" }, h("h3", null, "Quiet for a while"),
        h("p", { class: "muted small" }, "Pause Telegram without switching anything off. It comes back by itself."),
        h("div", { class: "row wrap", style: "gap:8px" }, pause(30, "30 min"), pause(120, "2 hours"), pause(480, "8 hours"), k.pause_until ? pause(0, "Resume now") : null)),
      h("div", { class: "sp-card" }, h("h3", null, "Alerts sent to Telegram"),
        h("p", { class: "muted small" }, "Which things may message you. Which notification categories use Telegram is set on the Notifications page."),
        row("Moderation approvals", "Messages that wait for your yes or no.", sw(k.notify.pending, "Approvals", (v) => void save({ notify: { pending: v } }))),
        row("Reminders", "Your own reminders.", sw(k.notify.reminders, "Reminders", (v) => void save({ notify: { reminders: v } }))),
        row("Stream events", "Going live, ending, quota warnings.", sw(k.notify.stream_events, "Stream events", (v) => void save({ notify: { stream_events: v } })))),
      h("div", { class: "sp-card" }, h("h3", null, "If you think it is compromised"),
        h("p", { class: "muted small" }, "Do these in order. The first two keep your token; the last one also removes the owner and closes claiming."),
        dangerRow("Replace the webhook secret", k.secret_from_env ? "The secret is set in your environment. Change TELEGRAM_WEBHOOK_SECRET there." : "Anything signed with the old secret stops working at once.", "Replace", "Webhook secret replaced", "/api/telegram/rotate-secret"),
        dangerRow("Unlink the owner", k.owner_from_env ? "TELEGRAM_OWNER_ID is set in your environment, so it keeps applying. Remove it there too." : "The bot forgets who you are and obeys nobody until it is claimed again.", "Unlink", "Owner unlinked", "/api/telegram/unlink"),
        dangerRow("Cut Telegram off", "Switch off, unlink the owner, close claiming, replace the secret and remove the webhook.", "Cut off", "Telegram is cut off", "/api/telegram/shutdown", () => "Telegram is cut off. Now revoke the token in BotFather."),
        h("p", { class: "muted small" }, "The token itself can only be replaced in Telegram: open @BotFather, send /revoke, choose the bot, then set the new TELEGRAM_BOT_TOKEN and redeploy.")),
      h("div", { class: "sp-card" }, h("div", { class: "row between" }, h("h3", null, "Recent activity"),
        log.length ? h("button", { class: "btn ghost", type: "button", onclick: (e: Event) => busy(e.currentTarget as HTMLButtonElement, async () => { await del("/api/telegram/log"); await load(); }, "Cleared") }, "Clear") : null),
        h("p", { class: "muted small" }, "What happened, not what was said: command names, strangers who were ignored, wrong claim passwords and setting changes. Messages, tokens and passwords are never recorded."),
        log.length
          ? h("ul", { class: "plain", style: "margin:0;padding:0;list-style:none" }, log.slice(0, 40).map((e) =>
            h("li", { style: "display:flex;gap:10px;padding:6px 0;border-top:1px solid var(--line)" },
              h("span", { class: "muted small", style: "min-width:64px" }, ago(e.ts)), h("strong", { class: "small" }, e.label), h("span", { class: "muted small wrap" }, e.detail))))
          : h("p", { class: "muted" }, "Nothing yet.")));
  }
  void load();
  return root;
}
