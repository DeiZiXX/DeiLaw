"""Regression tests for explicit background network opt-in."""
import json
import tempfile
import unittest
from pathlib import Path
from update_preferences import startup_checks_enabled

class SignPathPrivacyTests(unittest.TestCase):
    def test_startup_checks_fail_closed(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "settings.json"
            self.assertFalse(startup_checks_enabled(path))
            for data, enabled in [({}, False), ({"auto_check_program_updates": False}, False),
                                  ({"auto_check_program_updates": "true"}, False),
                                  ({"auto_check_program_updates": True}, True)]:
                path.write_text(json.dumps(data), encoding="utf-8")
                self.assertEqual(startup_checks_enabled(path), enabled)
            path.write_text("{invalid", encoding="utf-8")
            self.assertFalse(startup_checks_enabled(path))

    def test_background_network_default_is_off_and_toggle_is_available(self):
        root=Path(__file__).resolve().parents[1]
        window=(root/"ui/main_window.py").read_text(encoding="utf-8")
        self.assertIn('"auto_check_program_updates": False', window)
        self.assertIn('"auto_update_laws_on_startup": False', window)
        self.assertIn('"background_reply_notifications": False', window)
        self.assertIn('self.settings_auto_program_updates.setEnabled(True)', window)
        self.assertNotIn('self.app_settings["auto_check_program_updates"] = True', window)
        self.assertIn('if not self.app_settings.get("background_reply_notifications", False):', window)
        updater=(root/"updater.py").read_text(encoding="utf-8")
        self.assertIn('"check_on_startup": False',updater)

if __name__=="__main__":
    unittest.main()
