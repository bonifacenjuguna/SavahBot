/** Inline SVG icon set (24x24, stroke based, inherits currentColor). No emoji, no icon font, no network. */
type Shape = string | { c: [number, number, number] } | { r: [number, number, number, number, number] } | { pts: string };

const ICONS: Record<string, Shape[]> = {
  desk: [{ r: [3, 3, 7, 9, 1] }, { r: [14, 3, 7, 5, 1] }, { r: [14, 12, 7, 9, 1] }, { r: [3, 16, 7, 5, 1] }],
  shield: ["M20 13c0 5-3.5 7.5-7.66 8.95a1 1 0 0 1-.67-.01C7.5 20.5 4 18 4 13V6a1 1 0 0 1 1-1c2 0 4.5-1.2 6.24-2.72a1.17 1.17 0 0 1 1.52 0C14.51 3.81 17 5 19 5a1 1 0 0 1 1 1z"],
  terminal: ["m4 17 6-6-6-6", "M12 19h8"],
  notebook: ["M4 19.5v-15A2.5 2.5 0 0 1 6.5 2H19a1 1 0 0 1 1 1v18a1 1 0 0 1-1 1H6.5a1 1 0 0 1 0-5H20"],
  users: ["M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2", { c: [9, 7, 4] }, "M22 21v-2a4 4 0 0 0-3-3.87", "M16 3.13a4 4 0 0 1 0 7.75"],
  chart: ["M3 3v16a2 2 0 0 0 2 2h16", "M18 17V9", "M13 17V5", "M8 17v-3"],
  flask: ["M10 2v7.527a2 2 0 0 1-.211.896L4.72 20.55a1 1 0 0 0 .9 1.45h12.76a1 1 0 0 0 .9-1.45l-5.069-10.127A2 2 0 0 1 14 9.527V2", "M8.5 2h7", "M7 16h10"],
  plug: ["M12 22v-5", "M9 8V2", "M15 8V2", "M18 8v5a4 4 0 0 1-4 4h-4a4 4 0 0 1-4-4V8Z"],
  sliders: ["M21 4h-7", "M10 4H3", "M21 12h-9", "M8 12H3", "M21 20h-5", "M12 20H3", "M14 2v4", "M8 10v4", "M16 18v4"],
  search: [{ c: [11, 11, 8] }, "m21 21-4.3-4.3"],
  sun: [{ c: [12, 12, 4] }, "M12 2v2", "M12 20v2", "m4.93 4.93 1.41 1.41", "m17.66 17.66 1.41 1.41", "M2 12h2", "M20 12h2", "m6.34 17.66-1.41 1.41", "m19.07 4.93-1.41 1.41"],
  moon: ["M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9Z"],
  monitor: [{ r: [2, 3, 20, 14, 2] }, "M8 21h8", "M12 17v4"],
  menu: ["M4 6h16", "M4 12h16", "M4 18h16"],
  more: [{ c: [12, 12, 1] }, { c: [19, 12, 1] }, { c: [5, 12, 1] }],
  x: ["M18 6 6 18", "m6 6 12 12"],
  send: ["m22 2-7 20-4-9-9-4Z", "M22 2 11 13"],
  check: ["M20 6 9 17l-5-5"],
  trash: ["M3 6h18", "M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6", "M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"],
  pencil: ["M17 3a2.85 2.83 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5Z"],
  pin: ["M12 17v5", "M9 10.76a2 2 0 0 1-1.11 1.79l-1.78.9A2 2 0 0 0 5 15.24V16a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1v-.76a2 2 0 0 0-1.11-1.79l-1.78-.9A2 2 0 0 1 15 10.76V7a1 1 0 0 1 1-1 2 2 0 0 0 0-4H8a2 2 0 0 0 0 4 1 1 0 0 1 1 1z"],
  copy: [{ r: [8, 8, 14, 14, 2] }, "M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2"],
  refresh: ["M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8", "M21 3v5h-5", "M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16", "M8 16H3v5"],
  download: ["M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4", "m7 10 5 5 5-5", "M12 15V3"],
  message: ["M7.9 20A9 9 0 1 0 4 16.1L2 22Z"],
  flag: ["M4 15s1-1 4-1 5 2 8 2 4-1 4-1V3s-1 1-4 1-5-2-8-2-4 1-4 1z", "M4 22v-7"],
  ban: [{ c: [12, 12, 10] }, "m4.9 4.9 14.2 14.2"],
  alert: ["m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3", "M12 9v4", "M12 17h.01"],
  zap: ["M4 14a1 1 0 0 1-.78-1.63l9.9-10.2a.5.5 0 0 1 .86.46l-1.92 6.02A1 1 0 0 0 13 10h7a1 1 0 0 1 .78 1.63l-9.9 10.2a.5.5 0 0 1-.86-.46l1.92-6.02A1 1 0 0 0 11 14z"],
  activity: ["M22 12h-2.48a2 2 0 0 0-1.93 1.46l-2.35 8.36a.25.25 0 0 1-.48 0L9.24 2.18a.25.25 0 0 0-.48 0l-2.35 8.36A2 2 0 0 1 4.49 12H2"],
  logout: ["M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4", "m16 17 5-5-5-5", "M21 12H9"],
  chevronRight: ["m9 18 6-6-6-6"],
  chevronDown: ["m6 9 6 6 6-6"],
  arrowDown: ["M12 5v14", "m19 12-7 7-7-7"],
  plus: ["M5 12h14", "M12 5v14"],
  play: [{ pts: "6 3 20 12 6 21 6 3" }],
  pause: [{ r: [14, 4, 4, 16, 1] }, { r: [6, 4, 4, 16, 1] }],
  info: [{ c: [12, 12, 10] }, "M12 16v-4", "M12 8h.01"],
  lock: [{ r: [3, 11, 18, 11, 2] }, "M7 11V7a5 5 0 0 1 10 0v4"],
  wifi: ["M12 20h.01", "M2 8.82a15 15 0 0 1 20 0", "M5 12.859a10 10 0 0 1 14 0", "M8.5 16.429a5 5 0 0 1 7 0"],
  wifiOff: ["M12 20h.01", "M8.5 16.429a5 5 0 0 1 7 0", "M5 12.859a10 10 0 0 1 5.17-2.69", "M19 12.859a10 10 0 0 0-2.007-1.523", "M2 8.82a15 15 0 0 1 4.177-2.643", "M22 8.82a15 15 0 0 0-11.288-3.764", "m2 2 20 20"],
  gauge: ["m12 14 4-4", "M3.34 19a10 10 0 1 1 17.32 0"],
  clock: [{ c: [12, 12, 10] }, "M12 6v6l4 2"],
  bell: ["M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9", "M10.3 21a1.94 1.94 0 0 0 3.4 0"],
  filter: ["M22 3H2l8 9.46V19l4 2v-8.54z"],
  timer: ["M10 2h4", "M12 14l3-3", { c: [12, 14, 8] }],
  command: ["M15 6v12a3 3 0 1 0 3-3H6a3 3 0 1 0 3 3V6a3 3 0 1 0-3 3h12a3 3 0 1 0-3-3"],
  star: ["M11.525 2.295a.53.53 0 0 1 .95 0l2.31 4.679a2.123 2.123 0 0 0 1.595 1.16l5.166.756a.53.53 0 0 1 .294.904l-3.736 3.638a2.123 2.123 0 0 0-.611 1.878l.882 5.14a.53.53 0 0 1-.771.56l-4.618-2.428a2.122 2.122 0 0 0-1.973 0L6.396 21.01a.53.53 0 0 1-.77-.56l.881-5.139a2.122 2.122 0 0 0-.611-1.879L2.16 9.795a.53.53 0 0 1 .294-.906l5.165-.755a2.122 2.122 0 0 0 1.597-1.16z"],
  user: ["M19 21v-2a4 4 0 0 0-4-4H9a4 4 0 0 0-4 4v2", { c: [12, 7, 4] }],
  quote: ["M3 21c3 0 7-1 7-8V5c0-1.25-.756-2.017-2-2H4c-1.25 0-2 .75-2 1.972V11c0 1.25.75 2 2 2 1 0 1 0 1 1v1c0 1-1 2-2 2s-1 .008-1 1.031V21z", "M15 21c3 0 7-1 7-8V5c0-1.25-.757-2.017-2-2h-4c-1.25 0-2 .75-2 1.972V11c0 1.25.75 2 2 2h.75c0 2.25.25 4-2.75 4v3z"],
  bot: ["M12 8V4H8", { r: [4, 8, 16, 12, 2] }, "M2 14h2", "M20 14h2", "M15 13v2", "M9 13v2"],
  telegram: ["m22 2-7 20-4-9-9-4Z"],
  youtube: [{ r: [2, 5, 20, 14, 4] }, { pts: "10 9 15 12 10 15 10 9" }],
  database: ["M3 5v14a9 3 0 0 0 18 0V5", "M3 12a9 3 0 0 0 18 0", "M3 5a9 3 0 0 1 18 0a9 3 0 0 1-18 0"],
  external: ["M15 3h6v6", "M10 14 21 3", "M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"],
  list: ["M8 6h13", "M8 12h13", "M8 18h13", "M3 6h.01", "M3 12h.01", "M3 18h.01"],
  history: ["M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8", "M3 3v5h5", "M12 7v5l4 2"],
  trending: ["M22 7 13.5 15.5 8.5 10.5 2 17", "M16 7h6v6"],
  inbox: ["M22 12h-6l-2 3h-4l-2-3H2", "M5.45 5.11 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z"],
  upload: ["M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4", "m17 8-5-5-5 5", "M12 3v12"],
  layers: ["m12.83 2.18a2 2 0 0 0-1.66 0L2.6 6.08a1 1 0 0 0 0 1.83l8.58 3.91a2 2 0 0 0 1.66 0l8.58-3.9a1 1 0 0 0 0-1.83Z", "m22 17.65-9.17 4.16a2 2 0 0 1-1.66 0L2 17.65", "m22 12.65-9.17 4.16a2 2 0 0 1-1.66 0L2 12.65"],
  repeat: ["m17 2 4 4-4 4", "M3 11v-1a4 4 0 0 1 4-4h14", "m7 22-4-4 4-4", "M21 13v1a4 4 0 0 1-4 4H3"],
  keyboard: [{ r: [2, 4, 20, 16, 2] }, "M6 8h.01", "M10 8h.01", "M14 8h.01", "M18 8h.01", "M8 12h.01", "M12 12h.01", "M16 12h.01", "M7 16h10"],
};

