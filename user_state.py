import json
import shutil
from copy import deepcopy
from datetime import datetime
from pathlib import Path


class ProfileStore:
    """Persistent user profiles for favorites, memo and calculator state."""

    DEFAULT_PROFILES = ("Профиль 1",)
    LEGACY_AUTO_PROFILES = ("Общий", "ДПС", "Полиция", "Адвокат")

    def __init__(self, path="data/profiles.json"):
        self.path = Path(path)
        self.data = self._load()
        self._ensure_defaults()
        self.save()

    @staticmethod
    def _blank_profile():
        return {
            "favorites": [],
            "memo_columns": None,
            "calculator_entries": [],
        }

    def _load(self):
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                return payload
        except Exception:
            pass
        return {"active": "Профиль 1", "profiles": {}, "recent": []}

    def _profile_is_blank(self, state):
        if not isinstance(state, dict):
            return True
        return (
            not state.get("favorites")
            and not state.get("memo_columns")
            and not state.get("calculator_entries")
        )

    def _should_migrate_legacy_defaults(self):
        profiles = self.data.get("profiles", {})
        if not isinstance(profiles, dict) or not profiles:
            return False
        legacy_names = set(self.LEGACY_AUTO_PROFILES)
        current_names = set(str(name) for name in profiles.keys())
        if current_names != legacy_names:
            return False
        if self.data.get("recent"):
            return False
        return all(self._profile_is_blank(profiles.get(name)) for name in current_names)

    def _ensure_defaults(self):
        if not isinstance(self.data.get("profiles"), dict):
            self.data["profiles"] = {}
        if not isinstance(self.data.get("recent"), list):
            self.data["recent"] = []

        if self._should_migrate_legacy_defaults():
            self.data["profiles"] = {
                "Профиль 1": self._blank_profile(),
            }
            self.data["active"] = "Профиль 1"

        for name in self.DEFAULT_PROFILES:
            self.data["profiles"].setdefault(
                name,
                self._blank_profile(),
            )

        # The application must always have at least one profile.
        if not self.data["profiles"]:
            self.data["profiles"] = {
                "Профиль 1": self._blank_profile(),
            }

        active = str(self.data.get("active") or "").strip()
        if active not in self.data["profiles"]:
            active = next(iter(self.data["profiles"]))
        self.data["active"] = active
    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(self.data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def profile_names(self):
        return list(self.data.get("profiles", {}).keys())

    def active_name(self):
        return str(self.data.get("active") or "Профиль 1")

    def set_active(self, name):
        name = str(name or "").strip()
        if name not in self.data["profiles"]:
            raise KeyError(name)
        self.data["active"] = name
        self.save()

    def add_profile(self, name):
        name = " ".join(str(name or "").split()).strip()
        if not name:
            raise ValueError("Название профиля не может быть пустым.")
        if name not in self.data["profiles"]:
            self.data["profiles"][name] = self._blank_profile()

        deleted = [
            item
            for item in self.data.get("deleted_default_profiles", [])
            if item != name
        ]
        self.data["deleted_default_profiles"] = deleted
        self.save()
        return name

    def delete_profile(self, name):
        name = str(name or "").strip()
        profiles = self.data.get("profiles", {})

        if name not in profiles:
            raise KeyError(name)
        if len(profiles) <= 1:
            raise ValueError(
                "Нельзя удалить последний профиль. "
                "Сначала создайте другой профиль."
            )

        del profiles[name]

        if name in self.DEFAULT_PROFILES:
            deleted = {
                str(item)
                for item in self.data.get(
                    "deleted_default_profiles",
                    [],
                )
            }
            deleted.add(name)
            self.data["deleted_default_profiles"] = sorted(deleted)

        if self.data.get("active") == name:
            self.data["active"] = next(iter(profiles))

        self.save()
        return str(self.data["active"])

    def rename_profile(self, old_name, new_name):
        old_name = str(old_name or "").strip()
        new_name = " ".join(str(new_name or "").split()).strip()
        profiles = self.data.get("profiles", {})

        if old_name not in profiles:
            raise KeyError(old_name)
        if not new_name:
            raise ValueError("Название профиля не может быть пустым.")
        if new_name != old_name and new_name in profiles:
            raise ValueError("Профиль с таким названием уже существует.")
        if new_name == old_name:
            return old_name

        reordered = {}
        for key, value in profiles.items():
            if key == old_name:
                reordered[new_name] = value
            else:
                reordered[key] = value
        self.data["profiles"] = reordered

        if self.data.get("active") == old_name:
            self.data["active"] = new_name

        self.save()
        return new_name

    def state(self, name=None):
        name = str(name or self.active_name())
        return self.data["profiles"].setdefault(name, self._blank_profile())

    def save_runtime(self, memo_columns=None, calculator_entries=None, name=None):
        state = self.state(name)
        if memo_columns is not None:
            state["memo_columns"] = deepcopy(memo_columns)
        if calculator_entries is not None:
            state["calculator_entries"] = deepcopy(calculator_entries)
        self.save()

    def memo_columns(self, fallback, name=None):
        value = self.state(name).get("memo_columns")
        if isinstance(value, list) and value:
            return deepcopy(value)
        return deepcopy(fallback)

    def calculator_entries(self, name=None):
        value = self.state(name).get("calculator_entries")
        return deepcopy(value) if isinstance(value, list) else []

    @staticmethod
    def article_key(article):
        law_title = str(article.get("law_title") or "").strip()
        article_number = str(article.get("article_number") or "").strip().rstrip(".")
        return f"{law_title.casefold()}::{article_number.casefold()}"

    @staticmethod
    def compact_article(article):
        return {
            "law_title": str(article.get("law_title") or "").strip(),
            "article_number": str(article.get("article_number") or "").strip(),
            "article_title": str(article.get("article_title") or article.get("title") or "").strip(),
            "url": str(article.get("url") or "").strip(),
        }

    def favorites(self, name=None):
        value = self.state(name).get("favorites")
        return deepcopy(value) if isinstance(value, list) else []

    def is_favorite(self, article, name=None):
        key = self.article_key(article)
        return any(self.article_key(item) == key for item in self.favorites(name))

    def toggle_favorite(self, article, name=None):
        state = self.state(name)
        favorites = state.setdefault("favorites", [])
        key = self.article_key(article)
        kept = [item for item in favorites if self.article_key(item) != key]
        if len(kept) != len(favorites):
            state["favorites"] = kept
            self.save()
            return False
        kept.insert(0, self.compact_article(article))
        state["favorites"] = kept[:100]
        self.save()
        return True

    def remove_favorite(self, article, name=None):
        state = self.state(name)
        key = self.article_key(article)
        state["favorites"] = [
            item for item in state.get("favorites", [])
            if self.article_key(item) != key
        ]
        self.save()

    def add_recent(self, article):
        item = self.compact_article(article)
        key = self.article_key(item)
        recent = [
            old for old in self.data.get("recent", [])
            if self.article_key(old) != key
        ]
        recent.insert(0, item)
        self.data["recent"] = recent[:30]
        self.save()

    def recent(self):
        return deepcopy(self.data.get("recent", []))


class BackupManager:
    """Create/restore compact backups of DeiLaw user-owned data."""

    USER_FILES = (
        "settings.json",
        "memo.json",
        "profiles.json",
        "search_history.json",
        "ai_learning.jsonl",
        "training_dataset.jsonl",
        # Identity credentials and Cloud AI refresh tokens must NEVER enter
        # ordinary plaintext user backups.
        "ahk_binds.json",
    )

    def __init__(self, data_dir="data"):
        self.data_dir = Path(data_dir)
        self.backup_root = self.data_dir / "backups"

    def create_backup(self, reason="manual"):
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.backup_root.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        safe_reason = "".join(
            ch if ch.isalnum() or ch in "-_" else "_"
            for ch in str(reason or "backup")
        )[:40]
        target = self.backup_root / f"{stamp}_{safe_reason}"
        target.mkdir(parents=True, exist_ok=True)

        copied = 0
        for name in self.USER_FILES:
            source = self.data_dir / name
            if source.is_file():
                shutil.copy2(source, target / name)
                copied += 1

        meta = {
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "reason": str(reason or "manual"),
            "files": copied,
        }
        (target / "backup.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        self._trim(10)
        return target

    def _trim(self, keep=10):
        if not self.backup_root.exists():
            return
        folders = sorted(
            [p for p in self.backup_root.iterdir() if p.is_dir()],
            key=lambda p: p.name,
            reverse=True,
        )
        for folder in folders[max(1, int(keep)):]:
            shutil.rmtree(folder, ignore_errors=True)

    def list_backups(self):
        if not self.backup_root.exists():
            return []
        return sorted(
            [p for p in self.backup_root.iterdir() if p.is_dir()],
            key=lambda p: p.name,
            reverse=True,
        )

    def restore_latest(self):
        backups = self.list_backups()
        if not backups:
            raise FileNotFoundError("Резервные копии ещё не создавались.")
        source = backups[0]
        restored = 0
        self.data_dir.mkdir(parents=True, exist_ok=True)
        for name in self.USER_FILES:
            candidate = source / name
            if candidate.is_file():
                shutil.copy2(candidate, self.data_dir / name)
                restored += 1
        return source, restored
