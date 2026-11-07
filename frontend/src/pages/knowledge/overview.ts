import { get } from "../../api.js";
import { h, mount, toast } from "../../dom.js";
import { icon } from "../../icons.js";
import { empty } from "../shared.js";
import { invite, plural } from "../widgets.js";
import { DET_ICON, type DetectorInfo, hrefFor, modeChip, n0, pct, setSetting } from "./common.js";

interface Overview {
  enabled: boolean; hours: number; detectors: DetectorInfo[]; modes: Record<string, number>;
  packs: { total: number; enabled: number; entries: number; problems: string[] };
  learning: { ready: boolean; examples: { spam: number; ham: number; total: number }; accuracy_recent: number | null; accuracy_n: number };
  shadow: { hits: number; differs: number };
}

export function renderOverview(root: HTMLElement): void {
  const body = h("div", { class: "stack" });
  mount(root, body);

  const load = async () => {
    const o = await get<Overview>("/api/intel/overview?hours=24");
    const sw = h("input", { type: "checkbox", class: "switch", checked: o.enabled, "aria-label": "Run the intelligence layer", onchange: async (e: Event) => {
      const el = e.target as HTMLInputElement;
      if (!(await setSetting("intel_enabled", el.checked, el.checked ? "Intelligence is on" : "Intelligence is off"))) el.checked = !el.checked; else void load();
    } });

    // What to do next: the one most useful thing, in a sentence.
    let next: { icon: string; title: string; text: string; href: string; cta: string } | null = null;
    if (!o.enabled) next = { icon: "alert", title: "The intelligence layer is off", text: "Only your original moderation rules are running. Switch it on to let the detectors watch chat.", href: hrefFor("detectors"), cta: "See the detectors" };
    else if (o.packs.problems.length) next = { icon: "alert", title: "A knowledge pack could not be loaded", text: o.packs.problems[0], href: hrefFor("packs"), cta: "Open packs" };
    else if (o.shadow.differs > 0 && o.modes.active < o.detectors.length) next = { icon: "eyeOff", title: `In the last day, shadow detectors would have caught ${plural(o.shadow.differs, "message")} the bot let through`, text: "Look at what they found. When a detector is mostly right, switch it to Active.", href: hrefFor("shadow"), cta: "Open the shadow report" };
    else if (!o.learning.examples.total) next = { icon: "sparkle", title: "Teach the bot", text: "Approve or reject requests in Moderation, or use Teach on any message. It starts with a shipped head start, and your decisions count for more.", href: hrefFor("learning"), cta: "Open learning" };
    else if (o.modes.active === 0) next = { icon: "sliders", title: "Everything is still in shadow mode", text: "Nothing the detectors find changes what happens in chat yet. Check the shadow report, then turn on the ones you trust.", href: hrefFor("shadow"), cta: "Review shadow findings" };

    const tally = [{ id: "active", n: o.modes.active ?? 0, label: "Active", help: "adding to scores" }, { id: "shadow", n: o.modes.shadow ?? 0, label: "Shadow", help: "watching only" }, { id: "off", n: o.modes.off ?? 0, label: "Off", help: "not running" }];

    mount(body,
      h("section", { class: `wb mind${o.enabled ? "" : " is-off"}`, "aria-label": "Status" },
        h("div", { class: "mind-top" },
          h("div", null, h("h2", null, o.enabled ? "Intelligence is on" : "Intelligence is off"),
            h("p", { class: "lede" }, `${o.detectors.length} detectors and ${plural(o.packs.enabled, "knowledge pack")} with ${n0(o.packs.entries)} entries. Everything runs on this server, with no outside AI service.`)),
          h("label", { class: "ambient compact" }, h("span", { class: "muted small" }, o.enabled ? "On" : "Off"), sw)),
        h("div", { class: "tally" }, tally.map((t) => h("a", { class: `tally-item mode-${t.id}`, href: hrefFor("detectors") }, h("b", null, String(t.n)), h("span", null, t.label), h("small", null, t.help))))),
      next ? h("a", { class: "next-step", href: next.href }, h("span", { class: "nl-ico warn" }, icon(next.icon, 20)), h("span", { class: "ns-text" }, h("strong", null, next.title), h("span", null, next.text)), h("span", { class: "ns-cta" }, next.cta, icon("chevronRight", 16))) : null,
      h("div", { class: "cols even" },
        h("section", { class: "block flush" }, h("header", null, h("h2", null, icon("sliders", 18), "Detectors"), h("a", { class: "btn small ghost", href: hrefFor("detectors") }, "Manage")),
          h("ul", { class: "det-mini" }, o.detectors.map((d) => h("li", null, h("span", { class: "dm-ico" }, icon(DET_ICON[d.id] ?? "sliders", 17)), h("span", { class: "dm-name" }, h("strong", null, d.title), d.hits ? h("small", null, `${plural(d.hits, "finding")} in 24 hours`) : null), modeChip(d.mode))))),
        h("div", { class: "stack" },
          h("section", { class: "block flush" }, h("header", null, h("h2", null, icon("package", 18), "Knowledge"), h("a", { class: "btn small ghost", href: hrefFor("packs") }, "Browse")),
            h("div", { class: "kn-figs" },
              h("div", { class: "fig" }, h("b", null, String(o.packs.enabled)), h("span", null, `of ${o.packs.total} packs on`)),
              h("div", { class: "fig" }, h("b", null, n0(o.packs.entries)), h("span", null, "entries in use")))),
          h("section", { class: "block flush" }, h("header", null, h("h2", null, icon("sparkle", 18), "Learning"), h("a", { class: "btn small ghost", href: hrefFor("learning") }, "Open")),
            o.learning.examples.total || o.learning.accuracy_n
              ? h("div", { class: "kn-figs" },
                  h("div", { class: "fig" }, h("b", null, n0(o.learning.examples.total)), h("span", null, "lessons from you")),
                  h("div", { class: "fig" }, h("b", null, pct(o.learning.accuracy_recent)), h("span", null, "recent accuracy")))
              : invite("sparkle", "No lessons yet", "Approve or reject something in Moderation and the bot starts learning your chat."))),
      ),
      o.packs.problems.length ? h("section", { class: "banner error" }, icon("alert", 18), h("span", null, `Skipped packs: ${o.packs.problems.join(" ")}`)) : null);
  };
  void load().catch((e) => { toast(e.message, "error"); mount(body, empty("alert", "Could not load the overview.")); });
}
