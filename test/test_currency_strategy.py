import csv
import io
import os
import tempfile
import unittest
from unittest.mock import Mock

from core.currency.automation import SimulatedCurrency
from core.currency.settings import normalize_currency_settings
from core.currency.strategies import (
    MIN_PLANE,
    STRATEGIES,
    STRATEGY_NAMES,
    exit_plane_for,
    match_name,
)
from core.currency.strategy_stats import StrategySampler


class StrategyListTest(unittest.TestCase):
    def test_list_covers_the_season(self):
        self.assertEqual(len(STRATEGIES), 298)
        self.assertEqual(len(set(STRATEGY_NAMES)), 298)
        self.assertEqual(set(MIN_PLANE), set(STRATEGY_NAMES))

    def test_min_plane_distribution(self):
        counts = {}
        for name in STRATEGY_NAMES:
            counts[MIN_PLANE[name]] = counts.get(MIN_PLANE[name], 0) + 1
        self.assertEqual(counts, {1: 189, 2: 92, 3: 17})

    def test_match_name_repairs_ocr(self):
        self.assertEqual(match_name("尾款交付"), "尾款交付")
        self.assertEqual(match_name("尾款交什"), "尾款交付")   # 形近字
        self.assertIsNone(match_name("完全不存在的名字啊啊"))

    def test_exit_plane_follows_uncollected_targets(self):
        third = [n for n in STRATEGY_NAMES if MIN_PLANE[n] == 3][0]
        second = [n for n in STRATEGY_NAMES if MIN_PLANE[n] == 2][0]

        # 三条都没收到：最晚出现的一面是 3
        self.assertEqual(exit_plane_for([third, second], set()), 3)
        # 第三面那条收到了：降到 2
        self.assertEqual(exit_plane_for([third, second], {third}), 2)
        # 全收到：退回第 1 面，避免空转
        self.assertEqual(exit_plane_for([third, second], {third, second}), 1)


class StrategySamplerTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.csv = os.path.join(self.temp.name, "strategy_samples.csv")
        self.summary = os.path.join(self.temp.name, "strategy_summary.txt")
        self.sampler = StrategySampler(self.csv, self.summary)

    def tearDown(self):
        self.temp.cleanup()

    def test_record_writes_screen_row_and_counts(self):
        hits = self.sampler.record(2, ["尾款交付", "特战资金", ""], "尾款交付",
                                   targets=["尾款交付"], run_index=1)

        self.assertEqual(hits, ["尾款交付"])
        self.assertEqual(self.sampler.screen_index, 1)
        self.assertEqual(self.sampler.seen["尾款交付"], 1)
        self.assertEqual(self.sampler.first_plane["特战资金"], 2)

        with open(self.csv, encoding="utf-8") as handle:
            rows = list(csv.reader(handle))
        self.assertEqual(rows[0][0], "时间")
        self.assertEqual(rows[1][2], "2")
        self.assertEqual(rows[1][3], "尾款交付|特战资金")
        self.assertEqual(rows[1][4], "尾款交付")

    def test_empty_screen_is_ignored(self):
        self.assertEqual(self.sampler.record(1, ["", "", ""]), [])
        self.assertEqual(self.sampler.screen_index, 0)

    def test_missing_lists_whole_roster(self):
        self.sampler.record(1, ["尾款交付"], None)
        missing = self.sampler.missing()
        self.assertEqual(len(missing), len(STRATEGY_NAMES) - 1)
        self.assertNotIn("尾款交付", missing)


class StrategyChoiceTest(unittest.TestCase):
    @staticmethod
    def make(targets=(), avoid=()):
        currency = object.__new__(SimulatedCurrency)
        currency.strategy_targets = list(targets)
        currency.strategy_avoid = list(avoid)
        return currency

    def test_target_beats_unlocked_icon(self):
        currency = self.make(targets=["尾款交付"])
        pick, reason = currency._pick_strategy(
            ["特战资金", "尾款交付", "尾款交付+".replace("+", "")],
            [True, False, False],
        )
        self.assertEqual(pick, 1)
        self.assertIn("目标", reason)

    def test_avoid_is_never_chosen_even_with_unlocked_icon(self):
        currency = self.make(avoid=["特战资金"])
        pick, reason = currency._pick_strategy(
            ["特战资金", "轮回不止", ""],
            [True, True, False],
        )
        self.assertEqual(pick, 1)        # 有图标的负面策略被跳过
        self.assertNotEqual(reason, "fallback")

    def test_all_avoid_falls_back_to_something(self):
        currency = self.make(avoid=["特战资金", "尾款交付", "经验到账"])
        pick, reason = currency._pick_strategy(
            ["特战资金", "尾款交付", "经验到账"],
            [False, False, False],
        )
        self.assertIsNotNone(pick)
        self.assertEqual(reason, "fallback")

    def test_empty_screen_returns_none(self):
        currency = self.make()
        self.assertEqual(currency._pick_strategy(["", "", ""], [False] * 3), (None, "empty"))


class StrategySettingsTest(unittest.TestCase):
    def test_new_fields_default_and_sanitised(self):
        values = normalize_currency_settings({})
        self.assertEqual(values["strategy_targets"], [])
        self.assertEqual(values["strategy_avoid"], [])
        self.assertFalse(values["auto_exit_plane"])

        values = normalize_currency_settings({
            "strategy_targets": ["尾款交付", "尾款交付", "", 3],
            "strategy_avoid": ["特战资金"],
            "auto_exit_plane": True,
        })
        self.assertEqual(values["strategy_targets"], ["尾款交付"])
        self.assertEqual(values["strategy_avoid"], ["特战资金"])
        self.assertTrue(values["auto_exit_plane"])


if __name__ == "__main__":
    unittest.main()
