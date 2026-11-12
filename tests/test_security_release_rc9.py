"""Fail-closed security guards for the 0.3.5rc9 source preview."""
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]

class SecurityReleaseRC9Tests(unittest.TestCase):
    def test_edge_attachments_reject_zip_and_sniff_magic(self):
        code=(ROOT/'supabase/functions/deilaw-report-attachments/index.ts').read_text('utf-8')
        self.assertIn('validAttachmentSignature(ext, body)',code)
        self.assertIn('!validAttachmentSignature(ext, body)',code)
        self.assertNotIn('".zip"',code)
        client=(ROOT/'community_client.py').read_text('utf-8')
        self.assertNotIn('".zip"',client)

    def test_upstream_error_body_never_logged(self):
        code=(ROOT/'supabase/functions/deilaw-ai/index.ts').read_text('utf-8')
        self.assertNotIn('console.error("OpenAI error", openaiResponse.status, openaiPayload)',code)
        self.assertIn('signal: AbortSignal.timeout(45_000)',code)

    def test_updater_fail_closed_until_release_key_supplied(self):
        code=(ROOT/'update_trust.py').read_text('utf-8')
        self.assertIn('UPDATE_ED25519_PUBLIC_KEY_B64 = ""',code)
        self.assertIn('не настроен ключ проверки подписи',code)
        worker=(ROOT/'updater.py').read_text('utf-8')
        self.assertIn('validate_signed_download(self.update_info)',worker)
        self.assertIn('downloaded != expected_size',worker)
        self.assertIn('verify_manifest(manifest)',worker)
        self.assertIn('digest.hexdigest().lower() != expected_sha256',worker)
        self.assertIn('не из установленной версии',worker)

    def test_rate_limit_migration_checks_uid_and_locks(self):
        code=(ROOT/'SUPABASE_FEEDBACK_RATE_LIMIT_20261112.sql').read_text('utf-8')
        self.assertIn('pg_advisory_xact_lock',code)
        self.assertIn('v_uid uuid := auth.uid()',code)
        self.assertNotIn("current_user <> 'authenticated'",code)

if __name__ == '__main__': unittest.main()
