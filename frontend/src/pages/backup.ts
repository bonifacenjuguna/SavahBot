/** Backup & Recovery: one encrypted file with everything, a key shown once, and a careful way back in. */
import { ApiError, get, post } from "../api.js";
import { busy, h, mount, sheet, toast } from "../dom.js";
import { icon } from "../icons.js";
import { areaNav } from "./kit.js";
import { card, pageHead } from "./shared.js";
import type { Page } from "./types.js";
import { lede, seg } from "./widgets.js";

interface Info { scopes: { id: string; label: string; default: boolean; rows: number }[]; undo_available: boolean; last_export: number | null }
interface Exported { filename: string; key: string; fingerprint: string; size: number; data: string; passphrase: boolean }
interface Summary { fingerprint: string; created: number; app_version: string; passphrase: boolean; scopes: { id: string; label: string; rows: number }[]; plan?: Record<string, Record<string, number>>; applied?: Record<string, { added: number; skipped: number; failed?: number; error?: string }> }
interface Prog { state: "idle" | "running" | "done" | "failed"; id?: string; stage?: string; pct?: number; elapsed?: number; cancellable?: boolean; error?: string; where?: string; kind?: string;
  result?: { added: number; skipped: number; failed: number; error: string; fingerprint: string; mode: string } | null;
  scopes?: { id: string; label: string; state: "wait" | "run" | "done"; done: number; total: number }[] }

import { APP_VERSION } from "../version.js";
const fail = (e: unknown) => toast(e instanceof Error ? e.message : String(e), "error");
const mb = (n: number) => (n > 1_000_000 ? `${(n / 1_000_000).toFixed(1)} MB` : `${Math.max(1, Math.round(n / 1000))} KB`);

function save(name: string, blob: Blob): void {
  const url = URL.createObjectURL(blob);
  const a = h("a", { href: url, download: name }) as HTMLAnchorElement;
  document.body.append(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(url), 3000);
}
const fromB64 = (b64: string): Blob => { const bin = atob(b64); const u = new Uint8Array(bin.length); for (let i = 0; i < bin.length; i++) u[i] = bin.charCodeAt(i); return new Blob([u], { type: "application/octet-stream" }); };
const readB64 = (f: File): Promise<string> => new Promise((ok, no) => { const r = new FileReader(); r.onload = () => ok(String(r.result).split(",")[1] ?? ""); r.onerror = () => no(new Error("The file could not be read.")); r.readAsDataURL(f); });

/** A password-style box with an eye button that shows or hides what is typed (1.4.3). */
function revealable(input: HTMLInputElement, what = "passphrase"): HTMLElement {
  const eye = h("button", { class: "pw-eye", type: "button", "aria-label": `Show ${what}`, "aria-pressed": "false", title: `Show ${what}`, onclick: () => {
    const show = input.type === "password";
    input.type = show ? "text" : "password";
    eye.setAttribute("aria-pressed", String(show));
    eye.setAttribute("aria-label", `${show ? "Hide" : "Show"} ${what}`);
    eye.title = `${show ? "Hide" : "Show"} ${what}`;
    eye.replaceChildren(icon(show ? "eyeOff" : "eye", 18));
    input.focus();
  } }, icon("eye", 18));
  return h("span", { class: "pw-reveal" }, input, eye);
}

const num = (n: number) => n.toLocaleString();
const clock = (sec: number) => `${Math.floor(sec / 60)}:${String(Math.floor(sec % 60)).padStart(2, "0")}`;

/** Ask for the password again if the server wants a fresh confirmation, then retry. */
async function fresh<T>(run: () => Promise<T>): Promise<T | undefined> {
  try { return await run(); } catch (e) { if (!(e instanceof ApiError) || e.code !== "step_up_required") throw e; }
  const pw = prompt("Confirm it is you. Enter your password:");
  if (!pw) return undefined;
  await post("/api/security/step-up", { method: "password", code: pw });
  return run();
}

