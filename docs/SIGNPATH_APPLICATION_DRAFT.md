# SignPath Foundation — актуальный проект заявки DeiLaw (НЕ ОТПРАВЛЕНА)

Дата обновления: 18.11.2026. **Не утверждать, что SignPath одобрил проект, выдал сертификат или что подписанный релиз существует.** Это подготовленный текст для официальной заявки после закрытия юридических и технических блокеров.

## Application / project identity

- **Project:** DeiLaw — open-source Windows desktop companion for role-play users of RMRP, independently developed and not affiliated with RMRP.
- **Repository and source:** https://github.com/DeiZiXX/DeiLaw
- **Maintainer:** GitHub account @DeiZiXX (proof of repo control via connected GitHub; 2FA still to be verified by owner).
- **Source license:** GNU GPL version 3 only, SPDX `GPL-3.0-only`, for owned DeiLaw code and eligible media. Source-only publication is authorized by owner via PR №1; verify release tag and final `main` commit before submitting the Foundation application. Third-party libraries retain their own licenses.
- **Current GitHub source application version:** 0.3.1 (`app_version.py`); do not infer which version the owner's installed Windows application is running. Some older docs mention 0.3.5rc builds; align release version and actual source before publication.
- **User-facing functionality:** RMRP statutes search, local notes, role-play calculators, quick overlays, opt-in law synchronisation, optional Cloud AI, user reports/reviews and Discord login.
- **Privacy statement:** https://github.com/DeiZiXX/DeiLaw/blob/main/PRIVACY.md (the GPL candidate contains a newer policy in PR #1; update on main after clearance).
- **Code signing policy:** https://github.com/DeiZiXX/DeiLaw/blob/main/CODE_SIGNING_POLICY.md (candidate policy in PR #1).
- **Proposed signed artifacts:** `DeiLaw.exe` and `DeiLaw_Setup_v<version>.exe`. Do not sign unsigned third-party Qt or Microsoft DLLs as if DeiLaw authored them.
- **Workflow:** `.github/workflows/signpath-release.yml`, GitHub-hosted Windows runner, manually gated, separate signing of application and NSIS setup.
- **Release history:** earlier GitHub release v0.3.0 existed according to repository preparation records; an already released, complete, GPL-licensed version still must be verified.

## Verifiable CI evidence available BEFORE submitting

- [CI run #44158776436](https://github.com/DeiZiXX/DeiLaw/actions/runs/44158776436): 112 automated tests passed; PyInstaller EXE and NSIS setup assembled, unsigned.
- Silent Windows install, reinstall and uninstall smoke passed, preserving user preferences and `data/`.
- 282 build files; 61 upstream Python-wheel license notices verified by SHA-256; 105 native EXE/DLL/PYD files categorized, not fully license-cleared.
- A subsequent CI version includes `DeiLaw_Source_v0.3.1.zip` from exact Git HEAD with `source_provenance.json` binding source and unsigned installer hashes. Verify its run success before citing this as completed.

## Not yet cleared — cannot truthfully mark eligible

- Rights on all original code, 12 media files and contributions by other authors; human owner review form: [OWNER_RIGHTS_REVIEW.md](OWNER_RIGHTS_REVIEW.md).
- Full Qt LGPL/GPL notice and corresponding source/replacement instructions; OpenSSL/CPython and Microsoft CRT/GPL System Libraries treatment; actual bundle audit: [PHASE3_RELEASE_GATE.md](PHASE3_RELEASE_GATE.md).
- SignPath's statement against commercial dual licensing: **PyQt6 is distributed under GPLv3 or a separate commercial license**. Get written confirmation of whether use of its GPLv3 distribution as a dependency meets the Foundation's eligibility rule. Do not assume either acceptance or rejection.
- An official public GPL release from fully matched source, interactive GUI/privacy verification and a GitHub `main` that contains the approved license.
- MFA, protected GitHub branch/rulesets, actual reviewers and release approver, trusted-build project/app, policy/configuration and SignPath token; these require account-owner and SignPath permissions.

## Suggested concise eligibility question to SignPath

> We maintain DeiLaw, an open-source GPL-3.0-only Windows desktop utility distributed from our public GitHub repository. Our Python application uses the **GPLv3 edition** of PyQt6, while upstream PyQt6 offers a separate commercial license. The installer is NSIS/zlib; Qt DLLs are dynamically linked and supplied as upstream OSS binaries. Some Python/Windows redistributable runtime DLLs may qualify as GPLv3 System Libraries. Does this dependency model meet the Foundation's requirement for OSI-approved licensing without commercial dual-licensing? Which notices, corresponding sources and System Libraries evidence should be supplied for acceptance?

## Submission and post-approval controls

1. Complete rights/license and GUI/privacy review; publicize the GPL release with exact matching source and notice texts.
2. Enable MFA and branch protection/rulesets, document reviewers and approvers in [CODE_SIGNING_POLICY.md](../CODE_SIGNING_POLICY.md).
3. Owner submits [official application](https://signpath.org/apply). **Submission has not taken place in this preparation**; response and reputation check belong to SignPath Foundation.
4. Once approved, create the Foundation organization/project, trusted build system GitHub.com, authorize SignPath GitHub App, create signing policy and two artifact configurations with metadata checks.
5. Store token only in GitHub secret and IDs as repository/environment variables, require protected environment reviewer, perform verified-origin sign and manually approve **every** request.
6. Verify both Authenticode signatures, bind signed installer to source provenance, issue a release with matching source and licenses. Prepare offline Ed25519 key on owner's Windows PC, never in CI or a chat.

Official terms: https://signpath.org/terms
GitHub integration: https://docs.signpath.io/trusted-build-systems/github

**Status: candidate only. Application not submitted; official approval, certificate and code signing not obtained.**
