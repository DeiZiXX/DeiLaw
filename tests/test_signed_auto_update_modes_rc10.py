"""Security regressions for the selectable signed-release updater."""
import base64
import json
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from update_preferences import DEFAULT_UPDATE_MODE, mode_from_settings, normalize_update_mode, update_action
from update_trust import UntrustedUpdateError, signed_manifest_bytes, verify_manifest
import update_trust


class SignedUpdateModeTests(unittest.TestCase):
    def test_all_three_modes_and_invalid_mode_falls_back_to_confirmation(self):
        self.assertEqual(DEFAULT_UPDATE_MODE, "confirm")
        self.assertEqual({v: update_action(v) for v in ("auto", "confirm", "notify")},
                         {"auto": "install", "confirm": "ask", "notify": "notify"})
        for bad in (None, 1, True, [], "manual", "always"):
            self.assertEqual(normalize_update_mode(bad), "confirm")

    def test_persistent_modes_and_missing_or_corrupted_settings(self):
        with tempfile.TemporaryDirectory() as root:
            path=Path(root)/'data'/'settings.json'
            self.assertEqual(mode_from_settings(path),"confirm")
            path.parent.mkdir()
            for mode in ('auto','confirm','notify'):
                path.write_text(json.dumps({'update_install_mode':mode}),encoding='utf-8')
                self.assertEqual(mode_from_settings(path),mode)
            path.write_text('{broken',encoding='utf-8')
            self.assertEqual(mode_from_settings(path),'confirm')

    def test_signed_manifest_requires_real_key_and_refuses_tampering(self):
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        from cryptography.hazmat.primitives import serialization
        private=Ed25519PrivateKey.generate()
        public=private.public_key().public_bytes(serialization.Encoding.Raw,serialization.PublicFormat.Raw)
        manifest={'version':'0.3.5rc10','installer_asset':'DeiLaw_Setup_v0.3.5rc10.exe','sha256':'f'*64,'size':2500}
        manifest['signature_ed25519']=base64.b64encode(private.sign(signed_manifest_bytes(manifest))).decode('ascii')
        with patch.object(update_trust,'UPDATE_ED25519_PUBLIC_KEY_B64',''):
            with self.assertRaisesRegex(UntrustedUpdateError,'не настроен ключ'):
                verify_manifest(manifest)
        with patch.object(update_trust,'UPDATE_ED25519_PUBLIC_KEY_B64',base64.b64encode(public).decode('ascii')):
            self.assertTrue(verify_manifest(manifest))
            for key,val in [('sha256','b'*64),('size',2501),('version','0.3.5rc11')]:
                bad=dict(manifest);bad[key]=val
                with self.subTest(key=key),self.assertRaises(UntrustedUpdateError):
                    verify_manifest(bad)

    def test_direct_helper_cannot_run_unsigned_exe(self):
        # Updater imports Qt for signals; this source-test environment has no Qt.
        fake_qt=types.ModuleType('PyQt6')
        fake_core=types.ModuleType('PyQt6.QtCore')
        class QThread:pass
        fake_core.QThread=QThread
        fake_core.pyqtSignal=lambda *types: None
        with patch.dict(sys.modules, {'PyQt6':fake_qt,'PyQt6.QtCore':fake_core}):
            import updater
        with patch.object(updater.subprocess,'Popen') as popen:
            with self.assertRaises(UntrustedUpdateError):
                updater.launch_update_helper({'installer_path':'C:/fake/evil.exe','update_info':{}})
            popen.assert_not_called()
        self.assertIn('validate_signed_download(update_info)',Path(updater.__file__).read_text('utf-8'))
        self.assertIn('Uninstall.exe',Path(updater.__file__).read_text('utf-8'))
        self.assertIn('create_update_install_helper(installer_path, update_info)',Path(updater.__file__).read_text('utf-8'))

    def test_gui_modes_wired_to_startup_poll_and_saved_state(self):
        root=Path(__file__).resolve().parents[1]
        main=(root/'main.py').read_text('utf-8')
        window=(root/'ui/main_window.py').read_text('utf-8')
        self.assertIn('update_install_mode = _read_startup_update_mode()',main)
        self.assertIn('startup_checks_enabled(',main)
        self.assertIn('action = update_action(self.update_install_mode)',main)
        self.assertIn('action = update_action(self.app_settings.get("update_install_mode"))',window)
        self.assertIn('self.settings_update_install_mode.addItem("Автоматически", "auto")',window)
        self.assertIn('"update_install_mode": "confirm"',window)
        self.assertEqual(window.count('"update_install_mode": normalize_update_mode('),2)
        installer=(root/'installer/DeiLaw.iss').read_text('utf-8')
        self.assertIn('nowait skipifnotsilent',installer)


if __name__=='__main__':unittest.main()
