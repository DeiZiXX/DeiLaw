import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import requests
from PyQt6.QtCore import QThread, pyqtSignal

from app_version import APP_VERSION


MANIFEST_ASSET = "update_manifest.json"

# Official DeiLaw update channel. This is intentionally built into the app so
# release builds no longer require or ship a separate update_config.json.
OFFICIAL_UPDATE_CONFIG = {
    "enabled": True,
    "provider": "github_releases",
    "github_owner": "DeiZiXX",
    "github_repo": "DeiLaw",
    "channel": "stable",
    "check_on_startup": True,
}


def app_base_dir():
    """Directory containing the installed EXE or source project."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def load_update_config(channel=None):
    """Return the built-in official DeiLaw update configuration.

    stable -> only stable GitHub Releases
    beta   -> stable + prerelease (alpha/beta/rc)
    """
    config = dict(OFFICIAL_UPDATE_CONFIG)
    if channel is None:
        # Test builds (a/b/alpha/beta/rc) stay on the Beta channel by default
        # so letter builds such as 0.2.0b can discover 0.2.0c, rc, etc.
        selected = (
            "beta"
            if version_key(APP_VERSION)[3] < 4
            else str(config.get("channel") or "stable").strip().lower()
        )
    else:
        selected = str(channel or "stable").strip().lower()
    if selected not in ("stable", "beta"):
        selected = "stable"
    config["channel"] = selected
    return config


def update_is_configured(config=None):
    config = config or load_update_config()
    owner = str(config.get("github_owner") or "").strip()
    repo = str(config.get("github_repo") or "").strip()

    if not config.get("enabled", True):
        return False
    if not owner or not repo:
        return False
    if "CHANGE_ME" in owner.upper() or "CHANGE_ME" in repo.upper():
        return False
    return True


def version_key(version):
    """Comparable key for DeiLaw stable and test versions.

    Letter builds are ordered naturally:
      0.2.0a < 0.2.0b < 0.2.0c < ... < 0.2.0rc1 < 0.2.0 < 0.2.1

    Also accepts alpha/beta aliases and numbered suffixes such as b2/c3.
    """
    value = str(version or "").strip().lstrip("vV").lower()
    value = value.split("+", 1)[0]

    match = re.match(
        r"^(\d+)(?:\.(\d+))?(?:\.(\d+))?(.*)$",
        value,
    )
    if not match:
        return (0, 0, 0, 0, 0)

    major = int(match.group(1) or 0)
    minor = int(match.group(2) or 0)
    patch = int(match.group(3) or 0)
    suffix = (match.group(4) or "").strip(" ._-")

    # Stable release is always newer than prereleases with the same numeric
    # core. RC is newer than letter test builds.
    if not suffix:
        stage = 300
        stage_number = 0
    elif suffix.startswith(("rc", "releasecandidate")):
        stage = 200
        digits = re.findall(r"\d+", suffix)
        stage_number = int(digits[0]) if digits else 0
    else:
        alias = suffix
        if suffix.startswith("alpha"):
            alias = "a" + suffix[len("alpha"):]
        elif suffix.startswith("beta"):
            alias = "b" + suffix[len("beta"):]

        letter_match = re.match(r"^([a-z])(\d*)$", alias)
        if letter_match:
            letter = letter_match.group(1)
            # a=101, b=102, c=103 ... z=126
            stage = 100 + (ord(letter) - ord("a") + 1)
            stage_number = int(letter_match.group(2) or 0)
        else:
            # Unknown suffixes remain below known prerelease stages.
            stage = 0
            digits = re.findall(r"\d+", suffix)
            stage_number = int(digits[0]) if digits else 0

    return (major, minor, patch, stage, stage_number)


def is_newer_version(remote, current=APP_VERSION):
    return version_key(remote) > version_key(current)


def _repair_mojibake(value):
    """Repair the common UTF-8-as-Windows-1251 corruption seen in PS 5.1."""
    text = str(value or "")
    if not text:
        return text

    # Typical damaged Russian text contains sequences like "РџСЂ...".
    if "Р" not in text and "С" not in text:
        return text

    try:
        repaired = text.encode("cp1251").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return text

    # Keep the repaired form only when it clearly reduces mojibake markers.
    before = text.count("Р") + text.count("С")
    after = repaired.count("Р") + repaired.count("С")
    return repaired if after < before else text


def _release_notes_from_manifest(manifest, release):
    notes = manifest.get("notes")
    if isinstance(notes, list):
        return [
            _repair_mojibake(str(item).strip())
            for item in notes
            if str(item).strip()
        ]
    if isinstance(notes, str) and notes.strip():
        return [
            _repair_mojibake(line.strip(" •-\t"))
            for line in notes.splitlines()
            if line.strip()
        ]

    body = str(release.get("body") or "").strip()
    if body:
        return [
            _repair_mojibake(line.strip(" •-\t"))
            for line in body.splitlines()
            if line.strip()
        ]
    return []


class UpdateCheckWorker(QThread):
    update_available = pyqtSignal(object)
    no_update = pyqtSignal(str)
    error = pyqtSignal(str)

    def __init__(self, config=None, parent=None):
        super().__init__(parent)
        self.config = config or load_update_config()

    def run(self):
        try:
            if not update_is_configured(self.config):
                self.error.emit(
                    "Канал автоматических обновлений DeiLaw недоступен."
                )
                return

            provider = str(
                self.config.get("provider") or "github_releases"
            ).strip().lower()
            if provider != "github_releases":
                self.error.emit(
                    f"Неподдерживаемый провайдер обновлений: {provider}"
                )
                return

            owner = self.config["github_owner"]
            repo = self.config["github_repo"]
            channel = str(
                self.config.get("channel") or "stable"
            ).strip().lower()
            if channel not in ("stable", "beta"):
                channel = "stable"

            # Do not use /releases/latest here: GitHub deliberately excludes
            # prereleases from that endpoint. Beta users must be able to see
            # versions such as 0.2.0a / 0.2.0b / 0.2.0c / rc.
            api_url = (
                f"https://api.github.com/repos/{owner}/{repo}/releases"
                "?per_page=30"
            )

            headers = {
                "Accept": "application/vnd.github+json",
                "User-Agent": f"DeiLaw/{APP_VERSION}",
                "Cache-Control": "no-cache",
            }
            response = requests.get(
                api_url,
                headers=headers,
                timeout=12,
            )
            if response.status_code == 404:
                self.no_update.emit(
                    "На GitHub ещё нет опубликованных релизов."
                )
                return
            response.raise_for_status()
            releases = response.json()
            if not isinstance(releases, list):
                raise RuntimeError("GitHub вернул неожиданный список релизов.")

            candidates = []
            for item in releases:
                if not isinstance(item, dict) or item.get("draft"):
                    continue
                if channel == "stable" and item.get("prerelease"):
                    continue

                tag_version = str(
                    item.get("tag_name")
                    or item.get("name")
                    or ""
                ).strip().lstrip("vV")
                if not tag_version or not is_newer_version(tag_version):
                    continue

                assets = item.get("assets") or []
                manifest_asset = next(
                    (
                        asset
                        for asset in assets
                        if asset.get("name") == MANIFEST_ASSET
                    ),
                    None,
                )
                if manifest_asset is None:
                    continue

                candidates.append((version_key(tag_version), item, tag_version, manifest_asset))

            if not candidates:
                label = "Stable" if channel == "stable" else "Beta"
                self.no_update.emit(
                    f"Установлена актуальная версия DeiLaw {APP_VERSION} "
                    f"для канала {label}."
                )
                return

            candidates.sort(key=lambda row: row[0], reverse=True)
            _, release, tag_version, manifest_asset = candidates[0]
            assets = release.get("assets") or []

            manifest_url = manifest_asset.get("browser_download_url")
            if not manifest_url:
                raise RuntimeError(
                    "GitHub не вернул ссылку на update_manifest.json."
                )

            manifest_response = requests.get(
                manifest_url,
                headers={"User-Agent": f"DeiLaw/{APP_VERSION}"},
                timeout=12,
            )
            manifest_response.raise_for_status()
            manifest = manifest_response.json()

            manifest_version = str(
                manifest.get("version") or tag_version
            ).strip().lstrip("vV")
            if not is_newer_version(manifest_version):
                self.no_update.emit(
                    f"Установлена актуальная версия DeiLaw {APP_VERSION}."
                )
                return

            installer_name = str(
                manifest.get("installer_asset")
                or f"DeiLaw_Setup_v{manifest_version}.exe"
            ).strip()
            installer_asset = next(
                (
                    asset
                    for asset in assets
                    if asset.get("name") == installer_name
                ),
                None,
            )
            if installer_asset is None:
                raise RuntimeError(
                    f"В релизе не найден установщик {installer_name}."
                )

            expected_sha256 = str(
                manifest.get("sha256") or ""
            ).strip().lower()
            if len(expected_sha256) != 64:
                raise RuntimeError(
                    "update_manifest.json не содержит корректный SHA-256."
                )

            info = {
                "version": manifest_version,
                "current_version": APP_VERSION,
                "mandatory": bool(manifest.get("mandatory", False)),
                "channel": channel,
                "published_at": (
                    manifest.get("published_at")
                    or release.get("published_at")
                    or ""
                ),
                "notes": _release_notes_from_manifest(
                    manifest,
                    release,
                ),
                "installer_name": installer_name,
                "download_url": installer_asset.get(
                    "browser_download_url"
                ),
                "sha256": expected_sha256,
                "size": int(
                    manifest.get("size")
                    or installer_asset.get("size")
                    or 0
                ),
                "release_url": release.get("html_url") or "",
            }

            if not info["download_url"]:
                raise RuntimeError(
                    "GitHub не вернул ссылку на установщик."
                )

            self.update_available.emit(info)
        except requests.RequestException as exc:
            self.error.emit(
                "Не удалось проверить обновления через интернет: "
                f"{exc}"
            )
        except Exception as exc:
            self.error.emit(str(exc))


class ProgramReleaseHistoryWorker(QThread):
    """Load published DeiLaw program releases for the in-app history page."""

    completed = pyqtSignal(object)
    error = pyqtSignal(str)

    def __init__(self, config=None, parent=None, limit=100):
        super().__init__(parent)
        self.config = config or load_update_config("beta")
        self.limit = max(1, min(100, int(limit)))

    def run(self):
        try:
            if not update_is_configured(self.config):
                raise RuntimeError(
                    "Канал обновлений DeiLaw не настроен."
                )

            owner = self.config["github_owner"]
            repo = self.config["github_repo"]
            url = (
                f"https://api.github.com/repos/{owner}/{repo}/releases"
                f"?per_page={self.limit}"
            )
            response = requests.get(
                url,
                timeout=12,
                headers={
                    "Accept": "application/vnd.github+json",
                    "User-Agent": f"DeiLaw/{APP_VERSION}",
                    "Cache-Control": "no-cache",
                },
            )
            response.raise_for_status()

            payload = response.json()
            if not isinstance(payload, list):
                raise RuntimeError(
                    "GitHub вернул некорректную историю релизов."
                )

            releases = []
            for release in payload:
                if not isinstance(release, dict):
                    continue
                if release.get("draft"):
                    continue

                tag = str(
                    release.get("tag_name")
                    or release.get("name")
                    or ""
                ).strip()
                version = tag.lstrip("vV")
                if not version:
                    continue

                body = _repair_mojibake(
                    str(release.get("body") or "").strip()
                )
                name = _repair_mojibake(
                    str(release.get("name") or tag).strip()
                )

                releases.append({
                    "version": version,
                    "tag": tag,
                    "name": name or f"DeiLaw {tag}",
                    "prerelease": bool(
                        release.get("prerelease")
                    ),
                    "published_at": str(
                        release.get("published_at")
                        or release.get("created_at")
                        or ""
                    ),
                    "notes": body,
                    "url": str(
                        release.get("html_url") or ""
                    ),
                })

            releases.sort(
                key=lambda item: version_key(
                    item.get("version")
                ),
                reverse=True,
            )
            self.completed.emit(releases)
        except requests.RequestException as exc:
            self.error.emit(
                "Не удалось загрузить историю обновлений DeiLaw: "
                f"{exc}"
            )
        except Exception as exc:
            self.error.emit(str(exc))


class UpdateDownloadWorker(QThread):
    progress = pyqtSignal(int, int, int)
    completed = pyqtSignal(str)
    error = pyqtSignal(str)

    def __init__(self, update_info, parent=None):
        super().__init__(parent)
        self.update_info = dict(update_info)

    def run(self):
        partial_path = None
        try:
            version = self.update_info["version"]
            name = self.update_info["installer_name"]
            url = self.update_info["download_url"]
            expected = self.update_info["sha256"].lower()

            local_appdata = os.environ.get("LOCALAPPDATA")
            if local_appdata:
                update_dir = Path(local_appdata) / "DeiLaw" / "updates"
            else:
                update_dir = (
                    Path(tempfile.gettempdir()) / "DeiLaw" / "updates"
                )
            update_dir.mkdir(parents=True, exist_ok=True)

            final_path = update_dir / name
            partial_path = update_dir / (name + ".part")

            digest = hashlib.sha256()
            downloaded = 0

            with requests.get(
                url,
                stream=True,
                timeout=(12, 60),
                headers={"User-Agent": f"DeiLaw/{APP_VERSION}"},
            ) as response:
                response.raise_for_status()
                total = int(
                    response.headers.get("Content-Length")
                    or self.update_info.get("size")
                    or 0
                )

                with partial_path.open("wb") as handle:
                    for chunk in response.iter_content(
                        chunk_size=1024 * 512
                    ):
                        if not chunk:
                            continue
                        handle.write(chunk)
                        digest.update(chunk)
                        downloaded += len(chunk)
                        percent = (
                            int(downloaded * 100 / total)
                            if total > 0
                            else 0
                        )
                        self.progress.emit(
                            percent,
                            downloaded,
                            total,
                        )

            actual = digest.hexdigest().lower()
            if actual != expected:
                try:
                    partial_path.unlink(missing_ok=True)
                except Exception:
                    pass
                raise RuntimeError(
                    "SHA-256 загруженного установщика не совпадает с "
                    "манифестом. Обновление отменено."
                )

            if final_path.exists():
                final_path.unlink()
            partial_path.replace(final_path)
            self.completed.emit(str(final_path))
        except requests.RequestException as exc:
            self.error.emit(
                f"Не удалось скачать обновление: {exc}"
            )
        except Exception as exc:
            if partial_path is not None:
                try:
                    partial_path.unlink(missing_ok=True)
                except Exception:
                    pass
            self.error.emit(str(exc))


def create_update_install_helper(installer_path):
    """Create a PowerShell helper that waits for DeiLaw to exit, updates, restarts."""
    installer_path = Path(installer_path).resolve()
    if not installer_path.exists():
        raise FileNotFoundError(installer_path)

    current_pid = os.getpid()

    if getattr(sys, "frozen", False):
        restart_file = Path(sys.executable).resolve()
        restart_args = ""
    else:
        restart_file = Path(sys.executable).resolve()
        restart_args = str((Path(__file__).resolve().parent / "main.py"))

    helper_dir = installer_path.parent
    helper_path = helper_dir / "deilaw_update_helper.ps1"

    def ps_quote(value):
        return str(value).replace("'", "''")

    installer_q = ps_quote(installer_path)
    restart_q = ps_quote(restart_file)
    restart_args_q = ps_quote(restart_args)

    script = f"""$ErrorActionPreference = 'SilentlyContinue'
