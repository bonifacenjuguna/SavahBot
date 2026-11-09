/** Weather settings: places, units and display, refresh and data, alert rules, and what this uses. */
import { del, get, patch, post } from "../api.js";
import { busy, dateTime, h, mount, sheet, toast } from "../dom.js";
import { icon } from "../icons.js";
import { attribution, placePicker, type Place } from "./weather.js";
import { areaNav } from "./kit.js";
import { card, empty, pageHead } from "./shared.js";
import type { Page } from "./types.js";
import { lede, seg } from "./widgets.js";

interface Show { current: boolean; hourly: boolean; daily: boolean; precip: boolean; wind: boolean; sun: boolean; details: boolean }
interface Prefs { temp: "c" | "f"; wind: "kmh" | "ms" | "mph" | "kn"; precip: "mm" | "in"; clock: "12" | "24"; horizon_hours: 12 | 24 | 48 | 72; daily_days: 3 | 5 | 7 | 10 | 14; offer_device_location: boolean; show: Show; refresh: { auto: boolean; minutes: number }; alerts: { enabled: boolean } }
interface Rule { id: number; name: string; kind: "threshold" | "summary"; variable: string; variable_label: string; op: string; threshold: number | null; unit: string; window_hours: number; location_id: number | null; category: string;
  cooldown_minutes: number; every_minutes: number; active_from: string; active_to: string; summary_time: string; enabled: boolean }
interface Catalog { variables: { id: string; label: string; unit: string }[]; ops: string[]; categories: { id: string; label: string }[] }
interface Status { provider: string; commercial: boolean; calls: number; failures: number; paused_until: number | null; redis: boolean; cache_entries: number; locations: { id: number; name: string; last_ok: number | null; last_try: number | null; last_error: string; next: number | null }[] }

const fail = (e: unknown) => toast(e instanceof Error ? e.message : String(e), "error");
const sw = (checked: boolean, label: string, on: (v: boolean) => void) => h("input", { type: "checkbox", class: "switch", checked, "aria-label": label, onchange: (e: Event) => on((e.target as HTMLInputElement).checked) });
const row = (title: string, text: string | null, control: HTMLElement | null) => h("div", { class: "n-row" }, h("div", { class: "n-row-main" }, h("strong", null, title), text ? h("span", { class: "muted small" }, text) : null), control);
const savePrefs = (b: unknown) => patch<Prefs>("/api/weather/prefs", b);
const when = (ts: number | null) => (ts ? dateTime(ts) : "never");

async function locationsCard(el: HTMLElement, prefs: Prefs): Promise<HTMLElement> {
  const r = await get<{ locations: Place[] }>("/api/weather/locations");
  const again = () => void render(el).catch(fail);
  const list = r.locations.length ? h("div", { class: "n-log" }, r.locations.map((l) => h("div", { class: "n-log-row n-dev" },
    h("div", { class: "n-row-main" }, h("strong", null, l.name, l.default ? h("span", { class: "chip ok" }, "default") : null), h("span", { class: "muted small" }, [l.admin1, l.country].filter(Boolean).join(", ") || l.timezone)),
    h("label", { class: "n-chan", title: "Refresh this place automatically and check alert rules for it" }, sw(l.monitor || l.default, `Monitor ${l.name}`, (v) => void patch(`/api/weather/locations/${l.id}`, { monitor: v }).catch(fail)), "Monitor"),
    l.default ? null : h("button", { class: "btn small ghost", type: "button", onclick: () => void post(`/api/weather/locations/${l.id}/default`).then(again).catch(fail) }, icon("star", 14), "Make default"),
    h("button", { class: "btn small ghost", type: "button", "aria-label": `Rename ${l.name}`, onclick: () => { const nm = prompt("Name this place", l.name); if (nm) void patch(`/api/weather/locations/${l.id}`, { name: nm }).then(again).catch(fail); } }, icon("edit", 14)),
    h("button", { class: "btn small ghost", type: "button", "aria-label": `Remove ${l.name}`, onclick: () => { if (confirm(`Remove ${l.name}?`)) void del(`/api/weather/locations/${l.id}`).then(again).catch(fail); } }, icon("trash", 14))))) : empty("mapPin", "No places yet.");
  return card("mapPin", "Places", h("div", null, list, h("div", { style: "padding:12px 14px" }, h("strong", null, "Add a place"), placePicker(again, prefs.offer_device_location))), { flush: true });
}

