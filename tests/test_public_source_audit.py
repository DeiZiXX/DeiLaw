"""Do not accidentally publish operational files, credentials or user data."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.audit_public_source import archive_files, violations, tracked_files


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

    def test_blocks_batch_scripts(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "start.bat").write_text("@echo off", encoding="utf-8")
            self.assertTrue(any("batch script forbidden" in issue for issue in violations(root, ["start.bat"])))

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

    def test_missing_git_binary_is_reported_without_windows_traceback(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / ".git").mkdir()
            with patch("scripts.audit_public_source.subprocess.run", side_effect=FileNotFoundError(2, "The system cannot find the file specified", "git")):
                with self.assertRaisesRegex(RuntimeError, "Git executable is unavailable"):
                    tracked_files(root)

    def test_source_zip_scan_works_without_git(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "main.py").write_text("print('hello')", encoding="utf-8")
            (root / ".venv" / "Scripts").mkdir(parents=True)
            (root / ".venv" / "Scripts" / "activate.bat").write_text("ignored", encoding="utf-8")
            names = archive_files(root)
            self.assertEqual(names, ["main.py"])
            self.assertEqual(violations(root, names), [])

    def test_fails_closed_without_git_metadata(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(RuntimeError):
                tracked_files(Path(temp))


if __name__ == "__main__":
    unittest.main()