$TargetPid = {current_pid}
$Installer = '{installer_q}'
$RestartFile = '{restart_q}'
$RestartArgs = '{restart_args_q}'

try {{
    Wait-Process -Id $TargetPid -ErrorAction SilentlyContinue
}} catch {{}}

$Args = @(
    '/VERYSILENT',
    '/SUPPRESSMSGBOXES',
    '/NORESTART',
    '/CLOSEAPPLICATIONS'
)

$Process = Start-Process -FilePath $Installer -ArgumentList $Args -Wait -PassThru
if ($Process -and $Process.ExitCode -eq 0) {{
    Remove-Item -LiteralPath $Installer -Force -ErrorAction SilentlyContinue
}}

# Always reopen DeiLaw after the installer attempt. If installation failed,
# the currently installed version is still available to the user.
if ([string]::IsNullOrWhiteSpace($RestartArgs)) {{
    Start-Process -FilePath $RestartFile
}} else {{
    Start-Process -FilePath $RestartFile -ArgumentList @($RestartArgs)
}}

Start-Sleep -Milliseconds 800
Remove-Item -LiteralPath $PSCommandPath -Force -ErrorAction SilentlyContinue
"""
    helper_path.write_text(script, encoding="utf-8-sig")
    return helper_path


def launch_update_helper(helper_path):
    flags = 0
    if sys.platform == "win32":
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)

    subprocess.Popen(
        [
            "powershell.exe",
            "-NoLogo",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-WindowStyle",
            "Hidden",
            "-File",
            str(Path(helper_path).resolve()),
        ],
        close_fds=True,
        creationflags=flags,
    )
