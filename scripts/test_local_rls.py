"""Integration regression checks for a LOCAL DeiLaw Supabase stack only.

Run after the local SQL fixture and hardening migration; see
docs/LOCAL_SECURITY_TEST.md. Never point this at the hosted production project.
"""

import argparse
import json
import secrets
import urllib.error
import urllib.parse
import urllib.request


LEGACY_ID = "deilaw-local-legacy"
LEGACY_SECRET = "deilaw-local-fixture-secret-only-2026"


def require_local_url(url):
    parsed = urllib.parse.urlsplit(url)
    if (parsed.scheme != "http" or parsed.hostname not in ("127.0.0.1", "localhost", "::1")
            or parsed.port != 54321 or parsed.username or parsed.password
            or parsed.path not in ("", "/") or parsed.query or parsed.fragment):
        raise ValueError("Тест разрешён только на http://127.0.0.1:54321")
    return url.rstrip("/")


class ApiFailure(Exception):
    def __init__(self, status, body):
        super().__init__(f"HTTP {status}: {str(body)[:180]}")
        self.status = status
        self.body = str(body)


class NoRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        raise ValueError("Локальный тест не должен переходить по перенаправлениям")


class LocalSupabase:
    def __init__(self, url, key):
        self.url = require_local_url(url)
        self.key = key.strip()
        if not self.key:
            raise ValueError("Укажите локальный publishable/anon key из supabase status")
        self.opener = urllib.request.build_opener(NoRedirects)

    def request(self, path, *, method="GET", token=None, body=None, query=None,
                extra_headers=None):
        target = self.url + path
        if query:
            target += "?" + urllib.parse.urlencode(query)
        headers = {"apikey": self.key, "Content-Type": "application/json",
                   "Accept": "application/json", "Prefer": "return=representation"}
        if token:
            headers["Authorization"] = "Bearer " + token
        if extra_headers:
            headers.update(extra_headers)
        payload = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(target, headers=headers, data=payload, method=method)
        try:
            with self.opener.open(req, timeout=15) as response:
                raw = response.read()
                return json.loads(raw) if raw else None
        except urllib.error.HTTPError as error:
            message = error.read().decode("utf-8", "replace")
            raise ApiFailure(error.code, message) from None

    def signup(self, suffix):
        name = secrets.token_hex(8)
        response = self.request("/auth/v1/signup", method="POST", body={
            "email": f"deilaw-{suffix}-{name}@example.invalid",
            "password": "LocalTest!" + secrets.token_urlsafe(20),
        })
        token = (response or {}).get("access_token")
        if not token:
            raise RuntimeError("Нет тестового JWT: отключите подтверждение email в локальном Auth")
        return token, response["user"]["id"]


def check(condition, description):
    if not condition:
        raise AssertionError(description)
    print("[OK] " + description)


def blocked(call, description, *, trigger_error=None):
    try:
        result = call()
    except ApiFailure as error:
        if error.status in (401, 403) or (
            trigger_error is not None and error.status == 400
            and trigger_error in error.body
        ):
            print("[OK] " + description)
            return
        raise
    if result in (None, []):
        print("[OK] " + description)
        return
    raise AssertionError(description + ": запрет не сработал")


