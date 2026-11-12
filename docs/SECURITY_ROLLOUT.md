# Security rollout — DeiLaw (updated 2026-11-12)

## Current status

This repository contains a **source-level preview**, not a completed production
security release. On November 11, 2026, the **Cloud AI v2 quota** and **JWT Edge
Function v8** were deployed to production. An interim RLS migration also
removed the unsafe NULL-secret bypass. On November 12 the **non-breaking
interim review moderation patch** was deployed to production and verified:
`approved` now defaults to false, its guard trigger is active, and all three
previously approved reviews remain approved. The full auth.uid() RLS migration, public invoker view, and restricted
base-table column privileges have now been **applied** to production. The internal trigger
helpers were hardened. The Security Advisor no longer reports the
SECURITY DEFINER view error; a warning remains for the temporary privileged
legacy ownership-claim RPC (restricted to authenticated callers).
No Windows installer
has been built or Authenticode-signed. Do not issue a security
clearance before the rollout and independent verification below.

On November 12, the owner approved a coordinated production JWT cutover even
though older desktop clients will lose Community write access. A private
**in-database rollback snapshot** was created in schema
`deilaw_rollback_20261112`: 3 reviews, 4 bug reports, 12 messages, 0
suggestions, 3318 law articles, 0 attachment metadata rows, and 17 current
RLS policies. All counts matched live tables at snapshot time. Both `anon`
and `authenticated` were verified to have no schema/table access. This is
**not an offsite disaster recovery backup** and does not copy OAuth/Auth
configuration. The breaking RLS migration was applied on November 12, 2026 after the
internal snapshot, and the attachments Edge Function was upgraded to v2
with verify_jwt=true. The existing DeiLaw 0.3.5rc6 source/client already
uses these contracts. An external backup and full Windows integration
verification are still outstanding.

## Critical coordination: deploy in order

1. Back up Supabase project, including reviews, bug_reports,
   bug_report_messages, suggestions, deilaw_law_articles and Auth settings. Restrict
   publish access to the repository and enable MFA on GitHub.
2. **Anonymous Sign-ins were enabled in production on November 11, 2026.**
   Supabase enforces a 30/hour/IP anonymous signup limit. CAPTCHA remains
   **disabled** and needs configuration to deter fake accounts.
   Discord OAuth is now enabled in production; the owner reported a successful
   Windows Discord sign-in. Guest login remains optional. See
   docs/DISCORD_AUTH_SETUP.md. CAPTCHA is still not configured.
3. Applied the reviewed ownership migration to production after snapshot.
   For new installations, review SUPABASE_SECURITY_HARDENING.sql after legacy setup.
   The migration protects private table columns, transfers legacy data ownership
   through secret proof, and preserves the three previously published reviews. **Old desktop clients
   will stop writing community data.** Never run SUPABASE_SETUP.sql again
   after this migration.
   **Attachment cutover has been deployed:** `deilaw-report-attachments`
   Edge Function v2 with `verify_jwt=true` after `owner_uid` was added. The new function verifies the user's JWT and
   matches `bug_reports.owner_uid`; it no longer accepts a device-supplied
   installation secret or NULL-hash rows. Deploy the matching desktop update
   (including bearer tokens in attachment requests) with the migration.
4. The revised SUPABASE_CLOUD_AI_SETUP.sql and deilaw-ai with verify_jwt=true
   are deployed. The global AI
   cap default is **250** requests/day, per user **12** requests/day. Set
   conservative OpenAI *project-level* budget alerts and expenditure limits
   manually in its dashboard. Those are not created by this repo.
5. Verify the Edge Function's retrieval against actual populated
   deilaw_law_articles rows and Auth tokens. Test no JWT, malformed JWT,
   forged device header, public reviews, own/other report, old-owner claim,
   attempted changes to approved/helpful_count, and exhausted quotas.
6. Deploy the reviewed desktop build to users alongside the SQL migration.
   Existing devices migrate community_identity.json to Windows DPAPI and
   new cloud sessions to cloud_auth.bin. Backups no longer include identity;
   **old user backups may still contain plaintext secrets**. Preserve both
   guest and Discord sessions when switching login modes; transferring data
   between their user IDs needs a separately audited owner-authorized flow.
7. Produce a release **only** after adding a pinned Ed25519 release public
   key to update_trust.py. Generate/store the private key offline; sign
   update_manifest.json with scripts/sign_update_manifest.py and verify
   exact installer SHA-256. Sign the actual installer with Authenticode and
   verify that signature in an installer-execution design. Until then,
   automatic installation and PowerShell helper execution are disabled.
   Windows build helpers (build_app_only.ps1, build_release.ps1) are included.
   build_release.ps1 refuses to finish without Authenticode and offline
   Ed25519 signatures. Provide an actual Windows signing certificate and
   generate the Ed25519 key offline.
