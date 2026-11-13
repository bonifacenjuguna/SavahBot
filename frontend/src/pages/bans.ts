/** Bans: everything the bot has timed out or banned, lifting them again, and the rules that make the bot gentler. */
import { get, patch, post } from "../api.js";
import { busy, dateTime, duration, h, mount, toast } from "../dom.js";
import { icon } from "../icons.js";
import { areaNav } from "./kit.js";
import { empty, pageHead } from "./shared.js";
import type { Page } from "./types.js";
import { openBanProfile } from "./person-profile.js";
import { avatar, figures, invite, lede, seg } from "./widgets.js";

interface Ban { id: number; ts: number; author_id: string; author_name: string; kind: "ban" | "timeout"; duration: number | null; source: string; reason: string; status: string; lifted_ts: number | null; lifted_by: string; error: string; demo: number; can_lift: boolean }
interface Rules { mod_max_punishment: string; mod_never_punish: string; mod_reason_caps: string; mod_auto_punish_daily_cap: number; mod_second_chance_hours: number }
interface Listing { total: number; items: Ban[]; counts: Record<string, number>; auto_today: number; rules: Rules }

type Filter = "active" | "lifted" | "expired" | "all";
const SOURCE: Record<string, string> = { auto: "Done by the bot", approved: "Approved by you", manual: "Added by you" };
const fail = (e: unknown) => toast(e instanceof Error ? e.message : String(e), "error");