function displayCard(el: HTMLElement, p: Prefs): HTMLElement {
  const s = <T extends string>(label: string, opts: [T, string][], v: T, key: string) => seg<T>(label, opts.map(([id, l]) => ({ id, label: l })), v, (x) => void savePrefs({ [key]: key === "horizon_hours" || key === "daily_days" ? Number(x) : x }).catch(fail)).el;
  const show = (k: keyof Show, label: string) => row(label, null, sw(p.show[k], label, (v) => void savePrefs({ show: { [k]: v } }).catch(fail)));
  return card("sliders", "Units and display", h("div", { class: "k-stack", style: "padding:6px 14px 12px" },
    row("Temperature", null, s("Temperature unit", [["c", "°C"], ["f", "°F"]], p.temp, "temp")),
    row("Wind speed", null, s("Wind unit", [["kmh", "km/h"], ["ms", "m/s"], ["mph", "mph"], ["kn", "kn"]], p.wind, "wind")),
    row("Rain", null, s("Rain unit", [["mm", "mm"], ["in", "in"]], p.precip, "precip")),
    row("Clock", null, s("Clock", [["24", "24-hour"], ["12", "12-hour"]], p.clock, "clock")),
    row("Hours shown", null, s("Hours shown", [["12", "12"], ["24", "24"], ["48", "48"], ["72", "72"]], String(p.horizon_hours) as "24", "horizon_hours")),
    row("Days shown", null, s("Days shown", [["3", "3"], ["5", "5"], ["7", "7"], ["10", "10"], ["14", "14"]], String(p.daily_days) as "7", "daily_days")),
    h("strong", null, "Show on the Weather page"), show("current", "Current conditions"), show("hourly", "Hourly forecast"), show("daily", "Daily forecast"), show("precip", "Rain"), show("wind", "Wind"), show("sun", "Sunrise and sunset"), show("details", "Humidity, pressure, cloud, visibility"),
    row("Offer \"Use this device's location\"", "Only a button. The browser asks permission when you press it.", sw(p.offer_device_location, "Offer device location", (v) => void savePrefs({ offer_device_location: v }).catch(fail)))), { flush: true });
}

async function refreshCard(el: HTMLElement, p: Prefs): Promise<HTMLElement> {
  const st = await get<Status>("/api/weather/status");
  const mins = h("input", { type: "number", min: 15, max: 180, step: 5, value: p.refresh.minutes, "aria-label": "Refresh every, minutes", style: "width:90px", onchange: (e: Event) => void savePrefs({ refresh: { minutes: Number((e.target as HTMLInputElement).value) } }).then(() => toast("Saved")).catch((x) => { fail(x); void render(el); }) });
  const now = h("button", { class: "btn small", type: "button" }, icon("refresh", 15), "Refresh now") as HTMLButtonElement;
  now.onclick = () => busy(now, async () => { await post("/api/weather/refresh", {}); await render(el); }, "Refreshed");
  return card("refresh", "Refresh and data", h("div", { class: "k-stack", style: "padding:6px 14px 12px" },
    row("Refresh automatically", "Only places you monitor. Forecasts are kept for 15 minutes before a new request is made.", sw(p.refresh.auto, "Auto refresh", (v) => void savePrefs({ refresh: { auto: v } }).catch(fail))),
    row("Every (minutes, 15 to 180)", null, mins),
    ...st.locations.map((l) => row(l.name, `Last updated ${when(l.last_ok)}${l.last_error ? ` · last problem: ${l.last_error}` : ""}${l.next ? ` · next ${when(l.next)}` : ""}`, null)),
    h("div", { class: "row" }, now),
    h("p", { class: "muted small" }, `Provider: ${st.provider}${st.commercial ? " (commercial plan)" : " (free, non-commercial)"} · ${st.calls} requests since start · cache: ${st.redis ? "Redis + memory" : "memory only"}${st.paused_until ? ` · paused until ${when(st.paused_until)} after errors` : ""}`)), { flush: true });
}

