"""验证到期、空闲等待、重复推进和配置界面；执行入口用替身隔离。"""

import json
import tempfile
import unittest
from dataclasses import asdict, replace
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from PyQt5.QtCore import QDateTime
from PyQt5.QtWidgets import QApplication, QMessageBox

from route import PATHS
from tool.gui.schedule_dialog import ScheduleDialog, ScheduleTimer
from tool.gui.script_editor import new_event
from tool.schedule import Plan, ScheduleBook
from tool.script_files import save_script


class ScheduleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        self.enterContext(patch.dict(PATHS, {"root": str(self.root), "config": str(self.root / "config")}))
        self.path = self.root / "config/schedules.json"
        self.script = self.root / "actions/job.json"
        save_script(self.script, [new_event()])
        self.now = datetime.now().replace(microsecond=0) + timedelta(days=2)
        self.book = ScheduleBook(self.path)
        self.registry = Mock()
        self.spec = SimpleNamespace(id="Custom", name="测试内核", folder=self.root / "core/custom")
        self.registry.runnable.return_value = [self.spec]
        self.registry.specs = {"Custom": self.spec}
        self.launch = Mock()
        self.busy = Mock(return_value=False)
        self.stop = Mock()

    def plan(self, *, when=None, repeat="once", engine="Custom"):
        return Plan.create("测试计划", engine, "actions/job.json", when or self.now, repeat)

    def scheduler(self):
        timer = ScheduleTimer(self.registry, self.launch, self.busy, self.stop, path=self.path)
        timer.timer.stop()
        self.addCleanup(timer.deleteLater)
        return timer

    def test_once_due_is_persisted_before_launch_and_never_repeated(self):
        plan = self.plan()
        self.book.put(plan)
        timer = self.scheduler()
        def inspect_claim(*_):
            persisted = ScheduleBook(self.path).plans[0]
            self.assertFalse(persisted.enabled)
            self.assertEqual(persisted.result, "已触发")
        self.launch.side_effect = inspect_claim
        timer.poll(self.now - timedelta(seconds=1))
        self.launch.assert_not_called()
        timer.poll(self.now)
        self.launch.assert_called_once_with("Custom", str(self.script))
        timer.poll(self.now + timedelta(seconds=10))
        self.scheduler().poll(self.now + timedelta(seconds=20))
        self.assertEqual(self.launch.call_count, 1)

    def test_busy_task_defers_without_consuming_occurrence(self):
        self.book.put(self.plan())
        timer = self.scheduler()
        self.busy.return_value = True
        timer.poll(self.now)
        self.launch.assert_not_called()
        waiting = ScheduleBook(self.path).plans[0]
        self.assertTrue(waiting.enabled)
        self.assertEqual(waiting.result, "等待当前任务结束")
        before = self.path.read_bytes()
        timer.poll(self.now + timedelta(seconds=1))
        self.assertEqual(self.path.read_bytes(), before)
        self.busy.return_value = False
        timer.poll(self.now + timedelta(seconds=2))
        self.launch.assert_called_once()
        self.stop.assert_not_called()

    def test_old_plan_without_interruptible_field_defaults_to_queue(self):
        data = asdict(self.plan())
        data.pop("interruptible")
        self.path.parent.mkdir()
        self.path.write_text(json.dumps([data]), encoding="utf-8")
        self.assertFalse(ScheduleBook(self.path).plans[0].interruptible)

    def test_enabled_interrupt_stops_once_and_waits_for_thread_exit(self):
        first = replace(self.plan(), id="a", interruptible=True)
        second = replace(self.plan(when=self.now + timedelta(seconds=1)), id="b")
        self.book.put(first)
        self.book.put(second)
        timer = self.scheduler()
        timer.poll(self.now)
        self.busy.return_value = True
        timer.poll(self.now + timedelta(seconds=1))
        self.stop.assert_called_once()
        self.assertEqual(self.launch.call_count, 1)
        self.assertTrue(timer.book.plans[1].enabled)
        timer.poll(self.now + timedelta(seconds=2))
        self.stop.assert_called_once()
        self.assertEqual(self.launch.call_count, 1)
        self.busy.return_value = False
        timer.poll(self.now + timedelta(seconds=3))
        self.assertEqual(self.launch.call_count, 2)
        self.assertIn("已退出", timer.book.plans[0].result)

    def test_incoming_option_cannot_interrupt_unchecked_running_plan(self):
        self.book.put(replace(self.plan(), id="a"))
        self.book.put(replace(self.plan(when=self.now + timedelta(seconds=1)), id="b", interruptible=True))
        timer = self.scheduler()
        timer.poll(self.now)
        self.busy.return_value = True
        timer.poll(self.now + timedelta(seconds=2))
        self.stop.assert_not_called()
        self.assertEqual(self.launch.call_count, 1)

    def test_saving_interrupt_option_applies_to_current_plan_and_waiting_tasks(self):
        self.book.put(self.plan())
        timer = self.scheduler()
        timer.poll(self.now)
        self.busy.return_value = True
        timer.queue_task(Mock())
        self.stop.assert_not_called()
        timer.book.put(replace(timer.book.plans[0], interruptible=True))
        timer.poll(self.now)
        self.stop.assert_called_once()
        self.assertEqual(self.launch.call_count, 1)

    def test_failed_stop_record_pauses_dispatch_and_preserves_running_task(self):
        self.book.put(replace(self.plan(), interruptible=True))
        timer = self.scheduler()
        timer.poll(self.now)
        self.busy.return_value = True
        before = self.path.read_bytes()
        with patch("tool.storage.os.replace", side_effect=OSError("计划文件只读")):
            timer.queue_task(Mock())
        self.stop.assert_not_called()
        self.assertEqual(self.launch.call_count, 1)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertTrue(timer.pending)
        self.assertIn("已停止", timer.error)

    def test_failed_stop_record_from_due_plan_does_not_retry_writing_wait_status(self):
        self.book.put(replace(self.plan(), interruptible=True))
        self.book.put(self.plan(when=self.now + timedelta(seconds=1)))
        timer = self.scheduler()
        timer.poll(self.now)
        self.busy.return_value = True
        with patch("tool.storage.os.replace", side_effect=OSError("计划文件只读")) as write:
            timer.poll(self.now + timedelta(seconds=1))
        write.assert_called_once()
        self.stop.assert_not_called()
        self.assertEqual(self.launch.call_count, 1)
        self.assertTrue(timer.book.plans[1].enabled)
        self.assertIn("已停止", timer.error)

    def test_same_daily_plan_next_occurrence_does_not_interrupt_itself(self):
        self.book.put(replace(self.plan(repeat="daily"), interruptible=True))
        timer = self.scheduler()
        timer.poll(self.now)
        self.busy.return_value = True
        timer.poll(self.now + timedelta(days=1))
        self.stop.assert_not_called()
        self.assertEqual(self.launch.call_count, 1)

    def test_unavailable_due_plan_does_not_interrupt_valid_running_plan(self):
        self.book.put(replace(self.plan(), id="a", interruptible=True))
        self.book.put(replace(self.plan(when=self.now + timedelta(seconds=1), engine="Removed"), id="b"))
        timer = self.scheduler()
        timer.poll(self.now)
        self.busy.return_value = True
        timer.poll(self.now + timedelta(seconds=2))
        self.stop.assert_not_called()
        self.assertEqual(self.launch.call_count, 1)
        self.assertIn("启动失败", timer.book.plans[1].result)

    def test_stop_error_never_launches_parallel_task_or_repeats_stop(self):
        self.book.put(replace(self.plan(), id="a", interruptible=True))
        self.book.put(replace(self.plan(when=self.now + timedelta(seconds=1)), id="b"))
        timer = self.scheduler()
        timer.poll(self.now)
        self.busy.return_value = True
        self.stop.side_effect = RuntimeError("模拟停止失败")
        timer.poll(self.now + timedelta(seconds=2))
        timer.poll(self.now + timedelta(seconds=3))
        self.stop.assert_called_once()
        self.assertEqual(self.launch.call_count, 1)
        self.assertIn("停止请求未完成", timer.book.plans[0].result)

    def test_manual_submission_respects_current_plan_option_and_fifo(self):
        for interruptible in (False, True):
            with self.subTest(interruptible=interruptible):
                self.book.save([replace(self.plan(), interruptible=interruptible)])
                self.busy.return_value = False
                self.stop.reset_mock()
                timer = self.scheduler()
                timer.poll(self.now)
                self.busy.return_value = True
                calls = []
                timer.queue_task(lambda: calls.append("first"))
                timer.queue_task(lambda: calls.append("second"))
                self.assertEqual(self.stop.call_count, int(interruptible))
                timer.poll(self.now)
                self.assertEqual(calls, [])
                self.busy.return_value = False
                timer.poll(self.now)
                timer.poll(self.now)
                self.assertEqual(calls, ["first", "second"])

    def test_manual_running_task_has_no_plan_permission_to_interrupt(self):
        self.book.put(replace(self.plan(), interruptible=True))
        timer = self.scheduler()
        self.busy.return_value = True
        timer.poll(self.now)
        self.stop.assert_not_called()
        self.launch.assert_not_called()

    def test_dispatch_flag_is_reset_after_callback_failure(self):
        timer = self.scheduler()
        queued = Mock(side_effect=RuntimeError("模拟手动启动失败"))
        timer.queue_task(queued)
        timer.poll(self.now)
        self.assertFalse(timer.dispatching)
        self.assertFalse(timer.pending)
        queued.assert_called_once()

    def test_daily_preserves_clock_time_and_skips_elapsed_days(self):
        self.book.put(self.plan(repeat="daily"))
        timer = self.scheduler()
        timer.poll(self.now + timedelta(days=3, hours=1))
        plan = ScheduleBook(self.path).plans[0]
        self.assertTrue(plan.enabled)
        self.assertEqual(datetime.fromisoformat(plan.run_at), self.now + timedelta(days=4))
        self.assertEqual(self.launch.call_count, 1)

    def test_weekly_triggers_once_and_persists_next_week_before_launch(self):
        self.book.put(self.plan(repeat="weekly"))
        timer = self.scheduler()

        def inspect_claim(*_):
            saved = ScheduleBook(self.path).plans[0]
            self.assertTrue(saved.enabled)
            self.assertEqual(saved.repeat, "weekly")
            self.assertEqual(saved.last_run, self.now.isoformat(timespec="seconds"))
            self.assertEqual(datetime.fromisoformat(saved.run_at), self.now + timedelta(days=7))

        self.launch.side_effect = inspect_claim
        timer.poll(self.now - timedelta(seconds=1))
        self.launch.assert_not_called()
        timer.poll(self.now)
        timer.poll(self.now + timedelta(days=7) - timedelta(seconds=1))
        self.launch.assert_called_once_with("Custom", str(self.script))
        self.launch.side_effect = None
        timer.poll(self.now + timedelta(days=7))
        self.assertEqual(self.launch.call_count, 2)
        self.assertEqual(datetime.fromisoformat(ScheduleBook(self.path).plans[0].run_at), self.now + timedelta(days=14))

    def test_weekly_advance_preserves_weekday_and_time_across_missed_weeks_and_years(self):
        cases = [
            (self.now, self.now + timedelta(days=3, hours=1), self.now + timedelta(days=7)),
            (self.now, self.now + timedelta(days=7) - timedelta(seconds=1), self.now + timedelta(days=7)),
            (self.now, self.now + timedelta(days=7), self.now + timedelta(days=14)),
            (self.now, self.now + timedelta(days=35), self.now + timedelta(days=42)),
            (datetime(2026, 12, 28, 8), datetime(2027, 1, 1, 9), datetime(2027, 1, 4, 8)),
            (datetime(2024, 2, 26, 8), datetime(2024, 3, 1, 9), datetime(2024, 3, 4, 8)),
        ]
        for when, now, expected in cases:
            with self.subTest(when=when, now=now):
                plan = self.plan(when=when, repeat="weekly")
                self.book.claim(plan, now)
                saved = ScheduleBook(self.path).plans[-1]
                self.assertTrue(saved.enabled)
                self.assertEqual(datetime.fromisoformat(saved.run_at), expected)
                self.assertEqual(expected.weekday(), when.weekday())
                self.assertEqual(expected.time(), when.time())

    def test_restart_skips_missed_weekly_occurrences_and_preserves_future_plan(self):
        now = datetime.now().replace(microsecond=0)
        missed = self.plan(when=now - timedelta(days=17), repeat="weekly")
        future = self.plan(when=now + timedelta(days=3), repeat="weekly")
        self.book.put(missed)
        self.book.put(future)
        timer = self.scheduler()
        saved = ScheduleBook(self.path).plans
        self.assertTrue(saved[0].enabled)
        self.assertIn("未补跑", saved[0].result)
        self.assertEqual(datetime.fromisoformat(saved[0].run_at), now + timedelta(days=4))
        self.assertEqual(saved[1], future)
        timer.poll(now)
        self.launch.assert_not_called()

    def test_same_weekly_plan_next_occurrence_does_not_interrupt_itself(self):
        self.book.put(replace(self.plan(repeat="weekly"), interruptible=True))
        timer = self.scheduler()
        timer.poll(self.now)
        self.busy.return_value = True
        timer.poll(self.now + timedelta(days=7))
        self.stop.assert_not_called()
        self.assertEqual(self.launch.call_count, 1)

    def test_restart_skips_missed_once_and_advances_daily(self):
        once = self.plan(when=self.now - timedelta(days=3))
        daily = self.plan(when=self.now - timedelta(days=3), repeat="daily")
        self.book.put(once)
        self.book.put(daily)
        self.book.skip_missed(self.now)
        self.assertFalse(self.book.plans[0].enabled)
        self.assertIn("未补跑", self.book.plans[0].result)
        self.assertEqual(datetime.fromisoformat(self.book.plans[1].run_at), self.now + timedelta(days=1))

    def test_removed_kernel_does_not_block_other_due_plans(self):
        invalid = replace(self.plan(engine="Removed"), id="a")
        valid = replace(self.plan(), id="b")
        self.book.put(invalid)
        self.book.put(valid)
        timer = self.scheduler()
        timer.poll(self.now)
        self.launch.assert_called_once_with("Custom", str(self.script))
        self.assertIn("内核", timer.book.plans[0].result)
        self.assertEqual(timer.book.plans[1].result, "已触发")

    def test_deleted_script_records_failure_without_launch(self):
        self.book.put(self.plan())
        timer = self.scheduler()
        self.script.unlink()
        timer.poll(self.now)
        self.launch.assert_not_called()
        self.assertIn("启动失败", timer.book.plans[0].result)
        self.assertFalse(timer.book.plans[0].enabled)

    def test_two_due_plans_start_on_separate_idle_ticks(self):
        self.book.put(replace(self.plan(), id="a"))
        self.book.put(replace(self.plan(), id="b"))
        timer = self.scheduler()
        timer.poll(self.now)
        self.assertEqual(self.launch.call_count, 1)
        self.busy.return_value = True
        timer.poll(self.now)
        self.assertEqual(self.launch.call_count, 1)
        self.busy.return_value = False
        timer.poll(self.now + timedelta(seconds=1))
        self.assertEqual(self.launch.call_count, 2)

    def test_failed_claim_stops_timer_and_preserves_execution_opportunity(self):
        self.book.put(self.plan())
        timer = self.scheduler()
        before = self.path.read_bytes()
        with patch("tool.storage.os.replace", side_effect=OSError("计划文件只读")):
            timer.poll(self.now)
        self.launch.assert_not_called()
        self.assertTrue(timer.book.plans[0].enabled)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertIn("已停止", timer.error)

    def test_corrupt_file_is_reported_and_never_overwritten(self):
        self.path.parent.mkdir()
        self.path.write_text("broken", encoding="utf-8")
        timer = self.scheduler()
        self.assertTrue(timer.error)
        self.assertIsNone(timer.book)
        self.assertFalse(timer.timer.isActive())
        timer.poll(self.now)
        self.assertEqual(self.path.read_text(encoding="utf-8"), "broken")

    def test_invalid_plan_fields_and_duplicate_ids_are_rejected(self):
        for plan in (replace(self.plan(), repeat="monthly"), replace(self.plan(), enabled=1), replace(self.plan(), run_at="bad"),
                     replace(self.plan(), interruptible="true")):
            with self.subTest(plan=plan), self.assertRaises(ValueError):
                self.book.put(plan)
        self.assertEqual(self.book.plans, [])
        self.path.parent.mkdir()
        plan = asdict(self.plan())
        self.path.write_text(json.dumps([plan, plan]), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "ID 重复"):
            ScheduleBook(self.path)

    def test_dialog_saves_dynamic_selection_and_reopens_existing_plan(self):
        timer = self.scheduler()
        dialog = ScheduleDialog(timer, self.registry)
        self.addCleanup(dialog.deleteLater)
        dialog.name_input.setText("中文计划")
        self.assertFalse(dialog.interruptible_check.isChecked())
        dialog.interruptible_check.setChecked(True)
        dialog.time_input.setDateTime(QDateTime(self.now))
        dialog.save_btn.click()
        saved = ScheduleBook(self.path).plans[0]
        self.assertEqual((saved.name, saved.engine, saved.script), ("中文计划", "Custom", "actions/job.json"))
        self.assertTrue(saved.interruptible)
        reopened = ScheduleDialog(timer, self.registry)
        self.addCleanup(reopened.deleteLater)
        reopened.plan_table.selectRow(0)
        self.assertEqual(reopened.name_input.text(), "中文计划")
        self.assertTrue(reopened.interruptible_check.isChecked())
        reopened.toggle_btn.click()
        self.assertFalse(ScheduleBook(self.path).plans[0].enabled)
        reopened.toggle_btn.click()
        self.assertTrue(ScheduleBook(self.path).plans[0].enabled)
        with patch.object(QMessageBox, "question", return_value=QMessageBox.Yes):
            reopened.remove_btn.click()
        self.assertEqual(ScheduleBook(self.path).plans, [])

    def test_dialog_rejects_past_once_and_does_not_create_plan(self):
        timer = self.scheduler()
        dialog = ScheduleDialog(timer, self.registry)
        self.addCleanup(dialog.deleteLater)
        dialog.time_input.setDateTime(QDateTime.currentDateTime().addSecs(-60))
        dialog.save_btn.click()
        self.assertEqual(timer.book.plans, [])
        self.assertIn("将来", dialog.status_label.text())
        self.assertFalse(self.path.exists())

    def test_daily_dialog_advances_past_time_and_disable_prevents_launch(self):
        timer = self.scheduler()
        dialog = ScheduleDialog(timer, self.registry)
        self.addCleanup(dialog.deleteLater)
        dialog.repeat_combo.setCurrentIndex(dialog.repeat_combo.findData("daily"))
        before = datetime.now().replace(microsecond=0) - timedelta(minutes=1)
        dialog.time_input.setDateTime(QDateTime(before))
        dialog.save_btn.click()
        self.assertEqual(datetime.fromisoformat(timer.book.plans[0].run_at), before + timedelta(days=1))
        dialog.plan_table.selectRow(0)
        dialog.toggle_btn.click()
        timer.poll(self.now + timedelta(days=10))
        self.launch.assert_not_called()

    def test_weekly_dialog_advances_past_time_and_restores_saved_selection(self):
        timer = self.scheduler()
        dialog = ScheduleDialog(timer, self.registry)
        self.addCleanup(dialog.deleteLater)
        dialog.repeat_combo.setCurrentIndex(dialog.repeat_combo.findData("weekly"))
        self.assertEqual(dialog.repeat_combo.currentText(), "每周同一时间")
        before = datetime.now().replace(microsecond=0) - timedelta(days=17, minutes=1)
        dialog.time_input.setDateTime(QDateTime(before))
        dialog.save_btn.click()
        saved = ScheduleBook(self.path).plans[0]
        self.assertEqual(saved.repeat, "weekly")
        self.assertEqual(datetime.fromisoformat(saved.run_at), before + timedelta(days=21))
        reopened = ScheduleDialog(timer, self.registry)
        self.addCleanup(reopened.deleteLater)
        reopened.plan_table.selectRow(0)
        self.assertEqual(reopened.repeat_combo.currentData(), "weekly")
        self.assertEqual(reopened.plan_table.item(0, 6).text(), "每周")
        self.assertEqual(reopened.time_input.dateTime().toPyDateTime(), before + timedelta(days=21))

    def test_enabling_expired_weekly_plan_advances_to_next_corresponding_weekday(self):
        before = datetime.now().replace(microsecond=0) - timedelta(days=17)
        self.book.put(replace(self.plan(when=before, repeat="weekly"), enabled=False))
        timer = self.scheduler()
        dialog = ScheduleDialog(timer, self.registry)
        self.addCleanup(dialog.deleteLater)
        dialog.plan_table.selectRow(0)
        dialog.toggle_btn.click()
        saved = ScheduleBook(self.path).plans[0]
        self.assertTrue(saved.enabled)
        self.assertEqual(saved.repeat, "weekly")
        self.assertEqual(datetime.fromisoformat(saved.run_at), before + timedelta(days=21))
        self.assertEqual(dialog.repeat_combo.currentData(), "weekly")
        timer.poll(datetime.now())
        self.launch.assert_not_called()

    def test_timer_refresh_updates_saved_form_and_preserves_unsaved_draft(self):
        self.book.put(self.plan())
        timer = self.scheduler()
        dialog = ScheduleDialog(timer, self.registry)
        self.addCleanup(dialog.deleteLater)
        dialog.plan_table.selectRow(0)
        timer.poll(self.now)
        self.assertFalse(dialog.enabled_check.isChecked())
        self.assertEqual(dialog.status_label.text(), "已触发")
        dialog.name_input.setText("未保存名称")
        dialog.mark_dirty()
        timer.changed.emit()
        self.assertEqual(dialog.name_input.text(), "未保存名称")
        self.assertTrue(dialog.isWindowModified())
        with patch.object(QMessageBox, "question", return_value=QMessageBox.Cancel):
            dialog.new_btn.click()
            dialog.reject()
        self.assertEqual(dialog.name_input.text(), "未保存名称")
        self.assertEqual(timer.book.plans[0].name, "测试计划")


if __name__ == "__main__":
    unittest.main()
