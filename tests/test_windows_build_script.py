import unittest
from pathlib import Path


class WindowsBuildScriptTests(unittest.TestCase):
    def test_powershell_app_build_has_no_execution_policy_bypass(self):
        root = Path(__file__).resolve().parents[1]
        build = (root / "build_app_only.ps1").read_text(encoding="utf-8").lower()
        self.assertNotIn("powershell.exe", build)
        self.assertNotIn("-executionpolicy bypass", build)
        self.assertIn("-m pyinstaller", build)
        self.assertIn("-m unittest discover -s tests", build)
        self.assertIn("dist\\deilaw\\deilaw.exe", build)

    def test_release_tree_has_no_batch_scripts(self):
        root = Path(__file__).resolve().parents[1]
        self.assertEqual(list(root.rglob("*.bat")), [])


if __name__ == "__main__":
    unittest.main()
