"""Supabase guest and Discord user sessions for DeiLaw.

An API publishable key identifies an application, not a person. Cloud AI needs
an actual user access token. Refresh credentials are protected with Windows
DPAPI and never included in backups or diagnostics.
"""

import ctypes
import ctypes.wintypes
import json
import subprocess
import sys
import threading
import time
from pathlib import Path

import requests


class CloudAuthError(RuntimeError):
    pass


def restart_deilaw_for_login_choice(logged_out_mode=None, *, discord_only=False):
    """Restart into account choice or directly into fresh Discord OAuth."""
    frozen = getattr(sys, "frozen", False)
    app_dir = (Path(sys.executable).resolve().parent if frozen
               else Path(__file__).resolve().parent)
    command = [sys.executable]
    if not frozen:
        command.append(str(app_dir / "main.py"))
    command.append("--auth-discord" if discord_only else "--auth-choice")
    if logged_out_mode in ("discord", "guest"):
        command.append(f"--logout-mode={logged_out_mode}")
    return subprocess.Popen(command, cwd=str(app_dir), close_fds=True)


class _DataBlob(ctypes.Structure):
    _fields_ = [
        ("cbData", ctypes.wintypes.DWORD),
        ("pbData", ctypes.POINTER(ctypes.c_ubyte)),
    ]


