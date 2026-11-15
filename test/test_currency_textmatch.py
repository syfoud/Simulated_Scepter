import unittest

from core.currency.automation import SimulatedCurrency
from core.currency.envirs import ENVIR_NAMES
from core.currency.textmatch import best_match, normalize, similar


class TextMatchTests(unittest.TestCase):
    def test_normalize_strips_separators(self):
        self.assertEqual(normalize("银•金•彩"), "银金彩")
        self.assertEqual(normalize(" 银 · 金 彩 "), "银金彩")

    def test_similar_tolerates_one_wrong_char_in_long_names(self):
        self.assertTrue(similar("银•金•彩", "银金彩"))
        self.assertTrue(similar("彩虹时伐", "彩虹时代"))
        self.assertFalse(similar("蓝海", "蓝钻贵族"))

    def test_best_match_recovers_ocr_variants(self):
        self.assertEqual(best_match("银金彩", ENVIR_NAMES), "银•金•彩")
        self.assertEqual(best_match("彩虹时伐", ENVIR_NAMES), "彩虹时代")
        self.assertEqual(best_match("蓝海", ENVIR_NAMES), "蓝海")
        self.assertIsNone(best_match("完全不存在的名字啊啊", ENVIR_NAMES))

    def test_two_char_names_require_exact_match(self):
        # 短名字容错会把「头彩/尾彩」搅在一起，宁可让 OCR 自己认准
        self.assertIsNone(best_match("头採", ENVIR_NAMES))
        self.assertEqual(best_match("头彩", ENVIR_NAMES), "头彩")

    def test_canonical_environments_keeps_unknown_text(self):
        self.assertEqual(
            SimulatedCurrency.canonical_environments(["银金彩", "彩虹时伐", "看不懂的字"]),
            ["银•金•彩", "彩虹时代", "看不懂的字"],
        )


if __name__ == "__main__":
    unittest.main()
