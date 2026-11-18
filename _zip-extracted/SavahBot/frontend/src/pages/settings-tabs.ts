/** The one tab strip for everything under Settings (1.4.7). Some tabs draw inside the Settings page; the rest are their own pages that show this same strip on top, so it feels like one place. */
import { navigate } from "../router.js";
import { hasKeyboard } from "../ui.js";
import { seg, type Seg } from "./widgets.js";

export interface SettingsTab { id: string; label: string; icon: string; route: string }

export const settingsTabList = (): SettingsTab[] => [
  { id: "appearance", label: "Appearance", icon: "sparkle", route: "/settings" },
  { id: "privacy", label: "Privacy & data", icon: "database", route: "/settings?tab=privacy" },
  { id: "device", label: "Device & app", icon: "smartphone", route: "/settings?tab=device" },
  ...(hasKeyboard() ? [{ id: "shortcuts", label: "Shortcuts", icon: "keyboard", route: "/settings?tab=shortcuts" }] : []),
  { id: "knowledge", label: "Intelligence", icon: "sparkle", route: "/settings?tab=knowledge" },
  { id: "reader", label: "Chat reader", icon: "volume", route: "/reader" },
  { id: "stream-settings", label: "Stream alerts", icon: "radio", route: "/stream-settings" },
  { id: "activity", label: "Activity log", icon: "checklist", route: "/activity" },
  { id: "variables", label: "Variables", icon: "sparkle", route: "/variables" },
  { id: "setup", label: "Setup", icon: "plug", route: "/setup" },
  { id: "developer", label: "Developer", icon: "gauge", route: "/settings?tab=developer" },
];

/** The strip, with `active` pressed. Choosing a tab opens it (inside Settings, or its own page). */
export function settingsTabs(active: string): Seg<string> {
  const tabs = settingsTabList();
  return seg<string>("Settings view", tabs.map((t) => ({ id: t.id, label: t.label, icon: t.icon })), active, (v) => { const t = tabs.find((x) => x.id === v); if (t) navigate(t.route); });
}
