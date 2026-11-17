import json
import tempfile
import unittest
from pathlib import Path
from scripts.build_inventory import inventory

ROOT = Path(__file__).resolve().parents[1]

class PackagingChecks(unittest.TestCase):
    def test_nsis_has_privacy_opt_out_and_preserves_data(self):
        s = (ROOT / 'installer/DeiLaw.nsi').read_text(encoding='utf-8')
        for needle in ('SetCompressor zlib', 'MUI_PAGE_LICENSE',
                       'PrivacyPageCreate', 'NSD_CreateCheckbox',
                       'StrCpy $OptUpdates "false"', 'StrCpy $OptLaws "false"',
                       'StrCpy $OptReplies "false"',
                       'IfFileExists "$INSTDIR\\data\\settings.json"',
                       'WriteUninstaller', 'Section "Uninstall"'):
            self.assertIn(needle, s)
        self.assertNotIn('RMDir /r "$INSTDIR"',s)
        self.assertIn('RMDir /r "$INSTDIR\\THIRD_PARTY_LICENSES"', s)
        self.assertIn('"/S"', (ROOT/'updater.py').read_text(encoding='utf-8'))

    def test_nsis_utf8_cyrillic_and_legacy_inno_guard(self):
        build = (ROOT / 'scripts/build_signpath_candidate.ps1').read_text(encoding='utf-8')
        installer = (ROOT / 'installer/DeiLaw.nsi').read_text(encoding='utf-8')
        self.assertIn('"/INPUTCHARSET" "UTF8"', build)
        self.assertIn('scripts\\review_windows_bundle.py', build)
        self.assertIn("$AppMeta.ProductName -ne 'DeiLaw'", build)
        self.assertIn('$AppMeta.ProductVersion -ne $Version', build)
        self.assertIn('Unicode true', installer)
        self.assertIn('Обнаружена прежняя версия DeiLaw', installer)
        self.assertIn('IfFileExists "$INSTDIR\\unins000.exe"', installer)
        self.assertIn('Abort', installer)
        self.assertNotIn('ExecWait \'"$INSTDIR\\unins000.exe"', installer)

    def test_signpath_pipeline_fail_closed(self):
        s = (ROOT / '.github/workflows/signpath-release.yml').read_text(encoding='utf-8')
        for needle in ('SIGNPATH_API_TOKEN', 'if: github.ref ==',
                       'GNU GENERAL PUBLIC LICENSE', 'github-artifact-id:',
                       'output-artifact-directory:', 'manual release approval'):
            self.assertIn(needle, s)
        self.assertIn('SIGNPATH_REVIEWED_SHA -cne $env:GITHUB_SHA', s)
        self.assertIn('SIGNPATH_RIGHTS_ACK', s)
        self.assertEqual(s.count('Expected SignPath Foundation Authenticode signer'), 2)
        self.assertIn('scripts/review_windows_bundle.py', s)

    def test_inventory_sha256_and_no_file_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            (folder/'DeiLaw.exe').write_bytes(b'hello')
            a = inventory(folder)
            self.assertEqual(a['files'][0]['path'], 'DeiLaw.exe')
            self.assertEqual(len(a['files'][0]['sha256']),64)
            self.assertIn('python_packages',a)

if __name__ == '__main__': unittest.main()
