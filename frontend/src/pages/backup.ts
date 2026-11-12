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
interface Summary { fingerprint: string; created: number; app_version: string; passphrase: boolean; scopes: { id: string; label: string; rows: number }[]; plan?: Record<string, Record<string, number>>; applied?: Record<string, { added: number; skipped: number }> }

const fail = (e: unknown) => toast(e instanceof Error ? e.message : String(e), "error");
const mb = (n: number) => (n > 1_000_000 ? `${(n / 1_000_000).toFixed(1)} MB` : `${Math.max(1, Math.round(n / 1000))} KB`);

function save(name: string, blob: Blob): void {
  const url = URL.createObjectURL(blob);
  const a = h("a", { href: url, download: name }) as HTMLAnchorElement;
  document.body.append(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(url), 3000);
}
const fromB64 = (b64: string): Blob => { const bin = atob(b64); const u = new Uint8Array(bin.length); for (let i = 0; i < bin.length; i++) u[i] = bin.charCodeAt(i); return new Blob([u], { type: "application/octet-stream" }); };
const readB64 = (f: File): Promise<string> => new Promise((ok, no) => { const r = new FileReader(); r.onload = () => ok(String(r.result).split(",")[1] ?? ""); r.onerror = () => no(new Error("The file could not be read.")); r.readAsDataURL(f); });

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
  const show = (r: Summary & { dry_run?: boolean }) => {
    picked.clear(); r.scopes.forEach((s) => picked.add(s.id));
    const run = h("button", { class: "btn primary", type: "button" }, icon("upload", 16), mode === "replace" ? "Replace with this backup" : "Add from this backup") as HTMLButtonElement;
    run.onclick = () => busy(run, async () => {
      if (mode === "replace" && !confirm("Replace means what is in the backup becomes the only data for the chosen parts. A safety copy is kept so you can undo. Continue?")) return;
      try {
        const res = await (opts.firstRun ? post<Summary>(url, { ...base(), mode, scopes: [...picked], dry_run: false }) : fresh(() => post<Summary>(url, { ...base(), mode, scopes: [...picked], dry_run: false })));
        if (!res) return;
        const added = Object.values(res.applied ?? {}).reduce((a, x) => a + x.added, 0);
        mount(out, h("div", { class: "block" }, h("div", { style: "padding:14px" }, h("strong", null, "Restored. "), `${added} rows written. Fingerprint ${res.fingerprint}.`, opts.firstRun ? " You can sign in now with the password from the backup (if you included credentials) or the one in your server settings." : " If settings or sign-in methods were included, reload the page.")));
        toast("Backup restored", "ok");
        opts.onDone?.();
      } catch (e) { fail(e); }
    });
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
  return h("div", { class: "k-stack" }, file, key, pass, opts.firstRun ? token : null, h("div", { class: "row" }, check), out);
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
          pass, h("div", { class: "row" }, go),
          info.last_export ? h("p", { class: "muted small" }, `Last backup: ${new Date(info.last_export * 1000).toLocaleString()}`) : null), { flush: true }),
        card("upload", "Restore a backup", h("div", { class: "k-stack", style: "padding:12px 14px" }, restoreForm({ onDone: () => void load().catch(fail) }), undo), { flush: true }));
    }
    mount(root, h("div", { class: "page" }, areaNav("backup"), pageHead("database", "Backup & restore", "Move everything to a new deployment, or keep a safe copy."), body));
    void load().catch(fail);
  },
};
