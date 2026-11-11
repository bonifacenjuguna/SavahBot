/** Settings landing page: what needs attention, a card for every area with status that was actually checked, and search. */
import { get } from "../api.js";
import { dateTime, h, mount } from "../dom.js";
import { icon, statusIcon } from "../icons.js";
import { INDEX, GROUPS, recents, remember, search, type Entry } from "./settings-index.js";
import { card, empty } from "./shared.js";
import { href as routeHref } from "../router.js";

interface Overview {
  security: { methods: number; enforced: boolean; totp: boolean; passkeys: number; recovery_left: number; lockdown: boolean; sessions: number };
  notifications: { push_ready: boolean; devices: number; unread: number; enabled: boolean; paused: boolean; quiet_enabled: boolean };
  weather: { location: string | null; alerts: boolean; units: string };
  backup: { last_export: number | null };
  integrations: { youtube: { connected: boolean; error: string; quota_fraction: number }; telegram: { configured: boolean; owner_bound: boolean; error: string }; firebase: { configured: boolean } };
  attention: { level: "bad" | "warn" | "info"; text: string; route: string }[];
  system: { db: string; redis: string; version: string; mode: string };
}
type Tone = "ok" | "warn" | "bad" | "";
const dot = (t: Tone, text: string) => h("span", { class: `chip ${t}` }, text);

function tile(ic: string, title: string, text: string, route: string, status: HTMLElement | null, id: string): HTMLElement {
  return h("a", { class: "set-tile", href: route, onclick: () => remember(id) }, h("span", { class: "set-ic" }, icon(ic, 22)), h("span", { class: "set-main" }, h("strong", null, title), h("span", { class: "muted small" }, text)), status);
}

function result(e: Entry): HTMLElement {
  return h("a", { class: "set-hit", href: routeHref(e.route), onclick: () => remember(e.id) }, icon(e.icon, 18), h("span", { class: "set-main" }, h("strong", null, e.title), h("span", { class: "muted small" }, e.text)),
    h("span", { class: "chip" }, GROUPS.find((g) => g.id === e.group)?.title ?? ""));
}

export async function renderOverview(el: HTMLElement): Promise<void> {
  const o = await get<Overview>("/api/settings/overview");
  const s = o.security, n = o.notifications, i = o.integrations;
  const results = h("div", { class: "k-stack", role: "region", "aria-live": "polite", "aria-label": "Search results" });
  const input = h("input", { type: "search", placeholder: "Search settings: try “quiet hours”, “backup”, “accent”…", "aria-label": "Search settings", autocomplete: "off" }) as HTMLInputElement;
  const base = h("div", { class: "k-stack" });
  const showSearch = () => {
    const q = input.value.trim();
    base.hidden = q.length > 0;
    if (!q) { mount(results); return; }
    const hits = search(q);
    mount(results, hits.length ? hits.map(result) : empty("search", `Nothing matches “${q}”. Try another word, or open All environment settings.`),
      h("a", { class: "btn small", href: `/settings?tab=all&q=${encodeURIComponent(q)}` }, icon("sliders", 15), "Search every environment setting too"));
  };
  input.oninput = showSearch;
  const attention = o.attention.length ? card("alert", `Needs a look (${o.attention.length})`, h("div", { class: "n-log" }, o.attention.map((a) => h("a", { class: `n-hist ${a.level === "bad" ? "bad" : a.level === "warn" ? "warn" : "info"}`, href: routeHref(a.route) },
    statusIcon(a.level === "info" ? "info" : a.level === "bad" ? "bad" : "warn", 20), h("span", { class: "set-main" }, a.text), icon("chevronRight", 16)))), { flush: true })
    : card("check", "All clear", h("p", { style: "padding:12px 14px" }, "Nothing needs attention right now."), { flush: true });
  const yt: [Tone, string] = i.youtube.connected ? (i.youtube.error ? ["warn", "problem"] : ["ok", "connected"]) : ["", "not connected"];
  const tg: [Tone, string] = i.telegram.configured ? (i.telegram.error ? ["warn", "problem"] : i.telegram.owner_bound ? ["ok", "linked"] : ["warn", "not claimed"]) : ["", "not set up"];
  const tiles = h("div", { class: "set-grid" },
    tile("shield", "Security & access", "Sign-in methods, devices, recovery, lockdown.", "/security", dot(s.lockdown ? "bad" : s.enforced ? "ok" : "warn", s.lockdown ? "lockdown" : s.enforced ? `${s.methods} methods` : "password only"), "sec-methods"),
    tile("bell", "Notifications", "Push, bell, quiet hours, history.", "/notifications", dot(!n.enabled ? "" : n.devices ? "ok" : "warn", !n.enabled ? "off" : n.paused ? "paused" : n.devices ? `${n.devices} device${n.devices === 1 ? "" : "s"}` : "no push device"), "n-push"),
    tile("plug", "Integrations", "YouTube, Telegram, push service.", "/setup", dot(yt[0], `YouTube ${yt[1]}`), "i-youtube"),
    tile("send", "Telegram", "Your private control panel.", "/setup", dot(tg[0], tg[1]), "i-telegram"),
    tile("shield", "Moderation & automation", "Rules, bans, knowledge, commands.", "/moderation", null, "m-mod"),
    tile("volume", "Chat reader", "Read chat aloud, voices, voice packs.", "/reader", null, "i-reader"),
    tile("radio", "Stream alerts", "Likes, viewers, subscribers, members.", "/stream-settings", null, "i-stream"),
    tile("checklist", "Activity log", "What changed, by importance and area.", "/activity", null, "s-activity"),
    tile("sparkle", "Variables", "Your own $(names) for links and text.", "/variables", null, "m-vars"),
    tile("cloudSun", "Weather & location", "Places, units, alerts.", "/weather-settings", dot(o.weather.location ? "ok" : "", o.weather.location ?? "no place"), "w-places"),
    tile("sparkle", "Appearance", "Theme, accent, density, text size.", "/settings?tab=appearance", null, "a-theme"),
    tile("database", "Privacy & data", "What is stored and for how long.", "/settings?tab=privacy", null, "p-data"),
    tile("database", "Backup & recovery", "Encrypted export and restore.", "/backup", dot(o.backup.last_export ? "ok" : "warn", o.backup.last_export ? `last ${dateTime(o.backup.last_export).split(",")[0]}` : "never exported"), "b-export"),
    tile("smartphone", "Device & app", "Install, offline, this browser.", "/settings?tab=device", null, "d-install"),
    tile("gauge", "Developer & advanced", "Health, config check, all variables.", "/settings?tab=developer", dot("", `${o.system.db}${o.system.redis === "redis" ? " + redis" : ""}`), "x-health"));
  const rec = recents().map((id) => INDEX.find((e) => e.id === id)).filter((e): e is Entry => Boolean(e));
  mount(base, attention, tiles, rec.length ? card("clock", "Recently opened", h("div", { class: "k-stack", style: "padding:8px 14px 12px" }, rec.map(result)), { flush: true }) : null,
    h("p", { class: "muted small" }, `SavahBot ${o.system.version} · ${o.system.mode} mode · stored in ${o.system.db}. Only facts that were checked are shown as status.`));
  mount(el, h("div", { class: "input-icon" }, icon("search", 16), input), results, base);
}
