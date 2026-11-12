"""Discord profile / account-bound feedback contract (no Supabase side effects)."""
import sys
import types
import unittest
from pathlib import Path
from types import SimpleNamespace

try:
    import requests
except ImportError:
    requests = types.ModuleType('requests')
    requests.RequestException = type('RequestException', (Exception,), {})
    sys.modules['requests'] = requests

from community_client import SupabaseCommunityClient, CommunityError

ROOT = Path(__file__).resolve().parents[1]
UID = '12345678-1234-1234-1234-123456789abc'


class DiscordFeedbackContractTests(unittest.TestCase):
    def make_client(self, mode='discord'):
        identity = SimpleNamespace(path=Path('data/community_identity.json'), installation_id='legacy-install', secret_hash='x'*64, device_id='y'*64, device_secret_hash='z'*64)
        client = SupabaseCommunityClient(url='https://example.supabase.co', publishable_key='public', identity=identity)
        client.auth.data = {'active': mode, 'accounts': {mode: {'user': {'id': UID, 'identities': [{'provider': 'discord', 'identity_data': {'full_name': 'My Discord Nick'}}]}}}}
        client.auth.access_token = lambda: 'jwt-token'
        return client

    def test_reviews_submit_without_user_editable_nick_or_machine_id(self):
        client = self.make_client()
        calls = []
        def fake(method, table, **kw):
            calls.append((method, table, kw))
            return []
        client._request = fake
        client.submit_review(rating=5, review_text='Great app', app_version='test')
        payload = calls[-1][2]['payload']
        self.assertEqual(calls[-1][:2], ('POST', 'reviews'))
        self.assertEqual(set(payload), {'rating', 'review_text', 'app_version'})
        self.assertEqual(client.discord_display_name(), 'My Discord Nick')

    def test_existing_review_is_patched_per_account(self):
        client = self.make_client()
        calls = []
        def fake(method, table, **kw):
            calls.append((method, table, kw))
            return [{'id': 'existing-review'}] if method == 'GET' else None
        client._request = fake
        client.submit_review(rating=4, review_text='Updated text', app_version='test')
        self.assertEqual(calls[-1][:2], ('PATCH', 'reviews'))
        self.assertEqual(calls[-1][2]['params'], {'id': 'eq.existing-review'})
        self.assertNotIn('author_name', calls[-1][2]['payload'])

    def test_guest_can_view_but_cannot_submit_review_or_report(self):
        client = self.make_client('guest')
        with self.assertRaises(CommunityError):
            client.submit_review(rating=5, review_text='Nice app', app_version='test')
        with self.assertRaises(CommunityError):
            client.submit_bug_report({'title': 'Bug here', 'description': 'Details'})

    def test_report_payload_does_not_claim_installation_or_nickname(self):
        client = self.make_client()
        calls = []
        def fake(method, table, **kw):
            calls.append((method, table, kw))
            return [{'id': 'new-report'}] if table == 'bug_reports' else []
        client._request = fake
        client.send_report_message = lambda report_id, message: None
        client.submit_bug_report({'title': 'Some bug', 'description': 'It stopped working'})
        self.assertEqual(calls[0][:2], ('POST', 'bug_reports'))
        payload = calls[0][2]['payload']
        for banned in ('author_name', 'owner_uid', 'discord_name', 'discord_user_id', 'installation_id', 'installation_secret_hash'):
            self.assertNotIn(banned, payload)

    def test_ui_has_no_nickname_field_on_review_form(self):
        src = (ROOT/'ui/main_window.py').read_text(encoding='utf-8')
        review = src.split('    def show_review_dialog(self):', 1)[1].split('    def _suggestion_status_text', 1)[0]
        self.assertNotIn('author = QLineEdit()', review)
        self.assertIn('Ваш Discord:', review)
        self.assertIn('self._allow_discord_feedback_dialog()', review)
        sql = (ROOT/'SUPABASE_DISCORD_FEEDBACK_BINDING_20261112.sql').read_text(encoding='utf-8')
        self.assertIn('auth.identities', sql)
        self.assertIn('deilaw_internal.bind_discord_review', sql)
        self.assertIn('deilaw_internal.bind_discord_report', sql)
        self.assertIn("NEW.device_id := NULL", sql)


if __name__ == '__main__':
    unittest.main()