def run(api):
    user_a, uid_a = api.signup("a")
    user_b, uid_b = api.signup("b")
    print("Созданы две случайные локальные тестовые учётные записи")

    # Legacy proof: neither guessing an ID nor knowing the secret of another
    # account after its one-time claim can transfer ownership.
    wrong = api.request("/rest/v1/rpc/deilaw_claim_legacy_ownership",
                        method="POST", token=user_b, body={
                            "p_installation_id": LEGACY_ID,
                            "p_installation_secret": "incorrect-local-fixture-secret-2026",
                        })
    check(wrong.get("reviews") == 0 and wrong.get("reports") == 0,
          "Чужой legacy ID без секрета не присваивает данные")
    claimed = api.request("/rest/v1/rpc/deilaw_claim_legacy_ownership",
                          method="POST", token=user_a, body={
                              "p_installation_id": LEGACY_ID,
                              "p_installation_secret": LEGACY_SECRET,
                          })
    check(claimed.get("reviews") == 1 and claimed.get("reports") == 1,
          "Старые данные переходят только владельцу с секретом")
    stolen = api.request("/rest/v1/rpc/deilaw_claim_legacy_ownership",
                         method="POST", token=user_b, body={
                             "p_installation_id": LEGACY_ID,
                             "p_installation_secret": LEGACY_SECRET,
                         })
    check(stolen.get("reviews") == 0 and stolen.get("reports") == 0,
          "Другой JWT не может повторно присвоить старые данные")

    legacy_review = api.request("/rest/v1/reviews", token=user_a,
                                query={"select": "id,approved,owner_uid",
                                       "installation_id": "eq." + LEGACY_ID})
    check(len(legacy_review) == 1 and legacy_review[0]["owner_uid"] == uid_a
          and legacy_review[0]["approved"] is False,
          "Старый отзыв скрыт до модерации")
    blocked(lambda: api.request("/rest/v1/reviews", token=user_b,
                                query={"select": "id", "installation_id": "eq." + LEGACY_ID}),
            "Второй пользователь не видит чужой отзыв")
    blocked(lambda: api.request("/rest/v1/bug_reports", token=user_b,
                                query={"select": "id", "installation_id": "eq." + LEGACY_ID},
                                extra_headers={"x-deilaw-installation-id": LEGACY_ID,
                                               "x-deilaw-installation-secret": LEGACY_SECRET}),
            "Поддельные заголовки установки не обходят RLS")

    anon_public = api.request("/rest/v1/deilaw_public_reviews",
                              query={"select": "*"})
    check(anon_public == [], "Публично не видны отзывы до модерации")
    blocked(lambda: api.request("/rest/v1/reviews", query={"select": "*"}),
            "Анонимный доступ к приватной таблице отзывов закрыт")

    label = secrets.token_hex(8)
    reviews = api.request("/rest/v1/reviews", method="POST", token=user_a,
                          body={"installation_id": "local-qa-" + label,
                                "installation_secret_hash": "f" * 64,
                                "device_id": "a" * 64,
                                "device_secret_hash": "b" * 64,
                                "author_name": "Test A", "rating": 5,
                                "review_text": "Local RLS test", "app_version": "test",
                                "approved": True, "helpful_count": 99})
    review_id = reviews[0]["id"]
    check(reviews[0]["approved"] is False and reviews[0]["helpful_count"] == 0,
          "Клиент не может публиковать отзыв или накручивать голоса")
    blocked(lambda: api.request("/rest/v1/reviews", method="PATCH", token=user_a,
                                query={"id": "eq." + review_id}, body={"approved": True}),
            "Владелец не меняет модерацию существующего отзыва",
            trigger_error="Review owner cannot modify protected fields")
    blocked(lambda: api.request("/rest/v1/reviews", method="PATCH", token=user_b,
                                query={"id": "eq." + review_id}, body={"review_text": "stolen"}),
            "Другой пользователь не может редактировать отзыв")

    reports = api.request("/rest/v1/bug_reports", method="POST", token=user_a,
                          body={"installation_id": "local-qa-" + label,
                                "installation_secret_hash": "f" * 64,
                                "category": "QA", "title": "Private test report",
                                "description": "Sensitive test description", "app_version": "test"})
    report_id = reports[0]["id"]
    blocked(lambda: api.request("/rest/v1/bug_reports", token=user_b,
                                query={"select": "id,description", "id": "eq." + report_id}),
            "Другой пользователь не видит чужой репорт")
    blocked(lambda: api.request("/rest/v1/bug_report_messages", method="POST",
                                token=user_b, body={"report_id": report_id,
                                                    "sender": "user", "message": "Intrusion"}),
            "Другой пользователь не может писать в чужой репорт")
    messages = api.request("/rest/v1/bug_report_messages", method="POST",
                           token=user_a, body={"report_id": report_id,
                                               "sender": "user", "message": "My message"})
    check(len(messages) == 1 and messages[0]["owner_uid"] == uid_a,
          "Владелец может написать в свой репорт")
    blocked(lambda: api.request("/rest/v1/bug_report_messages", token=user_b,
                                query={"select": "id", "report_id": "eq." + report_id}),
            "Другой пользователь не читает переписку")

    suggested = api.request("/rest/v1/suggestions", method="POST", token=user_a,
                            body={"installation_id": "local-qa-" + label,
                                  "installation_secret_hash": "f" * 64,
                                  "author_name": "Test A", "title": "Safe suggestion",
                                  "suggestion_text": "Only I should see this text"})
    suggestion_id = suggested[0]["id"]
    blocked(lambda: api.request("/rest/v1/suggestions", token=user_b,
                                query={"select": "id", "id": "eq." + suggestion_id}),
            "Другой пользователь не читает предложения")
    blocked(lambda: api.request("/rest/v1/suggestions", method="PATCH", token=user_a,
                                query={"id": "eq." + suggestion_id},
                                body={"status": "fixed"}),
            "Пользователь не меняет статус предложений",
            trigger_error="Only developers can update suggestions")
    check(uid_a != uid_b, "JWT двух пользователей действительно различаются")
    print("Локальная RLS-проверка завершена успешно")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:54321")
    parser.add_argument("--key",
                        help="Только локальный Publishable/anon API key из supabase status")
    args = parser.parse_args()
    # Validate URL before asking the user for a key, so a typo cannot send
    # them down the wrong setup path.
    require_local_url(args.url)
    key = args.key if args.key is not None else input(
        "Вставьте локальный Publishable/anon key (из supabase status): "
    )
    run(LocalSupabase(args.url, key))


if __name__ == "__main__":
    main()
