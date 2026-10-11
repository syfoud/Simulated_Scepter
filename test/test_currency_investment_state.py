import unittest

from core.currency.investment_state import (
    InvestmentSelectionTracker,
    SelectionKind,
)


class InvestmentSelectionTrackerTests(unittest.TestCase):
    def complete(
        self,
        tracker: InvestmentSelectionTracker,
        expected_kind: SelectionKind,
        grants_bonus: bool = False,
    ) -> None:
        context = tracker.begin_selection()
        self.assertEqual(expected_kind, context.kind)
        tracker.complete_selection(context, grants_bonus=grants_bonus)

    def test_first_plane_bonus_finishes_before_second_plane_exit(self):
        tracker = InvestmentSelectionTracker()

        self.complete(tracker, SelectionKind.NORMAL, grants_bonus=True)
        self.assertEqual(1, tracker.plane_count)
        self.assertFalse(tracker.should_exit(2))

        self.complete(tracker, SelectionKind.IMMEDIATE_BONUS)
        self.complete(tracker, SelectionKind.DELAYED_BONUS)
        self.complete(tracker, SelectionKind.NORMAL)

        self.assertEqual(2, tracker.plane_count)
        self.assertTrue(tracker.should_exit(2))

    def test_bonus_from_delayed_choice_runs_after_second_normal_choice(self):
        tracker = InvestmentSelectionTracker()

        self.complete(tracker, SelectionKind.NORMAL, grants_bonus=True)
        self.complete(tracker, SelectionKind.IMMEDIATE_BONUS)

        self.complete(tracker, SelectionKind.DELAYED_BONUS, grants_bonus=True)
        self.complete(tracker, SelectionKind.IMMEDIATE_BONUS)

        self.complete(tracker, SelectionKind.NORMAL)
        self.assertEqual(2, tracker.plane_count)
        self.assertEqual(1, tracker.delayed_count)
        self.assertTrue(tracker.should_exit(2))
        self.assertFalse(tracker.should_exit(3))

        self.complete(tracker, SelectionKind.DELAYED_BONUS)
        self.complete(tracker, SelectionKind.NORMAL)

        self.assertEqual(3, tracker.plane_count)
        self.assertTrue(tracker.should_exit(3))

    def test_exit_plane_does_not_wait_for_future_delayed_bonus(self):
        tracker = InvestmentSelectionTracker()

        self.complete(tracker, SelectionKind.NORMAL, grants_bonus=True)
        self.assertFalse(tracker.should_exit(1))

        self.complete(tracker, SelectionKind.IMMEDIATE_BONUS)

        self.assertEqual(1, tracker.delayed_count)
        self.assertTrue(tracker.should_exit(1))

    def test_same_boundary_can_queue_multiple_delayed_bonuses(self):
        tracker = InvestmentSelectionTracker()

        self.complete(tracker, SelectionKind.NORMAL, grants_bonus=True)
        self.complete(
            tracker,
            SelectionKind.IMMEDIATE_BONUS,
            grants_bonus=True,
        )

        self.assertEqual(1, tracker.immediate_count)
        self.assertEqual(2, tracker.delayed_count)
        self.complete(tracker, SelectionKind.IMMEDIATE_BONUS)

        first_delayed = tracker.begin_selection()
        self.assertEqual(SelectionKind.DELAYED_BONUS, first_delayed.kind)
        tracker.complete_selection(first_delayed)

        second_delayed = tracker.begin_selection()
        self.assertEqual(SelectionKind.DELAYED_BONUS, second_delayed.kind)
        self.assertEqual(first_delayed.boundary, second_delayed.boundary)
        tracker.complete_selection(second_delayed)

        self.assertEqual(SelectionKind.NORMAL, tracker.begin_selection().kind)

    def test_nested_immediate_blocks_exit_until_chain_finishes(self):
        tracker = InvestmentSelectionTracker()

        self.complete(tracker, SelectionKind.NORMAL, grants_bonus=True)
        self.assertFalse(tracker.should_exit(1))

        self.complete(
            tracker,
            SelectionKind.IMMEDIATE_BONUS,
            grants_bonus=True,
        )
        self.assertEqual(1, tracker.plane_count)
        self.assertEqual(1, tracker.immediate_count)
        self.assertFalse(tracker.should_exit(1))

        self.complete(tracker, SelectionKind.IMMEDIATE_BONUS)
        self.assertTrue(tracker.should_exit(1))

    def test_bonus_selections_never_increment_plane_count(self):
        tracker = InvestmentSelectionTracker()

        self.complete(tracker, SelectionKind.NORMAL, grants_bonus=True)
        self.assertEqual(1, tracker.plane_count)

        self.complete(tracker, SelectionKind.IMMEDIATE_BONUS)
        self.assertEqual(1, tracker.plane_count)

        self.complete(tracker, SelectionKind.DELAYED_BONUS)
        self.assertEqual(1, tracker.plane_count)

    def test_reset_discards_previous_run_state(self):
        tracker = InvestmentSelectionTracker()
        self.complete(tracker, SelectionKind.NORMAL, grants_bonus=True)

        tracker.reset()

        self.assertEqual(0, tracker.plane_count)
        self.assertEqual(0, tracker.immediate_count)
        self.assertEqual(0, tracker.delayed_count)
        self.assertEqual(SelectionKind.NORMAL, tracker.begin_selection().kind)


if __name__ == "__main__":
    unittest.main(verbosity=2)
