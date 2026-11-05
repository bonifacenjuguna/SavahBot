import { del, get, post } from "../api.js";
import { ago, busy, copyButton, h, mount, toast } from "../dom.js";
import { icon } from "../icons.js";
import { ring } from "../charts.js";
import { computeSteps, setSetup, type SetupInfo, type SetupSection } from "../progress.js";
import { refreshStatus, type Status } from "../state.js";
import { card, pageHead } from "./shared.js";
import type { Page } from "./types.js";

interface Verify { ok: boolean; checks: { ok: boolean | null; label: string; detail: string }[] }
interface Diag {
  client_id: string; client_id_length: number; secret_set: boolean; redirect_uri: string; scope: string; sign_in_url: string;
  checks: { ok: boolean; text: string }[]; note: string;
}

const AREA_NAMES: Record<string, string> = { dashboard: "Dashboard", database: "Database", telegram: "Telegram", youtube: "YouTube", app: "App" };
const SECTIONS: { id: SetupSection; label: string; icon: string; blurb: string }[] = [
  { id: "overview", label: "Overview", icon: "desk", blurb: "Progress and next step" },
  { id: "addresses", label: "Addresses", icon: "copy", blurb: "Links to paste elsewhere" },
  { id: "youtube", label: "YouTube", icon: "youtube", blurb: "Google account and channel" },
  { id: "telegram", label: "Telegram", icon: "telegram", blurb: "Bot, owner and delivery" },
  { id: "checks", label: "Checks", icon: "activity", blurb: "Test access and connection" },
  { id: "variables", label: "Variables", icon: "sliders", blurb: "Railway settings" },
];

