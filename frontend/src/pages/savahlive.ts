/** SavahLive (1.5.0): the control room for the Android overlay app. Pair phones, see who is connected, tune what the overlay shows, remove a phone.
 *  SavahBot does the work; this page only manages the link. Everything the phone shows is produced by the backend. */
import { del, get, patch, post } from "../api.js";
import { ago, busy, copyButton, dateTime, h, mount, sheet, toast } from "../dom.js";
import { icon } from "../icons.js";
import { areaNav } from "./kit.js";
import { card, pageHead } from "./shared.js";
import type { Page } from "./types.js";
import { confirmAct, figures, invite, lede, seg } from "./widgets.js";

interface Phone { id: string; name: string; created: number; last_seen: number; expires: number | null; app_version: string; online: boolean; status: "active" | "expired" }
interface Prefs {
  enabled: boolean; max_devices: number; max_feeds: number; chat_lines: number; peek_seconds: number; font_size: number;
  hide_bots: boolean; hide_flagged: boolean; only_special: boolean; rotate_days: number; idle_unpair_days: number; track_stats: boolean;
}
interface Overview {
  enabled: boolean; protocol: number; server: string; server_is_public: boolean; devices: Phone[]; connected: number;
  state: { mode: string; live: boolean; title: string }; settings: Prefs; stats_seconds: number; dashboard_clients: number; dashboard_limit: number; now: number;
}
interface Made { code: string; shown: string; expires: number; link: string; app_link: string; server: string; qr: string }

const fail = (e: unknown) => toast(e instanceof Error ? e.message : String(e), "error");
const EXPIRY: { id: string; label: string }[] = [{ id: "0", label: "Until I remove it" }, { id: "30", label: "30 days" }, { id: "7", label: "7 days" }, { id: "1", label: "24 hours" }];

function airState(s: Overview["state"]): string {
  if (s.mode === "demo") return "in Demo";
  return s.live ? "on air" : "on standby";
}

