import { get, post } from "./api.js";
import { h, sheet, toast } from "./dom.js";
import { icon } from "./icons.js";
import { builtinVoices, devicePrefs, reader } from "./reader.js";
import { DEFAULT_RULES, KOKORO_VOICES, type Msg, type Rules } from "./reader-core.js";
import type { ChatLine } from "./chat-actions.js";

export async function loadRules(): Promise<Rules> {
  try { reader.rules = { ...DEFAULT_RULES, ...(await get<Rules>("/api/reader/rules")) }; } catch { /* keep the defaults */ }
  return reader.rules;
}
export async function saveRules(r: Rules): Promise<void> { reader.rules = await post<Rules>("/api/reader/rules", r); }

/**
 * The speaker control for the chat. 1.3.2: it is split in two so neither sits on top of chat lines any more:
 *  - `button` goes in the chat header, beside the rate and the expand button (icon only on a phone, with a label when there is room);
 *  - `note` is a thin status line (loading, errors, "3 waiting") that takes its own row under the toolbar and is hidden when empty.
 * Reading starts only when the button is tapped, because browsers block sound until then.
 */
export function readerControl(): { button: HTMLElement; note: HTMLElement; dispose: () => void } {
  const label = h("span", { class: "hide-narrow" }, "Read chat");
  const b = h("button", { class: "btn small reader-btn", type: "button", "aria-pressed": "false", title: "Read the chat aloud" }, icon("volumeOff", 15), label);
  const note = h("div", { class: "reader-note muted small wrap", role: "status", hidden: true });
  let lastIcon = "";
  let queued = false;
  const paintNow = () => {
    queued = false;
    const s = reader.state;
    const ic = s.running ? "volume" : "volumeOff";
    if (ic !== lastIcon) { lastIcon = ic; b.replaceChild(icon(ic, 15), b.firstChild as Node); }
    label.textContent = s.running ? "Reading" : "Read chat";
    b.setAttribute("aria-pressed", String(s.running));
    b.setAttribute("aria-label", s.running ? "Stop reading the chat" : "Read the chat aloud");
    b.classList.toggle("on", s.running);
    const t = s.loading || s.note || (s.running && (s.queued || s.spoken) ? `${s.queued} waiting · ${s.spoken} read` : "");
    if (note.textContent !== t) note.textContent = t;
    note.hidden = !t;
  };
  // the reader reports every line it takes in; draw at most once per frame so a busy chat never makes the page work harder
  const paint = () => { if (!queued) { queued = true; requestAnimationFrame(paintNow); } };
  b.onclick = () => { if (reader.state.running) reader.stop(); else void loadRules().then(() => reader.start()); };
  const off = reader.onChange(paint);          // released when the Desk is left, so redrawing the page never piles up listeners
  paintNow();
  return { button: b, note, dispose: off };
}

const item = (ic: string, label: string, run: () => void, close: () => void) => {
  const b = h("button", { class: "sheet-item", type: "button", style: "display:flex;gap:10px;align-items:center;width:100%;text-align:left;padding:12px 4px;background:none;border:0;border-top:1px solid var(--line);color:inherit;font:inherit;cursor:pointer" }, icon(ic, 18), h("span", null, label));
  b.onclick = () => { close(); run(); };
  return b;
};

async function setUser(m: ChatLine, mode: "always" | "never" | "voice" | "clear", voice = ""): Promise<void> {
  if (!m.author_id) { toast("This person has no ID yet.", "error"); return; }
  const rules = await loadRules(), users = { ...rules.users };
  if (mode === "clear") delete users[m.author_id]; else users[m.author_id] = { mode, voice, name: m.author_name };
  try { await saveRules({ ...rules, users }); toast(mode === "clear" ? `${m.author_name} follows the normal rules` : mode === "never" ? `${m.author_name} will not be read` : mode === "always" ? `${m.author_name} will always be read` : `${m.author_name} has their own voice`); } catch (e) { toast(e instanceof Error ? e.message : "Could not save", "error"); }
}

/** Items the reader adds to the chat action sheet. */
export function readerItems(m: ChatLine, close: () => void): HTMLElement[] {
  const cur = m.author_id ? reader.rules.users[m.author_id]?.mode : undefined;
  const pick = () => {
    const dev = devicePrefs();
    const options = dev.engine === "kokoro" ? KOKORO_VOICES.map(([id, l]) => [id, l] as [string, string]) : builtinVoices().map((v) => [v.voiceURI, `${v.name} (${v.lang})`] as [string, string]);
    const box = sheet(`Voice for ${m.author_name}`, h("div", null, ...(options.length ? options : [["", "No voices found on this device"] as [string, string]]).map(([id, l]) => item("volume", l, () => { if (id) void setUser(m, "voice", id); }, () => box.close()))));
  };
  return [
    item("volume", "Read this aloud now", () => { if (!reader.state.running) { toast("Tap Read chat first"); return; } reader.offer({ ...(m as Msg), verdict: "allow", ts: Date.now() / 1000 }); }, close),
    cur === "always" ? item("check", `Stop always reading ${m.author_name}`, () => void setUser(m, "clear"), close) : item("volume", `Always read ${m.author_name}`, () => void setUser(m, "always"), close),
    cur === "never" ? item("check", `Read ${m.author_name} again`, () => void setUser(m, "clear"), close) : item("volumeOff", `Never read ${m.author_name}`, () => void setUser(m, "never"), close),
    item("user", `Give ${m.author_name} their own voice`, pick, close),
  ];
}
