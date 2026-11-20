"""Build DeiLaw on Windows using Python, without BAT/PS1 launchers or Git in ZIP.

Git provenance remains MANDATORY for GitHub release pipelines. A normal
downloaded source ZIP can still build a local unsigned DeiLaw.exe without Git.
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app_version import APP_VERSION  # noqa: E402


def invoke(*args: str) -> None:
    print("+", args[0], *(str(x) for x in args[1:]), flush=True)
    subprocess.run([str(a) for a in args], check=True, cwd=ROOT)


def require(path: Path, description: str) -> None:
    if not path.is_file():
        raise RuntimeError(f"Required {description} not found: {path}")


def python_script(script: str, *args: str) -> None:
    invoke(sys.executable, ROOT / "scripts" / script, *args)


def git_available() -> bool:
    return bool(shutil.which("git") and (ROOT / ".git").exists())


def security_preflight(require_git: bool) -> None:
    if require_git and not git_available():
        raise RuntimeError("Verified Git checkout required for CI provenance; source ZIPs cannot assert a commit SHA.")
    python_script("audit_public_source.py", *([] if git_available() else ["--scan-source-tree"]))


def install_build_dependencies() -> None:
    for filename in ("requirements.txt", "requirements-build.txt"):
        require(ROOT / filename, filename)
        invoke(sys.executable, "-m", "pip", "install", "--disable-pip-version-check", "-r", filename)


def build_executable() -> Path:
    for filename, label in (
        ("main.py", "main Python entry point"),
        ("installer/version_info.txt", "Windows version metadata"),
        ("installer/assets/deilaw_installer.ico", "installer icon"),
    ):
        require(ROOT / filename, label)
    asset_dir = ROOT / "assets"
    if not asset_dir.is_dir():
        raise RuntimeError("The assets directory is required for the app build")
    (ROOT / "build" / "generated-spec").mkdir(parents=True, exist_ok=True)
    invoke(
        sys.executable, "-m", "PyInstaller",
        "--noconfirm", "--clean", "--onedir", "--windowed",
        "--name", "DeiLaw",
        "--specpath", str(ROOT / "build" / "generated-spec"),
        "--version-file", str(ROOT / "installer" / "version_info.txt"),
        "--icon", str(ROOT / "installer" / "assets" / "deilaw_installer.ico"),
        "--add-data", str(asset_dir) + ";assets",
        str(ROOT / "main.py"),
    )
    exe = ROOT / "dist" / "DeiLaw" / "DeiLaw.exe"
    require(exe, "DeiLaw.exe")
    python_script(
        "collect_runtime_licenses.py",
        str(ROOT / "dist" / "DeiLaw" / "THIRD_PARTY_LICENSES"),
    )
    return exe


def verify_windows_metadata(exe: Path) -> None:
    # Executing a one-off PowerShell expression does NOT create a .ps1 file.
    # ProductName/Version must be checked even if PyInstaller returned success.
    escaped = str(exe).replace("'", "''")
    expr = (
        f"$m=(Get-Item -LiteralPath '{escaped}').VersionInfo; "
        f"if ($m.ProductName -cne 'DeiLaw' -or $m.ProductVersion -cne '{APP_VERSION}')"
        " { throw 'DeiLaw executable metadata mismatch' }"
    )
    invoke("powershell.exe", "-NoProfile", "-NonInteractive", "-Command", expr)


def nsis_compiler() -> str | None:
    candidates = [
        shutil.which("makensis.exe"),
        r"C:\Program Files (x86)\NSIS\makensis.exe",
        r"C:\Program Files\NSIS\makensis.exe",
    ]
    return next((str(p) for p in candidates if p and
                 (Path(p).is_file() or shutil.which(str(p)))), None)


def package_nsis(exe: Path, require_installer: bool, require_git: bool) -> None:
    compiler = nsis_compiler()
    if not compiler:
        if require_installer:
            raise RuntimeError("NSIS is required by the CI release job but is not installed")
        print("No NSIS installed: DeiLaw.exe is ready. Installer and Git source snapshot skipped.")
        return
    release = ROOT / "release"
    release.mkdir(parents=True, exist_ok=True)
    invoke(
        compiler, "/INPUTCHARSET", "UTF8", "/V2",
        f"/DAPP_VERSION={APP_VERSION}",
        f"/DDEILAW_SOURCE={ROOT / 'dist' / 'DeiLaw'}",
        f"/DDEILAW_OUTPUT={release}",
        str(ROOT / "installer" / "DeiLaw.nsi"),
    )
    setup = release / f"DeiLaw_Setup_v{APP_VERSION}.exe"
    require(setup, "unsigned NSIS setup")
    python_script(
        "build_inventory.py", str(ROOT / "dist" / "DeiLaw"),
        str(release / "build_inventory.json"),
    )
    python_script(
        "classify_native_components.py",
        str(release / "build_inventory.json"),
        str(release / "component_review.json"),
    )
    python_script(
        "review_windows_bundle.py",
        str(ROOT / "dist" / "DeiLaw"),
        str(release / "license_evidence.json"),
    )
    if git_available():
        python_script("package_source_snapshot.py", str(release), APP_VERSION, str(setup))
    elif require_git:
        raise RuntimeError("Cannot create verified source snapshot from a Git-less ZIP")
    else:
        print("Local ZIP: no Git provenance claimed and no source snapshot generated.")
    print(f"UNSIGNED test installer: {setup}")
    print("Not signed or approved by SignPath Foundation.")


def main() -> int:
    parser = argparse.ArgumentParser(description="Build an unsigned DeiLaw Windows candidate without BAT/PS1 files.")
    parser.add_argument("--app-only", action="store_true", help="Only build DeiLaw.exe; no NSIS needed")
    parser.add_argument("--skip-app-build", action="store_true", help="Use already built and possibly SignPath-signed DeiLaw.exe")
    parser.add_argument("--require-installer", action="store_true", help="Fail unless NSIS setup is built")
    parser.add_argument("--require-git-provenance", action="store_true", help="CI only: require real Git checkout and exact source snapshot")
    args = parser.parse_args()
    if os.name != "nt":
        parser.error("Windows is required for this build")
    if args.skip_app_build and args.app_only:
        parser.error("--skip-app-build cannot be combined with --app-only")
    try:
        security_preflight(args.require_git_provenance)
        if args.skip_app_build:
            exe = ROOT / "dist" / "DeiLaw" / "DeiLaw.exe"
            require(exe, "prebuilt signed app executable")
        else:
            install_build_dependencies()
            python_script("verify_source.py")
            invoke(sys.executable, "-m", "unittest", "discover", "-s", "tests", "-q")
            exe = build_executable()
        verify_windows_metadata(exe)
        if not args.app_only:
            package_nsis(exe, args.require_installer, args.require_git_provenance)
        print(f"Windows application available: {exe}")
        return 0
    except (RuntimeError, OSError, subprocess.CalledProcessError) as exc:
        print(f"BUILD FAILED: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
