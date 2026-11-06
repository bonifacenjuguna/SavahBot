import { del, get, post } from "../api.js";
import { busy, copyButton, h, mount, toast, ago } from "../dom.js";
import { icon } from "../icons.js";
import { ring } from "../charts.js";
import { refreshStatus, type Status } from "../state.js";
import { areaNav } from "./kit.js";
import { pageHead } from "./shared.js";
import type { Page } from "./types.js";

export interface Setup {
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

export interface Step { id: string; done: boolean; title: string; text: string; go: string }

/** The five things that must be true before the bot can moderate. Shared with the More page. */
export function setupSteps(s: Setup, st: Status | null): Step[] {
  const yt = st?.youtube, tg = st?.telegram;
  return [
    { id: "s1", go: "addresses", done: !!s.public_url, title: "Public address", text: s.public_url ? s.public_url : "Set PUBLIC_BASE_URL in Railway" },
    { id: "s2", go: "telegram", done: !!tg?.configured, title: "Telegram bot token", text: tg?.configured ? `Bot @${s.telegram_bot ?? "connected"}` : "Create a bot with @BotFather and set TELEGRAM_BOT_TOKEN" },
    { id: "s3", go: "telegram", done: !!s.telegram_owner_bound, title: "Claim the bot", text: s.telegram_owner_bound ? "Only your account can use it" : "Send /claim and your dashboard password to the bot" },
    { id: "s4", go: "youtube", done: !!s.youtube_connected, title: "Google account", text: s.youtube_connected ? (yt?.account?.title || "Connected") : "Press Connect Google account on the YouTube step" },
    { id: "s5", go: "youtube", done: !!yt?.target, title: "Target channel", text: yt?.target ? (yt.target.title || yt.target.channel_id) : "Choose the channel whose live chat you moderate" },
  ];
}

const STEPS: { id: string; title: string; blurb: string; icon: string }[] = [
  { id: "overview", title: "Overview", blurb: "Where you are", icon: "rocket" },
  { id: "addresses", title: "Addresses", blurb: "Links to paste", icon: "link" },
  { id: "youtube", title: "YouTube", blurb: "Account and channel", icon: "youtube" },
  { id: "telegram", title: "Telegram", blurb: "Bot and owner", icon: "telegram" },
  { id: "variables", title: "Variables", blurb: "Railway settings", icon: "sliders" },
];

type Tone = "ok" | "warn" | "bad" | "";

export const setup: Page = {
  id: "setup",
  title: "Setup",
  icon: "plug",
  blurb: "Connect YouTube and Telegram",
  render(root, query) {
    let step = STEPS.some((x) => x.id === query.get("step")) ? query.get("step")! : query.get("youtube") ? "youtube" : "overview";
    let data: { s: Setup; st: Status | null } | null = null;
    let notice = query.get("message") ? { text: query.get("message")!, bad: query.get("youtube") === "error" } : null;
    let onlyMissing = false;
    let verify: Verify | null = null;
    let diag: Diag | null = null;

    const nav = h("nav", { class: "setup-nav", "aria-label": "Setup steps" });
    const panel = h("section", { class: "setup-panel", "aria-live": "polite" });
    const refreshBtn = h("button", { class: "btn ghost", type: "button", onclick: (e: Event) => busy(e.currentTarget as HTMLButtonElement, load) }, icon("refresh", 16), "Refresh");

    const go = (id: string) => {
      step = id;
      history.replaceState(null, "", `#/setup?step=${id}`);   // no page redraw, and the address can be shared or bookmarked
      draw();
      panel.scrollIntoView({ block: "start", behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" });
    };

    // ------------------------------------------------------------ status of each step (drives the dots in the navigation)
    const stepTone = (id: string): { tone: Tone; text: string } => {
      if (!data) return { tone: "", text: "" };
      const { s, st } = data;
      const steps = setupSteps(s, st);
      const mine = (ids: string[]) => steps.filter((x) => ids.includes(x.go));
      const pick = (arr: Step[], err = false): { tone: Tone; text: string } => err ? { tone: "bad", text: "Needs attention" } : arr.every((x) => x.done) ? { tone: "ok", text: "Done" } : { tone: "warn", text: `${arr.filter((x) => x.done).length} of ${arr.length}` };
      if (id === "overview") { const n = steps.filter((x) => x.done).length; return n === steps.length ? { tone: "ok", text: "All set" } : { tone: "warn", text: `${n} of ${steps.length}` }; }
      if (id === "addresses") return pick(mine(["addresses"]));
      if (id === "youtube") return pick(mine(["youtube"]), !!st?.youtube.last_error);
      if (id === "telegram") return pick(mine(["telegram"]), !!st?.telegram.last_error);
      const missing = Object.values(s.requirements).flat().filter((i) => !i.set).length;
      return missing ? { tone: "warn", text: `${missing} unset` } : { tone: "ok", text: "All set" };
    };

    const drawNav = () => mount(nav, STEPS.map((x, i) => {
      const t = stepTone(x.id);
      return h("a", { href: `#/setup?step=${x.id}`, class: "sn-item", "aria-current": x.id === step ? "step" : undefined, "data-tone": t.tone,
        onclick: (e: Event) => { e.preventDefault(); go(x.id); } },
        h("span", { class: "sn-dot" }, t.tone === "ok" ? icon("check", 14) : t.tone === "bad" ? icon("alert", 14) : String(i + 1)),
        h("span", { class: "sn-text" }, h("strong", null, x.title), h("span", null, t.text || x.blurb)));
    }));

    // ------------------------------------------------------------ small parts
    const head = (ic: string, title: string, text: string, chip?: [Tone, string]) =>
      h("header", { class: "sp-head" }, h("span", { class: "sp-ico" }, icon(ic, 22)), h("div", { class: "grow" }, h("h2", null, title), h("p", null, text)), chip ? h("span", { class: `chip ${chip[0]}` }, chip[1]) : null);
    const section = (title: string | null, ...kids: (Node | null | false)[]) => h("div", { class: "sp-card" }, title ? h("h3", null, title) : null, ...kids);
    const copyRow = (label: string, value: string, hint?: string) =>
      h("div", { class: "copy-row" }, h("div", { class: "grow" }, h("div", { class: "muted small" }, label), h("div", { class: "mono wrap" }, value || "Not set yet"), hint ? h("div", { class: "muted small" }, hint) : null), value ? copyButton(value) : null);
    const pager = () => {
      const i = STEPS.findIndex((x) => x.id === step);
      const prev = STEPS[i - 1], next = STEPS[i + 1];
      return h("div", { class: "sp-pager" },
        prev ? h("button", { class: "btn ghost", type: "button", onclick: () => go(prev.id) }, icon("arrowLeft", 16), prev.title) : h("span"),
        next ? h("button", { class: "btn primary", type: "button", onclick: () => go(next.id) }, next.title, icon("arrowRight", 16)) : h("span"));
    };
    const checkRow = (tone: Tone, label: string, textNodes: (Node | string)[]) =>
      h("li", { class: "check-row" }, h("span", { class: `chip ${tone}` }, icon(tone === "ok" ? "check" : tone === "bad" ? "alert" : "info", 12), label), h("span", { class: "grow" }, ...textNodes));
    const run = (fn: () => Promise<unknown>, ok?: string) => (e: Event) => busy(e.currentTarget as HTMLButtonElement, fn, ok);

    // ------------------------------------------------------------ panels
    const overview = (): HTMLElement => {
      const { s, st } = data!;
      const steps = setupSteps(s, st);
      const done = steps.filter((x) => x.done).length;
      const next = steps.find((x) => !x.done);
      const missing = Object.values(s.requirements).flat().filter((i) => !i.set).length;
      return h("div", { class: "stack" },
        head("rocket", "Overview", "Five things make the bot ready. Do them in order, or jump to what you need."),
        section(null, h("div", { class: "ov-top" },
          ring(done / steps.length, `${done}/${steps.length}`, "Setup steps done"),
          h("div", { class: "grow" },
            done === steps.length
              ? h("div", null, h("h3", null, "You are all set"), h("p", { class: "muted" }, "Moderation can run. Use Verify on the YouTube step any time to check what the account is allowed to do."))
              : h("div", null, h("span", { class: "eyebrow" }, "Next up"), h("h3", null, next!.title), h("p", { class: "muted wrap" }, next!.text),
                h("button", { class: "btn primary", type: "button", style: "margin-top:10px", onclick: () => go(next!.go) }, "Go to this step", icon("arrowRight", 16)))))),
        section("Checklist", h("ul", { class: "ov-list" }, steps.map((x, i) => h("li", null, h("button", { type: "button", class: `ov-row ${x.done ? "done" : "todo"}`, onclick: () => go(x.go) },
          h("span", { class: "mark" }, x.done ? icon("check", 14) : String(i + 1)), h("span", { class: "grow" }, h("strong", null, x.title), h("span", { class: "muted small wrap" }, x.text)),
          icon("chevronRight", 16)))))),
        missing ? h("button", { class: "ov-note", type: "button", onclick: () => go("variables") }, icon("info", 16), h("span", null, `${missing} variable${missing === 1 ? " is" : "s are"} still unset. See Variables.`), icon("chevronRight", 16)) : null);
    };

    const addresses = (): HTMLElement => {
      const { s } = data!;
      return h("div", { class: "stack" },
        head("link", "Addresses", "Copy these into the services that ask for them.", s.public_url ? ["ok", "Public address set"] : ["warn", "Not set"]),
        section(null,
          copyRow("Backend public address (PUBLIC_BASE_URL)", s.public_url, "Set in Railway. Everything below is built from it."),
          copyRow("Telegram webhook", s.telegram_webhook_url, "Registered with Telegram for you in webhook mode."),
          copyRow("Google OAuth redirect URI", s.google_redirect_uri, "Paste into your OAuth client in Google Cloud, exactly as shown.")),
        pager());
    };

    const youtube = (): HTMLElement => {
      const { s, st } = data!;
      const yt = st?.youtube as (Status["youtube"] & { target_source?: string }) | undefined;
      const source = yt?.target_source;
      const connected = s.youtube_connected;
      return h("div", { class: "stack" },
        head("youtube", "YouTube", "Sign in with the moderator account, then choose the channel whose chat it moderates.", connected ? ["ok", "Connected"] : ["warn", "Not connected"]),
        yt?.last_error ? h("div", { class: "banner error" }, icon("alert", 18), h("span", null, yt.last_error)) : null,
        yt?.last_action_error ? h("div", { class: "banner error" }, icon("ban", 18), h("span", null, `Last refused action: ${yt.last_action_error}`)) : null,
        section("Connection",
          connected && yt ? h("dl", { class: "facts" },
            h("dt", null, "Signed in as (the moderator)"),
            h("dd", null, yt.account ? (yt.account.title || "Unnamed account") : "Not looked up yet", yt.account?.channel_id ? h("span", { class: "mono muted" }, `  ${yt.account.channel_id}`) : yt.account ? h("span", { class: "muted" }, "  (no YouTube channel of its own)") : null),
            h("dt", null, "Moderating the live chat of (the target channel)"),
            h("dd", null, yt.target ? h("span", null, yt.target.title || "Channel", h("span", { class: "mono muted" }, `  ${yt.target.channel_id}`)) : h("span", { class: "chip warn" }, "Not set: put its ID in YOUTUBE_TARGET_CHANNEL_ID"),
              !yt.target && yt.account?.channel_id ? h("div", { style: "margin-top:8px" }, h("button", { class: "btn small primary", type: "button", onclick: run(async () => { await post("/api/youtube/use-own-channel"); await load(); }, "Now moderating your own channel") }, "Moderate my own channel")) : null,
              yt.target ? h("p", { class: "muted small", style: "margin-top:6px" }, source === "dashboard" ? "Set from this dashboard (this overrides the Railway variable). " : source === "legacy" ? "Taken from the old YOUTUBE_CHANNEL_ID variable: delete it and set YOUTUBE_TARGET_CHANNEL_ID. " : "Taken from the YOUTUBE_TARGET_CHANNEL_ID Railway variable. ") : null,
              source === "dashboard" ? h("button", { class: "btn small ghost", type: "button", onclick: run(async () => { await del("/api/settings/youtube_target_channel_id"); await load(); }, "Now using the Railway variable") }, "Use the Railway variable instead") : null))
            : h("p", { class: "muted" }, "No Google account connected yet."),
          yt ? h("p", { class: "muted small" }, `State: ${yt.state}. Last poll ${ago(yt.last_poll)}. Quota used today: ${yt.quota.used} of ${yt.quota.daily} units.`) : null,
          h("div", { class: "row" },
            h("button", { class: "btn primary", type: "button", onclick: run(async () => { const r = await post<{ url: string }>("/api/youtube/oauth/start"); location.href = r.url; }) }, icon("youtube", 16), connected ? "Reconnect Google account" : "Connect Google account"),
            connected ? h("button", { class: "btn ghost", type: "button", onclick: run(async () => { await post("/api/youtube/disconnect"); await load(); }, "Disconnected") }, "Disconnect") : null)),
        section("Verify moderator access",
          h("p", { class: "muted small" }, "Asks YouTube what the signed-in account can really do for the target channel. It never deletes or bans anything, and deleting and banning cannot be tested ahead of time, so they show as Unverified until YouTube has answered a real action."),
          h("div", null, h("button", { class: "btn ghost", type: "button", onclick: run(async () => { verify = await post<Verify>("/api/youtube/verify"); draw(); }) }, icon("check", 16), "Verify access")),
          verify ? h("ul", { class: "check-list" }, verify.checks.map((c) => checkRow(c.ok === true ? "ok" : c.ok === false ? "bad" : "warn", c.ok === true ? "OK" : c.ok === false ? "Fix" : "Unverified", [h("strong", null, `${c.label}: `), c.detail]))) : null),
        section("Check the Google connection",
          h("p", { class: "muted small" }, "Compares what the bot sends to Google with what your Google Cloud client expects."),
          h("div", null, h("button", { class: "btn ghost", type: "button", onclick: run(async () => { diag = await get<Diag>("/api/youtube/diagnostics"); draw(); }) }, icon("activity", 16), "Run check")),
          diag ? h("div", { class: "stack" },
            h("ul", { class: "check-list" }, diag.checks.map((c) => checkRow(c.ok ? "ok" : "bad", c.ok ? "OK" : "Fix", [c.text]))),
            copyRow(`Client ID the bot sends (${diag.client_id_length} characters)`, diag.client_id || "(empty)"),
            copyRow("Redirect address the bot sends", diag.redirect_uri || "(empty)"),
            h("p", { class: "muted small" }, "Compare both with the SavahBot client in Google Cloud: they must match exactly. The client secret is never shown."),
            h("p", { class: "muted small" }, diag.note)) : null),
        pager());
    };

    const telegram = (): HTMLElement => {
      const { s, st } = data!;
      const tg = st?.telegram;
      const ready = !!tg?.configured && s.telegram_owner_bound;
      const sel = h("select", { "aria-label": "Update delivery" }, [["webhook", "Webhook (recommended)"], ["polling", "Polling"]].map(([v, l]) => h("option", { value: v, selected: tg?.mode === v }, l)));
      sel.onchange = () => busy(sel as unknown as HTMLButtonElement, async () => { await post("/api/telegram/mode", { mode: sel.value }); await load(); }, "Telegram mode changed");
      return h("div", { class: "stack" },
        head("telegram", "Telegram", "Control the bot from your phone: approvals, status, search and more.", !tg?.configured ? ["warn", "No token"] : s.telegram_owner_bound ? ["ok", "Ready"] : ["warn", "Not claimed"]),
        tg?.last_error ? h("div", { class: "banner error" }, icon("alert", 18), h("span", null, tg.last_error)) : null,
        section("Bot",
          h("ol", { class: "how" },
            h("li", { class: tg?.configured ? "done" : "" }, h("strong", null, "Create the bot."), " Message @BotFather, send /newbot, then set the token as TELEGRAM_BOT_TOKEN in Railway."),
            h("li", { class: s.telegram_owner_bound ? "done" : "" }, h("strong", null, "Claim it."), ` Open ${tg?.configured ? `@${s.telegram_bot ?? "your bot"}` : "the bot"} in Telegram and send /claim followed by your dashboard password. Only your account will be able to use the bot.`),
            h("li", { class: ready ? "done" : "" }, h("strong", null, "Try it."), " Send /menu in Telegram for buttons, or press Send test message below.")),
          tg?.configured && !s.telegram_owner_bound ? h("div", null, copyButton("/claim ", "Copy /claim")) : null),
        section("Delivery",
          h("div", { class: "row" }, h("label", { class: "field" }, "Update delivery", sel),
            h("button", { class: "btn ghost", type: "button", onclick: run(async () => { await post("/api/telegram/test"); }, "Test message sent") }, icon("send", 16), "Send test message")),
          h("p", { class: "muted small wrap" }, tg?.mode === "webhook" ? `Webhook: ${tg.webhook_url || "not registered"}` : `Polling: ${tg?.polling ? "running" : "stopped"}`)),
        pager());
    };

    const variables = (): HTMLElement => {
      const { s } = data!;
      const all = Object.values(s.requirements).flat();
      const missing = all.filter((i) => !i.set).length;
      const groups = Object.entries(s.requirements).map(([area, items]) => [area, onlyMissing ? items.filter((i) => !i.set) : items] as const).filter(([, items]) => items.length);
      const toggle = h("input", { type: "checkbox", class: "switch", checked: onlyMissing, "aria-label": "Only show variables that are not set" });
      toggle.onchange = () => { onlyMissing = toggle.checked; draw(); };
      return h("div", { class: "stack" },
        head("sliders", "Variables", "Set these in Railway. Everything else already has a safe default.", missing ? ["warn", `${missing} unset`] : ["ok", "All set"]),
        section(null,
          h("div", { class: "row between" }, h("span", { class: "muted small" }, `${all.length - missing} of ${all.length} set`), h("label", { class: "check small" }, toggle, "Only what is missing")),
          groups.length ? h("div", { class: "stack" }, groups.map(([area, items]) => h("div", { class: "var-group" }, h("h3", null, AREA_NAMES[area] ?? area),
            h("div", { class: "row", style: "margin-top:6px" }, items.map((i) => h("span", { class: `chip ${i.set ? "ok" : "warn"}`, title: i.set ? "Set" : "Not set" }, icon(i.set ? "check" : "alert", 12), i.env))))))
            : h("div", { class: "empty" }, icon("checkCircle", 28), h("span", null, "Everything is set."))),
        pager());
    };

    const PANELS: Record<string, () => HTMLElement> = { overview, addresses, youtube, telegram, variables };
    function draw(): void {
      if (!data) { mount(panel, h("div", { class: "skeleton" }, "Loading setup")); return; }
      drawNav();
      mount(panel, notice ? h("div", { class: `banner ${notice.bad ? "error" : ""}` }, icon(notice.bad ? "alert" : "info", 18), h("span", { class: "grow" }, notice.text), h("button", { class: "icon-btn", type: "button", "aria-label": "Dismiss", onclick: () => { notice = null; draw(); } }, icon("x", 16))) : null, PANELS[step]());
    }
    async function load(): Promise<void> {
      const [s, st] = await Promise.all([get<Setup>("/api/setup"), refreshStatus()]);
      data = { s, st };
      draw();
    }

    mount(root, pageHead("plug", "Setup", "Connect YouTube and Telegram, step by step.", refreshBtn), areaNav("setup"), h("div", { class: "setup-wrap" }, nav, panel));
    draw();
    void load().catch((e) => toast(e.message, "error"));
  },
};
