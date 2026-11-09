# Backup & recovery guide

**Manage > Backup.** Move everything to a new deployment, or keep a safe copy.

## Make a backup
1. Tick what to include. Defaults: settings, commands/timers/auto replies, community lists, Knowledge and lessons, moderation history and ban ledger, long-term chart history. Off by default: raw chat messages (large) and **credentials** (sign-in methods, Google and Telegram links).
2. Optionally add a passphrase. Then the file needs **both** the key and the passphrase.
3. Confirm your password (step-up). The file downloads, and a sheet shows the **key** (`SVK1-XXXX-...`). It is shown **once**. SavahBot stores only a short fingerprint. Save the key apart from the file.

### What is never included
Signed-in sessions and sign-in tickets, sign-in activity logs, push-notification device tokens, the server's signing secret, and every environment variable (database URL, API keys...). After restoring on a new server you re-enter those in your host's variables.

## The file
`.svbak` = a zip (manifest + one JSON per part, each with a SHA-256) wrapped in AES-256-GCM, in 1 MiB chunks, each with its own random nonce. Every chunk is bound to the header, its position and whether it is the last, so editing, reordering, dropping or cutting the file makes opening it fail. The key is 256 random bits; a passphrase is mixed in with scrypt + HKDF. `cryptography` must be installed (it is in `requirements.txt`).

## Restore
1. Choose the file, paste the key (and passphrase). **Open and check** shows what is inside and its fingerprint. Nothing changes yet.
2. Pick the parts and the mode: **Merge** adds what is missing and keeps what is here; **Replace** makes the chosen parts match the backup exactly.
3. Restore. First a safety copy of the affected data is kept, the backup is applied, the result is checked, and on any failure everything is put back automatically. Afterwards **Undo the last restore** returns to the safety copy.
Opening is protected against hostile zips: only expected file names, size and compression-ratio limits, per-file checksums.

## Fresh deployment, before you can sign in
On a brand-new server the log prints a **one-time restore token** once. The sign-in screen then shows **Restore from a backup**: choose the file, key and token. Signing in normally (or restoring) ends the token's life. Include *credentials* in the backup if you want your password, passkeys and authenticator to come with you. Passkeys only work if the new dashboard has the same host name.

## Notes
- Restoring is recorded in the security audit log and sent to you on Telegram. Exporting needs step-up confirmation.
- API: `GET /api/backup/info`, `POST /api/backup/export|verify|import|undo`, `GET|POST /api/backup/first-run`.
- Lost the key? The backup cannot be opened. There is no back door by design.
- Tested: format, tampering, zip protections, export/wipe/restore/merge/dry-run/undo, forced-failure rollback, token flow. Not tested: PostgreSQL restore against a real server (the code handles sequences, but only SQLite was run here).
