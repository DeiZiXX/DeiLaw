"""Archive the exact Git commit used for an unsigned DeiLaw Windows candidate.

The snapshot contains tracked project sources, NOT vendored Qt or other
third-party corresponding sources. It is evidence, not a GPL-compliance ruling.
"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
import zipfile
from pathlib import Path


def run_git(root: Path, *args: str) -> str:
    return subprocess.check_output(
        ["git", "-C", str(root), *args],
        text=True, encoding="utf-8",
    ).strip()


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for part in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(part)
    return h.hexdigest()


def create_source_snapshot(root: Path, outdir: Path, version: str, unsigned_installer: Path | None = None) -> dict:
    root = root.resolve()
    outdir = outdir.resolve()
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", version):
        raise ValueError("Version must be a stable numeric version")
    if Path(run_git(root, "rev-parse", "--show-toplevel")).resolve() != root:
        raise ValueError("Expected exact repository root for source snapshot")
    head = run_git(root, "rev-parse", "HEAD")
    if not re.fullmatch(r"[a-f0-9]{40}", head):
        raise ValueError("Git did not return a commit SHA")
    # Do not accidentally publish locally edited tracked files as the sources
    # of an already committed binary build.
    dirty = run_git(root, "status", "--porcelain", "--untracked-files=no")
    if dirty:
        raise ValueError("Tracked files changed: cannot archive as a verified HEAD snapshot")

    outdir.mkdir(parents=True, exist_ok=True)
    source_zip = outdir / f"DeiLaw_Source_v{version}.zip"
    subprocess.run(
        ["git", "-C", str(root), "archive", "--format=zip", f"--output={source_zip}", head],
        check=True,
    )
    with zipfile.ZipFile(source_zip) as source:
        names = source.namelist()
        required = {"LICENSE", "app_version.py", "main.py", "requirements.txt", ".github/workflows/windows-build.yml"}
        if not required.issubset(set(names)):
            raise ValueError("Required source files are absent from the archive")
        source_version = source.read("app_version.py").decode("utf-8")
        if not re.search(r'APP_VERSION\s*=\s*["\']' + re.escape(version) + r'["\']', source_version):
            raise ValueError("Release version is inconsistent with source archive")
        if source.testzip() is not None:
            raise ValueError("Source archive is corrupt")

    evidence = {
        "schema": "deilaw-source-snapshot-v1",
        "source_commit": head,
        "version": version,
        "source_archive": source_zip.name,
        "source_archive_sha256": sha256(source_zip),
        "tracked_source_files": len(names),
        "scope": "TRACKED_DEILAW_PROJECT_SOURCES_ONLY",
        "third_party_corresponding_source_not_included": True,
        "not_legal_clearance": True,
        "not_signed": True,
    }
    if unsigned_installer is not None:
        installer = unsigned_installer.resolve()
        if not installer.is_file() or installer.name != f"DeiLaw_Setup_v{version}.exe":
            raise ValueError("Unsigned installer does not match the source snapshot version")
        evidence["unsigned_installer_name"] = installer.name
        evidence["unsigned_installer_sha256"] = sha256(installer)
        evidence["unsigned_installer_bytes"] = installer.stat().st_size
    (outdir / "source_provenance.json").write_text(
        json.dumps(evidence, indent=2, ensure_ascii=False) + "\n", encoding="utf-8",
    )
    return evidence


def main() -> int:
    if len(sys.argv) != 4:
        print("Usage: python scripts/package_source_snapshot.py OUTPUT_DIR VERSION UNSIGNED_SETUP.exe", file=sys.stderr)
        return 2
    root = Path(__file__).resolve().parent.parent
    result = create_source_snapshot(root, Path(sys.argv[1]), sys.argv[2], Path(sys.argv[3]))
    print("Exact tracked project source archived:", result["source_commit"])
    print("Third-party Qt/Python/OpenSSL corresponding sources still need independent review")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