async function alertsCard(el: HTMLElement, p: Prefs): Promise<HTMLElement> {
  const [rl, cat, locs] = await Promise.all([get<{ rules: Rule[] }>("/api/weather/rules"), get<Catalog>("/api/weather/catalog"), get<{ locations: Place[] }>("/api/weather/locations")]);
  const again = () => void render(el).catch(fail);
  const edit = (r: Rule | null) => {
    const f = r ?? { id: 0, name: "", kind: "threshold", variable: "precip_probability", variable_label: "", op: ">=", threshold: 70, unit: "%", window_hours: 3, location_id: null, category: "weather.rain", cooldown_minutes: 180, every_minutes: 30, active_from: "", active_to: "", summary_time: "07:00", enabled: true } as Rule;
    const name = h("input", { type: "text", value: f.name, maxlength: 60, "aria-label": "Rule name" }) as HTMLInputElement;
    const variable = h("select", { "aria-label": "What to watch" }, cat.variables.map((v) => h("option", { value: v.id, selected: v.id === f.variable }, `${v.label}${v.unit ? ` (${v.unit})` : ""}`))) as HTMLSelectElement;
    const op = h("select", { "aria-label": "Comparison" }, cat.ops.map((o) => h("option", { value: o, selected: o === f.op }, o))) as HTMLSelectElement;
    const thr = h("input", { type: "number", step: "any", value: f.threshold ?? 0, "aria-label": "Threshold" }) as HTMLInputElement;
    const win = h("input", { type: "number", min: 1, max: 72, value: f.window_hours, "aria-label": "Look ahead, hours" }) as HTMLInputElement;
    const cats = h("select", { "aria-label": "Notification category" }, cat.categories.map((c) => h("option", { value: c.id, selected: c.id === f.category }, c.label))) as HTMLSelectElement;
    const where = h("select", { "aria-label": "Place" }, h("option", { value: "" }, "Default place"), locs.locations.map((l) => h("option", { value: l.id, selected: l.id === f.location_id }, l.name))) as HTMLSelectElement;
    const cool = h("input", { type: "number", min: 15, max: 10080, value: f.cooldown_minutes, "aria-label": "Cooldown, minutes" }) as HTMLInputElement;
    const every = h("input", { type: "number", min: 15, max: 1440, value: f.every_minutes, "aria-label": "Check every, minutes" }) as HTMLInputElement;
    const from = h("input", { type: "time", value: f.active_from, "aria-label": "Active from" }) as HTMLInputElement;
    const to = h("input", { type: "time", value: f.active_to, "aria-label": "Active until" }) as HTMLInputElement;
    const at = h("input", { type: "time", value: f.summary_time, "aria-label": "Summary time" }) as HTMLInputElement;
    const lab = (t: string, c: HTMLElement) => h("label", { class: "k-field" }, h("span", { class: "muted small" }, t), c);
    const body = h("div", { class: "k-stack" }, lab("Name", name), lab("Place", where),
      f.kind === "threshold" ? [lab("Watch", variable), h("div", { class: "row wrap" }, lab("When", op), lab("Value", thr), lab("Within next (hours)", win))] : lab("Send at", at),
      lab("Notification category", cats), h("div", { class: "row wrap" }, lab("Check every (min)", every), lab("Repeat no sooner than (min)", cool)),
      f.kind === "threshold" ? h("div", { class: "row wrap" }, lab("Only between", from), lab("and", to)) : null,
      h("p", { class: "muted small" }, "Quiet hours and push settings from Notifications still apply. Alerts come from SavahBot's own reading of the forecast. They are not official weather warnings."));
    const save = h("button", { class: "btn primary", type: "button" }, "Save rule") as HTMLButtonElement;
    const sh = sheet(r ? "Edit rule" : "New rule", h("div", { class: "k-stack" }, body, save));
    save.onclick = () => busy(save, async () => {
      const b: Record<string, unknown> = { name: name.value, category: cats.value, location_id: where.value ? Number(where.value) : null, every_minutes: Number(every.value), cooldown_minutes: Number(cool.value), kind: f.kind };
      if (f.kind === "threshold") Object.assign(b, { variable: variable.value, op: op.value, threshold: Number(thr.value), window_hours: Number(win.value), active_from: from.value, active_to: to.value });
      else b.summary_time = at.value;
      await (r ? patch(`/api/weather/rules/${r.id}`, b) : post("/api/weather/rules", b));
      sh.close(); again();
    });
  };
  const describe = (r: Rule) => (r.kind === "summary" ? `Every day at ${r.summary_time}` : `${r.variable_label} ${r.op} ${r.threshold}${r.unit ? " " + r.unit : ""} within ${r.window_hours} h`);
  return card("bell", "Weather alerts", h("div", null, h("div", { style: "padding:6px 14px" },
    row("Send weather alerts", "They arrive through Notifications, so quiet hours, pause and push devices all apply.", sw(p.alerts.enabled, "Weather alerts", (v) => void savePrefs({ alerts: { enabled: v } }).catch(fail))),
    h("p", { class: "small" }, h("a", { href: "#/notifications?tab=categories" }, "Choose which weather alerts push, ring the bell or message Telegram"))),
  h("div", { class: "n-log" }, rl.rules.map((r) => h("div", { class: "n-log-row n-dev" }, h("div", { class: "n-row-main" }, h("strong", null, r.name), h("span", { class: "muted small" }, describe(r))),
    sw(r.enabled, `Enable ${r.name}`, (v) => void patch(`/api/weather/rules/${r.id}`, { enabled: v }).catch(fail)),
    h("button", { class: "btn small ghost", type: "button", "aria-label": `Edit ${r.name}`, onclick: () => edit(r) }, icon("edit", 14)),
    h("button", { class: "btn small ghost", type: "button", "aria-label": `Delete ${r.name}`, onclick: () => { if (confirm(`Delete ${r.name}?`)) void del(`/api/weather/rules/${r.id}`).then(again).catch(fail); } }, icon("trash", 14))))),
  h("div", { style: "padding:12px 14px" }, h("button", { class: "btn", type: "button", onclick: () => edit(null) }, icon("plus", 15), "New rule"))), { flush: true });
}

