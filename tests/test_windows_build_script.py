import unittest
from pathlib import Path


class WindowsBuildScriptTests(unittest.TestCase):
    def test_python_builder_has_no_execution_policy_bypass(self):
        root = Path(__file__).resolve().parents[1]
        build = (root / "scripts/build_windows_candidate.py").read_text(encoding="utf-8").lower()
        self.assertNotIn("powershell.exe", build)
        self.assertNotIn("-executionpolicy bypass", build)
        self.assertIn('"pyinstaller"', build)
        self.assertIn('"unittest", "discover", "-s", "tests"', build)
        self.assertIn('"deilaw.exe"', build)

    def test_release_tree_has_no_batch_scripts(self):
        root = Path(__file__).resolve().parents[1]
        self.assertEqual(list(root.glob("*.bat")), [])
        self.assertEqual(list((root / "scripts").rglob("*.bat")), [])
        for name in ("build_app_only.ps1", "build_release.ps1", "check_build_scripts.ps1", "scripts/build_signpath_candidate.ps1"):
            self.assertFalse((root / name).exists())


if __name__ == "__main__":
    unittest.main()
