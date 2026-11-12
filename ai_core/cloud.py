from __future__ import annotations

from typing import Iterable

import requests

from app_version import APP_VERSION
from cloud_auth import AnonymousSupabaseSession, CloudAuthError, WindowsTokenStore
from community_client import CommunityIdentity, SUPABASE_PUBLISHABLE_KEY, SUPABASE_URL


class CloudAIError(RuntimeError):
    pass


class CloudAIClient:
    """Client for DeiLaw Cloud AI with server-side law retrieval.

    The desktop client sends the user's question and short chat history only.
    Supabase searches the canonical server law corpus and returns the sources
    used for grounding together with the raw JSON answer.
    """

    FUNCTION_NAME = "deilaw-ai"

    def __init__(
        self,
        *,
        url: str = SUPABASE_URL,
        publishable_key: str = SUPABASE_PUBLISHABLE_KEY,
        identity: CommunityIdentity | None = None,
        timeout: int = 90,
    ):
        self.url = str(url or "").rstrip("/")
        self.publishable_key = str(publishable_key or "").strip()
        self.identity = identity or CommunityIdentity("data/community_identity.json")
        self.auth = AnonymousSupabaseSession(
            self.url,
            self.publishable_key,
            store=WindowsTokenStore(self.identity.path.parent / "cloud_auth.bin"),
        )
        self.timeout = max(20, int(timeout))

    @property
    def function_url(self) -> str:
        return f"{self.url}/functions/v1/{self.FUNCTION_NAME}"

    def _headers(self) -> dict[str, str]:
        return {
            "apikey": self.publishable_key,
            "Authorization": f"Bearer {self.auth.access_token()}",
            "Accept": "application/json",
            "Content-Type": "application/json",
            "X-DeiLaw-App-Version": APP_VERSION,
        }

    @staticmethod
    def _response_error(response: requests.Response) -> str:
        try:
            payload = response.json()
            if isinstance(payload, dict):
                message = payload.get("error") or payload.get("message")
                if message:
                    return str(message)
        except Exception:
            pass
        return (response.text or "").strip() or f"HTTP {response.status_code}"

    @staticmethod
    def _prepare_history(history: Iterable[dict] | None) -> list[dict]:
        result: list[dict] = []
        for item in list(history or [])[-6:]:
            role = str(item.get("role") or "").strip().lower()
            content = str(item.get("content") or "").strip()
            if role not in {"user", "assistant"} or not content:
                continue
            result.append({"role": role, "content": content[:3000]})
        return result

    def health(self, timeout: int = 6) -> dict:
        if not self.url or not self.publishable_key:
            return {"ok": False, "error": "Cloud AI не настроен."}
        try:
            response = requests.get(
                self.function_url,
                headers=self._headers(),
                params={"health": "1"},
                timeout=max(2, int(timeout)),
            )
        except CloudAuthError as exc:
            return {"ok": False, "error": str(exc)}
        except requests.RequestException as exc:
            return {"ok": False, "error": f"Нет связи с Cloud AI: {exc}"}
        try:
            payload = response.json()
        except Exception:
            payload = {}
        if not 200 <= response.status_code < 300:
            if isinstance(payload, dict) and payload:
                return {"ok": False, **payload}
            return {"ok": False, "error": self._response_error(response)}
        return payload if isinstance(payload, dict) else {"ok": True}

    def analyze(
        self,
        situation: str,
        candidates=None,  # retained for compatibility; server ignores local sources
        history=None,
        query_mode="general",
        exact_refs=None,
    ) -> tuple[str, list[dict]]:
        situation = str(situation or "").strip()
        if not situation:
            raise CloudAIError("Сначала опишите RP-ситуацию.")
        if len(situation) > 5000:
            raise CloudAIError("Сообщение слишком длинное. Сократите его до 5000 символов.")

        payload = {
            "situation": situation,
            "history": self._prepare_history(history),
            "query_mode": str(query_mode or "general"),
            "exact_refs": list(exact_refs or [])[:8],
            "app_version": APP_VERSION,
        }

        try:
            response = requests.post(
                self.function_url,
                headers=self._headers(),
                json=payload,
                timeout=self.timeout,
            )
        except CloudAuthError as exc:
            raise CloudAIError(str(exc)) from exc
        except requests.Timeout as exc:
            raise CloudAIError(
                "Cloud AI слишком долго отвечает. Проверьте интернет и повторите запрос."
            ) from exc
        except requests.ConnectionError as exc:
            raise CloudAIError(
                "Нет соединения с DeiLaw Cloud AI. Проверьте интернет и повторите запрос."
            ) from exc
        except requests.RequestException as exc:
            raise CloudAIError(f"Ошибка соединения с Cloud AI: {exc}") from exc

        if not 200 <= response.status_code < 300:
            raise CloudAIError(self._response_error(response))

        try:
            data = response.json()
        except Exception as exc:
            raise CloudAIError("Cloud AI вернул некорректный ответ.") from exc

        if not isinstance(data, dict):
            raise CloudAIError("Cloud AI вернул некорректный ответ.")

        answer = str(data.get("answer") or "").strip()
        sources = data.get("sources") if isinstance(data.get("sources"), list) else []
        sources = [dict(x) for x in sources if isinstance(x, dict)]
        if not answer:
            raise CloudAIError("Cloud AI вернул пустой ответ.")
        return answer, sources
