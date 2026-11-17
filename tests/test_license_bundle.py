"""Confirm release notice collection is deterministic and does not invent licenses."""
import json
import tempfile
import unittest
from pathlib import Path
from scripts.collect_runtime_licenses import collect_licenses


class FakeDist:
    def __init__(self, root, name, license_text=True):
        self.root = root
        self.metadata = {"Name": name, "License-Expression": "MIT"}
        self.version = "1.0"
        self.files = [Path(f"{name}-1.0.dist-info/licenses/LICENSE.txt")] if license_text else []
        if license_text:
            path = self.locate_file(self.files[0])
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("Example MIT license notice", encoding="utf-8")

    def locate_file(self, relative):
        return self.root / relative


class TestLicenseCollection(unittest.TestCase):
    def test_preserve_license_and_manifest(self):
        with tempfile.TemporaryDirectory() as folder:
            d = Path(folder)
            a = FakeDist(d, "requests")
            b = FakeDist(d, "PyQt6", license_text=False)
            result = collect_licenses(d / "distribution", [b, a])
            manifest = json.loads((d / "distribution/license_manifest.json").read_text(encoding="utf8"))
            self.assertEqual(len(manifest["packages"]), 2)
            self.assertEqual(result["missing_priority_notice_files"], ["PyQt6"])
            self.assertEqual(len(result["packages"][1]["license_files"]), 1)
            path = d / "distribution" / result["packages"][1]["license_files"][0]["file"]
            self.assertEqual(path.read_text(encoding="utf-8"), "Example MIT license notice")

    def test_missing_license_is_not_fabricated(self):
        with tempfile.TemporaryDirectory() as folder:
            d = Path(folder)
            x = FakeDist(d, "PyQt6-Qt6", license_text=False)
            m = collect_licenses(d / "licenses", [x])
            self.assertIn("PyQt6-Qt6", m["missing_priority_notice_files"])
            self.assertEqual(m["packages"][0]["license_files"], [])
            self.assertTrue(m["not_legal_certification"])


if __name__ == "__main__":
    unittest.main()
