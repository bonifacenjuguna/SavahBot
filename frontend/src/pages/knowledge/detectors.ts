import { get, post } from "../../api.js";
import { debounce, h, mount, toast } from "../../dom.js";
import { icon } from "../../icons.js";
import { SIGNAL, autoGrow, niceName, plural, seg } from "../widgets.js";
import { DET_ICON, type DetectorInfo, MODES, type Mode, hrefFor, modeChip, setSetting } from "./common.js";

interface Row { id: string; title: string; signal: string; mode: Mode; ran: boolean; strength: number; weight: number; detail: string }
interface TestReply { results: Row[]; verdict: { score: number; action: string; signals: { name: string; weight: number }[] }; thresholds: { flag: number; delete: number }; mode: string }

const EXAMPLES = [
  { label: "Scam bait", text: "YouTube Support: your channel will be terminated, verify at youtube.com.verify-login.xyz" },
  { label: "Disguised", text: "fr33 r0bux giveaway, dm me" },
  { label: "Typo", text: "get your fre robxu here" },
  { label: "Swahili", text: "Umeshinda KSh 50,000, bonyeza link na utume pesa kupata zawadi" },
  { label: "Honest chat", text: "that boss fight was brutal but you handled it" },
];
const ACTION_WORD: Record<string, string> = { allow: "allowed", flag: "flagged", delete: "deleted", timeout: "timed out", ban: "banned" };