async function render(el: HTMLElement): Promise<void> {
  const p = await get<Prefs>("/api/weather/prefs");
  const [loc, disp, refr, alerts] = await Promise.all([locationsCard(el, p), Promise.resolve(displayCard(el, p)), refreshCard(el, p), alertsCard(el, p)]);
  const at = await get<{ attribution: { text: string; url: string; license: string; note: string } }>("/api/weather/overview").catch(() => ({ attribution: { text: "Weather data by Open-Meteo.com", url: "https://open-meteo.com/", license: "CC BY 4.0", note: "" } }));
  mount(el, loc, disp, refr, alerts, attribution(at));
}

export const weatherSettings: Page = {
  id: "weather-settings", title: "Weather settings", icon: "sliders", blurb: "Places, units, refresh and alerts",
  render(root) {
    const body = h("div", { class: "k-stack" }, h("p", { class: "muted" }, "Loading…"));
    mount(root, h("div", { class: "page" }, areaNav("weather"), pageHead("cloudSun", "Weather settings", "Places, units, refresh and alerts.", h("a", { class: "btn small", href: "#/weather" }, icon("cloudSun", 15), "Back to Weather")), lede("Weather comes from Open-Meteo through your SavahBot server. No key is needed."), body));
    void render(body).catch((e) => { fail(e); mount(body, empty("alert", "Settings could not load.")); });
  },
};
