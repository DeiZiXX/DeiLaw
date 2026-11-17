"""Check exact notice hashes, manifest presence and explicit manual-review status."""
import tempfile
import unittest
from pathlib import Path

from scripts.collect_runtime_licenses import collect_licenses
from scripts.review_windows_bundle import audit_bundle


class FakeDistribution:
    version = "1.0"

    def __init__(self, root):
        self.root = root
        self.metadata = {"Name": "requests", "License-Expression": "Apache-2.0"}
        self.files = [Path("requests-1.0.dist-info/licenses/LICENSE.txt")]
        source = self.root / self.files[0]
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text("Original upstream notice", encoding="utf-8")

    def locate_file(self, path):
        return self.root / path


class TestWindowsLicenseEvidence(unittest.TestCase):
    def prepare(self, root):
        app = root / "DeiLaw"
        app.mkdir()
        (app / "DeiLaw.exe").write_bytes(b"unsigned Windows test stub")
        collect_licenses(app / "THIRD_PARTY_LICENSES", [FakeDistribution(root)])
        return app

    def test_report_is_review_evidence_not_legal_clearance(self):
        with tempfile.TemporaryDirectory() as temp:
            app = self.prepare(Path(temp))
            result = audit_bundle(app)
            self.assertTrue(result["technical_integrity_ok"])
            self.assertTrue(result["requires_manual_compliance_review"])
            self.assertEqual(len(result["verified_notice_files"]), 1)
            self.assertIn("DeiLaw.exe", result["windows_binaries"])
            self.assertEqual(result["integrity_issues"], [])

    def test_missing_or_modified_notice_fails(self):
        with tempfile.TemporaryDirectory() as temp:
            app = self.prepare(Path(temp))
            notice = next((app / "THIRD_PARTY_LICENSES").rglob("LICENSE.txt"))
            notice.write_text("tampered", encoding="utf-8")
            report = audit_bundle(app)
            self.assertFalse(report["technical_integrity_ok"])
            self.assertIn("changed notice", report["integrity_issues"][0])

    def test_no_manifest_is_error(self):
        with tempfile.TemporaryDirectory() as temp:
            app = Path(temp) / "DeiLaw"
            app.mkdir()
            (app / "DeiLaw.exe").write_bytes(b"stub")
            with self.assertRaises(FileNotFoundError):
                audit_bundle(app)

    def test_missing_executable_fails(self):
        with tempfile.TemporaryDirectory() as temp:
            app = self.prepare(Path(temp))
            (app / "DeiLaw.exe").unlink()
            self.assertFalse(audit_bundle(app)["technical_integrity_ok"])


if __name__ == "__main__":
    unittest.main()
