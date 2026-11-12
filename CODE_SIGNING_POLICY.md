# Code signing policy — PREPARATION DRAFT

Project: DeiLaw, https://github.com/DeiZiXX/DeiLaw

**Current status:** SignPath Foundation has NOT approved or signed DeiLaw. No current artifact should be advertised as SignPath-signed. This policy is a proposal pending rights and compliance review.

## Intended provider acknowledgement (only after formal approval)

"Free code signing provided by SignPath.io, certificate by SignPath Foundation"

The certificate would identify SignPath Foundation as publisher, not the developer's personal name.

## Team and roles (not yet verified)

- Candidate source maintainer: repository owner `@DeiZiXX` — verify control and MFA.
- Reviewers: to be designated; outside contributions require documented review.
- Release approver(s): to be designated; **every release requires manual signing approval**.
- Everyone with relevant repository or signing access must use MFA.

## Intended technical process

1. Confirm that all shipped components are eligible under OSI-approved licensing; see [licensing audit](docs/LICENSING_AUDIT_0.3.1.md).
2. Protect the main/release branches and require checks and review; prohibit force pushes into release refs.
3. Build exclusively from a trusted GitHub Actions Windows workflow, using pinned dependencies, controlled scripts and reproducible provenance. No manual upload of arbitrary unsigned EXE for signing.
4. After SignPath acceptance, configure the organization's trusted GitHub build system, origin verification, signing policy, artifact configuration, CI token stored only as a GitHub Actions secret, and mandatory release approval.
5. Sign both `DeiLaw.exe` and `DeiLaw_Setup_v0.3.1.exe` only if the approved artifact configuration permits both. Verify Authenticode and release matching source code/SBOM/license notices.
6. Keep **separate Ed25519 manifest trust** for the auto-updater. It is not replaced by Authenticode.
7. If any key, release or CI provenance is compromised, stop publishing and coordinate response/revocation with the provider.

The existing `build_release.ps1` expects a developer-owned Windows certificate. It is **not** a working SignPath integration today.

## User privacy and network access

[DeiLaw privacy policy](PRIVACY.md). Client features can contact Supabase, Discord, GitHub, external RMRP legislation sources and, through Supabase, OpenAI. Before signing, check installer-time disclosure and genuine ability to disable network transfers not specifically requested by the user, as SignPath Foundation requires. Existing installer behavior is **not yet certified**.

## References

- https://signpath.org/terms
- https://signpath.org/apply
- https://docs.signpath.io/projects
- https://github.com/SignPath/github-action-submit-signing-request
