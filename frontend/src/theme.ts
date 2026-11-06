/** Light / dark / follow-the-device. The palette itself lives in styles.css; this only decides which one applies. */
export type Theme = "system" | "light" | "dark";
const KEY = "savahbot.theme";
const ORDER: Theme[] = ["system", "light", "dark"];

export function getTheme(): Theme {
  try {
    const v = localStorage.getItem(KEY);
    return v === "light" || v === "dark" ? v : "system";
  } catch {
    return "system";
  }
}

export function applyTheme(theme: Theme = getTheme()): void {
  if (theme === "system") document.documentElement.removeAttribute("data-theme");
  else document.documentElement.setAttribute("data-theme", theme);
}

export function setTheme(theme: Theme): void {
  try {
    if (theme === "system") localStorage.removeItem(KEY);
    else localStorage.setItem(KEY, theme);
  } catch {
    /* private mode: the choice just does not persist */
  }
  applyTheme(theme);
}

export function nextTheme(): Theme {
  return ORDER[(ORDER.indexOf(getTheme()) + 1) % ORDER.length];
}

export function themeLabel(theme: Theme = getTheme()): string {
  return theme === "system" ? "Theme: follows your device" : theme === "light" ? "Theme: light" : "Theme: dark";
}
