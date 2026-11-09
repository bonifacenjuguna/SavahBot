# Security & Access guide

Open **Manage > Security** (shortcut `y`). SavahBot has exactly one user: you.

## The rule: any two of three
You can prove who you are four ways: **password**, **passkey**, **authenticator code**, **recovery code**. Once you have set up at least **two** sign-in methods (your password always counts as one), every sign-in must prove **any two different ones**. The server decides this on every sign-in. The dashboard cannot skip it.

Until you add a second method, password-only sign-in keeps working, because otherwise you could never set one up. The Security page shows this clearly and scores you down for it. Add a passkey or an authenticator app first thing.

| Lost... | Sign in with |
|---|---|
| Phone (authenticator) | password + passkey, or password + recovery code |
| Passkey device | password + authenticator code |
| Password | passkey + authenticator code |

You cannot remove a method if that would leave you with fewer than two.

## What is stored, and how
- **Password:** salted scrypt hash (argon2id automatically if `argon2-cffi` is installed). Plaintext is never stored. On first start on 1.2.0 the old plaintext copy is hashed and wiped. `OWNER_PASSWORD` stays a bootstrap: change it in your host's variables and it takes effect, until you change the password on the Security page (after that the variable is ignored).
- **Authenticator app:** the secret is encrypted at rest and never returned by the API after setup. A code cannot be used twice.
- **Recovery codes:** 10 single-use codes, stored only as keyed hashes. Shown once.
- **Passkeys:** only the public key is stored. Supported key types: ES256, RS256, EdDSA. The signature counter is checked, so a cloned key is refused.
- **Sessions:** opaque random tokens, stored only as a hash. You can see and sign out every device, and signing out really ends the session on the server. Sessions end after `JWT_EXPIRE_HOURS` (72) and after `SESSION_IDLE_MINUTES` (1440) of no use.
- **Step-up:** changing sign-in methods, removing passkeys, making recovery codes or lifting lockdown asks for your password again (valid `SECURITY_STEP_UP_MINUTES`, 5).
- **Activity and audit log:** sign-ins, failures and every security change, kept `SECURITY_LOG_RETENTION_DAYS` (365). A new device signing in also sends you a Telegram message.

## Passkeys on a Vercel + Railway setup
Passkeys belong to the **dashboard's** host, not the API's. Set `FRONTEND_URL=https://your-dashboard.example` (HTTPS). The passkey site then defaults to that host. Override with `WEBAUTHN_RP_ID` and `WEBAUTHN_ORIGINS` only if you serve the dashboard on several addresses. A passkey made for one site id never works on another.

## Lockdown
**Turn on** from the Security page or by sending `/lockdown` to the bot. All other sessions end at once. New sign-ins during lockdown only reach the Security page. **Lift** it there; that needs your password again.

## API (all under `/api`)
Public: `POST /auth/login`, `/auth/factor`, `/auth/passkey/options`, `/auth/passkey/verify`. Signed in: `POST /auth/logout`, `GET /security/overview|sessions|activity`, `POST /security/step-up|password|totp/begin|totp/confirm|passkeys/options|passkeys/register|recovery|lockdown|sessions/revoke-others`, `DELETE /security/totp|passkeys/{id}|sessions/{ref}`. Sensitive routes answer `403` with `"code": "step_up_required"` until you confirm.

## Settings
`SESSION_IDLE_MINUTES`, `SECURITY_STEP_UP_MINUTES`, `SECURITY_MAX_SESSIONS`, `SECURITY_LOG_RETENTION_DAYS`, `WEBAUTHN_RP_ID`, `WEBAUTHN_ORIGINS`, `WEBAUTHN_REQUIRE_UV`.

## What was and was not tested
Tested with automated tests: hashing, TOTP against the RFC 6238 vectors, recovery codes, the passkey verifier against a simulated authenticator (all three key types and every wrong-input case), the QR encoder (decoded with OpenCV), and the full HTTP sign-in, step-up, session and lockdown flows. **Not** tested: a real phone or security key and real browsers. Try a passkey on your own devices after deploying.

## Troubleshooting
- *Passkey says "different site":* `FRONTEND_URL` or `WEBAUTHN_RP_ID` does not match the address in your browser bar.
- *Authenticator codes rejected:* your phone's clock is off; turn on automatic time.
- *Locked out:* sign in with password + a recovery code. If you lost everything, set a new `OWNER_PASSWORD` and clear the access tables (see docs/TROUBLESHOOTING.md once written).
