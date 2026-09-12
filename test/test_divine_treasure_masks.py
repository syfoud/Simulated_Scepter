import itertools
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import Mock, patch

import numpy as np

import collect_snow_masks as gallery
import divine_treasure_entry as entry
import divine_treasure_masks as masks


def screen(state):
    return dict(state=state, target=(960, 980), cards=[], selected=None, refresh=None,
                rerolls=None, reroll_target=None, rows=[])


class MaskFlowTests(unittest.TestCase):
    def run_sequence(self, results, error=None):
        frame = np.zeros((2, 2, 3), dtype=np.uint8)
        rect = (0, 0, 1920, 1080)
        with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
            stack.enter_context(patch.object(masks, "capture_game", return_value=(frame, 1, rect)))
            # Each page lingers for several frames after a click.
            stack.enter_context(patch.object(masks, "inspect_screen",
                                            side_effect=itertools.chain(
                                                [item for item in results for _ in range(4)],
                                                itertools.repeat(results[-1]))))
            stack.enter_context(patch.object(masks, "save_evidence"))
            stack.enter_context(patch.object(masks.time, "sleep"))
            stack.enter_context(patch.object(masks.time, "monotonic", side_effect=itertools.count(0, 0.1)))
            stack.enter_context(patch("win32gui.GetForegroundWindow", return_value=1))
            stack.enter_context(patch("win32api.GetAsyncKeyState", return_value=0))
            stack.enter_context(patch("tool.utils.game_window.get_client_screen_rect", return_value=rect))
            clicks = stack.enter_context(patch.object(masks, "click_game"))
            keys = stack.enter_context(patch("pyautogui.press"))
            release = stack.enter_context(patch("win32api.mouse_event"))
            release_key = stack.enter_context(patch("win32api.keybd_event"))
            if error:
                with self.assertRaisesRegex((RuntimeError, TimeoutError), error):
                    masks.run(None, Path(directory))
            else:
                result = masks.run(None, Path(directory))
                self.assertEqual(result["restart"], keys.called)
            release.assert_called_once()
            release_key.assert_called_once()
            return clicks.call_count, keys.call_count

    def test_snow_and_failed_refresh_complete_once_with_lagging_frames(self):
        for restart in (False, True):
            with self.subTest(restart=restart):
                chosen = "战车面具" if restart else "雪鸡面具"
                first = screen("masks")
                first.update(cards=[("战车面具", 484, 415), ("机铠面具", 484, 601),
                                    ("点子王面具" if restart else chosen, 484, 786)], refresh=1)
                results = [first]
                if restart:
                    refreshed = screen("masks")
                    refreshed.update(cards=[("战车面具", 484, 415), ("万随面具", 484, 601),
                                            ("斗士面具", 484, 786)], refresh=0)
                    results.append(refreshed)
                for state in ("mask_selected", "mask_obtained", "equations", "equation_selected",
                              "blessings", "wonders", "wonder_selected", "first_area"):
                    item = screen(state)
                    item.update(selected=chosen, cards=[(chosen + "·绽", 960, 555)])
                    results.append(item)
                if restart:
                    results.extend(screen(s) for s in ("pause", "settle_confirm", "settlement", "home"))
                self.assertEqual(self.run_sequence(results), (12, 1) if restart else (8, 0))

    def snow_opening(self):
        results = []
        for state in ("masks", "mask_selected", "mask_obtained", "equations", "equation_selected", "blessings"):
            item = screen(state)
            item.update(selected="雪鸡面具", refresh=1,
                        cards=[("战车面具", 484, 415), ("机铠面具", 484, 601), ("雪鸡面具", 484, 786)])
            results.append(item)
        return results

    def test_opening_rerolls_until_preferred_or_settles_after_three_misses(self):
        for branch, rerolls in (("绽", 0), ("解", 1), ("霸", 3), ("终", 3)):
            with self.subTest(branch=branch, rerolls=rerolls):
                results = self.snow_opening()
                for remaining in range(3, 3 - rerolls, -1):
                    offer = screen("wonders")
                    offer.update(cards=[("雪鸡面具·终", 960, 555)],
                                 rerolls=remaining, reroll_target=(741, 972))
                    results.append(offer)
                offer = screen("wonders")
                offer.update(cards=[(f"雪鸡面具·{branch}", 960, 555)],
                             rerolls=3 - rerolls, reroll_target=(741, 972))
                selected = dict(offer, state="wonder_selected", rerolls=0)
                results.extend((offer, selected, screen("first_area")))
                restart = branch == "终"
                if restart:
                    results.extend(screen(s) for s in ("pause", "settle_confirm", "settlement", "home"))
                self.assertEqual(self.run_sequence(results), (8 + rerolls + (3 if restart else 0), int(restart)))

    def test_reroll_waits_for_decreased_counter_even_when_card_changes(self):
        before = screen("wonders")
        before.update(cards=[("雪鸡面具·终", 960, 555)], rerolls=3, reroll_target=(741, 972))
        unchanged_count = dict(before, cards=[("雪鸡面具·绽", 960, 555)])
        results = self.snow_opening() + [before, unchanged_count]
        self.assertEqual(self.run_sequence(results, "No confirmed next screen: after_reroll"), (7, 0))

    def test_unreadable_wonder_or_counter_does_not_spend_rerolls(self):
        for name, error in (("雪鸡面具·终", "reroll counter is unreadable"),
                            ("雪鸡面具·?", "wonder is unreadable")):
            with self.subTest(name=name):
                offer = screen("wonders")
                offer["cards"] = [(name, 960, 555)]
                self.assertEqual(self.run_sequence(self.snow_opening() + [offer], error), (6, 0))

    def test_reroll_counter_recognition_uses_the_opening_button_region(self):
        for counter in ("重随3/3", "重随2/3", "重随1/3", "重随0/3", "重随?/3"):
            with self.subTest(counter=counter):
                rows = [("选择惊世奇迹", 960, 137), ("雪鸡面具·终", 960, 555),
                        ("确认", 1150, 972), (counter, 741, 972), ("3/3", 1800, 66)]
                with patch.object(masks, "read_rows", return_value=rows):
                    result = masks.inspect_screen(np.zeros((2, 2, 3), dtype=np.uint8), None)
                self.assertEqual(result["state"], "wonders")
                expected = None if "?" in counter else int(counter[-3])
                self.assertEqual(result["rerolls"], expected)
                self.assertEqual(result["reroll_target"], None if expected is None else (741, 972))

    def test_settlement_reenters_and_attempt_logs_remain_separate(self):
        for stage in ("masks", "opening"):
            with self.subTest(stage=stage), tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
                stack.enter_context(patch("sys.argv", ["entry", "--worker", "--stage", stage, "--output", directory]))
                stack.enter_context(patch("tool.onnxocr.onnx_paddleocr.ONNXPaddleOcr"))
                stack.enter_context(patch.object(entry.os, "chdir"))
                run = stack.enter_context(patch.object(masks, "run", side_effect=[{"restart": True}, {"restart": False}]))
                enter = stack.enter_context(patch.object(entry, "enter_universe"))
                calls = Mock()
                calls.attach_mock(run, "masks")
                calls.attach_mock(enter, "entry")
                self.assertEqual(entry.main(), 0)
                self.assertEqual([call[0] for call in calls.mock_calls],
                                 (["entry"] if stage == "opening" else []) + ["masks", "entry", "masks"])
                self.assertEqual([call.args[1].parent.name for call in run.call_args_list], ["attempt-01", "attempt-02"])

    def test_retry_time_limit_does_not_start_another_run(self):
        with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
            stack.enter_context(patch("sys.argv", ["entry", "--worker", "--stage", "masks", "--output", directory]))
            stack.enter_context(patch("tool.onnxocr.onnx_paddleocr.ONNXPaddleOcr"))
            stack.enter_context(patch.object(entry.os, "chdir"))
            stack.enter_context(patch.object(entry.time, "monotonic", side_effect=[0, 0, 241]))
            run = stack.enter_context(patch.object(masks, "run", return_value={"restart": True}))
            enter = stack.enter_context(patch.object(entry, "enter_universe"))
            self.assertEqual(entry.main(), 2)
            run.assert_called_once()
            enter.assert_not_called()

    def test_wrong_selected_mask_stops_before_confirm(self):
        choice = screen("masks")
        choice.update(cards=[("雪鸡面具", 484, 786)], refresh=1)
        selected = screen("mask_selected")
        selected["selected"] = "点子王面具"
        self.assertEqual(self.run_sequence([choice, selected], "Selected mask changed"), (1, 0))

    def test_unreadable_refresh_never_selects_fallback(self):
        choice = screen("masks")
        choice["cards"] = [("战车面具", 484, 415)]
        self.assertEqual(self.run_sequence([choice], "Refresh counter"), (0, 0))

    def test_focus_or_f8_prevents_shared_click(self):
        rect = (0, 0, 1920, 1080)
        for foreground, f8 in ((2, 0), (1, 0x8000)):
            with patch("win32gui.GetForegroundWindow", return_value=foreground), \
                    patch("win32api.GetAsyncKeyState", return_value=f8), \
                    patch("tool.utils.game_window.get_client_screen_rect", return_value=rect), \
                    patch("pyautogui.click") as click:
                with self.assertRaises((RuntimeError, InterruptedError)):
                    entry.click_game(1, rect, (960, 500))
                click.assert_not_called()


