import base64
import json
import tempfile
import sys
import socket
import threading
import types
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

try:
    import requests
except ImportError:
    # The source-verification environment does not install desktop deps.
    requests = types.ModuleType("requests")
    requests.RequestException = type("RequestException", (Exception,), {})
    requests.Timeout = type("Timeout", (requests.RequestException,), {})
    requests.ConnectionError = type("ConnectionError", (requests.RequestException,), {})
    requests.Response = object
    requests.post = lambda *args, **kwargs: None
    requests.get = lambda *args, **kwargs: None
    sys.modules["requests"] = requests

from ai_core.cloud import CloudAIClient
from cloud_auth import (
    AnonymousSupabaseSession, CloudAuthError, WindowsTokenStore,
    restart_deilaw_for_login_choice,
)
from community_client import SupabaseCommunityClient
from discord_oauth import authorization_url, new_pkce_pair, DISCORD_REDIRECT_URL
import discord_oauth
from update_trust import UntrustedUpdateError, signed_manifest_bytes, verify_manifest
import update_trust
from user_state import BackupManager
import database


class InMemoryTokenStore:
    def __init__(self):
        self.value = {}

    def load(self):
        return dict(self.value)

    def save(self, data):
        self.value = dict(data)


class FakeResponse:
    ok = True
    status_code = 200
    text = ""

    def __init__(self, payload):
        self.payload = payload

    def json(self):
        return self.payload


