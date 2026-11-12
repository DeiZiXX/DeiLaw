"""Fail-closed validation at the signed Windows-update download boundary."""
import re
from pathlib import Path
from urllib.parse import urlparse

MAX_SIGNED_INSTALLER_BYTES = 300 * 1024 * 1024


def validate_signed_download(info):
    """Check signed manifest fields again at the final file-write boundary.

    This does not replace Ed25519 manifest verification; signed metadata must
    be created by UpdateCheckWorker and must not be editable by consumers.
    """
    name = str(info.get("installer_name") or "")
    expected_hash = str(info.get("sha256") or "").lower()
    try:
        expected_size = int(info.get("size") or 0)
    except (TypeError, ValueError):
        raise ValueError("Некорректный размер подписанного установщика.") from None
    download_url = str(info.get("download_url") or "")
    parsed = urlparse(download_url)
    if (not name or name.startswith(".") or
            not name.lower().endswith(".exe") or
            Path(name).name != name or
            "/" in name or "\\" in name or ":" in name or
            not re.fullmatch(r"[0-9a-f]{64}", expected_hash) or
            not 0 < expected_size <= MAX_SIGNED_INSTALLER_BYTES or
            parsed.scheme != "https" or parsed.hostname != "github.com" or
            parsed.username is not None or parsed.password is not None or
            parsed.port not in (None, 443) or
            not parsed.path.startswith("/DeiZiXX/DeiLaw/releases/download/")):
        raise ValueError("Недоверенные метаданные установщика DeiLaw.")
    return name, expected_hash, expected_size
