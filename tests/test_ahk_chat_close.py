import tempfile
import unittest
from pathlib import Path

from ahk_bindings import AHKBindStore


class AHKChatCloseTests(unittest.TestCase):
    def test_esc_can_be_enabled_and_disabled_in_export(self):
        with tempfile.TemporaryDirectory() as directory:
            store = AHKBindStore(Path(directory) / "binds.json")
            store.upsert(
                name="Проверка",
                hotkey="F11",
                commands=["/me проверяет жетон"],
            )
            self.assertNotIn('Send "{Esc}"', store.generate_script())

            store.set_script_options(
                chat_key="t", open_chat_delay=250, close_chat_after_send=True
            )
            self.assertIn('Send "{Esc}"', store.generate_script())

            reloaded = AHKBindStore(Path(directory) / "binds.json")
            self.assertTrue(reloaded.data["close_chat_after_send"])

            reloaded.set_script_options(
                chat_key="t", open_chat_delay=250, close_chat_after_send=False
            )
            self.assertNotIn('Send "{Esc}"', reloaded.generate_script())


if __name__ == "__main__":
    unittest.main()
