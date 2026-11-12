"""Per-user program update preferences. A signed manifest is always required."""
import json
from pathlib import Path

UPDATE_MODES = ("auto", "confirm", "notify")
DEFAULT_UPDATE_MODE = "confirm"


def normalize_update_mode(value):
    return value if isinstance(value, str) and value in UPDATE_MODES else DEFAULT_UPDATE_MODE


def mode_from_settings(path):
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
        if isinstance(value, dict):
            return normalize_update_mode(value.get("update_install_mode"))
    except (OSError, ValueError, UnicodeError):
        pass
    return DEFAULT_UPDATE_MODE


def update_action(mode):
    mode = normalize_update_mode(mode)
    if mode == "auto":
        return "install"
    if mode == "confirm":
        return "ask"
    return "notify"


def startup_checks_enabled(settings_path):
    """Fail closed for new installs. Respect explicit settings on upgrades."""
    try:
        value = json.loads(Path(settings_path).read_text(encoding="utf-8"))
        return isinstance(value, dict) and value.get("auto_check_program_updates") is True
    except (OSError, ValueError, UnicodeError):
        return False