class SecurityContractTests(unittest.TestCase):
    def test_cloud_ai_uses_jwt_without_device_identifiers(self):
        identity = SimpleNamespace(
            path=Path("data/community_identity.json"),
            installation_id="private-install-id",
            device_id="private-device-id",
        )
        client = CloudAIClient(
            url="https://example.supabase.co", publishable_key="public",
            identity=identity,
        )
        client.auth.access_token = lambda: "signed-jwt"
        headers = client._headers()
        self.assertEqual(headers["Authorization"], "Bearer signed-jwt")
        self.assertNotIn("X-DeiLaw-Installation-Id", headers)
        self.assertNotIn("X-DeiLaw-Device-Id", headers)

    def test_my_community_lists_follow_account_uid_across_pcs(self):
        identity = SimpleNamespace(
            path=Path("data/community_identity.json"),
            installation_id="pc-specific-install-id",
            secret_hash="a" * 64,
            device_id="b" * 64,
            device_secret_hash="c" * 64,
        )
        client = SupabaseCommunityClient(
            url="https://example.supabase.co", publishable_key="public",
            identity=identity,
        )
        client.auth.access_token = lambda: "signed-user-jwt"
        client.auth.data = {
            "active": "discord", "accounts": {
                "discord": {"user": {"id": "12345678-1234-1234-1234-123456789abc"}}
            }
        }
        observed = []
        def fake_request(method, table, **kwargs):
            observed.append((table, kwargs.get("params") or {}))
            return []
        client._request = fake_request
        client.fetch_my_bug_reports()
        client.fetch_my_suggestions()
        client.fetch_developer_report_messages()
        client.submit_review(
            rating=5, review_text="Very helpful", app_version="test",
        )
        my_calls = [params for _, params in observed if "owner_uid" in params]
        self.assertEqual(len(my_calls), 4)
        for params in my_calls:
            self.assertEqual(
                params["owner_uid"], "eq.12345678-1234-1234-1234-123456789abc"
            )
            self.assertNotIn("installation_id", params)

    def test_attachment_requests_require_user_jwt_not_device_headers(self):
        identity = SimpleNamespace(
            path=Path("data/community_identity.json"),
            installation_id="private-installation-id",
            installation_secret="private-installation-secret",
            device_id="a" * 64,
            device_secret="private-device-secret",
        )
        client = SupabaseCommunityClient(
            url="https://example.supabase.co", publishable_key="public",
            identity=identity,
        )
        client.auth.access_token = lambda: "real-user-jwt"
        headers = client._function_headers("application/octet-stream")
        self.assertEqual(headers["Authorization"], "Bearer real-user-jwt")
        self.assertNotIn("X-DeiLaw-Installation-Secret", headers)
        self.assertNotIn("X-DeiLaw-Installation-Id", headers)
        self.assertNotIn("X-DeiLaw-Device-Secret", client._headers())

    def test_attachment_edge_rejects_legacy_owner_bypass(self):
        root = Path(__file__).resolve().parents[1]
        edge = (root / "supabase" / "functions" /
                "deilaw-report-attachments" / "index.ts").read_text(encoding="utf-8")
        config = (root / "supabase" / "config.toml").read_text(encoding="utf-8")
        self.assertIn("authenticatedUserId(req)", edge)
        self.assertIn('.select("owner_uid")', edge)
        self.assertIn("report.owner_uid === userId", edge)
        self.assertNotIn("if (!storedHash) return true", edge)
        self.assertNotIn('x-deilaw-installation-secret', edge)
        self.assertIn("[functions.deilaw-report-attachments]\nverify_jwt = true", config)

    def test_staged_rls_policy_migration_uses_authenticated_owner_uid(self):
        root = Path(__file__).resolve().parents[1]
        sql = (root / "SUPABASE_SECURITY_HARDENING.sql").read_text(encoding="utf-8")
        self.assertIn("owner_uid = (select auth.uid())", sql)
        self.assertIn('drop policy if exists "deilaw_reviews_public_read"', sql)
        self.assertIn('create or replace view public.deilaw_public_reviews', sql)
        self.assertNotIn("current_setting('request.headers'", sql)
        self.assertNotIn("installation_secret_hash is null", sql.lower())

    def test_production_review_migration_preserves_approved_reviews_and_private_columns(self):
        root = Path(__file__).resolve().parents[1]
        sql = (root / "SUPABASE_SECURITY_HARDENING.sql").read_text(encoding="utf-8")
        self.assertNotIn("update public.reviews set approved = false where approved = true", sql.lower())
        self.assertIn("security_invoker = true", sql)
        self.assertIn('deilaw_reviews_public_projection_read', sql)
        self.assertIn("revoke select on public.reviews from anon, authenticated", sql)
        self.assertNotIn("grant select (installation_secret_hash", sql)

    def test_sign_out_revokes_only_selected_discord_session(self):
        store = InMemoryTokenStore()
        discord_user = {
            "id": "discord-id", "is_anonymous": False,
            "app_metadata": {"provider": "discord"},
        }
        requests_seen = []

        def post(url, **kwargs):
            requests_seen.append((url, kwargs))
            return FakeResponse({})

        auth = AnonymousSupabaseSession(
            "https://example.supabase.co", "public", store=store,
            http=SimpleNamespace(post=post),
        )
        auth._accept("guest", {
            "access_token": "guest-jwt", "refresh_token": "guest-rt",
            "user": {"id": "guest-id", "is_anonymous": True},
        })
        auth._accept("discord", {
            "access_token": "discord-jwt", "refresh_token": "discord-rt",
            "user": discord_user,
        })
        self.assertTrue(auth.sign_out_active())
        self.assertIsNone(auth.mode)
        self.assertEqual(auth.saved_modes(), ("guest",))
        self.assertNotIn("discord", store.value["accounts"])
        self.assertEqual(requests_seen[0][0],
                         "https://example.supabase.co/auth/v1/logout?scope=local")
        self.assertEqual(requests_seen[0][1]["headers"]["Authorization"],
                         "Bearer discord-jwt")
        reloaded = AnonymousSupabaseSession(
            "https://example.supabase.co", "public", store=store
        )
        self.assertIsNone(reloaded.resume_active())

    def test_sign_out_still_removes_local_session_when_network_fails(self):
        store = InMemoryTokenStore()
        auth = AnonymousSupabaseSession(
            "https://example.supabase.co", "public", store=store,
            http=SimpleNamespace(post=lambda *a, **k: (_ for _ in ()).throw(
                requests.ConnectionError("offline")
            )),
        )
        auth._accept("guest", {
            "access_token": "guest-jwt", "refresh_token": "guest-rt",
            "user": {"id": "guest-id", "is_anonymous": True},
        })
        self.assertFalse(auth.sign_out_active())
        self.assertIsNone(auth.mode)
        self.assertEqual(auth.saved_modes(), ())

    def test_relaunched_login_discards_stale_logged_out_mode(self):
        store = InMemoryTokenStore()
        user = {
            "id": "discord-id", "is_anonymous": False,
            "app_metadata": {"provider": "discord"},
        }
        stale_client = AnonymousSupabaseSession(
            "https://example.supabase.co", "public", store=store
        )
        stale_client._accept("discord", {
            "access_token": "old-discord", "refresh_token": "old-refresh",
            "user": user,
        })
        # Simulate a late write by another client after the user clicked Exit.
        new_process = AnonymousSupabaseSession(
            "https://example.supabase.co", "public", store=store
        )
        new_process.discard_saved_mode("discord")
        self.assertIsNone(new_process.resume_active())
        self.assertNotIn("discord", store.value["accounts"])

    def test_relaunch_command_opens_login_choice_in_fresh_process(self):
        with patch("cloud_auth.subprocess.Popen") as popen, \
                patch("cloud_auth.sys.frozen", False, create=True):
            restart_deilaw_for_login_choice("discord")
        command = popen.call_args.args[0]
        self.assertEqual(command[-2:], ["--auth-choice", "--logout-mode=discord"])
        self.assertTrue(command[-3].endswith("main.py"))
        self.assertTrue(popen.call_args.kwargs["close_fds"])

    def test_change_account_relaunches_directly_into_discord_login(self):
        with patch("cloud_auth.subprocess.Popen") as popen, \
                patch("cloud_auth.sys.frozen", False, create=True):
            restart_deilaw_for_login_choice(discord_only=True)
        command = popen.call_args.args[0]
        self.assertEqual(command[-1], "--auth-discord")
        self.assertTrue(command[-2].endswith("main.py"))
        self.assertNotIn("--auth-choice", command)

    def test_switching_discord_account_uses_fresh_oauth_and_keeps_guest(self):
        old_user = {
            "id": "old-discord", "is_anonymous": False,
            "app_metadata": {"provider": "discord"},
        }
        new_user = {
            "id": "new-discord", "is_anonymous": False,
            "app_metadata": {"provider": "discord"},
        }
        store = InMemoryTokenStore()

        def post(url, **kwargs):
            self.assertIn("grant_type=pkce", url)
            self.assertEqual(kwargs["json"]["auth_code"], "new-code")
            return FakeResponse({
                "access_token": "new-token", "refresh_token": "new-refresh",
                "user": new_user,
            })

        auth = AnonymousSupabaseSession(
            "https://example.supabase.co", "public", store=store,
            http=SimpleNamespace(
                get=lambda *a, **k: FakeResponse({"external": {"discord": True}}),
                post=post,
            ),
        )
        auth._accept("guest", {
            "access_token": "guest-token", "refresh_token": "guest-refresh",
            "user": {"id": "guest", "is_anonymous": True},
        })
        auth._accept("discord", {
            "access_token": "old-token", "refresh_token": "old-refresh",
            "user": old_user,
        })
        with patch("discord_oauth.complete_discord_pkce", return_value=(
            "new-code", "new-verifier"
        )) as browser_login:
            result = auth.select_discord(force=True)
        browser_login.assert_called_once()
        self.assertEqual(result, "new-token")
        self.assertEqual(auth.mode, "discord")
        self.assertEqual(auth.session["user"]["id"], "new-discord")
        self.assertEqual(auth.saved_modes(), ("guest", "discord"))

    def test_account_choice_marker_survives_other_cached_token_writes(self):
        with tempfile.TemporaryDirectory() as folder:
            store = WindowsTokenStore(Path(folder) / "cloud_auth.bin")
            store.request_choice()
            self.assertTrue(store.choice_requested())
            self.assertTrue(store.choice_path.is_file())
            store.clear_choice_request()
            self.assertFalse(store.choice_requested())

    def test_restart_resumes_discord_without_showing_login(self):
        store = InMemoryTokenStore()
        discord_user = {
            "id": "discord-user", "is_anonymous": False,
            "app_metadata": {"provider": "discord"},
        }
        http = SimpleNamespace(
            get=lambda *a, **k: FakeResponse(discord_user),
            post=lambda *a, **k: self.fail("Valid saved login must not send POST"),
        )
        first = AnonymousSupabaseSession(
            "https://example.supabase.co", "public", store=store, http=http
        )
        self.assertIsNone(first.resume_active())
        first._accept("discord", {
            "access_token": "discord-token", "refresh_token": "discord-refresh",
            "expires_in": 3600, "user": discord_user,
        })

        restarted = AnonymousSupabaseSession(
            "https://example.supabase.co", "public", store=store, http=http
        )
        with patch("discord_oauth.complete_discord_pkce") as browser_login:
            self.assertEqual(restarted.resume_active(), "discord-token")
            browser_login.assert_not_called()
        self.assertEqual(restarted.mode, "discord")

    def test_account_switch_is_requested_for_next_launch_only(self):
        store = InMemoryTokenStore()
        http = SimpleNamespace(
            get=lambda *a, **k: FakeResponse({"id": "g", "is_anonymous": True}),
            post=lambda *a, **k: FakeResponse({
                "access_token": "guest-token", "refresh_token": "guest-refresh",
                "expires_in": 3600, "user": {"id": "g", "is_anonymous": True},
            }),
        )
        first = AnonymousSupabaseSession(
            "https://example.supabase.co", "public", store=store, http=http
        )
        self.assertEqual(first.select_guest(), "guest-token")
        first.request_account_selection()
        # The currently open window may keep using its valid account.
        self.assertEqual(first.access_token(), "guest-token")

        restarted = AnonymousSupabaseSession(
            "https://example.supabase.co", "public", store=store, http=http
        )
        self.assertIsNone(restarted.resume_active())
        self.assertEqual(restarted.saved_modes(), ("guest",))
        self.assertEqual(restarted.select_guest(), "guest-token")
        again = AnonymousSupabaseSession(
            "https://example.supabase.co", "public", store=store, http=http
        )
        self.assertEqual(again.resume_active(), "guest-token")

    def test_expired_account_is_refreshed_on_restart(self):
        store = InMemoryTokenStore()
        user = {"id": "g", "is_anonymous": True}
        store.value = {
            "schema": 2, "active": "guest", "accounts": {"guest": {
                "access_token": "old-token", "refresh_token": "old-refresh",
                "expires_at": 1, "user": user,
            }},
        }
        posted = []
        def post(url, **kwargs):
            posted.append(kwargs["json"])
            return FakeResponse({
                "access_token": "new-token", "refresh_token": "new-refresh",
                "expires_in": 3600, "user": user,
            })

        auth = AnonymousSupabaseSession(
            "https://example.supabase.co", "public", store=store,
            http=SimpleNamespace(post=post, get=lambda *a, **k: FakeResponse(user))
        )
        self.assertEqual(auth.resume_active(), "new-token")
        self.assertEqual(posted, [{"refresh_token": "old-refresh"}])
        self.assertEqual(store.value["accounts"]["guest"]["refresh_token"], "new-refresh")

    def test_auth_uses_real_user_token_and_reuses_it(self):
        store = InMemoryTokenStore()
        http = SimpleNamespace(post=lambda *args, **kwargs: FakeResponse({
            "access_token": "signed-user-jwt",
            "refresh_token": "private-refresh",
            "expires_in": 3600,
            "user": {"id": "guest-1", "is_anonymous": True},
        }))
        auth = AnonymousSupabaseSession("https://example.supabase.co", "public", store=store, http=http)
        with self.assertRaises(CloudAuthError):
            auth.access_token()
        self.assertEqual(auth.select_guest(), "signed-user-jwt")
        self.assertEqual(auth.access_token(), "signed-user-jwt")
        self.assertEqual(store.value["accounts"]["guest"]["refresh_token"], "private-refresh")

    def test_discord_login_does_not_destroy_guest_session(self):
        store = InMemoryTokenStore()
        posted = []

        def post(url, **kwargs):
            posted.append((url, kwargs.get("json")))
            if url.endswith("/signup"):
                return FakeResponse({"access_token": "guest-token", "refresh_token": "guest-refresh",
                                     "expires_in": 3600,
                                     "user": {"id": "g", "is_anonymous": True}})
            return FakeResponse({"access_token": "discord-token", "refresh_token": "discord-refresh",
                                 "expires_in": 3600,
                                 "user": {"id": "d", "is_anonymous": False,
                                          "app_metadata": {"provider": "discord"}}})

        http = SimpleNamespace(post=post, get=lambda url, **k: FakeResponse(
            {"external": {"discord": True}} if url.endswith("/settings") else
            {"id": "g", "is_anonymous": True}
        ))
        auth = AnonymousSupabaseSession("https://example.supabase.co", "public", store=store, http=http)
        self.assertEqual(auth.select_guest(), "guest-token")
        with patch("discord_oauth.complete_discord_pkce", return_value=("one-time-code", "verifier")):
            self.assertEqual(auth.select_discord(), "discord-token")
        self.assertEqual(auth.mode, "discord")
        self.assertEqual(auth.access_token(), "discord-token")
        self.assertEqual(auth.select_guest(), "guest-token")
        self.assertEqual(auth.mode, "guest")
        self.assertEqual(len(posted), 2)
        self.assertEqual(posted[1][1], {"auth_code": "one-time-code", "code_verifier": "verifier"})
        self.assertIn("discord", store.value["accounts"])

    def test_discord_rejects_other_provider_and_keeps_guest(self):
        store = InMemoryTokenStore()

        def post(url, **kwargs):
            if url.endswith("/signup"):
                return FakeResponse({"access_token": "guest-token", "refresh_token": "guest-refresh",
                                     "expires_in": 3600,
                                     "user": {"id": "g", "is_anonymous": True}})
            return FakeResponse({"access_token": "wrong-provider", "refresh_token": "wrong-refresh",
                                 "expires_in": 3600,
                                 "user": {"id": "u", "is_anonymous": False,
                                          "app_metadata": {"provider": "email"}}})

        auth = AnonymousSupabaseSession("https://example.supabase.co", "public",
                                       store=store, http=SimpleNamespace(
                                           post=post,
                                           get=lambda *a, **k: FakeResponse(
                                               {"external": {"discord": True}})))
        auth.select_guest()
        with patch("discord_oauth.complete_discord_pkce", return_value=("code", "verifier")):
            with self.assertRaises(CloudAuthError):
                auth.select_discord()
        self.assertEqual(auth.access_token(), "guest-token")
        self.assertNotIn("discord", store.value["accounts"])

    def test_discord_requires_server_provider_configuration(self):
        store = InMemoryTokenStore()
        auth = AnonymousSupabaseSession("https://example.supabase.co", "public",
                                       store=store, http=SimpleNamespace(
                                           get=lambda *a, **k: FakeResponse(
                                               {"external": {"discord": False}})))
        with self.assertRaisesRegex(CloudAuthError, "не подключён"):
            auth.select_discord()

    def test_discord_oauth_uses_pkce_and_local_callback(self):
        verifier, challenge = new_pkce_pair()
        self.assertGreaterEqual(len(verifier), 43)
        self.assertNotEqual(verifier, challenge)
        uri = authorization_url("https://example.supabase.co", challenge)
        self.assertIn("provider=discord", uri)
        self.assertIn("code_challenge_method=s256", uri)
        self.assertIn("code_challenge=", uri)
        from urllib.parse import parse_qs, urlparse
        self.assertEqual(parse_qs(urlparse(uri).query)["redirect_to"], [DISCORD_REDIRECT_URL])

    def test_discord_local_callback_keeps_auth_code_out_of_logs(self):
        import urllib.request
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            local_port = probe.getsockname()[1]
        callback = f"http://127.0.0.1:{local_port}/deilaw-auth"
        completed = threading.Event()

        def open_browser(_auth_url):
            def callback_request():
                try:
                    with urllib.request.urlopen(callback + "?code=one-time-test-code", timeout=4) as r:
                        self.assertEqual(r.status, 200)
                finally:
                    completed.set()
            threading.Thread(target=callback_request, daemon=True).start()
            return True

        with patch.object(discord_oauth, "DISCORD_LOOPBACK_PORT", local_port), \
                patch.object(discord_oauth, "DISCORD_REDIRECT_URL", callback):
            code, verifier = discord_oauth.complete_discord_pkce(
                "https://example.supabase.co", browser_open=open_browser, timeout=5,
            )
        self.assertEqual(code, "one-time-test-code")
        self.assertTrue(completed.wait(2))
        self.assertTrue(verifier)

    def test_cloud_ai_contract_requires_auth_and_server_sources(self):
        identity = SimpleNamespace(
            path=Path("data/community_identity.json"),
            installation_id="install-id",
            device_id="a" * 64,
        )
        client = CloudAIClient(url="https://example.supabase.co", publishable_key="public", identity=identity)
        client.auth.access_token = lambda: "signed-user-jwt"
        calls = []

        def post(url, *, headers, json, timeout):
            calls.append((headers, json))
            return FakeResponse({"answer": '{"summary":"ok"}', "sources": [
                {"law_title": "УК", "article_number": "63", "content": "..." }
            ]})

        with patch("ai_core.cloud.requests.post", side_effect=post):
            answer, sources = client.analyze("63 УК")
        self.assertIn("summary", answer)
        self.assertEqual(sources[0]["article_number"], "63")
        self.assertEqual(calls[0][0]["Authorization"], "Bearer signed-user-jwt")
        self.assertNotIn("sources", calls[0][1])

    def test_unsigned_manifest_fails_closed(self):
        manifest = {
            "version": "0.3.6", "installer_asset": "DeiLaw_Setup.exe",
            "sha256": "a" * 64, "size": 1200,
        }
        with self.assertRaises(UntrustedUpdateError):
            verify_manifest(manifest)

    def test_signed_manifest_verification(self):
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        private = Ed25519PrivateKey.generate()
        public = private.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        manifest = {
            "version": "0.3.6", "installer_asset": "DeiLaw_Setup.exe",
            "sha256": "a" * 64, "size": 1200,
        }
        manifest["signature_ed25519"] = base64.b64encode(
            private.sign(signed_manifest_bytes(manifest))
        ).decode()
        with patch.object(update_trust, "UPDATE_ED25519_PUBLIC_KEY_B64", base64.b64encode(public).decode()):
            self.assertTrue(verify_manifest(manifest))
            manifest["sha256"] = "b" * 64
            with self.assertRaises(UntrustedUpdateError):
                verify_manifest(manifest)

    def test_backups_do_not_contain_installation_secret(self):
        self.assertNotIn("community_identity.json", BackupManager.USER_FILES)
        self.assertNotIn("cloud_auth.bin", BackupManager.USER_FILES)

    def test_runtime_packages_are_pinned(self):
        requirements = (Path(__file__).resolve().parent.parent / "requirements.txt").read_text(encoding="utf-8")
        packages = [line.strip() for line in requirements.splitlines() if line.strip() and not line.startswith("#")]
        self.assertTrue(packages)
        self.assertTrue(all("==" in line for line in packages))

    def test_secure_cloud_function_requires_gateway_jwt(self):
        base = Path(__file__).resolve().parent.parent
        config = (base / "supabase" / "config.toml").read_text(encoding="utf-8")
        edge = (base / "supabase" / "functions" / "deilaw-ai" / "index.ts").read_text(encoding="utf-8")
        self.assertIn("verify_jwt = true", config)
        self.assertIn("auth.getUser(jwt)", edge)
        self.assertIn("deilaw_claim_ai_request_v2", edge)
        self.assertNotIn("body?.sources", edge)

    def test_law_search_escapes_sqlite_like_wildcards(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(database, "DATA_DIR", Path(tmp)):
                with patch.object(database, "DB_PATH", Path(tmp) / "laws.db"):
                    db = database.LawDatabase()
                    try:
                        db.connection.execute(
                            "INSERT INTO laws(title,url,content) VALUES (?,?,?)",
                            ("УК", "https://example.org/1", "обычная статья"),
                        )
                        db.connection.commit()
                        self.assertEqual(len(db.search_laws("%")), 0)
                        self.assertEqual(len(db.search_laws("_")), 0)
                        self.assertEqual(len(db.search_laws("УК")), 1)
                    finally:
                        db.connection.close()


if __name__ == "__main__":
    unittest.main()
