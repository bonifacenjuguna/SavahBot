/** Command palette: Ctrl/Cmd+K (or "/") to jump anywhere or run a quick action. Keyboard and touch friendly. */
import { h, mount } from "./dom.js";
import { icon, type IconName } from "./icons.js";

export interface PaletteItem { id: string; label: string; hint?: string; icon: IconName; run: () => void }

let open: HTMLElement | null = null;
let restoreFocus: HTMLElement | null = null;

export function closePalette(): void {
  open?.remove();
  open = null;
  restoreFocus?.focus();
  restoreFocus = null;
}

export function openPalette(items: PaletteItem[]): void {
  if (open) return closePalette();
  restoreFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
  const input = h("input", { type: "text", placeholder: "Go to a page or run an action", "aria-label": "Search pages and actions", autocomplete: "off", spellcheck: false });
  const list = h("ul", { class: "palette-list", role: "listbox" });
  let shown: PaletteItem[] = items;
  let active = 0;

  const paint = () => {
    mount(list, shown.length
      ? shown.map((it, i) => h("li", { role: "option", "aria-selected": String(i === active), class: i === active ? "on" : "", onclick: () => choose(i), onpointermove: () => { if (active !== i) { active = i; paint(); } } },
        icon(it.icon, 18), h("span", { class: "grow" }, it.label), it.hint ? h("span", { class: "muted small" }, it.hint) : null))
      : h("li", { class: "empty" }, "Nothing matches."));
    list.querySelector(".on")?.scrollIntoView({ block: "nearest" });
  };
  const choose = (i: number) => { const it = shown[i]; closePalette(); it?.run(); };
  input.addEventListener("input", () => {
    const q = input.value.trim().toLowerCase();
    shown = items.filter((x) => !q || x.label.toLowerCase().includes(q) || (x.hint ?? "").toLowerCase().includes(q));
    active = 0;
    paint();
  });
  input.addEventListener("keydown", (e) => {
    if (e.key === "ArrowDown") { e.preventDefault(); active = Math.min(shown.length - 1, active + 1); paint(); }
    else if (e.key === "ArrowUp") { e.preventDefault(); active = Math.max(0, active - 1); paint(); }
    else if (e.key === "Enter") { e.preventDefault(); choose(active); }
    else if (e.key === "Escape") { e.preventDefault(); closePalette(); }
    else if (e.key === "Tab") e.preventDefault(); // keep focus inside the dialog
  });
  const scrim = h("div", { class: "scrim", onclick: (e: Event) => { if (e.target === scrim) closePalette(); } },
    h("div", { class: "palette", role: "dialog", "aria-modal": "true", "aria-label": "Command palette" },
      h("div", { class: "palette-field" }, icon("search", 18), input, h("button", { class: "btn small ghost palette-close", type: "button", "aria-label": "Close", onclick: closePalette }, icon("x", 16))),
      list,
      h("div", { class: "palette-foot muted small" }, "Arrow keys to move, Enter to open, Esc to close")));
  document.body.appendChild(scrim);
  open = scrim;
  paint();
  input.focus();
}
