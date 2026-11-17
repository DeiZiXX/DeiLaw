"""Safety regression checks for the manual GPL source/binary release workflow."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class GPLReleaseWorkflowTests(unittest.TestCase):
    def test_only_creates_draft_from_main_after_explicit_rights_review(self):
        workflow = (ROOT / ".github/workflows/gpl-release-draft.yml").read_text(encoding="utf-8")
        self.assertIn("workflow_dispatch:", workflow)
        self.assertIn("github.ref == 'refs/heads/main'", workflow)
        self.assertIn("RIGHTS_CHECKED -ne 'true'", workflow)
        self.assertIn("REVIEWED_SHA -cne $env:GITHUB_SHA", workflow)
        self.assertIn("GPL-3.0 not merged into main", workflow)
        self.assertIn("gh release create 'v0.3.1'", workflow)
        self.assertIn("--draft", workflow)
        self.assertIn("environment: gpl-release", workflow)
        self.assertNotIn("--latest", workflow)
        self.assertNotIn("gh release edit", workflow)

    def test_must_prove_binary_source_provenance_and_test_install(self):
        workflow = (ROOT / ".github/workflows/gpl-release-draft.yml").read_text(encoding="utf-8")
        self.assertIn("build_signpath_candidate.ps1", workflow)
        self.assertIn("test_nsis_install.ps1", workflow)
        self.assertIn("source_archive_sha256", workflow)
        self.assertIn("unsigned_installer_sha256", workflow)
        self.assertIn("release/DeiLaw_Source_v0.3.1.zip", workflow)
        self.assertIn("release/license_evidence.json", workflow)
        self.assertIn("release/component_review.json", workflow)


if __name__ == "__main__":
    unittest.main()
