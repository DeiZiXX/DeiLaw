"""Paced RP chat macros.

Games may sample keyboard events less frequently than ordinary edit controls.
The caller supplies the Windows input backend so this sequence can be tested
without a running game or a Windows desktop.
"""

import time


class MacroDeliveryError(RuntimeError):
    """The operating system did not accept one of the synthetic key events."""


def send_rp_chat_lines(
    commands,
    *,
    chat_vk,
    press_key,
    send_text,
    open_chat_delay_ms=250,
    between_lines_delay_ms=350,
    close_chat_after_send=False,
    sleep=time.sleep,
):
    """Send complete chat lines in the order supplied by the user.

    A True result only means events were submitted to Windows; the foreground
    application may still ignore synthetic input. The caller must not report
    successful delivery to the game without an in-game check.
    """
    lines = [str(line).strip() for line in commands if str(line).strip()]
    opening_delay = max(250, min(3000, int(open_chat_delay_ms))) / 1000.0
    line_delay = max(0, min(10000, int(between_lines_delay_ms))) / 1000.0

    for index, line in enumerate(lines, start=1):
        if not press_key(chat_vk):
            raise MacroDeliveryError(f"Строка {index}: Windows не приняла клавишу открытия чата.")
        sleep(opening_delay)

        if not send_text(line):
            raise MacroDeliveryError(f"Строка {index}: Windows не приняла ввод текста.")
        # Let the game process the final character before submitting the chat.
        # A very short pause can leave the text visible but miss Enter in RMRP.
        sleep(0.180)

        if not press_key(0x0D):
            raise MacroDeliveryError(f"Строка {index}: Windows не приняла Enter.")
        if close_chat_after_send:
            # Optional: in some RMRP chat configurations Enter sends a message
            # but leaves the input focused. Never press Esc unconditionally:
            # if Enter already closed chat, Esc may open the GTA pause menu.
            sleep(0.250)
            if not press_key(0x1B):
                raise MacroDeliveryError(
                    f"Строка {index}: Windows не приняла Esc для закрытия чата."
                )
            sleep(0.150)
        if line_delay and index < len(lines):
            sleep(line_delay)

    return len(lines)
