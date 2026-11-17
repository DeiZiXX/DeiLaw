"""Fail-closed audit of tracked DeiLaw files intended for a public source release.

Never print an actual credential value. Public backend sources and publishable
Supabase keys are intentionally permitted: server RLS/auth must protect data.
This is a high-confidence accidental-secret screen, not a penetration test.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Maintainer-only operational reports, live-deployment notes, and administrative
# cloud-sync client are NOT part of the end-user source distribution.
NONPUBLIC_PATHS = frozenset({
    "SECURITY_DEPLOYMENT_RC12_RU.md",
    "SECURITY_STATUS_20261112.md",
    "SECURITY_STATUS_RC11_RU.md",
    "RELEASE_SECURITY_RC11.txt",
    "RELEASE_SECURITY_RC9.txt",
    "RELEASE_NOTES_RC12.txt",
    "RELEASE_DISCORD_FEEDBACK_0.3.5rc7.txt",
    "RELEASE_LEGACY_DISCORD_CLAIM_0.3.5rc8.txt",
    "docs/SECURITY_ROLLOUT.md",
    "docs/VERIFY_PRODUCTION_CUTOVER.md",
    "docs/DISCORD_FEEDBACK_20261112.md",
    "security/EXTERNAL_SECURITY_AUDIT_SCOPE_RU.md",
    "security/SECURITY_RELEASE_GATE_RU.md",
    "security/av_gateway/README_RU.md",
    "sync_laws_to_cloud.py",
})
PRIVATE_SUFFIXES = (
    ".pem", ".pfx", ".p12", ".key", ".sqlite", ".sqlite3", ".db",
    ".db-wal", ".db-shm", ".dump", ".dump.gpg", ".bak",
)
TEXT_SUFFIXES = frozenset({
    ".py", ".ts", ".sql", ".json", ".jsonl", ".md", ".txt", ".toml",
    ".yml", ".yaml", ".ps1", ".bat", ".nsi", ".iss", ".ini", ".sh",
})
# Deliberately high-confidence only. Avoid falsely flagging literal regex
# examples or publishable client-side API configuration.
SECRET_PATTERNS = {
    "OpenAI credential": re.compile(rb"sk-(?:proj-)?[A-Za-z0-9_-]{24,}"),
    "GitHub credential": re.compile(rb"gh(?:p|o|u|s|r)_[A-Za-z0-9_]{25,}"),
    "GitLab credential": re.compile(rb"glpat-[A-Za-z0-9_-]{24,}"),
    "Supabase secret": re.compile(rb"sb_secret_[A-Za-z0-9_-]{20,}"),
    "AWS access key": re.compile(rb"\bAKIA[A-Z0-9]{16}\b"),
    "Private key block": re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH |ENCRYPTED )?PRIVATE KEY-----"),
    "JWT bearer token": re.compile(rb"\beyJ[A-Za-z0-9_-]{20,}\.eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{16,}"),
    "Database password in URL": re.compile(rb"postgres(?:ql)?://[^:\s/]+:[^@\s/'\"]{8,}@", re.I),
}

def tracked_files(root: Path = ROOT) -> list[str]:
    proc = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-z"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
    )
    if proc.returncode:
        raise RuntimeError("Git tracked file inventory unavailable: cannot approve public release")
    return sorted(n.decode("utf-8", "surrogateescape") for n in proc.stdout.split(b"\0") if n)

def violations(root: Path, names: list[str]) -> list[str]:
    problems: list[str] = []
    for name in names:
        path = Path(name)
        if (path.is_absolute() or ".." in path.parts or "\\" in name):
            problems.append(f"{name}: unsafe tracked path")
            continue
        low = name.lower()
        if name in NONPUBLIC_PATHS:
            problems.append(f"{name}: internal operations file in public release")
        if (path.name.startswith(".env") and path.name != ".env.example") or low.endswith(PRIVATE_SUFFIXES) or low.startswith("data/") and name != "data/README.md":
            problems.append(f"{name}: private data / credential filename")
        file = root / path
        if not file.is_file():
            problems.append(f"{name}: tracked file missing")
            continue
        if file.suffix.lower() not in TEXT_SUFFIXES and file.name != ".env.example":
            continue
        if file.stat().st_size > 5 * 1024 * 1024:
            problems.append(f"{name}: oversized source text requires human review")
            continue
        content = file.read_bytes()
        for label, regex in SECRET_PATTERNS.items():
            if regex.search(content):
                # Never disclose the match itself: this line goes to public CI logs.
                problems.append(f"{name}: possible {label}")
    return problems

def main() -> int:
    try:
        names = tracked_files()
        problems = violations(ROOT, names)
    except (OSError, RuntimeError) as exc:
        print(f"Public source audit failed to run: {exc}", file=sys.stderr)
        return 1
    if problems:
        print("PUBLIC SOURCE RELEASE BLOCKED", file=sys.stderr)
        for problem in problems:
            print(f"[REDACTED] {problem}", file=sys.stderr)
        return 1
    print(f"Public source audit passed: {len(names)} tracked files; no forbidden operational files or high-confidence secrets.")
    print("Note: public Supabase URL and publishable key are not secrets. Verify RLS and permissions independently.")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
