/** Security & Access Centre: how you sign in, who is signed in, what happened, and the emergency brake. */
import { ApiError, del, get, patch, post } from "../api.js";
import { busy, dateTime, h, mount, sheet, toast } from "../dom.js";
import { icon } from "../icons.js";
import { createPasskey, passkeyError, passkeysSupported } from "../passkeys.js";
import { areaNav } from "./kit.js";
import { card, empty, pageHead } from "./shared.js";
import type { Page } from "./types.js";
import { figures, lede } from "./widgets.js";

interface Check { id: string; ok: boolean; title: string; fix: string }
interface Overview {
  readiness: { score: number; checks: Check[]; failed_logins_24h: number; other_sessions: number };
  lockdown: boolean; enforced: boolean; methods: number; totp: boolean; recovery_left: number; step_up_seconds: number; this_device: string;
  passkeys: { id: number; name: string; created: number; last_used: number | null; synced: boolean }[];
  passkey_site: { rp_id: string; origins: string[] };
}
interface Sess { ref: string; created: number; last_seen: number; ip: string; label: string; factors: string[]; current: boolean; limited: number }
interface Activity { events: { ts: number; kind: string; ok: number; method: string; ip: string; device: string; detail: string }[]; audit: { ts: number; action: string; ip: string; detail: string }[] }

const fail = (e: unknown) => toast(e instanceof Error ? e.message : String(e), "error");
const EVENT: Record<string, string> = { login: "Signed in", login_failed: "Failed attempt", logout: "Signed out", factor: "Step passed" };
const ACTION: Record<string, string> = {
  password_changed: "Password changed", totp_enabled: "Authenticator app added", totp_removed: "Authenticator app removed", passkey_added: "Passkey added", passkey_removed: "Passkey removed",
  recovery_codes_regenerated: "New recovery codes made", recovery_code_used: "Recovery code used", session_revoked: "Session signed out", other_sessions_revoked: "Other sessions signed out",
  lockdown_on: "Lockdown turned on", lockdown_off: "Lockdown lifted", new_device_signed_in: "New device signed in",
};
const nice = (m: Record<string, string>, k: string) => m[k] ?? k.replace(/_/g, " ");

/** Run something that needs a fresh confirmation. If the server asks for one, ask for the password and try again. */
async function withStepUp<T>(run: () => Promise<T>): Promise<T | undefined> {
  try { return await run(); } catch (e) {
    if (!(e instanceof ApiError) || e.code !== "step_up_required") throw e;
  }
  const ok = await new Promise<boolean>((resolve) => {
    const pw = h("input", { type: "password", autocomplete: "current-password", placeholder: "Your password", "aria-label": "Your password" }) as HTMLInputElement;
    const err = h("p", { class: "lc-err", role: "alert" });
    const go = h("button", { class: "btn primary", type: "submit" }, "Confirm") as HTMLButtonElement;
    let settled = false;
    const finish = (v: boolean) => { if (!settled) { settled = true; resolve(v); } };
    const s = sheet("Confirm it is you", h("form", { class: "k-stack", onsubmit: (ev: Event) => {
      ev.preventDefault();
      void busy(go, async () => {
        try { await post("/api/security/step-up", { method: "password", code: pw.value }); finish(true); s.close(); } catch (x) { err.textContent = (x as Error).message; pw.select(); }
      });
    } }, h("p", { class: "muted" }, "This changes how you sign in, so please enter your password again."), pw, err, h("div", { class: "row" }, go)), () => finish(false));
  });
  return ok ? run() : undefined;
}

function codesSheet(codes: string[]): void {
  const text = codes.join("\n");
  sheet("Your recovery codes", h("div", { class: "k-stack" },
    lede("Each code works once, in place of a missing sign-in method. They are shown only now. Save them somewhere safe, away from this device."),
    h("pre", { class: "codes" }, text),
    h("div", { class: "row wrap" },
      h("button", { class: "btn small", type: "button", onclick: () => { void navigator.clipboard?.writeText(text).then(() => toast("Copied", "ok")); } }, icon("copy", 15), "Copy"),
      h("button", { class: "btn small", type: "button", onclick: () => {
        const url = URL.createObjectURL(new Blob([`SavahBot recovery codes\n\n${text}\n`], { type: "text/plain" }));
        const a = h("a", { href: url, download: "savahbot-recovery-codes.txt" }) as HTMLAnchorElement; document.body.append(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(url), 2000);
      } }, icon("download", 15), "Download"))));
}

