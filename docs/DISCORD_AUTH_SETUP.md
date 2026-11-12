# DeiLaw — Discord + guest sign-in setup (Windows, preview)

The client offers **two explicit choices** on first launch or when changing accounts:

- **Discord** — a permanent Supabase account using Discord OAuth with PKCE.
- **Guest** — a separate, stable anonymous Supabase account stored on this PC.

Both modes use an actual Supabase user JWT for Cloud AI and Community APIs.
They share neither their refresh token nor user ID. Switching modes **does not
automatically transfer** reports or reviews between users; never move data
based only on a Discord nickname. Supabase RLS must check `auth.uid()`.

## Required: enable Discord in the project's Supabase Auth

1. Sign in to https://discord.com/developers/applications as the project owner.
   Create a **New Application**, e.g. `DeiLaw`.
2. Under **OAuth2 → Redirects**, add exactly:
   `https://ntizjwncrbokebjsfwgu.supabase.co/auth/v1/callback`
   and save. This is **Discord → Supabase**, not the desktop callback.
3. Copy the Discord application's **Client ID** and **Client Secret** into
   Supabase Dashboard → DeiLaw → Authentication → Sign In / Providers →
   **Discord**. Turn it on and save. Never put the Client Secret into this
   repository, the desktop `.exe`, logs, screenshots, or chat messages.
4. Supabase Dashboard → Authentication → URL Configuration → Redirect URLs:
   add exactly `http://127.0.0.1:45831/deilaw-auth`.
   This is **Supabase → local Windows program** after OAuth. Avoid a broad
   wildcard in production.
5. Keep Anonymous Sign-ins enabled for Guest mode. Configure an appropriate
   CAPTCHA/abuse-prevention strategy and budget limits before wide release.

## On the user's PC

1. Start DeiLaw. The auth window appears on the **first launch** or if a saved
   session can no longer be restored.
2. Click **Войти через Discord**. The system browser opens Supabase/Discord.
   After approval, Supabase redirects to the local receiver on
   `127.0.0.1:45831`. The code is exchanged for a session using PKCE.
3. Or click **Продолжить как гость** to create/reuse a guest JWT.
4. On later launches, DeiLaw automatically restores the last selected Discord
   or guest session and refreshes expired access tokens. It does not open a
   browser or ask for a mode while the session can be restored.
5. The compact account status in the sidebar is a button. When signed into
   Discord, it offers **Сменить аккаунт Discord** (launch fresh Discord OAuth
   immediately) and **Выйти из аккаунта** (revoke the active session and show
   the guest/Discord choice). Account transitions always exit fully, regardless
   of the regular window-close/minimize-to-tray setting.
6. In **Гостевой режим**, the account button offers only **Войти через
   Discord**. This opens Discord OAuth without destroying the saved guest
   identity. If switching is cancelled, the previous session is still available
   on the next launch. Tokens remain encrypted with Windows DPAPI and should
   not be copied between PCs.

## Security and launch limitations

- The listener only binds the Windows loopback interface; the OAuth client
  secret stays in Supabase. The one-time auth code is never logged.
- Port `45831` must be free. Close a second DeiLaw instance if it is busy.
- The desktop login requires an internet connection. Offline access to the
  main window after login is not yet supported.
- The production RLS migration and legacy ownership claim are **still
  pending**. Old clients will not be able to write Community data after that
  migration, so stage both changes together.
- Discord sign-in from this source is **not live-tested** until the provider
  credentials and redirect allowlist have been configured. The Linux agent
  environment cannot validate the PyQt6 Windows dialog and installer.
- Account linking (guest → Discord) is not yet implemented. Data already
  claimed by a guest Supabase UUID cannot be reassigned automatically;
  transfer requires a narrowly scoped, audited, user-consented server flow.

## Verification checklist

- [ ] Supabase `/auth/v1/settings` reports `external.discord=true`.
- [ ] Discord login opens browser, returns to loopback, stores a Discord JWT.
- [ ] Guest login creates/reuses a different, anonymous UUID.
- [ ] Restart preserves each mode's own credentials and refreshes tokens.
- [ ] Reopening DeiLaw with a valid session skips the account picker.
- [ ] Guest account button shows only **Войти через Discord** and preserves
      guest data if OAuth is cancelled.
- [ ] Discord account button offers both direct **Сменить аккаунт Discord**
      and **Выйти из аккаунта**.
- [ ] Switching bypasses the cached Discord JWT and opens fresh browser OAuth.
- [ ] Logging out returns to the guest/Discord choice without a tray prompt,
      even when normal window closing is set to minimize.
- [ ] An OAuth failure or denied permission does not overwrite guest session.
- [ ] Server rejects expired/forged JWT; RLS blocks other users' reports.
- [ ] CAPTCHA, AI quota, rate limits, and budgets have been reviewed.
- [ ] Repeat the whole flow on a real signed Windows build.