function keySheet(x: Exported): void {
  const ack = h("input", { type: "checkbox", id: "ack" }) as HTMLInputElement;
  const done = h("button", { class: "btn primary", type: "button", disabled: true }, "Done") as HTMLButtonElement;
  ack.onchange = () => { done.disabled = !ack.checked; };
  const s = sheet("Save your key now", h("div", { class: "k-stack" },
    lede("This key unlocks the backup. It is shown only now and SavahBot does not keep it. Without it (and your passphrase, if you set one) the file cannot be opened by anyone, including us."),
    h("code", { class: "secret", style: "font-size:1.05rem" }, x.key),
    h("p", { class: "muted small" }, `File fingerprint ${x.fingerprint}. After a restore you can check it matches.`),
    h("div", { class: "row wrap" },
      h("button", { class: "btn small", type: "button", onclick: () => { void navigator.clipboard?.writeText(x.key).then(() => toast("Key copied", "ok")); } }, icon("copy", 15), "Copy key"),
      h("button", { class: "btn small", type: "button", onclick: () => save("savahbot-backup-key.txt", new Blob([`SavahBot backup key\nFile: ${x.filename}\nFingerprint: ${x.fingerprint}\n\n${x.key}\n`], { type: "text/plain" })) }, icon("download", 15), "Download key"),
      h("button", { class: "btn small", type: "button", onclick: () => save(x.filename, fromB64(x.data)) }, icon("download", 15), `Download backup (${mb(x.size)})`)),
    h("label", { class: "check" }, ack, " I saved the key somewhere safe, apart from the backup file"), done));
  done.onclick = () => s.close();
  save(x.filename, fromB64(x.data));
}

