import { get, post } from "../api.js";
import { busy, copyButton, h, mount, toast, ago } from "../dom.js";
import { refreshStatus } from "../state.js";
import type { Page } from "./types.js";

interface Setup {
  requirements: Record<string, { env: string; set: boolean }[]>;
  public_url: string; telegram_webhook_url: string; google_redirect_uri: string;
  youtube_connected: boolean; telegram_owner_bound: boolean; telegram_bot: string | null;
}

const AREA_NAMES: Record<string, string> = { dashboard: "Dashboard", database: "Database", telegram: "Telegram", youtube: "YouTube", app: "App" };

export const setup: Page = {
  id: "setup",
  title: "Setup",
  render(root, query) {
    const box = h("div", { class: "stack" });
    const urlRow = (label: string, value: string) => h("div", { class: "row between" }, h("span", null, h("div", { class: "muted small" }, label), h("span", { class: "mono" }, value || "Not set yet")), value ? copyButton(value) : null);
    const load = async () => {
      const [s, st] = await Promise.all([get<Setup>("/api/setup"), refreshStatus()]);
      const yt = st?.youtube, tg = st?.telegram;
      const ytMsg = query.get("message");
      mount(box,
        ytMsg ? h("div", { class: `banner ${query.get("youtube") === "error" ? "error" : ""}` }, ytMsg) : null,
        h("section", { class: "block" }, h("header", null, h("h2", null, "Addresses to paste into other services")), h("div", { class: "body stack" },
          urlRow("Backend public address (PUBLIC_BASE_URL)", s.public_url), urlRow("Telegram webhook", s.telegram_webhook_url), urlRow("Google OAuth redirect URI", s.google_redirect_uri))),
        h("div", { class: "cols" },
          h("section", { class: "block" }, h("header", null, h("h2", null, "YouTube"), h("span", { class: `chip ${s.youtube_connected ? "ok" : "warn"}` }, s.youtube_connected ? "Connected" : "Not connected")),
            h("div", { class: "body stack" },
              yt?.last_error ? h("p", { style: "color:var(--bad)" }, yt.last_error) : null,
              yt ? h("p", { class: "muted small" }, `State: ${yt.state}. Last poll ${ago(yt.last_poll)}. Quota used today: ${yt.quota.used} of ${yt.quota.daily} units.`) : null,
              h("div", { class: "row" },
                h("button", { class: "btn primary", onclick: (e: Event) => busy(e.currentTarget as HTMLButtonElement, async () => { const r = await post<{ url: string }>("/api/youtube/oauth/start"); location.href = r.url; }) }, s.youtube_connected ? "Reconnect Google account" : "Connect Google account"),
                s.youtube_connected ? h("button", { class: "btn ghost", onclick: (e: Event) => busy(e.currentTarget as HTMLButtonElement, async () => { await post("/api/youtube/disconnect"); await load(); }, "Disconnected") }, "Disconnect") : null))),
          h("section", { class: "block" }, h("header", null, h("h2", null, "Telegram"), h("span", { class: `chip ${tg?.configured && s.telegram_owner_bound ? "ok" : "warn"}` }, !tg?.configured ? "No token" : s.telegram_owner_bound ? "Ready" : "Not claimed")),
            h("div", { class: "body stack" },
              tg?.last_error ? h("p", { style: "color:var(--bad)" }, tg.last_error) : null,
              tg?.configured && !s.telegram_owner_bound ? h("p", null, `Open @${s.telegram_bot ?? "your bot"} in Telegram and send /claim followed by your dashboard password. Only your account will be able to use the bot.`) : null,
              h("div", { class: "row" }, h("label", { class: "field" }, "Update delivery", (() => {
                const sel = h("select", null, [["webhook", "Webhook (recommended)"], ["polling", "Polling"]].map(([v, l]) => h("option", { value: v, selected: tg?.mode === v }, l)));
                sel.onchange = () => busy(sel as unknown as HTMLButtonElement, async () => { await post("/api/telegram/mode", { mode: sel.value }); await load(); }, "Telegram mode changed");
                return sel;
              })()), h("button", { class: "btn ghost", onclick: (e: Event) => busy(e.currentTarget as HTMLButtonElement, async () => { await post("/api/telegram/test"); }, "Test message sent") }, "Send test message")),
              h("p", { class: "muted small" }, tg?.mode === "webhook" ? `Webhook: ${tg.webhook_url || "not registered"}` : `Polling: ${tg?.polling ? "running" : "stopped"}`)))),
        h("section", { class: "block flush" }, h("header", null, h("h2", null, "Variables to set in Railway"), h("span", { class: "muted small" }, "Everything else already has a safe default")),
          h("div", { class: "body stack" }, Object.entries(s.requirements).map(([area, items]) => h("div", null, h("h3", null, AREA_NAMES[area] ?? area),
            h("div", { class: "row", style: "margin-top:6px" }, items.map((i) => h("span", { class: `chip ${i.set ? "ok" : "warn"}`, title: i.set ? "Set" : "Not set" }, `${i.set ? "✓" : "○"} ${i.env}`))))))));
    };
    mount(root, h("div", { class: "page-head" }, h("h1", null, "Setup"), h("p", null, "Connect YouTube and Telegram, and see which variables are still missing.")), box);
    void load().catch((e) => toast(e.message, "error"));
  },
};
