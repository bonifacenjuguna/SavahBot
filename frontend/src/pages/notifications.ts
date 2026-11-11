/** Notification Centre: what reaches you, where, and when. Push (Firebase), the in-app bell and Telegram share these settings. */
import { folded } from "../nav.js";
import { del, get, patch, post } from "../api.js";
import { busy, dateTime, h, mount, toast } from "../dom.js";
import { icon, statusIcon } from "../icons.js";
import { disablePush, enablePush, pushState, type PushConfig, type PushState } from "../push.js";
import { openNotification, refresh as refreshBell } from "../notifications.js";
import { areaNav, dateRange, type RangeValue } from "./kit.js";
import { card, empty, pageHead } from "./shared.js";
import type { Page } from "./types.js";
import { figures, lede, seg } from "./widgets.js";

type Chan = "push" | "inapp" | "telegram";
interface Eff { enabled: boolean; push: boolean; inapp: boolean; telegram: boolean; priority: string }
interface Cat { id: string; group: string; group_label: string; label: string; description: string; icon: string; kind: string; priority: string; telegram_native: boolean; effective: Eff }
interface Prefs { enabled: boolean; push: boolean; inapp: boolean; telegram: boolean; hide_body_locked: boolean; pause_until: number; paused: boolean; quiet_now: boolean; quiet_ends: number | null;
  quiet: { enabled: boolean; start: string; end: string; mode: "hold" | "silent"; critical_breaks: boolean } }
interface Device { id: number; label: string; platform: string; browser: string; installed: boolean; created: number; last_seen: number; last_ok: number | null; last_error: string; fail_count: number; enabled: boolean }
interface Row { id: number; ts: number; category: string; label: string; title: string; body: string; route: string; priority: string; kind: string; icon: string; count: number; read: boolean }
interface Stats { days: number; total: number; by_category: { category: string; label: string; count: number; read: number }[]; per_day: { day: string; count: number }[]; deliveries: Record<string, number>; success_rate: number | null }
interface Log { id: number; created: number; status: string; attempts: number; error: string; category: string; priority: string; device: string | null; title: string | null }

const fail = (e: unknown) => toast(e instanceof Error ? e.message : String(e), "error");
const PRIORITY = [["low", "Low"], ["normal", "Normal"], ["high", "High"], ["critical", "Critical"]] as const;
const TABS = [{ id: "overview", label: "Overview", icon: "bell" }, { id: "categories", label: "Categories", icon: "checklist" }, { id: "delivery", label: "Delivery", icon: "send" },
  { id: "schedule", label: "Schedule", icon: "moon" }, { id: "stats", label: "Stats", icon: "chart" }, { id: "history", label: "History", icon: "clock" }, { id: "devices", label: "Devices", icon: "smartphone" }] as const;
type Tab = (typeof TABS)[number]["id"];

const sw = (checked: boolean, label: string, on: (v: boolean) => void, disabled = false) =>
  h("input", { type: "checkbox", class: "switch", checked, disabled, "aria-label": label, onchange: (e: Event) => on((e.target as HTMLInputElement).checked) });
const row = (title: string, text: string | null, control: HTMLElement | null) =>
  h("div", { class: "n-row" }, h("div", { class: "n-row-main" }, h("strong", null, title), text ? h("span", { class: "muted small" }, text) : null), control);
const savePrefs = (body: unknown) => patch<Prefs>("/api/notify/prefs", body);
const clock = (ts: number) => new Date(ts * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });

