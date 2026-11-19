/** SavahLive (1.6.0): the control room for the Android overlay app. Pair phones, see who is connected, tune what the overlay shows, remove a phone.
 *  SavahBot does the work; this page only manages the link. Everything the phone shows is produced by the backend. */
import { del, get, patch, post } from "../api.js";
import { ago, busy, copyButton, dateTime, h, mount, sheet, toast } from "../dom.js";
import { icon } from "../icons.js";
import { areaNav } from "./kit.js";
import type { Page } from "./types.js";
import { seg } from "./widgets.js";

interface Phone { id: string; name: string; created: number; last_seen: number; expires: number | null; app_version: string; online: boolean; status: "active" | "expired" }
interface Prefs {
  enabled: boolean; max_devices: number; max_feeds: number; chat_lines: number; peek_seconds: number; font_size: number; hide_seconds: number;
  hide_bots: boolean; hide_flagged: boolean; only_special: boolean; rotate_days: number; idle_unpair_days: number; track_stats: boolean; download_url: string;
}
interface Overview {
  enabled: boolean; protocol: number; server: string; server_is_public: boolean; devices: Phone[]; connected: number;
  state: { mode: string; live: boolean; title: string }; settings: Prefs; stats_seconds: number; dashboard_clients: number; dashboard_limit: number; now: number;
}
interface Made { code: string; shown: string; expires: number; link: string; app_link: string; server: string; qr: string }

const fail = (e: unknown) => toast(e instanceof Error ? e.message : String(e), "error");
const EXPIRY: { id: string; label: string }[] = [{ id: "0", label: "Until I remove it" }, { id: "30", label: "30 days" }, { id: "7", label: "7 days" }, { id: "1", label: "24 hours" }];

const stateWord = (s: Overview["state"]): string => (s.mode === "demo" ? "Demo" : s.live ? "On air" : "Standby");

// ---- small controls ---------------------------------------------------------------------------------------------------------------------------
function chip(label: string, tone: "" | "ok" | "bad"): HTMLElement {
  return h("span", { class: `sl-chip${tone ? " " + tone : ""}` }, label);
}

function switchEl(on: boolean, label: string, onChange: (v: boolean) => void): HTMLButtonElement {
  const b = h("button", { type: "button", class: "sl-switch", role: "switch", "aria-checked": String(on), "aria-label": label });
  b.addEventListener("click", () => {
    const v = b.getAttribute("aria-checked") !== "true";
    b.setAttribute("aria-checked", String(v));
    onChange(v);
  });
  return b;
}

function optRow(title: string, help: string, control: Node): HTMLElement {
  return h("div", { class: "sl-opt" }, h("div", null, h("b", null, title), h("small", null, help)), control);
}

function rangeRow(title: string, help: string, min: number, max: number, value: number, fmt: (n: number) => string, onChange: (n: number) => void): HTMLElement {
  const out = h("output", null, fmt(value));
  const input = h("input", { type: "range", min: String(min), max: String(max), step: "1", value: String(value), "aria-label": title });
  input.addEventListener("input", () => {
    const n = Number(input.value);
    out.textContent = fmt(n);
    onChange(n);
  });
  return h("div", { class: "sl-range" }, h("div", { class: "sl-range-head" }, h("b", null, title), out), input, h("small", null, help));
}

function stepRow(title: string, help: string, min: number, max: number, value: number, fmt: (n: number) => string, onChange: (n: number) => void): HTMLElement {
  let v = value;
  const out = h("output", null, fmt(v));
  const set = (n: number) => {
    v = Math.max(min, Math.min(max, n));
    out.textContent = fmt(v);
    onChange(v);
  };
  const minus = h("button", { type: "button", "aria-label": `Less: ${title}` }, "\u2212");
  const plus = h("button", { type: "button", "aria-label": `More: ${title}` }, "+");
  minus.addEventListener("click", () => set(v - 1));
  plus.addEventListener("click", () => set(v + 1));
  return optRow(title, help, h("div", { class: "sl-step" }, minus, out, plus));
}

