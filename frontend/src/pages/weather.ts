/** Weather dashboard: current conditions, the next hours, the coming days. Data comes from SavahBot's backend (Open-Meteo), never straight from the browser. */
import { get, post } from "../api.js";
import { busy, h, mount, toast } from "../dom.js";
import { icon } from "../icons.js";
import { areaNav } from "./kit.js";
import { card, empty, pageHead } from "./shared.js";
import type { Page } from "./types.js";
import { invite } from "./widgets.js";

export interface Cond { id: string; label: string; icon: string }
export interface Place { id: number; name: string; admin1: string; country: string; label: string; lat: number; lon: number; default: boolean; monitor: boolean; timezone: string }
interface Cur { ts: number; temp: number; feels: number | null; humidity: number | null; is_day: boolean; precip: number | null; cloud: number | null; wind: number | null; wind_dir_label: string; gust: number | null; pressure: number | null; visibility: number | null; cond: Cond }
interface Hour { ts: number; temp: number | null; pop: number | null; wind: number | null; cond: Cond; precip: number | null }
interface Day { date: string; tmax: number | null; tmin: number | null; pop: number | null; precip: number | null; sunrise: number | null; sunset: number | null; gust: number | null; uv: number | null; cond: Cond }
interface Prefs { clock: "12" | "24"; offer_device_location: boolean; show: Record<"current" | "hourly" | "daily" | "precip" | "wind" | "sun" | "details", boolean> }
export interface Overview {
  location: Place | null; timezone: string; current: Cur; hourly: Hour[]; daily: Day[]; prefs: Prefs; now: number;
  units: { temp: string; wind: string; precip: string; vis: string; pressure: string };
  meta: { fetched_at: number; age_seconds: number; stale: boolean; error: string };
  attribution: { text: string; url: string; license: string; note: string };
}

const fail = (e: unknown) => toast(e instanceof Error ? e.message : String(e), "error");
const n = (v: number | null | undefined, d = 0): string => (v === null || v === undefined ? "–" : v.toFixed(d).replace(/\.0+$/, ""));

function clock(ts: number | null, tz: string, h24: boolean): string {
  if (ts === null) return "–";
  return new Intl.DateTimeFormat([], { hour: "2-digit", minute: "2-digit", hour12: !h24, timeZone: tz }).format(new Date(ts * 1000));
}
const dayName = (date: string, i: number): string => (i === 0 ? "Today" : i === 1 ? "Tomorrow" : new Date(`${date}T12:00:00`).toLocaleDateString([], { weekday: "short", day: "numeric" }));

function age(sec: number): string {
  const m = Math.floor(sec / 60);
  return m < 1 ? "just now" : m < 60 ? `${m} min ago` : `${Math.floor(m / 60)} h ${m % 60} min ago`;
}

/** Place search + saving. `onSaved` runs after a place was added. Shared by the dashboard (first visit) and the settings page. */
export function placePicker(onSaved: () => void, offerDevice: boolean): HTMLElement {
  const results = h("div", { class: "k-stack" });
  const input = h("input", { type: "search", placeholder: "Search a town or city, e.g. Nairobi", "aria-label": "Search for a place", maxlength: 100, autocomplete: "off" }) as HTMLInputElement;
  const save = async (body: Record<string, unknown>) => { try { await post("/api/weather/locations", body); toast("Location saved"); onSaved(); } catch (e) { fail(e); } };
  const go = async () => {
    const q = input.value.trim();
    if (q.length < 2) { mount(results, h("p", { class: "muted small" }, "Type at least two letters.")); return; }
    mount(results, h("p", { class: "muted small" }, "Searching…"));
    try {
      const r = await get<{ results: Record<string, unknown>[] }>(`/api/weather/search?q=${encodeURIComponent(q)}`);
      mount(results, r.results.length ? r.results.map((p) => h("button", { class: "btn wx-result", type: "button", onclick: () => void save({ ...p, make_default: false }) },
        icon("mapPin", 16), h("span", null, h("strong", null, String(p.name)), h("span", { class: "muted small" }, ` ${[p.admin1, p.country].filter(Boolean).join(", ")}`)))) : h("p", { class: "muted small" }, "No place matched. Check the spelling, or add coordinates below."));
    } catch (e) { mount(results, h("p", { class: "bad-text small" }, e instanceof Error ? e.message : String(e))); }
  };
  input.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); void go(); } });
  const lat = h("input", { type: "number", step: "any", min: -90, max: 90, placeholder: "Latitude", "aria-label": "Latitude" }) as HTMLInputElement;
  const lon = h("input", { type: "number", step: "any", min: -180, max: 180, placeholder: "Longitude", "aria-label": "Longitude" }) as HTMLInputElement;
  const nm = h("input", { type: "text", placeholder: "Name (optional)", maxlength: 80, "aria-label": "Name" }) as HTMLInputElement;
  const manual = h("button", { class: "btn small", type: "button" }, icon("plus", 15), "Add coordinates") as HTMLButtonElement;
  manual.onclick = () => (lat.value.trim() === "" || lon.value.trim() === "") ? toast("Enter both latitude and longitude") : busy(manual, () => save({ lat: Number(lat.value), lon: Number(lon.value), name: nm.value }));
  // The browser only asks for location when this button is pressed. Nothing is requested on load.
  const dev = offerDevice && "geolocation" in navigator ? ((): HTMLButtonElement => {
    const b = h("button", { class: "btn small", type: "button" }, icon("compass", 15), "Use this device's location") as HTMLButtonElement;
    b.onclick = () => { b.disabled = true; navigator.geolocation.getCurrentPosition(
      (p) => { b.disabled = false; void save({ lat: Math.round(p.coords.latitude * 100) / 100, lon: Math.round(p.coords.longitude * 100) / 100, name: "My location" }); },
      (err) => { b.disabled = false; toast(err.code === 1 ? "Location permission was not given. Search for a place instead." : "Could not read the device location. Search for a place instead.", "error"); },
      { timeout: 10000, maximumAge: 600000 }); };
    return b;
  })() : null;
  return h("div", { class: "k-stack" },
    h("div", { class: "row wrap" }, input, h("button", { class: "btn primary", type: "button", onclick: () => void go() }, icon("search", 16), "Search")), results,
    dev ? h("div", { class: "row" }, dev, h("span", { class: "muted small" }, "Rounded to about 1 km before it is saved.")) : null,
    h("details", { class: "wx-manual" }, h("summary", null, "Enter coordinates"), h("div", { class: "row wrap" }, lat, lon, nm, manual)));
}

