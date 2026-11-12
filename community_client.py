import base64
import hashlib
import mimetypes
import json
import secrets
import threading
import sys
import uuid
from pathlib import Path

try:
    import winreg
except ImportError:
    winreg = None

import requests
from cloud_auth import AnonymousSupabaseSession, CloudAuthError, WindowsTokenStore


SUPABASE_URL = "https://ntizjwncrbokebjsfwgu.supabase.co"
SUPABASE_PUBLISHABLE_KEY = "sb_publishable_Kka_1BoaH6eBCwsz4KcL5w_E4ubiWbw"


class CommunityError(RuntimeError):
    pass


class CommunityIdentity:
    """Anonymous install + Windows-device identity for community features.

    Review limiting is tied to a one-way hash derived locally from Windows
    MachineGuid. The raw MachineGuid, IP address and MAC address are never sent
    to Supabase. Bug reports still use the per-installation identity so backup /
    restore keeps access to the user's own report conversations.
    """

    DEVICE_ID_SALT = "DeiLaw/community-device-id/v1"
    DEVICE_SECRET_SALT = "DeiLaw/community-device-secret/v1"

    def __init__(self, path="data/community_identity.json"):
        self.path = Path(path)
        payload = self._load_or_create()
        self.installation_id = payload["installation_id"]
        self.installation_secret = payload["installation_secret"]
        self._device_material = self._read_device_material()

    def _load_or_create(self):
        protected = WindowsTokenStore(self.path.with_suffix(".bin"))
        if sys.platform == "win32":
            saved = protected.load()
            if (
                isinstance(saved, dict)
                and saved.get("installation_id")
                and len(str(saved.get("installation_secret") or "")) >= 20
            ):
                return saved
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            installation_id = str(payload.get("installation_id") or "").strip()
            installation_secret = str(
                payload.get("installation_secret") or ""
            ).strip()
            if installation_id and len(installation_secret) >= 20:
                existing = {
                    "installation_id": installation_id,
                    "installation_secret": installation_secret,
                }
                if sys.platform == "win32":
                    # Migrate plaintext identity to Windows DPAPI without
                    # changing credentials used by existing reports.
                    protected.save(existing)
                    self.path.unlink(missing_ok=True)
                return existing
        except Exception:
            pass

        payload = {
            "installation_id": str(uuid.uuid4()),
            "installation_secret": secrets.token_urlsafe(36),
        }
        if sys.platform == "win32":
            protected.save(payload)
        else:
            # Non-Windows developer/test compatibility only.
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        return payload

    @staticmethod
    def _sha256(value):
        return hashlib.sha256(
            str(value or "").encode("utf-8")
        ).hexdigest()

    def _read_device_material(self):
        """Return a stable Windows-local machine identifier.

        MachineGuid is read locally and immediately hashed before it leaves
        this object. On non-Windows/test environments we deliberately fall back
        to the installation identity rather than collecting network identifiers.
        """
        if sys.platform == "win32" and winreg is not None:
            access_modes = [winreg.KEY_READ]
            wow64 = getattr(winreg, "KEY_WOW64_64KEY", 0)
            if wow64:
                access_modes.insert(0, winreg.KEY_READ | wow64)

            for access in access_modes:
                try:
                    with winreg.OpenKey(
                        winreg.HKEY_LOCAL_MACHINE,
                        r"SOFTWARE\Microsoft\Cryptography",
                        0,
                        access,
                    ) as key:
                        value, _ = winreg.QueryValueEx(key, "MachineGuid")
                    value = str(value or "").strip().lower()
                    if value:
                        return value
                except OSError:
                    continue
                except Exception:
                    break

        return f"install:{self.installation_id}"

    @property
    def secret_hash(self):
        return self._sha256(self.installation_secret)

    @property
    def device_id(self):
        # Only this salted one-way digest is sent to the server.
        return self._sha256(
            f"{self.DEVICE_ID_SALT}|{self._device_material}"
        )

    @property
    def device_secret(self):
        # A second independent digest proves ownership of the same device id
        # without exposing the raw Windows MachineGuid.
        return self._sha256(
            f"{self.DEVICE_SECRET_SALT}|{self._device_material}"
        )

    @property
    def device_secret_hash(self):
        return self._sha256(self.device_secret)


