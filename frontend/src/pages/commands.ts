import { foldChildren, tabRail } from "../nav.js";
import { del, get, patch, post } from "../api.js";
import { ago, busy, debounce, duration, h, mount, sheet, toast } from "../dom.js";
import { icon } from "../icons.js";
import { card, empty, pageHead } from "./shared.js";
import type { Page } from "./types.js";
import { replaceQuery } from "../router.js";

interface Cmd { id: number; name: string; response: string; userlevel: string; cooldown: number; user_cooldown: number; enabled: boolean; aliases: string[] | string }
interface Timer { id: number; name: string; message: string; interval_seconds: number; min_lines: number; enabled: boolean; match_mode: "all" | "any"; max_runs: number; runs: number; fired: number; last_fired: number }
interface Trigger { id: number; phrase: string; match_type: "exact" | "word"; response: string; mention: boolean; userlevel: string; cooldown: number; user_cooldown: number; enabled: boolean; hits: number }

const aliasList = (c: Cmd) => (Array.isArray(c.aliases) ? c.aliases : String(c.aliases || "").split(",").filter(Boolean));
const VARIABLES = ["$(user)", "$(touser)", "$(args)", "$(1)", "$(count)", "$(uptime)", "$(time)", "$(random 1 100)", "$(choose a|b)", "$(math 2+2)", "$(quote)", "$(urlfetch https://...)"];
const plural = (n: number, w: string) => `${n} ${w}${n === 1 ? "" : "s"}`;
type Tab = "commands" | "replies" | "timers";

/** Plain-language description of when a timer posts. */
export function describeSchedule(intervalSeconds: number, lines: number, mode: string, maxRuns: number): string {
  const t = intervalSeconds > 0 ? duration(intervalSeconds) : "";
  let when: string;
  if (t && lines) when = mode === "any" ? `every ${t} or after ${plural(lines, "chat line")}, whichever comes first` : `every ${t}, once at least ${plural(lines, "chat line")} have passed`;
  else if (t) when = `every ${t}`;
  else when = `after every ${plural(lines, "chat line")}`;
  const repeat = maxRuns === 0 ? "It keeps repeating until you switch it off." : maxRuns === 1 ? "It posts once, then switches itself off." : `It posts ${maxRuns} times, then switches itself off.`;
  return `Posts ${when}. ${repeat}`;
}

function variableChips(target: HTMLTextAreaElement, after: () => void): HTMLElement {
  const insert = (v: string) => {
    const s = target.selectionStart ?? target.value.length, e = target.selectionEnd ?? s;
    target.value = target.value.slice(0, s) + v + target.value.slice(e);
    target.focus();
    target.setSelectionRange(s + v.length, s + v.length);
    after();
  };
  const chip = (v: string) => h("button", { class: "chip", type: "button", style: "cursor:pointer", onclick: () => insert(v) }, v);
  const mine = h("div", { class: "row wrap", style: "gap:6px;margin-top:6px" });
  // your own variables (Settings, Variables) sit beside the built-in ones
  void get<{ variables: { name: string }[] }>("/api/variables").then((d) => { if (d.variables.length) mount(mine, h("span", { class: "muted small" }, "Yours:"), ...d.variables.map((v) => chip(`$(${v.name})`))); }).catch(() => undefined);
  return h("div", null, h("div", { class: "muted small", style: "margin-bottom:6px" }, "Tap a variable to insert it"),
    h("div", { class: "row", style: "gap:6px" }, VARIABLES.map(chip)), mine);
}

function livePreview(source: HTMLTextAreaElement): { el: HTMLElement; update: () => void } {
  const el = h("div", { class: "reasons", "aria-live": "polite" });
  const update = debounce(async () => {
    if (!source.value.trim()) return mount(el, "");
    try { mount(el, icon("message", 14), " Preview: ", (await post<{ output: string }>("/api/commands/preview", { template: source.value, user: "Viewer", level: "everyone", args: "a b" })).output); }
    catch (e) { mount(el, (e as Error).message); }
  }, 350) as () => void;
  source.addEventListener("input", update);
  return { el, update };
}

