/** The Knowledge section of Settings: the bot's knowledge packs, detectors, learning and shadow report in one place. */
import { h, mount } from "../../dom.js";
import { icon } from "../../icons.js";
import { areaNav } from "../kit.js";
import { pageHead } from "../shared.js";
import { VIEWS, type View, hrefFor, settingsTabs } from "./common.js";
import { renderDetectors } from "./detectors.js";
import { renderLearning } from "./learning.js";
import { renderOverview } from "./overview.js";
import { renderPacks } from "./packs.js";
import { renderShadow } from "./shadow.js";

export function renderKnowledge(root: HTMLElement, query: URLSearchParams): void {
  const raw = query.get("view") ?? "overview";
  const view: View = (VIEWS.some((v) => v.id === raw) ? raw : "overview") as View;
  const current = VIEWS.find((v) => v.id === view)!;
  const nav = h("nav", { class: "setup-nav", "aria-label": "Knowledge sections" }, VIEWS.map((v) => h("a", { href: hrefFor(v.id), class: "sn-item", "aria-current": v.id === view ? "step" : undefined, "data-tone": v.id === view ? "" : "" },
    h("span", { class: "sn-dot" }, icon(v.icon, 15)), h("span", { class: "sn-text" }, h("strong", null, v.title), h("span", null, v.blurb)))));
  const body = h("div", { class: "kn-body" });
  mount(root, pageHead("sparkle", "Knowledge", "What the bot knows, how it uses it, and what it has learned. All of it runs on this server, with no outside AI service."), areaNav("settings"), settingsTabs("knowledge"),
    h("div", { class: "setup-wrap" }, nav, h("div", { class: "kn-main", "aria-label": current.title }, body)));
  switch (view) {
    case "packs": renderPacks(body, query); break;
    case "detectors": renderDetectors(body); break;
    case "learning": renderLearning(body); break;
    case "shadow": renderShadow(body, query); break;
    default: renderOverview(body);
  }
}