export function renderDetectors(root: HTMLElement): void {
  let detectors: DetectorInfo[] = [];
  let level = "everyone";

  // ---------------------------------------------------------------- try it here
  const text = h("textarea", { rows: 2, maxLength: 1000, placeholder: "Type or paste a chat message", "aria-label": "Message to try" }) as HTMLTextAreaElement;
  autoGrow(text, 200);
  const name = h("input", { type: "text", maxLength: 100, placeholder: "Chat name (optional, to test name checks)", "aria-label": "Chat name", autocomplete: "off" });
  const who = seg("Sent by", [{ id: "everyone", label: "Viewer" }, { id: "member", label: "Member" }, { id: "regular", label: "Regular" }], "everyone", (v) => { level = v; void run(); });
  const out = h("div", { class: "lab-result", "aria-live": "polite" });
  let seq = 0;
  const idle = () => mount(out, h("div", { class: "lab-idle" }, icon("gauge", 22), h("span", null, "Try a message. Every detector gives its opinion, even ones that are Off, and you can see what the bot would do.")));
  const run = async () => {
    const value = text.value;
    if (!value.trim() && !name.value.trim()) { seq++; idle(); return; }
    const mine = ++seq;
    out.classList.add("busy");
    try {
      const r = await post<TestReply>("/api/intel/test", { text: value, name: name.value, level });
      if (mine !== seq) return;
      const total = r.results.filter((x) => x.mode === "active").reduce((a, x) => a + x.weight, 0);
      mount(out,
        h("ul", { class: "probe" }, r.results.map((x) => h("li", { class: x.ran ? (x.weight > 0 ? "hit" : x.weight < 0 ? "trust" : "") : "skip" },
          h("span", { class: "pr-ico" }, icon(DET_ICON[x.id] ?? "sliders", 16)),
          h("span", { class: "pr-main" }, h("strong", null, x.title), h("span", { class: "muted small wrap" }, x.ran ? (x.detail || "Nothing found.") : x.detail)),
          h("span", { class: "pr-side" }, x.ran && x.weight !== 0 ? h("b", null, `${x.weight > 0 ? "+" : ""}${x.weight}`) : null, modeChip(x.mode))))),
        h("p", { class: "lab-sum" }, icon("shield", 16), h("span", null, `With the detectors that are Active, the bot would score this `, h("b", null, String(r.verdict.score)), ` and it would be `, h("b", null, ACTION_WORD[r.verdict.action] ?? r.verdict.action), total ? ` (detectors add ${total} points).` : ".")));
    } catch (e) { if (mine === seq) mount(out, h("div", { class: "banner error" }, icon("alert", 18), h("span", null, (e as Error).message))); }
    finally { if (mine === seq) out.classList.remove("busy"); }
  };
  const soon = debounce(() => void run(), 500);
  text.addEventListener("input", soon);
  name.addEventListener("input", soon);
  idle();
  const lab = h("section", { class: "wb lab-wb", "aria-label": "Try it here" }, h("h2", null, "Try it here"),
    h("p", { class: "lede" }, "Nothing is sent to chat and nothing is remembered."), text, name,
    h("div", { class: "mt-opt" }, h("span", { class: "mt-opt-label" }, "Sent by"), who.el),
    h("div", { class: "chip-row" }, h("span", { class: "muted small" }, "Try an example"), EXAMPLES.map((x) => h("button", { type: "button", class: "chip pick", onclick: () => { text.value = x.text; name.value = ""; text.dispatchEvent(new Event("input")); void run(); } }, x.label))), out);

  // ---------------------------------------------------------------- detector cards
  const list = h("div", { class: "det-grid" });
  const card = (d: DetectorInfo): HTMLElement => {
    const modeSeg = seg(`${d.title} mode`, MODES.map((m) => ({ id: m.id, label: m.label })), d.mode, async (v) => {
      if (await setSetting(`intel_${d.id}_mode`, v, `${d.title}: ${v}`)) { d.mode = v; paintCard(); } else modeSeg.set(d.mode);
    });
    const sens = h("input", { type: "range", min: "0", max: "1", step: "0.05", value: String(d.sensitivity), "aria-label": `${d.title} sensitivity` }) as HTMLInputElement;
    const sensVal = h("span", { class: "muted small" }, sensWord(d.sensitivity));
    sens.addEventListener("input", () => { sensVal.textContent = sensWord(Number(sens.value)); });
    sens.addEventListener("change", () => void setSetting(`intel_${d.id}_sensitivity`, Number(sens.value), `${d.title}: sensitivity saved`).then((ok) => { if (ok) d.sensitivity = Number(sens.value); }));
    const cap = h("input", { type: "number", min: "1", max: "100", step: "1", value: String(d.weight), "aria-label": `${d.title} most points` }) as HTMLInputElement;
    cap.addEventListener("change", () => { const n = Math.max(1, Math.min(100, Math.round(Number(cap.value) || d.weight))); cap.value = String(n); void setSetting(`intel_${d.id}_weight`, n, `${d.title}: most points saved`).then((ok) => { if (ok) d.weight = n; }); });
    const hint = h("p", { class: "muted small det-hint" });
    const paintCard = () => {
      hint.textContent = d.mode === "active" ? "Acting on chat. Findings add to the message score." : d.mode === "shadow" ? ((d.hits ?? 0) ? `${plural(d.hits ?? 0, "finding")} in the last day, none acted on. See them in the shadow report.` : "Watching quietly. Nothing found in the last day.") : "Not running.";
      el.dataset.mode = d.mode;
    };
    const el = h("article", { class: "det", "data-mode": d.mode },
      h("div", { class: "det-top" }, h("span", { class: "scn-ico" }, icon(DET_ICON[d.id] ?? "sliders", 22)), h("div", { class: "scn-title" }, h("strong", null, d.title), h("span", { class: "muted small" }, `Shows up as "${niceName(SIGNAL, d.signal)}"`))),
      h("p", { class: "scn-what" }, d.description), modeSeg.el, hint,
      h("div", { class: "det-knobs" },
        h("label", { class: "knob" }, h("span", null, "Sensitivity ", sensVal), sens, h("span", { class: "knob-ends" }, h("small", null, "Careful"), h("small", null, "Eager"))),
        h("label", { class: "knob small-knob" }, h("span", null, "Most points"), cap)),
      d.needs_history ? h("p", { class: "muted small" }, icon("info", 13), " Needs remembered chat, so the test box cannot try it on one message.") : null,
      h("a", { class: "link-quiet", href: hrefFor("shadow") }, icon("eyeOff", 14), "See its shadow findings"));
    paintCard();
    return el;
  };
  const load = async () => {
    const o = await get<{ detectors: DetectorInfo[] }>("/api/intel/overview?hours=24");
    detectors = o.detectors;
    mount(list, detectors.map(card));
  };
  mount(root, h("div", { class: "stack" },
    h("div", { class: "banner info" }, icon("info", 18), h("span", { class: "grow" }, "New detectors start in ", h("b", null, "Shadow"), ": they run and are logged, but never change what happens in chat. Switch one to ", h("b", null, "Active"), " when its shadow findings look right. Intelligence alone never times out or bans anyone.")),
    lab, list));
  void load().catch((e) => toast(e.message, "error"));
}

function sensWord(v: number): string { return v < 0.3 ? "(careful)" : v < 0.7 ? "(balanced)" : "(eager)"; }