8. Obtain independent retest and rerun Supabase security/performance advisers.

## Findings addressed in source

- Cloud AI now sends a user Bearer JWT; Edge authenticates via Supabase Auth.
- Per-user plus global quota is enforced atomically by server-only RPC v2.
- Server retrieves law text instead of accepting client-submitted sources.
- RP law content is explicitly untrusted; source instructions are ignored.
- RLS migration uses auth.uid() ownership; NULL-hash ownership bypass and
  header-derived ownership are absent in the new policies. Legacy owner claim
  proves knowledge of the old random secret once.
- Public review view exposes only display columns; new reviews need moderation;
  owner cannot modify moderation or developer fields.
- Suggestions replace their legacy header-based policies with JWT-based ones; users cannot alter
  statuses, developer replies or other users' suggestions.
- Source code of law-sync and report-attachments Edge Functions is included.
- Revised attachment function validates user JWT and report owner_uid, limits
  request-body streaming to 10 MiB, and removes the NULL-secret bypass. This
  source variant is prepared; the function is deployed as v2 with the same JWT ownership contract.
- Runtime and secrets are excluded from Git via .gitignore.
- Windows user tokens and installation secrets are protected via DPAPI,
  and backups no longer contain identity credentials.
- DOCX size/decompression/XML checks, relative working-directory protection,
  escaped SQLite LIKE wildcard searches, opt-in diagnostic logs.
- Manifest Ed25519 signature support; no unauthenticated automatic installer
  execution.

## Outstanding / needs verification

- **JWT ownership rules are deployed**. Direct raw review secret columns are
  withheld, approved public reviews are available through a security-invoker view,
  and the existing reviews remain published. End-to-end client verification
  and an offsite backup are still outstanding.
- Production `deilaw-report-attachments` is now v2 with `verify_jwt=true`
  and per-report owner checks. Confirm request/response behavior on Windows.
- The interim review moderation patch was applied on November 12 via a named
  Supabase migration. Its enabled trigger, false default and the preservation
  of all three approved reviews were verified with read-only SQL.
- Windows RP binder and GUI must be retested on a real Windows machine.
- Anonymous Auth is enabled and IP rate-limited, but CAPTCHA and
  automated abuse alerts still need configuration at Supabase/edge/CDN level.
- Discord provider is enabled and a user sign-in succeeded on Windows; a full
  reinstall, logout, guest switch and permission-negative test remain necessary.
- Real Authenticode signing certificate, offline Ed25519 release key, safe
  signed installer launch workflow, dependency lock for Windows build, and
  release account MFA must be provisioned by the release owner.
- Independently test suggestions RLS and all admin RPCs/triggers in
  staging, and run negative tests on every entry point.
- Server law retrieval ranking should be checked against varied RP examples;
  it is not a guarantee of correct legal analysis.
- Only reviews go to moderation by default; further Community anti-spam
  controls may be needed.

## Local validation

Commands: python scripts/verify_source.py
and python -m unittest discover -s tests -v

For a free, isolated two-user Supabase JWT/RLS integration exercise, see
`docs/LOCAL_SECURITY_TEST.md`. The test fixture is synthetic and does not
copy users, reviews, reports, or secrets from production. Docker/Supabase CLI
must be available on the test machine; the source-only environment cannot
execute these integration tests without the local Supabase stack.

Production approval requires tests on staging against Supabase and a
Windows release build, not just the Python checks above.

## Production rollout checks (2026-11-12)

- `owner_uid` installed on reviews, bug_reports, bug_report_messages and suggestions.
- 0 remaining request-header-based policies for those four community tables.
- 3/3 previous reviews remain visible; 4 reports and 12 chat messages preserved.
- Public reviews use `security_invoker=true` and a limited column grant.
- The Supabase Security Advisor's `security_definer_view` ERROR was cleared.
- `deilaw-report-attachments` v2 has `verify_jwt=true` and checks report ownership.
- Internal snapshot in `deilaw_rollback_20261112` exists; it is not external backup.
- A temporary legacy ownership RPC remains intentionally SECURITY DEFINER,
  narrowly limited to JWT callers with the original long random install secret.
  Revoke it after legacy migration is no longer required.
- Remaining advisor warnings include anonymous sign-in visibility and
  leaked-password protection; CAPTCHA and signed installer are not yet done.
- This archive is source-only. No complete Windows E2E / independent audit yet.

## Discord-bound reviews and reports (12 November 2026)

New reviews and bug reports require a verified Discord identity in `auth.identities`. The DB assigns the account UID, Discord display name and provider ID; client-submitted nicknames and device identifiers cannot impersonate authors. One review per Discord provider ID; edited content returns to moderation. Historical rows are preserved. Production migration applied, review/admin tests completed in rolled-back transactions. See `docs/DISCORD_FEEDBACK_20261112.md`.
