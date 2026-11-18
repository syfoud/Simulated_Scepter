"""带搜索框的勾选列表：过滤不改勾选状态，写回顺序保持名单顺序。"""

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtWidgets import QApplication  # noqa: E402

from core.currency.checkbox_list_ui import SearchableCheckList  # noqa: E402


class SearchableCheckListTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def make_list(self, selected=()):
        return SearchableCheckList(
            ["军火贸易", "大裁员", "星徽大使叽米", "期货"], selected=selected)

    def test_filter_hides_non_matching_and_keeps_selection(self):
        widget = self.make_list(selected=["军火贸易"])
        widget.apply_filter("军火")
        self.assertTrue(widget.checkboxes["军火贸易"].isVisibleTo(widget))
        self.assertFalse(widget.checkboxes["大裁员"].isVisibleTo(widget))
        # 过滤不影响已勾选项
        self.assertEqual(widget.selected_names(), ["军火贸易"])

    def test_empty_keyword_shows_everything(self):
        widget = self.make_list(selected=["大裁员"])
        widget.apply_filter("军火")
        widget.apply_filter("")
        self.assertTrue(all(box.isVisibleTo(widget)
                            for box in widget.checkboxes.values()))
        self.assertEqual(widget.selected_names(), ["大裁员"])

    def test_selection_keeps_source_order(self):
        widget = self.make_list()
        widget.set_selected(["期货", "军火贸易"])
        self.assertEqual(widget.selected_names(), ["军火贸易", "期货"])

    def test_counter_reports_both_numbers(self):
        widget = self.make_list(selected=["军火贸易", "期货"])
        widget.apply_filter("期货")
        text = widget.counter.text()
        self.assertIn("已选 2 项", text)
        self.assertIn("显示 1 项", text)


if __name__ == "__main__":
    unittest.main()