// ------------------------------------------------------------------ overview
async function overview(el: HTMLElement): Promise<void> {
  const [cfg, prefs, devs, inbox] = await Promise.all([get<PushConfig>("/api/notify/config"), get<Prefs>("/api/notify/prefs"), get<{ devices: Device[] }>("/api/notify/devices"), get<{ unread: number }>("/api/notify/unread")]);
  const state: PushState = await pushState(cfg);
  const paint = () => void overview(el).catch(fail);
  const deviceCard = (() => {
    let body: HTMLElement;
    const msg = (t: string) => h("p", { class: "muted small" }, t);
    if (state.kind === "unsupported" || state.kind === "needs-install") body = h("div", { class: "k-stack" }, msg(state.why), h("p", { class: "muted small" }, "docs/PWA_AND_PUSH_PLATFORMS.md lists what each phone and browser can do."));
    else if (state.kind === "not-configured") body = h("div", { class: "k-stack" }, msg("Push is not set up on the server yet. Add the Firebase values below, redeploy, and this button appears. The in-app bell and Telegram work without it."));
    else if (state.kind === "blocked") body = msg("Notifications are blocked for this site in your browser. Open the site settings (the lock icon beside the address), allow Notifications, then reload.");
    else {
      const on = state.kind === "on";
      const b = h("button", { class: on ? "btn" : "btn primary", type: "button" }, icon(on ? "bellOff" : "bell", 16), on ? "Turn off on this device" : "Turn on push on this device") as HTMLButtonElement;
      b.onclick = () => busy(b, async () => { try { if (on) await disablePush(cfg); else await enablePush(cfg); paint(); } catch (e) { fail(e); } });
      const t = h("button", { class: "btn", type: "button", disabled: !devs.devices.length }, icon("send", 16), "Send a test") as HTMLButtonElement;
      t.onclick = () => busy(t, async () => {
        const r = await post<{ ok: boolean; results: { device: string; status: string; error: string }[]; problems: string[] }>("/api/notify/test", {});
        toast(r.ok ? "Test sent. Check your device." : r.problems[0] ?? r.results.map((x) => `${x.device}: ${x.error || x.status}`).join("; "), r.ok ? "ok" : "error");
        paint();
      });
      body = h("div", { class: "k-stack" }, msg(on ? "This device will get push messages." : "The browser will ask for permission when you press the button."), h("div", { class: "row wrap" }, b, t));
    }
    return card("smartphone", "This device", h("div", { style: "padding:12px 14px" }, body), { flush: true });
  })();
  const setup = card("checklist", "Firebase setup", h("div", { class: "k-stack", style: "padding:12px 14px" },
    lede(cfg.push_ready && cfg.web_ready ? "Everything needed is set. Use the check to confirm Google accepts the service account." : "Set these variables on your host (Railway), then redeploy. docs/NOTIFICATIONS.md walks through where each one comes from."),
    h("div", { class: "n-checks" }, cfg.checklist.map((c) => h("span", { class: `chip ${c.set ? "ok" : "warn"}` }, statusIcon(c.set ? "ok" : "warn", 15), c.name))),
    h("div", { class: "row" }, ((): HTMLButtonElement => {
      const b = h("button", { class: "btn small", type: "button", disabled: !cfg.push_ready }, icon("shield", 15), "Check the service account") as HTMLButtonElement;
      b.onclick = () => busy(b, async () => { const r = await post<{ ok: boolean; problems: string[] }>("/api/notify/check"); toast(r.ok ? "Google accepted the service account." : r.problems[0], r.ok ? "ok" : "error"); });
      return b;
    })())), { flush: true });
  const pause = (m: number | null, label: string) => h("button", { class: "btn small", type: "button", onclick: (e: Event) => void busy(e.currentTarget as HTMLButtonElement, async () => { await post("/api/notify/pause", { minutes: m }); paint(); }) }, label);
  const controls = card("sliders", "Switches", h("div", { class: "k-stack", style: "padding:6px 14px 12px" },
    row("Notifications", "Master switch. Off means nothing is created at all.", sw(prefs.enabled, "Notifications", (v) => void savePrefs({ enabled: v }).then(paint).catch(fail))),
    row("Push to devices", null, sw(prefs.push, "Push", (v) => void savePrefs({ push: v }).catch(fail))),
    row("In-app bell and history", null, sw(prefs.inapp, "In-app", (v) => void savePrefs({ inapp: v }).catch(fail))),
    row("Telegram", "Only for events Telegram does not already report itself.", sw(prefs.telegram, "Telegram", (v) => void savePrefs({ telegram: v }).catch(fail))),
    row("Pop-up messages on screen", "The small \"Saved\" and error messages. Turn off, move to the top or change how long they stay.", h("a", { class: "btn small", href: "#/settings?tab=appearance" }, "Appearance")),
    row("Pause push", prefs.paused ? `Paused until ${clock(prefs.pause_until)}. Critical alerts still come through.` : prefs.quiet_now ? `Quiet hours until ${prefs.quiet_ends ? clock(prefs.quiet_ends) : "later"}.` : "Silence push for a while. The bell keeps filling.",
      h("div", { class: "row wrap" }, prefs.paused ? pause(null, "Resume") : [pause(15, "15 min"), pause(60, "1 hour"), pause(480, "8 hours"), pause(minsToMorning(), "Until morning")]))), { flush: true });
  mount(el, figures([{ value: String(inbox.unread), label: "unread", tone: inbox.unread ? "warn" : "" }, { value: String(devs.devices.filter((d) => d.enabled).length), label: "push devices", tone: devs.devices.length ? "ok" : "" }, { value: prefs.paused ? "paused" : prefs.quiet_now ? "quiet" : "active", label: "right now", tone: prefs.paused || prefs.quiet_now ? "warn" : "ok" }]), deviceCard, controls, setup);
}

