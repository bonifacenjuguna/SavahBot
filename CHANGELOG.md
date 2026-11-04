# Changelog

## 1.0.0

### YouTube: the signed-in account and the target channel are separate

- `YOUTUBE_TARGET_CHANNEL_ID` names the channel whose live chat is moderated (a `UC…` ID or an `@handle`). It is never defaulted to the signed-in account's own channel; the **Moderate my own channel** button is an explicit choice.
- `YOUTUBE_MODERATOR_ACCOUNT` (optional) is a safety check only: the identity always comes from Google.
- `YOUTUBE_CHANNEL_ID` is deprecated and still honoured as an alias of `YOUTUBE_TARGET_CHANNEL_ID`.
- `YOUTUBE_VIDEO_ID` accepts an ID or a full video link and is checked against the target channel before attaching.
- Finding a stream on a channel you do not own uses search, capped by `YT_DETECT_BUDGET_FRACTION`.

### Safeguards added after the cross-version review

- **Delete batches stop at the first permission refusal.** Before, one refusal still sent the rest of the batch to YouTube and charged quota for each.
- **Five-minute cooldown after a permission refusal** (`YOUTUBE_PERMISSION_RETRY_SECONDS`, default 300). While it lasts, SavahBot sends nothing for that kind of action and spends no quota. An approval that includes a refused ban is stopped before any delete is sent. A new stream or a new sign-in clears it. A refusal about one protected person (a moderator or the owner) does not start a cooldown.
- **The moderator-account check fails closed.** When `YOUTUBE_MODERATOR_ACCOUNT` is set, SavahBot will not monitor or moderate until Google confirms which account is signed in. Before, a failed identity lookup let it carry on.
- **Sign-in is verified before it is saved.** The new login is checked with Google first. A wrong account, or an unconfirmable one when `YOUTUBE_MODERATOR_ACCOUNT` is set, is rejected and the previous connection is left exactly as it was.
- **No mixing of accounts.** A sign-in with no refresh token is refused, so a new account's access token is never paired with an older refresh token. The remembered account is stored with a fingerprint of the refresh token it was read with and is ignored if the token changes. Changing accounts replaces the token, the identity and any remembered refusals together, and says so.
- **`chatEndedEvent`** ends monitoring immediately.
- **Exponential backoff** for repeated errors: 30 s, 60 s, 120 s, 240 s, then 5 minutes. Any good answer resets it.
- **Verify access** on the Setup page (`POST /api/youtube/verify`). It probes reading for real, never searches, and reports delete and ban as unverified until YouTube has answered a real action.
- The signed-in account lookup no longer spends quota it does not have.

### Not verified against the real YouTube API

Whether a moderator-only account can read another channel's chat, delete messages there, or find its live stream has only been tested against a simulated server. See the README.
