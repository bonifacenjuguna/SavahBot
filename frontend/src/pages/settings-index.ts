/** The map of Settings: every place a setting lives, in words, so search can find it. Each entry points at a real page or tab. */
export interface Entry { id: string; title: string; text: string; words: string; route: string; group: string; icon: string }

export const GROUPS: { id: string; title: string }[] = [
  { id: "security", title: "Security & access" }, { id: "notifications", title: "Notifications" }, { id: "integrations", title: "Integrations" }, { id: "moderation", title: "Moderation & automation" },
  { id: "weather", title: "Weather & location" }, { id: "appearance", title: "Appearance" }, { id: "privacy", title: "Privacy & data" }, { id: "backup", title: "Backup & recovery" },
  { id: "device", title: "Device & app" }, { id: "developer", title: "Developer & advanced" }];

export const INDEX: Entry[] = [
  { id: "sec-methods", title: "Sign-in methods", text: "Password, passkeys and authenticator app. Any two are needed once two are set up.", words: "password totp authenticator passkey 2fa two factor login", route: "/security", group: "security", icon: "shield" },
  { id: "sec-recovery", title: "Recovery codes", text: "One-time codes for getting in if a device is lost.", words: "recovery codes lost device backup codes", route: "/security", group: "security", icon: "shield" },
  { id: "sec-sessions", title: "Devices and sessions", text: "See and sign out devices that are signed in.", words: "sessions devices sign out revoke logout", route: "/security", group: "security", icon: "shield" },
  { id: "sec-lockdown", title: "Lockdown", text: "Sign every device out at once and require a fresh sign-in.", words: "lockdown panic emergency incident", route: "/security", group: "security", icon: "lock" },
  { id: "sec-log", title: "Sign-in activity and audit log", text: "Who signed in and what changed.", words: "audit log activity history login attempts", route: "/security", group: "security", icon: "shield" },
  { id: "n-push", title: "Push notifications", text: "Turn push on for this device, send a test, manage devices.", words: "push firebase fcm phone browser device subscribe", route: "/notifications", group: "notifications", icon: "bell" },
  { id: "n-cats", title: "Notification categories", text: "Choose what notifies you, on which channel, at which priority.", words: "categories channels priority telegram bell", route: "/notifications?tab=categories", group: "notifications", icon: "bell" },
  { id: "n-quiet", title: "Quiet hours and pause", text: "Hold push messages overnight, or pause for a while.", words: "quiet hours do not disturb sleep pause snooze schedule timezone", route: "/notifications?tab=schedule", group: "notifications", icon: "moon" },
  { id: "n-stats", title: "Notification history and stats", text: "Everything that notified you, and delivery success.", words: "history analytics statistics delivery log", route: "/notifications?tab=history", group: "notifications", icon: "bell" },
  { id: "i-youtube", title: "YouTube connection", text: "Connect the account that moderates your chat.", words: "youtube google connect oauth channel quota", route: "/setup", group: "integrations", icon: "plug" },
  { id: "i-telegram", title: "Telegram bot", text: "Your private Telegram control panel.", words: "telegram bot token webhook polling owner", route: "/setup", group: "integrations", icon: "plug" },
  { id: "m-mod", title: "Moderation rules", text: "What gets held, approved or removed.", words: "moderation spam links caps repetition blacklist approval auto suggest escalation", route: "/moderation", group: "moderation", icon: "shield" },
  { id: "m-bans", title: "Bans and timeouts", text: "See and lift bans, set limits on automatic punishments.", words: "ban unban timeout punishment limit second chance", route: "/bans", group: "moderation", icon: "ban" },
  { id: "m-knowledge", title: "Intelligence: knowledge packs and learning", text: "Patterns the bot knows, what it learned from you, live threat lists.", words: "intelligence knowledge packs scams spam learning feeds detectors", route: "/settings?tab=knowledge", group: "moderation", icon: "sparkle" },
  { id: "m-commands", title: "Commands, timers and triggers", text: "Chat commands and scheduled messages.", words: "commands timers triggers auto reply schedule automation", route: "/commands", group: "moderation", icon: "terminal" },
  { id: "m-vars", title: "Variables", text: "Your own $(names) such as $(TikTok), usable in commands, timers and messages.", words: "variables custom placeholder tiktok link discord $( name", route: "/variables", group: "moderation", icon: "sparkle" },
  { id: "s-activity", title: "Activity log", text: "What changed in SavahBot, sorted by importance and area, with search and export.", words: "activity log history audit changes sensitive export retention", route: "/activity", group: "privacy", icon: "checklist" },
  { id: "i-stream", title: "Stream alerts", text: "Live likes and viewers, subscriber alerts, members and Super Chats.", words: "likes viewers subscribers subscribe members super chat superchat sticker gift milestone live stats thank", route: "/stream-settings", group: "integrations", icon: "radio" },
  { id: "i-reader", title: "Chat reader", text: "Read chat aloud with built-in or neural voices, choose who is read, upload voice packs.", words: "chat reader tts speech voice read aloud speak kokoro piper voice pack upload", route: "/reader", group: "integrations", icon: "volume" },
  { id: "w-places", title: "Weather places", text: "Saved places, default place, device location button.", words: "weather location city place default gps coordinates", route: "/weather-settings", group: "weather", icon: "mapPin" },
  { id: "w-units", title: "Weather units and display", text: "°C or °F, wind and rain units, hours and days shown.", words: "units celsius fahrenheit kmh mph forecast hours days clock", route: "/weather-settings", group: "weather", icon: "cloudSun" },
  { id: "w-alerts", title: "Weather alerts", text: "Rules that notify you about rain, heat, wind and storms.", words: "weather alerts rules rain heat storm wind summary", route: "/weather-settings", group: "weather", icon: "cloudRain" },
  { id: "w-refresh", title: "Weather refresh and cache", text: "How often forecasts update.", words: "weather refresh interval cache open-meteo", route: "/weather-settings", group: "weather", icon: "refresh" },
  { id: "a-theme", title: "Theme", text: "Light, dark, or follow your device.", words: "theme dark light mode system night", route: "/settings?tab=appearance", group: "appearance", icon: "moon" },
  { id: "a-accent", title: "Accent colour", text: "The colour of buttons and highlights.", words: "accent colour color palette", route: "/settings?tab=appearance", group: "appearance", icon: "sparkle" },
  { id: "a-density", title: "Density and text size", text: "Compact layout, bigger text.", words: "density compact comfortable text size font larger readability accessibility zoom", route: "/settings?tab=appearance", group: "appearance", icon: "sliders" },
  { id: "a-toasts", title: "Pop-up notices", text: "Turn the little messages off, move them to the top, set how long they stay.", words: "toast toasts popup pop-up notice notices message snackbar banner white bottom top position duration seconds swipe dismiss hide off", route: "/settings?tab=appearance", group: "appearance", icon: "bell" },
  { id: "a-progress", title: "Progress line", text: "The thin line at the top: follow scrolling, stay full, or hide it.", words: "progress bar line scroll top loading hide disable full", route: "/settings?tab=appearance", group: "appearance", icon: "sliders" },
  { id: "a-motion", title: "Reduce motion", text: "Turn animations down.", words: "motion animation reduce accessibility", route: "/settings?tab=appearance", group: "appearance", icon: "sliders" },
  { id: "p-data", title: "What is stored", text: "Everything SavahBot keeps, how much, and for how long.", words: "privacy data stored retention logs history gdpr", route: "/settings?tab=privacy", group: "privacy", icon: "database" },
  { id: "p-clear", title: "Clear caches and history", text: "Clear notification history and the weather cache.", words: "clear delete cache history cleanup wipe", route: "/settings?tab=privacy", group: "privacy", icon: "trash" },
  { id: "b-export", title: "Export a backup", text: "An encrypted file of your settings and content.", words: "backup export svbak encrypt key download", route: "/backup", group: "backup", icon: "database" },
  { id: "b-import", title: "Restore a backup", text: "Check, preview and restore, with an undo.", words: "restore import recovery undo", route: "/backup", group: "backup", icon: "database" },
  { id: "d-install", title: "Install the app", text: "Add SavahBot to your home screen or desktop.", words: "install pwa app home screen offline", route: "/settings?tab=device", group: "device", icon: "smartphone" },
  { id: "d-local", title: "Data on this device", text: "See and clear what this browser stores.", words: "local storage cache service worker clear device", route: "/settings?tab=device", group: "device", icon: "smartphone" },
  { id: "x-health", title: "Service health", text: "Database, Redis, background work and features.", words: "health status redis database leader scheduler diagnostics", route: "/settings?tab=developer", group: "developer", icon: "gauge" },
  { id: "x-config", title: "Configuration check", text: "Plain-language problems with your environment settings.", words: "config validation env environment problems check", route: "/settings?tab=developer", group: "developer", icon: "checklist" },
  { id: "x-all", title: "All environment settings", text: "Every option, searchable, with reset to default.", words: "all settings env variables options advanced railway", route: "/settings?tab=all", group: "developer", icon: "sliders" },
];

const KEY = "savahbot.settings.recent";
export const recents = (): string[] => { try { return JSON.parse(localStorage.getItem(KEY) ?? "[]") as string[]; } catch { return []; } };
export function remember(id: string): void {
  try { localStorage.setItem(KEY, JSON.stringify([id, ...recents().filter((x) => x !== id)].slice(0, 6))); } catch { /* private mode */ }
}

/** Plain scoring: whole-word and prefix hits in the title count most, then the description and hidden keywords. */
export function search(q: string): Entry[] {
  const terms = q.toLowerCase().split(/\s+/).filter(Boolean);
  if (!terms.length) return [];
  const scored = INDEX.map((e) => {
    const t = e.title.toLowerCase(), d = e.text.toLowerCase(), w = e.words.toLowerCase();
    let score = 0;
    for (const x of terms) {
      const s = t.includes(x) ? (t.startsWith(x) || t.includes(` ${x}`) ? 6 : 4) : d.includes(x) ? 2 : w.includes(x) ? 3 : 0;
      if (!s) return { e, score: 0 };       // every word must match somewhere
      score += s;
    }
    return { e, score };
  });
  return scored.filter((x) => x.score > 0).sort((a, b) => b.score - a.score).map((x) => x.e).slice(0, 12);
}