/** The import form, shared by the Backup page and the first-run restore on the sign-in screen. */
export function restoreForm(opts: { firstRun?: boolean; onDone?: () => void }): HTMLElement {
  let b64 = "", mode: "merge" | "replace" = opts.firstRun ? "replace" : "merge";
  const file = h("input", { type: "file", accept: ".svbak", "aria-label": "Backup file" }) as HTMLInputElement;
  const key = h("input", { type: "text", placeholder: "SVK1-XXXX-XXXX-…", autocomplete: "off", spellcheck: false, "aria-label": "Backup key" }) as HTMLInputElement;
  const pass = h("input", { type: "password", placeholder: "Passphrase (only if you set one)", autocomplete: "off", "aria-label": "Passphrase" }) as HTMLInputElement;
  const token = h("input", { type: "text", placeholder: "One-time restore token from the server log", autocomplete: "off", "aria-label": "Restore token" }) as HTMLInputElement;
  const out = h("div", { class: "k-stack" });
  const base = () => ({ data: b64, key: key.value, passphrase: pass.value, ...(opts.firstRun ? { token: token.value } : {}) });
  const url = opts.firstRun ? "/api/backup/first-run" : "/api/backup/import";
  file.onchange = async () => { const f = file.files?.[0]; b64 = f ? await readB64(f).catch((e) => { fail(e); return ""; }) : ""; mount(out); };

  const picked = new Set<string>();
  let last: (Summary & { dry_run?: boolean }) | null = null;

  // ---------------------------------------------------------------- the restore itself, with live progress (1.4.3)
  const restore = async (): Promise<void> => {
    const r = last;
    if (!r) return;
    if (mode === "replace" && !confirm("Replace means what is in the backup becomes the only data for the chosen parts. A safety copy is kept so you can undo. Continue?")) return;
    const startedAt = Date.now();
    let prev = "";
    try { prev = (await get<Prog>("/api/backup/progress")).id ?? ""; } catch { /* a first look that fails is fine */ }

    const ring = h("div", { class: "rs-ring", style: "--p:0" }, h("span", { class: "rs-pct" }, "0%"));
    const title = h("strong", { class: "rs-title" }, mode === "replace" ? "Replacing with your backup" : "Adding from your backup");
    const stage = h("div", { class: "rs-stage", role: "status", "aria-live": "polite" }, "Starting");
    const time = h("span", { class: "rs-time" }, "0:00");
    const fill = h("div", { class: "rs-fill" });
    const bar = h("div", { class: "rs-bar", role: "progressbar", "aria-valuemin": "0", "aria-valuemax": "100", "aria-valuenow": "0", "aria-label": "Restore progress" }, fill);
    const list = h("div", { class: "rs-list" });
    const note = h("p", { class: "rs-note" }, "Keep this page open. Your current data is copied first, so Undo is always possible.");
    const cancel = h("button", { class: "btn small ghost", type: "button", hidden: true }, icon("x", 14), "Cancel restore") as HTMLButtonElement;
    const panel = h("div", { class: "rs-panel", "data-state": "running" },
      h("div", { class: "rs-head" }, ring, h("div", { class: "rs-headtext" }, title, stage, time)), bar, list, note, h("div", { class: "row" }, cancel));
    mount(out, panel);
    panel.scrollIntoView({ block: "nearest", behavior: "smooth" });

    let moved = Date.now(), seen = "", stopped = false;
    const paint = (p: Prog) => {
      const pct = Math.max(0, Math.min(100, Math.round(p.pct ?? 0)));
      ring.style.setProperty("--p", String(pct));
      ring.firstElementChild!.textContent = `${pct}%`;
      fill.style.width = `${pct}%`;
      bar.setAttribute("aria-valuenow", String(pct));
      if (p.stage) stage.textContent = p.stage;
      cancel.hidden = !p.cancellable;
      const sig = `${p.stage}|${(p.scopes ?? []).reduce((a, x) => a + x.done, 0)}`;
      if (sig !== seen) { seen = sig; moved = Date.now(); }
      note.textContent = Date.now() - moved > 30000 ? "Still working. Big backups can take a few minutes, and nothing is wrong unless this turns red."
        : "Keep this page open. Your current data is copied first, so Undo is always possible.";
      mount(list, (p.scopes ?? []).map((x) => {
        const f = x.total ? Math.round((x.done / x.total) * 100) : x.state === "done" ? 100 : 0;
        return h("div", { class: `rs-item ${x.state}` },
          h("span", { class: "rs-mark", "aria-hidden": "true" }, x.state === "done" ? icon("check", 14) : x.state === "run" ? h("span", { class: "rs-spin" }) : null),
          h("span", { class: "rs-label" }, x.label),
          h("span", { class: "rs-count muted small" }, x.state === "wait" ? "waiting" : x.total ? `${num(x.done)} / ${num(x.total)}` : "done"),
          h("span", { class: "rs-mini" }, h("span", { style: `width:${f}%` })));
      }));
    };
    const tickClock = window.setInterval(() => { time.textContent = clock((Date.now() - startedAt) / 1000); }, 1000);
    const poll = async () => {
      while (!stopped) {
        try { const p = await get<Prog>("/api/backup/progress"); if (p.state !== "idle" && p.id !== prev) paint(p); } catch { /* keep trying while the request runs */ }
        await new Promise((ok) => setTimeout(ok, 600));
      }
    };
    void poll();
    cancel.onclick = () => { if (confirm("Stop the restore? Everything is put back as it was.")) { cancel.disabled = true; void post("/api/backup/cancel").catch(fail); } };

    const finish = (kind: "done" | "failed", body: HTMLElement[]) => {
      stopped = true; window.clearInterval(tickClock);
      panel.dataset.state = kind;
      ring.style.setProperty("--p", "100");
      ring.replaceChildren(icon(kind === "done" ? "check" : "x", 26));
      fill.style.width = "100%";
      bar.hidden = true; note.hidden = true; cancel.hidden = true; list.hidden = kind === "failed";
      title.textContent = kind === "done" ? "Restored" : "The restore did not finish";
      stage.replaceChildren(...body);
      time.textContent = `Took ${clock((Date.now() - startedAt) / 1000)}`;
      const again = h("button", { class: "btn primary", type: "button" }, icon("undo", 15), "Try again") as HTMLButtonElement;
      const back = h("button", { class: "btn", type: "button" }, "Back to options") as HTMLButtonElement;
      const done = h("button", { class: "btn primary", type: "button" }, icon("check", 15), opts.firstRun ? "Close" : "Done") as HTMLButtonElement;
      again.onclick = () => void restore();
      back.onclick = () => show(r);
      done.onclick = () => { if (opts.firstRun) out.closest(".sheet")?.querySelector<HTMLButtonElement>("[aria-label=\"Close\"]")?.click(); mount(out); opts.onDone?.(); };
      panel.append(h("div", { class: "row rs-actions" }, ...(kind === "done" ? [done] : [again, back])));
    };
    const summary = (res: { added: number; skipped: number; failed: number; error: string; fingerprint: string; warnings?: string[] }): HTMLElement[] => [
      h("span", null, `${num(res.added)} rows added`), res.skipped ? h("span", null, `, ${num(res.skipped)} were already here`) : null,
      res.failed ? h("div", { class: "rs-warn" }, icon("alert", 14), ` ${num(res.failed)} rows could not be added${res.error ? ` (${res.error})` : ""}.`) : null,
      ...(res.warnings ?? []).map((w) => h("div", { class: "rs-warn" }, icon("alert", 14), ` ${w}`)),
      h("div", { class: "muted small" }, `Fingerprint ${res.fingerprint}.${opts.firstRun ? " You can sign in now." : " If settings or sign-in methods were included, reload the page."}`),
    ].filter(Boolean) as HTMLElement[];
    const failed = (msg: string) => {
      finish("failed", [h("span", null, msg)]);
      // technical details, one tap to copy, so a problem can be pinned down without guessing (1.4.3)
      void get<Prog>("/api/backup/progress").catch(() => ({ state: "idle" }) as Prog).then((p) => {
        const text = [`SavahBot ${APP_VERSION} backup restore`, `Mode: ${mode}`, `Parts: ${[...picked].join(", ")}`, `Failed during: ${p.id !== prev && p.where ? p.where : "unknown"}`,
          `Server said: ${msg}`, p.kind && p.id !== prev ? `Error type: ${p.kind}` : "", `Time: ${new Date().toISOString()}`].filter(Boolean).join("\n");
        const copy = h("button", { class: "btn small", type: "button", onclick: () => { void navigator.clipboard?.writeText(text).then(() => toast("Details copied", "ok")); } }, icon("copy", 14), "Copy details");
        panel.querySelector(".rs-actions")?.before(h("details", { class: "rs-details" }, h("summary", null, "Technical details"), h("pre", null, text), copy));
      });
    };

    try {
      const body = { ...base(), mode, scopes: [...picked], dry_run: false };
      const res = await (opts.firstRun ? post<Summary>(url, body) : fresh(() => post<Summary>(url, body)));
      if (!res) { stopped = true; window.clearInterval(tickClock); show(r); return; }
      const t = Object.values(res.applied ?? {}).reduce<{ added: number; skipped: number; failed: number; error: string }>((a, x) => ({ added: a.added + x.added, skipped: a.skipped + x.skipped, failed: a.failed + (x.failed ?? 0), error: a.error || x.error || "" }), { added: 0, skipped: 0, failed: 0, error: "" });
      finish("done", summary({ ...t, fingerprint: res.fingerprint }));
      toast("Backup restored", "ok");
    } catch (e) {
      if (e instanceof ApiError && e.status === 0) {
        // the connection dropped, but the server may still be working: keep watching until it says how it ended
        stage.textContent = "Lost contact with the server. Checking whether it is still restoring.";
        stopped = true;
        for (let i = 0; i < 300; i++) {
          await new Promise((ok) => setTimeout(ok, 2000));
          try {
            const p = await get<Prog>("/api/backup/progress");
            if (p.id === prev) continue;
            if (p.state === "running") { paint(p); continue; }
            if (p.state === "done" && p.result) { finish("done", summary(p.result)); toast("Backup restored", "ok"); return; }
            if (p.state === "failed") { failed(p.error || "The restore failed."); return; }
          } catch { /* still unreachable */ }
        }
        failed("Could not reach the server to see how it ended. Reload the page and check Settings, or press Undo the last restore.");
      } else failed(e instanceof Error ? e.message : String(e));
    }
  };

  const show = (r: Summary & { dry_run?: boolean }) => {
    last = r;
    picked.clear(); r.scopes.forEach((s) => picked.add(s.id));
    const run = h("button", { class: "btn primary", type: "button" }, icon("upload", 16), mode === "replace" ? "Replace with this backup" : "Add from this backup") as HTMLButtonElement;
    run.onclick = () => void restore();
    mount(out, h("div", { class: "k-stack" },
      h("p", null, h("strong", null, "Key accepted. "), `Made ${new Date(r.created * 1000).toLocaleString()} by version ${r.app_version}. Fingerprint ${r.fingerprint}.`),
      h("div", { class: "k-stack" }, r.scopes.map((s) => h("label", { class: "check" }, h("input", { type: "checkbox", checked: true, onchange: (e: Event) => { (e.target as HTMLInputElement).checked ? picked.add(s.id) : picked.delete(s.id); } }), ` ${s.label} `, h("span", { class: "muted small" }, `(${s.rows.toLocaleString()} rows)`)))),
      seg<"merge" | "replace">("How to restore", [{ id: "merge", label: "Merge (keep what is here)" }, { id: "replace", label: "Replace" }], mode, (v) => { mode = v; show(r); }).el,
      h("p", { class: "muted small" }, mode === "merge" ? "Adds what is missing and keeps everything you have now." : "Makes the chosen parts exactly match the backup."),
      run));
  };
  const check = h("button", { class: "btn", type: "button" }, icon("check", 16), "Open and check the backup") as HTMLButtonElement;
  check.onclick = () => busy(check, async () => {
    if (!b64) return toast("Choose the backup file first.", "error");
    try { show(await post<Summary>(opts.firstRun ? url : "/api/backup/verify", opts.firstRun ? { ...base(), mode, scopes: [], dry_run: true } : base())); } catch (e) { fail(e); }
  });
  return h("div", { class: "k-stack" }, file, key, revealable(pass), opts.firstRun ? token : null, h("div", { class: "row" }, check), out);
}

