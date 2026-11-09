/** Browser side of passkeys (WebAuthn): converts what the server sends into what the browser wants, and back. */
const toBuf = (b64u: string): ArrayBuffer => {
  const pad = "=".repeat((4 - (b64u.length % 4)) % 4);
  const bin = atob((b64u + pad).replace(/-/g, "+").replace(/_/g, "/"));
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out.buffer;
};
const toB64u = (buf: ArrayBuffer): string => {
  let s = "";
  new Uint8Array(buf).forEach((b) => { s += String.fromCharCode(b); });
  return btoa(s).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
};

export const passkeysSupported = (): boolean => typeof window !== "undefined" && "PublicKeyCredential" in window && !!navigator.credentials;

type Opts = Record<string, any>;

/** Ask the browser to make a new passkey. Returns the JSON the server's /passkeys/register expects. */
export async function createPasskey(pk: Opts): Promise<Opts> {
  const cred = (await navigator.credentials.create({ publicKey: {
    ...pk, challenge: toBuf(pk.challenge), user: { ...pk.user, id: toBuf(pk.user.id) },
    excludeCredentials: (pk.excludeCredentials ?? []).map((c: Opts) => ({ ...c, id: toBuf(c.id) })) } as PublicKeyCredentialCreationOptions })) as PublicKeyCredential | null;
  if (!cred) throw new Error("No passkey was created.");
  const r = cred.response as AuthenticatorAttestationResponse;
  return { id: toB64u(cred.rawId), response: { clientDataJSON: toB64u(r.clientDataJSON), attestationObject: toB64u(r.attestationObject) } };
}

/** Ask the browser to sign in with a passkey. Returns the JSON the server's /auth/passkey/verify expects. */
export async function usePasskey(pk: Opts): Promise<Opts> {
  const cred = (await navigator.credentials.get({ publicKey: {
    ...pk, challenge: toBuf(pk.challenge), allowCredentials: (pk.allowCredentials ?? []).map((c: Opts) => ({ ...c, id: toBuf(c.id) })) } as PublicKeyCredentialRequestOptions })) as PublicKeyCredential | null;
  if (!cred) throw new Error("No passkey was used.");
  const r = cred.response as AuthenticatorAssertionResponse;
  return { id: toB64u(cred.rawId), response: { clientDataJSON: toB64u(r.clientDataJSON), authenticatorData: toB64u(r.authenticatorData), signature: toB64u(r.signature) } };
}

/** Browsers say "NotAllowedError" when you cancel or it times out. Turn their errors into plain words. */
export function passkeyError(e: unknown): string {
  const name = (e as { name?: string })?.name;
  if (name === "NotAllowedError") return "The passkey prompt was cancelled or timed out.";
  if (name === "InvalidStateError") return "This device already has a passkey for SavahBot.";
  if (name === "SecurityError") return "Your browser refused passkeys on this address. The dashboard must be on HTTPS and match the passkey site setting.";
  return e instanceof Error ? e.message : "The passkey could not be used.";
}
