/** Push on this device: asks permission (only when you press the button), gets a Firebase token and tells the server about it.
 *
 * The Firebase web SDK is loaded from Google's CDN only when you turn push on, so it costs nothing otherwise. The token goes to your own
 * backend; the service-account key never comes near the browser. Messages are shown by /sw.js.
 */
import { get, post } from "./api.js";

const SDK = "https://www.gstatic.com/firebasejs/10.14.1";
const FLAG = "savahbot.push";

export interface PushConfig { push_ready: boolean; web_ready: boolean; web: Record<string, string>; vapid_key: string; checklist: { name: string; set: boolean }[]; problems: string[] }
export type PushState =
  | { kind: "unsupported"; why: string }
  | { kind: "needs-install"; why: string }
  | { kind: "not-configured" }
  | { kind: "blocked" }
  | { kind: "off" }
  | { kind: "on" };

const flag = (): boolean => { try { return localStorage.getItem(FLAG) === "1"; } catch { return false; } };
const setFlag = (on: boolean): void => { try { on ? localStorage.setItem(FLAG, "1") : localStorage.removeItem(FLAG); } catch { /* private mode */ } };

export const isStandalone = (): boolean => matchMedia("(display-mode: standalone)").matches || (navigator as { standalone?: boolean }).standalone === true;
const isIOS = (): boolean => /iphone|ipad|ipod/i.test(navigator.userAgent) || (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);

export async function pushState(cfg: PushConfig | null): Promise<PushState> {
  if (!("serviceWorker" in navigator) || !("PushManager" in window) || !("Notification" in window)) {
    if (isIOS() && !isStandalone()) return { kind: "needs-install", why: "On iPhone and iPad, push works only after you add SavahBot to the Home Screen (Share, then Add to Home Screen) and open it from there. iOS 16.4 or newer is needed." };
    return { kind: "unsupported", why: "This browser cannot receive push messages. Try Chrome, Edge, Firefox, or Safari 16.4+ with the app added to the Home Screen." };
  }
  if (isIOS() && !isStandalone()) return { kind: "needs-install", why: "On iPhone and iPad, open SavahBot from the Home Screen icon first. Safari tabs cannot receive push." };
  if (!cfg || !cfg.push_ready || !cfg.web_ready) return { kind: "not-configured" };
  if (Notification.permission === "denied") return { kind: "blocked" };
  return Notification.permission === "granted" && flag() ? { kind: "on" } : { kind: "off" };
}

async function messaging(cfg: PushConfig): Promise<{ getToken: (m: unknown, o: unknown) => Promise<string>; deleteToken: (m: unknown) => Promise<boolean>; m: unknown }> {
  const app = await import(/* @vite-ignore */ `${SDK}/firebase-app.js`);
  const msg = await import(/* @vite-ignore */ `${SDK}/firebase-messaging.js`);
  const existing = app.getApps().find((a: { name: string }) => a.name === "savahbot");
  const fb = existing ?? app.initializeApp(cfg.web, "savahbot");
  return { getToken: msg.getToken, deleteToken: msg.deleteToken, m: msg.getMessaging(fb) };
}

async function worker(): Promise<ServiceWorkerRegistration> {
  const reg = (await navigator.serviceWorker.getRegistration("/")) ?? (await navigator.serviceWorker.register("/sw.js", { scope: "/" }));
  await navigator.serviceWorker.ready;
  return reg;
}

/** Must be called from a button press: browsers only show the permission prompt for a user gesture. */
export async function enablePush(cfg: PushConfig): Promise<void> {
  const perm = await Notification.requestPermission();
  if (perm !== "granted") throw new Error(perm === "denied" ? "Notifications are blocked for this site. Allow them in the browser's site settings, then try again." : "Permission was not given.");
  await sync(cfg, true);
  setFlag(true);
}

/** Gets the current token and makes sure the server knows it. Called after enabling and quietly on every start (tokens can rotate). */
async function sync(cfg: PushConfig, loud: boolean): Promise<void> {
  const reg = await worker();
  const f = await messaging(cfg);
  let token = "";
  try { token = await f.getToken(f.m, { vapidKey: cfg.vapid_key, serviceWorkerRegistration: reg }); } catch (e) {
    if (loud) throw new Error(`Firebase could not give this device a token (${e instanceof Error ? e.message : e}). Check the web app values and the VAPID key.`);
    return;
  }
  if (!token) throw new Error("Firebase returned no token.");
  await post("/api/notify/devices", { token, installed: isStandalone() });
  try { sessionStorage.setItem("savahbot.fcm", token); } catch { /* ignore */ }
}

export async function disablePush(cfg: PushConfig | null): Promise<void> {
  setFlag(false);
  let token = "";
  try { token = sessionStorage.getItem("savahbot.fcm") ?? ""; } catch { /* ignore */ }
  try {
    if (cfg?.web_ready) {
      const f = await messaging(cfg);
      if (!token) token = await f.getToken(f.m, { vapidKey: cfg.vapid_key, serviceWorkerRegistration: await worker() }).catch(() => "");
      await f.deleteToken(f.m).catch(() => false);
    }
  } finally {
    if (token) await post("/api/notify/devices/unregister", { token }).catch(() => undefined);
  }
}

/** Quiet refresh on start for a device that already turned push on. Never prompts. */
export async function resumePush(): Promise<void> {
  if (!flag() || !("Notification" in window) || Notification.permission !== "granted") return;
  try {
    const cfg = await get<PushConfig>("/api/notify/config");
    if (cfg.push_ready && cfg.web_ready) await sync(cfg, false);
  } catch { /* offline or not signed in: try again next start */ }
}

/** Taps on a system notification arrive here from the service worker. */
export function listenForTaps(onRoute: (route: string) => void, onPush: () => void, onResub: () => void): () => void {
  if (!("serviceWorker" in navigator)) return () => undefined;
  const fn = (e: MessageEvent) => {
    const d = e.data as { type?: string; route?: string } | undefined;
    if (d?.type === "notify-click" && typeof d.route === "string" && /^#\/[\w\-/]{0,60}(\?[\w=&.\-%]{0,120})?$/.test(d.route)) onRoute(d.route);
    else if (d?.type === "notify-push") onPush();
    else if (d?.type === "notify-resubscribe") onResub();
  };
  navigator.serviceWorker.addEventListener("message", fn);
  return () => navigator.serviceWorker.removeEventListener("message", fn);
}
