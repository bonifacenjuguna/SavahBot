import { api, apiBase, get, post, upload } from "../api.js";
import { busy, h, mount, toast } from "../dom.js";
import { builtinSupported, builtinVoices, DEFAULT_DEVICE, devicePrefs, reader, saveDevicePrefs, type DevicePrefs } from "../reader.js";
import { KOKORO_VOICES, type Rules } from "../reader-core.js";
import { loadRules, saveRules } from "../reader-ui.js";
import { empty, pageHead } from "./shared.js";
import type { Page } from "./types.js";

interface Voices { dir: string; writable: boolean; max_mb: number; used_bytes: number; volume_hint: string; host: string; files_base: string; packs: { name: string; files: number; bytes: number; list: string[] }[] }
const mb = (n: number) => `${(n / 1048576).toFixed(1)} MB`;

async function render(body: HTMLElement): Promise<void> {
  const rules = await loadRules();
  const vp = await get<Voices>("/api/voices");
  const dev = devicePrefs();
  const filesBase = vp.files_base.startsWith("http") ? vp.files_base : apiBase() + vp.files_base;   // the backend address the browser can reach
  const again = () => void render(body);
  const persist = async (r: Rules) => { try { await saveRules(r); toast("Saved"); } catch (e) { toast(e instanceof Error ? e.message : "Could not save", "error"); } };
  const row = (title: string, hint: string, control: Node) => h("div", { class: "row between", style: "align-items:center;gap:12px;padding:10px 0;border-top:1px solid var(--line)" }, h("div", { style: "min-width:0" }, h("strong", null, title), h("div", { class: "muted small wrap" }, hint)), control);
  const sw = (key: keyof Rules, label: string) => h("input", { type: "checkbox", class: "switch", checked: Boolean(rules[key]), "aria-label": label, onchange: (e: Event) => void persist({ ...rules, [key]: (e.target as HTMLInputElement).checked }) });
  const dsave = (p: Partial<DevicePrefs>) => { saveDevicePrefs({ ...devicePrefs(), ...p }); toast("Saved on this device"); };

  // --- this device
  const voiceSel = h("select", { "aria-label": "Voice", onchange: (e: Event) => dsave({ voice: (e.target as HTMLSelectElement).value }) }) as HTMLSelectElement;
  const fillVoices = () => {
    const d = devicePrefs();
    const opts: [string, string][] = d.engine === "kokoro" ? KOKORO_VOICES : builtinVoices().map((v) => [v.voiceURI, `${v.name} (${v.lang})`]);
    mount(voiceSel, h("option", { value: "" }, "Default voice"), ...opts.map(([id, l]) => h("option", { value: id, selected: d.voice === id }, l)));
  };
  fillVoices();
  if (builtinSupported()) speechSynthesis.onvoiceschanged = fillVoices;
  const engine = h("select", { "aria-label": "Voice engine", onchange: (e: Event) => { dsave({ engine: (e.target as HTMLSelectElement).value as DevicePrefs["engine"], voice: "" }); fillVoices(); } },
    h("option", { value: "builtin", selected: dev.engine === "builtin" }, "Built-in browser voices"), h("option", { value: "kokoro", selected: dev.engine === "kokoro" }, "Neural voice (Kokoro, free, downloads once)")) as HTMLSelectElement;
  const num = (k: "rate" | "volume", min: number, max: number, step: number) => h("input", { type: "range", min, max, step, value: String(dev[k]), "aria-label": k, onchange: (e: Event) => dsave({ [k]: Number((e.target as HTMLInputElement).value) } as Partial<DevicePrefs>) });
  const sources = [["", "The public model host (Hugging Face)"], ...(vp.host ? [[vp.host, "Your host link"] as [string, string]] : []), ...vp.packs.map((p) => [`${filesBase}${p.name}`, `Uploaded pack: ${p.name}`] as [string, string])];
  const source = h("select", { "aria-label": "Where the neural voice is downloaded from", onchange: (e: Event) => dsave({ source: (e.target as HTMLSelectElement).value }) },
    ...sources.map(([v, l]) => h("option", { value: v, selected: dev.source === v }, l)));
  const gpu = h("input", { type: "checkbox", class: "switch", checked: dev.gpu, "aria-label": "Use the graphics chip for the neural voice", onchange: (e: Event) => dsave({ gpu: (e.target as HTMLInputElement).checked }) });
  const test = h("button", { class: "btn small", type: "button" }, "Try this voice");
  test.onclick = () => void busy(test, async () => { if (!reader.state.running) await reader.start(); reader.offer({ author_name: "SavahBot", text: "This is how chat will sound.", level: "everyone", verdict: "allow", ts: Date.now() / 1000, author_id: "test" }); });

  // --- who to read
  const who = h("select", { "aria-label": "Who to read", onchange: (e: Event) => void persist({ ...rules, who: (e.target as HTMLSelectElement).value as Rules["who"] }) },
    ...([["everyone", "Everyone"], ["mods", "Moderators and the owner"], ["members", "Members, moderators and the owner"], ["owner", "Only the owner"], ["chosen", "Only people I marked Always read"], ["prefix", "Messages that start with a word"]] as const).map(([k, l]) => h("option", { value: k, selected: rules.who === k }, l)));
  const prefix = h("input", { type: "text", value: rules.prefix, maxlength: 20, style: "width:110px", "aria-label": "Trigger word", onchange: (e: Event) => void persist({ ...rules, prefix: (e.target as HTMLInputElement).value }) });
  const numRule = (key: "shorten" | "drop_backlog", min: number, max: number, unit: string) => h("span", { class: "row", style: "gap:6px;align-items:center" }, h("input", { type: "number", min, max, value: String(rules[key]), style: "width:80px", "aria-label": unit, onchange: (e: Event) => { const n = Number((e.target as HTMLInputElement).value); if (n < min || n > max || !Number.isFinite(n)) { toast(`Use ${min} to ${max}`, "error"); return; } void persist({ ...rules, [key]: n }); } }), h("span", { class: "muted small" }, unit));

  // --- people
  const people = Object.entries(rules.users);
  const personRow = ([id, u]: [string, Rules["users"][string]]) => h("div", { class: "row between", style: "align-items:center;padding:8px 0;border-top:1px solid var(--line)" },
    h("span", null, h("strong", null, u.name || id), h("span", { class: "muted small" }, u.mode === "never" ? "  never read" : u.mode === "always" ? "  always read" : `  own voice (${u.voice})`)),
    h("button", { class: "btn ghost small", type: "button", onclick: () => { const users = { ...rules.users }; delete users[id]; void persist({ ...rules, users }).then(again); } }, "Remove"));

  // --- pronunciation
  const from = h("input", { type: "text", placeholder: "gg", maxlength: 40, "aria-label": "Written as", style: "width:110px" }) as HTMLInputElement;
  const to = h("input", { type: "text", placeholder: "good game", maxlength: 60, "aria-label": "Said as", style: "flex:1;min-width:120px" }) as HTMLInputElement;
  const addWord = h("button", { class: "btn small primary", type: "button" }, "Add");
  addWord.onclick = () => { if (!from.value.trim() || !to.value.trim()) { toast("Fill both boxes", "error"); return; } void persist({ ...rules, dictionary: [...rules.dictionary, { from: from.value.trim(), to: to.value.trim() }] }).then(again); };

  // --- voice packs
  const pack = h("input", { type: "text", value: "kokoro", maxlength: 48, "aria-label": "Pack name", style: "width:140px" }) as HTMLInputElement;
  const pick = h("input", { type: "file", multiple: true, accept: ".zip,.onnx,.json,.bin,.wav,.txt", "aria-label": "Choose voice files" }) as HTMLInputElement;
  const progress = h("p", { class: "muted small" });
  const send = h("button", { class: "btn primary small", type: "button" }, "Upload");
  send.onclick = () => void busy(send, async () => {
    const files = [...(pick.files ?? [])];
    if (!files.length) { toast("Choose files first", "error"); return; }
    if (!apiBase() && files.some((f) => f.size > 4 * 1048576)) { toast("Large uploads must go straight to the backend. Set the backend address on the sign-in screen first.", "error"); return; }
    try {
      for (const [i, f] of files.entries()) {
        progress.textContent = `Uploading ${i + 1} of ${files.length}: ${f.name}`;
        if (f.name.toLowerCase().endsWith(".zip")) await upload(`/api/voices/zip?pack=${encodeURIComponent(pack.value)}`, f);
        else await upload(`/api/voices/file?pack=${encodeURIComponent(pack.value)}&path=${encodeURIComponent(((f as File & { webkitRelativePath?: string }).webkitRelativePath || f.name))}`, f);
      }
      progress.textContent = ""; toast("Uploaded"); again();
    } catch (e) { progress.textContent = ""; toast(e instanceof Error ? e.message : "Upload failed", "error"); }
  });
  const host = h("input", { type: "url", value: vp.host, placeholder: "https://example.com/my-voice-files", "aria-label": "Link to your own voice files", style: "width:100%" }) as HTMLInputElement;
  const saveHost = h("button", { class: "btn small", type: "button" }, "Save link");
  saveHost.onclick = () => void busy(saveHost, async () => { try { await post("/api/voices/host", { url: host.value }); toast("Saved"); again(); } catch (e) { toast(e instanceof Error ? e.message : "Could not save", "error"); } });

  mount(body,
    h("div", { class: "sp-card" }, h("h3", null, "Voice on this device"),
      h("p", { class: "muted small wrap" }, "The reader only starts when you tap Read chat on the Desk, because browsers do not allow sound before you interact. These choices are remembered on this device only."),
      row("Engine", "If the neural voice cannot load, reading continues with the built-in voice and says why.", engine),
      row("Voice", builtinSupported() ? "Voices come from your device and browser." : "This browser has no built-in voices.", voiceSel),
      row("Speed", "", num("rate", 0.6, 1.6, 0.1)), row("Volume", "", num("volume", 0.1, 1, 0.1)),
      row("Neural voice comes from", "Used only by the neural engine. Pick one of your uploads or links below if the public host is blocked for you.", source),
      row("Faster mode (graphics chip)", "Neural voice only. Uses the phone's graphics chip when the browser allows it, which can be several times faster, but downloads a larger file (about 300 MB, one time) and ignores uploaded packs. If it cannot start, the normal processor is used. Takes effect the next time you tap Read chat.", gpu),
      h("div", { style: "padding-top:8px" }, test)),
    h("div", { class: "sp-card" }, h("h3", null, "Who to read"),
      row("Read", "Messages held, flagged or blocked by moderation are never read. Moderators and the owner are who the platform says they are.", who),
      rules.who === "prefix" ? row("Trigger word", "Only messages starting with this are read, without the word.", prefix) : null,
      row("Skip older than", "When the reader is behind, lines older than this are dropped so it keeps up with the chat. 0 reads everything.", numRule("drop_backlog", 0, 300, "seconds")),
      h("p", { class: "muted small" }, "To pick people: open the action sheet on one of their messages in the chat and choose Always read, Never read or Give their own voice.")),
    h("div", { class: "sp-card" }, h("h3", null, "What is said"),
      row("Say the name first", "“Sam says …”", sw("say_name", "Say the name first")), row("Skip links", "A link is read as the word “link”.", sw("skip_links", "Skip links")),
      row("Skip emoji", "Emoji are not read out.", sw("skip_emoji", "Skip emoji")), row("Collapse repeats", "“noooooo” and “spam spam spam” are shortened.", sw("collapse_repeats", "Collapse repeats")),
      row("Shorten long messages", "Cut after this many characters and add “and more”.", numRule("shorten", 20, 500, "characters"))),
    h("div", { class: "sp-card" }, h("h3", null, "People with their own rule"),
      people.length ? h("div", null, ...people.map(personRow)) : empty("user", "Nobody yet. Set it from a message in the chat.")),
    h("div", { class: "sp-card" }, h("h3", null, "Pronunciation"),
      h("p", { class: "muted small" }, "Teach the reader how to say a word or a name."),
      ...rules.dictionary.map((d, i) => h("div", { class: "row between", style: "padding:6px 0;border-top:1px solid var(--line)" }, h("span", null, `${d.from} → ${d.to}`), h("button", { class: "btn ghost small", type: "button", onclick: () => void persist({ ...rules, dictionary: rules.dictionary.filter((_, j) => j !== i) }).then(again) }, "Remove"))),
      h("div", { class: "row wrap", style: "gap:8px;margin-top:8px" }, from, to, addWord)),
    h("div", { class: "sp-card" }, h("h3", null, "Voice packs"),
      h("p", { class: "muted small wrap" }, "A fallback for when the neural voice cannot be downloaded from the public host. Upload the files of the Kokoro model (config.json, tokenizer.json, tokenizer_config.json, onnx/model_quantized.onnx and voices/*.bin) keeping those folder names, or one zip of them. Then choose the pack above under Neural voice comes from."),
      h("p", { class: "muted small wrap" }, `Stored at ${vp.dir} on the backend. ${mb(vp.used_bytes)} of ${vp.max_mb} MB used. ${vp.writable ? "" : "This folder is not writable, so uploads will fail. "}${vp.volume_hint}`),
      h("div", { class: "row wrap", style: "gap:8px;align-items:center" }, h("label", { class: "muted small" }, "Pack name ", pack), pick, send), progress,
      ...vp.packs.map((p) => h("div", { class: "row between", style: "padding:8px 0;border-top:1px solid var(--line)" }, h("span", { class: "wrap" }, h("strong", null, p.name), h("span", { class: "muted small" }, `  ${p.files} files, ${mb(p.bytes)}`)),
        h("button", { class: "btn ghost small", type: "button", onclick: () => { if (confirm(`Delete the pack ${p.name}?`)) void api("POST", "/api/voices/delete", { pack: p.name }).then(() => { toast("Deleted"); again(); }); } }, "Delete"))),
      h("label", { class: "field", style: "margin-top:10px" }, "Or a link to files you host yourself (https)", host), saveHost,
      h("p", { class: "muted small wrap" }, "A link is downloaded by your browser, not by the server. The host must allow cross-origin requests.")));
  void DEFAULT_DEVICE;
}

export const readerSettings: Page = {
  id: "reader", title: "Chat reader", icon: "volume", blurb: "Read chat aloud with built-in or neural voices",
  render(root) {
    const body = h("div", { class: "stack" }, h("p", { class: "muted" }, "Loading…"));
    mount(root, h("div", { class: "page" }, pageHead("volume", "Chat reader", "Reads your chat out loud while you are on the Desk.", h("a", { class: "btn small", href: "/settings" }, "Back to Settings")), body));
    void render(body).catch(() => mount(body, empty("alert", "The reader settings could not load.")));
  },
};
