# DeiLaw 0.3.5rc9 — security hardening status (12 November 2026)

This is **NOT a security-certified release**. It contains source code for a Windows build and documents verified mitigations and outstanding tasks. Do not distribute the development executable as a trusted signed release.

## Changes verified in this revision

- Client requests for arbitrary charter URLs now require public DNS hostnames, HTTPS and checked redirects. Downloads are streamed and capped at 8 MiB. DNS validation is defense-in-depth; DNS rebinding/proxies still require assessment on the actual Windows network.
- DOCX parsing rejects oversized archives, excessive file counts, unsafe paths, large XML and suspicious compression ratios. No claim of protection from every malicious document is made.
- Signed installer metadata has extra checks for name/path, expected length (max 300 MiB), SHA-256, and GitHub release origin before saving a downloaded installer. Automatic execution remains deliberately **disabled** until release-signing certificates/keys are provisioned.
- Client attachment selection no longer offers ZIP, and matches Supabase attachment function v3. Existing attachments are not deleted. The server rejects new ZIP uploads and validates PNG/JPEG/WEBP file signatures. TXT/LOG are checked for binary NUL bytes. Antivirus scanning still needs a dedicated pipeline.
- Cloud AI function v9 removes full upstream error/response bodies from logs and limits the upstream request duration; user JWT and daily limits remain.
- Server-side per-user Community quotas: 10 reports, 100 user chat messages, and 10 suggestions per 24 hours. Quotas were tested on the production database using rolled-back transactions. Captcha and multi-account defenses still need configuration.
- Admin Support Center 0.2.4 source redacts bearer tokens and refresh-token/password-like values from exception tracebacks as well as normal log markers.

## Previous mitigations retained

- Community ownership policies use `auth.uid()` and verified Discord identity; client installation headers are no longer used to authorize private records.
- Attachments function requires JWT and report ownership; public reviews use restricted columns and invoker-security view.
- Legacy reviews/reports can be claimed only with prior installation secret and valid Discord identity.
- New/edited reviews are automatically filtered and suspicious entries stay unpublished; admin override remains.
- Tokens saved using Windows DPAPI; client has no OpenAI server secret.
- Cloud AI retrieves laws server-side and enforces atomic quotas for user/global daily use.

## Remaining blocking items for external certification

1. **Authenticode certificate and offline Ed25519 signing key**: the owner must create and safeguard real signing credentials; sign and verify Windows installer and a complete release manifest on a separate Windows machine. Automatic installation is not enabled. Test file substitution and time-of-check/time-of-use negative scenarios.
2. **Independent offsite backup** of database, Auth and Storage assets plus proven restoration procedure. Existing rollback snapshots are inside the same Supabase database only.
3. **CAPTCHA**, identity-abuse monitoring and per-IP abuse controls in Supabase Auth or at an appropriate reverse proxy/CDN. Per-user quotas alone are not enough against fresh anonymous accounts.
4. **Leaked-password protection and MFA** for admin/GitHub release owners must be configured in providers; the Supabase advisor currently flags disabled leaked-password protection.
5. **Independent penetration test**, GitHub/release workflow and dependency/supply-chain audit, real Windows 10/11 E2E testing of DeiLaw + Support Center, and a staging environment with two-user auth/RLS integration tests. PyQt6/Windows-native behavior was not runnable in the source container.
6. **Remaining private helper warning**: Supabase reports SECURITY DEFINER `deilaw_claim_legacy_ownership` is authenticated-callable. Its purpose is secret-proven legacy migration, but should be independently audited and disabled after the recovery window.
7. **Unscanned allowed attachments**: approved image/text files are filtered by type but not antivirus scanned. ZIP uploads were disabled pending safe archive inspection. Repeated concurrent uploads require a transaction-safe per-report limit and storage-quota verification.
8. **Full static/dynamic analysis** of every app component and dependencies, not just current tests. No technical team can guarantee zero unknown vulnerabilities.

## Verification

`python scripts/verify_source.py`

`python -m unittest discover -s tests -q`

Build on Windows using `build_app_only.bat`. The resulting EXE is an UNSIGNED DEVELOPMENT build. Do not bypass Windows execution policies or run update helpers downloaded from arbitrary sites.

**Production Supabase changed**: Edge `deilaw-ai` v9; `deilaw-report-attachments` v3; Community feedback quota triggers. These have not been verified by end-to-end Windows integration tests.
