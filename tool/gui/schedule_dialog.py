"""应用内计划计时与独立配置窗口，复用主窗口的任务启动入口。"""

from collections import deque
from contextlib import ExitStack
from dataclasses import replace
from datetime import datetime
from pathlib import Path

from PyQt5 import uic
from PyQt5.QtCore import QDateTime, QObject, QSignalBlocker, Qt, QTimer, pyqtSignal
from PyQt5.QtWidgets import (
    QDialog,
    QFileDialog,
    QHeaderView,
    QMessageBox,
    QTableWidgetItem,
)

from route import PATHS
from tool.log import CUS_LOGGER
from tool.schedule import Plan, ScheduleBook, next_run
from tool.script_files import discover_scripts, read_script, script_key, script_path


class ScheduleTimer(QObject):
    changed = pyqtSignal()

    def __init__(self, registry, launch, busy, stop, parent=None, *, path=None):
        super().__init__(parent)
        self.registry, self.launch, self.busy = registry, launch, busy
        self.stop = stop
        self.pending = deque()
        self.dispatching = False
        # 活动计划为 (计划 ID, 阶段)：1=运行，2=已请求停止；None 表示无活动计划。
        self.active = None
        self.error = ""
        self.book = None
        self.timer = QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self.poll)
        try:
            self.book = ScheduleBook(path)
            self.book.skip_missed(datetime.now())
        except (OSError, ValueError) as error:
            self.fail_storage(error)
            return
        self.timer.start()

    def fail_storage(self, error):
        self.timer.stop()
        self.error = f"定时计划读写失败，计时已停止：{error}"
        CUS_LOGGER.error(self.error, exc_info=True)
        self.changed.emit()

    def poll(self, now=None):
        if self.error or self.book is None:
            return
        now = now or datetime.now()
        due = self.book.due(now)
        busy = self.busy()
        if not busy:
            self.release_active()
            if self.error:
                return
        if not due and not self.pending:
            return
        try:
            if busy:
                active_id = self.active[0] if self.active else None
                if self.can_interrupt():
                    for plan in due:
                        if plan.id == active_id:
                            continue
                        try:
                            self.prepare_plan(plan)
                        except (OSError, ValueError) as error:
                            self.record_failure(self.book.claim(plan, now), error)
                            continue
                        self.request_stop(f"计划“{plan.name}”")
                        break
                    if self.pending:
                        self.request_stop("手动运行任务")
                    if self.error:
                        return
                    due = self.book.due(now)
                waiting = {plan.id for plan in due if plan.id != active_id}
                plans = [replace(plan, result="等待当前任务结束") if plan.id in waiting else plan for plan in self.book.plans]
                if plans != self.book.plans:
                    self.book.save(plans)
                    self.changed.emit()
                return
            if self.pending and (not due or self.pending[0][0] < datetime.fromisoformat(due[0].run_at)):
                _, _, launch = self.pending.popleft()
                self.dispatching = True
                try:
                    launch()
                except Exception as error:
                    CUS_LOGGER.error("排队任务无法启动：%s", error, exc_info=True)
                finally:
                    self.dispatching = False
                return
            for plan in due:
                claimed = self.book.claim(plan, now)
                self.dispatching = True
                try:
                    self.launch(plan.engine, self.prepare_plan(plan))
                except Exception as error:
                    self.record_failure(claimed, error)
                    continue
                finally:
                    self.dispatching = False
                self.active = (plan.id, 1)
                CUS_LOGGER.debug("计划“%s”已触发，使用 %s 内核运行脚本。", plan.name, plan.engine)
                self.changed.emit()
                # 一次计时只发起一个任务；后续计划继续等待主任务线程释放。
                return
        except (OSError, ValueError) as error:
            self.fail_storage(error)

    def prepare_plan(self, plan):
        if plan.engine not in {spec.id for spec in self.registry.runnable()}:
            raise ValueError("计划指定的内核已不可用，请重新选择内核")
        path = script_path(plan.script)
        read_script(path)
        return str(path)

    def record_failure(self, plan, error):
        self.book.put(replace(plan, result=f"启动失败：{error}"))
        CUS_LOGGER.error("计划“%s”无法启动：%s", plan.name, error, exc_info=True)
        self.changed.emit()

    def queue_task(self, launch, key=None):
        """手动任务只在本次程序运行期间排队，与到期计划按准备时间排序。"""
        if self.error:
            raise RuntimeError(self.error)
        self.pending.append((datetime.now(), launch if key is None else key, launch))
        CUS_LOGGER.debug("本次手动任务已加入执行队列。")
        self.request_stop("手动运行任务")

    def cancel_task(self, key):
        remaining = deque(item for item in self.pending if item[1] is not key)
        removed = len(remaining) != len(self.pending)
        self.pending = remaining
        if removed:
            CUS_LOGGER.debug("本次排队任务已取消。")
        return removed

    def has_pending(self):
        return not self.error and bool(self.pending or (self.book is not None and self.book.due(datetime.now())))

    def can_interrupt(self):
        if self.active is None or self.active[1] != 1:
            return False
        return any(plan.id == self.active[0] and plan.interruptible for plan in self.book.plans)

    def request_stop(self, reason):
        if not self.can_interrupt():
            return
        plan_id = self.active[0]
        plan = next(plan for plan in self.book.plans if plan.id == plan_id)
        try:
            self.book.put(replace(plan, result=f"因{reason}请求停止，等待线程退出"))
        except (OSError, ValueError) as error:
            self.fail_storage(error)
            return
        self.active = (plan_id, 2)
        self.changed.emit()
        CUS_LOGGER.info("计划“%s”允许中断，因%s请求停止；后续任务等待线程退出。", plan.name, reason)
        try:
            self.stop()
        except Exception as error:
            CUS_LOGGER.error("计划“%s”的停止请求未完成，后续任务继续等待：%s", plan.name, error, exc_info=True)
            try:
                self.book.put(replace(plan, result=f"停止请求未完成，继续等待：{error}"))
                self.changed.emit()
            except (OSError, ValueError) as save_error:
                self.fail_storage(save_error)

    def release_active(self):
        """主任务线程确认空闲后才释放计划归属，防止中断后来手动启动的任务。"""
        if self.active is None:
            return
        plan_id, phase = self.active
        self.active = None
        if phase != 2:
            return
        plan = next((plan for plan in self.book.plans if plan.id == plan_id), None)
        if plan is not None:
            try:
                self.book.put(replace(plan, result="已退出，后续任务可继续执行"))
                self.changed.emit()
            except (OSError, ValueError) as error:
                self.fail_storage(error)


