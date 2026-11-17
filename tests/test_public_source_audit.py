"""Do not accidentally publish operational files, credentials or user data."""
import tempfile
import unittest
from pathlib import Path

from scripts.audit_public_source import violations, tracked_files


class PublicSourceAuditTests(unittest.TestCase):
    def test_allows_public_client_configuration(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "client.py").write_text(
                'SUPABASE_URL="https://example.supabase.co"\n'
                'SUPABASE_PUBLISHABLE_KEY="sb_publishable_public_sample"\n',
                encoding="utf-8",
            )
            self.assertEqual(violations(root, ["client.py"]), [])

    def test_blocks_internal_operations_document(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            path = "docs/SECURITY_ROLLOUT.md"
            (root / "docs").mkdir()
            (root / path).write_text("sensitive deployment status", encoding="utf-8")
            found = violations(root, [path])
            self.assertTrue(any("internal operations" in issue for issue in found))

    def test_blocks_raw_secret_without_printing_it(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            raw = "sk-" + ("A" * 40)
            (root / "client.py").write_text("API = '" + raw + "'", encoding="utf-8")
            found = violations(root, ["client.py"])
            self.assertTrue(any("OpenAI credential" in issue for issue in found))
            self.assertFalse(any(raw in issue for issue in found))

    def test_blocks_private_key_and_user_db_filenames(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for name in ("my_token.pem", "data/identity.db", ".env"):
                p = root / name
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text("redacted", encoding="utf-8")
            found = violations(root, ["my_token.pem", "data/identity.db", ".env"])
            self.assertEqual(sum("private data" in issue for issue in found), 3)

    def test_fails_closed_without_git_metadata(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(RuntimeError):
                tracked_files(Path(temp))


if __name__ == "__main__":
    unittest.main()
