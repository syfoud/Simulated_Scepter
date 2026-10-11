"""动作脚本的事件列表、参数表单及 JSON 源码编辑窗口。"""

import copy
import json
from pathlib import Path
from uuid import uuid4

from PyQt5 import uic
from PyQt5.QtCore import QSignalBlocker, Qt, pyqtSignal
from PyQt5.QtGui import QFontDatabase
from PyQt5.QtWidgets import (
    QComboBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from route import PATHS
from tool.gui.trigger_sample import TriggerSample
from tool.script_files import (
    discover_scripts,
    parse_script,
    read_script,
    save_script,
    script_key,
    validate_script,
)

STEP_DEFAULTS = {
    "点击坐标": {"position": [960, 540]},
    "点击文字": {"text": "目标文字", "box": [0, 1920, 0, 1080]},
    "点击图片": {"photo": "图片名称", "threshold": 0.9},
    "按键": {"press": "esc", "time": 0},
    "等待": {"sleep": 1},
    "直接等待": {"real_sleep": 1},
    "拖拽": {"drag": [960, 540, 960, 640]},
    "滚动": {"scroll": -1},
    "更新状态": {"set_state": "新状态"},
    "内核方法": "method_name",
}


def new_event():
    return {"name": "新事件", "trigger": {"state_only": True, "once": True}, "actions": [{"sleep": 1}]}


class ParameterFields(QWidget):
    """逐项编辑 JSON 参数；未识别的字段同样可以保留和修改。"""

    changed = pyqtSignal()

    def __init__(self, defaults, parent=None):
        super().__init__(parent)
        self.defaults = defaults
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.table = QTableWidget(0, 2, self)
        self.table.setMinimumHeight(80)
        self.table.setHorizontalHeaderLabels(["参数名称", "参数值（JSON）"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setToolTip('文字需加双引号，例如 "end"；坐标例如 [960, 540]；开关用 true / false。')
        layout.addWidget(self.table)
        toolbar = QHBoxLayout()
        self.key_combo = QComboBox(self)
        self.key_combo.addItems([*defaults, "自定义字段"])
        add = QPushButton("添加参数", self)
        remove = QPushButton("删除参数", self)
        toolbar.addWidget(self.key_combo)
        toolbar.addWidget(add)
        toolbar.addWidget(remove)
        layout.addLayout(toolbar)
        add.clicked.connect(self.add_field)
        remove.clicked.connect(self.remove_field)
        self.table.itemChanged.connect(lambda _item: self.changed.emit())

    def set_value(self, values):
        with QSignalBlocker(self.table):
            self.table.setRowCount(0)
            for key, value in values.items():
                row = self.table.rowCount()
                self.table.insertRow(row)
                self.table.setItem(row, 0, QTableWidgetItem(key))
                self.table.setItem(row, 1, QTableWidgetItem(json.dumps(value, ensure_ascii=False)))

    def value(self):
        values = {}
        for row in range(self.table.rowCount()):
            key_item, value_item = self.table.item(row, 0), self.table.item(row, 1)
            key = key_item.text().strip() if key_item is not None else ""
            if not key or key in values:
                raise ValueError(f"参数第 {row + 1} 行名称为空或重复")
            try:
                values[key] = json.loads(value_item.text() if value_item is not None else "")
            except json.JSONDecodeError as error:
                raise ValueError(f"参数 {key} 的值不是有效 JSON：{error.msg}") from error
        return values

    def add_field(self):
        key = self.key_combo.currentText()
        if key == "自定义字段":
            key, accepted = QInputDialog.getText(self, "添加参数", "参数名称")
            if not accepted or not key.strip():
                return
            key = key.strip()
        if any(self.table.item(row, 0).text() == key for row in range(self.table.rowCount())):
            return
        row = self.table.rowCount()
        self.table.insertRow(row)
        self.table.setItem(row, 0, QTableWidgetItem(key))
        self.table.setItem(row, 1, QTableWidgetItem(json.dumps(self.defaults.get(key, ""), ensure_ascii=False)))
        self.table.setCurrentCell(row, 1)

    def remove_field(self):
        row = self.table.currentRow()
        if row >= 0:
            self.table.removeRow(row)
            self.changed.emit()


class ScriptEditor(QDialog):
    script_saved = pyqtSignal(str)
    sample_requested = pyqtSignal(str, str, bool)
    debug_requested = pyqtSignal(str, str, object, bool)
    stop_requested = pyqtSignal(str)

    def __init__(self, registry, selected=None, parent=None):
        super().__init__(parent)
        uic.loadUi(str(Path(PATHS["ui"]) / "ScriptEditor.ui"), self)
        self.path = None
        self.document = []
        self.event_index = self.step_index = -1
        self.mode = 0
        self.session = uuid4().hex
        self.operation = None
        self.close_pending = False
        for spec in registry.runnable():
            self.debug_kernel_combo.addItem(spec.name, spec.id)
        self.debug_scope_combo.addItem("当前事件", "event")
        self.debug_scope_combo.addItem("整个脚本", "script")
        self.debug_stop_btn.setEnabled(False)
        self.trigger_fields = ParameterFields({
            "text": "目标文字", "box": [0, 1920, 0, 1080], "photo": "图片名称",
            "pos": {"x": 0.5, "y": 0.5}, "mask": "图片名称", "state_only": True,
            "condition": "状态名称", "once": False, "interval": 1, "threshold": 0.9, "redundancy": 30,
        }, self.trigger_host)
        self.trigger_layout.addWidget(self.trigger_fields)
        self.step_fields = ParameterFields({
            "position": [960, 540], "text": "目标文字", "box": [0, 1920, 0, 1080],
            "photo": "图片名称", "press": "esc", "time": 0, "sleep": 1, "real_sleep": 1,
            "drag": [960, 540, 960, 640], "scroll": -1, "set_state": "状态名称", "threshold": 0.9,
        }, self.step_host)
        self.step_layout.addWidget(self.step_fields)
        self.step_type.addItems(STEP_DEFAULTS)
        self.source_edit.setFont(QFontDatabase.systemFont(QFontDatabase.FixedFont))
        for path in discover_scripts(registry):
            self.file_combo.addItem(script_key(path), str(path))
        if selected:
            try:
                self.load_document(read_script(selected), Path(selected))
            except (OSError, ValueError) as error:
                self.load_document([new_event()], None)
                self.status_label.setText(f"脚本打开失败：{error}")
        elif self.file_combo.count():
            path = Path(self.file_combo.currentData())
            self.load_document(read_script(path), path)
        else:
            self.load_document([new_event()], None)
        self.file_combo.currentIndexChanged.connect(self.select_file)
        self.event_list.currentRowChanged.connect(self.select_event)
        self.step_list.currentRowChanged.connect(self.select_step)
        self.tabs.currentChanged.connect(self.switch_mode)
        self.event_name.textEdited.connect(self.mark_dirty)
        self.trigger_fields.changed.connect(self.mark_dirty)
        self.step_fields.changed.connect(self.mark_dirty)
        self.source_edit.textChanged.connect(self.mark_dirty)
        self.new_btn.clicked.connect(self.new_script)
        self.open_btn.clicked.connect(self.open_file)
        self.save_btn.clicked.connect(self.save)
        self.save_as_btn.clicked.connect(lambda: self.save(as_new=True))
        self.validate_btn.clicked.connect(self.check_script)
        self.sample_text_btn.clicked.connect(lambda: self.request_sample(True))
        self.sample_image_btn.clicked.connect(lambda: self.request_sample(False))
        self.debug_trigger_btn.clicked.connect(lambda: self.request_debug(False))
        self.debug_direct_btn.clicked.connect(lambda: self.request_debug(True))
        self.debug_stop_btn.clicked.connect(self.stop_operation)
        for button, operation in ((self.add_event_btn, "add"), (self.clone_event_btn, "clone"),
                                  (self.remove_event_btn, "remove"), (self.event_up_btn, "up"), (self.event_down_btn, "down")):
            button.clicked.connect(lambda checked=False, op=operation: self.edit_events(op))
        for button, operation in ((self.add_step_btn, "add"), (self.remove_step_btn, "remove"),
                                  (self.step_up_btn, "up"), (self.step_down_btn, "down")):
            button.clicked.connect(lambda checked=False, op=operation: self.edit_steps(op))

    def mark_dirty(self, *_):
        self.setWindowModified(True)
        self.status_label.clear()

    def set_operation(self, operation):
        self.operation = operation
        self.tabs.setEnabled(operation is None)
        for widget in (self.file_combo, self.new_btn, self.open_btn, self.debug_kernel_combo,
                       self.debug_scope_combo, self.debug_trigger_btn, self.debug_direct_btn):
            widget.setEnabled(operation is None)
        self.debug_stop_btn.setEnabled(operation is not None)

    def request_sample(self, recognize):
        try:
            self.commit_event()
            kernel = self.debug_kernel_combo.currentData()
            if kernel is None:
                raise ValueError("请选择可用内核")
            self.set_operation("text" if recognize else "image")
            self.status_label.setText("截图取样已提交，可点击停止取消；繁忙时按队列等待")
            self.sample_requested.emit(self.session, kernel, recognize)
        except ValueError as error:
            self.status_label.setText(f"无法截取：{error}")

    def request_debug(self, direct):
        try:
            events = self.current_document()
            kernel = self.debug_kernel_combo.currentData()
            if kernel is None:
                raise ValueError("请选择可用内核")
            if self.debug_scope_combo.currentData() == "event":
                events = [events[min(self.event_index, len(events) - 1)]]
            self.set_operation("debug")
            self.status_label.setText("调试已提交，可点击停止取消；繁忙时按队列等待")
            self.debug_requested.emit(self.session, kernel, copy.deepcopy(events), direct)
        except ValueError as error:
            self.status_label.setText(f"无法调试：{error}")

    def stop_operation(self):
        if self.operation is not None:
            self.operation = "stopping"
            self.status_label.setText("正在取消排队或停止任务，等待线程退出")
            self.stop_requested.emit(self.session)

    def receive_result(self, session, result):
        if session != self.session or self.operation is None:
            return
        operation = self.operation
        self.set_operation(None)
        if result.get("error"):
            self.status_label.setText(f"操作失败：{result['error']}")
        elif "sample" in result and operation in ("text", "image") and not self.close_pending:
            dialog = TriggerSample(result["sample"], operation == "text", self, event_name=self.event_name.text())
            try:
                if dialog.exec_() == QDialog.Accepted:
                    trigger = self.trigger_fields.value()
                    for key in ("text", "box", "photo", "pos", "mask", "state_only", "binary"):
                        trigger.pop(key, None)
                    trigger.update(dialog.trigger)
                    self.trigger_fields.set_value(trigger)
                    self.mark_dirty()
                    self.status_label.setText("画面标志已填入当前事件，保存脚本后持久生效")
            finally:
                dialog.deleteLater()
        else:
            self.status_label.setText(result.get("message", "操作已停止"))
        if self.close_pending:
            self.close_pending = False
            self.reject()

    def load_document(self, data, path):
        self.document = copy.deepcopy(data)
        self.path = path
        self.mode = 0
        with QSignalBlocker(self.tabs):
            self.tabs.setCurrentIndex(0)
        with QSignalBlocker(self.file_combo):
            index = self.file_combo.findData(str(path)) if path else -1
            if path is not None and index < 0:
                self.file_combo.addItem(script_key(path), str(path))
                index = self.file_combo.count() - 1
            self.file_combo.setCurrentIndex(index)
        self.path_label.setText(str(path) if path is not None else "未保存脚本（默认保存到 actions 文件夹）")
        self.display_events(0)
        self.status_label.clear()
        self.setWindowModified(False)

    def display_events(self, index):
        with QSignalBlocker(self.event_list):
            self.event_list.clear()
            self.event_list.addItems([event["name"] for event in self.document])
            self.event_list.setCurrentRow(index)
        self.display_event(index)

    def display_event(self, index):
        self.event_index = index
        event = self.document[index]
        with QSignalBlocker(self.event_name):
            self.event_name.setText(event["name"])
        self.trigger_fields.set_value(event["trigger"])
        with QSignalBlocker(self.step_list):
            self.step_list.clear()
            for step in event["actions"]:
                item = QListWidgetItem(json.dumps(step, ensure_ascii=False))
                item.setData(Qt.UserRole, step)
                self.step_list.addItem(item)
            self.step_list.setCurrentRow(0 if self.step_list.count() else -1)
        self.display_step(self.step_list.currentRow())

    def display_step(self, row):
        self.step_index = row
        self.step_fields.setEnabled(row >= 0)
        step = self.step_list.item(row).data(Qt.UserRole) if row >= 0 else {}
        self.step_fields.set_value({"method": step} if isinstance(step, str) else step)

    def commit_step(self):
        if self.step_index < 0:
            return
        item = self.step_list.item(self.step_index)
        values = self.step_fields.value()
        if isinstance(item.data(Qt.UserRole), str):
            if set(values) != {"method"} or not isinstance(values["method"], str) or not values["method"].isidentifier():
                raise ValueError("内核方法动作只接受 method 参数，值需为有效的方法名称")
            values = values["method"]
        if not values:
            raise ValueError("动作参数不能为空")
        item.setData(Qt.UserRole, values)
        item.setText(json.dumps(values, ensure_ascii=False))

    def commit_event(self):
        self.commit_step()
        event = copy.deepcopy(self.document[self.event_index])
        event.update(name=self.event_name.text().strip(), trigger=self.trigger_fields.value(),
                     actions=[self.step_list.item(row).data(Qt.UserRole) for row in range(self.step_list.count())])
        validate_script([event])
        self.document[self.event_index] = event
        self.event_list.item(self.event_index).setText(event["name"])

    def select_event(self, row):
        if row < 0:
            return
        try:
            self.commit_event()
        except ValueError as error:
            self.status_label.setText(str(error))
            with QSignalBlocker(self.event_list):
                self.event_list.setCurrentRow(self.event_index)
            return
        self.display_event(row)

    def select_step(self, row):
        try:
            self.commit_step()
        except ValueError as error:
            self.status_label.setText(str(error))
            with QSignalBlocker(self.step_list):
                self.step_list.setCurrentRow(self.step_index)
            return
        self.display_step(row)

    def switch_mode(self, mode):
        try:
            if mode == 1:
                self.commit_event()
                with QSignalBlocker(self.source_edit):
                    self.source_edit.setPlainText(json.dumps(self.document, ensure_ascii=False, indent=4))
            else:
                self.document = parse_script(self.source_edit.toPlainText())
                self.display_events(min(self.event_index, len(self.document) - 1))
        except ValueError as error:
            self.status_label.setText(str(error))
            with QSignalBlocker(self.tabs):
                self.tabs.setCurrentIndex(self.mode)
            return
        self.mode = mode
        self.status_label.clear()

    def edit_events(self, operation):
        try:
            if operation != "remove":
                self.commit_event()
            index = self.event_index
            if operation == "add":
                self.document.append(new_event())
                index = len(self.document) - 1
            elif operation == "clone":
                event = copy.deepcopy(self.document[index])
                event["name"] += " 副本"
                self.document.insert(index + 1, event)
                index += 1
            elif operation == "remove":
                if len(self.document) <= 1:
                    raise ValueError("脚本至少需要一个事件")
                self.document.pop(index)
                index = min(index, len(self.document) - 1)
            else:
                target = index + (-1 if operation == "up" else 1)
                if not 0 <= target < len(self.document):
                    return
                self.document[index], self.document[target] = self.document[target], self.document[index]
                index = target
            self.display_events(index)
            self.mark_dirty()
        except ValueError as error:
            self.status_label.setText(str(error))

    def edit_steps(self, operation):
        try:
            if operation != "remove":
                self.commit_step()
            row = self.step_index
            if operation == "add":
                step = copy.deepcopy(STEP_DEFAULTS[self.step_type.currentText()])
                item = QListWidgetItem(json.dumps(step, ensure_ascii=False))
                item.setData(Qt.UserRole, step)
                self.step_list.addItem(item)
                row = self.step_list.count() - 1
            elif operation == "remove":
                if row < 0:
                    return
                with QSignalBlocker(self.step_list):
                    self.step_list.takeItem(row)
                row = min(row, self.step_list.count() - 1)
            else:
                target = row + (-1 if operation == "up" else 1)
                if row < 0 or not 0 <= target < self.step_list.count():
                    return
                with QSignalBlocker(self.step_list):
                    item = self.step_list.takeItem(row)
                    self.step_list.insertItem(target, item)
                row = target
            with QSignalBlocker(self.step_list):
                self.step_list.setCurrentRow(row)
            self.display_step(row)
            self.mark_dirty()
        except ValueError as error:
            self.status_label.setText(str(error))

    def current_document(self):
        if self.mode == 1:
            return parse_script(self.source_edit.toPlainText())
        self.commit_event()
        return validate_script(self.document)

    def check_script(self):
        try:
            data = self.current_document()
            self.status_label.setText(f"结构校验通过：{len(data)} 个事件、{sum(len(event['actions']) for event in data)} 个动作；内核方法需在运行时由内核提供。")
        except ValueError as error:
            self.status_label.setText(f"校验失败：{error}")

    def save(self, checked=False, *, as_new=False):
        try:
            data = self.current_document()
            path = self.path
            if as_new or path is None:
                initial = path or Path(PATHS["root"]) / "actions" / "新脚本.json"
                chosen, _ = QFileDialog.getSaveFileName(self, "保存动作脚本", str(initial), "JSON 脚本 (*.json)")
                if not chosen:
                    return False
                path = Path(chosen)
                if path.suffix.lower() != ".json":
                    path = path.with_name(path.name + ".json")
            save_script(path, data)
            self.path = path
            self.path_label.setText(str(path))
            with QSignalBlocker(self.file_combo):
                index = self.file_combo.findData(str(path))
                if index < 0:
                    self.file_combo.addItem(script_key(path), str(path))
                    index = self.file_combo.count() - 1
                self.file_combo.setCurrentIndex(index)
            self.setWindowModified(False)
            self.status_label.setText("脚本已保存")
            self.script_saved.emit(str(path))
            return True
        except (OSError, ValueError) as error:
            self.status_label.setText(f"保存失败：{error}")
            return False

    def can_leave(self):
        if not self.isWindowModified():
            return True
        answer = QMessageBox.question(self, "未保存的脚本", "脚本有未保存的修改，是否保存？",
                                      QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel, QMessageBox.Cancel)
        if answer == QMessageBox.Save:
            return self.save()
        if answer == QMessageBox.Discard:
            self.setWindowModified(False)
            return True
        return False

    def select_file(self, index):
        path = self.file_combo.itemData(index)
        if path is None:
            return
        try:
            data = read_script(path)
            if self.can_leave():
                self.load_document(data, Path(path))
                return
        except (OSError, ValueError) as error:
            self.status_label.setText(f"脚本打开失败：{error}")
        with QSignalBlocker(self.file_combo):
            self.file_combo.setCurrentIndex(self.file_combo.findData(str(self.path)) if self.path else -1)

    def open_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "打开动作脚本", str(Path(PATHS["root"]) / "actions"), "JSON 脚本 (*.json)")
        if not path:
            return
        try:
            data = read_script(path)
            if self.can_leave():
                self.load_document(data, Path(path))
        except (OSError, ValueError) as error:
            self.status_label.setText(f"脚本打开失败：{error}")

    def new_script(self):
        if self.can_leave():
            self.load_document([new_event()], None)

    def reject(self):
        if self.operation is not None:
            self.close_pending = True
            self.stop_operation()
            return
        if self.can_leave():
            super().reject()

    def closeEvent(self, event):
        if self.operation is not None:
            self.close_pending = True
            self.stop_operation()
            event.ignore()
            return
        if self.can_leave():
            event.accept()
        else:
            event.ignore()
