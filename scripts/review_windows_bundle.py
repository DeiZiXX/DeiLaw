"""Produce review evidence for the *actual* Windows app directory.

This is a technical consistency check, NOT a license clearance, complete SBOM,
or a substitute for human review of third-party runtime components.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path


BINARY_SUFFIXES = {".dll", ".exe", ".pyd"}
MANUAL_CHECKS = [
    "Copyright and relicensing rights for all DeiLaw code and media",
    "Qt DLL/plugins exact upstream licenses and LGPL replacement conditions",
    "OpenSSL, Python runtime, VC/UCRT, certifi and PyInstaller bootloader notices",
    "Bundled third-party files, relinking, corresponding sources and release notices",
    "SignPath Foundation acceptance and per-release human approval",
]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def audit_bundle(app_dir: Path) -> dict:
    app_dir = app_dir.resolve()
    if not app_dir.is_dir():
        raise FileNotFoundError(f"Windows application folder not found: {app_dir}")
    notice_dir = app_dir / "THIRD_PARTY_LICENSES"
    manifest_file = notice_dir / "license_manifest.json"
    if not manifest_file.is_file():
        raise FileNotFoundError(f"License manifest not bundled: {manifest_file}")
    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    if manifest.get("scope") != "PYTHON_BUILD_ENVIRONMENT_NOT_A_COMPLETE_RUNTIME_SBOM":
        raise ValueError("Unexpected license manifest scope")
    packages = manifest.get("packages")
    if not isinstance(packages, list) or not packages:
        raise ValueError("License manifest does not contain package records")

    issues = []
    verified = []
    used_paths = set()
    for package in packages:
        package_name = str(package.get("package", "UNKNOWN"))
        for item in package.get("license_files", []):
            relative = item.get("file")
            expected = item.get("sha256")
            if not isinstance(relative, str) or not relative or not isinstance(expected, str):
                issues.append(f"{package_name}: malformed notice entry")
                continue
            target = (notice_dir / relative).resolve()
            if not target.is_relative_to(notice_dir.resolve()) or target == notice_dir.resolve():
                issues.append(f"{package_name}: notice path escapes directory")
                continue
            if relative in used_paths:
                issues.append(f"{package_name}: duplicate notice path {relative}")
                continue
            used_paths.add(relative)
            if not target.is_file():
                issues.append(f"{package_name}: missing notice {relative}")
            elif sha256_file(target).lower() != expected.lower():
                issues.append(f"{package_name}: changed notice {relative}")
            else:
                verified.append({"package": package_name, "file": relative, "sha256": expected.lower()})

    binaries = sorted(
        path.relative_to(app_dir).as_posix()
        for path in app_dir.rglob("*")
        if path.is_file() and path.suffix.lower() in BINARY_SUFFIXES
    )
    if "DeiLaw.exe" not in binaries:
        issues.append("DeiLaw.exe is missing from Windows app folder")

    return {
        "schema": "deilaw-windows-license-evidence-v1",
        "status": "TECHNICAL_EVIDENCE_ONLY_NOT_LEGAL_CLEARANCE",
        "technical_integrity_ok": not issues,
        "requires_manual_compliance_review": True,
        "manifest_sha256": sha256_file(manifest_file),
        "build_environment_package_count": len(packages),
        "verified_notice_files": verified,
        "priority_packages_without_original_notice": manifest.get("missing_priority_notice_files", []),
        "windows_binaries": binaries,
        "manual_review_checklist": MANUAL_CHECKS,
        "integrity_issues": issues,
    }


def main() -> int:
    if len(sys.argv) != 3:
        print("Usage: python scripts/review_windows_bundle.py APP_DIR OUTPUT.json", file=sys.stderr)
        return 2
    output = Path(sys.argv[2])
    try:
        report = audit_bundle(Path(sys.argv[1]))
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"Bundle notice files verified: {len(report['verified_notice_files'])}")
        print(f"Windows binaries catalogued: {len(report['windows_binaries'])}")
        print("Human license, media, LGPL and SignPath review still required.")
        for issue in report["integrity_issues"]:
            print("ERROR: " + issue, file=sys.stderr)
        return 0 if report["technical_integrity_ok"] else 1
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        print(f"Windows license evidence failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