// ------------------------------------------------------------------ categories
/** Minutes from now until 07:00 (tomorrow if it is already past), for "Until morning". */
function minsToMorning(): number {
  const t = new Date(); t.setHours(7, 0, 0, 0);
  if (t.getTime() <= Date.now() + 60_000) t.setDate(t.getDate() + 1);
  return Math.round((t.getTime() - Date.now()) / 60_000);
}

async function categories(el: HTMLElement): Promise<void> {
  const r = await get<{ groups: Record<string, string>; items: Cat[] }>("/api/notify/categories");
  const groups = [...new Set(r.items.map((i) => i.group))];
  const save = (id: string, body: Partial<Eff>) => void savePrefs({ categories: { [id]: body } }).catch(fail);
  const preset = (label: string, hint: string, pick: (c: Cat) => Partial<Eff>) => h("button", { class: "btn small", type: "button", title: hint, onclick: (e: Event) => void busy(e.currentTarget as HTMLButtonElement, async () => {
    await savePrefs({ categories: Object.fromEntries(r.items.filter((i) => i.group !== "test").map((i) => [i.id, pick(i)])) }); toast("Applied"); void categories(el).catch(fail);
  }) }, label);
  const urgent = (c: Cat) => c.group === "security" || c.effective.priority === "high" || c.effective.priority === "critical";
  const presets = card("sliders", "Quick presets", h("div", { style: "padding:6px 14px 12px" },
    h("p", { class: "muted small" }, "Change every kind at once. You can still adjust each one below."),
    h("div", { class: "row wrap", style: "gap:8px" },
      preset("Essentials only", "Only security and urgent kinds stay on", (c) => ({ enabled: urgent(c) })),
      preset("No push, bell only", "Keep everything in the bell but stop push", (c) => ({ push: false })),
      preset("Everything on", "Turn every kind back on", () => ({ enabled: true })))), { flush: true });
  mount(el, presets, ...groups.filter((g) => g !== "test").map((g) => card(null, r.groups[g] ?? g, h("div", { class: "k-stack", style: "padding:6px 14px 12px" }, r.items.filter((i) => i.group === g).map((c) => {
    const chan = (k: Chan, label: string, disabled = false, hint = "") => h("label", { class: "n-chan", title: hint }, sw(c.effective[k], `${c.label}: ${label}`, (v) => { c.effective[k] = v; save(c.id, { [k]: v }); }, disabled), label);
    const prio = h("select", { "aria-label": `${c.label} priority`, onchange: (e: Event) => save(c.id, { priority: (e.target as HTMLSelectElement).value }) }, PRIORITY.map(([v, l]) => h("option", { value: v, selected: v === c.effective.priority }, l)));
    return h("div", { class: "n-cat" }, h("div", { class: "n-row" },
      h("div", { class: "n-row-main" }, h("strong", null, icon(c.icon, 15), " ", c.label), h("span", { class: "muted small" }, c.description)),
      sw(c.effective.enabled, `Enable ${c.label}`, (v) => { c.effective.enabled = v; save(c.id, { enabled: v }); })),
      h("div", { class: "row wrap n-chans" }, chan("push", "Push"), chan("inapp", "Bell"), chan("telegram", "Telegram", c.telegram_native, c.telegram_native ? "Telegram already reports this through its own settings." : ""), prio));
  })), { flush: true })));
}

