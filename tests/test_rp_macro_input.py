import unittest

from rp_macro_input import MacroDeliveryError, send_rp_chat_lines


class RPGameInputTests(unittest.TestCase):
    def test_two_lines_are_ordered_and_paced(self):
        actions = []
        count = send_rp_chat_lines(
            ["/me достал жетон", "", "/do Жетон в руке."],
            chat_vk=0x54,
            press_key=lambda vk: actions.append(("key", vk)) or True,
            send_text=lambda value: actions.append(("text", value)) or True,
            open_chat_delay_ms=300,
            between_lines_delay_ms=350,
            sleep=lambda seconds: actions.append(("sleep", seconds)),
        )
        self.assertEqual(count, 2)
        self.assertEqual(actions, [
            ("key", 0x54), ("sleep", 0.3),
            ("text", "/me достал жетон"), ("sleep", 0.18),
            ("key", 0x0D), ("sleep", 0.35),
            ("key", 0x54), ("sleep", 0.3),
            ("text", "/do Жетон в руке."), ("sleep", 0.18),
            ("key", 0x0D),
        ])

    def test_rejected_chat_key_stops_before_text(self):
        written = []
        with self.assertRaisesRegex(MacroDeliveryError, "открытия чата"):
            send_rp_chat_lines(
                ["/me test"],
                chat_vk=0x54,
                press_key=lambda vk: False,
                send_text=lambda line: written.append(line) or True,
                sleep=lambda seconds: None,
            )
        self.assertEqual(written, [])

    def test_rejected_text_does_not_send_enter(self):
        pressed = []
        with self.assertRaisesRegex(MacroDeliveryError, "ввод текста"):
            send_rp_chat_lines(
                ["/do test"],
                chat_vk=0x54,
                press_key=lambda vk: pressed.append(vk) or True,
                send_text=lambda line: False,
                sleep=lambda seconds: None,
            )
        self.assertEqual(pressed, [0x54])

    def test_empty_commands_do_nothing(self):
        count = send_rp_chat_lines(
            ["", "   "],
            chat_vk=0x54,
            press_key=lambda vk: self.fail("unexpected key event"),
            send_text=lambda line: self.fail("unexpected text event"),
            sleep=lambda seconds: self.fail("unexpected sleep"),
        )
        self.assertEqual(count, 0)

    def test_optional_escape_closes_chat_after_each_line(self):
        actions = []
        send_rp_chat_lines(
            ["/me test", "/do test"],
            chat_vk=0x54,
            press_key=lambda vk: actions.append(("key", vk)) or True,
            send_text=lambda line: actions.append(("text", line)) or True,
            close_chat_after_send=True,
            between_lines_delay_ms=0,
            sleep=lambda seconds: actions.append(("sleep", seconds)),
        )
        self.assertEqual(
            [value for action, value in actions if action == "key"],
            [0x54, 0x0D, 0x1B, 0x54, 0x0D, 0x1B],
        )
        self.assertEqual(
            [value for action, value in actions if action == "sleep"].count(0.25),
            4,  # 2 chat-opening pauses + 2 pauses before Esc
        )

    def test_rejected_escape_is_reported(self):
        with self.assertRaisesRegex(MacroDeliveryError, "Esc"):
            send_rp_chat_lines(
                ["/me test"],
                chat_vk=0x54,
                press_key=lambda vk: vk != 0x1B,
                send_text=lambda line: True,
                close_chat_after_send=True,
                sleep=lambda seconds: None,
            )


if __name__ == "__main__":
    unittest.main()
