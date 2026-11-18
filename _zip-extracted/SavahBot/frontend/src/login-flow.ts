/** Sign-in after the first step: any two of password, passkey, authenticator code, recovery code. */
import { ApiError, post } from "./api.js";
import { h } from "./dom.js";
import { icon } from "./icons.js";
import { passkeyError, passkeysSupported, usePasskey } from "./passkeys.js";

export interface LoginReply { token?: string; setup_needed?: boolean; step?: "more"; ticket?: string; have?: string[]; methods?: string[]; lockdown?: boolean }
type Next = (reply: LoginReply) => void;

/** The screen shown when one proof is not enough. `have` is what you already proved. */
export function secondStep(reply: LoginReply, done: Next, back: () => void): HTMLElement {
  const methods = reply.methods ?? [];
  let ticket = reply.ticket ?? "";
  const err = h("p", { class: "lc-err", role: "alert" });
  const code = h("input", { type: "text", inputmode: "numeric", autocomplete: "one-time-code", placeholder: "6-digit code", maxlength: 12, class: "lc-code", "aria-label": "Authenticator code" }) as HTMLInputElement;
  const recovery = h("input", { type: "text", autocomplete: "off", placeholder: "XXXXX-XXXXX", maxlength: 14, "aria-label": "Recovery code", hidden: true }) as HTMLInputElement;
  const pw = h("input", { type: "password", autocomplete: "current-password", placeholder: "Password", "aria-label": "Password", hidden: true }) as HTMLInputElement;
  let mode: "totp" | "recovery" | "password" = methods.includes("totp") ? "totp" : methods.includes("password") ? "password" : "recovery";
  const go = h("button", { class: "btn primary lc-btn", type: "submit" }, icon("lock", 16), "Continue") as HTMLButtonElement;
  const swap = h("div", { class: "lc-alt" });

  const show = () => {
    code.hidden = mode !== "totp"; recovery.hidden = mode !== "recovery"; pw.hidden = mode !== "password";
    ({ totp: code, recovery, password: pw })[mode].focus({ preventScroll: true });
    swap.replaceChildren(...(["totp", "recovery", "password"] as const).filter((m) => m !== mode && (m === "recovery" ? methods.includes("recovery") : methods.includes(m)))
      .map((m) => h("button", { class: "lc-link", type: "button", onclick: () => { mode = m; err.textContent = ""; show(); } },
        m === "totp" ? "Use an authenticator code" : m === "recovery" ? "Use a recovery code" : "Use my password")));
  };
  const fail = (e: unknown) => { err.textContent = e instanceof ApiError || e instanceof Error ? (e instanceof ApiError || e.name === "Error" ? e.message : passkeyError(e)) : "Something went wrong."; };
  const run = async (fn: () => Promise<LoginReply>) => {
    err.textContent = ""; go.disabled = true;
    try { const r = await fn(); if (r.ticket) ticket = r.ticket; done(r); } catch (e) { fail(e); } finally { go.disabled = false; }
  };
  const passkeyBtn = methods.includes("passkey") && passkeysSupported()
    ? h("button", { class: "btn lc-btn", type: "button", onclick: () => void run(async () => {
        const o = await post<{ ticket: string; publicKey: Record<string, unknown> }>("/api/auth/passkey/options", { ticket });
        ticket = o.ticket;
        let cred;
        try { cred = await usePasskey(o.publicKey); } catch (e) { throw new Error(passkeyError(e)); }
        return post<LoginReply>("/api/auth/passkey/verify", { ticket, credential: cred });
      }) }, icon("key", 16), "Use a passkey")
    : null;

  show();
  const have = (reply.have ?? []).map((x) => ({ password: "your password", passkey: "your passkey", totp: "your authenticator code", recovery: "a recovery code" } as Record<string, string>)[x] ?? x);
  return h("form", { class: "login-card", onsubmit: (e: Event) => {
    e.preventDefault();
    void run(() => mode === "password" ? post<LoginReply>("/api/auth/login", { password: pw.value, ticket })
      : post<LoginReply>("/api/auth/factor", { ticket, method: mode, code: (mode === "totp" ? code : recovery).value }));
  } },
    h("div", { class: "lc-top" }, h("div", null, h("h1", null, "One more step"), h("p", null, `You proved ${have.join(" and ")}. Prove one more thing to finish signing in.`))),
    code, recovery, pw, err, go, passkeyBtn, swap,
    h("button", { class: "lc-link", type: "button", onclick: back }, "Start over"));
}

/** The "Use a passkey" button on the first screen: passkey first, then a second proof. */
export function passkeyFirst(done: Next, setErr: (m: string) => void): HTMLElement | null {
  if (!passkeysSupported()) return null;
  return h("button", { class: "btn lc-btn", type: "button", onclick: async () => {
    setErr("");
    try {
      const o = await post<{ ticket: string; publicKey: Record<string, unknown> }>("/api/auth/passkey/options", {});
      const cred = await usePasskey(o.publicKey).catch((e) => { throw new Error(passkeyError(e)); });
      done(await post<LoginReply>("/api/auth/passkey/verify", { ticket: o.ticket, credential: cred }));
    } catch (e) { setErr(e instanceof Error ? e.message : "The passkey could not be used."); }
  } }, icon("key", 16), "Sign in with a passkey");
}
