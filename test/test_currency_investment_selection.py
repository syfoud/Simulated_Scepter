import unittest

from core.currency.investment_selection import choose_fallback_investment


class InvestmentFallbackSelectionTests(unittest.TestCase):
    def test_middle_reincarnation_with_icon_keeps_original_middle_choice(self):
        selected = choose_fallback_investment(
            ["普通投资甲", "轮回不止", "普通投资乙"],
            [False, True, False],
        )

        self.assertEqual(selected, 1)

    def test_middle_reincarnation_without_icon_uses_left_choice(self):
        selected = choose_fallback_investment(
            ["普通投资甲", "轮回不止", "普通投资乙"],
            [False, False, False],
        )

        self.assertEqual(selected, 0)

    def test_normal_middle_option_keeps_original_fallback(self):
        selected = choose_fallback_investment(
            ["普通投资甲", "普通投资乙", "普通投资丙"],
            [False, False, False],
        )

        self.assertEqual(selected, 1)

    def test_side_reincarnation_does_not_change_middle_fallback(self):
        selected = choose_fallback_investment(
            ["轮回不止", "普通投资甲", "普通投资乙"],
            [False, False, False],
        )

        self.assertEqual(selected, 1)


if __name__ == "__main__":
    unittest.main()
