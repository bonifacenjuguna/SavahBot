export class ApiError extends Error {
  constructor(message: string, public status: number, public code: string = "") {
    super(message);
  }
}

const TOKEN_KEY = "savahbot.token";
const BASE_KEY = "savahbot.api";

function read(key: string): string {
  try {
    return localStorage.getItem(key) ?? "";
  } catch {
    return "";
  }
}
function write(key: string, value: string): void {
  try {
    if (value) localStorage.setItem(key, value);
    else localStorage.removeItem(key);
  } catch {
    /* private mode: the session simply will not persist */
  }
}

let memoryToken = read(TOKEN_KEY);

export function apiBase(): string {
  const configured = read(BASE_KEY) || import.meta.env?.VITE_API_URL || "";
  return configured.trim().replace(/\/+$/, "");
}
export function setApiBase(url: string): void {
  write(BASE_KEY, url.trim().replace(/\/+$/, ""));
}
export function hasToken(): boolean {
  return memoryToken !== "";
}
export function getToken(): string {
  return memoryToken;
}
export function setToken(token: string): void {
  memoryToken = token;
  write(TOKEN_KEY, token);
}

export const loggedOut = new EventTarget();

/** Sends one file as the raw request body (no JSON, no form), for uploads that can be large. The backend address is used directly, never the Vercel proxy, whose request size limit is small. */
export async function upload<T = any>(path: string, file: Blob): Promise<T> {
  let res: Response;
  try {
    res = await fetch(apiBase() + path, { method: "POST", headers: { "Content-Type": "application/octet-stream", ...(memoryToken ? { Authorization: `Bearer ${memoryToken}` } : {}) }, body: file });
  } catch { throw new ApiError("Cannot reach the backend. Large uploads need the backend address to be set on the sign-in screen.", 0); }
  const text = await res.text();
  let data: any = {};
  try { data = text ? JSON.parse(text) : {}; } catch { data = { error: text.slice(0, 200) }; }
  if (!res.ok) throw new ApiError(data.error || `Upload failed (${res.status})`, res.status);
  return data as T;
}

export async function api<T = any>(method: string, path: string, body?: unknown): Promise<T> {
  const base = apiBase();
  let res: Response;
  try {
    res = await fetch(base + path, {
      method,
      headers: {
        ...(body !== undefined ? { "Content-Type": "application/json" } : {}),
        ...(memoryToken ? { Authorization: `Bearer ${memoryToken}` } : {}),
      },
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
  } catch {
    throw new ApiError(
      base ? `Cannot reach the backend at ${base}. Check the address and that the service is running.` : "Cannot reach the backend. Set its address on the sign-in screen.",
      0,
    );
  }
  let data: any = null;
  const text = await res.text();
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      data = { error: text.slice(0, 200) };
    }
  }
  // A wrong code or password on a sign-in or confirm screen is not a lost session; anything else with 401 is.
  const signingIn = path.startsWith("/api/auth/") || path === "/api/security/step-up" || path === "/api/security/password";
  if (res.status === 401 && !signingIn) {
    setToken("");
    loggedOut.dispatchEvent(new Event("out"));
  }
  if (res.status === 403 && data?.code === "lockdown" && !location.hash.startsWith("#/security")) location.hash = "#/security";
  if (!res.ok) throw new ApiError(data?.error ?? `Request failed (${res.status}).`, res.status, data?.code ?? "");
  return data as T;
}

export const get = <T = any>(path: string) => api<T>("GET", path);
export const post = <T = any>(path: string, body: unknown = {}) => api<T>("POST", path, body);
export const patch = <T = any>(path: string, body: unknown) => api<T>("PATCH", path, body);
export const del = <T = any>(path: string) => api<T>("DELETE", path);