class GalleryTests(unittest.TestCase):
    def test_detail_extraction_requires_all_ten_cards_and_excludes_other_ui(self):
        rows = [(name.replace("雪鸮", "雪鸡"), 250 + (i % 5) * 216, 490 + (i // 5) * 245)
                for i, name in enumerate(gallery.BRANCHES)]
        rows[0] = ("雪号面具·序", 250, 490)
        rows += [("惊世奇迹", 143, 49), ("惊世奇迹-览【200/200]", 400, 145), ("雪鸡面具·序", 1520, 145),
                 ("强化面具效果，招聘时区域卡等级额外+1", 1630, 390),
                 ("适用面具", 1510, 500), ("查看可用面具", 1610, 550)]
        with patch.object(gallery, "read_rows", return_value=rows):
            result = gallery.inspect_screen(np.zeros((2, 2, 3), dtype=np.uint8), Mock())
            self.assertEqual(result["state"], "gallery")
            self.assertEqual(result["selected"], gallery.BRANCHES[0])
            self.assertNotIn("查看", result["effect"])
            rows.pop(0)
            self.assertEqual(gallery.inspect_screen(np.zeros((2, 2, 3), dtype=np.uint8), Mock())["state"], "unknown")

    def run_gallery(self, stale=False):
        with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
            root = Path(directory)
            cards = dict.fromkeys(gallery.BRANCHES, (250, 490))
            results = [dict(state="gallery", cards=cards, selected=name, effect=f"{name}效果原文+1", rows=[])
                       for name in gallery.BRANCHES]
            writer = stack.enter_context(patch.object(gallery, "write_document", wraps=gallery.write_document))
            stack.enter_context(patch.object(gallery, "capture_game",
                                            return_value=(np.zeros((2, 2, 3), dtype=np.uint8), 1, (0, 0, 1920, 1080))))
            stack.enter_context(patch.object(gallery, "inspect_screen", **(
                {"return_value": results[0]} if stale else
                {"side_effect": [results[0]] + [item for item in results for _ in range(2)]})))
            stack.enter_context(patch.object(gallery, "save_evidence"))
            stack.enter_context(patch.object(gallery.time, "sleep"))
            stack.enter_context(patch.object(gallery.time, "monotonic", side_effect=itertools.count()))
            clicks = stack.enter_context(patch.object(gallery, "click_game"))
            release = stack.enter_context(patch("win32api.mouse_event"))
            if stale:
                with self.assertRaisesRegex(TimeoutError, "stable matching details"):
                    gallery.run(None, root / "logs")
                self.assertFalse((root / "docs/snow-mask-effects.md").exists())
                report = (root / "logs/snow-mask-effects.md").read_text(encoding="utf-8")
                self.assertIn("1/10", report)
                self.assertEqual(clicks.call_count, 1)
            else:
                records = gallery.run(None, root / "logs")
                self.assertEqual(len(records), 10)
                self.assertEqual(clicks.call_count, 9)
                report = (root / "logs/snow-mask-effects.md").read_text(encoding="utf-8")
                self.assertIn("10/10", report)
                self.assertNotIn("待采集", report)
            self.assertTrue(all(call.args[1] == root / "logs/snow-mask-effects.md"
                                for call in writer.call_args_list))
            release.assert_called_once()

    def test_collect_ten_effects_to_document(self):
        self.run_gallery()

    def test_stale_detail_is_not_assigned_to_next_branch(self):
        self.run_gallery(stale=True)


if __name__ == "__main__":
    unittest.main()
