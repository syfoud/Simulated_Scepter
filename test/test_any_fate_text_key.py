"""静态事件数据：命途顺序、祝福/奇物/事件优先级与交互词表。

这些数据原先分散在 core/simulated/config/default.json 与 core/simulated/text_key.py，
现在集中到 core/any_fate/text_key.py。祝福数据的顺序与 FATES 一一对应，顺序错位会让
各内核的命途索引整体偏移，因此这里锁定顺序和取值来源。
"""

import re
import unittest
from pathlib import Path

from core.any_fate.text_key import (
    BLESSES,
    FATES,
    INTERACTS,
    PRIOR_BLESS,
    SECONDARY,
    text_keys,
)

ROOT = Path(__file__).resolve().parents[1]


class FateDataTest(unittest.TestCase):
    def test_fates_keep_the_game_order(self):
        self.assertEqual(len(FATES), 9)
        self.assertEqual(
            FATES,
            ["存护", "记忆", "虚无", "丰饶", "巡猎", "毁灭", "欢愉", "繁育", "智识"],
        )
        # 默认下标 4 必须是巡猎：AnyFate 未指定命途时使用该默认值
        self.assertEqual(FATES[4], "巡猎")

    def test_each_fate_has_its_own_blessing_list(self):
        self.assertEqual(len(BLESSES), len(FATES))
        for fate, blessings in zip(FATES, BLESSES, strict=True):
            self.assertGreater(len(blessings), 0, fate)
            self.assertTrue(all(isinstance(item, str) and item for item in blessings), fate)

    def test_shared_glossary_entries_are_present(self):
        self.assertIn("火堆外的夜", PRIOR_BLESS)
        self.assertEqual(SECONDARY, ["毁灭", "巡猎", "丰饶"])
        for word in ("黑塔", "区域", "事件", "退出", "复活", "觐见", "挑战"):
            self.assertIn(word, INTERACTS)


class TextKeysTest(unittest.TestCase):
    def test_prior_bless_starts_with_the_shared_prefix_then_the_fate_list(self):
        for index, fate in enumerate(FATES):
            with self.subTest(fate=fate):
                keys = text_keys(index)
                self.assertEqual(keys.fate, index)
                self.assertEqual(keys.fates, list(FATES))
                self.assertEqual(keys.prior_bless, list(PRIOR_BLESS) + list(BLESSES[index]))
                self.assertEqual(keys.secondary, [fate] + list(SECONDARY))
                self.assertEqual(keys.interacts, list(INTERACTS))

    def test_skip_flag_follows_the_regression_inequality_rule(self):
        """祝福优先级里出现「回归不等式」时不跳过它（skip=0），否则跳过首项（skip=1）。"""
        for index in range(len(FATES)):
            with self.subTest(index=index):
                keys = text_keys(index)
                expected = 0 if any("回归不等式" in item for item in keys.prior_bless) else 1
                self.assertEqual(keys.skip, expected)

    def test_default_argument_uses_the_hunting_fate(self):
        self.assertEqual(text_keys().fate, FATES.index("巡猎"))

    def test_blessing_lists_are_copied_per_instance(self):
        first = text_keys(0)
        first.blesses[0].append("被改动的条目")
        self.assertNotIn("被改动的条目", text_keys(0).blesses[0])


class StaticConfigSourceTest(unittest.TestCase):
    def test_text_key_does_not_read_module_config_any_more(self):
        """数据改为静态常量后不再依赖 module.ini / default.json 的 prior/secondary_fate。"""
        source = (ROOT / "core" / "any_fate" / "text_key.py").read_text(encoding="utf-8")
        self.assertIsNone(re.search(r"config_path|load_module_settings|default\.json", source))


if __name__ == "__main__":
    unittest.main()
