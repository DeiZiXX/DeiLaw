"""Preserve the license files shipped with installed Python wheels for DeiLaw.

This tool deliberately does NOT assert legal compliance: transitive Qt/Windows
components, third-party dependencies, and replacement/relinking rights still
require review of the exact Windows build.
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
from importlib import metadata
from pathlib import Path


POSSIBLE_LICENSE_FILE = re.compile(
    r"(?i)^(?:licen[cs]e(?:[._-].*)?|copying(?:[._-].*)?|"
    r"notice(?:[._-].*)?|copyright(?:[._-].*)?)$"
)
MAJOR_COMPONENTS = {
    "pyqt6", "pyqt6-qt6", "pyqt6-sip", "requests",
    "beautifulsoup4", "cryptography", "certifi", "urllib3",
    "charset-normalizer", "idna", "cffi", "soupsieve",
}


def normalized_package_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def collect_licenses(dest: Path, distributions=None) -> dict:
    """Copy wheel license notices with no inference from missing metadata.

    The manifest reports every build-env package, including build tools not
    necessarily bundled by PyInstaller. Do not treat this as a runtime SBOM.
    """
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    if distributions is None:
        distributions = list(metadata.distributions())

    reports = []
    for dist in sorted(distributions, key=lambda d: normalized_package_name(d.metadata.get("Name", ""))):
        name = dist.metadata.get("Name", "")
        if not name:
            continue
        norm = normalized_package_name(name)
        version = dist.version
        path_component = re.sub(r"[^A-Za-z0-9._-]", "_", f"{norm}-{version}")
        package_root = dest / path_component
        preserved = []
        seen_notice_paths = set()
        for entry in dist.files or []:
            as_posix = entry.as_posix()
            parts = entry.parts
            # Nested vendored .dist-info folders can contain DIFFERENT LICENSE
            # files with the same basename. Keep their entire wheel-relative
            # paths to avoid overwriting or misrepresenting the upstream text.
            if not parts or not any(p.lower().endswith(".dist-info") for p in parts):
                continue
            leaf = parts[-1]
            if not POSSIBLE_LICENSE_FILE.match(leaf):
                continue
            relative = Path(as_posix)
            if relative.is_absolute() or any(p in ("", ".", "..") for p in relative.parts):
                continue
            relative_name = relative.as_posix()
            if relative_name in seen_notice_paths:
                continue
            src = Path(dist.locate_file(entry))
            if not src.is_file() or src.stat().st_size > 2_000_000:
                continue
            out = package_root.joinpath(*relative.parts)
            out.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, out)
            seen_notice_paths.add(relative_name)
            preserved.append({
                "file": out.relative_to(dest).as_posix(),
                "sha256": hashlib.sha256(out.read_bytes()).hexdigest(),
            })
        reports.append({
            "package": name,
            "version": version,
            "license_expression": dist.metadata.get("License-Expression") or "NOT_DECLARED",
            "license_files": preserved,
            "needs_human_review": bool(norm in MAJOR_COMPONENTS and not preserved),
        })
    manifest = {
        "scope": "PYTHON_BUILD_ENVIRONMENT_NOT_A_COMPLETE_RUNTIME_SBOM",
        "not_legal_certification": True,
        "qt_and_windows_dll_licenses_need_manual_review": True,
        "packages": reports,
        "missing_priority_notice_files": [p["package"] for p in reports if p["needs_human_review"]],
    }
    (dest / "license_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


if __name__ == "__main__":
    import sys
    if len(sys.argv) != 2:
        raise SystemExit("Usage: python scripts/collect_runtime_licenses.py OUTPUT_DIR")
    result = collect_licenses(Path(sys.argv[1]))
    print("Preserved license files for", len(result["packages"]), "build-env packages")
    print("Priority packages without upstream license file:", ", ".join(result["missing_priority_notice_files"]) or "none")
    print("THIS IS NOT A VERIFIED WINDOWS RUNTIME LICENSE AUDIT")