class SupabaseCommunityClient:
    """Small REST client for the public DeiLaw Supabase backend."""

    def __init__(
        self,
        url=SUPABASE_URL,
        publishable_key=SUPABASE_PUBLISHABLE_KEY,
        identity=None,
        timeout=12,
    ):
        self.url = str(url or "").rstrip("/")
        self.publishable_key = str(publishable_key or "").strip()
        self.identity = identity or CommunityIdentity()
        self.timeout = max(3, int(timeout))
        self.auth = AnonymousSupabaseSession(
            self.url, self.publishable_key,
            store=WindowsTokenStore(self.identity.path.parent / "cloud_auth.bin"),
        )
        self._legacy_claim_done_for = None
        self._legacy_claim_lock = threading.Lock()

    def _headers(self, prefer=None):
        headers = {
            "apikey": self.publishable_key,
            "Authorization": f"Bearer {self.auth.access_token()}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        if prefer:
            headers["Prefer"] = prefer
        return headers

    def _owner_filter(self):
        """Filter the user-facing lists by verified Supabase account UUID.

        An admin's RLS policies can see other users' rows, so the UI must
        explicitly restrict *my* lists rather than rely on a permissive
        admin SELECT policy or the current PC's installation ID.
        """
        try:
            self.auth.access_token()
        except CloudAuthError as exc:
            raise CommunityError(str(exc)) from exc
        user = self.auth.session.get("user") or {}
        uid = str(user.get("id") or "").strip()
        if not uid:
            raise CommunityError("Не удалось определить аккаунт DeiLaw. Войдите заново.")
        return f"eq.{uid}"

    def claim_legacy_feedback(self):
        """Automatically import previous install-owned records after Discord login.

        The server verifies the original random installation secret against a
        stored hash and ensures the token has an actual Discord identity. Guest
        sessions NEVER claim legacy data. Run this in a background worker.
        """
        empty = {"reviews": 0, "reports": 0, "messages": 0,
                 "suggestions": 0, "review_conflicts": 0}
        if self.auth.mode != "discord":
            return dict(empty)
        with self._legacy_claim_lock:
            # Recheck the authenticated account each time, so switching from a
            # guest or between Discord accounts cannot reuse stale claim state.
            try:
                headers = self._headers()
                user = self.auth.session.get("user") or {}
                uid = str(user.get("id") or "").strip()
            except CloudAuthError as exc:
                raise CommunityError(str(exc)) from exc
            if not uid:
                raise CommunityError("Не удалось определить Discord-аккаунт.")
            if self._legacy_claim_done_for == uid:
                return dict(empty)
            try:
                response = requests.post(
                    f"{self.url}/rest/v1/rpc/deilaw_claim_legacy_ownership",
                    headers=headers,
                    json={
                        "p_installation_id": self.identity.installation_id,
                        "p_installation_secret": self.identity.installation_secret,
                    },
                    timeout=self.timeout,
                )
            except requests.RequestException as exc:
                raise CommunityError("Не удалось восстановить старые отзывы и репорты.") from exc
            if not response.ok:
                raise CommunityError("Не удалось привязать старые данные: " + self._error_message(response))
            try:
                result = response.json()
            except ValueError as exc:
                raise CommunityError("Сервер вернул некорректный результат переноса.") from exc
            if not isinstance(result, dict):
                raise CommunityError("Сервер вернул некорректный результат переноса.")
            self._legacy_claim_done_for = uid
            return {key: max(0, int(result.get(key) or 0)) for key in empty}

    def _ensure_legacy_claim(self):
        """Safety net for requests made before the background claim finishes."""
        return self.claim_legacy_feedback()

    @staticmethod
    def _error_message(response):
        try:
            payload = response.json()
            if isinstance(payload, dict):
                message = (
                    payload.get("message")
                    or payload.get("hint")
                    or payload.get("details")
                    or payload.get("error")
                )
                if message:
                    return str(message)
        except Exception:
            pass
        return (response.text or "").strip() or f"HTTP {response.status_code}"

    def _request(
        self,
        method,
        table,
        *,
        params=None,
        payload=None,
        prefer=None,
    ):
        if not self.url or not self.publishable_key:
            raise CommunityError("Supabase для DeiLaw не настроен.")

        try:
            if table != "deilaw_public_reviews":
                self._ensure_legacy_claim()
        except CloudAuthError as exc:
            raise CommunityError(str(exc)) from exc
        url = f"{self.url}/rest/v1/{table.lstrip('/')}"
        try:
            response = requests.request(
                method,
                url,
                headers=self._headers(prefer),
                params=params,
                json=payload,
                timeout=self.timeout,
            )
        except CloudAuthError as exc:
            raise CommunityError(str(exc)) from exc
        except requests.RequestException as exc:
            raise CommunityError(
                f"Не удалось связаться с сервером DeiLaw: {exc}"
            ) from exc

        if not 200 <= response.status_code < 300:
            raise CommunityError(self._error_message(response))

        if response.status_code == 204 or not response.content:
            return None

        try:
            return response.json()
        except Exception as exc:
            raise CommunityError(
                "Сервер DeiLaw вернул некорректный ответ."
            ) from exc

    def _function_headers(self, content_type=None):
        headers = {
            "apikey": self.publishable_key,
            "Authorization": f"Bearer {self.auth.access_token()}",
            "Accept": "application/json",
        }
        if content_type:
            headers["Content-Type"] = content_type
        return headers

    def _attachment_function_request(
        self,
        method,
        *,
        action,
        params=None,
        data=None,
        headers=None,
        expect_binary=False,
    ):
        if not self.url or not self.publishable_key:
            raise CommunityError("Supabase для DeiLaw не настроен.")

        query = {"action": action}
        query.update(dict(params or {}))
        try:
            request_headers = self._function_headers()
        except CloudAuthError as exc:
            raise CommunityError(str(exc)) from exc
        request_headers.update(dict(headers or {}))

        try:
            response = requests.request(
                method,
                f"{self.url}/functions/v1/deilaw-report-attachments",
                params=query,
                headers=request_headers,
                data=data,
                timeout=max(self.timeout, 30),
            )
        except requests.RequestException as exc:
            raise CommunityError(
                f"Не удалось связаться с сервером вложений DeiLaw: {exc}"
            ) from exc

        if not 200 <= response.status_code < 300:
            raise CommunityError(self._error_message(response))

        if expect_binary:
            return response
        if not response.content:
            return {}
        try:
            return response.json()
        except Exception as exc:
            raise CommunityError("Сервер вложений DeiLaw вернул некорректный ответ.") from exc

    @staticmethod
    def _attachment_filename_header(filename):
        raw = str(filename or "").encode("utf-8")
        return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")

    def upload_report_attachment(self, report_id, file_path):
        report_id = str(report_id or "").strip()
        path = Path(file_path)
        if not report_id:
            raise CommunityError("Не указан репорт для вложения.")
        if not path.is_file():
            raise CommunityError(f"Файл не найден: {path}")

        allowed = {".png", ".jpg", ".jpeg", ".webp", ".txt", ".log"}
        suffix = path.suffix.lower()
        if suffix not in allowed:
            raise CommunityError(
                "Поддерживаются PNG, JPG, WEBP, TXT и LOG."
            )

        size = path.stat().st_size
        if size <= 0:
            raise CommunityError("Нельзя прикрепить пустой файл.")
        if size > 10 * 1024 * 1024:
            raise CommunityError("Размер одного вложения не должен превышать 10 МБ.")

        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        payload = self._attachment_function_request(
            "POST",
            action="upload",
            params={"report_id": report_id},
            data=path.read_bytes(),
            headers={
                "Content-Type": content_type,
                "X-File-Name-B64": self._attachment_filename_header(path.name),
            },
        )
        return dict(payload.get("attachment") or {})

    def fetch_report_attachments(self, report_id):
        payload = self._attachment_function_request(
            "GET",
            action="list",
            params={"report_id": str(report_id or "").strip()},
        )
        rows = payload.get("attachments") if isinstance(payload, dict) else []
        return rows if isinstance(rows, list) else []

    def download_report_attachment(self, attachment_id):
        response = self._attachment_function_request(
            "GET",
            action="download",
            params={"attachment_id": str(attachment_id or "").strip()},
            expect_binary=True,
        )
        filename = "attachment"
        encoded = str(response.headers.get("X-File-Name-B64") or "").strip()
        if encoded:
            try:
                encoded += "=" * ((4 - len(encoded) % 4) % 4)
                filename = base64.urlsafe_b64decode(encoded.encode("ascii")).decode("utf-8")
            except Exception:
                pass
        return {
            "filename": filename,
            "content_type": response.headers.get("Content-Type") or "application/octet-stream",
            "data": response.content,
        }

    def submit_bug_report_with_attachments(self, report, attachment_paths=None):
        row = self.submit_bug_report(report)
        report_id = str((row or {}).get("id") or "").strip()
        paths = [str(Path(item)) for item in list(attachment_paths or [])]
        uploaded = []
        errors = []

        if report_id:
            for file_path in paths[:5]:
                try:
                    uploaded.append(self.upload_report_attachment(report_id, file_path))
                except CommunityError as exc:
                    errors.append(f"{Path(file_path).name}: {exc}")

        result = dict(row or {})
        result["_uploaded_attachments"] = uploaded
        result["_attachment_upload_errors"] = errors
        return result

    def fetch_reviews(self, limit=300):
        rows = self._request(
            "GET",
            "deilaw_public_reviews",
            params={
                "select": (
                    "id,author_name,rating,review_text,app_version,"
                    "helpful_count,developer_reply,developer_reply_at,"
                    "created_at,updated_at"
                ),
                "order": "created_at.desc",
                "limit": str(max(1, min(500, int(limit)))),
            },
        )
        return rows if isinstance(rows, list) else []

    def require_discord_feedback(self):
        """Only verified Discord sessions can submit public feedback/reports."""
        if self.auth.mode != "discord":
            raise CommunityError("Для отправки отзыва или репорта войдите через Discord.")
        # Auth must verify token and refresh the user when needed.
        try:
            self.auth.access_token()
        except CloudAuthError as exc:
            raise CommunityError(str(exc)) from exc
        if self.auth.mode != "discord":
            raise CommunityError("Необходим действующий вход через Discord.")

    def discord_display_name(self):
        """UI-only display; the DB derives its own authoritative Discord name."""
        if self.auth.mode != "discord":
            return "Гость"
        user = self.auth.session.get("user") or {}
        for identity in user.get("identities") or []:
            if isinstance(identity, dict) and identity.get("provider") == "discord":
                info = identity.get("identity_data") or {}
                for key in ("full_name", "name", "user_name"):
                    value = " ".join(str(info.get(key) or "").split())
                    if value:
                        return value[:40]
        info = user.get("user_metadata") or {}
        for key in ("full_name", "name", "user_name"):
            value = " ".join(str(info.get(key) or "").split())
            if value:
                return value[:40]
        return "Discord"

    def submit_review(self, *, rating, review_text, app_version):
        self.require_discord_feedback()
        review_text = str(review_text or "").strip()
        rating = int(rating)
        if not 1 <= rating <= 5:
            raise CommunityError("Поставьте оценку от 1 до 5 звёзд.")
        if not 3 <= len(review_text) <= 2000:
            raise CommunityError("Отзыв должен содержать от 3 до 2000 символов.")

        # Identity and name MUST be derived from auth.identities by the DB.
        # Do not send a client-editable author_name/device_id/installation_id.
        data = {
            "rating": rating,
            "review_text": review_text,
            "app_version": str(app_version or "")[:40],
        }
        own_reviews = self._request(
            "GET", "reviews",
            params={"owner_uid": self._owner_filter(), "select": "id", "limit": "1"},
        )
        if isinstance(own_reviews, list) and own_reviews:
            self._request(
                "PATCH", "reviews",
                params={"id": f"eq.{own_reviews[0]['id']}"},
                payload=data,
                prefer="return=minimal",
            )
            return
        self._request("POST", "reviews", payload=data, prefer="return=minimal")

    def submit_suggestion(
        self,
        *,
        author_name,
        category,
        title,
        suggestion_text,
        app_version,
    ):
        author_name = " ".join(str(author_name or "").split()).strip()
        category = " ".join(str(category or "Функционал").split()).strip()
        title = " ".join(str(title or "").split()).strip()
        suggestion_text = str(suggestion_text or "").strip()

        if not 1 <= len(author_name) <= 40:
            raise CommunityError("Ник должен содержать от 1 до 40 символов.")
        if not 1 <= len(category) <= 50:
            raise CommunityError("Некорректная категория предложения.")
        if not 3 <= len(title) <= 150:
            raise CommunityError("Название должно содержать от 3 до 150 символов.")
        if not 5 <= len(suggestion_text) <= 5000:
            raise CommunityError("Описание предложения должно содержать от 5 до 5000 символов.")

        rows = self._request(
            "POST",
            "suggestions",
            payload={
                "installation_id": self.identity.installation_id,
                "installation_secret_hash": self.identity.secret_hash,
                "author_name": author_name,
                "category": category,
                "title": title,
                "suggestion_text": suggestion_text,
                "app_version": str(app_version or "")[:80],
                "status": "new",
            },
            prefer="return=representation",
        )
        if isinstance(rows, list) and rows:
            return rows[0]
        return None

    def fetch_my_suggestions(self, limit=100):
        rows = self._request(
            "GET",
            "suggestions",
            params={
                "owner_uid": self._owner_filter(),
                "select": (
                    "id,suggestion_number,author_name,category,title,"
                    "suggestion_text,app_version,status,developer_reply,"
                    "developer_reply_at,created_at,updated_at"
                ),
                "order": "created_at.desc",
                "limit": str(max(1, min(300, int(limit)))),
            },
        )
        return rows if isinstance(rows, list) else []

    def submit_bug_report(self, report):
        self.require_discord_feedback()
        payload = {
            "category": str(report.get("category") or "Другое")[:50],
            "title": str(report.get("title") or "").strip()[:150],
            "description": str(report.get("description") or "").strip()[:5000],
            "reproduce_steps": str(
                report.get("reproduce_steps") or ""
            ).strip()[:5000],
            "expected_result": str(
                report.get("expected_result") or ""
            ).strip()[:3000],
            "app_version": str(report.get("app_version") or "")[:40],
            "windows_version": str(
                report.get("windows_version") or ""
            )[:250],
            "theme": str(report.get("theme") or "")[:100],
            "hotkey_search": str(
                report.get("hotkey_search") or ""
            )[:100],
            "hotkey_memo": str(
                report.get("hotkey_memo") or ""
            )[:100],
            "hotkey_calculator": str(
                report.get("hotkey_calculator") or ""
            )[:100],
            "update_channel": str(
                report.get("update_channel") or ""
            )[:40],
            "ai_status": str(report.get("ai_status") or "")[:1000],
            "logs": str(report.get("logs") or "")[:20000],
        }

        if len(payload["title"]) < 3:
            raise CommunityError("Коротко укажите название проблемы.")
        if len(payload["description"]) < 3:
            raise CommunityError("Опишите, что произошло.")

        inserted = self._request(
            "POST", "bug_reports", payload=payload,
            prefer="return=representation",
        )

        row = (
            inserted[0]
            if isinstance(inserted, list) and inserted
            else {}
        )
        report_id = str(row.get("id") or "").strip()

        # Seed the conversation with the user's original description.
        # If an older Supabase schema does not yet have the messages table,
        # the report itself still remains successfully submitted.
        if report_id:
            initial_message = payload["description"]
            try:
                self.send_report_message(
                    report_id,
                    initial_message,
                )
            except CommunityError:
                pass

        return row

    def fetch_my_bug_reports(self, limit=100):
        rows = self._request(
            "GET",
            "bug_reports",
            params={
                "owner_uid": self._owner_filter(),
                "select": (
                    "id,report_number,category,title,description,"
                    "reproduce_steps,expected_result,app_version,status,"
                    "developer_reply,created_at,updated_at"
                ),
                "order": "updated_at.desc",
                "limit": str(max(1, min(200, int(limit)))),
            },
        )
        return rows if isinstance(rows, list) else []

    def fetch_report_messages(self, report_id, limit=300):
        report_id = str(report_id or "").strip()
        if not report_id:
            return []

        rows = self._request(
            "GET",
            "bug_report_messages",
            params={
                "report_id": f"eq.{report_id}",
                "select": (
                    "id,report_id,sender,message,created_at"
                ),
                "order": "created_at.asc",
                "limit": str(max(1, min(500, int(limit)))),
            },
        )
        return rows if isinstance(rows, list) else []


    def fetch_developer_report_messages(self, limit=120):
        """Return recent developer replies owned by the current account.

        The explicit owner filter also avoids showing every user's replies
        when a developer signs into the user-facing DeiLaw app.
        """
        rows = self._request(
            "GET",
            "bug_report_messages",
            params={
                "sender": "eq.developer",
                "owner_uid": self._owner_filter(),
                "select": (
                    "id,report_id,sender,message,created_at"
                ),
                "order": "created_at.desc",
                "limit": str(max(1, min(300, int(limit)))),
            },
        )
        return rows if isinstance(rows, list) else []

    def send_report_message(self, report_id, message):
        report_id = str(report_id or "").strip()
        message = str(message or "").strip()

        if not report_id:
            raise CommunityError("Не выбран репорт.")
        if not 1 <= len(message) <= 4000:
            raise CommunityError(
                "Сообщение должно содержать от 1 до 4000 символов."
            )

        payload = {
            "report_id": report_id,
            "sender": "user",
            "message": message,
        }

        rows = self._request(
            "POST",
            "bug_report_messages",
            payload=payload,
            prefer="return=representation",
        )
        if isinstance(rows, list) and rows:
            return rows[0]
        return None
