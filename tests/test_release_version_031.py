"""Release metadata must consistently use the approved public version."""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class PublicVersionMetadataTests(unittest.TestCase):
    def test_public_release_version(self):
        self.assertEqual((ROOT / "app_version.py").read_text(encoding="utf-8").strip(),
                         'APP_VERSION = "0.3.1"')

    def test_inno_setup_matches_public_version(self):
        installer = (ROOT / "installer/DeiLaw.iss").read_text(encoding="utf-8")
        self.assertIn('#define MyAppVersion "0.3.1"', installer)

    def test_windows_executable_metadata_matches_public_version(self):
        info = (ROOT / "installer/version_info.txt").read_text(encoding="utf-8")
        self.assertIn('filevers=(0, 3, 1, 0)', info)
        self.assertIn('prodvers=(0, 3, 1, 0)', info)
        self.assertIn("StringStruct(u'FileVersion', u'0.3.1')", info)
        self.assertIn("StringStruct(u'ProductVersion', u'0.3.1')", info)

    def test_build_scripts_embed_version_info(self):
        for name in ("build_app_only.bat", "build_app_only.ps1"):
            script = (ROOT / name).read_text(encoding="utf-8")
            with self.subTest(name=name):
                self.assertIn('--version-file', script)
                self.assertIn('version_info.txt', script)

    def test_current_docs(self):
        self.assertIn('Текущая версия исходников: 0.3.1',
            (ROOT / 'README.md').read_text(encoding='utf-8'))
        self.assertIn('APP_VERSION = "0.3.1"',
            (ROOT / 'docs/VERIFICATION.md').read_text(encoding='utf-8'))


if __name__ == "__main__":
    unittest.main()