// ------------------------------------------------------------------ delivery
async function delivery(el: HTMLElement): Promise<void> {
  const [prefs, log] = await Promise.all([get<Prefs>("/api/notify/prefs"), get<{ items: Log[] }>("/api/notify/log")]);
  mount(el,
    card("lock", "On a locked screen", h("div", { style: "padding:6px 14px 12px" }, row("Hide message text", "Push shows only the title. Security alerts always hide their text.", sw(prefs.hide_body_locked, "Hide text", (v) => void savePrefs({ hide_body_locked: v }).catch(fail)))), { flush: true }),
    card("send", "Recent deliveries", log.items.length ? h("div", { class: "n-log" }, folded(log.items, (d) => h("div", { class: "n-log-row" },
      h("span", { class: `chip ${d.status === "sent" ? "ok" : d.status === "failed" || d.status === "dead" ? "bad" : "warn"}` }, d.status),
      h("div", { class: "n-row-main" }, h("strong", null, d.title ?? d.category), h("span", { class: "muted small" }, `${d.device ?? "device removed"} · ${dateTime(d.created)}${d.attempts > 1 ? ` · ${d.attempts} tries` : ""}${d.error ? ` · ${d.error}` : ""}`))), { noun: "deliveries", title: "Recent deliveries", initial: 6, text: (d) => `${d.title ?? d.category} ${d.status} ${d.device ?? ""}` })) : empty("send", "Nothing has been pushed yet."), { flush: true }));
}

// ------------------------------------------------------------------ schedule
async function schedule(el: HTMLElement): Promise<void> {
  const p = await get<Prefs>("/api/notify/prefs");
  const q = p.quiet;
  const time = (v: string, label: string, key: "start" | "end") => h("input", { type: "time", value: v, "aria-label": label, onchange: (e: Event) => void savePrefs({ quiet: { [key]: (e.target as HTMLInputElement).value } }).catch(fail) });
  const mode = seg<"hold" | "silent">("During quiet hours", [{ id: "hold", label: "Hold and summarise" }, { id: "silent", label: "No push at all" }], q.mode, (v) => void savePrefs({ quiet: { mode: v } }).catch(fail));
  mount(el, card("moon", "Quiet hours", h("div", { class: "k-stack", style: "padding:12px 14px" },
    lede("Use your own time zone (set under Settings). During quiet hours the bell still fills; only push is affected."),
    row("Use quiet hours", p.quiet_now ? `Quiet now, until ${p.quiet_ends ? clock(p.quiet_ends) : "later"}.` : null, sw(q.enabled, "Quiet hours", (v) => void savePrefs({ quiet: { enabled: v } }).catch(fail))),
    h("div", { class: "row wrap" }, h("label", { class: "n-time" }, "From ", time(q.start, "Quiet hours start", "start")), h("label", { class: "n-time" }, "Until ", time(q.end, "Quiet hours end", "end"))),
    mode.el,
    h("p", { class: "muted small" }, "Hold: push messages wait and arrive together as one summary when quiet hours end."),
    row("Let critical alerts through", "Security alerts can still wake you. Everything else waits.", sw(q.critical_breaks, "Critical breaks quiet hours", (v) => void savePrefs({ quiet: { critical_breaks: v } }).catch(fail)))), { flush: true }));
}

