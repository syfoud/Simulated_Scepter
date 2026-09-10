import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import Mock, patch

import numpy as np

import divine_treasure_entry as entry


class EntryTests(unittest.TestCase):
    def run_sequence(self, states, protocol=5, error=None):
        frame = np.zeros((2, 2, 3), dtype=np.uint8)
        rect = (0, 0, 1920, 1080)
        results = [{"state": state, "target": (960, 980), "protocol": protocol}
                   for state in states]
        with ExitStack() as stack:
            stack.enter_context(patch.object(entry, "capture_game", return_value=(frame, 1, rect)))
            stack.enter_context(patch.object(entry, "inspect_screen", side_effect=results))
            stack.enter_context(patch.object(entry, "save_evidence"))
            stack.enter_context(patch.object(entry.time, "sleep"))
            stack.enter_context(patch("win32gui.GetForegroundWindow", return_value=1))
            stack.enter_context(patch("win32api.GetAsyncKeyState", return_value=0))
            stack.enter_context(patch("tool.utils.game_window.get_client_screen_rect", return_value=rect))
            click = stack.enter_context(patch("pyautogui.click"))
            release = stack.enter_context(patch("win32api.mouse_event"))
            if error:
                with self.assertRaisesRegex(RuntimeError, error):
                    entry.enter_universe(None, Path("unused"))
            else:
                entry.enter_universe(None, Path("unused"))
            release.assert_called_once()
            return click.call_count

    def test_lagging_page_does_not_repeat_click_and_masks_stop_input(self):
        states = ["home"] * 4
        for state in entry.STATES[1:5]:
            states.extend([state, state])
        states.extend(["unknown", "masks", "masks"])
        self.assertEqual(self.run_sequence(states), 5)

    def test_wrong_or_unreadable_protocol_never_launches(self):
        states = [state for state in entry.STATES[:5] for _ in range(2)]
        for protocol in (4, None):
            with self.subTest(protocol=protocol):
                self.assertEqual(self.run_sequence(states, protocol, "Protocol must be 5"), 4)

    def test_skipped_page_stops_without_clicking_it(self):
        self.assertEqual(self.run_sequence(["home", "home", "regular", "regular"], error="Unexpected page"), 1)

    def test_existing_mask_page_does_not_claim_this_probe_entered(self):
        self.assertEqual(self.run_sequence(["masks", "masks"], error="before this probe"), 0)

    def test_mask_title_alone_does_not_count_as_entry(self):
        def row(text, x, y):
            return ([[x - 5, y - 5], [x + 5, y - 5], [x + 5, y + 5], [x - 5, y + 5]], (text, 0.99))

        image = np.zeros((1080, 1920, 3), dtype=np.uint8)
        title = row("欢愉假面", 150, 70)
        ocr = Mock()
        ocr.ocr.return_value = [title]
        self.assertEqual(entry.inspect_screen(image, ocr)["state"], "unknown")
        ocr.ocr.return_value = [title, row("机铠面具", 500, 500), row("雪鹄面具", 1000, 500)]
        self.assertEqual(entry.inspect_screen(image, ocr)["state"], "masks")


if __name__ == "__main__":
    unittest.main()
