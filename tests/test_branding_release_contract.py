"""Fail if a release silently drops DeiLaw branding, icons, UI or installer sounds."""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP_SOUNDS = (
    "click.wav", "button.wav", "toggle.wav", "save.wav",
    "memo_open.wav", "memo_close.wav", "law_update_complete.wav",
    "ai_complete.wav", "report_reply.wav",
)
SETUP_SOUNDS = ("installer_start.wav", "installer_page.wav", "installer_finish.wav")
PAGE_IMAGES = (
    "back_welcome.png", "back_directory.png", "back_tasks.png",
    "back_ready.png", "back_installing.png", "back_finish.png",
)


class MandatoryBrandingTests(unittest.TestCase):
    def test_app_icon_exists_for_exe_and_runtime(self):
        self.assertTrue((ROOT / "assets/icons/icon.ico").is_file())
        self.assertTrue((ROOT / "installer/assets/deilaw_installer.ico").is_file())
        builder = (ROOT / "scripts/build_windows_candidate.py").read_text(encoding="utf-8")
        runtime = (ROOT / "ui/main_window.py").read_text(encoding="utf-8")
        self.assertIn('"--icon"', builder)
        self.assertIn('str(asset_dir) + ";assets"', builder)
        self.assertIn('self.setup_application_icon()', runtime)
        self.assertIn('self.setWindowIcon(icon)', runtime)

    def test_all_app_sounds_present_in_source(self):
        runtime = (ROOT / "ui/main_window.py").read_text(encoding="utf-8")
        for sound in APP_SOUNDS:
            with self.subTest(sound=sound):
                file = ROOT / "assets/sounds" / sound
                self.assertTrue(file.is_file(), sound)
                self.assertGreater(file.stat().st_size, 1000)
                self.assertIn(sound, runtime)

    def test_all_installer_artwork_and_sounds_present(self):
        installer = (ROOT / "installer/DeiLaw.nsi").read_text(encoding="utf-8")
        builder = (ROOT / "scripts/build_windows_candidate.py").read_text(encoding="utf-8")
        for name in PAGE_IMAGES:
            with self.subTest(image=name):
                self.assertTrue((ROOT / "installer/assets/pages" / name).is_file())
        for sound in SETUP_SOUNDS:
            with self.subTest(sound=sound):
                soundfile = ROOT / "installer/assets/sounds" / sound
                self.assertTrue(soundfile.is_file())
                self.assertGreater(soundfile.stat().st_size, 1000)
                self.assertIn(sound, installer)
        for text in ('MUI_WELCOMEFINISHPAGE_BITMAP', 'MUI_HEADERIMAGE_BITMAP',
                     'PlayInstallerWelcome', 'PlayInstallerFinish',
                     'deilaw_installer.ico'):
            self.assertIn(text, installer)
        self.assertIn('prepare_installer_brand_bitmaps()', builder)
        self.assertIn('back_welcome.png', builder)

    def test_branding_and_theme_code_is_not_removed(self):
        code = (ROOT / "ui/main_window.py").read_text(encoding="utf-8")
        for term in ('def apply_style(', 'def play_ui_sound(', 'def play_report_reply_voice(',
                     'def setup_application_icon(', 'self.app_settings.get("theme", "dark")'):
            self.assertIn(term, code)


if __name__ == "__main__":
    unittest.main()