export const savahlive: Page = {
  id: "savahlive",
  title: "SavahLive",
  icon: "smartphone",
  blurb: "Pair the Android overlay and choose what it shows",
  render(root) {
    let ov: Overview | null = null;
    let alive = true;
    let closePair: (() => void) | null = null;
    const top = h("div", { class: "k-stack" });
    const phones = h("div", { class: "k-stack" });
    const prefs = h("div", { class: "k-stack" });
    const notes = h("div", { class: "k-stack" });
    const pairBtn = h("button", { class: "btn primary", type: "button" }, icon("plus", 16), "Pair a phone") as HTMLButtonElement;
    pairBtn.onclick = () => openPair();

    // ------------------------------------------------------------------ drawing
    function draw(withPrefs = true): void {
      if (!ov) return;
      const o = ov;
      mount(top, figures([
        { value: String(o.devices.length), label: o.devices.length === 1 ? "phone paired" : "phones paired" },
        { value: String(o.connected), label: "connected now", tone: o.connected ? "ok" : "" },
        { value: airState(o.state), label: "SavahBot is", tone: o.state.live ? "ok" : "" }]));
      const warn: HTMLElement[] = [];
      if (!o.enabled) warn.push(h("p", { class: "small", style: "color:var(--warn)" }, "SavahLive is switched off, so no phone can connect. Turn it on under Connection below."));
      if (o.server.startsWith("http://") && !/localhost|127\.0\.0\.1/.test(o.server)) warn.push(h("p", { class: "small", style: "color:var(--warn)" }, "Phones can only pair over HTTPS. Set PUBLIC_BASE_URL to your https:// backend address."));
      if (!o.settings.track_stats) warn.push(h("p", { class: "small", style: "color:var(--warn)" }, "Viewers and likes are off, so the overlay will show chat only. Turn on “Track viewers and likes” under Overlay."));
      mount(notes, warn);
      mount(phones, o.devices.length ? o.devices.map(phoneRow)
        : invite("smartphone", "No phone paired yet", "Install SavahLive on your Android phone, then tap Pair a phone. You only pair once; after that the phone stays paired until you remove it.", pairBtn.cloneNode(true) as HTMLElement));
      const again = phones.querySelector<HTMLButtonElement>(".invite button");
      if (again) again.onclick = () => openPair();
      if (withPrefs) drawPrefs(o);      // the 10-second refresh leaves the settings alone, so nothing you are typing is wiped
    }

    function phoneRow(p: Phone): HTMLElement {
      const chip = p.status === "expired" ? h("span", { class: "chip bad" }, "Pairing ended") : p.online ? h("span", { class: "chip ok" }, "Connected") : h("span", { class: "chip" }, "Not connected");
      const until = p.expires ? `${p.status === "expired" ? "Ended" : "Ends"} ${dateTime(p.expires)}` : "Stays paired until you remove it";
      const rm = confirmAct({ icon: "trash", label: `Remove ${p.name}`, confirmText: "Remove?", onConfirm: async () => {
        try { await del(`/api/savahlive/devices/${p.id}`); toast(`${p.name} was unpaired`, "ok"); await load(); } catch (e) { fail(e); }
      } });
      const edit = h("button", { class: "icon-act", type: "button", title: "Rename or change how long it stays paired", "aria-label": `Edit ${p.name}`, onclick: () => editSheet(p) }, icon("pencil", 18));
      return h("div", { class: "block flush" }, h("div", { class: "row between", style: "padding:12px 14px;gap:12px;align-items:center" },
        h("span", { class: "tile-ico", "aria-hidden": "true" }, icon("smartphone", 22)),
        h("div", { style: "min-width:0;flex:1" }, h("div", { class: "row wrap", style: "gap:8px;align-items:center" }, h("strong", null, p.name), chip),
          h("div", { class: "muted small" }, `Paired ${dateTime(p.created)} · Last seen ${ago(p.last_seen)}${p.app_version ? ` · app ${p.app_version}` : ""}`),
          h("div", { class: "muted small" }, until)),
        h("div", { class: "row", style: "gap:4px" }, edit, rm)));
    }

    function field(label: string, el: HTMLElement, help: string): HTMLElement {
      return h("label", { class: "field" }, h("span", null, label), el, h("span", { class: "muted small" }, help));
    }
    function toggle(label: string, help: string, on: boolean): { row: HTMLElement; get: () => boolean } {
      const box = h("input", { type: "checkbox", class: "switch", checked: on, "aria-label": label }) as HTMLInputElement;
      return { get: () => box.checked, row: h("label", { class: "row between", style: "gap:12px;align-items:center" }, h("span", null, h("strong", null, label), h("div", { class: "muted small" }, help)), box) };
    }
    function num(value: number, min: number, max: number, label: string): HTMLInputElement {
      return h("input", { type: "number", inputmode: "numeric", min: String(min), max: String(max), value: String(value), "aria-label": label }) as HTMLInputElement;
    }

    function drawPrefs(o: Overview): void {
      const s = o.settings;
      const track = toggle("Track viewers and likes", `Reads them from YouTube about every ${o.stats_seconds} seconds (about 1 quota unit each time). SavahLive shows what SavahBot already has; without this the overlay shows chat only.`, s.track_stats);
      const bots = toggle("Hide bot messages", "Leaves out other bots and SavahBot's own replies.", s.hide_bots);
      const flagged = toggle("Hide flagged messages", "Leaves out messages moderation flagged or removed.", s.hide_flagged);
      const special = toggle("Members and moderators only", "Shows chat only from members, regulars, moderators and you. Useful during a raid.", s.only_special);
      const lines = num(s.chat_lines, 10, 100, "Chat lines kept");
      const peek = num(s.peek_seconds, 2, 15, "Peek seconds");
      const font = num(s.font_size, 11, 22, "Text size");
      const enabled = toggle("SavahLive is on", "Switch off to pause every phone at once. They stay paired.", s.enabled);
      const maxDev = num(s.max_devices, 1, 20, "Phones allowed");
      const maxFeeds = num(s.max_feeds, 1, 20, "Connected at once");
      const rotate = num(s.rotate_days, 0, 365, "Key renewal days");
      const idle = num(s.idle_unpair_days, 0, 365, "Unpair after idle days");
      const save = h("button", { class: "btn primary", type: "button" }, icon("save", 16), "Save") as HTMLButtonElement;
      save.onclick = () => busy(save, async () => {
        try {
          ov = await post<Overview>("/api/savahlive/settings", {
            enabled: enabled.get(), max_devices: Number(maxDev.value), max_feeds: Number(maxFeeds.value), chat_lines: Number(lines.value), peek_seconds: Number(peek.value),
            font_size: Number(font.value), hide_bots: bots.get(), hide_flagged: flagged.get(), only_special: special.get(), rotate_days: Number(rotate.value),
            idle_unpair_days: Number(idle.value), track_stats: track.get() });
          toast("Saved. Connected phones update within seconds.", "ok");
          draw();
        } catch (e) { fail(e); }
      });
      const removeAll = confirmAct({ icon: "trash", label: "Remove all phones", confirmText: "Remove all?", text: "Remove all phones", onConfirm: async () => {
        try { const r = await post<{ removed: number }>("/api/savahlive/devices/revoke-all"); toast(`${r.removed} phone(s) unpaired`, "ok"); await load(); } catch (e) { fail(e); }
      } });
      mount(prefs,
        card("eye", "Overlay", h("div", { class: "k-stack", style: "padding:12px 14px" },
          lede("What every paired phone shows. Changes reach connected phones within a few seconds."),
          track.row, bots.row, flagged.row, special.row,
          field("Chat lines kept on the phone", lines, "10 to 100. The big window scrolls through these."),
          field("Peek time (seconds)", peek, "How long the docked overlay slides out when a new chat line arrives (2 to 15)."),
          field("Text size", font, "11 to 22."))),
        card("plug", "Connection", h("div", { class: "k-stack", style: "padding:12px 14px" },
          enabled.row,
          field("Phones that can be paired", maxDev, "1 to 20."),
          field("Phones connected at once", maxFeeds, `1 to 20. This is separate from the dashboard limit (${o.dashboard_clients} of ${o.dashboard_limit} dashboards connected now).`),
          field("Renew each phone's key every (days)", rotate, "Done quietly in the background; you never notice. 0 turns it off."),
          field("Unpair a phone left unused for (days)", idle, "0 keeps phones paired until you remove them, which is the default."),
          h("p", { class: "muted small" }, `Server address given to phones: ${o.server}`),
          h("div", { class: "row between wrap", style: "gap:10px" }, save, o.devices.length ? removeAll : null))));
    }

    // ------------------------------------------------------------------ pairing
    function openPair(): void {
      if (!ov) return;
      closePair?.();
      let days = "0";
      let timer = 0;
      let poll = 0;
      const known = new Set(ov.devices.map((d) => d.id));
      const body = h("div", { class: "k-stack" });
      const stop = () => { window.clearInterval(timer); window.clearInterval(poll); };
      const s = sheet("Pair a phone", body, () => { stop(); closePair = null; });
      closePair = s.close;

      const choose = (): void => {
        stop();
        const pick = seg<string>("How long it stays paired", EXPIRY.map((e) => ({ id: e.id, label: e.label })), days, (v) => { days = v; });
        const go = h("button", { class: "btn primary", type: "submit" }, icon("link", 16), "Make a pairing code") as HTMLButtonElement;
        mount(body, h("form", { class: "k-stack", onsubmit: (ev: Event) => { ev.preventDefault(); busy(go, async () => { try { show(await post<Made>("/api/savahlive/pair-code", { expiry_days: Number(days) })); } catch (e) { fail(e); } }); } },
          lede("Pair once and the phone stays paired. Choose “Until I remove it” for your own phone, or a time limit for a borrowed one. You can change it later."), pick.el, go));
      };

      const show = (m: Made): void => {
        stop();
        const qr = h("div", { style: "width:min(240px,70vw);margin:0 auto;background:#fff;padding:10px;border-radius:14px", role: "img", "aria-label": "Pairing QR code" });
        qr.innerHTML = m.qr;       // drawn by our own server from the pairing link; it contains no user text
        qr.querySelector("svg")?.setAttribute("style", "width:100%;height:auto;display:block");
        const left = h("p", { class: "muted small", style: "text-align:center", role: "timer" });
        const again = h("button", { class: "btn", type: "button", onclick: () => choose() }, icon("refresh", 16), "Make a new code");
        const tick = () => {
          const sec = Math.max(0, Math.round(m.expires - Date.now() / 1000));
          if (sec === 0) { stop(); mount(left, "This code has run out."); again.classList.add("primary"); return; }
          left.textContent = `Works once. Runs out in ${Math.floor(sec / 60)}:${String(sec % 60).padStart(2, "0")}.`;
        };
        tick();
        timer = window.setInterval(tick, 1000);
        poll = window.setInterval(() => {
          void get<Overview>("/api/savahlive").then((r) => {
            const fresh = r.devices.find((d) => !known.has(d.id));
            if (fresh && alive) { ov = r; toast(`${fresh.name} is paired`, "ok"); s.close(); draw(); }
          }, () => undefined);
        }, 3000);
        mount(body,
          lede("On the phone: open SavahLive and scan this with the phone's camera, or tap the button if you are on that phone now, or type the code."),
          qr,
          h("div", { style: "font:700 30px/1.2 ui-monospace,monospace;letter-spacing:.12em;text-align:center" }, m.shown),
          left,
          h("div", { class: "row wrap", style: "gap:8px;justify-content:center" },
            h("a", { class: "btn primary", href: m.app_link }, icon("smartphone", 16), "Open in SavahLive"), copyButton(m.link, "Copy link"), copyButton(m.code, "Copy code"), again),
          h("p", { class: "muted small", style: "text-align:center;word-break:break-all" }, `Server: ${m.server}`));
      };
      choose();
    }

    // ------------------------------------------------------------------ one phone
    function editSheet(p: Phone): void {
      const name = h("input", { type: "text", value: p.name, maxlength: 40, "aria-label": "Phone name" }) as HTMLInputElement;
      let days = "keep";
      const pick = seg<string>("Stay paired", [{ id: "keep", label: "Keep as is" }, ...EXPIRY], days, (v) => { days = v; });
      const go = h("button", { class: "btn primary", type: "submit" }, icon("save", 16), "Save") as HTMLButtonElement;
      const s = sheet(`Edit ${p.name}`, h("form", { class: "k-stack", onsubmit: (ev: Event) => {
        ev.preventDefault();
        busy(go, async () => {
          try {
            const body: { name: string; expiry_days?: number } = { name: name.value.trim() };
            if (days !== "keep") body.expiry_days = Number(days);
            await patch(`/api/savahlive/devices/${p.id}`, body);
            s.close(); toast("Saved", "ok"); await load();
          } catch (e) { fail(e); }
        });
      } }, field("Name", name, "Shown here only."),
      field("How long it stays paired, counted from now", pick.el, p.status === "expired" ? "Choosing a time brings this phone back without pairing again." : "Choose “Until I remove it” to never expire."), go));
    }

    // ------------------------------------------------------------------ loading
    async function load(withPrefs = true): Promise<void> {
      ov = await get<Overview>("/api/savahlive");
      if (alive) draw(withPrefs);
    }

    mount(root, h("div", { class: "page" }, areaNav("savahlive"),
      pageHead("smartphone", "SavahLive", "The Android overlay: pair phones and choose what it shows."),
      top, notes,
      card("smartphone", "Phones", h("div", { class: "k-stack", style: "padding:12px 14px" }, phones), { actions: pairBtn }),
      prefs,
      h("p", { class: "muted small centered" }, "SavahBot does the work, SavahLive shows the results. The phone never talks to YouTube.")));
    mount(phones, h("p", { class: "muted", role: "status" }, "Loading…"));
    void load().catch((e) => { fail(e); mount(phones, invite("alert", "Could not load SavahLive", (e as Error).message)); });
    const refresh = window.setInterval(() => { if (!document.hidden) void load(false).catch(() => undefined); }, 10000);
    return () => { alive = false; window.clearInterval(refresh); closePair?.(); };
  },
};
