import tempfile
import unittest
from pathlib import Path

from core.currency.run_history import (
    CurrencyRunHistory,
    get_newly_unlocked_investment,
)


class FakeClock:
    def __init__(self, current: float = 0):
        self.current = current

    def __call__(self) -> float:
        return self.current


class CurrencyRunHistoryTests(unittest.TestCase):
    def create_history(self, directory: str, clock: FakeClock) -> CurrencyRunHistory:
        return CurrencyRunHistory(Path(directory) / "currency_count.txt", clock)

    def test_writes_unlocked_investments_and_elapsed_time(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            clock = FakeClock(100)
            history = self.create_history(temp_dir, clock)

            history.start_run()
            self.assertTrue(history.record_unlocked_investment("投资策略甲"))
            self.assertTrue(history.record_unlocked_investment("投资策略乙"))
            self.assertFalse(history.record_unlocked_investment("投资策略甲"))
            clock.current = 225

            record = history.finish_run()

            self.assertEqual(
                record,
                "对局次数：1，本局解锁的投资策略：投资策略甲、投资策略乙，用时：2分5秒",
            )
            self.assertEqual(
                (Path(temp_dir) / "currency_count.txt").read_text(encoding="utf-8"),
                record + "\n",
            )

    def test_writes_none_when_no_investment_was_unlocked(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            clock = FakeClock(10)
            history = self.create_history(temp_dir, clock)
            history.start_run()
            clock.current = 11

            record = history.finish_run()

            self.assertEqual(
                record,
                "对局次数：1，本局解锁的投资策略：无，用时：0分1秒",
            )

    def test_continues_from_largest_persisted_run_count(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "currency_count.txt"
            path.write_text(
                "对局次数：2，本局解锁的投资策略：无，用时：1分0秒\n"
                "无法识别的旧记录\n"
                "对局次数:5, 本局解锁的投资策略:无, 用时:2分0秒\n",
                encoding="utf-8",
            )
            clock = FakeClock()
            history = CurrencyRunHistory(path, clock)
            history.start_run()

            record = history.finish_run()

            self.assertTrue(record.startswith("对局次数：6，"))

    def test_new_start_discards_an_unfinished_run(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            clock = FakeClock(10)
            history = self.create_history(temp_dir, clock)
            history.start_run()
            history.record_unlocked_investment("投资策略甲")
            clock.current = 40

            history.start_run()
            clock.current = 70
            record = history.finish_run()

            self.assertIn("本局解锁的投资策略：无", record)
            self.assertTrue(record.endswith("用时：0分30秒"))

    def test_ignores_unlock_and_finish_before_run_starts(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            clock = FakeClock()
            history = self.create_history(temp_dir, clock)

            self.assertFalse(history.record_unlocked_investment("投资策略甲"))
            self.assertIsNone(history.finish_run())
            self.assertFalse((Path(temp_dir) / "currency_count.txt").exists())


class NewlyUnlockedInvestmentTests(unittest.TestCase):
    def test_returns_selected_text_when_icon_is_present(self):
        self.assertEqual(
            get_newly_unlocked_investment(
                ["投资策略甲", "投资策略乙", "投资策略丙"],
                [False, True, False],
                1,
            ),
            "投资策略乙",
        )

    def test_ignores_selected_text_without_icon(self):
        self.assertIsNone(
            get_newly_unlocked_investment(
                ["投资策略甲", "投资策略乙", "投资策略丙"],
                [False, False, False],
                1,
            )
        )

    def test_ignores_invalid_or_blank_selection(self):
        self.assertIsNone(get_newly_unlocked_investment(["投资策略甲"], [True], -1))
        self.assertIsNone(get_newly_unlocked_investment([""], [True], 0))


if __name__ == "__main__":
    unittest.main()
