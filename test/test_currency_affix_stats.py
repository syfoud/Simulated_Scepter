import json
import os
import tempfile
import unittest

from core.currency.affixes import AFFIX_NAMES, ordered_selection
from core.currency.affix_stats import AffixSampler
from core.currency.envirs import ENVIR_NAMES
from core.currency.settings import PRIORITY_KEYS, normalize_currency_settings


class AffixSamplerTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.csv = os.path.join(self.temp.name, "affix_samples.csv")
        self.summary = os.path.join(self.temp.name, "affix_summary.txt")
        self.sampler = AffixSampler(self.csv, self.summary)

    def tearDown(self):
        self.temp.cleanup()

    def test_record_counts_and_returns_hits(self):
        self.assertEqual(self.sampler.record(["战个痛快", "重复熄火"], ["复仇心切"]), [])
        self.assertEqual(self.sampler.record(["复仇心切", "战个痛快"], ["复仇心切"]), ["复仇心切"])

        self.assertEqual(self.sampler.run_index, 2)
        self.assertEqual(self.sampler.counter["战个痛快"], 2)
        self.assertEqual(self.sampler.counter["复仇心切"], 1)

        with open(self.csv, encoding="utf-8") as handle:
            lines = [line.rstrip("\n") for line in handle]
        self.assertEqual(lines[0], "时间,把次,词缀,命中目标")
        self.assertEqual(len(lines), 3)
        self.assertIn("1,战个痛快|重复熄火,", lines[1])
        self.assertIn("2,复仇心切|战个痛快,复仇心切", lines[2])

    def test_empty_run_is_ignored(self):
        self.assertEqual(self.sampler.record([], ["复仇心切"]), [])
        self.assertEqual(self.sampler.run_index, 0)
        self.assertFalse(os.path.exists(self.csv))

    def test_summary_marks_targets_even_when_missing(self):
        self.sampler.record(["战个痛快"], ["复仇心切", "战个痛快"])
        with open(self.summary, encoding="utf-8") as handle:
            text = handle.read()
        self.assertIn("累计 1 把", text)
        self.assertIn("战个痛快  ← 目标", text)
        self.assertIn("尚未出现", text)
        self.assertIn("复仇心切  ← 目标", text)


class CurrencyAffixSettingsTest(unittest.TestCase):
    def test_new_fields_default(self):
        values = normalize_currency_settings({})
        self.assertEqual(values["gamemode"], "overclock")
        self.assertEqual(values["difficulty_mode"], "lowest")
        self.assertFalse(values["gather_mode"])
        self.assertEqual(values["max_runs"], 0)
        self.assertEqual(values["affix_targets"], [])

    def test_invalid_values_fall_back(self):
        values = normalize_currency_settings({
            "gamemode": "unknown",
            "difficulty_mode": 42,
            "max_runs": -5,
            "gather_mode": "yes",
            "affix_targets": ["复仇心切", "", 3, " 复仇心切 ", "沉重脚步"],
        })
        self.assertEqual(values["gamemode"], "overclock")
        self.assertEqual(values["difficulty_mode"], "lowest")
        self.assertEqual(values["max_runs"], 0)
        self.assertFalse(values["gather_mode"])
        self.assertEqual(values["affix_targets"], ["复仇心切", "沉重脚步"])

    def test_valid_values_round_trip(self):
        values = normalize_currency_settings({
            "gamemode": "STANDARD",
            "difficulty_mode": "top",
            "gather_mode": True,
            "max_runs": 1000,
            "affix_targets": ["复仇心切"],
        })
        self.assertEqual(values["gamemode"], "standard")
        self.assertEqual(values["difficulty_mode"], "top")
        self.assertTrue(values["gather_mode"])
        self.assertEqual(values["max_runs"], 1000)
        json.dumps(values)  # 必须可序列化，才能写回配置文件

    def test_affix_names_cover_current_season(self):
        self.assertEqual(len(AFFIX_NAMES), 53)
        self.assertEqual(len(set(AFFIX_NAMES)), len(AFFIX_NAMES))
        for name in ("复仇心切", "侵蚀·第一位面强化", "战个痛快", "吸星魔王"):
            self.assertIn(name, AFFIX_NAMES)

    def test_ordered_selection_follows_table_order(self):
        self.assertEqual(
            ordered_selection({"战个痛快", "首领强化", "复仇心切"}),
            ["首领强化", "复仇心切", "战个痛快"],
        )
        self.assertEqual(ordered_selection([]), [])

    def test_envir_names_cover_current_season(self):
        self.assertEqual(len(ENVIR_NAMES), 72)
        self.assertEqual(len(set(ENVIR_NAMES)), len(ENVIR_NAMES))
        for name in ("蓝海", "银•金•彩", "火药味", "尾彩"):
            self.assertIn(name, ENVIR_NAMES)

    def test_priority_keys_cover_every_envir_level(self):
        self.assertEqual(
            PRIORITY_KEYS,
            ("prior_envir", "envir_1", "envir_2", "envir_3", "envir_4"),
        )
        # 勾选表格按 PRIORITY_KEYS 生成列，两种数据源不能错位
        values = normalize_currency_settings({"priority": {"envir_2": ["蓝海"]}})
        self.assertEqual(values["priority"]["envir_2"], ["蓝海"])
        self.assertEqual(values["priority"]["envir_1"], [])


if __name__ == "__main__":
    unittest.main()
