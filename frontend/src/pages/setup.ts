import { del, get, post } from "../api.js";
import { busy, copyButton, h, mount, toast, ago } from "../dom.js";
import { icon } from "../icons.js";
import { refreshStatus } from "../state.js";
import { pageHead } from "./shared.js";
import type { Page } from "./types.js";

interface Setup {
  requirements: Record<string, { env: string; set: boolean }[]>;
  public_url: string; telegram_webhook_url: string; google_redirect_uri: string;
  youtube_connected: boolean; telegram_owner_bound: boolean; telegram_bot: string | null;
}

interface Verify { ok: boolean; checks: { ok: boolean | null; label: string; detail: string }[] }

interface Diag {
  client_id: string; client_id_length: number; secret_set: boolean; redirect_uri: string; scope: string; sign_in_url: string;
  checks: { ok: boolean; text: string }[]; note: string;
}

const AREA_NAMES: Record<string, string> = { dashboard: "Dashboard", database: "Database", telegram: "Telegram", youtube: "YouTube", app: "App" };

export const setup: Page = {
  id: "setup",
  title: "Setup",
  icon: "plug",
  blurb: "Connect YouTube and Telegram",
  render(root, query) {
    const box = h("div", { class: "stack" });
    const urlRow = (label: string, value: string) => h("div", { class: "row between" }, h("span", null, h("div", { class: "muted small" }, label), h("span", { class: "mono" }, value || "Not set yet")), value ? copyButton(value) : null);
    const diagBox = h("div", { class: "body stack" });
    const runDiag = async () => {
      const d = await get<Diag>("/api/youtube/diagnostics");
      mount(diagBox,
        h("ul", { class: "list", style: "margin:0" }, d.checks.map((c) => h("li", { class: "row", style: "padding:6px 0;border:0" }, h("span", { class: `chip ${c.ok ? "ok" : "bad"}` }, icon(c.ok ? "check" : "alert", 12), c.ok ? "OK" : "Fix"), h("span", null, c.text)))),
        h("div", { class: "row between" }, h("span", null, h("div", { class: "muted small" }, `Client ID the bot sends (${d.client_id_length} characters)`), h("span", { class: "mono", style: "overflow-wrap:anywhere" }, d.client_id || "(empty)")), d.client_id ? copyButton(d.client_id) : null),
        h("div", { class: "row between" }, h("span", null, h("div", { class: "muted small" }, "Redirect address the bot sends"), h("span", { class: "mono", style: "overflow-wrap:anywhere" }, d.redirect_uri || "(empty)")), d.redirect_uri ? copyButton(d.redirect_uri) : null),
        h("p", { class: "muted small" }, "Compare both with the SavahBot client in Google Cloud: they must match exactly. The client secret is never shown."),
        h("p", { class: "muted small" }, d.note));
    };
    const verifyBox = h("div", { class: "body stack" });
    const runVerify = async () => {
      const v = await post<Verify>("/api/youtube/verify");
      mount(verifyBox, h("ul", { class: "list", style: "margin:0" }, v.checks.map((c) => h("li", { class: "row", style: "padding:6px 0;border:0" },
        h("span", { class: `chip ${c.ok === true ? "ok" : c.ok === false ? "bad" : "warn"}` }, icon(c.ok === true ? "check" : c.ok === false ? "alert" : "info", 12), c.ok === true ? "OK" : c.ok === false ? "Fix" : "Unverified"),
        h("span", null, h("strong", null, `${c.label}: `), c.detail)))));
    };
    const load = async () => {
      const [s, st] = await Promise.all([get<Setup>("/api/setup"), refreshStatus()]);
      const yt = st?.youtube, tg = st?.telegram;
      const ytMsg = query.get("message");
      mount(box,
        ytMsg ? h("div", { class: `banner ${query.get("youtube") === "error" ? "error" : ""}` }, ytMsg) : null,
        (() => {
          const missing = Object.values(s.requirements).flat().filter((i) => !i.set).length;
          const steps: { done: boolean; title: string; text: string; href?: string }[] = [
            { done: !!s.public_url, title: "Public address", text: s.public_url ? s.public_url : "Set PUBLIC_BASE_URL in Railway" },
            { done: !!tg?.configured, title: "Telegram bot token", text: tg?.configured ? `Bot @${s.telegram_bot ?? "connected"}` : "Create a bot with @BotFather and set TELEGRAM_BOT_TOKEN" },
            { done: !!s.telegram_owner_bound, title: "Claim the bot", text: s.telegram_owner_bound ? "Only your account can use it" : "Send /claim and your dashboard password to the bot" },
            { done: !!s.youtube_connected, title: "Google account", text: s.youtube_connected ? (yt?.account?.title || "Connected") : "Press Connect Google account below" },
            { done: !!yt?.target, title: "Target channel", text: yt?.target ? (yt.target.title || yt.target.channel_id) : "Choose the channel whose live chat you moderate" },
          ];
          const done = steps.filter((x) => x.done).length;
          return h("section", { class: "block flush" }, h("header", null, h("h2", null, icon("check", 18), "Setup progress"), h("span", { class: `chip ${done === steps.length ? "ok" : "warn"}` }, `${done} of ${steps.length} done`)),
            h("div", { class: "body", style: "padding:14px 16px 0" }, h("div", { class: "progress", role: "progressbar", "aria-valuemin": 0, "aria-valuemax": steps.length, "aria-valuenow": done, "aria-label": "Setup progress" }, h("i", { style: `width:${(done / steps.length) * 100}%` }))),
            h("div", { class: "steps", style: "margin-top:8px" }, steps.map((x, i) => h("div", { class: `step ${x.done ? "done" : "todo"}` },
              h("span", { class: "mark" }, x.done ? icon("check", 14) : String(i + 1)), h("div", { style: "min-width:0" }, h("div", null, x.title), h("div", { class: "muted small", style: "overflow-wrap:anywhere" }, x.text)),
              h("span", { class: `chip ${x.done ? "ok" : "warn"}` }, x.done ? "Done" : "To do")))),
            missing ? h("div", { class: "body muted small" }, `${missing} optional or required variable${missing === 1 ? " is" : "s are"} still unset. See the list at the bottom.`) : null);
        })(),
        h("section", { class: "block" }, h("header", null, h("h2", null, icon("copy", 18), "Addresses to paste into other services")), h("div", { class: "body stack" },
          urlRow("Backend public address (PUBLIC_BASE_URL)", s.public_url), urlRow("Telegram webhook", s.telegram_webhook_url), urlRow("Google OAuth redirect URI", s.google_redirect_uri))),
        h("div", { class: "cols" },
          h("section", { class: "block" }, h("header", null, h("h2", null, icon("youtube", 18), "YouTube"), h("span", { class: `chip ${s.youtube_connected ? "ok" : "warn"}` }, s.youtube_connected ? "Connected" : "Not connected")),
            h("div", { class: "body stack" },
              yt?.last_error ? h("p", { style: "color:var(--bad)" }, yt.last_error) : null,
              yt?.last_action_error ? h("p", { style: "color:var(--bad)" }, `Last refused action: ${yt.last_action_error}`) : null,
              s.youtube_connected && yt ? h("div", { class: "stack", style: "gap:6px" },
                h("div", null, h("div", { class: "muted small" }, "Signed in as (the moderator)"),
                  h("span", null, yt.account ? (yt.account.title || "Unnamed account") : "Not looked up yet", yt.account?.channel_id ? h("span", { class: "mono muted" }, `  ${yt.account.channel_id}`) : yt.account ? h("span", { class: "muted" }, "  (no YouTube channel of its own)") : null)),
                h("div", null, h("div", { class: "muted small" }, "Moderating the live chat of (the target channel)"),
                  yt.target ? h("span", null, yt.target.title || "Channel", h("span", { class: "mono muted" }, `  ${yt.target.channel_id}`)) : h("span", { class: "chip warn" }, "Not set: put its ID in YOUTUBE_TARGET_CHANNEL_ID"),
                  !yt.target && yt.account?.channel_id ? h("div", { style: "margin-top:6px" }, h("button", { class: "btn small primary", onclick: (e: Event) => busy(e.currentTarget as HTMLButtonElement, async () => { await post("/api/youtube/use-own-channel"); await load(); }, "Now moderating your own channel") }, "Moderate my own channel")) : null,
                  yt.target ? h("p", { class: "muted small", style: "margin-top:6px" }, ((yt as any).target_source === "dashboard" ? "Set from this dashboard (this overrides the Railway variable). " : (yt as any).target_source === "legacy" ? "Taken from the old YOUTUBE_CHANNEL_ID variable: delete it and set YOUTUBE_TARGET_CHANNEL_ID. " : "Taken from the YOUTUBE_TARGET_CHANNEL_ID Railway variable. ")) : null,
                  (yt as any)?.target_source === "dashboard" ? h("button", { class: "btn small ghost", onclick: (e: Event) => busy(e.currentTarget as HTMLButtonElement, async () => { await del("/api/settings/youtube_target_channel_id"); await load(); }, "Now using the Railway variable") }, "Use the Railway variable instead") : null)) : null,
              yt ? h("p", { class: "muted small" }, `State: ${yt.state}. Last poll ${ago(yt.last_poll)}. Quota used today: ${yt.quota.used} of ${yt.quota.daily} units.`) : null,
              h("div", { class: "row" },
                h("button", { class: "btn primary", onclick: (e: Event) => busy(e.currentTarget as HTMLButtonElement, async () => { const r = await post<{ url: string }>("/api/youtube/oauth/start"); location.href = r.url; }) }, s.youtube_connected ? "Reconnect Google account" : "Connect Google account"),
                s.youtube_connected ? h("button", { class: "btn ghost", onclick: (e: Event) => busy(e.currentTarget as HTMLButtonElement, async () => { await post("/api/youtube/disconnect"); await load(); }, "Disconnected") }, "Disconnect") : null))),
          h("section", { class: "block" }, h("header", null, h("h2", null, icon("telegram", 18), "Telegram"), h("span", { class: `chip ${tg?.configured && s.telegram_owner_bound ? "ok" : "warn"}` }, !tg?.configured ? "No token" : s.telegram_owner_bound ? "Ready" : "Not claimed")),
            h("div", { class: "body stack" },
              tg?.last_error ? h("p", { style: "color:var(--bad)" }, tg.last_error) : null,
              tg?.configured && !s.telegram_owner_bound ? h("p", null, `Open @${s.telegram_bot ?? "your bot"} in Telegram and send /claim followed by your dashboard password. Only your account will be able to use the bot.`) : null,
              h("div", { class: "row" }, h("label", { class: "field" }, "Update delivery", (() => {
                const sel = h("select", null, [["webhook", "Webhook (recommended)"], ["polling", "Polling"]].map(([v, l]) => h("option", { value: v, selected: tg?.mode === v }, l)));
                sel.onchange = () => busy(sel as unknown as HTMLButtonElement, async () => { await post("/api/telegram/mode", { mode: sel.value }); await load(); }, "Telegram mode changed");
                return sel;
              })()), h("button", { class: "btn ghost", onclick: (e: Event) => busy(e.currentTarget as HTMLButtonElement, async () => { await post("/api/telegram/test"); }, "Test message sent") }, "Send test message")),
              h("p", { class: "muted small" }, tg?.mode === "webhook" ? `Webhook: ${tg.webhook_url || "not registered"}` : `Polling: ${tg?.polling ? "running" : "stopped"}`)))),
        h("section", { class: "block flush" }, h("header", null, h("h2", null, icon("shield", 18), "Verify moderator access"),
          h("button", { class: "btn small ghost", onclick: (e: Event) => busy(e.currentTarget as HTMLButtonElement, runVerify) }, icon("check", 15), "Verify access")),
          h("div", { class: "body" }, h("p", { class: "muted small" }, "Asks YouTube what the signed-in account can really do for the target channel. It never deletes or bans anything, and deleting and banning cannot be tested ahead of time, so they show as Unverified until YouTube has answered a real action.")), verifyBox),
        h("section", { class: "block flush" }, h("header", null, h("h2", null, icon("lock", 18), "Check the Google connection"),
          h("button", { class: "btn small ghost", onclick: (e: Event) => busy(e.currentTarget as HTMLButtonElement, runDiag) }, icon("activity", 15), "Run check")), diagBox),
        h("section", { class: "block flush" }, h("header", null, h("h2", null, icon("sliders", 18), "Variables to set in Railway"), h("span", { class: "muted small" }, "Everything else already has a safe default")),
          h("div", { class: "body stack" }, Object.entries(s.requirements).map(([area, items]) => h("div", null, h("h3", null, AREA_NAMES[area] ?? area),
            h("div", { class: "row", style: "margin-top:6px" }, items.map((i) => h("span", { class: `chip ${i.set ? "ok" : "warn"}`, title: i.set ? "Set" : "Not set" }, icon(i.set ? "check" : "alert", 12), i.env))))))));
    };
    mount(root, pageHead("plug", "Setup", "Connect YouTube and Telegram, and see which variables are still missing.", h("button", { class: "btn ghost", type: "button", onclick: (e: Event) => busy(e.currentTarget as HTMLButtonElement, load) }, icon("refresh", 16), "Refresh")), box);
    void load().catch((e) => toast(e.message, "error"));
  },
};