// ------------------------------------------------------------------ stats
async function stats(el: HTMLElement, days = 7): Promise<void> {
  const s = await get<Stats>(`/api/notify/stats?days=${days}`);
  const max = Math.max(1, ...s.per_day.map((d) => d.count));
  const range = seg<"7" | "30" | "90">("Range", [{ id: "7", label: "7 days" }, { id: "30", label: "30 days" }, { id: "90", label: "90 days" }], String(days) as "7", (v) => void stats(el, Number(v)).catch(fail));
  const d = s.deliveries;
  mount(el, h("div", { class: "row wrap" }, range.el),
    figures([{ value: String(s.total), label: `notifications in ${days} days` }, { value: String(d.sent ?? 0), label: "pushes sent", tone: "ok" }, { value: String((d.failed ?? 0) + (d.dead ?? 0)), label: "push failures", tone: (d.failed ?? 0) + (d.dead ?? 0) ? "bad" : "" },
      { value: s.success_rate === null ? "n/a" : `${Math.round(s.success_rate * 100)}%`, label: "delivery success" }]),
    card("chart", "Per day", h("div", { class: "n-bars", role: "img", "aria-label": `Notifications per day, highest ${max}` }, s.per_day.map((x) => h("span", { class: "n-bar", title: `${x.day}: ${x.count}`, style: `height:${Math.max(3, Math.round((x.count / max) * 100))}%` }))), { flush: true }),
    card("checklist", "By category", s.by_category.length ? h("div", { class: "n-log" }, s.by_category.map((c) => h("div", { class: "n-log-row" }, h("strong", { class: "grow" }, c.label), h("span", { class: "muted small" }, `${c.read} read`), h("span", { class: "chip" }, String(c.count))))) : empty("chart", "No notifications in this period."), { flush: true }));
}

// ------------------------------------------------------------------ history
function history(el: HTMLElement): void {
  let range: RangeValue = { label: "", active: false };
  let category = "", onlyUnread = false;
  const list = h("div", { class: "n-log" });
  const more = h("button", { class: "btn small", type: "button", hidden: true }, "Load older") as HTMLButtonElement;
  let last = 0;
  const q = (before?: number) => `/api/notify/inbox?limit=40${before ? `&before=${before}` : ""}${category ? `&category=${category}` : ""}${onlyUnread ? "&unread=1" : ""}${range.since !== undefined ? `&since=${Math.floor(range.since)}` : ""}${range.until !== undefined ? `&until=${Math.floor(range.until)}` : ""}`;
  const line = (n: Row) => h("a", { class: `n-hist ${n.kind}${n.read ? "" : " unread"}`, href: n.route }, icon(n.icon, 18),
    h("div", { class: "n-row-main" }, h("strong", null, n.title, n.count > 1 ? ` (${n.count})` : ""), n.body ? h("span", { class: "muted small" }, n.body) : null, h("span", { class: "muted small" }, `${n.label} · ${dateTime(n.ts)}`)),
    h("button", { class: "btn small ghost", type: "button", "aria-label": "Delete", onclick: (e: Event) => { e.preventDefault(); void post("/api/notify/delete", { ids: [n.id] }).then(() => { (e.currentTarget as HTMLElement).closest(".n-hist")?.remove(); void refreshBell(); }).catch(fail); } }, icon("trash", 14)));
  async function load(append = false): Promise<void> {
    const r = await get<{ items: Row[]; more: boolean }>(q(append ? last : undefined));
    last = r.items.length ? r.items[r.items.length - 1].ts : last;
    const rows = r.items.map(line);
    if (!append) mount(list, rows.length ? rows : empty("clock", "Nothing here."));
    else list.append(...rows);
    more.hidden = !r.more;
  }
  more.onclick = () => busy(more, () => load(true).catch(fail));
  const cat = h("select", { "aria-label": "Category", onchange: (e: Event) => { category = (e.target as HTMLSelectElement).value; void load().catch(fail); } }, h("option", { value: "" }, "All categories"));
  void get<{ groups: Record<string, string>; items: Cat[] }>("/api/notify/categories").then((r) => Object.entries(r.groups).filter(([g]) => g !== "test").forEach(([g, l]) => cat.append(h("option", { value: g }, l))));
  const un = seg<"all" | "unread">("Show", [{ id: "all", label: "All" }, { id: "unread", label: "Unread" }], "all", (v) => { onlyUnread = v === "unread"; void load().catch(fail); });
  const dates = dateRange({ presets: ["any", "today", "yesterday", "7d", "30d", "custom"], label: "History dates" }, (v) => { range = v; void load().catch(fail); });
  mount(el, h("div", { class: "row wrap" }, un.el, cat), dates.el, list, h("div", { class: "row" }, more));
  void load().catch(fail);
}

