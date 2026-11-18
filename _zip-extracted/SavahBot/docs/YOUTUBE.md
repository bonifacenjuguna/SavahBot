# YouTube guide

Signing in, moderating your own or someone else's channel, quota and permissions.

## Moderating someone else's channel (appointed moderator)

SavahBot keeps two identities apart:

| | What it is | Where it is set |
|---|---|---|
| **Signed-in account** (the moderator) | The Google account you press *Connect Google account* with. Every YouTube request, including deletes and bans, is made as this account. | The sign-in itself. `YOUTUBE_MODERATOR_ACCOUNT` is only an optional safety check. |
| **Target channel** | The channel whose live chat is read and moderated. | `YOUTUBE_TARGET_CHANNEL_ID` |

Example: Creator A owns the channel and streams. Creator B is appointed as A's moderator.
1. Creator A opens YouTube Studio > Settings > Community and adds Creator B's channel as a **moderator**. (Creator A never gives B a password.)
2. Creator B deploys SavahBot and presses **Connect Google account**, signing in as **B**.
3. Creator B sets `YOUTUBE_TARGET_CHANNEL_ID` to **A's** channel ID (starts with `UC`; in YouTube Studio it is under Settings > Channel > Advanced settings, or paste A's `@handle`).
4. SavahBot now reads and moderates **A's** live chat. The Setup page shows *Signed in as B* and *Moderating A*.

Finding the stream: if `YOUTUBE_VIDEO_ID` is set (an ID or a full video link), SavahBot uses that video and refuses it if it belongs to a different channel. If it is empty, SavahBot searches for the target channel's live stream. For someone else's channel, that search costs about 100 quota units, so it runs every `YOUTUBE_TARGET_DETECT_INTERVAL_SECONDS` (default 600) and may use at most `YT_DETECT_BUDGET_FRACTION` (25%) of the day's quota. **Pasting the live video link into `YOUTUBE_VIDEO_ID` (or the Settings page) is cheaper and attaches instantly.** If you own the target channel, SavahBot uses the cheap lookup of your own active broadcast instead and never searches.

What is documented, and what is not. YouTube's documentation says a channel **owner or a chat moderator** may ban users (`liveChatBans.insert`). For deleting messages (`liveChatMessages.delete`) the page's wording is unclear, and the documentation does not say whether a moderator-only account may look up another channel's live stream or read its chat. SavahBot therefore tries each operation with the moderator's credentials and reports YouTube's real answer. It never shows a success that YouTube did not confirm, and it does not retry a refused permission over and over. If YouTube refuses:
- reading the chat: state `no_permission`, with the instruction to ask the owner to appoint the signed-in account as a moderator. SavahBot stops reading that chat and looks again after `YOUTUBE_PERMISSION_RETRY_SECONDS` (default 300);
- delete, ban or timeout: that approval is marked failed, with the reason (not a moderator, or the target is a moderator or the owner). A "not permitted" answer starts a **five-minute cooldown for that kind of action**: during it SavahBot sends no further requests of that kind and spends no quota, a batch of deletes stops at the first refusal, and no ban is attempted after its deletes were refused. The cooldown ends early if the stream ends or a different account signs in;
- an invalid or revoked login: a *Reconnect Google account* message. Repeated unexpected errors are retried with a growing delay (30 s, 1 min, 2 min ... up to 5 min) instead of every 30 seconds.

**Which account signed in is checked, and it fails closed.** Right after you sign in, SavahBot asks Google which account the login belongs to, and only then keeps the login. If `YOUTUBE_MODERATOR_ACCOUNT` is set (a channel ID or `@handle`) and the account is a different one, or Google cannot confirm who it is, the sign-in is **not saved** and a previous working connection is left exactly as it was. While `YOUTUBE_MODERATOR_ACCOUNT` is set, SavahBot will not monitor a chat or perform any moderation action until the signed-in account has been confirmed to match (state `config_error`, retried every 30 seconds). With it left empty nothing is enforced, and the Setup page just shows who is signed in. A new sign-in that Google answers without a refresh token is refused outright: SavahBot never pairs one account's access token with another account's refresh token. Signing in as a **different** account replaces the connection explicitly: the message names both accounts, and the attached stream, learned permissions and cooldowns are released.

**Verify access.** The *Verify moderator access* button on the Setup page (`POST /api/youtube/verify`) asks YouTube what the signed-in account can really do: which account is signed in, whether it matches `YOUTUBE_MODERATOR_ACCOUNT`, the role (owner or moderator), and whether it can read the chat of the attached or pinned stream. It never searches for a stream (that costs 100 quota units) and never deletes or bans anything. YouTube has no dry run for those, so **delete and ban show as *Unverified* until a real action has been answered by YouTube.**

If no target channel is set, SavahBot stops with a configuration error instead of guessing. If you own the channel, press **Moderate my own channel** on the Setup page, or set `YOUTUBE_TARGET_CHANNEL_ID` to your own channel ID.

**Upgrading an existing installation.** Nothing is lost: your saved Google login, settings and data are kept. After upgrading, set `YOUTUBE_TARGET_CHANNEL_ID` (or press **Moderate my own channel** once). The old `YOUTUBE_CHANNEL_ID` still works as the target if you had set it, but is deprecated. `YOUTUBE_VIDEO_ID` works as before, and is now also checked against the target channel.

**Quota.** The default YouTube quota is 10,000 units a day. Reading chat is the expensive part, so the bot spreads a configurable share of the quota over the expected stream length (`YT_READ_BUDGET_FRACTION`, `YOUTUBE_EXPECTED_STREAM_HOURS`) and keeps a reserve for deletes, timeouts and bans. The sidebar shows how much is used. Sending or deleting a chat message costs 20 units and a ban or timeout 200 (all adjustable), and the bot checks it can afford a whole action before starting one.