const numInput = (value: number, min: number, max: number, label: string) => h("input", { type: "number", min, max, value: String(value), inputmode: "numeric", "aria-label": label });
const segButtons = (options: [string, string][], current: () => string, set: (v: string) => void, label: string) => {
  const wrap = h("div", { class: "seg-control", role: "group", "aria-label": label });
  const draw = () => mount(wrap, options.map(([v, l]) => h("button", { type: "button", "aria-pressed": String(current() === v), onclick: () => { set(v); draw(); } }, l)));
  draw();
  return wrap;
};

export const commands: Page = {
  id: "commands",
  title: "Commands",
  icon: "terminal",
  blurb: "Commands, auto-replies and timers",
  render(root, query) {
    let tab: Tab = (["commands", "replies", "timers"] as Tab[]).includes(query.get("tab") as Tab) ? (query.get("tab") as Tab) : "commands";
    const listBox = h("div"), timerBox = h("div"), replyBox = h("div");
    let levels: string[] = ["everyone", "member", "regular", "mod", "owner"];
    let builtin: string[] = [];
    let items: Cmd[] = [];
    let timers: Timer[] = [];
    let triggers: Trigger[] = [];
    let triggersOn = true;
    let needle = "";

    // ================================================================== commands
    const editor = (c?: Cmd) => {
      const name = h("input", { type: "text", value: c?.name ?? "", required: true, maxLength: 33, placeholder: "!hello" });
      const resp = h("textarea", { required: true, maxLength: 2000, placeholder: "Welcome $(user)! Stream has been live for $(uptime)." }, c?.response ?? "");
      const lvl = h("select", null, levels.map((l) => h("option", { value: l, selected: (c?.userlevel ?? "everyone") === l }, l)));
      const cd = numInput(c?.cooldown ?? 5, 0, 86400, "Cooldown");
      const ucd = numInput(c?.user_cooldown ?? 10, 0, 86400, "Per person cooldown");
      const al = h("input", { type: "text", value: c ? aliasList(c).join(", ") : "", placeholder: "hi, hey" });
      const en = h("input", { type: "checkbox", class: "switch", checked: c?.enabled ?? true, "aria-label": "Enabled" });
      const pv = livePreview(resp);
      const save = h("button", { class: "btn primary", type: "submit" }, icon("check", 16), c ? "Save changes" : "Add command");
      const holder: { close: () => void } = { close: () => undefined };
      const form = h("form", { class: "stack", onsubmit: (e: Event) => {
        e.preventDefault();
        const body = { name: name.value, response: resp.value, userlevel: lvl.value, cooldown: Number(cd.value), user_cooldown: Number(ucd.value), enabled: en.checked,
          aliases: al.value.split(",").map((s) => s.trim()).filter(Boolean) };
        busy(save, async () => { c ? await patch(`/api/commands/${c.id}`, body) : await post("/api/commands", body); await load(); holder.close(); }, "Saved");
      } },
        h("div", { class: "form-grid" }, h("label", { class: "field" }, "Name", name), h("label", { class: "field" }, "Who can use it", lvl),
          h("label", { class: "field" }, "Cooldown (seconds, everyone)", cd), h("label", { class: "field" }, "Cooldown (seconds, per person)", ucd),
          h("label", { class: "field wide" }, "Aliases (comma separated)", al), h("label", { class: "field wide" }, "Reply", resp)),
        variableChips(resp, pv.update), pv.el,
        h("div", { class: "row between" }, h("label", { class: "check" }, en, "Enabled"), h("span", { class: "row" }, h("button", { class: "btn ghost", type: "button", onclick: () => holder.close() }, "Cancel"), save)));
      holder.close = sheet(c ? `Edit !${c.name}` : "New command", form).close;
      if (c) pv.update();
    };

    const drawList = () => {
      const search = h("input", { type: "search", placeholder: "Search commands", "aria-label": "Search commands", value: needle });
      search.addEventListener("input", () => { needle = search.value.trim().toLowerCase(); drawRows(); });
      const rowsBox = h("div");
      const drawRows = () => {
        const r = items.filter((c) => !needle || `${c.name} ${c.response} ${aliasList(c).join(" ")}`.toLowerCase().includes(needle));
        mount(rowsBox, r.length ? h("div", { class: "table-wrap" }, h("table", { class: "cards" }, h("thead", null, h("tr", null, ["On", "Command", "Reply", "Who", ""].map((c) => h("th", null, c)))),
          h("tbody", null, r.map((c) => h("tr", null,
            h("td", { "data-label": "On" }, h("input", { type: "checkbox", class: "switch", checked: c.enabled, "aria-label": `Enable !${c.name}`, onchange: (e: Event) => void patch(`/api/commands/${c.id}`, { enabled: (e.target as HTMLInputElement).checked }).then(() => { c.enabled = !c.enabled; }).catch((x) => toast(x.message, "error")) })),
            h("td", { "data-label": "Command" }, h("div", null, h("span", { class: "mono" }, "!" + c.name), aliasList(c).length ? h("div", { class: "muted small" }, aliasList(c).map((a) => "!" + a).join(" ")) : null)),
            h("td", { style: "max-width:380px;overflow-wrap:anywhere", "data-label": "Reply" }, c.response),
            h("td", { "data-label": "Who" }, h("div", null, h("span", { class: "chip" }, c.userlevel), h("div", { class: "muted small" }, `${duration(c.cooldown)} / ${duration(c.user_cooldown)}`))),
            h("td", { "data-label": "" }, h("div", { class: "row", style: "gap:6px" }, h("button", { class: "btn small ghost", "aria-label": `Edit !${c.name}`, onclick: () => editor(c) }, icon("pencil", 15), "Edit"),
              h("button", { class: "btn small danger", "aria-label": `Delete !${c.name}`, onclick: (e: Event) => busy(e.currentTarget as HTMLButtonElement, async () => { await del(`/api/commands/${c.id}`); await load(); }) }, icon("trash", 15), "Delete"))))))))
          : empty("terminal", items.length ? "No commands match." : "No commands yet. Add your first one."));
      foldChildren(rowsBox.querySelector("tbody"), "commands", 12);
      };
      drawRows();
      mount(listBox,
        h("div", { class: "toolbar" }, h("div", { class: "input-icon" }, icon("search", 16), search), h("span", { class: "chip" }, `${items.length} custom`)),
        rowsBox,
        builtin.length ? h("div", { class: "body" }, h("div", { class: "muted small", style: "margin-bottom:6px" }, "Built in"), h("div", { class: "row", style: "gap:6px" }, builtin.map((b) => h("span", { class: "chip mono" }, "!" + b)))) : null);
    };

    // ================================================================== auto-replies
    const replyEditor = (t?: Trigger) => {
      const phrase = h("input", { type: "text", value: t?.phrase ?? "", required: true, maxLength: 200, placeholder: "gm" });
      const resp = h("textarea", { required: true, maxLength: 500, placeholder: "Good morning! Glad you are here." }, t?.response ?? "");
      let match: string = t?.match_type ?? "exact";
      const matchSeg = segButtons([["exact", "The whole message"], ["word", "Contains the word or phrase"]], () => match, (v) => { match = v; hint(); }, "Match");
      const matchHint = h("p", { class: "muted small" });
      const hint = () => { matchHint.textContent = match === "exact" ? "Replies only when the message is exactly this. Capital letters and extra spaces do not matter. \"gm\" matches \"GM\" but not \"gm chat\"." : "Replies when the word or phrase appears anywhere in a message, as a whole word. \"discord\" matches \"got a discord?\" but not \"discordant\"."; };
      hint();
      const mention = h("input", { type: "checkbox", class: "switch", checked: t?.mention ?? true, "aria-label": "Mention the viewer" });
      const lvl = h("select", null, levels.map((l) => h("option", { value: l, selected: (t?.userlevel ?? "everyone") === l }, l)));
      const cd = numInput(t?.cooldown ?? 30, 0, 86400, "Cooldown");
      const ucd = numInput(t?.user_cooldown ?? 60, 0, 86400, "Per person cooldown");
      const en = h("input", { type: "checkbox", class: "switch", checked: t?.enabled ?? true, "aria-label": "Enabled" });
      const pv = livePreview(resp);
      const save = h("button", { class: "btn primary", type: "submit" }, icon("check", 16), t ? "Save changes" : "Add auto-reply");
      const holder: { close: () => void } = { close: () => undefined };
      const form = h("form", { class: "stack", onsubmit: (e: Event) => {
        e.preventDefault();
        const body = { phrase: phrase.value, response: resp.value, match_type: match, mention: mention.checked, userlevel: lvl.value, cooldown: Number(cd.value), user_cooldown: Number(ucd.value), enabled: en.checked };
        busy(save, async () => { t ? await patch(`/api/triggers/${t.id}`, body) : await post("/api/triggers", body); await load(); holder.close(); }, "Saved");
      } },
        h("label", { class: "field" }, "When a viewer sends", phrase),
        h("div", null, h("div", { class: "field-title" }, "Match"), matchSeg, matchHint),
        h("label", { class: "field" }, "The bot replies", resp),
        variableChips(resp, pv.update), pv.el,
        h("label", { class: "check" }, mention, h("span", null, "Mention the viewer ", h("span", { class: "muted small" }, "(adds @name unless the reply already uses $(user))"))),
        h("div", { class: "form-grid" }, h("label", { class: "field" }, "Who can trigger it", lvl), h("label", { class: "field" }, "Cooldown (seconds, everyone)", cd), h("label", { class: "field" }, "Cooldown (seconds, per person)", ucd)),
        h("div", { class: "row between" }, h("label", { class: "check" }, en, "Enabled"), h("span", { class: "row" }, h("button", { class: "btn ghost", type: "button", onclick: () => holder.close() }, "Cancel"), save)));
      holder.close = sheet(t ? "Edit auto-reply" : "New auto-reply", form).close;
      if (t) pv.update();
    };

    const drawReplies = () => {
      mount(replyBox,
        triggersOn ? null : h("div", { class: "banner" }, icon("info", 18), h("span", null, "Auto-replies are switched off in Settings (TRIGGERS_ENABLED). Your rules are saved but the bot will not answer.")),
        h("div", { class: "card-note" }, "When a viewer sends the phrase, the bot answers. Commands that start with ! always take priority, and the bot answers at most once per message."),
        triggers.length ? h("div", { class: "cards-grid" }, triggers.map((t) => h("div", { class: `item-card${t.enabled ? "" : " off"}` },
          h("div", { class: "row between nowrap" }, h("span", { class: "meta" }, icon("quote", 16), h("strong", { style: "overflow-wrap:anywhere" }, t.phrase)),
            h("input", { type: "checkbox", class: "switch", checked: t.enabled, "aria-label": `Enable auto-reply for ${t.phrase}`, onchange: (e: Event) => void patch(`/api/triggers/${t.id}`, { enabled: (e.target as HTMLInputElement).checked }).then(load).catch((x) => toast(x.message, "error")) })),
          h("div", { class: "meta" }, h("span", { class: "chip accent" }, t.match_type === "exact" ? "exact message" : "contains word"), h("span", { class: "chip" }, t.userlevel), t.mention ? h("span", { class: "chip" }, "mentions viewer") : null),
          h("div", { class: "say-text" }, icon("reply", 14), " ", t.response),
          h("div", { class: "muted small" }, `Used ${plural(t.hits, "time")}. Cooldown ${duration(t.cooldown)} / ${duration(t.user_cooldown)} per person.`),
          h("div", { class: "row", style: "gap:6px" }, h("button", { class: "btn small ghost", "aria-label": `Edit auto-reply for ${t.phrase}`, onclick: () => replyEditor(t) }, icon("pencil", 15), "Edit"),
            h("button", { class: "btn small danger", "aria-label": `Delete auto-reply for ${t.phrase}`, onclick: (e: Event) => busy(e.currentTarget as HTMLButtonElement, async () => { await del(`/api/triggers/${t.id}`); await load(); }) }, icon("trash", 15), "Delete")))))
          : h("div", { class: "empty" }, icon("reply", 30), h("span", null, "No auto-replies yet."), h("span", { class: "small" }, "Example: when a viewer sends \"gm\", the bot says \"@Ann Good morning!\""),
            h("button", { class: "btn primary", type: "button", onclick: () => replyEditor() }, icon("plus", 16), "Create the first one")));
    };

    // ================================================================== timers
    const timerEditor = (t?: Timer) => {
      let timeOn = t ? t.interval_seconds > 0 : true;
      let linesOn = t ? t.min_lines > 0 : true;
      let mode: string = t?.match_mode ?? "all";
      let repeat: string = !t || t.max_runs === 0 ? "repeat" : t.max_runs === 1 ? "once" : "limited";
      const name = h("input", { type: "text", value: t?.name ?? "", required: true, maxLength: 32, placeholder: "social" });
      const msg = h("textarea", { required: true, maxLength: 500, placeholder: "Follow the channel so you never miss a stream!" }, t?.message ?? "");
      const minutes = numInput(t && t.interval_seconds ? Math.round(t.interval_seconds / 60) : 15, 1, 1440, "Minutes");
      const lines = numInput(t && t.min_lines ? t.min_lines : 10, 1, 1000, "Chat lines");
      const limit = numInput(t && t.max_runs > 1 ? t.max_runs : 3, 2, 1000, "Number of posts");
      const timeSw = h("input", { type: "checkbox", class: "switch", checked: timeOn, "aria-label": "Post after a time" });
      const linesSw = h("input", { type: "checkbox", class: "switch", checked: linesOn, "aria-label": "Post after chat lines" });
      const en = h("input", { type: "checkbox", class: "switch", checked: t?.enabled ?? false, "aria-label": "Switch on" });
      const timeBox = h("div", { class: "when-opt" }, h("div", { class: "row" }, h("span", null, h("strong", null, "After a time"), h("div", { class: "muted small" }, "Minutes between posts")), timeSw), h("label", { class: "field" }, "Every (minutes)", minutes));
      const linesBox = h("div", { class: "when-opt" }, h("div", { class: "row" }, h("span", null, h("strong", null, "After chat lines"), h("div", { class: "muted small" }, "Posts only while chat is active")), linesSw), h("label", { class: "field" }, "After (chat lines)", lines));
      const modeBox = h("div");
      const modeSegBuild = () => segButtons([["all", "Both must happen"], ["any", "Whichever comes first"]], () => mode, (v) => { mode = v; sync(); }, "How time and lines combine");
      const limitBox = h("label", { class: "field" }, "Number of posts", limit);
      const summary = h("div", { class: "summary-line" }, icon("info", 18), h("span", null, ""));
      const pv = livePreview(msg);
      const sync = () => {
        timeOn = timeSw.checked; linesOn = linesSw.checked;
        minutes.disabled = !timeOn; lines.disabled = !linesOn;
        timeBox.classList.toggle("on", timeOn); linesBox.classList.toggle("on", linesOn);
        mount(modeBox, timeOn && linesOn ? h("div", null, h("div", { class: "field-title" }, "When both are set"), modeSegBuild()) : null);
        limitBox.hidden = repeat !== "limited";
        const runs = repeat === "repeat" ? 0 : repeat === "once" ? 1 : Math.max(2, Number(limit.value) || 2);
        (summary.lastElementChild as HTMLElement).textContent = describeSchedule(timeOn ? Math.max(1, Number(minutes.value) || 1) * 60 : 0, linesOn ? Math.max(1, Number(lines.value) || 1) : 0, mode, runs);
      };
      const keepOne = (self: HTMLInputElement, other: HTMLInputElement) => () => { if (!self.checked && !other.checked) { self.checked = true; toast("A timer needs a time, chat lines, or both.", "error"); } sync(); };
      timeSw.onchange = keepOne(timeSw, linesSw);
      linesSw.onchange = keepOne(linesSw, timeSw);
      for (const i of [minutes, lines, limit]) i.addEventListener("input", sync);
      const presets: { label: string; apply: () => void }[] = [
        { label: "Every 15 min", apply: () => { timeSw.checked = true; linesSw.checked = false; minutes.value = "15"; repeat = "repeat"; } },
        { label: "Every 30 min, if chat is active", apply: () => { timeSw.checked = true; linesSw.checked = true; minutes.value = "30"; lines.value = "10"; mode = "all"; repeat = "repeat"; } },
        { label: "Every 25 chat lines", apply: () => { timeSw.checked = false; linesSw.checked = true; lines.value = "25"; repeat = "repeat"; } },
        { label: "Once, in 10 min", apply: () => { timeSw.checked = true; linesSw.checked = false; minutes.value = "10"; repeat = "once"; } },
      ];
      const presetRow = h("div", { class: "row", style: "gap:6px" }, presets.map((p) => h("button", { class: "chip", type: "button", style: "cursor:pointer", onclick: () => { p.apply(); mount(repeatHolder, repeatSegBuild()); sync(); } }, p.label)));
      const repeatHolder = h("div");
      const repeatSegBuild = () => segButtons([["repeat", "Keep repeating"], ["once", "Post once"], ["limited", "Post a few times"]], () => repeat, (v) => { repeat = v; sync(); }, "Repeat");
      mount(repeatHolder, repeatSegBuild());
      const save = h("button", { class: "btn primary", type: "submit" }, icon("check", 16), t ? "Save changes" : "Add timer");
      const holder: { close: () => void } = { close: () => undefined };
      const form = h("form", { class: "stack", onsubmit: (e: Event) => {
        e.preventDefault();
        const body = { name: name.value, message: msg.value, interval_seconds: timeOn ? Math.max(1, Number(minutes.value)) * 60 : 0, min_lines: linesOn ? Math.max(1, Number(lines.value)) : 0,
          match_mode: mode, max_runs: repeat === "repeat" ? 0 : repeat === "once" ? 1 : Math.max(2, Number(limit.value)), enabled: en.checked };
        busy(save, async () => { t ? await patch(`/api/timers/${t.id}`, body) : await post("/api/timers", body); await load(); holder.close(); }, "Saved");
      } },
        h("div", { class: "form-grid" }, h("label", { class: "field" }, "Name", name), h("label", { class: "field wide" }, "Message", msg)),
        variableChips(msg, pv.update), pv.el,
        h("div", null, h("div", { class: "field-title" }, "When should it post?"), presetRow),
        h("div", { class: "when-grid" }, timeBox, linesBox), modeBox,
        h("div", null, h("div", { class: "field-title" }, "How often"), repeatHolder, h("div", { style: "margin-top:10px" }, limitBox)),
        summary,
        h("div", { class: "row between" }, h("label", { class: "check" }, en, "Switch on now"), h("span", { class: "row" }, h("button", { class: "btn ghost", type: "button", onclick: () => holder.close() }, "Cancel"), save)));
      holder.close = sheet(t ? `Edit timer ${t.name}` : "New timer", form).close;
      sync();
      if (t) pv.update();
    };

    const drawTimers = () => {
      mount(timerBox,
        h("div", { class: "card-note" }, "Timers post on their own, only while the stream is live. Use a time, a number of chat lines, or both, and choose whether a timer repeats or posts just once."),
        timers.length ? h("div", { class: "cards-grid" }, timers.map((t) => {
          const left = t.max_runs > 1 && t.enabled ? Math.max(0, t.max_runs - t.runs) : 0;
          return h("div", { class: `item-card${t.enabled ? "" : " off"}` },
            h("div", { class: "row between nowrap" }, h("span", { class: "meta" }, icon("timer", 16), h("strong", null, t.name)),
              h("input", { type: "checkbox", class: "switch", checked: t.enabled, "aria-label": `Switch ${t.name} ${t.enabled ? "off" : "on"}`, onchange: (e: Event) => void patch(`/api/timers/${t.id}`, { enabled: (e.target as HTMLInputElement).checked }).then(load).catch((x) => { toast(x.message, "error"); void load(); }) })),
            h("div", { class: "say-text" }, t.message),
            h("div", { class: "meta" },
              t.interval_seconds ? h("span", { class: "chip accent" }, icon("clock", 12), `every ${duration(t.interval_seconds)}`) : null,
              t.min_lines ? h("span", { class: "chip accent" }, icon("message", 12), `${plural(t.min_lines, "line")}`) : null,
              t.interval_seconds && t.min_lines ? h("span", { class: "chip" }, t.match_mode === "any" ? "either" : "both") : null,
              h("span", { class: "chip" }, t.max_runs === 0 ? "repeats" : t.max_runs === 1 ? "once" : `${t.max_runs} times${left ? `, ${left} left` : ""}`)),
            h("div", { class: "muted small" }, describeSchedule(t.interval_seconds, t.min_lines, t.match_mode, t.max_runs)),
            h("div", { class: "muted small" }, t.fired ? `Posted ${plural(t.fired, "time")}${t.last_fired ? `, last ${ago(t.last_fired)}` : ""}.` : "Not posted yet."),
            h("div", { class: "row", style: "gap:6px" },
              h("button", { class: "btn small primary", "aria-label": `Post ${t.name} now`, onclick: (e: Event) => busy(e.currentTarget as HTMLButtonElement, async () => { await post(`/api/timers/${t.id}/send`); }, "Posted to chat") }, icon("send", 15), "Post now"),
              h("button", { class: "btn small ghost", "aria-label": `Edit ${t.name}`, onclick: () => timerEditor(t) }, icon("pencil", 15), "Edit"),
              h("button", { class: "btn small danger", "aria-label": `Delete ${t.name}`, onclick: (e: Event) => busy(e.currentTarget as HTMLButtonElement, async () => { await del(`/api/timers/${t.id}`); await load(); }) }, icon("trash", 15), "Delete")));
        }))
          : h("div", { class: "empty" }, icon("timer", 30), h("span", null, "No timers yet."), h("button", { class: "btn primary", type: "button", onclick: () => timerEditor() }, icon("plus", 16), "Create a timer")));
    };

    // ================================================================== page
    const load = async () => {
      const [c, tm, tr] = await Promise.all([
        get<{ items: Cmd[]; builtin: string[]; levels: string[] }>("/api/commands"),
        get<{ items: Timer[] }>("/api/timers"),
        get<{ items: Trigger[]; enabled: boolean }>("/api/triggers"),
      ]);
      levels = c.levels; builtin = c.builtin; items = c.items; timers = tm.items; triggers = tr.items; triggersOn = tr.enabled;
      drawList(); drawReplies(); drawTimers(); drawTabs();
      foldChildren(replyBox.querySelector(".cards-grid"), "auto-replies", 8); foldChildren(timerBox.querySelector(".cards-grid"), "timers", 8);
    };

    const actions = h("div", { class: "row" });
    const tabsBox = h("div", { class: "scroll-x", style: "margin-bottom:16px" });
    const panes: Record<Tab, HTMLElement> = {
      commands: card("terminal", "Commands", listBox, { flush: true }),
      replies: card("reply", "Auto-replies", replyBox, { flush: true }),
      timers: card("timer", "Timers", timerBox, { flush: true }),
    };
    const drawTabs = () => {
      const label: Record<Tab, string> = { commands: `Commands (${items.length})`, replies: `Auto-replies (${triggers.length})`, timers: `Timers (${timers.length})` };
      const rail = h("div", { class: "seg-control", role: "tablist" }, (Object.keys(label) as Tab[]).map((k) =>
        h("button", { type: "button", role: "tab", "aria-selected": String(tab === k), onclick: () => { tab = k; replaceQuery(`tab=${k}`); drawTabs(); } }, label[k])));
      mount(tabsBox, rail);
      tabRail(rail, "commands-tabs");
      for (const [k, el] of Object.entries(panes)) el.hidden = k !== tab;
      const add: Record<Tab, [string, () => void]> = { commands: ["New command", () => editor()], replies: ["New auto-reply", () => replyEditor()], timers: ["New timer", () => timerEditor()] };
      mount(actions, h("button", { class: "btn primary", type: "button", onclick: add[tab][1] }, icon("plus", 16), add[tab][0]));
    };

    mount(root, pageHead("terminal", "Commands", "Commands answer viewers who type !something. Auto-replies answer exact phrases. Timers post on their own.", actions), tabsBox, panes.commands, panes.replies, panes.timers);
    drawTabs();
    void load().catch((e) => toast(e.message, "error"));
  },
};