class ScheduleDialog(QDialog):
    def __init__(self, scheduler, registry, parent=None):
        super().__init__(parent)
        uic.loadUi(str(Path(PATHS["ui"]) / "Schedule.ui"), self)
        self.scheduler = scheduler
        self.registry = registry
        self.editing = None
        self.plan_table.setColumnCount(9)
        self.plan_table.setHorizontalHeaderLabels(["启用", "允许中断", "计划名称", "内核", "脚本", "下次执行", "重复", "上次触发", "触发记录"])
        self.plan_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.plan_table.horizontalHeader().setStretchLastSection(True)
        for spec in registry.runnable():
            self.engine_combo.addItem(spec.name, spec.id)
        for path in discover_scripts(registry):
            self.script_combo.addItem(script_key(path), script_key(path))
        self.repeat_combo.addItem("指定日期执行一次", "once")
        self.repeat_combo.addItem("每天同一时间", "daily")
        self.repeat_combo.addItem("每周同一时间", "weekly")
        self.new_btn.clicked.connect(self.new_plan)
        self.save_btn.clicked.connect(self.save_plan)
        self.toggle_btn.clicked.connect(self.toggle_plan)
        self.remove_btn.clicked.connect(self.remove_plan)
        self.browse_btn.clicked.connect(self.browse_script)
        self.close_btn.clicked.connect(self.reject)
        self.plan_table.itemSelectionChanged.connect(self.select_plan)
        scheduler.changed.connect(self.refresh)
        self.refresh()
        self.new_plan()
        self.name_input.textEdited.connect(self.mark_dirty)
        self.engine_combo.currentIndexChanged.connect(self.mark_dirty)
        self.script_combo.currentIndexChanged.connect(self.mark_dirty)
        self.time_input.dateTimeChanged.connect(self.mark_dirty)
        self.repeat_combo.currentIndexChanged.connect(self.mark_dirty)
        self.enabled_check.toggled.connect(self.mark_dirty)
        self.interruptible_check.toggled.connect(self.mark_dirty)

    def mark_dirty(self, *_):
        self.setWindowModified(True)
        self.status_label.setText("配置已修改，保存后生效")

    def refresh(self):
        selected = self.selected_id()
        with QSignalBlocker(self.plan_table):
            self.plan_table.setRowCount(0)
            if self.scheduler.book is not None:
                for row, plan in enumerate(self.scheduler.book.plans):
                    self.plan_table.insertRow(row)
                    spec = self.registry.specs.get(plan.engine)
                    values = ["是" if plan.enabled else "否", "是" if plan.interruptible else "否", plan.name, spec.name if spec else f"{plan.engine}（不可用）",
                              plan.script, plan.run_at.replace("T", " ") if plan.enabled else "—",
                              {"once": "一次", "daily": "每天", "weekly": "每周"}[plan.repeat], plan.last_run.replace("T", " ") or "—", plan.result]
                    for column, value in enumerate(values):
                        item = QTableWidgetItem(value)
                        item.setToolTip(value)
                        item.setData(Qt.UserRole, plan.id)
                        self.plan_table.setItem(row, column, item)
                    if plan.id == selected:
                        self.plan_table.selectRow(row)
        enabled = not self.scheduler.error and self.scheduler.book is not None
        for button in (self.save_btn, self.remove_btn, self.toggle_btn):
            button.setEnabled(enabled)
        if self.scheduler.error:
            self.status_label.setText(self.scheduler.error)
        elif self.editing is not None and not self.isWindowModified():
            plan = next((plan for plan in self.scheduler.book.plans if plan.id == self.editing), None)
            if plan is not None:
                self.fill_form(plan)
                self.status_label.setText(plan.result)

    def selected_id(self):
        row = self.plan_table.currentRow()
        item = self.plan_table.item(row, 0) if row >= 0 else None
        return item.data(Qt.UserRole) if item is not None else None

    def new_plan(self):
        if not self.can_leave():
            return
        self.editing = None
        with QSignalBlocker(self.plan_table):
            self.plan_table.clearSelection()
            self.plan_table.setCurrentCell(-1, -1)
        with QSignalBlocker(self.time_input), QSignalBlocker(self.repeat_combo), QSignalBlocker(self.enabled_check), QSignalBlocker(self.interruptible_check):
            self.name_input.setText("新计划")
            self.time_input.setDateTime(QDateTime.currentDateTime().addSecs(60))
            self.repeat_combo.setCurrentIndex(0)
            self.enabled_check.setChecked(True)
            self.interruptible_check.setChecked(False)
        self.setWindowModified(False)
        if not self.scheduler.error:
            self.status_label.setText("填写配置后点击“保存计划”")

    def select_plan(self):
        plan_id = self.selected_id()
        if plan_id is None:
            return
        if plan_id != self.editing and not self.can_leave():
            with QSignalBlocker(self.plan_table):
                self.plan_table.clearSelection()
                self.plan_table.setCurrentCell(-1, -1)
                for row in range(self.plan_table.rowCount()):
                    if self.plan_table.item(row, 0).data(Qt.UserRole) == self.editing:
                        self.plan_table.selectRow(row)
                        break
            return
        plan = next(item for item in self.scheduler.book.plans if item.id == plan_id)
        self.fill_form(plan)
        self.status_label.setText("修改配置后点击“保存计划”")

    def fill_form(self, plan):
        self.editing = plan.id
        with ExitStack() as stack:
            for widget in (self.engine_combo, self.script_combo, self.time_input, self.repeat_combo, self.enabled_check, self.interruptible_check):
                stack.enter_context(QSignalBlocker(widget))
            self.name_input.setText(plan.name)
            self.engine_combo.setCurrentIndex(self.engine_combo.findData(plan.engine))
            index = self.script_combo.findData(plan.script)
            if index < 0:
                self.script_combo.addItem(plan.script, plan.script)
                index = self.script_combo.count() - 1
            self.script_combo.setCurrentIndex(index)
            self.time_input.setDateTime(QDateTime(datetime.fromisoformat(plan.run_at)))
            self.repeat_combo.setCurrentIndex(self.repeat_combo.findData(plan.repeat))
            self.enabled_check.setChecked(plan.enabled)
            self.interruptible_check.setChecked(plan.interruptible)
        self.setWindowModified(False)

    def save_plan(self):
        try:
            name = self.name_input.text().strip()
            engine = self.engine_combo.currentData()
            script = self.script_combo.currentData()
            if not name or engine is None or script is None:
                raise ValueError("请填写名称并选择可用内核与脚本")
            read_script(script_path(script))
            when = self.time_input.dateTime().toPyDateTime().replace(microsecond=0)
            repeat = self.repeat_combo.currentData()
            enabled = self.enabled_check.isChecked()
            now = datetime.now()
            if enabled and when <= now:
                if repeat == "once":
                    raise ValueError("一次计划的执行时间必须在将来")
                when = next_run(when, now, repeat)
            old = next((plan for plan in self.scheduler.book.plans if plan.id == self.editing), None)
            plan = Plan.create(name, engine, script, when, repeat, interruptible=self.interruptible_check.isChecked())
            if old is not None:
                plan = replace(plan, id=old.id, last_run=old.last_run)
            plan = replace(plan, enabled=enabled, result="等待执行" if enabled else "已停用")
            self.scheduler.book.put(plan)
            self.editing = plan.id
            self.setWindowModified(False)
            self.scheduler.changed.emit()
            self.status_label.setText("计划已保存")
            return True
        except (OSError, ValueError) as error:
            self.status_label.setText(f"计划保存失败：{error}")
            return False

    def toggle_plan(self):
        plan_id = self.selected_id()
        if plan_id is None or not self.can_leave():
            return
        try:
            plan = next(item for item in self.scheduler.book.plans if item.id == plan_id)
            when = datetime.fromisoformat(plan.run_at)
            if not plan.enabled:
                if plan.engine not in {spec.id for spec in self.registry.runnable()}:
                    raise ValueError("该计划的内核已不可用，请先修改配置")
                read_script(script_path(plan.script))
                if when <= datetime.now():
                    if plan.repeat == "once":
                        raise ValueError("该计划时间已过，请先修改执行时间")
                    when = next_run(when, datetime.now(), plan.repeat)
            self.scheduler.book.put(replace(plan, enabled=not plan.enabled, run_at=when.isoformat(timespec="seconds"),
                                            result="已停用" if plan.enabled else "等待执行"))
            self.scheduler.changed.emit()
            self.select_plan()
        except (OSError, ValueError) as error:
            self.status_label.setText(str(error))

    def remove_plan(self):
        plan_id = self.selected_id()
        if plan_id is None or QMessageBox.question(self, "删除计划", "确定删除选中的计划？",
                                                  QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
            return
        try:
            self.scheduler.book.remove(plan_id)
            self.editing = None
            self.setWindowModified(False)
            self.scheduler.changed.emit()
            self.new_plan()
        except OSError as error:
            self.status_label.setText(f"计划删除失败：{error}")

    def browse_script(self):
        path, _ = QFileDialog.getOpenFileName(self, "选择动作脚本", str(Path(PATHS["root"]) / "actions"), "JSON 脚本 (*.json)")
        if not path:
            return
        try:
            read_script(path)
            key = script_key(path)
            index = self.script_combo.findData(key)
            if index < 0:
                self.script_combo.addItem(key, key)
                index = self.script_combo.count() - 1
            self.script_combo.setCurrentIndex(index)
        except (OSError, ValueError) as error:
            self.status_label.setText(f"脚本无法加载：{error}")

    def can_leave(self):
        if not self.isWindowModified():
            return True
        answer = QMessageBox.question(self, "未保存的计划", "计划配置有未保存的修改，是否保存？",
                                      QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel, QMessageBox.Cancel)
        if answer == QMessageBox.Save:
            return self.save_plan()
        if answer == QMessageBox.Discard:
            self.setWindowModified(False)
            return True
        return False

    def reject(self):
        if self.can_leave():
            super().reject()

    def closeEvent(self, event):
        if self.can_leave():
            event.accept()
        else:
            event.ignore()
