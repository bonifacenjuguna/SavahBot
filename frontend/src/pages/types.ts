export interface Page {
  id: string;
  title: string;
  /** Renders into `root` and returns an optional cleanup that stops timers and live-feed listeners. */
  render(root: HTMLElement, query: URLSearchParams): (() => void) | void;
}