export function attribution(o: { attribution: Overview["attribution"] }): HTMLElement {
  return h("p", { class: "muted small wx-attr" }, h("a", { href: o.attribution.url, target: "_blank", rel: "noopener noreferrer" }, o.attribution.text), ` · ${o.attribution.license}`, o.attribution.note ? ` · ${o.attribution.note}` : "");
}

function tempLine(hours: Hour[]): HTMLElement | null {
  const v = hours.map((x) => x.temp).filter((x): x is number => x !== null);
  if (v.length < 3) return null;
  const lo = Math.min(...v), hi = Math.max(...v), span = hi - lo || 1, W = 100, H = 30;
  const pts = hours.map((x, i) => (x.temp === null ? null : `${(i / (hours.length - 1)) * W},${H - 3 - ((x.temp - lo) / span) * (H - 6)}`)).filter(Boolean).join(" ");
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", `0 0 ${W} ${H}`); svg.setAttribute("preserveAspectRatio", "none"); svg.setAttribute("class", "wx-line"); svg.setAttribute("role", "img");
  svg.setAttribute("aria-label", `Temperature from ${lo.toFixed(0)} to ${hi.toFixed(0)} over the next ${hours.length} hours`);
  const pl = document.createElementNS("http://www.w3.org/2000/svg", "polyline");
  pl.setAttribute("points", pts); pl.setAttribute("fill", "none"); pl.setAttribute("stroke", "currentColor"); pl.setAttribute("stroke-width", "1.6"); pl.setAttribute("vector-effect", "non-scaling-stroke");
  svg.appendChild(pl);
  return h("div", { class: "wx-line-wrap" }, svg) as HTMLElement;
}

