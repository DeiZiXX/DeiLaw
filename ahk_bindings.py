import json
import uuid
from pathlib import Path


class AHKBindStore:
    """Persistent RP macro definitions and AutoHotkey v2 script builder."""

    def __init__(self, path="data/ahk_binds.json"):
        self.path = Path(path)
        self.data = self._load()
        self.save()

    @staticmethod
    def _defaults():
        return {
            "chat_key": "t",
            "open_chat_delay": 140,
            "bindings": [],
        }

    def _load(self):
        defaults = self._defaults()
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                defaults.update(payload)
        except Exception:
            pass

        if not isinstance(defaults.get("bindings"), list):
            defaults["bindings"] = []
        defaults["chat_key"] = str(defaults.get("chat_key") or "t").strip() or "t"
        try:
            defaults["open_chat_delay"] = max(
                40,
                min(3000, int(defaults.get("open_chat_delay", 140))),
            )
        except Exception:
            defaults["open_chat_delay"] = 140
        return defaults

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(self.data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def bindings(self):
        return [dict(item) for item in self.data.get("bindings", []) if isinstance(item, dict)]

    def get(self, bind_id):
        bind_id = str(bind_id or "")
        for item in self.data.get("bindings", []):
            if str(item.get("id") or "") == bind_id:
                return dict(item)
        return None

    def upsert(self, *, bind_id=None, name, hotkey, commands, delay_ms=350, enabled=True):
        name = " ".join(str(name or "").split()).strip()
        hotkey = str(hotkey or "").strip()
        commands = [str(line).strip() for line in commands if str(line).strip()]
        delay_ms = max(0, min(10000, int(delay_ms)))

        if not name:
            raise ValueError("Укажите название бинда.")
        if not hotkey:
            raise ValueError("Назначьте клавишу бинда.")
        if not commands:
            raise ValueError("Добавьте хотя бы одну RP-команду.")

        # Validate the key before changing the persistent store.
        self.hotkey_to_ahk(hotkey)

        # One hotkey should execute one macro in the generated script.
        for item in self.data.get("bindings", []):
            if (
                str(item.get("id") or "") != str(bind_id or "")
                and str(item.get("hotkey") or "").casefold() == hotkey.casefold()
            ):
                raise ValueError(
                    f"Бинд {hotkey} уже используется: {item.get('name') or 'без названия'}."
                )

        record = {
            "id": str(bind_id or uuid.uuid4()),
            "name": name,
            "hotkey": hotkey,
            "commands": commands,
            "delay_ms": delay_ms,
            "enabled": bool(enabled),
        }

        rows = self.data.setdefault("bindings", [])
        for index, item in enumerate(rows):
            if str(item.get("id") or "") == record["id"]:
                rows[index] = record
                self.save()
                return dict(record)

        rows.append(record)
        self.save()
        return dict(record)

    def remove(self, bind_id):
        bind_id = str(bind_id or "")
        before = len(self.data.get("bindings", []))
        self.data["bindings"] = [
            item
            for item in self.data.get("bindings", [])
            if str(item.get("id") or "") != bind_id
        ]
        changed = len(self.data["bindings"]) != before
        if changed:
            self.save()
        return changed

    def set_script_options(self, *, chat_key, open_chat_delay):
        chat_key = str(chat_key or "").strip() or "t"
        delay = max(40, min(3000, int(open_chat_delay)))
        self.data["chat_key"] = chat_key
        self.data["open_chat_delay"] = delay
        self.save()

    @staticmethod
    def _escape_ahk_string(value):
        return str(value).replace("`", "``").replace('"', '""')

    @staticmethod
    def hotkey_to_ahk(spec):
        spec = str(spec or "").strip()
        if not spec:
            raise ValueError("Пустой бинд.")

        parts = [part.strip() for part in spec.split("+") if part.strip()]
        modifiers = ""
        is_numpad = False
        base_parts = []

        for part in parts:
            token = part.casefold()
            if token in ("ctrl", "control"):
                modifiers += "^"
            elif token == "alt":
                modifiers += "!"
            elif token == "shift":
                modifiers += "+"
            elif token in ("win", "windows", "meta"):
                modifiers += "#"
            elif token in ("num", "numpad", "keypad"):
                is_numpad = True
            else:
                base_parts.append(part)

        if not base_parts:
            raise ValueError(f"Не удалось определить основную клавишу: {spec}")

        base = base_parts[-1]
        upper = base.upper()

        if is_numpad:
            num_map = {
                "0": "Numpad0",
                "1": "Numpad1",
                "2": "Numpad2",
                "3": "Numpad3",
                "4": "Numpad4",
                "5": "Numpad5",
                "6": "Numpad6",
                "7": "Numpad7",
                "8": "Numpad8",
                "9": "Numpad9",
                "PLUS": "NumpadAdd",
                "ADD": "NumpadAdd",
                "MINUS": "NumpadSub",
                "SUBTRACT": "NumpadSub",
                "ASTERISK": "NumpadMult",
                "MULTIPLY": "NumpadMult",
                "SLASH": "NumpadDiv",
                "DIVIDE": "NumpadDiv",
                "DECIMAL": "NumpadDot",
                "PERIOD": "NumpadDot",
                "ENTER": "NumpadEnter",
            }
            ahk_key = num_map.get(upper)
            if not ahk_key:
                raise ValueError(f"NumPad-бинд не поддерживается: {spec}")
            return modifiers + ahk_key

        cyrillic_physical = {
            "Й": "q", "Ц": "w", "У": "e", "К": "r", "Е": "t", "Н": "y",
            "Г": "u", "Ш": "i", "Щ": "o", "З": "p", "Х": "[", "Ъ": "]",
            "Ф": "a", "Ы": "s", "В": "d", "А": "f", "П": "g", "Р": "h",
            "О": "j", "Л": "k", "Д": "l", "Ж": ";", "Э": "'", "Я": "z",
            "Ч": "x", "С": "c", "М": "v", "И": "b", "Т": "n", "Ь": "m",
            "Б": ",", "Ю": ".", "Ё": "`",
        }
        if upper in cyrillic_physical:
            return modifiers + cyrillic_physical[upper]

        names = {
            "SPACE": "Space",
            "TAB": "Tab",
            "ENTER": "Enter",
            "RETURN": "Enter",
            "ESC": "Esc",
            "ESCAPE": "Esc",
            "BACKSPACE": "Backspace",
            "DELETE": "Delete",
            "DEL": "Delete",
            "INSERT": "Insert",
            "INS": "Insert",
            "HOME": "Home",
            "END": "End",
            "PAGEUP": "PgUp",
            "PGUP": "PgUp",
            "PAGEDOWN": "PgDn",
            "PGDOWN": "PgDn",
            "PGDN": "PgDn",
            "UP": "Up",
            "DOWN": "Down",
            "LEFT": "Left",
            "RIGHT": "Right",
            "CAPSLOCK": "CapsLock",
            "NUMLOCK": "NumLock",
            "SCROLLLOCK": "ScrollLock",
            "PAUSE": "Pause",
        }
        if upper in names:
            return modifiers + names[upper]
        if upper.startswith("F") and upper[1:].isdigit():
            number = int(upper[1:])
            if 1 <= number <= 24:
                return modifiers + upper
        if len(base) == 1:
            return modifiers + base.lower()

        raise ValueError(f"AHK не знает клавишу «{base}».")

    @classmethod
    def _chat_send_line(cls, chat_key):
        key = str(chat_key or "t").strip()
        if len(key) == 1:
            return f'Send "{cls._escape_ahk_string(key)}"'
        normalized = cls.hotkey_to_ahk(key)
        # Modifiers are not useful for the chat-open key; allow special keys,
        # but reject accidental modifier combinations.
        if normalized[:1] in "^!+#":
            raise ValueError("Клавиша открытия чата должна быть одной клавишей без Ctrl/Alt/Shift/Win.")
        return f'Send "{{{cls._escape_ahk_string(normalized)}}}"'

    def generate_script(self):
        chat_key = str(self.data.get("chat_key") or "t").strip() or "t"
        open_delay = max(40, min(3000, int(self.data.get("open_chat_delay", 140))))
        bindings = [item for item in self.bindings() if item.get("enabled", True)]

        lines = [
            "#Requires AutoHotkey v2.0",
            "#SingleInstance Force",
            "SetKeyDelay 30, 30",
            "",
            "; Создано DeiLaw — RP AHK бинды",
            "; Команды отправляются в игровой чат по одной строке.",
            "",
        ]

        for item in bindings:
            hotkey = self.hotkey_to_ahk(item.get("hotkey"))
            name = str(item.get("name") or "RP бинд").replace("\n", " ")
            commands = [str(line).strip() for line in item.get("commands", []) if str(line).strip()]
            delay_ms = max(0, min(10000, int(item.get("delay_ms", 350))))

            lines.append(f"; {name}")
            lines.append(f"{hotkey}::")
            lines.append("{")
            for command in commands:
                lines.append(f"    {self._chat_send_line(chat_key)}")
                lines.append(f"    Sleep {open_delay}")
                lines.append(f'    SendText "{self._escape_ahk_string(command)}"')
                lines.append('    Send "{Enter}"')
                if delay_ms:
                    lines.append(f"    Sleep {delay_ms}")
            lines.append("}")
            lines.append("")

        if not bindings:
            lines.append("; Активных биндов пока нет.")

        return "\n".join(lines).rstrip() + "\n"