export const backup: Page = {
  id: "backup",
  title: "Backup",
  icon: "database",
  blurb: "Encrypted export and restore",
  render(root) {
    const body = h("div", { class: "k-stack" });
    async function load(): Promise<void> {
      const info = await get<Info>("/api/backup/info");
      const picks = new Map(info.scopes.map((s) => [s.id, s.default]));
      const pass = h("input", { type: "password", placeholder: "Optional passphrase (extra lock)", autocomplete: "new-password", "aria-label": "Passphrase" }) as HTMLInputElement;
      const go = h("button", { class: "btn primary", type: "button" }, icon("download", 16), "Make encrypted backup") as HTMLButtonElement;
      go.onclick = () => busy(go, async () => {
        try {
          const scopes = [...picks].filter(([, v]) => v).map(([k]) => k);
          const x = await fresh(() => post<Exported>("/api/backup/export", { scopes, passphrase: pass.value }));
          if (x) { keySheet(x); await load(); }
        } catch (e) { fail(e); }
      });
      const undo = info.undo_available ? h("button", { class: "btn small", type: "button", onclick: (e: Event) => void busy(e.currentTarget as HTMLButtonElement, async () => {
        if (!confirm("Put everything back as it was just before the last restore?")) return;
        try { await fresh(() => post("/api/backup/undo")); toast("Undone", "ok"); await load(); } catch (x) { fail(x); }
      }) }, icon("undo", 15), "Undo the last restore") : null;
      mount(body,
        card("download", "Make a backup", h("div", { class: "k-stack", style: "padding:12px 14px" },
          lede("One file, encrypted with a random 256-bit key that is shown once and never stored. Pick what goes in."),
          h("div", { class: "k-stack" }, info.scopes.map((s) => h("label", { class: "check" }, h("input", { type: "checkbox", checked: s.default, onchange: (e: Event) => picks.set(s.id, (e.target as HTMLInputElement).checked) }), ` ${s.label} `, h("span", { class: "muted small" }, `(${s.rows.toLocaleString()} rows)`)))),
          h("p", { class: "muted small" }, "Never included, whatever you tick: signed-in sessions, push-notification device tokens, the server's signing secret and environment variables. Sign-in methods are only included if you tick the last box. Demo mode's sample data is never exported or imported: the dashboard already has its own."),
          revealable(pass), h("div", { class: "row" }, go),
          info.last_export ? h("p", { class: "muted small" }, `Last backup: ${new Date(info.last_export * 1000).toLocaleString()}`) : null), { flush: true }),
        card("upload", "Restore a backup", h("div", { class: "k-stack", style: "padding:12px 14px" }, restoreForm({ onDone: () => void load().catch(fail) }), undo), { flush: true }));
    }
    mount(root, h("div", { class: "page" }, areaNav("backup"), pageHead("database", "Backup & restore", "Move everything to a new deployment, or keep a safe copy."), body));
    void load().catch(fail);
  },
};
