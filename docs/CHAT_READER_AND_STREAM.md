# Chat actions, chat reader, variables, stream alerts (1.3.0)

## Chat actions
Hold a chat line (or tap / double tap: Settings > Stream alerts > Chat actions, remembered per device). Right click works on computers.
Delete, time out and ban ask first and show the YouTube quota cost; a timeout or ban offers Undo for 10 seconds (it lifts the ban). Pins are dashboard-only and stored on that device, because YouTube has no pin call for live chat.

## Chat reader
Desk > Read chat starts reading (a tap is required by browsers). Settings > Chat reader sets voice (per device) and rules (saved on the server). Held, flagged or blocked messages are never read.
Neural voice: Kokoro, loaded in the browser from a pinned jsDelivr build and the public model host; if it fails, the built-in voice takes over and the Desk says why.
Voice packs: upload the Kokoro files (`config.json`, `tokenizer.json`, `tokenizer_config.json`, `onnx/model_quantized.onnx`, `voices/*.bin`) or a zip, or save a link to your own https host, then choose it under "Neural voice comes from". Files live in `VOICE_DIR` (default `data/voices`); on Railway attach a Volume there or they vanish on redeploy. Uploads go straight to the backend (Vercel limits request size). Limit: `VOICE_PACK_MAX_MB`.

## Custom variables
Settings > Variables. `$(Name)` works in commands, timers, auto replies, messages sent from the Desk and Telegram `/say`. Names cannot reuse built-ins; unknown names stay as typed; deleting a variable in use warns first.

## Stream alerts and live stats
Settings > Stream alerts. Member, Super Chat, Super Sticker and gift events come from chat. New subscribers use YouTube's recent-subscribers list (public subscribers only, may need re-consent) plus the channel subscriber count for milestones. Likes (may be hidden by the creator) and viewers refresh every N seconds; each refresh and each subscriber check costs about 1 quota unit.


## 1.3.2 notes

- **Where the controls are.** Read chat is in the chat header. Its status line (loading, "3 waiting", errors) is under the toolbar and hidden when there is nothing to say.
- **Neural voice and the page.** Kokoro runs in a Web Worker (`frontend/src/reader-worker.ts`), so a slow phone stays responsive while it downloads (once, about 90 MB) and speaks. If the worker cannot start, reading falls back to the built-in voice and says why.
- **Stream end.** The bot leaves "On air" when YouTube marks the chat offline, when a send or delete is refused because the chat ended, or when a quiet chat is checked and the video no longer has an active chat. The quiet check costs 1 quota unit at most every 90 seconds and never runs while chat is busy.
