"""Central configuration.

Every setting is declared ONCE in the FIELDS table below. From that single table we derive:
  * the typed `Settings` object (reads real environment variables, then a local .env file)
  * `.env.example` (run `python scripts/gen_env_example.py`)
  * the settings schema the dashboard shows (for runtime-editable settings)

Every variable has a safe default, so the app boots with ZERO environment variables set.
Add a value on Railway later and it takes effect on the next deploy; nothing else to wire up.
Variables marked "reserved" are placeholders for future features and are not used yet.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from .utils import split_csv


@dataclass(frozen=True)
class Field:
    name: str
    default: Any
    description: str
    group: str


FIELDS: list[Field] = []


def _f(group: str, name: str, default: Any, description: str) -> None:
    FIELDS.append(Field(name=name, default=default, description=description, group=group))


# ---------------------------------------------------------------------------------------------
G = "App"
_f(G, "app_name", "SavahBot", "Display name used in the dashboard and Telegram messages.")
_f(G, "app_env", "production", "'production' or 'development'.")
_f(G, "log_level", "INFO", "Python log level: DEBUG, INFO, WARNING or ERROR.")
_f(G, "public_base_url", "", "Public HTTPS URL of this backend, e.g. https://savahbot.up.railway.app. Needed for the Telegram webhook and the Google OAuth redirect. Falls back to RAILWAY_PUBLIC_DOMAIN.")
_f(G, "railway_public_domain", "", "Injected automatically by Railway. Leave empty.")
_f(G, "frontend_url", "", "Public URL of the Vercel dashboard. Added to the CORS allow-list.")
_f(G, "cors_origins", "", "Extra allowed browser origins, comma separated.")
_f(G, "owner_timezone", "Africa/Nairobi", "IANA timezone used to read reminder times such as 18:30 and to show local times.")
_f(G, "bot_mode", "demo", "Active chat source: 'demo' (simulated chat) or 'live' (YouTube). Switchable at runtime from the dashboard or Telegram.")
_f(G, "api_docs_enabled", False, "Expose /docs and /openapi.json (interactive API docs).")
_f(G, "sse_max_clients", 10, "Maximum simultaneous dashboard live-feed connections.")
_f(G, "chat_buffer_size", 500, "How many recent chat messages are kept in memory for the live view.")
_f(G, "chat_retention_days", 90, "Chat messages older than this are deleted automatically. Daily totals are kept forever, so charts still reach back further.")
_f(G, "action_retention_days", 365, "Moderation history older than this is deleted automatically. Daily totals are kept forever.")

G = "Security"
_f(G, "owner_password", "", "Dashboard login password. If empty, a random one is generated on first boot and printed ONCE in the server logs.")
_f(G, "jwt_secret", "", "Secret used to sign login tokens. If empty, a random one is generated and stored in the database.")
_f(G, "jwt_expire_hours", 72, "How long a dashboard login stays valid.")
_f(G, "session_idle_minutes", 1440, "Sign a dashboard session out after this many minutes without use. 0 turns the idle limit off.")
_f(G, "security_step_up_minutes", 5, "After you re-confirm it is you, sensitive security actions stay unlocked for this many minutes.")
_f(G, "security_max_sessions", 10, "Most dashboard sessions open at once. The least recently used is closed when this is exceeded.")
_f(G, "security_log_retention_days", 365, "How long sign-in activity and the security audit log are kept.")
_f(G, "webauthn_rp_id", "", "Passkey site id. Leave empty to use the host name of FRONTEND_URL (for example dash.example.app). Must be the dashboard's host, not the API's.")
_f(G, "webauthn_origins", "", "Comma-separated dashboard origins allowed to use passkeys. Leave empty to use FRONTEND_URL.")
_f(G, "webauthn_require_uv", False, "Require passkeys to verify you (fingerprint, face or PIN). Turn on if every passkey you use supports it.")
_f(G, "trusted_proxy_hops", 1, "How many reverse proxies sit in front of this server and append to X-Forwarded-For (Railway: 1). Used to find the real client address for the sign-in lockout; addresses a client adds to the left of that are ignored. 0 means no proxy: the connection's own address is used.")
_f(G, "login_max_attempts", 5, "Failed logins allowed before the lockout starts.")
_f(G, "login_lockout_minutes", 15, "How long a locked-out client must wait.")

G = "Notifications (Firebase Cloud Messaging)"
_f(G, "firebase_project_id", "", "Firebase project ID (Project settings > General). Needed to send push notifications.")
_f(G, "firebase_client_email", "", "Service account e-mail (the client_email in the service-account JSON). Backend only; never shown in the dashboard.")
_f(G, "firebase_private_key", "", "Service account private key (the private_key in the JSON). Paste it with \\n for line breaks. Backend only; never commit it.")
_f(G, "firebase_service_account_json", "", "Alternative to the two lines above: the whole service-account JSON, or the same JSON base64 encoded. Backend only.")
_f(G, "firebase_web_api_key", "", "Firebase web app apiKey (Project settings > Your apps). Public by design; the dashboard needs it to receive pushes.")
_f(G, "firebase_web_app_id", "", "Firebase web app appId. Public by design.")
_f(G, "firebase_messaging_sender_id", "", "Firebase messagingSenderId (Cloud Messaging tab). Public by design.")
_f(G, "firebase_auth_domain", "", "Optional Firebase authDomain. Not needed for push; leave blank.")
_f(G, "firebase_vapid_key", "", "Web Push certificate public key (Cloud Messaging > Web configuration > Generate key pair). Public by design.")
_f(G, "activity_retention_days", 365, "How long the activity log is kept. 0 keeps it forever.")
_f(G, "activity_notify_sensitive", False, "Send a notification when a sensitive change is logged, such as a security or sign-in setting.")
_f(G, "voice_dir", "data/voices", "Folder where voice packs for the chat reader are stored. On Railway, attach a Volume at this path or uploads are lost on redeploy.")
_f(G, "voice_pack_max_mb", 300, "Most megabytes of voice files you can keep. Uploads that would pass this are refused.")
_f(G, "notify_retention_days", 30, "Notification history older than this is deleted automatically.")
_f(G, "notify_max_push_per_hour", 30, "Most push messages sent per hour. Extras are folded into one summary.")
_f(G, "notify_max_attempts", 5, "Times a failed push is retried (with growing delays) before it is marked failed.")

G = "Weather (Open-Meteo)"
_f(G, "weather_commercial_api_key", "", "Only if you have bought an Open-Meteo commercial plan: its API key. Leave blank for the free, non-commercial service (no key needed).")
_f(G, "weather_forecast_ttl_minutes", 15, "How long a fetched forecast counts as fresh before the next request goes to Open-Meteo.")
_f(G, "weather_stale_max_hours", 12, "If Open-Meteo is unreachable, a forecast up to this old can still be shown (clearly marked as old). Alerts never use it.")
_f(G, "weather_geocode_ttl_hours", 168, "How long place-search results are remembered.")
_f(G, "weather_timeout_seconds", 8, "How long to wait for Open-Meteo before giving up on one try.")
_f(G, "weather_retries", 2, "Extra tries after a temporary failure, with growing pauses.")

G = "Database"
_f(G, "database_url", "", "PostgreSQL URL (Railway sets DATABASE_URL for you). Empty = local SQLite file, fine for local testing only.")
_f(G, "db_pool_size", 5, "Database connection pool size (PostgreSQL).")
_f(G, "db_echo", False, "Log every SQL statement (debugging).")

G = "Telegram"
_f(G, "telegram_bot_token", "", "Bot token from @BotFather.")
_f(G, "telegram_owner_id", 0, "Your numeric Telegram user id. If 0, send /claim <OWNER_PASSWORD> to the bot once to bind yourself.")
_f(G, "telegram_mode", "webhook", "'webhook' (recommended on Railway) or 'polling'. Switchable at runtime with /tgmode.")
_f(G, "telegram_webhook_secret", "", "Secret Telegram must send with every webhook call. If empty, one is generated and stored.")
_f(G, "telegram_webhook_max_connections", 40, "Parallel webhook connections Telegram may open (1-100).")
_f(G, "telegram_allowed_updates", "message,callback_query", "Update types requested from Telegram, comma separated.")
_f(G, "telegram_poll_timeout", 30, "Long-poll timeout in seconds (polling mode).")
_f(G, "telegram_api_base", "https://api.telegram.org", "Telegram Bot API base URL (change only for a local Bot API server).")
_f(G, "telegram_drop_pending_updates", False, "Discard queued updates when switching modes.")
_f(G, "telegram_notify_pending", True, "Message you when moderation wants approval.")
_f(G, "telegram_notify_max_per_min", 6, "Cap on approval messages per minute; extras are summarised.")
_f(G, "telegram_notify_reminders", True, "Deliver reminders to Telegram.")
_f(G, "telegram_notify_stream_events", True, "Message you when the stream goes live or ends, and on quota warnings.")

G = "Google / YouTube"
_f(G, "google_client_id", "", "OAuth client id from Google Cloud Console (YouTube Data API v3 enabled).")
_f(G, "google_client_secret", "", "OAuth client secret.")
_f(G, "google_redirect_uri", "", "OAuth redirect URI. Empty = PUBLIC_BASE_URL + /api/youtube/oauth/callback (add this exact URL in Google Cloud).")
_f(G, "youtube_refresh_token", "", "Optional: paste a refresh token here, or connect from the dashboard and it is stored for you.")
_f(G, "youtube_moderator_account", "", "Optional safety check: the Google account that should be signed in, as its channel ID (UC...) or @handle. If a different account is signed in, SavahBot reports it. It never grants any permission.")
_f(G, "youtube_target_channel_id", "", "The channel whose live chat SavahBot moderates, as a channel ID (UC...) or @handle. Your own channel if you are the owner; the creator's channel if you were appointed their moderator. Not the same thing as the Google account you sign in with.")
_f(G, "youtube_channel_id", "", "Deprecated: use YOUTUBE_TARGET_CHANNEL_ID. If that is empty, this value is used as the target channel.")
_f(G, "youtube_video_id", "", "Optional: monitor this specific live video (ID or full URL). It must belong to the target channel, otherwise SavahBot refuses to attach.")
_f(G, "google_oauth_auth_url", "https://accounts.google.com/o/oauth2/v2/auth", "Google OAuth consent URL.")
_f(G, "google_oauth_token_url", "https://oauth2.googleapis.com/token", "Google OAuth token URL.")
_f(G, "google_oauth_scope", "https://www.googleapis.com/auth/youtube.force-ssl", "OAuth scope. force-ssl is required to read chat, delete messages and ban users.")
_f(G, "youtube_api_key", "", "Reserved: API key for public (unauthenticated) reads.")
_f(G, "youtube_api_base", "https://www.googleapis.com/youtube/v3", "YouTube Data API base URL.")
_f(G, "youtube_auto_detect_live", True, "Automatically find the target channel's live stream when no video ID is set.")
_f(G, "youtube_detect_interval_seconds", 180, "How often to check for a live broadcast while offline (costs 1 quota unit per check).")
_f(G, "youtube_expected_stream_hours", 4.0, "Typical stream length. The quota governor paces chat polling so a stream this long fits the daily budget.")
_f(G, "youtube_max_results", 200, "Chat messages requested per poll (200-2000).")
_f(G, "youtube_permission_retry_seconds", 300, "After YouTube refuses an action because this account lacks permission, wait this long before trying that kind of action (or reading that chat) again.")
_f(G, "youtube_use_streaming", False, "Reserved: use the streamList (gRPC) endpoint instead of polling.")
_f(G, "youtube_message_max_length", 200, "Longest message YouTube chat accepts; bot replies are trimmed to this.")
_f(G, "youtube_backfill_on_connect", True, "Store the chat history found on connect (not moderated).")

G = "YouTube quota"
_f(G, "yt_daily_quota", 10000, "Daily quota units available to your Google Cloud project.")
_f(G, "yt_quota_reset_tz", "America/Los_Angeles", "Timezone where YouTube resets quota (midnight Pacific).")
_f(G, "yt_cost_chat_list", 5, "Quota cost: read chat messages. Verify against the current YouTube docs.")
_f(G, "yt_cost_chat_insert", 20, "Quota cost: send a chat message.")
_f(G, "yt_cost_chat_delete", 20, "Quota cost: delete a chat message.")
_f(G, "yt_cost_ban", 200, "Quota cost: ban / time out a user.")
_f(G, "yt_cost_broadcast_list", 1, "Quota cost: look up your live broadcast.")
_f(G, "yt_cost_video_list", 1, "Quota cost: look up a video.")
_f(G, "yt_cost_channel_list", 1, "Quota cost: look up a channel (the signed-in account, or a @handle).")
_f(G, "yt_cost_search", 100, "Quota cost: search for a channel's live stream. Verify against the current YouTube docs.")
_f(G, "yt_detect_budget_fraction", 0.1, "Share of the daily quota that searching for another channel's live stream may use.")
_f(G, "youtube_target_detect_interval_seconds", 900, "How often to search for a live stream on a channel you do not own while it is offline. Searching is expensive, so it is also capped by YT_DETECT_BUDGET_FRACTION. Set YOUTUBE_VIDEO_ID to avoid searching.")
_f(G, "yt_cost_subscription_list", 1, "Quota cost: check recent subscribers. Verify against the current YouTube docs.")
_f(G, "yt_events_notify", True, "Tell me (bell, push, Telegram per the category settings) about new members, Super Chats, Super Stickers and membership gifts.")
_f(G, "yt_events_thank", False, "Post a thank-you in chat for members, Super Chats and gifts. Off by default: it costs YouTube quota for every message.")
_f(G, "yt_events_msg_member", "Welcome to the members, $(user)! 💚", "Thank-you for a new member. $(user) and $(count) are filled in; your own variables work too.")
_f(G, "yt_events_msg_superchat", "Thank you $(user) for the $(amount)!", "Thank-you for a Super Chat or Super Sticker. $(user) and $(amount) are filled in.")
_f(G, "yt_events_msg_gift", "Thank you $(user) for gifting $(count) memberships!", "Thank-you for membership gifts. $(user) and $(count) are filled in.")
_f(G, "yt_subs_enabled", True, "Look for new subscribers while you are live. Best effort: YouTube only lists subscribers who made their subscription public.")
_f(G, "yt_subs_minutes", 10, "How often to check for new subscribers, in minutes (5 to 120). Each check costs about 1 quota unit.")
_f(G, "yt_subs_thank", False, "Post a thank-you in chat for a new subscriber you can see by name.")
_f(G, "yt_subs_msg", "Thanks for subscribing, $(user)! 🎉", "Thank-you for a new subscriber. $(user) is filled in.")
_f(G, "yt_subs_milestone_step", 100, "Alert me each time the subscriber count passes a multiple of this. 0 turns milestones off.")
_f(G, "yt_live_enabled", True, "Track likes and people watching while you are live.")
_f(G, "yt_live_seconds", 60, "How often to refresh likes and viewers, in seconds (30 to 600). Each refresh costs about 1 quota unit.")
_f(G, "yt_live_likes_step", 100, "Alert me each time likes pass a multiple of this. 0 turns it off.")
_f(G, "yt_live_viewers_step", 50, "Alert me each time viewers pass a multiple of this for the first time in a stream. 0 turns it off.")
_f(G, "yt_cost_moderator_list", 50, "Quota cost: list moderators.")
_f(G, "yt_read_budget_fraction", 0.6, "Share of the daily quota the bot may spend reading chat (the rest is kept for actions).")
_f(G, "yt_min_poll_seconds", 5.0, "Never poll chat faster than this.")
_f(G, "yt_max_poll_seconds", 60.0, "Never wait longer than this between polls.")
_f(G, "yt_quota_warn_fraction", 0.8, "Warn on Telegram when this share of the daily quota is used.")

G = "Moderation"
_f(G, "mod_mode", "suggest", "'off' (no checks), 'suggest' (ask you to approve actions) or 'auto' (act by itself). Switchable at runtime.")
_f(G, "mod_auto_actions", "delete,timeout", "Actions allowed to run without approval in auto mode. Bans always wait for you unless 'ban' is listed.")
_f(G, "mod_exempt_levels", "owner,mod,bot", "Chat levels that are never moderated.")
_f(G, "mod_exempt_regulars", True, "Regulars are never moderated.")
_f(G, "mod_exempt_members", False, "Paying members are never moderated.")
_f(G, "mod_score_flag", 30, "Score at which a message is flagged (logged only).")
_f(G, "mod_score_delete", 55, "Score at which a message is deleted.")
_f(G, "mod_score_timeout", 90, "Score at which the author is timed out.")
_f(G, "mod_score_ban", 100, "Score at which the author is banned.")
_f(G, "mod_timeout_ladder", "60,300,900,3600", "Timeout seconds for the first, second, third... timeout. Each extra strike climbs one rung.")
_f(G, "mod_strike_decay_minutes", 60, "Strikes expire after this many minutes.")
_f(G, "mod_strikes_to_timeout", 2, "Strikes before a delete escalates to a timeout.")
_f(G, "mod_strikes_to_ban", 4, "Strikes before a timeout escalates to a ban.")
_f(G, "mod_allow_ban_escalation", True, "Allow escalation to bans (bans cost the most YouTube quota).")
_f(G, "mod_max_punishment", "ban", "The harshest action the bot may ever take: 'delete' (messages only, nobody is timed out or banned), 'timeout' or 'ban'. Lower actions are unaffected.")
_f(G, "mod_never_punish", "", "Comma-separated names or channel ids that are never timed out or banned. Their bad messages are still deleted.")
_f(G, "mod_reason_caps", "", "Cap the harshest action for one kind of trigger, as name:action pairs, e.g. 'link:delete,caps:delete,raid:ban'. Names are the signal names shown on each moderation card.")
_f(G, "mod_auto_punish_daily_cap", 0, "Most automatic timeouts and bans per day. After that the bot only deletes. 0 means no limit.")
_f(G, "mod_second_chance_hours", 0, "Automatically lift permanent bans the bot made by itself after this many hours (each lift costs YouTube quota). 0 means never.")
_f(G, "mod_pending_ttl_minutes", 30, "Unanswered approval requests expire after this long, so stale bans are never approved by accident.")
_f(G, "mod_max_deletes_per_action", 10,"Messages deleted when one grouped action is approved (protects quota).")
_f(G, "mod_action_cooldown_seconds", 60, "Do not repeat a timeout/ban on the same user within this window.")
_f(G, "mod_notify_on_flag", False, "Also message you for flag-level events.")
_f(G, "mod_new_chatter_seconds", 120, "A chatter is 'new' for this long after their first message.")
_f(G, "mod_new_chatter_weight", 15, "Extra score for a new chatter who already triggered another signal.")
_f(G, "mod_caps_enabled", True, "Detect shouting (mostly capital letters).")
_f(G, "mod_caps_min_length", 20, "Messages shorter than this are never caps-checked.")
_f(G, "mod_caps_ratio", 0.7, "Share of letters that must be capitals to trigger.")
_f(G, "mod_caps_weight", 30, "Score added by the caps signal.")
_f(G, "mod_symbols_enabled", True, "Detect symbol spam.")
_f(G, "mod_symbols_min_length", 10, "Messages shorter than this are never symbol-checked.")
_f(G, "mod_symbols_ratio", 0.5, "Share of non-alphanumeric characters that triggers.")
_f(G, "mod_symbols_weight", 25, "Score added by the symbol signal.")
_f(G, "mod_emotes_enabled", True, "Detect emote/emoji floods.")
_f(G, "mod_emotes_max", 8, "Emotes allowed in one message.")
_f(G, "mod_emotes_weight", 20, "Score added by the emote signal.")
_f(G, "mod_links_enabled", True, "Detect links (including 'site dot com' disguises).")
_f(G, "mod_links_weight", 45, "Score added by the link signal.")
_f(G, "mod_allowed_domains", "youtube.com,youtu.be", "Domains that are always allowed, comma separated.")
_f(G, "mod_permit_seconds", 60, "How long !permit lets someone post links.")
_f(G, "mod_repeat_enabled", True, "Detect repeated characters and words.")
_f(G, "mod_repeat_char_run", 10, "Same character in a row that triggers.")
_f(G, "mod_repeat_word_ratio", 0.6, "Share of repeated words (in messages of 6+ words) that triggers.")
_f(G, "mod_repeat_weight", 25, "Score added by the repetition signal.")
_f(G, "mod_length_enabled", True, "Detect overly long messages.")
_f(G, "mod_max_length", 300, "Longest normal message.")
_f(G, "mod_length_weight", 15, "Score added by the length signal.")
_f(G, "mod_blacklist_enabled", True, "Match the banned-phrase list (handles leetspeak, look-alike letters, spacing).")
_f(G, "mod_blacklist_weight", 70, "Default score for a banned phrase (each phrase can override it).")
_f(G, "mod_rate_enabled", True, "Limit how fast one user may post.")
_f(G, "mod_rate_max_messages", 5, "Messages allowed per window.")
_f(G, "mod_rate_window_seconds", 10, "Rate-limit window length.")
_f(G, "mod_rate_new_chatter_max", 3, "Messages allowed per window for new chatters.")
_f(G, "mod_rate_weight", 40, "Score added by the rate signal.")
_f(G, "mod_dup_enabled", True, "Detect the same user repeating a message.")
_f(G, "mod_dup_window_seconds", 60, "Window in which a repeat counts.")
_f(G, "mod_dup_weight", 35, "Score added by the duplicate signal (60% for the first repeat).")
_f(G, "mod_sim_enabled", True, "Detect copy-paste raids: near-identical messages from several accounts.")
_f(G, "mod_sim_window_seconds", 120, "Window for cross-account similarity.")
_f(G, "mod_sim_max_distance", 8, "Max SimHash bit distance (of 64) to call two messages similar. Lower = stricter.")
_f(G, "mod_sim_min_accounts", 4, "Distinct accounts posting similar text before it counts as a raid.")
_f(G, "mod_sim_min_length", 12, "Shortest message considered for similarity.")
_f(G, "mod_sim_weight", 45, "Score added by the raid signal.")
_f(G, "mod_interval_enabled", True, "Detect bots posting at machine-regular intervals.")
_f(G, "mod_interval_min_messages", 5, "Messages needed before timing is judged.")
_f(G, "mod_interval_max_cv", 0.15, "Timing variation (std/mean) below this looks automated.")
_f(G, "mod_interval_max_mean_gap", 120.0, "Only judge users whose average gap is under this many seconds.")
_f(G, "mod_interval_weight", 30, "Score added by the timing signal.")

# ---------------------------------------------------------------------------------------------
G = "Intelligence"
_f(G, "intel_enabled", True, "Master switch for the intelligence layer (phrase packs, typo matching, link intelligence, scam intent, statistics). Off = the bot behaves exactly as in 1.1.5.")
_f(G, "intel_max_weight", 60, "The most score the intelligence layer can add to one message on its own. Keeps it from banning anyone by itself.")
_f(G, "intel_scam_mode", "live", "Scam phrases and scam-intent scoring: off, shadow (logged, never scored) or live.")
_f(G, "intel_spam_mode", "live", "Spam and promotion phrases: off, shadow or live.")
_f(G, "intel_abuse_mode", "shadow", "Profanity and insults: off, shadow or live. Shadow by default so you can review what it would catch first.")
_f(G, "intel_harassment_mode", "live", "Threats and harassment (death wishes, doxxing, swatting): off, shadow or live.")
_f(G, "intel_typo_mode", "live", "Typo and disguise matching of blocked and known-bad phrases: off, shadow or live.")
_f(G, "intel_link_risk_mode", "live", "Link intelligence (look-alike domains, shorteners, threat lists): off, shadow or live.")
_f(G, "intel_impersonation_mode", "live", "Impersonation guard (copied or staff-like account names, 'I am the admin'): off, shadow or live.")
_f(G, "intel_obfuscation_mode", "live", "Text tricks (zalgo, hidden characters, mixed alphabets, symbol art): off, shadow or live.")
_f(G, "intel_bot_like_mode", "shadow", "Bot-like account names: off, shadow or live.")
_f(G, "intel_intent_mode", "shadow", "Naive Bayes spam-likeness: off, shadow or live.")
_f(G, "intel_known_spam_mode", "shadow", "Similarity to known spam messages (BM25): off, shadow or live.")
_f(G, "intel_raid_wave_mode", "live", "Raid wave tracker: off, shadow or live.")
_f(G, "intel_scam_scale", 1.0, "Strength multiplier for the scam detector (0.5 = half as strong, 2 = twice).")
_f(G, "intel_spam_scale", 1.0, "Strength multiplier for the spam detector.")
_f(G, "intel_abuse_scale", 1.0, "Strength multiplier for the abuse detector.")
_f(G, "intel_harassment_scale", 1.0, "Strength multiplier for the threats and harassment detector.")
_f(G, "intel_typo_scale", 1.0, "Strength multiplier for typo matching.")
_f(G, "intel_link_risk_scale", 1.0, "Strength multiplier for link intelligence.")
_f(G, "intel_impersonation_scale", 1.0, "Strength multiplier for the impersonation guard.")
_f(G, "intel_obfuscation_scale", 1.0, "Strength multiplier for text-trick detection.")
_f(G, "intel_bot_like_scale", 1.0, "Strength multiplier for bot-like accounts.")
_f(G, "intel_intent_scale", 1.0, "Strength multiplier for the Naive Bayes detector.")
_f(G, "intel_known_spam_scale", 1.0, "Strength multiplier for known-spam similarity.")
_f(G, "intel_raid_wave_scale", 1.0, "Strength multiplier for the raid wave bonus.")
_f(G, "intel_context_enabled", True, "Understand context: a question about a scam, or a warning to others, scores lower than the scam itself.")
_f(G, "intel_safe_enabled", True, "Use the safe phrases (gaming talk such as 'kill streak') to stop rules firing on normal chat.")
_f(G, "intel_languages", "en,sw,sheng", "Which language packs are active, comma separated: en, sw (Swahili), sheng.")
_f(G, "intel_protected_names", "", "Names the impersonation guard protects, comma separated (your channel name, your moderators). The demo channel name is added automatically.")
_f(G, "intel_protected_domains", "", "Your own websites, comma separated. Links that look almost like them are flagged as look-alikes, and links to them are never treated as risky.")
_f(G, "intel_intent_min_tokens", 4, "Messages shorter than this many words are not scored by the statistical detectors.")
_f(G, "intel_wave_accounts", 6, "A raid wave starts when this many brand-new accounts speak within the window below.")
_f(G, "intel_wave_window_seconds", 30, "Window for counting new accounts toward a raid wave.")
_f(G, "intel_wave_duration_seconds", 180, "How long a raid wave stays active once detected.")
_f(G, "intel_wave_weight", 15, "Score added to suspicious messages from new accounts during a raid wave.")
_f(G, "intel_learning_mode", "suggest", "What the bot does with what it learns from your approve and reject decisions: off, suggest (you decide) or auto (applies the confident ones, every change is logged and reversible).")
_f(G, "intel_learn_min_lessons", 10, "The learned model only influences scoring once it has at least this many lessons (spam and fine together). Stops a few early decisions from swinging the bot.")
_f(G, "intel_learn_from_demo", False, "Also learn from simulated (demo) decisions. Off by default so test data never teaches the bot.")
_f(G, "intel_learn_trusted_ham", True, "Learn that ordinary messages from regulars, members and mods are fine (a few per minute at most).")
_f(G, "intel_example_cap", 5000, "Most lessons kept. When there are more, the oldest are forgotten first.")
_f(G, "intel_lesson_retention_days", 0, "Delete lessons older than this many days. 0 keeps them until you forget them or the limit above is reached.")
_f(G, "intel_feeds_enabled", True, "Refresh the live data feeds (public phishing and malware domain lists) in the background.")
_f(G, "intel_feed_interval_hours", 24, "Minimum hours between refreshes of the same feed. Never lower than 1.")
_f(G, "intel_feed_max_entries", 15000, "Most domains kept from any one feed.")
_f(G, "intel_feed_max_bytes", 6000000, "Largest download accepted from a feed.")
_f(G, "intel_feed_startup_delay_seconds", 120, "Wait this long after boot before the first feed refresh, so start-up stays fast.")

G = "Commands"
_f(G, "command_prefix", "!", "Character(s) that start a chat command.")
_f(G, "command_default_cooldown", 5, "Default global cooldown (seconds) for new commands.")
_f(G, "command_user_cooldown", 10, "Default per-user cooldown (seconds) for new commands.")
_f(G, "command_max_response_length", 200, "Replies are trimmed to this many characters.")
_f(G, "command_max_render_depth", 6, "Maximum nesting of $(variables).")
_f(G, "command_max_expansions", 25, "Maximum $(variables) evaluated per reply.")
_f(G, "triggers_enabled", True, "Run auto-replies: the bot answers when a viewer sends a configured phrase or word.")
_f(G, "trigger_default_cooldown", 30, "Default global cooldown (seconds) for new auto-replies.")
_f(G, "trigger_user_cooldown", 60, "Default per-user cooldown (seconds) for new auto-replies.")
_f(G, "command_seed_defaults", True, "Create starter commands, timers, quotes and banned phrases on first boot.")
_f(G, "urlfetch_enabled", True, "Allow $(urlfetch ...) in commands (owner-created commands only).")
_f(G, "urlfetch_timeout_seconds", 4.0, "Timeout for $(urlfetch ...).")
_f(G, "urlfetch_max_bytes", 2000, "Maximum bytes read by $(urlfetch ...).")
_f(G, "urlfetch_allowed_hosts", "", "If set, urlfetch may only call these hosts (comma separated).")
_f(G, "urlfetch_block_private", True, "Block urlfetch calls to private/internal addresses (SSRF protection).")

G = "Scheduler"
_f(G, "timers_enabled", True, "Run chat timers.")
_f(G, "reminders_enabled", True, "Run reminders.")
_f(G, "scheduler_tick_seconds", 3, "How often timers and reminders are checked.")

G = "Demo"
_f(G, "demo_enabled", True, "Allow demo mode.")
_f(G, "demo_autostart", True, "Start the ambient demo chat when the bot is in demo mode.")
_f(G, "demo_messages_per_minute", 30, "Ambient demo chat speed.")
_f(G, "demo_channel_name", "SavahDemo", "Channel name shown in demo mode.")
_f(G, "demo_chatter_count", 20, "Number of simulated viewers.")
_f(G, "demo_spam_probability", 0.06, "Chance (0-1) that an ambient demo message is spam.")
_f(G, "demo_seed", 0, "Random seed (0 = different every run).")

G = "Redis (optional)"
_f(G, "redis_url", "", "Redis address (redis:// or rediss://). Blank = everything stays in memory. Turns on: moderation memory that survives restarts, shared login lockouts, live events across instances, one leader instance, a short dashboard cache, and restart-proof cooldowns.")
_f(G, "redis_prefix", "savahbot", "Prefix for every key this bot writes, so one Redis can be shared with other apps.")
_f(G, "redis_timeout_seconds", 3, "How long to wait for Redis before carrying on in memory.")
_f(G, "redis_snapshot_seconds", 10, "How often the moderation memory is saved to Redis (0 = never). It is also saved when the bot shuts down.")
_f(G, "redis_leader_ttl_seconds", 30, "If the leader instance disappears, another one takes over after about this many seconds.")
_f(G, "shared_cache_seconds", 15, "With Redis on, how long heavy dashboard queries (such as Insights) are reused. 0 = no caching.")

G = "Reserved (future features, unused today)"
_f(G, "twitch_client_id", "", "Reserved: Twitch application client id.")
_f(G, "twitch_client_secret", "", "Reserved: Twitch application client secret.")
_f(G, "twitch_channel", "", "Reserved: Twitch channel name.")
_f(G, "twitch_bot_token", "", "Reserved: Twitch chat OAuth token.")
_f(G, "kick_client_id", "", "Reserved: Kick application client id.")
_f(G, "kick_client_secret", "", "Reserved: Kick application client secret.")
_f(G, "discord_bot_token", "", "Reserved: Discord bot token.")
_f(G, "discord_webhook_url", "", "Reserved: Discord webhook for alerts.")
_f(G, "sentry_dsn", "", "Reserved: Sentry error reporting DSN.")
_f(G, "smtp_host", "", "Reserved: SMTP host for email alerts.")
_f(G, "smtp_port", 587, "Reserved: SMTP port.")
_f(G, "smtp_user", "", "Reserved: SMTP username.")
_f(G, "smtp_password", "", "Reserved: SMTP password.")
_f(G, "smtp_from", "", "Reserved: sender address for email alerts.")
_f(G, "outbound_webhook_url", "", "Reserved: POST moderation events to this URL.")
_f(G, "outbound_webhook_secret", "", "Reserved: HMAC secret for outbound webhooks.")
_f(G, "ai_enabled", False, "Reserved: AI features (off by design for now).")
_f(G, "ai_provider", "", "Reserved: AI provider name.")
_f(G, "ai_api_key", "", "Reserved: AI provider API key.")
_f(G, "ai_model", "", "Reserved: AI model name.")

# ---------------------------------------------------------------------------------------------
BY_NAME: dict[str, Field] = {f.name: f for f in FIELDS}

# Settings the dashboard / Telegram may change at runtime. Secrets and infrastructure stay env-only.
EDITABLE_PREFIXES = (
    "mod_", "command_", "urlfetch_", "demo_", "yt_", "timers_", "reminders_", "scheduler_",
    "telegram_notify_", "intel_", "youtube_expected", "youtube_detect", "youtube_max", "youtube_message",
    "notify_", "youtube_backfill", "youtube_auto", "youtube_target", "youtube_video", "youtube_moderator", "youtube_permission", "chat_", "sse_", "activity_",
)
EDITABLE_KEYS = {"bot_mode", "telegram_mode", "owner_timezone"}
ENUMS: dict[str, list[str]] = {
    "bot_mode": ["demo", "live"],
    "telegram_mode": ["webhook", "polling"],
    "mod_mode": ["off", "suggest", "auto"],
    "intel_learning_mode": ["off", "suggest", "auto"],
    **{f"intel_{d}_mode": ["off", "shadow", "live"] for d in (
        "scam", "spam", "abuse", "harassment", "typo", "link_risk", "impersonation", "obfuscation", "bot_like", "intent", "known_spam", "raid_wave")},
}


def is_editable(name: str) -> bool:
    return name in BY_NAME and (name in EDITABLE_KEYS or name.startswith(EDITABLE_PREFIXES))


def coerce(default: Any, raw: Any) -> Any:
    """Convert a raw value (string from env, JSON from the API) to the type of `default`."""
    if isinstance(default, bool):
        if isinstance(raw, str):
            return raw.strip().lower() in ("1", "true", "yes", "on")
        return bool(raw)
    if isinstance(default, int):
        return int(float(raw))
    if isinstance(default, float):
        return float(raw)
    return str(raw)


def validate_value(name: str, value: Any) -> Any:
    field = BY_NAME[name]
    coerced = coerce(field.default, value)
    if name in ENUMS and coerced not in ENUMS[name]:
        raise ValueError(f"{name} must be one of {ENUMS[name]}")
    return coerced


def _read_env_file(path: str) -> dict[str, str]:
    out: dict[str, str] = {}
    p = Path(path)
    if not p.is_file():
        return out
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        out[key.strip().lower()] = value
    return out


# Variables that cannot have a useful default: .env.example shows this marker so you can see what still needs your input.
# The backend treats the marker exactly like a blank value, so leaving it in place is harmless.
PLACEHOLDER = "edit-me"

NEEDS_EDIT = frozenset({
    "owner_password", "public_base_url", "frontend_url", "youtube_target_channel_id", "telegram_bot_token", "google_client_id", "google_client_secret", "youtube_api_key",
    "twitch_client_id", "twitch_client_secret", "twitch_channel", "twitch_bot_token", "kick_client_id", "kick_client_secret",
    "discord_bot_token", "discord_webhook_url", "redis_url", "sentry_dsn", "smtp_host", "smtp_user", "smtp_password", "smtp_from",
    "outbound_webhook_url", "outbound_webhook_secret", "ai_api_key",
    "firebase_project_id", "firebase_client_email", "firebase_private_key", "firebase_web_api_key", "firebase_web_app_id", "firebase_messaging_sender_id", "firebase_vapid_key",
})

# Blank on purpose; the reason is printed next to the variable in .env.example.
BLANK_BECAUSE = {
    "railway_public_domain": "Railway sets this itself",
    "cors_origins": "only needed for extra dashboard addresses; FRONTEND_URL is already allowed",
    "jwt_secret": "generated and stored automatically on first start",
    "database_url": "Railway sets this when you add PostgreSQL; blank means a local SQLite file",
    "telegram_webhook_secret": "generated and stored automatically",
    "google_redirect_uri": "built from PUBLIC_BASE_URL automatically",
    "youtube_refresh_token": "filled in when you press Connect on the Setup page",
    "youtube_moderator_account": "optional safety check, not required",
    "youtube_channel_id": "deprecated, use YOUTUBE_TARGET_CHANNEL_ID",
    "youtube_video_id": "blank means find the live stream automatically",
    "urlfetch_allowed_hosts": "blank means any public host is allowed (private networks are always blocked)",
    "ai_provider": "AI is not used in this version",
    "ai_model": "AI is not used in this version",
    "weather_commercial_api_key": "only for a paid Open-Meteo plan; the free service needs no key",
    "firebase_service_account_json": "optional: use it instead of FIREBASE_CLIENT_EMAIL and FIREBASE_PRIVATE_KEY",
    "firebase_auth_domain": "not needed for push notifications",
}


def _is_placeholder(raw: Any) -> bool:
    return str(raw).strip().lower().startswith(PLACEHOLDER)


class Settings:
    """Typed, read-only view of the environment. Access values as attributes: settings.mod_mode."""

    def __init__(self, env: Mapping[str, str] | None = None, env_file: str | None = ".env") -> None:
        source: dict[str, str] = {}
        if env_file:
            source.update(_read_env_file(env_file))
        real = os.environ if env is None else env
        source.update({k.lower(): v for k, v in real.items()})  # real environment wins over .env
        values: dict[str, Any] = {}
        for f in FIELDS:
            raw = source.get(f.name)
            if raw is None or str(raw).strip() == "" or _is_placeholder(raw):
                values[f.name] = f.default
                continue
            try:
                values[f.name] = coerce(f.default, raw)
            except (TypeError, ValueError):
                values[f.name] = f.default
        self._values = values

    def __getattr__(self, name: str) -> Any:
        try:
            return self.__dict__["_values"][name]
        except KeyError:
            raise AttributeError(name) from None

    def get(self, name: str) -> Any:
        return self._values[name]

    @property
    def public_url(self) -> str:
        if self.public_base_url:
            return self.public_base_url.rstrip("/")
        if self.railway_public_domain:
            return "https://" + self.railway_public_domain.strip("/")
        return ""

    @property
    def cors_list(self) -> list[str]:
        origins = split_csv(self.cors_origins)
        if self.frontend_url:
            origins.append(self.frontend_url.rstrip("/"))
        origins += ["http://localhost:5173", "http://127.0.0.1:5173"]
        seen: list[str] = []
        for o in origins:
            if o not in seen:
                seen.append(o)
        return seen


class StaticConfig:
    """Config with the same .get() interface as the runtime config; used by tests and scripts."""

    def __init__(self, overrides: Mapping[str, Any] | None = None) -> None:
        self._d = {f.name: f.default for f in FIELDS}
        self._d.update(overrides or {})

    def get(self, key: str) -> Any:
        return self._d[key]

    def set(self, key: str, value: Any) -> None:
        self._d[key] = value

    @property
    def public_url(self) -> str:
        return str(self._d["public_base_url"]).rstrip("/")


# Variables that must be provided for each integration to work (used by the health checklist).
REQUIREMENTS: dict[str, list[str]] = {
    "dashboard": ["owner_password"],
    "telegram": ["telegram_bot_token", "public_base_url"],
    "youtube": ["google_client_id", "google_client_secret", "public_base_url"],
    "database": ["database_url"],
}


def env_name(name: str) -> str:
    return name.upper()


def render_env_example() -> str:
    lines = [
        "# SavahBot backend environment variables.",
        "# Generated from app/config.py by scripts/gen_env_example.py. Do not edit by hand.",
        "# Copy to .env for local use, or paste into Railway > Variables.",
        "#",
        "# Every line already holds the default, so the file works as it is.",
        f"# Lines that say {PLACEHOLDER} are the ones only you can fill in; the app ignores {PLACEHOLDER}, so leaving it is harmless.",
        "# A few lines are blank on purpose; the comment above each says why.",
        "",
    ]
    group = None
    for f in FIELDS:
        if f.group != group:
            group = f.group
            lines += ["", "# " + "=" * 70, f"# {group}", "# " + "=" * 70]
        default = f.default
        if f.name in NEEDS_EDIT:
            value, note = PLACEHOLDER, "you must edit this" if f.group != "Reserved (future features, unused today)" else "unused today; edit only when that feature ships"
        elif f.name in BLANK_BECAUSE:
            value, note = "", f"blank on purpose: {BLANK_BECAUSE[f.name]}"
        else:
            value = "true" if default is True else "false" if default is False else str(default)
            note = ""
        lines.append(f"# {f.description}")
        if note:
            lines.append(f"# ({note})")
        lines.append(f"{env_name(f.name)}={value}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"
