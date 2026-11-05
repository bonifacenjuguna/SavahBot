export interface Page {
  id: string;
  title: string;
  /** Icon name from icons.ts, used by the sidebar, tab bar and command palette. */
  icon: string;
  /** Short description shown in the command palette. */
  blurb?: string;
  /** Renders into `root` and returns an optional cleanup that stops timers and live-feed listeners. */
  render(root: HTMLElement, query: URLSearchParams): (() => void) | void;
}