/** A button that asks twice: the first tap arms it ("Tap again to remove"), the second does it. It disarms itself after a few seconds. */
function armButton(label: string, armedLabel: string, run: () => Promise<unknown>): HTMLButtonElement {
  let armed = false;
  let timer = 0;
  const b = h("button", { type: "button", class: "sl-btn small danger" });
  const rest = () => { armed = false; b.classList.remove("armed"); mount(b, icon("trash", 15), label); };
  rest();
  b.addEventListener("click", () => {
    if (!armed) {
      armed = true;
      b.classList.add("armed");
      mount(b, icon("check", 15), armedLabel);
      timer = window.setTimeout(rest, 3500);
      return;
    }
    window.clearTimeout(timer);
    busy(b, async () => { await run(); rest(); });
  });
  return b;
}

export const savahlive: Page = {
  id: "savahlive",
  title: "SavahLive",
  icon: "smartphone",
  blurb: "Pair the Android overlay and choose what it shows",
  render(root) {
    let ov: Overview | null = null;
    let draft: Prefs | null = null;
    let dirty = false;
    let alive = true;
    let closePair: (() => void) | null = null;

    const heroBox = h("div");
    const warnBox = h("div", { class: "sl-warns" });
    const phonesBox = h("div");
    const settingsBox = h("div");
    const previewBox = h("div");
    const connBox = h("div");
    const saveBar = h("div", { class: "sl-savebar" });
    saveBar.hidden = true;

    // ------------------------------------------------------------------ top: hero, status, warnings
    function drawTop(): void {
      if (!ov) return;
      const o = ov;
      const pairBtn = h("button", { type: "button", class: "sl-btn primary" }, icon("plus", 18), "Pair a phone") as HTMLButtonElement;
      pairBtn.onclick = () => openPair();
      const actions = h("div", { class: "sl-actions" }, pairBtn);
      if (o.settings.download_url) {
        actions.append(h("a", { class: "sl-btn", href: o.settings.download_url, target: "_blank", rel: "noopener" }, icon("download", 18), "Download the app"));
      }
      mount(heroBox, h("section", { class: "sl-hero" },
        h("div", { class: "sl-hero-top" },
          h("div", { class: "sl-mark", "aria-hidden": "true" }, icon("smartphone", 28)),
          h("div", null, h("h1", null, "Savah", h("b", null, "Live")), h("p", null, "Float your stream's chat, viewers and likes over any game on your Android phone. Pair once, then it just works."))),
        actions,
        h("div", { class: "sl-stats" },
          h("div", { class: "sl-stat" }, h("small", null, o.devices.length === 1 ? "Phone paired" : "Phones paired"), h("b", null, String(o.devices.length))),
          h("div", { class: `sl-stat${o.connected ? " ok" : ""}` }, h("small", null, "Connected now"), h("b", null, String(o.connected))),
          h("div", { class: `sl-stat${o.state.live ? " ok" : ""}` }, h("small", null, "SavahBot is"), h("b", null, stateWord(o.state))))));

      const warns: HTMLElement[] = [];
      const warn = (text: string, action?: { label: string; patch: Partial<Prefs> }) => {
        const row = h("div", { class: "sl-warn" }, icon("alert", 18), h("span", null, text));
        if (action) {
          const b = h("button", { type: "button", class: "sl-btn small" }, action.label) as HTMLButtonElement;
          b.onclick = () => busy(b, async () => { ov = await post<Overview>("/api/savahlive/settings", action.patch); draft = { ...ov.settings }; drawAll(); });
          row.append(b);
        }
        warns.push(row);
      };
      if (!o.enabled) warn("SavahLive is switched off, so no phone can connect.", { label: "Switch on", patch: { enabled: true } });
      if (o.server.startsWith("http://") && !/localhost|127\.0\.0\.1/.test(o.server)) warn("Phones can only pair over HTTPS. Set PUBLIC_BASE_URL to your https:// backend address.");
      if (!o.settings.track_stats) warn("Viewers and likes are off, so the overlay shows chat only.", { label: "Turn on", patch: { track_stats: true } });
      mount(warnBox, warns);
    }

    // ------------------------------------------------------------------ phones
    function phoneCard(p: Phone): HTMLElement {
      const expired = p.status === "expired";
      const status = expired ? chip("Pairing ended", "bad") : p.online ? chip("Connected", "ok") : chip("Not connected", "");
      const edit = h("button", { type: "button", class: "sl-btn small" }, icon("pencil", 15), "Edit") as HTMLButtonElement;
      edit.onclick = () => editSheet(p);
      const remove = armButton("Remove", "Tap again to remove", async () => {
        try { await del(`/api/savahlive/devices/${p.id}`); toast(`${p.name} was unpaired`, "ok"); await load(false); } catch (e) { fail(e); }
      });
      const meta = (k: string, v: string) => h("div", null, h("dt", null, k), h("dd", null, v));
      return h("article", { class: "sl-phone" },
        h("div", { class: "sl-phone-top" },
          h("div", { class: "sl-avatar", "aria-hidden": "true" }, icon("smartphone", 22)),
          h("div", { style: "min-width:0" }, h("h3", null, p.name), h("div", { class: "sl-chips" }, status, p.app_version ? chip(`App ${p.app_version}`, "") : null))),
        h("dl", { class: "sl-meta" },
          meta("Paired", dateTime(p.created)),
          meta("Last seen", p.online ? "now" : ago(p.last_seen)),
          meta(expired ? "Ended" : "Stays paired", p.expires ? dateTime(p.expires) : "Until you remove it")),
        h("div", { class: "sl-row-actions" }, edit, remove));
    }

    function drawPhones(): void {
      if (!ov) return;
      const o = ov;
      const pair = h("button", { type: "button", class: "sl-btn primary" }, icon("plus", 18), "Pair a phone") as HTMLButtonElement;
      pair.onclick = () => openPair();
      mount(phonesBox, h("section", { class: "sl-section" },
        h("header", null, h("h2", null, icon("smartphone", 18), "Phones"), h("small", null, `${o.devices.length} of ${o.settings.max_devices}`)),
        o.devices.length
          ? h("div", { class: "sl-phones" }, o.devices.map(phoneCard))
          : h("div", { class: "sl-empty" },
            h("div", { class: "sl-avatar", "aria-hidden": "true" }, icon("smartphone", 28)),
            h("h3", null, "No phone paired yet"),
            h("p", null, "Install SavahLive on your Android phone, then pair it here. You only pair once: after that the phone stays paired until you remove it."),
            pair)));
    }

    // ------------------------------------------------------------------ settings (edited as a draft, saved together)
    function markDirty(): void {
      dirty = true;
      saveBar.hidden = false;
      drawPreview();
    }

    function drawSettings(): void {
      if (!draft || !ov) return;
      const d = draft;
      const o = ov;
      const secs = (n: number) => `${n} s`;
      mount(settingsBox, h("section", { class: "sl-section" },
        h("header", null, h("h2", null, icon("sliders", 18), "Overlay"), h("small", null, "Applies to every paired phone")),
        h("div", { class: "sl-body" },
          h("div", null,
            optRow("Hide bot messages", "Leaves out other bots and SavahBot's own replies.", switchEl(d.hide_bots, "Hide bot messages", (v) => { d.hide_bots = v; markDirty(); })),
            optRow("Hide flagged messages", "Leaves out messages moderation flagged or removed.", switchEl(d.hide_flagged, "Hide flagged messages", (v) => { d.hide_flagged = v; markDirty(); })),
            optRow("Members and moderators only", "Useful during a raid: only members, regulars, moderators and you.", switchEl(d.only_special, "Members and moderators only", (v) => { d.only_special = v; markDirty(); })),
            optRow("Track viewers and likes", `Reads them from YouTube about every ${o.stats_seconds} seconds (about 1 quota unit each time). Off means chat only.`, switchEl(d.track_stats, "Track viewers and likes", (v) => { d.track_stats = v; markDirty(); }))),
          h("div", null,
            rangeRow("Chat lines kept", "How many recent lines each phone keeps. The big panel scrolls through them.", 10, 100, d.chat_lines, (n) => String(n), (n) => { d.chat_lines = n; markDirty(); }),
            rangeRow("Text size", "Chat text size on the phone. Each phone can also adjust it from the panel.", 11, 22, d.font_size, (n) => `${n} px`, (n) => { d.font_size = n; markDirty(); }),
            rangeRow("Pop-out time", "How long new chat stays out of the tucked-away tab before it slides back.", 2, 15, d.peek_seconds, secs, (n) => { d.peek_seconds = n; markDirty(); }),
            rangeRow("Tab hides after", "How long the tab waits before sliding almost out of sight. 0 keeps it fully visible.", 0, 30, d.hide_seconds, (n) => (n === 0 ? "never" : secs(n)), (n) => { d.hide_seconds = n; markDirty(); })))));
      drawPreview();
    }

    function drawPreview(): void {
      if (!draft) return;
      const d = draft;
      const sample: { name: string; text: string; kind: "normal" | "member" | "mod" | "bot" | "flagged"; color: string }[] = [
        { name: "Amara", text: "wait, rewind that", kind: "normal", color: "#b8becc" },
        { name: "Kamau", text: "lol", kind: "member", color: "#4ade80" },
        { name: "SavahBot", text: "Welcome in! Type !rules", kind: "bot", color: "#b8becc" },
        { name: "spam123", text: "free followers click here", kind: "flagged", color: "#b8becc" },
        { name: "Wanjiru", text: "what's the plan for today?", kind: "mod", color: "#6ea8ff" },
        { name: "Imani", text: "haha", kind: "normal", color: "#b8becc" }];
      const visible = (k: string) => !(d.hide_bots && k === "bot") && !(d.hide_flagged && k === "flagged") && !(d.only_special && k !== "member" && k !== "mod");
      mount(previewBox, h("section", { class: "sl-section" },
        h("header", null, h("h2", null, icon("eye", 18), "Preview"), h("small", null, "How the panel reads")),
        h("div", { class: "sl-body" },
          h("div", { class: "sl-preview", style: `font-size:${d.font_size}px` },
            h("div", { class: "sl-pv-bar" }, icon("expand", 16), icon("dots", 18), icon("x", 16)),
            h("div", { class: "sl-pv-stats" }, h("span", null, h("i", { class: "dot" })), h("span", null, icon("eye", 16), "1.2K"), h("span", { style: "color:#ff4d55" }, icon("heart", 15), h("span", { style: "color:#f1f2f5" }, "345"))),
            sample.map((l) => h("div", { class: `sl-pv-line${visible(l.kind) ? "" : " gone"}` }, h("b", { style: `color:${l.color}` }, l.name), l.text))),
          h("small", { class: "muted" }, "Each phone has its own theme, see-through level and size, set from the three dots on the panel."))));
    }

    function drawConnection(): void {
      if (!draft || !ov) return;
      const d = draft;
      const o = ov;
      const url = h("input", { class: "sl-input", type: "url", placeholder: "https://github.com/.../SavahLive-1.6.0.apk", value: d.download_url, "aria-label": "App download link" });
      url.addEventListener("input", () => { d.download_url = url.value.trim(); markDirty(); });
      const removeAll = armButton("Remove all phones", "Tap again to remove all", async () => {
        try { const r = await post<{ removed: number }>("/api/savahlive/devices/revoke-all"); toast(`${r.removed} phone(s) unpaired`, "ok"); await load(true); } catch (e) { fail(e); }
      });
      mount(connBox, h("section", { class: "sl-section" },
        h("header", null, h("h2", null, icon("link", 18), "Connection and security")),
        h("div", { class: "sl-body" },
          h("div", null,
            optRow("SavahLive is on", "Switch off to pause every phone at once. They stay paired.", switchEl(d.enabled, "SavahLive is on", (v) => { d.enabled = v; markDirty(); })),
            stepRow("Phones that can be paired", "Between 1 and 20.", 1, 20, d.max_devices, (n) => String(n), (n) => { d.max_devices = n; markDirty(); }),
            stepRow("Phones connected at once", `Separate from the dashboard limit (${o.dashboard_clients} of ${o.dashboard_limit} dashboards connected now).`, 1, 20, d.max_feeds, (n) => String(n), (n) => { d.max_feeds = n; markDirty(); }),
            stepRow("Renew each phone's key every", "Done quietly in the background. 0 turns it off.", 0, 365, d.rotate_days, (n) => (n === 0 ? "off" : `${n} d`), (n) => { d.rotate_days = n; markDirty(); }),
            stepRow("Unpair a phone left unused for", "0 keeps phones paired until you remove them, which is the default.", 0, 365, d.idle_unpair_days, (n) => (n === 0 ? "never" : `${n} d`), (n) => { d.idle_unpair_days = n; markDirty(); })),
          h("label", { class: "sl-range" }, h("div", { class: "sl-range-head" }, h("b", null, "App download link")), url, h("small", null, "Optional. The link to the signed APK. When set, a Download button shows at the top of this page.")),
          h("div", { class: "sl-range" }, h("div", { class: "sl-range-head" }, h("b", null, "Server address given to phones")), h("div", { class: "sl-actions", style: "margin:0" }, h("code", { style: "overflow-wrap:anywhere;align-self:center" }, o.server), copyButton(o.server, "Copy"))),
          h("div", { class: "sl-row-actions" }, removeAll))));
    }

    function drawSaveBar(): void {
      const save = h("button", { type: "button", class: "sl-btn primary" }, icon("save", 18), "Save changes") as HTMLButtonElement;
      save.onclick = () => busy(save, async () => {
        try {
          ov = await post<Overview>("/api/savahlive/settings", draft);
          draft = { ...ov.settings };
          dirty = false;
          saveBar.hidden = true;
          toast("Saved. Connected phones update within seconds.", "ok");
          drawAll();
        } catch (e) { fail(e); }
      });
      const discard = h("button", { type: "button", class: "sl-btn" }, "Discard") as HTMLButtonElement;
      discard.onclick = () => { if (ov) { draft = { ...ov.settings }; dirty = false; saveBar.hidden = true; drawSettings(); drawConnection(); } };
      mount(saveBar, h("span", null, "You have unsaved changes."), h("div", { class: "sl-actions", style: "margin:0" }, discard, save));
    }

    function drawAll(): void {
      drawTop();
      drawPhones();
      drawSettings();
      drawConnection();
    }

    // ------------------------------------------------------------------ pairing
    function openPair(): void {
      if (!ov) return;
      closePair?.();
      let days = "0";
      let timer = 0;
      let poll = 0;
      const known = new Set(ov.devices.map((d) => d.id));
      const body = h("div", { class: "sl-pair" });
      const stop = () => { window.clearInterval(timer); window.clearInterval(poll); };
      const s = sheet("Pair a phone", body, () => { stop(); closePair = null; });
      closePair = s.close;

      const choose = (): void => {
        stop();
        const pick = seg<string>("How long it stays paired", EXPIRY, days, (v) => { days = v; });
        const go = h("button", { type: "submit", class: "sl-btn primary" }, icon("link", 18), "Make a pairing code") as HTMLButtonElement;
        mount(body, h("form", { style: "display:grid;gap:14px;width:100%;text-align:left", onsubmit: (ev: Event) => { ev.preventDefault(); busy(go, async () => { try { show(await post<Made>("/api/savahlive/pair-code", { expiry_days: Number(days) })); } catch (e) { fail(e); } }); } },
          h("p", { class: "muted", style: "margin:0" }, "Pair once and the phone stays paired. Choose \u201CUntil I remove it\u201D for your own phone, or a time limit for a borrowed one. You can change it later."),
          pick.el, go));
      };

      const show = (m: Made): void => {
        stop();
        const qr = h("div", { class: "sl-qr", role: "img", "aria-label": "Pairing QR code" });
        qr.innerHTML = m.qr;       // drawn by our own server from the pairing link; it contains no user text
        const bar = h("i");
        const left = h("p", { class: "muted", style: "margin:0", role: "timer" });
        const again = h("button", { type: "button", class: "sl-btn" }, icon("refresh", 16), "New code") as HTMLButtonElement;
        again.onclick = () => choose();
        const total = Math.max(1, m.expires - Date.now() / 1000);
        const tick = () => {
          const sec = Math.max(0, Math.round(m.expires - Date.now() / 1000));
          bar.style.width = `${Math.min(100, (sec / total) * 100)}%`;
          if (sec === 0) { stop(); left.textContent = "This code has run out."; again.classList.add("primary"); return; }
          left.textContent = `Works once. Runs out in ${Math.floor(sec / 60)}:${String(sec % 60).padStart(2, "0")}.`;
        };
        tick();
        timer = window.setInterval(tick, 1000);
        poll = window.setInterval(() => {
          void get<Overview>("/api/savahlive").then((r) => {
            const fresh = r.devices.find((d) => !known.has(d.id));
            if (fresh && alive) { ov = r; draft = draft ?? { ...r.settings }; toast(`${fresh.name} is paired`, "ok"); s.close(); drawTop(); drawPhones(); }
          }, () => undefined);
        }, 3000);
        mount(body,
          qr,
          h("div", { class: "sl-code" }, m.shown),
          h("div", { class: "sl-timer" }, bar),
          left,
          h("div", { class: "sl-actions", style: "margin:0;justify-content:center" },
            h("a", { class: "sl-btn primary", href: m.app_link }, icon("smartphone", 18), "Open in SavahLive"), copyButton(m.link, "Copy link"), copyButton(m.code, "Copy code"), again),
          h("ol", { class: "sl-steps" },
            h("li", null, "Install SavahLive on the phone and open it."),
            h("li", null, "Scan this QR with the phone's camera and tap Open SavahLive. On that same phone, tap the red button instead."),
            h("li", null, "Or type the code into the app.")),
          h("small", { class: "muted", style: "word-break:break-all" }, `Server: ${m.server}`));
      };
      choose();
    }

    // ------------------------------------------------------------------ one phone
    function editSheet(p: Phone): void {
      const name = h("input", { class: "sl-input", type: "text", value: p.name, maxlength: 40, "aria-label": "Phone name" });
      let days = "keep";
      const pick = seg<string>("Stay paired", [{ id: "keep", label: "Keep as is" }, ...EXPIRY], days, (v) => { days = v; });
      const go = h("button", { class: "sl-btn primary", type: "submit" }, icon("save", 18), "Save") as HTMLButtonElement;
      const s = sheet(`Edit ${p.name}`, h("form", { style: "display:grid;gap:14px", onsubmit: (ev: Event) => {
        ev.preventDefault();
        busy(go, async () => {
          try {
            const body: { name: string; expiry_days?: number } = { name: name.value.trim() };
            if (days !== "keep") body.expiry_days = Number(days);
            await patch(`/api/savahlive/devices/${p.id}`, body);
            s.close(); toast("Saved", "ok"); await load(false);
          } catch (e) { fail(e); }
        });
      } },
      h("label", { style: "display:grid;gap:6px" }, h("b", null, "Name"), name),
      h("div", { style: "display:grid;gap:6px" }, h("b", null, "How long it stays paired, counted from now"), pick.el,
        h("small", { class: "muted" }, p.status === "expired" ? "Choosing a time brings this phone back without pairing again." : "Choose \u201CUntil I remove it\u201D to never expire.")),
      go));
    }

    // ------------------------------------------------------------------ loading
    async function load(everything: boolean): Promise<void> {
      ov = await get<Overview>("/api/savahlive");
      if (!alive) return;
      if (everything || !draft) draft = { ...ov.settings };
      if (everything && dirty) { dirty = false; saveBar.hidden = true; }
      if (everything || !dirty) { drawAll(); } else { drawTop(); drawPhones(); }       // the 10-second refresh never wipes unsaved edits
    }

    drawSaveBar();
    mount(root, h("div", { class: "page sl-page" },
      areaNav("savahlive"),
      heroBox, warnBox, phonesBox,
      h("div", { class: "sl-grid2" }, settingsBox, previewBox),
      connBox, saveBar));
    mount(heroBox, h("p", { class: "muted", role: "status" }, "Loading\u2026"));
    void load(true).catch((e) => { fail(e); mount(heroBox, h("div", { class: "sl-empty" }, h("h3", null, "Could not load SavahLive"), h("p", null, (e as Error).message))); });
    const refresh = window.setInterval(() => { if (!document.hidden) void load(false).catch(() => undefined); }, 10000);
    return () => { alive = false; window.clearInterval(refresh); closePair?.(); };
  },
};