// ------------------------------------------------------------------ devices
async function devices(el: HTMLElement): Promise<void> {
  const r = await get<{ devices: Device[] }>("/api/notify/devices");
  const paint = () => void devices(el).catch(fail);
  mount(el, card("smartphone", "Devices that get push", r.devices.length ? h("div", { class: "n-log" }, r.devices.map((d) => h("div", { class: "n-log-row n-dev" },
    h("div", { class: "n-row-main" }, h("strong", null, d.label, d.installed ? h("span", { class: "chip" }, "installed app") : null),
      h("span", { class: "muted small" }, `${d.platform} · ${d.browser} · added ${dateTime(d.created)}`),
      h("span", { class: `small ${d.last_error ? "bad-text" : "muted"}` }, d.last_error ? `Last problem: ${d.last_error}` : d.last_ok ? `Last delivered ${dateTime(d.last_ok)}` : "Nothing delivered yet")),
    sw(d.enabled, `Send push to ${d.label}`, (v) => void patch(`/api/notify/devices/${d.id}`, { enabled: v }).catch(fail)),
    h("button", { class: "btn small ghost", type: "button", "aria-label": `Rename ${d.label}`, onclick: () => { const n = prompt("Name this device", d.label); if (n) void patch(`/api/notify/devices/${d.id}`, { label: n }).then(paint).catch(fail); } }, icon("edit", 14)),
    h("button", { class: "btn small ghost", type: "button", "aria-label": `Forget ${d.label}`, onclick: () => { if (confirm(`Stop sending push to ${d.label}?`)) void del(`/api/notify/devices/${d.id}`).then(paint).catch(fail); } }, icon("trash", 14))))) : empty("smartphone", "No device yet. Turn on push from the Overview tab."), { flush: true }),
    h("p", { class: "muted small" }, "Device tokens are stored encrypted and are never shown here or in backups."));
}

export const notifications: Page = {
  id: "notifications", title: "Notifications", icon: "bell", blurb: "Push, bell, Telegram, quiet hours and history",
  render(root, query) {
    let tab = (TABS.find((t) => t.id === query.get("tab"))?.id ?? (query.get("open") ? "history" : "overview")) as Tab;
    const body = h("div", { class: "k-stack" });
    const tabs = seg<Tab>("Notification sections", TABS.map((t) => ({ id: t.id, label: t.label, icon: t.icon })), tab, (v) => { tab = v; show(); });
    const show = () => {
      const run: Record<Tab, (el: HTMLElement) => Promise<void> | void> = { overview, categories, delivery, schedule, stats: (e) => stats(e), history, devices };
      mount(body, h("p", { class: "muted" }, "Loading…"));
      const inner = h("div", { class: "k-stack" });
      Promise.resolve(run[tab](inner)).then(() => mount(body, inner)).catch((e) => { fail(e); mount(body, empty("alert", "This section could not load.")); });
    };
    mount(root, h("div", { class: "page" }, areaNav("notifications"), pageHead("bell", "Notifications", "Choose what reaches you, where, and when."), h("div", { class: "tab-row" }, tabs.el), body));
    show();
    const wanted = Number(query.get("open"));
    if (Number.isInteger(wanted) && wanted > 0) void openNotification(wanted);     // a tap on a notification lands here and shows that notification
  },
};
