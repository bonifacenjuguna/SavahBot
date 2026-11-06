/** Icon set. Every icon is an inline SVG drawn on a 24x24 grid with the current text colour: no emoji, no icon font, no network. */
const NS = "http://www.w3.org/2000/svg";

export const LOGO_VIEWBOX = [1058, 966] as const;
const LOGO_PATH = "M402 637 L403 644 L414 661 L429 676 L441 685 L469 699 L488 705 L512 709 L555 708 L582 702 L600 695 L618 685 L630 676 L646 660 L653 650 L657 641 L657 636 L652 630 L644 629 L616 639 L581 647 L542 651 L516 651 L515 650 L492 649 L468 645 L444 639 L416 629 L407 630 L403 634ZM608 391 L600 398 L597 406 L597 558 L600 565 L606 571 L616 574 L623 573 L626 574 L667 573 L669 574 L678 572 L685 567 L689 559 L689 404 L688 401 L680 392 L675 390 L611 390ZM381 391 L373 398 L370 405 L370 558 L372 564 L379 571 L388 574 L449 573 L458 567 L462 559 L462 404 L457 395 L448 390 L384 390ZM119 219 L106 241 L87 280 L72 322 L64 352 L56 394 L32 580 L9 732 L8 753 L10 767 L14 779 L23 794 L39 808 L49 813 L67 817 L85 816 L98 812 L160 783 L177 802 L202 826 L247 863 L291 892 L345 919 L397 938 L451 951 L502 957 L558 957 L608 951 L656 940 L713 920 L759 898 L804 870 L832 849 L865 820 L901 783 L961 812 L982 817 L999 816 L1016 810 L1025 804 L1035 794 L1044 778 L1048 762 L1049 747 L1046 716 L1030 612 L1030 605 L1003 414 L994 364 L979 309 L961 264 L949 241 L936 219 L909 181 L892 161 L861 130 L817 95 L794 80 L760 61 L714 41 L664 25 L618 15 L556 8 L501 8 L500 9 L487 9 L459 12 L423 18 L378 29 L334 44 L308 55 L282 68 L252 86 L217 111 L188 136 L168 156 L148 179ZM187 259 L208 229 L224 210 L259 176 L286 155 L319 134 L355 116 L401 99 L436 90 L465 85 L506 81 L567 82 L606 87 L650 97 L686 109 L712 120 L756 144 L787 166 L805 181 L827 202 L850 228 L866 250 L880 273 L892 297 L902 322 L913 358 L929 438 L939 508 L941 531 L944 546 L949 593 L953 617 L953 625 L955 633 L966 735 L964 736 L886 698 L865 689 L850 710 L837 725 L794 768 L756 799 L718 824 L674 846 L639 859 L595 870 L554 875 L505 875 L475 872 L449 867 L407 855 L382 845 L357 833 L316 808 L275 776 L223 724 L196 688 L116 727 L94 736 L93 728 L111 589 L111 581 L113 573 L113 565 L116 550 L129 447 L137 398 L147 353 L157 321 L169 292Z";

