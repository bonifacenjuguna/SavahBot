# Changelog

## 1.0.0

### YouTube: authenticated account and target channel are now separate

- New `YOUTUBE_TARGET_CHANNEL_ID`: the channel whose livestream chat is moderated. Required for live mode. Never defaulted to the signed-in account's own channel.
- New `YOUTUBE_MODERATOR_ACCOUNT` (optional): refuse to run if Google reports a different signed-in account. A safety check only; the identity always comes from Google.
- `YOUTUBE_CHANNEL_ID` is deprecated and still honoured as an alias of `YOUTUBE_TARGET_CHANNEL_ID`.
- `YOUTUBE_VIDEO_ID` is validated against the target channel before attaching.
- Moderators (accounts that do not own the target channel) discover the stream through the channel's public data instead of the owner-only `liveBroadcasts.list`. Opt-in search fallback: `YOUTUBE_DISCOVERY_USE_SEARCH`.
- Permission refusals from YouTube are reported accurately, marked failed, and not retried until `YOUTUBE_PERMISSION_RETRY_SECONDS` has passed.
- The Setup page shows the signed-in account and the moderated channel, and has a **Verify access** check (`POST /api/youtube/verify`).
- OAuth: scope unchanged (`youtube.force-ssl`); existing refresh tokens keep working. Revoked or rejected logins now show a dedicated `auth_error` state with recovery instructions, and a sign-in by the wrong account is disconnected.
- Chat polling: `chatEndedEvent` ends monitoring immediately; repeated errors back off up to 5 minutes.