export const security: Page = {
  id: "security",
  title: "Security",
  icon: "shield",
  blurb: "Sign-in methods, devices and lockdown",
  render(root) {
    const body = h("div", { class: "k-stack" });

    async function load(): Promise<void> {
      const [ov, ses, act] = await Promise.all([get<Overview>("/api/security/overview"), get<{ sessions: Sess[] }>("/api/security/sessions"), get<Activity>("/api/security/activity")]);
      mount(body, ...(ov.lockdown ? [lockBanner()] : []), scoreCard(ov), methodsCard(ov), sessionsCard(ses.sessions), activityCard(act), lockdownCard(ov));
    }
    const reload = () => load().catch(fail);

    function lockBanner(): HTMLElement {
      return h("div", { class: "block notice-bad", role: "alert" }, h("div", { style: "padding:14px" }, h("strong", null, "Lockdown is on."), " Every other device was signed out and nothing else works until you lift it (bottom of this page)."));
    }

    function scoreCard(ov: Overview): HTMLElement {
      const r = ov.readiness;
      const tone = r.score >= 85 ? "ok" : r.score >= 60 ? "warn" : "bad";
      return card("shield", "Security check", h("div", { class: "k-stack", style: "padding:12px 14px" },
        figures([{ value: `${r.score}%`, label: "protected", tone }, { value: String(ov.methods), label: "sign-in methods" }, { value: String(r.failed_logins_24h), label: "failed attempts today", tone: r.failed_logins_24h ? "warn" : "ok" }]),
        ov.enforced ? h("p", { class: "muted small" }, "Two-step sign-in is on: every sign-in must prove any two of your password, a passkey and an authenticator code.")
          : h("p", { class: "muted small", style: "color:var(--warn)" }, "Two-step sign-in is OFF. Anyone with your password can sign in. Add a passkey or an authenticator app below to turn it on."),
        h("ul", { class: "list" }, r.checks.map((c) => h("li", null, icon(c.ok ? "checkCircle" : "alert", 16), " ", c.title, c.ok ? null : h("div", { class: "muted small" }, c.fix))))), { flush: true });
    }

    function methodsCard(ov: Overview): HTMLElement {
      const pwBtn = h("button", { class: "btn small", type: "button", onclick: () => passwordSheet() }, icon("lock", 15), "Change password");
      const totpRow = ov.totp
        ? h("div", { class: "row between" }, h("div", null, h("strong", null, "Authenticator app"), h("div", { class: "muted small" }, "Set up. Works with any authenticator app.")),
          h("button", { class: "btn small", type: "button", onclick: (e: Event) => void busy(e.currentTarget as HTMLButtonElement, async () => { try { if (await withStepUp(() => del("/api/security/totp")) !== undefined) { toast("Removed", "ok"); await reload(); } } catch (x) { fail(x); } }) }, "Remove"))
        : h("div", { class: "row between" }, h("div", null, h("strong", null, "Authenticator app"), h("div", { class: "muted small" }, "A 6-digit code from an app on your phone.")),
          h("button", { class: "btn small primary", type: "button", onclick: () => void totpSheet() }, icon("smartphone", 15), "Set up"));
      const keys = ov.passkeys.map((p) => h("li", { class: "row between" },
        h("div", null, h("strong", null, p.name), h("div", { class: "muted small" }, `Added ${dateTime(p.created)}${p.last_used ? " · used " + dateTime(p.last_used) : " · not used yet"}${p.synced ? " · synced" : ""}`)),
        h("div", { class: "row" },
          h("button", { class: "btn small ghost", type: "button", "aria-label": `Rename ${p.name}`, onclick: () => { const n = prompt("Name this passkey", p.name); if (n) void patch(`/api/security/passkeys/${p.id}`, { name: n }).then(reload).catch(fail); } }, icon("pencil", 15)),
          h("button", { class: "btn small ghost", type: "button", "aria-label": `Remove ${p.name}`, onclick: (e: Event) => void busy(e.currentTarget as HTMLButtonElement, async () => { try { if (await withStepUp(() => del(`/api/security/passkeys/${p.id}`)) !== undefined) { toast("Removed", "ok"); await reload(); } } catch (x) { fail(x); } }) }, icon("trash", 15)))));
      const addKey = passkeysSupported()
        ? h("button", { class: "btn small primary", type: "button", onclick: (e: Event) => void busy(e.currentTarget as HTMLButtonElement, async () => {
            try {
              const o = await withStepUp(() => post<{ ticket: string; publicKey: Record<string, unknown> }>("/api/security/passkeys/options"));
              if (!o) return;
              const cred = await createPasskey(o.publicKey).catch((x) => { throw new Error(passkeyError(x)); });
              const name = prompt("Name this passkey (for example “Pixel phone”)", "My passkey") || "My passkey";
              const r = await post<{ recovery_codes: string[] | null }>("/api/security/passkeys/register", { ticket: o.ticket, credential: cred, name });
              toast("Passkey added", "ok");
              if (r.recovery_codes) codesSheet(r.recovery_codes);
              await reload();
            } catch (x) { fail(x); }
          }) }, icon("key", 15), "Add a passkey")
        : h("p", { class: "muted small" }, "This browser cannot make passkeys.");
      return card("key", "How you sign in", h("div", { class: "k-stack", style: "padding:12px 14px" },
        h("div", { class: "row between" }, h("div", null, h("strong", null, "Password"), h("div", { class: "muted small" }, "Stored as a salted hash. Never shown anywhere.")), pwBtn),
        totpRow,
        h("div", null, h("div", { class: "row between" }, h("div", null, h("strong", null, "Passkeys"), h("div", { class: "muted small" }, "Fingerprint, face or screen lock. Cannot be phished.")), addKey),
          keys.length ? h("ul", { class: "list" }, keys) : null),
        h("div", { class: "row between" }, h("div", null, h("strong", null, "Recovery codes"), h("div", { class: "muted small" }, `${ov.recovery_left} unused. Each works once if you lose a device.`)),
          h("button", { class: "btn small", type: "button", disabled: ov.methods < 2, title: ov.methods < 2 ? "Set up a second sign-in method first." : "", onclick: (e: Event) => void busy(e.currentTarget as HTMLButtonElement, async () => {
            try { const r = await withStepUp(() => post<{ codes: string[] }>("/api/security/recovery")); if (r) { codesSheet(r.codes); await reload(); } } catch (x) { fail(x); }
          }) }, icon("refresh", 15), "Make new codes")),
        h("p", { class: "muted small" }, `Passkey site: ${ov.passkey_site.rp_id}. Passkeys only work on that address.`)), { flush: true });
    }

    function passwordSheet(): void {
      const cur = h("input", { type: "password", autocomplete: "current-password", placeholder: "Current password", "aria-label": "Current password" }) as HTMLInputElement;
      const nw = h("input", { type: "password", autocomplete: "new-password", placeholder: "New password (10+ characters)", "aria-label": "New password" }) as HTMLInputElement;
      const err = h("p", { class: "lc-err", role: "alert" });
      const go = h("button", { class: "btn primary", type: "submit" }, "Change password") as HTMLButtonElement;
      const s = sheet("Change password", h("form", { class: "k-stack", onsubmit: (ev: Event) => {
        ev.preventDefault();
        void busy(go, async () => {
          try { const r = await post<{ signed_out_elsewhere: number }>("/api/security/password", { current: cur.value, new: nw.value }); s.close(); toast(r.signed_out_elsewhere ? `Password changed. ${r.signed_out_elsewhere} other device(s) signed out.` : "Password changed", "ok"); await reload(); }
          catch (x) { err.textContent = (x as Error).message; }
        });
      } }, lede("Other devices are signed out when you change it."), cur, nw, err, h("div", { class: "row" }, go)));
    }

    async function totpSheet(): Promise<void> {
      let setup: { secret: string; uri: string; qr: string } | undefined;
      try { setup = await withStepUp(() => post<{ secret: string; uri: string; qr: string }>("/api/security/totp/begin")); } catch (x) { fail(x); return; }
      if (!setup) return;
      const code = h("input", { type: "text", inputmode: "numeric", autocomplete: "one-time-code", placeholder: "6-digit code", maxlength: 8, "aria-label": "Code from your app" }) as HTMLInputElement;
      const err = h("p", { class: "lc-err", role: "alert" });
      const go = h("button", { class: "btn primary", type: "submit" }, "Turn on") as HTMLButtonElement;
      const qr = h("div", { class: "qr", role: "img", "aria-label": "QR code for your authenticator app" });
      qr.innerHTML = setup.qr;   // generated by our own server from a fixed template; contains no user text
      const s = sheet("Set up an authenticator app", h("form", { class: "k-stack", onsubmit: (ev: Event) => {
        ev.preventDefault();
        void busy(go, async () => {
          try {
            const r = await post<{ recovery_codes: string[] | null }>("/api/security/totp/confirm", { code: code.value });
            s.close(); toast("Authenticator app turned on", "ok");
            if (r.recovery_codes) codesSheet(r.recovery_codes);
            await reload();
          } catch (x) { err.textContent = (x as Error).message; code.select(); }
        });
      } },
        lede("Scan this with an authenticator app (Google Authenticator, Authy, 1Password, Microsoft Authenticator and others), then type the 6-digit code it shows."),
        qr,
        h("details", null, h("summary", null, "Cannot scan? Enter the key by hand"), h("code", { class: "secret" }, setup.secret.replace(/(.{4})/g, "$1 ").trim()),
          h("div", null, h("a", { href: setup.uri, class: "small" }, "Open in an authenticator app on this phone"))),
        code, err, h("div", { class: "row" }, go)));
    }

    function sessionsCard(list: Sess[]): HTMLElement {
      const others = list.filter((s) => !s.current).length;
      return card("monitor", "Signed-in devices", h("div", { class: "k-stack", style: "padding:12px 14px" },
        h("ul", { class: "list" }, list.map((s) => h("li", { class: "row between" },
          h("div", null, h("strong", null, s.label), s.current ? h("span", { class: "chip" }, "This device") : null,
            h("div", { class: "muted small" }, `${s.ip} · signed in ${dateTime(s.created)} · last active ${dateTime(s.last_seen)} · ${s.factors.join(" + ")}`)),
          s.current ? null : h("button", { class: "btn small", type: "button", onclick: (e: Event) => void busy(e.currentTarget as HTMLButtonElement, async () => { try { await del(`/api/security/sessions/${s.ref}`); toast("Signed out", "ok"); await reload(); } catch (x) { fail(x); } }) }, "Sign out")))),
        others ? h("div", { class: "row" }, h("button", { class: "btn small", type: "button", onclick: (e: Event) => void busy(e.currentTarget as HTMLButtonElement, async () => { try { const r = await post<{ closed: number }>("/api/security/sessions/revoke-others"); toast(`${r.closed} signed out`, "ok"); await reload(); } catch (x) { fail(x); } }) }, icon("logout", 15), `Sign out the other ${others}`)) : null), { flush: true });
    }

    function activityCard(a: Activity): HTMLElement {
      const rows = [...a.events.map((e) => ({ ts: e.ts, bad: !e.ok, text: `${nice(EVENT, e.kind)}${e.method ? " (" + e.method + ")" : ""}`, sub: `${e.device} · ${e.ip}${e.detail ? " · " + e.detail : ""}` })),
        ...a.audit.map((e) => ({ ts: e.ts, bad: false, text: nice(ACTION, e.action), sub: e.detail || e.ip }))].sort((x, y) => y.ts - x.ts).slice(0, 40);
      return card("history", "Recent activity", rows.length ? h("ul", { class: "list", style: "padding:6px 14px" }, rows.map((r) => h("li", null, icon(r.bad ? "alert" : "check", 15), " ", h("strong", null, r.text), h("span", { class: "muted small" }, ` · ${dateTime(r.ts)}`), h("div", { class: "muted small" }, r.sub)))) : empty("history", "Nothing yet."), { flush: true });
    }

    function lockdownCard(ov: Overview): HTMLElement {
      const btn = h("button", { class: ov.lockdown ? "btn primary" : "btn danger", type: "button", onclick: (e: Event) => void busy(e.currentTarget as HTMLButtonElement, async () => {
        try {
          if (ov.lockdown) { if (await withStepUp(() => post("/api/security/lockdown", { on: false })) !== undefined) { toast("Lockdown lifted", "ok"); await reload(); } }
          else if (confirm("Turn on lockdown? Every other device is signed out at once.")) { await post("/api/security/lockdown", { on: true }); toast("Lockdown is on", "ok"); await reload(); }
        } catch (x) { fail(x); }
      }) }, icon("alert", 16), ov.lockdown ? "Lift lockdown" : "Turn on lockdown");
      return card("alert", "Emergency lockdown", h("div", { class: "k-stack", style: "padding:12px 14px" },
        lede("If you think someone else has access, turn this on. Every other device is signed out immediately and only this Security page keeps working. Lifting it needs your password again. You can also send /lockdown to the bot on Telegram."), h("div", { class: "row" }, btn)), { flush: true });
    }

    mount(root, h("div", { class: "page" }, areaNav("security"), pageHead("shield", "Security", "How you sign in, which devices are signed in, and what has happened."), body));
    void reload();
  },
};