export const setup: Page = {
  id: "setup",
  title: "Setup",
  icon: "plug",
  blurb: "Connect YouTube and Telegram",
  render(root, query) {
    const wanted = query.get("section") as SetupSection | null;
    let section: SetupSection = SECTIONS.some((s) => s.id === wanted) ? (wanted as SetupSection) : query.get("message") ? "youtube" : "overview";
    let s: SetupInfo | null = null;
    let st: Status | null = null;
    let verifyResult: Verify | null = null;
    let diagResult: Diag | null = null;
    let onlyMissing = false;

    const nav = h("nav", { class: "subnav", "aria-label": "Setup sections" });
    const body = h("div", { class: "stack setup-body" });

    // ------------------------------------------------------------------ status of each section (drives the dots in the navigation)
    const tone = (id: SetupSection): { tone: "ok" | "warn" | "bad" | ""; text: string } => {
      if (!s) return { tone: "", text: "" };
      const steps = computeSteps(s, st);
      const done = steps.filter((x) => x.done).length;
      const yt = st?.youtube, tg = st?.telegram;
      const missing = Object.values(s.requirements).flat().filter((i) => !i.set).length;
      switch (id) {
        case "overview": return done === steps.length ? { tone: "ok", text: "" } : { tone: "warn", text: `${done}/${steps.length}` };
        case "addresses": return s.public_url ? { tone: "ok", text: "" } : { tone: "warn", text: "" };
        case "youtube": return yt?.last_error ? { tone: "bad", text: "" } : s.youtube_connected && yt?.target ? { tone: "ok", text: "" } : { tone: "warn", text: "" };
        case "telegram": return tg?.last_error ? { tone: "bad", text: "" } : tg?.configured && s.telegram_owner_bound ? { tone: "ok", text: "" } : { tone: "warn", text: "" };
        case "variables": return missing ? { tone: "warn", text: String(missing) } : { tone: "ok", text: "" };
        default: return { tone: "", text: "" };
      }
    };
    const go = (id: SetupSection) => {
      section = id;
      history.replaceState(null, "", `#/setup?section=${id}`);
      drawNav();
      drawBody();
      window.scrollTo({ top: 0 });
    };
    const drawNav = () => mount(nav, SECTIONS.map((x) => {
      const t = tone(x.id);
      return h("button", { class: "sn-item", type: "button", "aria-current": section === x.id ? "page" : undefined, onclick: () => go(x.id) },
        icon(x.icon, 18), h("span", { class: "sn-text" }, h("span", { class: "sn-label" }, x.label), h("span", { class: "sn-blurb" }, x.blurb)),
        t.text ? h("span", { class: `sn-tag ${t.tone}` }, t.text) : t.tone ? h("i", { class: `sn-dot ${t.tone}`, "aria-label": t.tone === "ok" ? "Done" : t.tone === "bad" ? "Problem" : "To do" }) : null);
    }));

    // ------------------------------------------------------------------ sections
    const urlCard = (title: string, value: string, where: string) =>
      h("div", { class: "url-card" }, h("div", { class: "row between nowrap" }, h("strong", null, title), value ? copyButton(value) : h("span", { class: "chip warn" }, "Not set")),
        h("div", { class: "mono url-val" }, value || "Not set yet"), h("div", { class: "muted small" }, where));

    const overview = (): HTMLElement => {
      const steps = computeSteps(s!, st);
      const done = steps.filter((x) => x.done).length;
      const next = steps.find((x) => !x.done);
      const label = (id: SetupSection) => SECTIONS.find((x) => x.id === id)!.label;
      return h("div", { class: "stack" },
        h("section", { class: "block" }, h("div", { class: "body setup-hero" },
          ring(done / steps.length, `${done}/${steps.length}`, "Setup steps done", ""),
          h("div", { class: "stack tight" },
            h("h2", null, done === steps.length ? "Everything is connected" : "Let's finish setting up"),
            h("p", { class: "muted" }, done === steps.length ? "YouTube and Telegram are ready. Run the checks once, then switch to Live when you start streaming." : `${steps.length - done} step${steps.length - done === 1 ? "" : "s"} left. Start with the next one.`),
            h("div", { class: "row" }, next
              ? h("button", { class: "btn primary", type: "button", onclick: () => go(next.section) }, icon("chevronRight", 16), `${next.title}`)
              : [h("button", { class: "btn primary", type: "button", onclick: () => go("checks") }, icon("activity", 16), "Run the checks"), h("a", { class: "btn ghost", href: "#/desk" }, icon("desk", 16), "Open Desk")])))),
        card("check", "Steps", h("div", { class: "steps" }, steps.map((x, i) => h("div", { class: `step ${x.done ? "done" : "todo"}` },
          h("span", { class: "mark" }, x.done ? icon("check", 14) : String(i + 1)),
          h("div", { style: "min-width:0" }, h("div", null, x.title), h("div", { class: "muted small", style: "overflow-wrap:anywhere" }, x.text)),
          h("button", { class: `btn small ${x.done ? "ghost" : "primary"}`, type: "button", onclick: () => go(x.section) }, x.done ? "Review" : "Open", icon("chevronRight", 14))))), { flush: true,
          actions: h("span", { class: "muted small" }, `Opens ${label("youtube")}, ${label("telegram")} or ${label("addresses")}`) }));
    };

    const addresses = (): HTMLElement => h("div", { class: "stack" },
      h("div", { class: "banner" }, icon("info", 18), h("span", null, "These links belong in other services. Copy each one and paste it where it says.")),
      urlCard("Backend public address", s!.public_url, "Set as the PUBLIC_BASE_URL variable in Railway (your backend's own address)."),
      urlCard("Telegram webhook", s!.telegram_webhook_url, "Telegram calls this address with new messages. SavahBot registers it for you in webhook mode."),
      urlCard("Google OAuth redirect URI", s!.google_redirect_uri, "In Google Cloud Console, add exactly this under Authorized redirect URIs for your OAuth client."));

    const youtube = (): HTMLElement => {
      const yt = st?.youtube;
      const connected = s!.youtube_connected;
      const q = yt?.quota;
      const pct = q ? Math.min(100, Math.round(q.fraction * 100)) : 0;
      const src = (yt as any)?.target_source as string | undefined;
      return h("div", { class: "stack" },
        yt?.last_error ? h("div", { class: "banner error" }, icon("alert", 18), h("span", null, yt.last_error)) : null,
        yt?.last_action_error ? h("div", { class: "banner error" }, icon("ban", 18), h("span", null, `Last refused action: ${yt.last_action_error}`)) : null,
        card("youtube", "Connection", h("div", { class: "body stack" },
          h("div", { class: "tiles" },
            h("div", { class: "tile" }, h("div", { class: "muted small" }, "Signed in as (the moderator)"),
              connected && yt ? h("div", null, h("strong", null, yt.account ? (yt.account.title || "Unnamed account") : "Not looked up yet"), yt.account?.channel_id ? h("div", { class: "mono muted small" }, yt.account.channel_id) : yt.account ? h("div", { class: "muted small" }, "No YouTube channel of its own") : null) : h("span", { class: "chip warn" }, "Not connected")),
            h("div", { class: "tile" }, h("div", { class: "muted small" }, "Moderating the live chat of (the target)"),
              yt?.target ? h("div", null, h("strong", null, yt.target.title || "Channel"), h("div", { class: "mono muted small" }, yt.target.channel_id)) : h("span", { class: "chip warn" }, "Not set yet"))),
          yt?.target ? h("p", { class: "muted small" }, src === "dashboard" ? "Set from this dashboard (this overrides the Railway variable). " : src === "legacy" ? "Taken from the old YOUTUBE_CHANNEL_ID variable: delete it and set YOUTUBE_TARGET_CHANNEL_ID. " : "Taken from the YOUTUBE_TARGET_CHANNEL_ID Railway variable. ") : h("p", { class: "muted small" }, "Put the channel's ID in YOUTUBE_TARGET_CHANNEL_ID, or use your own channel below."),
          h("div", { class: "row" },
            !yt?.target && yt?.account?.channel_id ? h("button", { class: "btn primary", type: "button", onclick: (e: Event) => busy(e.currentTarget as HTMLButtonElement, async () => { await post("/api/youtube/use-own-channel"); await load(); }, "Now moderating your own channel") }, icon("user", 16), "Moderate my own channel") : null,
            src === "dashboard" ? h("button", { class: "btn ghost", type: "button", onclick: (e: Event) => busy(e.currentTarget as HTMLButtonElement, async () => { await del("/api/settings/youtube_target_channel_id"); await load(); }, "Now using the Railway variable") }, "Use the Railway variable instead") : null)),
          { actions: h("span", { class: `chip ${connected ? "ok" : "warn"}` }, connected ? "Connected" : "Not connected") }),
        card("gauge", "Activity and quota", h("div", { class: "body stack" },
          yt ? h("div", { class: "tiles" },
            h("div", { class: "tile" }, h("div", { class: "muted small" }, "State"), h("strong", null, yt.state), h("div", { class: "muted small" }, `Last poll ${ago(yt.last_poll)}`)),
            h("div", { class: "tile" }, h("div", { class: "muted small" }, "Quota used today"), h("strong", null, `${q!.used} of ${q!.daily}`), h("div", { class: "progress", style: "margin-top:6px" }, h("i", { style: `width:${pct}%;${pct >= 75 ? "background:var(--demo)" : ""}` })))) : null), {}),
        card("lock", "Account", h("div", { class: "body row" },
          h("button", { class: "btn primary", type: "button", onclick: (e: Event) => busy(e.currentTarget as HTMLButtonElement, async () => { const r = await post<{ url: string }>("/api/youtube/oauth/start"); location.href = r.url; }) }, icon("youtube", 16), connected ? "Reconnect Google account" : "Connect Google account"),
          connected ? h("button", { class: "btn ghost", type: "button", onclick: (e: Event) => busy(e.currentTarget as HTMLButtonElement, async () => { await post("/api/youtube/disconnect"); await load(); }, "Disconnected") }, icon("logout", 16), "Disconnect") : null), {}));
    };

    const telegram = (): HTMLElement => {
      const tg = st?.telegram;
      const claimed = s!.telegram_owner_bound;
      const sel = h("select", { "aria-label": "Update delivery" }, [["webhook", "Webhook (recommended)"], ["polling", "Polling"]].map(([v, l]) => h("option", { value: v, selected: tg?.mode === v }, l)));
      sel.onchange = () => busy(sel as unknown as HTMLButtonElement, async () => { await post("/api/telegram/mode", { mode: sel.value }); await load(); }, "Telegram mode changed");
      return h("div", { class: "stack" },
        tg?.last_error ? h("div", { class: "banner error" }, icon("alert", 18), h("span", null, tg.last_error)) : null,
        card("telegram", "Bot", h("div", { class: "body stack" },
          h("div", { class: "tiles" },
            h("div", { class: "tile" }, h("div", { class: "muted small" }, "Bot"), tg?.configured ? h("strong", null, tg.bot_username ? `@${tg.bot_username}` : "Connected") : h("span", { class: "chip warn" }, "No token")),
            h("div", { class: "tile" }, h("div", { class: "muted small" }, "Owner"), claimed ? h("span", { class: "chip ok" }, icon("check", 12), "Claimed") : h("span", { class: "chip warn" }, tg?.configured ? "Not claimed" : "Needs a token"))),
          !tg?.configured ? h("ol", { class: "how" }, h("li", null, "Open @BotFather in Telegram and create a bot."), h("li", null, "Copy the token it gives you."), h("li", null, "Set it as TELEGRAM_BOT_TOKEN in Railway and redeploy."))
            : !claimed ? h("ol", { class: "how" }, h("li", null, `Open @${s!.telegram_bot ?? "your bot"} in Telegram.`), h("li", null, "Send /claim followed by your dashboard password."), h("li", null, "Only your account can use the bot from then on."))
              : h("p", { class: "muted small" }, "Only your Telegram account can control the bot.")),
          { actions: h("span", { class: `chip ${tg?.configured && claimed ? "ok" : "warn"}` }, !tg?.configured ? "No token" : claimed ? "Ready" : "Not claimed") }),
        card("send", "Delivery", h("div", { class: "body stack" },
          h("div", { class: "row" }, h("label", { class: "field", style: "min-width:220px" }, "Update delivery", sel),
            h("button", { class: "btn ghost", type: "button", style: "align-self:end", onclick: (e: Event) => busy(e.currentTarget as HTMLButtonElement, async () => { await post("/api/telegram/test"); }, "Test message sent") }, icon("send", 16), "Send test message")),
          h("p", { class: "muted small" }, tg?.mode === "webhook" ? `Webhook: ${tg.webhook_url || "not registered"}` : `Polling: ${tg?.polling ? "running" : "stopped"}`)), {}));
    };

    const checks = (): HTMLElement => {
      const verifyBody = verifyResult
        ? h("ul", { class: "list", style: "margin:0" }, verifyResult.checks.map((c) => h("li", { class: "row", style: "padding:6px 0;border:0" },
          h("span", { class: `chip ${c.ok === true ? "ok" : c.ok === false ? "bad" : "warn"}` }, icon(c.ok === true ? "check" : c.ok === false ? "alert" : "info", 12), c.ok === true ? "OK" : c.ok === false ? "Fix" : "Unverified"),
          h("span", null, h("strong", null, `${c.label}: `), c.detail))))
        : h("p", { class: "muted small" }, "Not run yet.");
      const diagBody = diagResult
        ? h("div", { class: "stack" },
          h("ul", { class: "list", style: "margin:0" }, diagResult.checks.map((c) => h("li", { class: "row", style: "padding:6px 0;border:0" }, h("span", { class: `chip ${c.ok ? "ok" : "bad"}` }, icon(c.ok ? "check" : "alert", 12), c.ok ? "OK" : "Fix"), h("span", null, c.text)))),
          h("div", { class: "row between nowrap" }, h("span", { style: "min-width:0" }, h("div", { class: "muted small" }, `Client ID the bot sends (${diagResult.client_id_length} characters)`), h("span", { class: "mono", style: "overflow-wrap:anywhere" }, diagResult.client_id || "(empty)")), diagResult.client_id ? copyButton(diagResult.client_id) : null),
          h("div", { class: "row between nowrap" }, h("span", { style: "min-width:0" }, h("div", { class: "muted small" }, "Redirect address the bot sends"), h("span", { class: "mono", style: "overflow-wrap:anywhere" }, diagResult.redirect_uri || "(empty)")), diagResult.redirect_uri ? copyButton(diagResult.redirect_uri) : null),
          h("p", { class: "muted small" }, "Compare both with the SavahBot client in Google Cloud: they must match exactly. The client secret is never shown."),
          h("p", { class: "muted small" }, diagResult.note))
        : h("p", { class: "muted small" }, "Not run yet.");
      return h("div", { class: "stack" },
        card("shield", "Verify moderator access", h("div", { class: "body stack" },
          h("p", { class: "muted small" }, "Asks YouTube what the signed-in account can really do for the target channel. It never deletes or bans anything, and deleting and banning cannot be tested ahead of time, so they show as Unverified until YouTube has answered a real action."), verifyBody), {
          actions: h("button", { class: "btn small primary", type: "button", onclick: (e: Event) => busy(e.currentTarget as HTMLButtonElement, async () => { verifyResult = await post<Verify>("/api/youtube/verify"); drawBody(); }) }, icon("check", 15), "Verify access") }),
        card("lock", "Check the Google connection", h("div", { class: "body" }, diagBody), {
          actions: h("button", { class: "btn small primary", type: "button", onclick: (e: Event) => busy(e.currentTarget as HTMLButtonElement, async () => { diagResult = await get<Diag>("/api/youtube/diagnostics"); drawBody(); }) }, icon("activity", 15), "Run check") }));
    };

    const variables = (): HTMLElement => {
      const all = Object.entries(s!.requirements);
      const missing = all.flatMap(([, i]) => i).filter((i) => !i.set).length;
      return h("div", { class: "stack" },
        h("div", { class: "row between" }, h("div", { class: "seg-control", role: "group", "aria-label": "Show" }, [["All", false], [`Missing${missing ? ` (${missing})` : ""}`, true]].map(([l, v]) =>
          h("button", { type: "button", "aria-pressed": String(onlyMissing === v), onclick: () => { onlyMissing = v as boolean; drawBody(); } }, String(l)))), h("span", { class: "muted small" }, "Everything else already has a safe default. Tap a name to copy it.")),
        ...all.map(([area, items]) => {
          const shown = items.filter((i) => !onlyMissing || !i.set);
          if (!shown.length) return null;
          const setCount = items.filter((i) => i.set).length;
          return card(area === "telegram" ? "telegram" : area === "youtube" ? "youtube" : area === "database" ? "database" : "sliders", AREA_NAMES[area] ?? area,
            h("div", { class: "body row", style: "gap:8px" }, shown.map((i) => h("button", { class: `chip var-chip ${i.set ? "ok" : "warn"}`, type: "button", title: i.set ? "Set. Tap to copy the name." : "Not set. Tap to copy the name.",
              onclick: () => navigator.clipboard?.writeText(i.env).then(() => toast("Copied")).catch(() => toast("Could not copy", "error")) }, icon(i.set ? "check" : "alert", 12), i.env))),
            { actions: h("span", { class: `chip ${setCount === items.length ? "ok" : "warn"}` }, `${setCount} of ${items.length} set`) });
        }),
        onlyMissing && !missing ? h("div", { class: "empty" }, icon("checkCircle", 30), h("span", null, "Nothing is missing.")) : null);
    };

    const drawBody = () => {
      if (!s) return mount(body, h("div", { class: "empty" }, "Loading setup..."));
      const sec = SECTIONS.find((x) => x.id === section)!;
      const view = { overview, addresses, youtube, telegram, checks, variables }[section]();
      mount(body, h("div", { class: "section-head" }, h("span", { class: "ph-icon small" }, icon(sec.icon, 18)), h("div", null, h("h2", null, sec.label), h("p", { class: "muted small" }, sec.blurb))),
        query.get("message") && section === "youtube" ? h("div", { class: `banner ${query.get("youtube") === "error" ? "error" : ""}` }, icon(query.get("youtube") === "error" ? "alert" : "check", 18), h("span", null, query.get("message"))) : null, view);
    };

    const load = async () => {
      const [info, status] = await Promise.all([get<SetupInfo>("/api/setup"), refreshStatus()]);
      s = info; st = status;
      setSetup(info);
      drawNav();
      drawBody();
    };

    mount(root, pageHead("plug", "Setup", "Connect YouTube and Telegram. Each section has its own page; the dot shows what still needs you.",
      h("button", { class: "btn ghost", type: "button", onclick: (e: Event) => busy(e.currentTarget as HTMLButtonElement, load) }, icon("refresh", 16), "Refresh")),
      h("div", { class: "setup-layout" }, nav, body));
    drawNav();
    drawBody();
    void load().catch((e) => toast(e.message, "error"));
  },
};
