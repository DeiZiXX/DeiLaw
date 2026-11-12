"""Discord legacy-import contract tests; no live Supabase or Qt required."""
import sys
import types
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

try:
    import requests
except ImportError:
    requests = types.ModuleType('requests')
    requests.RequestException = type('RequestException', (Exception,), {})
    sys.modules['requests'] = requests

from community_client import SupabaseCommunityClient, CommunityError

ROOT = Path(__file__).resolve().parents[1]
USER_A = '11111111-1111-4111-8111-111111111111'
USER_B = '22222222-2222-4222-8222-222222222222'


class LegacyDiscordAutoClaimTests(unittest.TestCase):
    def make_client(self, mode='discord', uid=USER_A):
        identity = SimpleNamespace(path=Path('/nonexistent-test/data/community_identity.json'),
                                   installation_id='legacy-install',
                                   installation_secret='secret-' + 'x'*36,
                                   secret_hash='a'*64)
        client = SupabaseCommunityClient(url='https://example.supabase.co',
                                         publishable_key='public', identity=identity)
        client.auth.data = {'active': mode, 'accounts': {mode: {'user': {'id': uid}}}}
        client.auth.access_token = lambda: 'jwt-token'
        return client

    def test_guest_does_not_claim(self):
        client = self.make_client('guest')
        with patch('community_client.requests.post') as post:
            result = client.claim_legacy_feedback()
        post.assert_not_called()
        self.assertEqual(result['reports'], 0)
        self.assertIsNone(client._legacy_claim_done_for)

    def test_proves_original_installation_secret(self):
        client = self.make_client()
        response = SimpleNamespace(ok=True, json=lambda: {
            'reports': 2, 'reviews': 1, 'messages': 4,
            'review_conflicts': 0, 'suggestions': 0})
        with patch('community_client.requests.post', return_value=response) as post:
            result = client.claim_legacy_feedback()
            duplicate = client.claim_legacy_feedback()
        post.assert_called_once()
        self.assertEqual(post.call_args.kwargs['json'], {
            'p_installation_id': 'legacy-install',
            'p_installation_secret': 'secret-' + 'x'*36,
        })
        self.assertEqual(post.call_args.kwargs['headers']['Authorization'], 'Bearer jwt-token')
        self.assertEqual(result['reviews'], 1)
        self.assertEqual(result['reports'], 2)
        self.assertEqual(duplicate['reviews'], 0)

    def test_retry_after_server_failure(self):
        client = self.make_client()
        error_response = SimpleNamespace(ok=False, json=lambda: {'message': 'Unavailable'})
        success = SimpleNamespace(ok=True, json=lambda: {'reports': 1})
        with patch('community_client.requests.post', side_effect=[error_response, success]) as post:
            with self.assertRaises(CommunityError):
                client.claim_legacy_feedback()
            self.assertIsNone(client._legacy_claim_done_for)
            self.assertEqual(client.claim_legacy_feedback()['reports'], 1)
        self.assertEqual(post.call_count, 2)

    def test_account_switch_does_not_skip_other_discord_identity(self):
        client = self.make_client()
        response = SimpleNamespace(ok=True, json=lambda: {'reports': 1})
        with patch('community_client.requests.post', return_value=response) as post:
            self.assertEqual(client.claim_legacy_feedback()['reports'], 1)
            client.auth.data['accounts']['discord']['user']['id'] = USER_B
            self.assertEqual(client.claim_legacy_feedback()['reports'], 1)
        self.assertEqual(post.call_count, 2)

    def test_guest_request_does_not_silently_adopt_old_records(self):
        client = self.make_client('guest')
        with patch('community_client.requests.post') as post:
            client._ensure_legacy_claim()
        post.assert_not_called()

    def test_ui_import_is_scheduled_after_login_and_nonblocking(self):
        main = (ROOT/'main.py').read_text(encoding='utf-8')
        ui = (ROOT/'ui/main_window.py').read_text(encoding='utf-8')
        self.assertIn('QTimer.singleShot(350, window.start_legacy_feedback_import)', main)
        self.assertIn('self._run_community_task(\n            self.community_client.claim_legacy_feedback', ui)
        self.assertIn('if self.community_client.auth.mode != "discord":', ui)

    def test_server_requires_real_discord_identity_and_owner_proof(self):
        sql = (ROOT/'SUPABASE_LEGACY_DISCORD_AUTO_CLAIM_20261112.sql').read_text(encoding='utf-8')
        self.assertIn("i.provider='discord'", sql)
        self.assertIn('installation_secret_hash=v_hash', sql)
        self.assertIn('u.is_anonymous', sql)
        self.assertIn('review_conflicts', sql)
        self.assertIn('other.owner_uid=v_uid', sql)


if __name__ == '__main__':
    unittest.main()