export const bans: Page = {
  id: "bans",
  title: "Bans",
  icon: "ban",
  blurb: "Lift bans and soften the bot's actions",
  render(root) {
    let filter: Filter = "active";
    let needle = "";
    const list = h("div", { class: "k-stack" });
    const rulesBox = h("div", { class: "k-stack" });
    const top = h("div", { class: "k-stack" });

    const row = (b: Ban): HTMLElement => {
      const lift = h("button", { class: "btn small", type: "button", disabled: !b.can_lift, title: b.can_lift ? "" : "YouTube gave no id for this ban, so it can only be lifted in YouTube Studio." },
        icon("undo", 15), "Lift") as HTMLButtonElement;
      lift.onclick = () => busy(lift, async () => {
        try { await post(`/api/bans/${b.id}/lift`); toast(`${b.author_name || b.author_id} can chat again`, "ok"); await load(); } catch (e) { fail(e); }
      });
      const what = b.kind === "ban" ? "Banned" : `Timed out${b.duration ? " for " + duration(b.duration) : ""}`;
      return h("div", { class: "block flush" }, h("div", { class: "row between", style: "padding:12px 14px;gap:12px;align-items:center" },
        h("button", { class: "row row-open", type: "button", "aria-label": `Open the profile of ${b.author_name || b.author_id}`, onclick: () => openBanProfile(b, () => void load().catch(fail)) }, avatar(b.author_name || b.author_id, 38),
          h("div", { style: "min-width:0" }, h("strong", null, b.author_name || b.author_id),
            h("div", { class: "muted small" }, `${what} · ${SOURCE[b.source] ?? b.source} · ${dateTime(b.ts)}${b.demo ? " · demo" : ""}`),
            b.reason ? h("div", { class: "muted small" }, b.reason) : null,
            b.status === "lifted" ? h("div", { class: "muted small" }, `Lifted ${b.lifted_ts ? dateTime(b.lifted_ts) : ""} by ${b.lifted_by}`) : null,
            b.error ? h("div", { class: "small", style: "color:var(--bad, #c0392b)" }, b.error) : null), icon("chevronRight", 18)),
        b.status === "active" ? lift : h("span", { class: "chip" }, b.status)));
    };

    async function load(): Promise<void> {
      const r = await get<Listing>(`/api/bans?status=${filter === "all" ? "" : filter}&q=${encodeURIComponent(needle)}`);
      mount(top, figures([{ value: String(r.counts.active), label: "active now", tone: r.counts.active ? "warn" : "ok" }, { value: String(r.counts.lifted), label: "lifted" },
        { value: String(r.counts.expired), label: "timeouts ended" }, { value: String(r.auto_today), label: "by the bot today" }]));
      mount(list, r.items.length ? h("div", { class: "k-stack" }, r.items.map(row)) : empty("ban", filter === "active" ? "Nobody is banned or timed out right now." : "Nothing here."));
      drawRules(r.rules);
    }

    function drawRules(r: Rules): void {
      const level = h("select", { "aria-label": "Harshest action" }, [["ban", "Ban (no limit)"], ["timeout", "Timeout at most"], ["delete", "Only delete messages"]].map(([v, t]) => h("option", { value: v, selected: v === r.mod_max_punishment }, t))) as HTMLSelectElement;
      const never = h("input", { type: "text", value: r.mod_never_punish, placeholder: "names or channel ids, comma separated", "aria-label": "Never punish" }) as HTMLInputElement;
      const caps = h("input", { type: "text", value: r.mod_reason_caps, placeholder: "link:delete,caps:delete", "aria-label": "Per-trigger caps" }) as HTMLInputElement;
      const daily = h("input", { type: "number", min: "0", value: String(r.mod_auto_punish_daily_cap), "aria-label": "Daily cap" }) as HTMLInputElement;
      const chance = h("input", { type: "number", min: "0", value: String(r.mod_second_chance_hours), "aria-label": "Second chance hours" }) as HTMLInputElement;
      const field = (label: string, el: HTMLElement, help: string) => h("label", { class: "field" }, h("span", null, label), el, h("span", { class: "muted small" }, help));
      const saveBtn = h("button", { class: "btn primary", type: "button" }, icon("save", 16), "Save rules") as HTMLButtonElement;
      saveBtn.onclick = () => busy(saveBtn, async () => {
        try {
          await patch("/api/settings", { values: { mod_max_punishment: level.value, mod_never_punish: never.value.trim(), mod_reason_caps: caps.value.trim(),
            mod_auto_punish_daily_cap: Number(daily.value) || 0, mod_second_chance_hours: Number(chance.value) || 0 } });
          toast("Rules saved", "ok");
        } catch (e) { fail(e); }
      });
      mount(rulesBox, h("div", { class: "k-stack" },
        lede("These rules only ever make the bot gentler. A message that breaks them is still deleted. Escalation steps (how many strikes lead to a timeout or ban, and the timeout ladder) are in Settings under Moderation."),
        field("Harshest action allowed", level, "Pick “Only delete messages” to stop all timeouts and bans."),
        field("Never time out or ban", never, "Their bad messages are still deleted."),
        field("Cap by trigger", caps, "name:action pairs. The trigger names are shown on each moderation card."),
        field("Automatic timeouts and bans per day", daily, "After this many the bot only deletes. 0 means no limit."),
        field("Lift automatic bans after (hours)", chance, `A second chance. Each lift costs YouTube quota (200 units). 0 means never.`),
        h("div", { class: "row" }, saveBtn)));
    }

    const views = seg<Filter>("Show", [{ id: "active", label: "Active" }, { id: "lifted", label: "Lifted" }, { id: "expired", label: "Ended" }, { id: "all", label: "All" }], filter, (v) => { filter = v; void load().catch(fail); });
    const search = h("input", { type: "search", placeholder: "Find a person", "aria-label": "Find a person", autocomplete: "off" }) as HTMLInputElement;
    let t = 0;
    search.oninput = () => { clearTimeout(t); t = window.setTimeout(() => { needle = search.value.trim(); void load().catch(fail); }, 250); };

    mount(root, h("div", { class: "page" }, areaNav("bans"),
      pageHead("ban", "Bans", "Everyone the bot has timed out or banned, and the rules that keep it fair."),
      top,
      h("section", { class: "block fixed-scroll" }, h("header", null, h("h2", null, icon("list", 18), "Ledger")),
        h("div", { class: "k-stack", style: "padding:12px 14px" }, h("div", { class: "row wrap", style: "gap:10px" }, views.el, search), list,
          h("p", { class: "muted small" }, "Tap a person to see their profile and why it happened. Only bans made by SavahBot from version 1.2.0 on can be lifted here. Older bans, and bans made in YouTube Studio, must be lifted in YouTube Studio: YouTube gives no way to list them."))),
      h("section", { class: "block" }, h("header", null, h("h2", null, icon("sliders", 18), "Be gentler")), h("div", { style: "padding:12px 14px" }, rulesBox))));
    void load().catch((e) => { fail(e); mount(list, invite("alert", "Could not load the bans", (e as Error).message)); });
  },
};
