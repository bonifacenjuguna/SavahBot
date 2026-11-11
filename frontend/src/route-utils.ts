/**
 * Pure routing rules (no DOM, no window), so they can be tested on their own. The browser side is in router.ts.
 *
 * A "route" is a page id plus an optional query string: `/settings?tab=knowledge`. Three spellings are understood and all mean the same thing:
 *   - `/settings?tab=x`   the clean URL (the only one the app produces and shows)
 *   - `#/settings?tab=x`  the old hash URL, and the "route token" the backend stores in notifications and sends in push messages
 *   - `settings`          a bare id
 * Anything else (another site, `//host`, `javascript:`, a path with more than one segment) is NOT a route, so it can never be navigated to.
 */

/** Old names that still lead somewhere sensible. */
export const ALIASES: Readonly<Record<string, string>> = { dashboard: "desk", home: "desk", index: "desk", "chat-reader": "reader" };

/** Query parameters that must never ride along in an address bar, history entry or log. Dropped when an old URL is converted. */
const SECRET_PARAM = /^(token|access_token|id_token|refresh_token|auth|authorization|password|passwd|secret|api_?key|key|code_verifier)$/i;

export type Resolved = { kind: "page"; id: string; canonical: boolean } | { kind: "notfound"; path: string };

/** One path segment: letters, digits, dash, underscore. Longer than any page id, shorter than anything abusive. */
const SEGMENT = /^[A-Za-z0-9_-]{1,60}$/;

/** What page does this pathname ask for? `ids` is the list of registered page ids. */
export function resolvePath(pathname: string, ids: readonly string[]): Resolved {
  let p = pathname;
  try { p = decodeURIComponent(pathname); } catch { return { kind: "notfound", path: pathname }; }
  const trimmed = p.replace(/^\/+|\/+$/g, "");
  if (trimmed === "" || trimmed.toLowerCase() === "index.html") return { kind: "page", id: "desk", canonical: pathname === "/desk" };
  if (!SEGMENT.test(trimmed)) return { kind: "notfound", path: pathname };
  const lower = trimmed.toLowerCase();
  const id = ids.includes(lower) ? lower : ALIASES[lower] && ids.includes(ALIASES[lower]) ? ALIASES[lower] : "";
  if (!id) return { kind: "notfound", path: pathname };
  return { kind: "page", id, canonical: pathname === `/${id}` };
}

export function stripSecrets(params: URLSearchParams): URLSearchParams {
  const out = new URLSearchParams();
  params.forEach((v, k) => { if (!SECRET_PARAM.test(k)) out.append(k, v); });
  return out;
}

/** Splits `settings?tab=x&y=1` (any of the spellings) into its path part and query part. Returns null when it is not a route at all. */
function split(href: string): { path: string; query: string } | null {
  if (typeof href !== "string" || href.length > 400) return null;
  let s = href.trim();
  if (/[\u0000-\u001f\\]/.test(s)) return null;                 // control characters and backslashes are never part of a route
  if (s.startsWith("#!/")) s = s.slice(2);
  else if (s.startsWith("#/")) s = s.slice(1);
  else if (s.startsWith("#")) return null;                        // a plain fragment such as "#top" is not a route
  if (s.startsWith("//") || /^[a-z][a-z0-9+.-]*:/i.test(s)) return null;   // another site, or javascript:, data: and so on
  const frag = s.indexOf("#");                                    // a fragment after the route is not part of it
  if (frag >= 0) s = s.slice(0, frag);
  const q = s.indexOf("?");
  const path = q >= 0 ? s.slice(0, q) : s;
  const query = q >= 0 ? s.slice(q + 1) : "";
  const m = /^\/*([A-Za-z0-9_-]{0,60})\/*$/.exec(path);          // one segment, optional slashes around it; no dots, no encoded characters, no nesting
  if (!m) return null;
  return { path: `/${m[1]}`, query };
}

/**
 * Turns any route spelling into the canonical clean URL (`/settings?tab=x`), or null if it is not a route of this app.
 * Unknown but well-formed ids ARE returned (they lead to the 404 page); malformed ones are refused.
 */
export function normalize(href: string, ids: readonly string[]): string | null {
  const s = split(href);
  if (!s) return null;
  const r = resolvePath(s.path, ids);
  const path = r.kind === "page" ? `/${r.id}` : s.path;
  const params = stripSecrets(new URLSearchParams(s.query)).toString();
  return params ? `${path}?${params}` : path;
}

/**
 * An old-style address (`/#/moderation?tab=rules`) turned into the clean one. `search` is whatever real query string came with it (an old
 * OAuth return or a share link); the hash's own parameters win. Returns null when the hash is not a route (so an ordinary `#anchor` is left alone).
 */
export function fromLegacyHash(hash: string, search: string, ids: readonly string[]): string | null {
  if (!(hash.startsWith("#/") || hash.startsWith("#!/"))) return null;
  const base = normalize(hash, ids);
  if (!base) return "/desk";                                   // "#/" followed by something unusable: land on the Desk, never loop
  const [path, q = ""] = base.split("?");
  const merged = stripSecrets(new URLSearchParams(search));
  new URLSearchParams(q).forEach((v, k) => merged.set(k, v));
  const qs = merged.toString();
  return qs ? `${path}?${qs}` : path;
}

/** `?a=1` or `a=1` or a URLSearchParams to a leading-`?` string (empty when there are no params). */
export function queryString(q: string | URLSearchParams): string {
  const s = (typeof q === "string" ? q.replace(/^\?/, "") : q.toString());
  return s ? `?${s}` : "";
}
