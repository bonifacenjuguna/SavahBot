import { get } from "../api.js";
import { ago, h, mount } from "../dom.js";
import { sparkline } from "../charts.js";
import { icon } from "../icons.js";
import { card } from "./shared.js";

interface Live {
  likes: number | null; viewers: number | null; updated: number; peak_viewers: number; likes_hidden: boolean; note: string; likes_per_min: number | null;
  series: { ts: number; likes: number | null; viewers: number | null }[]; sample: boolean; enabled: boolean;
  subscribers: { count: number | null; state: string; note: string };
}

const num = (v: number | null | undefined) => (typeof v === "number" ? v.toLocaleString() : "n/a");

/** Likes, viewers, likes per minute and a trend, with how old the numbers are. Refreshes itself; YouTube is only asked on the server's own schedule. */
export function liveCard(): { el: HTMLElement; stop: () => void } {
  const body = h("div", { class: "stack", style: "padding:14px" }, h("p", { class: "muted" }, "Loading…"));
  const el = card("activity", "Live stats", body, { flush: true, actions: h("a", { class: "btn small ghost", href: "/stream-settings" }, icon("sliders", 14), "Set up") });
  let last: Live | null = null;
  const stat = (ic: string, label: string, value: string, sub = "") =>
    h("div", { style: "min-width:96px;flex:1" }, h("div", { class: "muted small" }, icon(ic, 14), " ", label), h("div", { style: "font-size:1.5rem;font-weight:600" }, value), sub ? h("div", { class: "muted small" }, sub) : null);
  const draw = () => {
    const d = last;
    if (!d) return;
    if (!d.enabled) { mount(body, h("p", { class: "muted small" }, "Live stats are switched off. Turn them on in Set up.")); return; }
    if (!d.updated) { mount(body, h("p", { class: "muted small" }, "Nothing yet. Likes and viewers appear once your stream is live and YouTube has answered.")); return; }
    const viewers = d.series.map((p) => p.viewers ?? 0);
    mount(body,
      d.sample ? h("div", { class: "banner demo" }, icon("flask", 16), h("span", null, "Sample data: Demo mode has no YouTube, so these numbers are made up.")) : null,
      h("div", { class: "row wrap", style: "gap:12px" },
        stat("thumbsUp", "Likes", d.likes_hidden ? "hidden" : num(d.likes), d.likes_per_min !== null ? `${d.likes_per_min}/min` : ""),
        stat("eye", "Watching", num(d.viewers), `peak ${num(d.peak_viewers)}`),
        stat("users", "Subscribers", num(d.subscribers?.count))),
      viewers.length > 1 ? h("div", { style: "height:44px" }, sparkline(viewers)) : null,
      d.note ? h("p", { class: "muted small wrap" }, d.note) : null,
      h("p", { class: "muted small" }, `Updated ${ago(d.updated)}. YouTube can lag behind real life by a minute or more.`));
  };
  const load = async () => { try { last = await get<Live>("/api/live/stats"); } catch { /* keep the last numbers */ } draw(); };
  void load();
  const t1 = window.setInterval(() => void load(), 30_000), t2 = window.setInterval(draw, 10_000);   // redraw so "updated N s ago" stays true
  return { el, stop: () => { clearInterval(t1); clearInterval(t2); } };
}