def _windows_dpapi(data: bytes, *, decrypt: bool) -> bytes:
    if sys.platform != "win32":
        raise CloudAuthError("Защищённое хранение Cloud AI доступно только в Windows.")
    source = ctypes.create_string_buffer(data)
    original = _DataBlob(
        len(data), ctypes.cast(source, ctypes.POINTER(ctypes.c_ubyte))
    )
    result = _DataBlob()
    crypt = ctypes.windll.crypt32
    operation = crypt.CryptUnprotectData if decrypt else crypt.CryptProtectData
    if decrypt:
        ok = operation(
            ctypes.byref(original), None, None, None, None, 0x1,
            ctypes.byref(result),
        )
    else:
        ok = operation(
            ctypes.byref(original), None, None, None, None, 0x1,
            ctypes.byref(result),
        )
    if not ok:
        raise CloudAuthError("Windows не удалось защитить данные Cloud AI.")
    try:
        return ctypes.string_at(result.pbData, result.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(ctypes.cast(result.pbData, ctypes.c_void_p))


class WindowsTokenStore:
    def __init__(self, path):
        self.path = Path(path)
        # Separate marker: other live clients refreshing their cached token
        # must not overwrite the user's request to choose an account next time.
        self.choice_path = self.path.with_suffix(".choose_account")

    def choice_requested(self):
        return self.choice_path.is_file()

    def request_choice(self):
        self.choice_path.parent.mkdir(parents=True, exist_ok=True)
        self.choice_path.touch(exist_ok=True)

    def clear_choice_request(self):
        self.choice_path.unlink(missing_ok=True)

    def load(self):
        try:
            return json.loads(
                _windows_dpapi(self.path.read_bytes(), decrypt=True).decode("utf-8")
            )
        except (FileNotFoundError, ValueError, CloudAuthError, OSError):
            return {}

    def save(self, session):
        encrypted = _windows_dpapi(
            json.dumps(session, ensure_ascii=False).encode("utf-8"), decrypt=False
        )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_bytes(encrypted)
        temporary.replace(self.path)

    def clear(self):
        self.path.unlink(missing_ok=True)


class AnonymousSupabaseSession:
    """Maintain independent Discord and guest tokens, protected by DPAPI.

    ``allow_implicit_guest`` is off in the application: only the guest button
    creates anonymous accounts. It remains opt-in for older API consumers.
    """

    MODES = ("guest", "discord")

    def __init__(self, url, publishable_key, *, store=None, http=None,
                 allow_implicit_guest=False):
        self.url = str(url or "").rstrip("/")
        self.key = str(publishable_key or "").strip()
        self.store = store or WindowsTokenStore("data/cloud_auth.bin")
        self.http = http or requests
        self.lock = threading.Lock()
        self.allow_implicit_guest = allow_implicit_guest
        self.data = self._normalize(self.store.load() or {})

    @staticmethod
    def _normalize(saved):
        if not isinstance(saved, dict):
            saved = {}
        if saved.get("schema") == 2:
            accounts = saved.get("accounts") or {}
            if not isinstance(accounts, dict):
                accounts = {}
            active = saved.get("active")
            return {
                "schema": 2,
                "active": active if active in ("guest", "discord") else None,
                "prompt_next_start": saved.get("prompt_next_start") is True,
                "accounts": {
                    mode: value for mode, value in accounts.items()
                    if mode in ("guest", "discord") and isinstance(value, dict)
                },
            }
        # v1 contained only one anonymous session. Never reclassify an
        # unknown permanent user as Discord based on editable local metadata.
        user = saved.get("user") or {}
        accounts = {"guest": saved} if saved.get("access_token") and (
            isinstance(user, dict) and user.get("is_anonymous") is True
        ) else {}
        return {"schema": 2, "active": "guest" if accounts else None,
                "prompt_next_start": False, "accounts": accounts}

    @property
    def mode(self):
        return self.data["active"]

    @property
    def session(self):
        return self.data["accounts"].get(self.mode, {})

    def saved_modes(self):
        return tuple(mode for mode in self.MODES if self.data["accounts"].get(mode))

    def resume_active(self):
        """Silently restore the last selected account, never create a new one.

        The saved JWT is verified against Supabase; an expired one is refreshed.
        A failed restore leaves both saved accounts available for explicit login.
        """
        if not self.url or not self.key:
            raise CloudAuthError("Supabase для DeiLaw не настроен.")
        with self.lock:
            mode = self.data["active"]
            choice_requested = getattr(self.store, "choice_requested", None)
            if (self.data["prompt_next_start"] or
                    (callable(choice_requested) and choice_requested()) or
                    mode not in self.MODES):
                return None
            if not self.data["accounts"].get(mode):
                return None
            return self._token_for(mode, verify=True)

    def request_account_selection(self):
        """Show the choice on the next launch without ending this session."""
        with self.lock:
            request_choice = getattr(self.store, "request_choice", None)
            if callable(request_choice):
                request_choice()
            else:
                self.data["prompt_next_start"] = True
                self.store.save(self.data)

    def _finish_explicit_selection(self, token):
        self.data["prompt_next_start"] = False
        self.store.save(self.data)
        clear_choice_request = getattr(self.store, "clear_choice_request", None)
        if callable(clear_choice_request):
            clear_choice_request()
        return token

    def _save_session(self, mode, payload):
        self.data["accounts"][mode] = payload
        self.data["active"] = mode
        self.store.save(self.data)

    def _request(self, path, payload):
        try:
            response = self.http.post(
                f"{self.url}/auth/v1/{path}",
                headers={
                    "apikey": self.key,
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=15,
            )
        except requests.RequestException as exc:
            raise CloudAuthError("Нет связи с авторизацией Cloud AI.") from exc
        if not response.ok:
            raise CloudAuthError(
                "Ошибка авторизации Supabase. Проверьте соединение и настройки входа."
            )
        try:
            data = response.json()
        except ValueError as exc:
            raise CloudAuthError("Сервер авторизации вернул неверный ответ.") from exc
        if not isinstance(data, dict) or not data.get("access_token") or not data.get("refresh_token"):
            raise CloudAuthError("Сервер авторизации не вернул токен пользователя.")
        return data

    def _user(self, token):
        try:
            response = self.http.get(
                f"{self.url}/auth/v1/user",
                headers={"apikey": self.key, "Authorization": f"Bearer {token}"},
                timeout=15,
            )
        except requests.RequestException as exc:
            raise CloudAuthError("Не удалось проверить сессию Supabase.") from exc
        if not response.ok:
            raise CloudAuthError("Сессия истекла. Войдите заново.")
        try:
            user = response.json()
        except ValueError as exc:
            raise CloudAuthError("Неверный ответ сервера авторизации.") from exc
        if not isinstance(user, dict) or not user.get("id"):
            raise CloudAuthError("Не удалось подтвердить пользователя.")
        return user

    @staticmethod
    def _validate_user(mode, user):
        if not isinstance(user, dict) or not user.get("id"):
            raise CloudAuthError("Сервер не подтвердил личность пользователя.")
        if mode == "guest":
            if user.get("is_anonymous") is not True:
                raise CloudAuthError("Это не гостевая сессия DeiLaw.")
            return
        if user.get("is_anonymous") is True:
            raise CloudAuthError("Вместо Discord получена гостевая сессия.")
        app_meta = user.get("app_metadata") or {}
        providers = app_meta.get("providers") or []
        if not isinstance(providers, list):
            providers = []
        identities = user.get("identities") or []
        linked = any(
            isinstance(item, dict) and item.get("provider") == "discord"
            for item in identities
        )
        if app_meta.get("provider") != "discord" and "discord" not in providers and not linked:
            raise CloudAuthError("Для этого входа необходим аккаунт Discord.")

    def _accept(self, mode, data, user=None):
        user = user or data.get("user")
        self._validate_user(mode, user)
        data = dict(data)
        data["user"] = user
        data["expires_at"] = int(time.time()) + int(data.get("expires_in") or 3600)
        self._save_session(mode, data)
        return str(data["access_token"])

    def _token_for(self, mode, *, create_guest=False, verify=False, captcha_token=None):
        session = self.data["accounts"].get(mode) or {}
        token = str(session.get("access_token") or "")
        expires = int(session.get("expires_at") or 0)
        if token and expires > int(time.time()) + 90:
            if verify:
                self._validate_user(mode, self._user(token))
            self.data["active"] = mode
            self.store.save(self.data)
            return token
        refresh = str(session.get("refresh_token") or "")
        if refresh:
            data = self._request("token?grant_type=refresh_token", {"refresh_token": refresh})
            return self._accept(mode, data, data.get("user") or session.get("user"))
        if mode == "guest" and create_guest:
            return self._accept("guest", self._request("signup", {
                "gotrue_meta_security": {"captcha_token": captcha_token},
            }))
        raise CloudAuthError("Нет действующей сессии. Выберите способ входа.")

    def select_guest(self):
        if not self.url or not self.key:
            raise CloudAuthError("Supabase для DeiLaw не настроен.")
        # A restored guest account must never be challenged again: CAPTCHA is
        # required only when Supabase actually creates a NEW anonymous user.
        with self.lock:
            if self.data["accounts"].get("guest"):
                try:
                    return self._finish_explicit_selection(
                        self._token_for("guest", verify=True)
                    )
                except CloudAuthError:
                    # If the existing token truly cannot be restored, the user
                    # may explicitly create a new guest account after CAPTCHA.
                    pass
        from captcha_config import TURNSTILE_SITE_KEY
        token = None
        if TURNSTILE_SITE_KEY:
            from turnstile_browser import get_turnstile_token, CaptchaChallengeError
            try:
                token = get_turnstile_token(TURNSTILE_SITE_KEY)
            except CaptchaChallengeError as exc:
                raise CloudAuthError(str(exc)) from exc
        with self.lock:
            return self._finish_explicit_selection(
                self._token_for("guest", create_guest=True, verify=True,
                                captcha_token=token)
            )

    def select_discord(self, *, cancel_event=None, browser_open=None, force=False):
        if not self.url or not self.key:
            raise CloudAuthError("Supabase для DeiLaw не настроен.")
        with self.lock:
            if not force and self.data["accounts"].get("discord"):
                try:
                    return self._finish_explicit_selection(
                        self._token_for("discord", verify=True)
                    )
                except CloudAuthError:
                    pass

        try:
            settings_response = self.http.get(
                f"{self.url}/auth/v1/settings",
                headers={"apikey": self.key}, timeout=10,
            )
            settings = settings_response.json() if settings_response.ok else {}
        except (requests.RequestException, ValueError) as exc:
            raise CloudAuthError("Не удалось проверить настройки Discord в Supabase.") from exc
        external = settings.get("external") if isinstance(settings, dict) else None
        if not isinstance(external, dict) or external.get("discord") is not True:
            raise CloudAuthError(
                "Вход Discord пока не подключён. Администратору нужно создать "
                "Discord Application и включить Discord в Supabase Auth."
            )

        from discord_oauth import complete_discord_pkce

        code, verifier = complete_discord_pkce(
            self.url, cancel_event=cancel_event, browser_open=browser_open
        )
        with self.lock:
            data = self._request("token?grant_type=pkce", {
                "auth_code": code, "code_verifier": verifier,
            })
            return self._finish_explicit_selection(self._accept("discord", data))

    def clear_active(self):
        with self.lock:
            mode = self.data["active"]
            if mode:
                self.data["accounts"].pop(mode, None)
            self.data["active"] = None
            self.store.save(self.data)

    def discard_saved_mode(self, mode):
        """Prevent another cached client from resurrecting a logged-out mode."""
        if mode not in self.MODES:
            return
        with self.lock:
            self.data["accounts"].pop(mode, None)
            if self.data["active"] == mode:
                self.data["active"] = None
            self.store.save(self.data)

    def sign_out_active(self):
        """Forget this PC's active account and revoke only this Auth session.

        A server/network failure must not keep a user logged in locally.
        Returns whether Supabase confirmed the session revocation.
        Other saved account modes are retained.
        """
        with self.lock:
            mode = self.data["active"]
            if mode not in self.MODES:
                return True
            current = self.data["accounts"].get(mode) or {}
            token = str(current.get("access_token") or "")
            self.data["accounts"].pop(mode, None)
            self.data["active"] = None
            self.data["prompt_next_start"] = False
            self.store.save(self.data)
            clear_choice_request = getattr(self.store, "clear_choice_request", None)
            if callable(clear_choice_request):
                clear_choice_request()

        if not token:
            return False
        try:
            response = self.http.post(
                f"{self.url}/auth/v1/logout?scope=local",
                headers={
                    "apikey": self.key,
                    "Authorization": f"Bearer {token}",
                },
                timeout=6,
            )
        except requests.RequestException:
            return False
        return bool(response.ok)

    def access_token(self):
        if not self.url or not self.key:
            raise CloudAuthError("Cloud AI не настроен.")
        with self.lock:
            mode = self.data["active"]
            if mode not in self.MODES:
                if not self.allow_implicit_guest:
                    raise CloudAuthError("Сначала войдите через Discord или как гость.")
                mode = "guest"
            return self._token_for(mode, create_guest=self.allow_implicit_guest)
