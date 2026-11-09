# Design system

SavahBot has one visual language. New screens reuse it; nothing here introduces a second one.

## Tokens (`frontend/src/styles.css`)
`--bg --rail --panel --raised --line --ink --muted` for surfaces and text; `--accent / --accent-ink` for the one brand colour; `--ok --warn --bad --live --demo --standby` for status; `--radius --radius-sm` for corners. Light, dark and system themes are all defined here. Use `color-mix()` on these tokens for tints, never hard-coded colours.

## Appearance preferences (`appearance.ts`, `appearance.css`)
Stored per device in `localStorage`, applied as attributes on `<html>`:

| Attribute | Values | Effect |
|---|---|---|
| `data-accent` | teal, violet, rose, amber, green (absent = indigo) | Replaces only `--accent`, `--accent-ink`, `--focus` |
| `data-density` | compact (absent = comfortable) | Smaller block headers and buttons; touch targets stay 44px on touch screens |
| `data-motion` | reduce (absent = follow system) | Switches animation and transitions off for this app |

Each accent pair meets WCAG contrast: text on the accent at least 4.5:1, the accent against its page background at least 3:1 (checked when the CSS was generated).

## Components (reuse these)
`.block` cards (`card()` in `pages/shared.ts`), `pageHead()`, `seg()` segmented control, `figures()` number strips, `invite()` empty states, `lede()` intro text, `kcard()` Knowledge cards, `tile()` link tiles, `.chip`, `.btn` and `.btn.primary`, `areaNav()`. Icons come from `icons.ts` (stroke SVG, 24px grid); add new ones there.

## Rules
- Mobile first, 360px wide minimum, 44px touch targets, no horizontal page scroll.
- Never rely on colour alone: pair status colour with text or an icon.
- Respect `prefers-reduced-motion`.
- Controls must do something real. No placeholder switches.