/** Stroke icons: each entry is a list of path commands. */
const PATHS = {
  overview: ["M3 3h7v7H3z", "M14 3h7v7h-7z", "M3 14h7v7H3z", "M14 14h7v7h-7z"],
  desk: ["M21 12a8 8 0 0 1-11.6 7.1L4 20l1-4.6A8 8 0 1 1 21 12z"],
  shield: ["M12 3l8 3v6c0 4.5-3.2 8.2-8 9-4.8-.8-8-4.5-8-9V6z", "M8.5 12l2.5 2.5 4.5-5"],
  commands: ["M4 5h16v14H4z", "M8 10l3 2-3 2", "M13 15h4"],
  notebook: ["M6 3h12a1 1 0 0 1 1 1v16a1 1 0 0 1-1 1H6z", "M9 3v18", "M12 8h4", "M12 12h4"],
  users: ["M16 20v-1.5a3.5 3.5 0 0 0-3.5-3.5h-5A3.5 3.5 0 0 0 4 18.5V20", "M10 12a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7z", "M20 20v-1.5a3.5 3.5 0 0 0-2.5-3.3", "M15.5 5.2a3.5 3.5 0 0 1 0 6.6"],
  chart: ["M4 20V4", "M4 20h16", "M8 16v-5", "M12 16V8", "M16 16v-3"],
  flask: ["M9 3h6", "M10 3v6L4.5 19a1.5 1.5 0 0 0 1.3 2h12.4a1.5 1.5 0 0 0 1.3-2L14 9V3", "M7.5 15h9"],
  plug: ["M9 2v5", "M15 2v5", "M6 7h12v4a6 6 0 0 1-12 0z", "M12 17v5"],
  sliders: ["M4 6h9", "M17 6h3", "M4 12h3", "M11 12h9", "M4 18h11", "M19 18h1", "M15 4v4", "M9 10v4", "M17 16v4"],
  search: ["M11 19a8 8 0 1 0 0-16 8 8 0 0 0 0 16z", "M21 21l-4.3-4.3"],
  sun: ["M12 17a5 5 0 1 0 0-10 5 5 0 0 0 0 10z", "M12 1v2", "M12 21v2", "M4.2 4.2l1.4 1.4", "M18.4 18.4l1.4 1.4", "M1 12h2", "M21 12h2", "M4.2 19.8l1.4-1.4", "M18.4 5.6l1.4-1.4"],
  moon: ["M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z"],
  monitor: ["M3 4h18v12H3z", "M8 20h8", "M12 16v4"],
  more: ["M5 12h.01", "M12 12h.01", "M19 12h.01"],
  logout: ["M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4", "M16 17l5-5-5-5", "M21 12H9"],
  check: ["M4 12.5l5 5L20 6.5"],
  x: ["M6 6l12 12", "M18 6L6 18"],
  alert: ["M12 3l10 18H2z", "M12 10v5", "M12 18h.01"],
  info: ["M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18z", "M12 11v5", "M12 8h.01"],
  arrowDown: ["M12 5v14", "M5 12l7 7 7-7"],
  copy: ["M9 9h11v11H9z", "M5 15V4h11"],
  refresh: ["M20 11a8 8 0 0 0-14.5-3.5L4 9", "M4 4v5h5", "M4 13a8 8 0 0 0 14.5 3.5L20 15", "M20 20v-5h-5"],
  send: ["M22 2L11 13", "M22 2l-7 20-4-9-9-4z"],
  link: ["M10 14a5 5 0 0 0 7 0l3-3a5 5 0 0 0-7-7l-1 1", "M14 10a5 5 0 0 0-7 0l-3 3a5 5 0 0 0 7 7l1-1"],
  youtube: ["M3 6.5A2.5 2.5 0 0 1 5.5 4h13A2.5 2.5 0 0 1 21 6.5v11a2.5 2.5 0 0 1-2.5 2.5h-13A2.5 2.5 0 0 1 3 17.5z", "M10 9l5 3-5 3z"],
  telegram: ["M22 3L2 11l7 3 3 7 3-5 5 4z", "M9 14L22 3"],
  database: ["M12 8c4.4 0 8-1.1 8-2.5S16.4 3 12 3 4 4.1 4 5.5 7.6 8 12 8z", "M4 5.5v13C4 19.9 7.6 21 12 21s8-1.1 8-2.5v-13", "M4 12c0 1.4 3.6 2.5 8 2.5s8-1.1 8-2.5"],
  clock: ["M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18z", "M12 7v5l3 2"],
  bolt: ["M13 2L4 14h7l-1 8 9-12h-7z"],
  pause: ["M8 5v14", "M16 5v14"],
  filter: ["M3 5h18l-7 8v6l-4 2v-8z"],
  pin: ["M12 17v5", "M8 3h8l-1 6 3 4H6l3-4z"],
  trash: ["M4 7h16", "M9 7V4h6v3", "M6 7l1 14h10l1-14", "M10 11v6", "M14 11v6"],
  edit: ["M4 20h4L19 9l-4-4L4 16z", "M14 6l4 4"],
  crown: ["M3 8l4.5 4L12 5l4.5 7L21 8l-2 11H5z"],
  wrench: ["M14.7 6.3a4 4 0 0 0-5 5L3 18l3 3 6.7-6.7a4 4 0 0 0 5-5l-2.4 2.4-2.6-.7-.7-2.6z"],
  star: ["M12 3l2.7 5.6 6.1.9-4.4 4.3 1 6.1L12 17l-5.4 2.9 1-6.1L3.2 9.5l6.1-.9z"],
  user: ["M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8z", "M4 21a8 8 0 0 1 16 0"],
  download: ["M12 3v12", "M7 10l5 5 5-5", "M4 21h16"],
  broadcast: ["M12 13a1.5 1.5 0 1 0 0-3 1.5 1.5 0 0 0 0 3z", "M8.5 8.5a5 5 0 0 0 0 7", "M15.5 8.5a5 5 0 0 1 0 7", "M5.6 5.6a9 9 0 0 0 0 12.8", "M18.4 5.6a9 9 0 0 1 0 12.8"],
  chevronRight: ["M9 6l6 6-6 6"],
  chevronDown: ["M6 9l6 6 6-6"],
  bot: ["M12 8V4", "M8 4h8", "M5 8h14a2 2 0 0 1 2 2v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-7a2 2 0 0 1 2-2z", "M9 13h.01", "M15 13h.01", "M9.5 16.5h5"],
  ban: ["M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18z", "M5.6 5.6l12.8 12.8"],
  plus: ["M12 5v14", "M5 12h14"],
  play: ["M7 4l13 8-13 8z"],
  lock: ["M5 11h14v10H5z", "M8 11V7a4 4 0 0 1 8 0v4"],
  circle: ["M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18z"],
  smartphone: ["M7 2h10a1 1 0 0 1 1 1v18a1 1 0 0 1-1 1H7a1 1 0 0 1-1-1V3a1 1 0 0 1 1-1z", "M11 18h2"],
} as const;

export type IconName = keyof typeof PATHS;

function el<K extends keyof SVGElementTagNameMap>(tag: K, attrs: Record<string, string>): SVGElementTagNameMap[K] {
  const e = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v);
  return e;
}

/** A decorative inline icon (hidden from screen readers; put the meaning in nearby text or an aria-label on the button). */
export function icon(name: IconName, size = 18): SVGSVGElement {
  const svg = el("svg", { viewBox: "0 0 24 24", width: String(size), height: String(size), fill: "none", stroke: "currentColor", "stroke-width": "2", "stroke-linecap": "round", "stroke-linejoin": "round", "aria-hidden": "true", focusable: "false", class: "icon" });
  for (const d of PATHS[name]) svg.appendChild(el("path", { d }));
  return svg;
}

/** The SavahBot mark, traced from the supplied logo. Filled with the current text colour so it follows light and dark themes. */
export function logo(size = 28): SVGSVGElement {
  const [w, hh] = LOGO_VIEWBOX;
  const svg = el("svg", { viewBox: `0 0 ${w} ${hh}`, width: String(size), height: String(Math.round((size * hh) / w)), fill: "currentColor", "aria-hidden": "true", focusable: "false", class: "logo" });
  svg.appendChild(el("path", { d: LOGO_PATH, "fill-rule": "evenodd" }));
  return svg;
}
