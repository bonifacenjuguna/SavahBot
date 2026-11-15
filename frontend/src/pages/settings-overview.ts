/** Settings search and the "Needs a look" list. (Until 1.4.5 this was the Overview tab; 1.4.6 removed the tab: search sits above every Settings tab and the list lives in Developer.) */
import { get } from "../api.js";
import { h, mount } from "../dom.js";
import { icon, statusIcon } from "../icons.js";
import { GROUPS, remember, search, type Entry } from "./settings-index.js";
import { card, empty } from "./shared.js";
import { href as routeHref } from "../router.js";

interface Attention { attention: { level: "bad" | "warn" | "info"; text: string; route: string }[] }

function result(e: Entry): HTMLElement {
  return h("a", { class: "set-hit", href: routeHref(e.route), onclick: () => remember(e.id) }, icon(e.icon, 18), h("span", { class: "set-main" }, h("strong", null, e.title), h("span", { class: "muted small" }, e.text)),
    h("span", { class: "chip" }, GROUPS.find((g) => g.id === e.group)?.title ?? ""));
}

/** A search box for every setting. While something is typed, `below` (the tab's content) is hidden and the results show in its place. */
export function settingsSearch(below: HTMLElement): HTMLElement {
  const results = h("div", { class: "k-stack", role: "region", "aria-live": "polite", "aria-label": "Search results" });
  const input = h("input", { type: "search", placeholder: "Search settings: try “quiet hours”, “backup”, “accent”…", "aria-label": "Search settings", autocomplete: "off" }) as HTMLInputElement;
  input.oninput = () => {
    const q = input.value.trim();
    below.hidden = q.length > 0;
    if (!q) { mount(results); return; }
    const hits = search(q);
    mount(results, hits.length ? hits.map(result) : empty("search", `Nothing matches “${q}”. Try another word, or search the environment options in Developer.`),
      h("a", { class: "btn small", href: `/settings?tab=developer&q=${encodeURIComponent(q)}` }, icon("sliders", 15), "Search every environment setting too"));
  };
  return h("div", { class: "k-stack" }, h("div", { class: "input-icon" }, icon("search", 16), input), results);
}

/** The "Needs a look" list (or "All clear"), shown at the top of Developer. */
export async function renderAttention(el: HTMLElement): Promise<void> {
  const o = await get<Attention>("/api/settings/overview");
  mount(el, o.attention.length
    ? card("alert", `Needs a look (${o.attention.length})`, h("div", { class: "n-log" }, o.attention.map((a) => h("a", { class: `n-hist ${a.level === "bad" ? "bad" : a.level === "warn" ? "warn" : "info"}`, href: routeHref(a.route) },
      statusIcon(a.level === "info" ? "info" : a.level === "bad" ? "bad" : "warn", 20), h("span", { class: "set-main" }, a.text), icon("chevronRight", 16)))), { flush: true })
    : card("check", "All clear", h("p", { style: "padding:12px 14px" }, "Nothing needs attention right now."), { flush: true }));
}