const NS = "http://www.w3.org/2000/svg";

function el<K extends string>(tag: K, attrs: Record<string, string | number>): SVGElement {
  const e = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, String(v));
  return e;
}

export type IconName = keyof typeof ICONS;

/** Returns a decorative (aria-hidden) SVG icon. */
export function icon(name: string, size = 20, cls = ""): SVGElement {
  const svg = el("svg", { viewBox: "0 0 24 24", width: size, height: size, fill: "none", stroke: "currentColor", "stroke-width": 2, "stroke-linecap": "round", "stroke-linejoin": "round", "aria-hidden": "true", focusable: "false" });
  svg.setAttribute("class", `ico ${cls}`.trim());
  for (const s of ICONS[name] ?? ICONS.info) {
    if (typeof s === "string") svg.appendChild(el("path", { d: s }));
    else if ("c" in s) svg.appendChild(el("circle", { cx: s.c[0], cy: s.c[1], r: s.c[2] }));
    else if ("r" in s) svg.appendChild(el("rect", { x: s.r[0], y: s.r[1], width: s.r[2], height: s.r[3], rx: s.r[4] }));
    else svg.appendChild(el("polygon", { points: s.pts }));
  }
  return svg;
}

/** The SavahBot mark. Inherits currentColor; transparent background. */
export function logo(size = 28, cls = ""): SVGElement {
  const svg = el("svg", { viewBox: "88 88 1080 1080", width: size, height: size, fill: "none", "aria-hidden": "true", focusable: "false" });
  svg.setAttribute("class", `logo ${cls}`.trim());
  svg.appendChild(el("path", { d: "M150 897C165 760 185 620 200 520C235 300 400 168 627 168C855 168 1020 300 1055 520C1070 620 1090 760 1104 897L985 872C900 980 770 1040 627 1040C485 1040 355 980 270 872Z", stroke: "currentColor", "stroke-width": 78, "stroke-linejoin": "round" }));
  svg.appendChild(el("rect", { x: 467, y: 512, width: 93, height: 185, rx: 20, fill: "currentColor" }));
  svg.appendChild(el("rect", { x: 695, y: 512, width: 93, height: 185, rx: 20, fill: "currentColor" }));
  svg.appendChild(el("path", { d: "M503 757C570 785 690 785 748 752C735 790 690 832 627 832C565 832 525 795 503 757Z", fill: "currentColor", stroke: "currentColor", "stroke-width": 10, "stroke-linejoin": "round" }));
  return svg;
}