function render(root: HTMLElement, o: Overview, pick: (id: number) => void, reload: (force: boolean) => void, places: Place[]): void {
  const loc = o.location!, p = o.prefs, u = o.units, tz = o.timezone, h24 = p.clock === "24", c = o.current;
  const select = h("select", { "aria-label": "Location", onchange: (e: Event) => pick(Number((e.target as HTMLSelectElement).value)) }, places.map((x) => h("option", { value: x.id, selected: x.id === loc.id }, x.name)));
  const refresh = h("button", { class: "btn small", type: "button", "aria-label": "Refresh weather" }, icon("refresh", 15), "Refresh") as HTMLButtonElement;
  refresh.onclick = () => busy(refresh, async () => reload(true));
  const status = h("p", { class: `small ${o.meta.stale ? "bad-text" : "muted"}`, role: "status" },
    o.meta.stale ? `Showing old data from ${age(o.meta.age_seconds)}. ${o.meta.error}` : `Updated ${age(o.meta.age_seconds)}`);
  const stat = (ic: string, label: string, value: string) => h("div", { class: "wx-stat" }, icon(ic, 16), h("span", { class: "muted small" }, label), h("b", null, value));
  const d0 = o.daily[0];
  const details: HTMLElement[] = [];
  if (p.show.details) details.push(stat("droplet", "Humidity", `${n(c.humidity)}%`), stat("gauge", "Pressure", `${n(c.pressure)} ${u.pressure}`), stat("cloud", "Cloud cover", `${n(c.cloud)}%`), stat("eye", "Visibility", `${n(c.visibility, 1)} ${u.vis}`));
  if (p.show.wind) details.push(stat("wind", "Wind", `${n(c.wind, 0)} ${u.wind} ${c.wind_dir_label}${c.gust ? `, gusts ${n(c.gust)}` : ""}`));
  if (p.show.precip) details.push(stat("cloudRain", "Rain now", `${n(c.precip, 1)} ${u.precip}`), ...(d0 ? [stat("droplet", "Chance today", `${n(d0.pop)}%`)] : []));
  if (p.show.sun && d0) details.push(stat("sunrise", "Sunrise", clock(d0.sunrise, tz, h24)), stat("sunset", "Sunset", clock(d0.sunset, tz, h24)));
  const now = p.show.current ? card("mapPin", loc.label || loc.name, h("div", { class: "wx-now" },
    h("div", { class: "wx-big" }, icon(c.cond.icon, 56), h("div", null, h("div", { class: "wx-temp" }, `${n(c.temp)}${u.temp}`), h("div", { class: "wx-cond" }, c.cond.label), c.feels !== null ? h("div", { class: "muted small" }, `Feels like ${n(c.feels)}${u.temp}`) : null)),
    d0 ? h("p", { class: "muted" }, `Today ${n(d0.tmin)} to ${n(d0.tmax)}${u.temp}`) : null, h("div", { class: "wx-grid" }, details)), { actions: h("div", { class: "row" }, select, refresh) }) : null;
  const hourly = p.show.hourly ? card("clock", `Next ${o.hourly.length} hours`, h("div", { class: "wx-hourly-wrap" }, tempLine(o.hourly), h("div", { class: "wx-hourly", role: "list" }, o.hourly.map((x) =>
    h("div", { class: "wx-hour", role: "listitem" }, h("span", { class: "muted small" }, clock(x.ts, tz, h24)), icon(x.cond.icon, 22), h("b", null, `${n(x.temp)}°`), h("span", { class: "small wx-pop", title: "Chance of rain" }, x.pop ? `${n(x.pop)}%` : ""))))), { flush: true }) : null;
  const lo = Math.min(...o.daily.map((d) => d.tmin ?? 99)), hi = Math.max(...o.daily.map((d) => d.tmax ?? -99)), span = hi - lo || 1;
  const daily = p.show.daily ? card("chart", `${o.daily.length}-day forecast`, h("div", { class: "wx-days" }, o.daily.map((d, i) => h("div", { class: "wx-day" },
    h("span", { class: "wx-dn" }, dayName(d.date, i)), icon(d.cond.icon, 20), h("span", { class: "wx-pop small" }, d.pop ? `${n(d.pop)}%` : ""),
    h("span", { class: "wx-lo" }, `${n(d.tmin)}°`),
    h("span", { class: "wx-range", "aria-hidden": "true" }, h("i", { style: `left:${(((d.tmin ?? lo) - lo) / span) * 100}%;right:${100 - (((d.tmax ?? hi) - lo) / span) * 100}%` })),
    h("span", { class: "wx-hi" }, `${n(d.tmax)}°`), h("span", { class: "wx-dc muted small" }, d.cond.label)))), { flush: true }) : null;
  mount(root, h("div", { class: "page" }, areaNav("weather"),
    pageHead("cloudSun", "Weather", "Conditions and forecast for your saved places.", h("a", { class: "btn small", href: "/weather-settings" }, icon("sliders", 15), "Weather settings")),
    status, now, hourly, daily, attribution(o)));
}

export const weather: Page = {
  id: "weather", title: "Weather", icon: "cloudSun", blurb: "Current weather, hourly and daily forecast",
  render(root) {
    let locId: number | null = null;
    const load = async (force: boolean): Promise<void> => {
      try {
        const [places, o] = await Promise.all([get<{ locations: Place[] }>("/api/weather/locations"), force ? post<Overview>("/api/weather/refresh", { location_id: locId }) : get<Overview>(`/api/weather/overview${locId ? `?location=${locId}` : ""}`)]);
        if (!o.location) {
          const prefs = await get<Prefs>("/api/weather/prefs");
          mount(root, h("div", { class: "page" }, areaNav("weather"), pageHead("cloudSun", "Weather", "Add a place to see its weather."),
            invite("mapPin", "Which place?", "Search for a town, or use this device's location if you like. SavahBot never asks for your location on its own.", null),
            card("search", "Add a place", h("div", { style: "padding:12px 14px" }, placePicker(() => void load(false), prefs.offer_device_location)), { flush: true })));
          return;
        }
        locId = o.location.id;
        render(root, o, (id) => { locId = id; void load(false); }, (f) => void load(f), places.locations);
      } catch (e) {
        mount(root, h("div", { class: "page" }, areaNav("weather"), pageHead("cloudSun", "Weather"), empty("cloud", e instanceof Error ? e.message : "Weather could not load."),
          h("div", { class: "row" }, h("button", { class: "btn", type: "button", onclick: () => void load(false) }, icon("refresh", 15), "Try again"))));
      }
    };
    mount(root, h("div", { class: "page" }, areaNav("weather"), pageHead("cloudSun", "Weather"), h("p", { class: "muted" }, "Loading…")));
    void load(false);
  },
};
