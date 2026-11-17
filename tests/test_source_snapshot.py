"""Security tests for Git-committed source snapshot packaging."""
from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from scripts.package_source_snapshot import create_source_snapshot, sha256


def git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)


class TestSourceSnapshot(unittest.TestCase):
    def create_repo(self, root: Path) -> None:
        (root / ".github" / "workflows").mkdir(parents=True)
        files = {
            "LICENSE": "GNU GENERAL PUBLIC LICENSE\n",
            "app_version.py": 'APP_VERSION = "0.3.1"\n',
            "main.py": "print('hello')\n",
            "requirements.txt": "testdep==1.0\n",
            ".github/workflows/windows-build.yml": "name: Build\n",
        }
        for name, content in files.items():
            (root / name).write_text(content, encoding="utf-8")
        git(root, "init", "-q")
        git(root, "add", ".")
        git(root, "-c", "user.name=CI Test", "-c", "user.email=ci@example.invalid", "commit", "-qm", "test snapshot")

    def test_snapshot_binds_exact_commit_and_hash(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.create_repo(root)
            archive_dir = root / "untracked-output"
            result = create_source_snapshot(root, archive_dir, "0.3.1")
            self.assertEqual(result["scope"], "TRACKED_DEILAW_PROJECT_SOURCES_ONLY")
            self.assertTrue(result["third_party_corresponding_source_not_included"])
            self.assertEqual(result["source_archive_sha256"], sha256(archive_dir / result["source_archive"]))
            self.assertEqual(len(result["source_commit"]), 40)
            self.assertEqual(json.loads((archive_dir / "source_provenance.json").read_text(encoding="utf-8"))["source_commit"], result["source_commit"])

    def test_refuses_changed_tracked_files_and_version_mismatch(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.create_repo(root)
            (root / "main.py").write_text("modified", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Tracked files changed"):
                create_source_snapshot(root, root / "out", "0.3.1")
            git(root, "checkout", "--", "main.py")
            with self.assertRaisesRegex(ValueError, "inconsistent"):
                create_source_snapshot(root, root / "out", "0.3.2")

if __name__ == "__main__":
    unittest.main()
