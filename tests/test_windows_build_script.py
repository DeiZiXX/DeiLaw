import unittest
from pathlib import Path


class WindowsBuildScriptTests(unittest.TestCase):
    def test_app_build_does_not_bypass_powershell_policy(self):
        root = Path(__file__).resolve().parents[1]
        build = (root / "build_app_only.bat").read_text(encoding="utf-8").lower()
        self.assertNotIn("powershell.exe", build)
        self.assertNotIn("-executionpolicy bypass", build)
        self.assertIn("-m pyinstaller", build)
        self.assertIn("-m unittest discover -s tests", build)
        self.assertIn("dist\\deilaw\\deilaw.exe", build)


if __name__ == "__main__":
    unittest.main()
