import argparse
import ctypes
import json
import os
import shutil
import subprocess
import sys
import time
import hashlib

import keyboard
from PyQt5.QtGui import QFont

from route import PATHS
from tool import EXTRA
from tool.action_script import run_script as run_action_script
from tool.cleanup import (
    CATEGORIES,
    CATEGORY_BUTTONS,
    MODE_NAMES,
    MODES,
    TRIGGER_NAMES,
    TRIGGERS,
    UNIT_NAMES,
    UNITS,
    CleanupConfig,
    CleanupItem,
    cleanup_manual,
    finish_manual_cleanup,
    last_cleanup_text,
    load_cleanup_config,
    run_cleanup,
    validate_config,
    write_config,
)
from tool.GLOBAL import get_global_stop_flag, set_global_stop_flag
from tool.gui.advanced_features import show_unlock_dialog
from tool.gui.schedule_dialog import ScheduleDialog, ScheduleTimer
from tool.gui.script_editor import ScriptEditor
from tool.log import CUS_LOGGER, log_emitter
from tool.registry import KernelRegistry
from tool.script_files import discover_scripts, read_script, script_key, script_path
from tool.script_tools import capture_sample, debug_events
from tool.settings import load_settings, update_settings
from tool.thread import ThreadWithException
from tool.utils.game_install import (
    find_star_rail_executable,
    is_global_star_rail_executable,
)
from tool.utils.game_process import is_star_rail_process_running
from tool.utils.game_window import find_game_window
from tool.utils.image_tool import find_image_by_name, load_all_images_from_directory
from tool.window_recorder.video_remux import (
    convert_to_standard_mp4,
    convert_with_tail_trimmed,
    needs_conversion,
)

load_all_images_from_directory()
import faulthandler

from PyQt5.QtCore import QSignalBlocker, Qt, QTimer, pyqtSignal, pyqtSlot
from PyQt5.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QTextBrowser,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from align_angle import main as align_angle_main
from logger_printer import QMainWindowLog

HOTKEY_DEBOUNCE_SECONDS = 1.0
# 程序启动时触发的清理延迟执行的毫秒数，让主界面先完成显示。
CLEANUP_STARTUP_DELAY_MS = 1500
STARTUP_TASK_DELAY_SECONDS = 5


def parse_startup_args(argv=None):
    """解析启动时可选的任务及其延迟时间。"""
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument(
        "--start-task",
        metavar="TASK",
        help="启动后自动运行的任务 ID 或按钮名称，例如 IronBlood。",
    )
    parser.add_argument(
        "--start-delay",
        type=int,
        default=STARTUP_TASK_DELAY_SECONDS,
        metavar="SECONDS",
        help=f"任务启动前等待的秒数（默认：{STARTUP_TASK_DELAY_SECONDS}）。",
    )
    args = parser.parse_args(argv)
    if args.start_delay < 0:
        parser.error("--start-delay 必须是大于或等于 0 的整数")

    if args.start_task:
        registry = KernelRegistry()
        search_target = args.start_task.lower()
        spec = next(
            (item for item in registry.runnable() if search_target == item.id.lower()),
            None,
        )
        if spec is None:
            available = ", ".join(item.id for item in registry.runnable())
            parser.error(f"未知任务 {args.start_task!r}；可用任务 ID：{available}")
        args.start_task = spec.id
    return args


def acquire_instance_lock(mutex_name):
    """按程序目录获取单实例锁，允许其他目录中的副本同时运行。"""
    handle = ctypes.windll.kernel32.CreateMutexW(None, True, mutex_name)
    if not handle:
        raise ctypes.WinError()
    if ctypes.windll.kernel32.GetLastError() == 183:
        ctypes.windll.kernel32.CloseHandle(handle)
        return None
    return handle


def show_instance_warning():
    """在控制台提示同目录的程序实例已启动。"""
    try:
        print("当前程序目录下的权杖已经启动，请勿重复启动。")
    except UnicodeEncodeError:
        print("Simulated Scepter is already running in this directory; do not start it again.")


class CleanupSettingsSection(QWidget):
    """自动清理设置区，负责显示三个清理对象的配置并收集用户改动。

    界面控件由 UI.ui 的进阶设置页承载，本类只负责读写这些控件的值：清理
    按钮发出清理请求，实际清理与参数校验由主窗口完成。
    """

    cleanup_requested = pyqtSignal(str)  # 清理对象

    WIDGET_TYPES = {
        "mode_combo": QComboBox,
        "trigger_combo": QComboBox,
        "value_input": QLineEdit,
        "unit_combo": QComboBox,
        "cleanup_btn": QPushButton,
        "last_label": QLabel,
    }

    def __init__(self, page):
        super().__init__(page)

        self.setVisible(False)
        for field in self.WIDGET_TYPES:
            setattr(self, field, {})

        for category in CATEGORIES:
            self._load_widgets(page, category)

            mode_combo = self.mode_combo[category]
            for mode in MODES:
                mode_combo.addItem(MODE_NAMES[mode], mode)
            for trigger in TRIGGERS:
                self.trigger_combo[category].addItem(TRIGGER_NAMES[trigger], trigger)
            for unit in UNITS:
                self.unit_combo[category].addItem(UNIT_NAMES[unit], unit)
            self.cleanup_btn[category].setText(CATEGORY_BUTTONS[category])

            mode_combo.currentIndexChanged.connect(
                lambda _index, name=category: self._refresh_mode(name)
            )
            self.cleanup_btn[category].clicked.connect(
                lambda _checked=False, name=category: self.cleanup_requested.emit(name)
            )

        self._fix_column_layout()
        self.refresh_display()

    def _load_widgets(self, page, category) -> None:
        """取出某个清理对象在 UI.ui 中的全部控件。

        Args:
            page: 承载自动清理设置区的页面。
            category: 清理对象，取 CATEGORIES 之一。

        Raises:
            RuntimeError: UI.ui 与代码版本不一致，缺少必需控件。
        """
        missing = []
        for field, widget_type in self.WIDGET_TYPES.items():
            widget = page.findChild(widget_type, f"Cleanup_{category}_{field}")
            if widget is None:
                missing.append(f"Cleanup_{category}_{field}")
                continue
            getattr(self, field)[category] = widget

        if missing:
            raise RuntimeError(
                "界面文件 resource/ui/UI.ui 与当前代码版本不一致，缺少控件："
                + "、".join(missing)
                + "。请使用与代码相同版本的 UI.ui。"
            )

    def _fix_column_layout(self) -> None:
        """统一操作/参数列各控件的高度与宽度。

        清理模式与触发时机选择框、数值输入框、单位选择框、清理按钮会按模式
        互换显示，这里统一它们的高度与宽度，切换模式时行高与列宽不再变化。
        """
        # 清理模式列容纳“永不清理”等模式名，操作/参数列容纳触发时机、数值与单位。
        mode_width = 120
        action_width = 150

        for category in CATEGORIES:
            button = self.cleanup_btn[category]
            trigger_combo = self.trigger_combo[category]

            # 按钮与触发时机选择框在同一位置交替显示，统一高度以稳定行高，使其美观。
            row_height = button.sizeHint().height()
            trigger_combo.setMinimumHeight(row_height)
            trigger_combo.setSizePolicy(
                QSizePolicy.Preferred, QSizePolicy.Fixed)

            self.mode_combo[category].setFixedWidth(mode_width)
            self.value_input[category].setFixedWidth(60)
            self.unit_combo[category].setFixedWidth(action_width - 60)

    def refresh_display(self, config=None) -> None:
        """按自动清理配置刷新控件内容与可用状态。

        Args:
            config: 需要显示的配置；默认为重新读取配置文件。
        """
        if config is None:
            config = load_cleanup_config()
        for category in CATEGORIES:
            item = config.item(category)
            mode_combo = self.mode_combo[category]
            trigger_combo = self.trigger_combo[category]
            unit_combo = self.unit_combo[category]
            mode_combo.setCurrentIndex(mode_combo.findData(item.mode))
            trigger_combo.setCurrentIndex(trigger_combo.findData(item.trigger))
            self.value_input[category].setText(str(item.value))
            unit_combo.setCurrentIndex(unit_combo.findData(item.unit))
            self.set_last_cleanup(category, item.last_cleanup)
            self._refresh_mode(category)

    def _refresh_mode(self, category: str) -> None:
        """按当前清理模式切换操作/参数列的显示与可用状态。"""
        mode = self.mode_combo[category].currentData()
        if mode is None:
            return
        # 永不清理：按钮不可用；手动清理：按钮可用；周期/自动清理：改由触发时机选择。
        self.cleanup_btn[category].setEnabled(mode != "never")
        self.cleanup_btn[category].setVisible(mode in ("never", "manual"))
        self.trigger_combo[category].setVisible(mode in ("periodic", "automatic"))
        self.value_input[category].setEnabled(mode != "never")
        self.unit_combo[category].setEnabled(mode != "never")

    def collect_config(self) -> CleanupConfig:
        """读取控件中的配置。

        数值无法解析为整数时按 -1 处理，交给参数校验给出提示。

        Returns:
            当前界面上的自动清理配置。
        """
        items = {}
        for category in CATEGORIES:
            text = self.value_input[category].text().strip()
            try:
                value = int(text)
            except ValueError:
                value = -1
            items[category] = CleanupItem(
                mode=self.mode_combo[category].currentData(),
                trigger=self.trigger_combo[category].currentData(),
                value=value,
                unit=self.unit_combo[category].currentData(),
                last_cleanup=self.last_label[category].property("last_cleanup") or "",
            )
        return CleanupConfig(items=items)

    def cleanup_value(self, category: str) -> tuple[int, str]:
        """读取某个清理对象当前的数值与时间单位。

        数值非法时按 0 处理，手动清理因此退化为清理全部符合规则的文件。

        Args:
            category: 清理对象，取 CATEGORIES 之一。

        Returns:
            (数值, 时间单位)。
        """
        text = self.value_input[category].text().strip()
        try:
            value = int(text)
        except ValueError:
            value = 0
        if value < 0:
            value = 0
        return value, self.unit_combo[category].currentData()

    def set_last_cleanup(self, category: str, cleaned_at: str) -> None:
        """更新某个清理对象的上次清理时间文本。"""
        label = self.last_label[category]
        label.setProperty("last_cleanup", cleaned_at)
        label.setText(last_cleanup_text(cleaned_at))


class MainWindow(QMainWindowLog):
    calibration_finished = pyqtSignal(object)
    hotkey_pressed = pyqtSignal(str)
    script_tool_result = pyqtSignal(str, object)

    def __init__(self, start_task=None, start_delay=STARTUP_TASK_DELAY_SECONDS):
        super().__init__()
        # 任务管理相关属性
        self.current_task = None
        self.task_thread = None
        self._task_thread = None
        # 异常视频封装的后台线程，避免重复触发
        self._video_convert_thread = None
        self.scheduler = None
        self.editor_tasks = {}
        self.script_tool_result.connect(lambda session, _result: self.editor_tasks.pop(session, None))
        self._task_monitor_timer = QTimer(self)
        self._task_monitor_timer.setInterval(100)
        self._task_monitor_timer.timeout.connect(self._check_task_thread)
        self._last_key_time = {}
        self._task_running_warning = None

        # 加载快捷键配置并注册监听器
        self.hotkey_config = self.load_hotkey_config()
        self.registered_hotkeys = []

        self.init_ui()
        self.setup_keyboard_listener()
        # 确保热键回调中的 GUI 操作排队回主线程执行
        self.hotkey_pressed.connect(self.handle_key_pressed, Qt.QueuedConnection)
        self.calibration_finished.connect(self.show_calibration_result)
        log_emitter.show_error_signal.connect(self.show_error_message)
        log_emitter.find_path_state_signal.connect(self.set_find_path_state)
        log_emitter.kill_num_signal.connect(self.set_kill_num)
        log_emitter.fps_update_signal.connect(self.set_FPS)
        log_emitter.cleanup_finished_signal.connect(self.refresh_cleanup_state)
        log_emitter.video_convert_finished_signal.connect(self.on_video_convert_finished)

        # 检查是否首次启动并显示用户协议
        self.check_first_launch()

        self.scheduler = ScheduleTimer(self.registry, self.launch_script, self.is_task_running, self.stop_task, self)

        # 程序启动后先让界面完成显示，再按配置执行程序启动时触发的清理
        QTimer.singleShot(CLEANUP_STARTUP_DELAY_MS, lambda: self.cleanup_at("program_start"))
        if start_task is not None:
            spec = self.registry.specs[start_task]
            CUS_LOGGER.debug(
                "将在等待 %s 秒后，自动启动内核 %s。",
                start_delay,
                spec.id,
            )
            QTimer.singleShot(
                start_delay * 1000,
                lambda: self.run_kernel(start_task),
            )

    def create_task_engine(self, kernel_id, *, script=False):
        """创建内核实例，并把它绑到本次任务线程上。

        录制线程每轮检查所属任务线程是否还活着，任务结束就停止录制；
        不绑定的话录制线程会变成孤儿，任务早就停了录像却一直在写。
        """
        engine = self.registry.create_engine(kernel_id, script=script)
        task_thread = getattr(self, "_task_thread", None) or getattr(self, "task_thread", None)
        # 没有录制能力的内核（例如通用脚本内核）没有 recorder；取不到任务线程时也不绑定
        if task_thread is not None and getattr(engine, "recorder", None) is not None:
            engine.recorder.task_owner = task_thread
        return engine

    def start_task(self, task_func):
        """
        启动一个新任务
        """
        if self.scheduler is not None and not self.scheduler.dispatching and (self.is_task_running() or self.scheduler.has_pending()):
            self.scheduler.queue_task(lambda: self.start_task(task_func), task_func)
            self.scheduler.poll()
            return

        if self.task_thread is not None:
            if self.task_thread.is_alive():
                raise RuntimeError("上一个任务仍在停止，请稍候")
            self.task_thread = None
            self.current_task = None

        if self.start_game_checkbox.isChecked():
            game_running = find_game_window() is not None
            if not game_running:
                try:
                    game_running = is_star_rail_process_running()
                except OSError as error:
                    CUS_LOGGER.error("无法检查崩坏：星穹铁道进程：%s", error, exc_info=True)
                    QMessageBox.warning(self, "无法确认游戏状态", "无法检查游戏进程，本次不会尝试启动游戏。")
                    return

            if not game_running:
                game_path = self.game_path_input.text().strip().strip('"')
                is_global_game = is_global_star_rail_executable(game_path) if game_path else False
                if not game_path:
                    discovered_game = find_star_rail_executable()
                    if discovered_game:
                        game_path, is_global_game = discovered_game
                        self.game_path_input.setText(game_path)
                if (not os.path.isabs(game_path)
                        or os.path.basename(game_path).casefold() != "starrail.exe"
                        or not os.path.isfile(game_path)):
                    CUS_LOGGER.error("未能自动找到游戏，请在进阶设置中填写有效的 StarRail.exe 完整路径。")
                    QMessageBox.warning(
                        self, "无法启动游戏",
                        "未能自动找到游戏，请在进阶设置中填写有效的 StarRail.exe 完整路径。",
                    )
                    return
                self.save_game_path_config()
                try:
                    subprocess.Popen([game_path], cwd=os.path.dirname(game_path))
                except OSError as error:
                    CUS_LOGGER.error("无法启动崩坏：星穹铁道：%s", error, exc_info=True)
                    QMessageBox.warning(self, "无法启动游戏", f"启动 StarRail.exe 失败：{error}")
                    return
                if is_global_game:
                    CUS_LOGGER.info("本次启动的是国际服崩坏·星穹铁道")
                CUS_LOGGER.info("未检测到崩坏：星穹铁道，已尝试启动 StarRail.exe。")
            else:
                CUS_LOGGER.debug("已检测到崩坏：星穹铁道窗口或进程，跳过重复启动。")

        if self.scheduler is not None:
            self.scheduler.release_active()

        set_global_stop_flag(False)
        # 捕获本次任务的线程对象本身：录制要绑的是「这一个」任务线程，
        # 而不是 self.task_thread 这个会被下一次任务覆盖的属性。
        task_thread = ThreadWithException(target=task_func, name="主任务线程")
        self.task_thread = task_thread
        self._task_thread = task_thread
        task_thread.start()
        # 更新任务状态标签为"运行中"
        self.Label_RunningState.setText("任务序列线程状态: 运行中")

        # 任务开始后再执行任务启动时触发的清理，避免清理耗时拖后任务启动
        self.cleanup_at("task_start")

        # 启动异步线程状态监控
        if not self._task_monitor_timer.isActive():
            self._task_monitor_timer.start()

    def _check_task_thread(self):
        """
        异步检查任务线程是否已经退出。
        不使用 join，避免阻塞 Qt 主线程。
        """
        if self.task_thread is None:
            self._task_monitor_timer.stop()
            return

        if self.task_thread.is_alive():
            return

        # 线程已经确认退出，现在才清理引用
        self.task_thread = None
        self.current_task = None
        set_global_stop_flag(False)

        self.Label_RunningState.setText("任务序列线程状态: 未运行")
        self._task_monitor_timer.stop()

        # 任务结束触发时机：此时任务线程已经退出，任务占用的文件已释放
        self.cleanup_at("task_end")

    def is_task_running(self):
        """
        检查是否有任务正在运行
        """
        return self.task_thread is not None and self.task_thread.is_alive()

    def stop_task(self):
        """
        请求停止当前任务。
        不等待线程退出，由 QTimer 异步检查线程状态。
        """
        if self.task_thread is None:
            set_global_stop_flag(False)
            return False

        # 发出停止请求
        set_global_stop_flag(True)

        if self.current_task and hasattr(self.current_task, 'stop'):
            self.current_task.stop()

        # 不在 Qt 主线程中 join，避免阻塞 GUI
        self.Label_RunningState.setText("任务序列线程状态: 停止中")

        # 确保异步监控正在运行
        if not self._task_monitor_timer.isActive():
            self._task_monitor_timer.start()

        return False

    def show_error_message(self, title, error_msg):
        """显示错误消息弹窗，支持复制内容并强制置顶"""
        msg = QMessageBox(self)
        msg.setIcon(QMessageBox.Critical)
        msg.setWindowTitle("出错了！！！")
        msg.setText(title)
        msg.setStandardButtons(QMessageBox.Ok)

        # 设置窗口标志，确保弹窗置顶显示
        msg.setWindowFlags(msg.windowFlags() | Qt.WindowStaysOnTopHint)

        # 设置详细文本，这样用户可以选中并复制内容
        msg.setDetailedText(error_msg)

        # 显示弹窗并强制置顶
        msg.show()
        msg.raise_()
        msg.activateWindow()

        # 等待用户关闭弹窗
        msg.exec_()


    def init_ui(self):
        self.registry = KernelRegistry()
        for module, error in self.registry.errors.items():
            CUS_LOGGER.error("内核 %s 不可用：%s", module, error)
        self.init_kernel_buttons()
        self.init_script_controls()
        self.script_editor_btn.clicked.connect(self.open_script_editor)
        self.schedule_btn.clicked.connect(self.open_schedule)
        self.engine_settings_btn.clicked.connect(
            lambda: self.open_engine_settings(self.engine_combo.currentData()))
        self.calibrate_btn.clicked.connect(self.calibrate)
        self.test_btn.clicked.connect(self.test)
        self.print_btn.clicked.connect(self.test_2)
        self.stop_btn.clicked.connect(self.stop_task)
        self.general_settings_save_btn.clicked.connect(self.save_general_config)
        self.hotkey_save_btn.clicked.connect(self.save_hotkey_config)
        self.record_stats_btn.clicked.connect(self.open_record_stats)
        self.Aboutupdatelock.clicked.connect(lambda: show_unlock_dialog(self))
        self.video_convert_btn.clicked.connect(self.start_video_convert)
        self.video_convert_mode_combo.addItem("严格模式：自动删除末尾的不正常帧", "strict")
        self.video_convert_mode_combo.addItem(
            "抢救模式：尽可能保留更多帧，结尾有概率出现异常帧", "rescue")

        self.opt = data = load_settings()
        self.start_game_checkbox.setChecked(data.get("start_game_on_task", False))
        self.game_path_input.setText(data.get("game_executable_path", ""))
        self.recording_checkBox.setChecked(data.get("recording_state", False))
        self.recording_checkBox2.setChecked(data.get("recording_iron_blood", False))
        self.recording_time_input.setText(str(data.get("del_record_time", 14)))
        self.record_event_map_checkbox.setChecked(data.get("record_event_map", False))
        self.recording_keep_long_run_checkbox.setChecked(data.get("recording_keep_long_run", False))
        self.recording_keep_long_run_threshold_input.setText(str(data.get("recording_keep_long_run_threshold", 1.2)))
        self.recording_label_checkbox.setChecked(data.get("record_add_label", True))
        self.check_model_file()

        self.cleanup_section = CleanupSettingsSection(self.advanced_settings_main_page)
        self.cleanup_section.cleanup_requested.connect(self.cleanup_category)
        self.Cleanup_save_btn.clicked.connect(self.save_cleanup_config)
        hotkeys = data.get("hotkeys", {})
        self.stop_hotkey_input.setText(hotkeys.get("stop", "f5"))
        self.test_hotkey_input.setText(hotkeys.get("test", "f6"))
        self.print_hotkey_input.setText(hotkeys.get("print", "f7"))
        self.update_button_hotkey_text(hotkeys)
        self.update_dependent_controls_state()
        self.connect_dependency_signals()
        tray = next((spec for spec in self.registry.runnable() if spec.tray), None)
        if tray is None:
            tray = next((spec for spec in self.registry.runnable() if spec.button), None)
        self.restore_action.setEnabled(tray is not None)
        if tray is not None:
            self.restore_action.triggered.connect(lambda: self.run_kernel(tray.id))

    def open_engine_settings(self, engine):
        """主窗口只选择配置入口，控件和保存逻辑由各独立模块管理。"""
        try:
            dialog = self.registry.create_settings(engine, self)
        except Exception as error:
            CUS_LOGGER.error("配置加载失败：%s", error, exc_info=True)
            QMessageBox.critical(self, "配置加载失败", f"无法打开内核配置：{error}")
            return
        try:
            if dialog.exec_() == QDialog.Accepted:
                self.opt = load_settings()
        finally:
            dialog.deleteLater()


    def load_hotkey_config(self):
        """从 settings.json 加载快捷键配置"""
        default_config = {
            "stop": "f5",
            "test": "f6",
            "print": "f7"
        }

        try:
            settings_path = os.path.join(PATHS["config"], "settings.json")
            example_path = os.path.join(PATHS["example"], "settings_example.json")
            if not os.path.exists(settings_path) and os.path.exists(example_path):
                shutil.copy2(example_path, settings_path)
            with EXTRA.FILE_LOCK:
                with open(settings_path, encoding="UTF-8") as file:
                    data = json.load(file)

            hotkey_config = data.get("hotkeys", default_config)

            # 确保所有必需的快捷键都存在
            for key in ["stop", "test", "print"]:
                if key not in hotkey_config:
                    hotkey_config[key] = default_config[key]

            return hotkey_config
        except Exception as e:
            print(f"加载快捷键配置失败：{e}，使用默认配置")
            return default_config

    def setup_keyboard_listener(self):
        """
        设置键盘监听器，根据 UI 配置监听自定义快捷键
        """
        # 使用当前 hotkey_config 注册快捷键监听
        for action, key in self.hotkey_config.items():
            if key and key.lower() != "none":
                keyboard.on_press_key(key.lower(), lambda event, act=action: self._on_hotkey_pressed(event, act))
                self.registered_hotkeys.append(key.lower())

    def update_settings(self, updates):
        self.opt = update_settings(updates)

    def _on_hotkey_pressed(self, event, action):
        """
        当自定义快捷键被按下时的回调函数（运行在键盘监听线程，仅发射信号）
        """
        current_time = time.time()
        key = event.name.lower()

        # 防重复触发
        last_time = self._last_key_time.get(key, 0)
        if current_time - last_time > HOTKEY_DEBOUNCE_SECONDS:
            self._last_key_time[key] = current_time

            if action in {"stop", "test", "print"}:
                self.hotkey_pressed.emit(action)

    @pyqtSlot(str)
    def handle_key_pressed(self, action):
        """
        快捷键信号的槽函数（运行在主线程）
        """
        if action in {"test", "print"} and not bool(self.opt.get("debug", False)):
            return
        if action == "stop":
            if self.is_task_running():
                self.stop_btn.click()
        elif action == "test":
            if self.is_task_running():
                self.show_task_running_warning()
            else:
                self.test_btn.click()
        elif action == "print":
            if self.is_task_running():
                self.show_task_running_warning()
            else:
                self.print_btn.click()

    def show_task_running_warning(self):
        """
        非阻塞显示热键冲突提示，避免任务运行时嵌套弹窗事件循环。
        """
        if self._task_running_warning and self._task_running_warning.isVisible():
            self._task_running_warning.raise_()
            self._task_running_warning.activateWindow()
            return

        msg = QMessageBox(self)
        msg.setIcon(QMessageBox.Warning)
        msg.setWindowTitle("警告")
        msg.setText("已有任务正在运行")
        msg.setStandardButtons(QMessageBox.Ok)
        msg.setWindowFlags(msg.windowFlags() | Qt.WindowStaysOnTopHint)
        msg.setAttribute(Qt.WA_DeleteOnClose, True)
        msg.finished.connect(lambda result: self.clear_task_running_warning(result))
        self._task_running_warning = msg
        msg.open()
        msg.raise_()
        msg.activateWindow()

    @pyqtSlot(int)
    def clear_task_running_warning(self, _result):
        self._task_running_warning = None

    def update_button_hotkey_text(self, hotkey_config):
        stop_key = hotkey_config.get("stop", "f5").upper()
        test_key = hotkey_config.get("test", "f6").upper()
        print_key = hotkey_config.get("print", "f7").upper()

        self.stop_btn.setText(f"停止任务 {stop_key}")
        self.test_btn.setText(f"截图测试 {test_key}")
        self.print_btn.setText(f"打印坐标 {print_key}")

    def refresh_keyboard_listener(self):
        keyboard.unhook_all()
        self.registered_hotkeys.clear()
        for action, key in self.hotkey_config.items():
            if key and key.lower() != "none":
                keyboard.on_press_key(key.lower(), lambda event, act=action: self._on_hotkey_pressed(event, act))
                self.registered_hotkeys.append(key.lower())

    def update_dependent_controls_state(self):
        self.game_path_input.setEnabled(self.start_game_checkbox.isChecked())
        debug_enabled = bool(self.opt.get("debug", False))
        recording_enabled = self.recording_checkBox2.isEnabled() and self.recording_checkBox2.isChecked()
        self.recording_time_input.setEnabled(recording_enabled)
        self.kernel_buttons.setVisible(not debug_enabled)
        for widget in (
            self.engine_label, self.engine_combo, self.engine_settings_btn,
            self.script_label, self.script_combo, self.run_script_btn,
            self.test_btn, self.print_btn, self.PrintEdit, self.PrintPhoto, self.PrintText,
            self.label_test_hotkey, self.test_hotkey_input, self.label_print_hotkey, self.print_hotkey_input,
        ):
            widget.setVisible(debug_enabled)
        self.debug_group.setVisible(debug_enabled)
        for widget in (self.recording_keep_long_run_checkbox,
                       self.recording_keep_long_run_threshold_input,
                       self.recording_label_checkbox):
            widget.setEnabled(debug_enabled and recording_enabled)


    def connect_dependency_signals(self):
        self.start_game_checkbox.toggled.connect(self.update_dependent_controls_state)
        self.recording_checkBox2.toggled.connect(self.update_dependent_controls_state)
        self.game_path_input.editingFinished.connect(self.save_game_path_config)


    def save_game_path_config(self):
        """路径有效时自动保存，保留合并写入避免覆盖其他设置。"""
        game_path = self.game_path_input.text().strip().strip('"')
        if (not os.path.isabs(game_path)
                or os.path.basename(game_path).casefold() != "starrail.exe"
                or not os.path.isfile(game_path)
                or self.opt.get("game_executable_path") == game_path):
            return
        try:
            self.update_settings({"game_executable_path": game_path})
        except (OSError, ValueError) as error:
            CUS_LOGGER.warning("崩铁路径自动保存失败：%s", error)
            QMessageBox.warning(self, "保存失败", f"崩铁路径无法自动保存：{error}")


    def closeEvent(self, event):
        """
        窗口关闭事件，清理键盘监听器
        """
        self.scheduler.timer.stop()
        keyboard.unhook_all()
        super().closeEvent(event)

    def test(self):
        kernel_id = self.engine_combo.currentData()
        if kernel_id is None:
            return

        def task():
            self.current_task = self.create_task_engine(kernel_id)
            self.current_task.save_screen()

        try:
            self.start_task(task)
        except RuntimeError as error:
            QMessageBox.warning(self, "警告", str(error))

    def test_2(self):
        kernel_id = self.engine_combo.currentData()
        if kernel_id is None:
            return
        print_text = self.PrintEdit.text()
        photo, text_only = self.PrintPhoto.isChecked(), self.PrintText.isChecked()

        def task():
            self.current_task = su = self.create_task_engine(kernel_id)
            if photo:
                su.click_target(find_image_by_name(print_text), 0.9, True)
            elif text_only:
                su.click_text(print_text, click=False, find_all=True)
            else:
                su.click_text(print_text, click=True)

        try:
            self.start_task(task)
        except RuntimeError as error:
            QMessageBox.warning(self, "警告", str(error))

    def init_kernel_buttons(self):
        """普通运行按钮及齿轮由模块声明，主 UI 仅提供容器。"""
        self.kernel_rows = {}
        for spec in sorted(self.registry.runnable(), key=lambda spec: spec.button_order):
            if not spec.button:
                continue
            row = QWidget(self.kernel_buttons)
            layout = QHBoxLayout(row)
            layout.setContentsMargins(0, 0, 0, 0)
            button = QPushButton(spec.button, row)
            button.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
            button.setToolTip(spec.description)
            gear = QToolButton(row)
            gear.setProperty("kernelSettings", True)
            gear.setToolTip(f"{spec.description}配置")
            gear.setFixedWidth(30)
            gear.setMinimumHeight(24)
            button.clicked.connect(lambda checked=False, key=spec.id: self.run_kernel(key))
            gear.clicked.connect(lambda checked=False, key=spec.id: self.open_engine_settings(key))
            layout.addWidget(button, 1)
            layout.addWidget(gear)
            self.kernel_button_layout.addWidget(row)
            self.kernel_rows[spec.id] = (button, gear)
        self.set_exit_and_minimized_btn_icon()

    def init_script_controls(self):
        """恢复模块 ID 和可迁移的脚本路径，发现阶段不导入运行代码。"""
        for spec in self.registry.runnable():
            self.engine_combo.addItem(spec.name, spec.id)
            self.engine_combo.setItemData(self.engine_combo.count() - 1, spec.description, Qt.ToolTipRole)
        available = self.engine_combo.count() > 0
        for widget in (self.engine_combo, self.engine_settings_btn, self.test_btn, self.print_btn):
            widget.setEnabled(available)
        self.calibrate_btn.setEnabled(any(spec.calibration for spec in self.registry.runnable()))
        self.run_script_btn.clicked.connect(self.run_script)
        self.refresh_scripts()
        engine_index = self.engine_combo.findData(self.opt.get("script_engine", ""))
        if engine_index >= 0:
            self.engine_combo.setCurrentIndex(engine_index)
        saved = self.opt.get("script_file", "")
        for index in range(self.script_combo.count()):
            script = self.script_combo.itemData(index)
            if script and (script_key(script) == saved
                           or os.path.basename(script) == saved):
                self.script_combo.setCurrentIndex(index)
                break
        self.engine_combo.currentIndexChanged.connect(self.save_script_selection)
        self.script_combo.currentIndexChanged.connect(self.save_script_selection)

    def save_script_selection(self):
        """保存内核 ID 及脚本路径，项目内脚本随项目目录迁移。"""
        updates = {"script_engine": self.engine_combo.currentData()}
        script_path = self.script_combo.currentData()
        if script_path is not None:
            updates["script_file"] = script_key(script_path)
        try:
            self.update_settings(updates)
        except (OSError, ValueError) as error:
            CUS_LOGGER.error("保存脚本选项失败：%s", error)
            QMessageBox.warning(self, "提示", f"保存脚本选项失败：{error}")

    def refresh_scripts(self, selected=None):
        """列出用户脚本和可用模块自带脚本，排除角色别名等数据文件。"""
        chosen = selected or self.script_combo.currentData()
        paths = discover_scripts(self.registry)
        saved = self.opt.get("script_file", "")
        candidate = script_path(chosen or saved) if chosen or saved else None
        if candidate is not None and candidate not in paths:
            try:
                read_script(candidate)
                paths.append(candidate)
            except (OSError, ValueError):
                candidate = None
        with QSignalBlocker(self.script_combo):
            self.script_combo.clear()
            for path in paths:
                self.script_combo.addItem(path.stem, str(path))
                self.script_combo.setItemData(self.script_combo.count() - 1, script_key(path), Qt.ToolTipRole)
            index = self.script_combo.findData(str(candidate)) if candidate else -1
            if index >= 0:
                self.script_combo.setCurrentIndex(index)
            available = bool(paths)
            if not available:
                self.script_combo.addItem("actions 中没有可用脚本")
        self.script_combo.setEnabled(available)
        self.run_script_btn.setEnabled(available and self.engine_combo.count() > 0)

    def run_script(self):
        script_path = self.script_combo.currentData()
        kernel_id = self.engine_combo.currentData()
        if script_path is None or kernel_id is None:
            QMessageBox.warning(self, "提示", "请选择可用的内核和 JSON 动作脚本。")
            return
        try:
            self.launch_script(kernel_id, script_path)
        except (OSError, ValueError, RuntimeError) as error:
            QMessageBox.warning(self, "脚本无法启动", str(error))

    def launch_script(self, kernel_id, path):
        """手动与计划任务共用入口；计划参数不修改当前下拉框选择。"""
        spec = self.registry.specs.get(kernel_id)
        if spec is None or not spec.factory:
            raise ValueError("所选内核不可用")
        read_script(path)
        engine_name = spec.name
        stop_key = self.load_hotkey_config()["stop"].upper()

        def task():
            self.current_task = su = self.create_task_engine(kernel_id, script=True)
            CUS_LOGGER.info("使用%s内核运行脚本：%s；点击“停止任务”或按 %s 可终止。",
                            engine_name, os.path.basename(path), stop_key)
            run_action_script(su, path)

        self.start_task(task)

    def open_script_editor(self):
        dialog = ScriptEditor(self.registry, self.script_combo.currentData(), self)
        dialog.script_saved.connect(self.script_saved)
        dialog.debug_kernel_combo.setCurrentIndex(dialog.debug_kernel_combo.findData(self.engine_combo.currentData()))
        dialog.sample_requested.connect(self.capture_script_sample)
        dialog.debug_requested.connect(self.debug_script_events)
        dialog.stop_requested.connect(self.stop_editor_task)
        self.script_tool_result.connect(dialog.receive_result)
        try:
            dialog.exec_()
        finally:
            dialog.deleteLater()

    def capture_script_sample(self, session, kernel, recognize):
        self.run_editor_task(session, kernel, lambda engine: {"sample": capture_sample(engine, recognize)},
                             "识别文字取样" if recognize else "框选图片取样")

    def debug_script_events(self, session, kernel, events, direct):
        self.run_editor_task(session, kernel, lambda engine: {"message": debug_events(engine, events, direct)},
                             "直接执行动作" if direct else "按触发条件调试")

    def run_editor_task(self, session, kernel, operation, description):
        def task():
            engine = None
            result = {"message": "操作已停止"}
            try:
                if find_game_window() is None:
                    raise RuntimeError("未找到游戏窗口，请启动游戏后重新截取或调试")
                self.current_task = engine = self.registry.create_engine(kernel, script=True)
                if not engine._stop and not get_global_stop_flag():
                    CUS_LOGGER.info("脚本编辑器开始%s，使用 %s 内核；按 %s 可停止。",
                                    description, kernel, self.load_hotkey_config()["stop"].upper())
                    result = operation(engine)
                    if get_global_stop_flag():
                        result = {"message": "操作已停止"}
            except InterruptedError:
                result = {"message": "操作已停止"}
            except Exception as error:
                result = {"error": str(error)}
                CUS_LOGGER.error("脚本编辑器操作失败：%s", error, exc_info=True)
            finally:
                if engine is not None and not engine._stop:
                    try:
                        engine.stop()
                    except Exception as error:
                        result = {"error": f"运行资源释放失败：{error}"}
                        CUS_LOGGER.error("脚本编辑器的运行资源释放失败：%s", error, exc_info=True)
                self.script_tool_result.emit(session, result)

        self.editor_tasks[session] = task
        try:
            self.start_task(task)
        except RuntimeError as error:
            self.script_tool_result.emit(session, {"error": str(error)})

    def stop_editor_task(self, session):
        task = self.editor_tasks.get(session)
        if task is None:
            return
        if self.scheduler.cancel_task(task):
            self.script_tool_result.emit(session, {"message": "排队任务已取消"})
        elif self.task_thread is not None and self.task_thread.target is task:
            try:
                self.stop_task()
            except Exception as error:
                CUS_LOGGER.error("编辑器任务的停止请求未完成，继续等待线程退出：%s", error, exc_info=True)

    def script_saved(self, path):
        self.refresh_scripts(path)
        self.save_script_selection()

    def open_schedule(self):
        dialog = ScheduleDialog(self.scheduler, self.registry, self)
        try:
            dialog.exec_()
        finally:
            dialog.deleteLater()

    def run_kernel(self, kernel_id):
        def task():
            self.current_task = self.create_task_engine(kernel_id)
            self.current_task.start()

        try:
            self.start_task(task)
        except RuntimeError as error:
            QMessageBox.warning(self, "警告", str(error))


    def calibrate(self):
        spec = next((spec for spec in self.registry.runnable() if spec.calibration), None)
        if spec is None:
            return

        def task():
            try:
                self.current_task = self.create_task_engine(spec.id)
                res = align_angle_main(su=self.current_task)
                self.calibration_finished.emit(res)
            except Exception as e:
                self.calibration_finished.emit(e)

        try:
            self.start_task(task)
        except RuntimeError as e:
            QMessageBox.warning(self, "警告", str(e))

    def show_calibration_result(self, result):
        if isinstance(result, Exception):
            QMessageBox.critical(self, "错误", f"校准失败: {str(result)}")
        elif result == 1:
            QMessageBox.information(self, "成功", "校准成功！")
        else:
            QMessageBox.warning(self, "失败", "校准失败，请重试。")


    def open_record_stats(self):
        os.startfile(os.path.join(PATHS["html"], "record_stats.html"))

    def start_video_convert(self):
        """把 video 目录下尚未封装的录像按所选模式封装。

        转换在后台线程逐个进行，界面保持可用；结束后由信号回到主线程恢复按钮并提示结果。
        严格模式会先丢弃末尾无法解码的帧，抢救模式则尽可能保留更多帧。
        """
        if self._video_convert_thread is not None and self._video_convert_thread.is_alive():
            return

        video_dir = PATHS["video"]
        if not os.path.isdir(video_dir):
            QMessageBox.information(self, "异常视频封装", "未检测到需要封装的视频")
            return

        # 只处理仍是分片格式的录像：标准 mp4 已经可以正常跳转
        pending = [os.path.join(video_dir, name)
                   for name in sorted(os.listdir(video_dir))
                   if needs_conversion(os.path.join(video_dir, name))]
        if not pending:
            QMessageBox.information(self, "异常视频封装", "未检测到需要封装的视频")
            return

        mode = self.video_convert_mode_combo.currentData()
        self.video_convert_btn.setEnabled(False)
        self.video_convert_btn.setText("转换中...")
        self._video_convert_thread = ThreadWithException(
            target=self._run_video_convert, kwargs={"paths": pending, "mode": mode},
            name="异常视频封装", is_print=False)
        self._video_convert_thread.start()

    def _run_video_convert(self, paths, mode):
        """后台线程：逐个封装，不删除原文件。"""
        succeeded = failed = 0
        for source in paths:
            # 输出用「原文件名」+ 模式后缀，原文件保持不变
            suffix = "-严格模式" if mode == "strict" else "-抢救模式"
            base, ext = os.path.splitext(source)
            target = f"{base}{suffix}{ext}"
            try:
                if mode == "strict":
                    ok = convert_with_tail_trimmed(source, target, del_frames=False)
                else:
                    ok = convert_to_standard_mp4(
                        source, check_source=False, check_output=False, target=target)
            except Exception as error:
                CUS_LOGGER.error(f"封装录像失败：{source}（{error}）")
                ok = False
            if ok:
                succeeded += 1
            else:
                failed += 1
        log_emitter.video_convert_finished_signal.emit(succeeded, failed)

    def on_video_convert_finished(self, succeeded, failed):
        """转换结束：恢复按钮并提示结果。"""
        self.video_convert_btn.setText("转换")
        self.video_convert_btn.setEnabled(True)
        QMessageBox.information(
            self, "异常视频封装",
            f"转换成功：{succeeded}个文件，转换失败：{failed}个文件")


    def save_hotkey_config(self):
        hotkey_config = {
            "stop": self.stop_hotkey_input.text().strip(),
            "test": self.test_hotkey_input.text().strip(),
            "print": self.print_hotkey_input.text().strip(),
        }

        self.update_settings({
            "hotkeys": hotkey_config
        })

        self.hotkey_config = hotkey_config
        self.refresh_keyboard_listener()
        self.update_button_hotkey_text(self.hotkey_config)

        QMessageBox.information(self, "提示", "快捷键配置已保存")

    def save_general_config(self):
        try:
            self.update_settings({
                "start_game_on_task": self.start_game_checkbox.isChecked(),
                "game_executable_path": self.game_path_input.text().strip(),
                "recording_state": self.recording_checkBox.isChecked(),
                "recording_iron_blood": self.recording_checkBox2.isChecked(),
                "del_record_time": int(self.recording_time_input.text()),
                "record_event_map": self.record_event_map_checkbox.isChecked(),
                "recording_keep_long_run": self.recording_keep_long_run_checkbox.isChecked(),
                "recording_keep_long_run_threshold": float(self.recording_keep_long_run_threshold_input.text()),
                "record_add_label": self.recording_label_checkbox.isChecked(),
            })
        except (ValueError, OSError) as error:
            QMessageBox.warning(self, "保存失败", f"通用设置无法保存：{error}")
            return
        QMessageBox.information(self, "提示", "通用设置已保存")


    def save_cleanup_config(self):
        """校验并保存自动清理设置，参数非法时拒绝写入配置文件。"""
        config = self.cleanup_section.collect_config()

        errors = validate_config(config)
        if errors:
            QMessageBox.warning(
                self,
                "参数错误",
                "以下参数不合法，自动清理设置未保存：\n" + "\n".join(errors),
            )
            return

        try:
            write_config(config)
        except OSError as error:
            QMessageBox.critical(self, "错误", f"自动清理设置保存失败：{error}")
            return

        QMessageBox.information(self, "提示", "自动清理设置已保存")

    def cleanup_category(self, category):
        """响应用户点击清理按钮，按当前数值与时间单位清理一类文件。

        Args:
            category: 清理对象，取 CATEGORIES 之一。
        """
        value, unit = self.cleanup_section.cleanup_value(category)
        config = self.cleanup_section.collect_config()
        # 手动清理以界面上的数值与时间单位为期限，不受是否已保存影响。
        config.items[category] = CleanupItem(
            mode=config.item(category).mode,
            trigger=config.item(category).trigger,
            value=value,
            unit=unit,
            last_cleanup=config.item(category).last_cleanup,
        )

        result = cleanup_manual(config, category)
        cleaned_at = finish_manual_cleanup(result)
        self.cleanup_section.set_last_cleanup(category, cleaned_at)

        QMessageBox.information(self, "清理结果", result.summary)

    def cleanup_at(self, trigger):
        """在某个触发时机执行周期清理与自动清理。

        清理可能涉及大量文件的删除，放在后台线程执行，避免任务启动时阻塞
        主界面；结果由 cleanup_finished_signal 回到主线程刷新显示。上一次
        清理尚未结束时，run_cleanup 会跳过本次触发。

        Args:
            trigger: 触发时机，取 TRIGGERS 之一。
        """
        ThreadWithException(
            target=run_cleanup,
            kwargs={"trigger": trigger},
            name=f"自动清理-{trigger}",
            is_print=False,
        ).start()

    def refresh_cleanup_state(self, _results):
        """按清理后的配置文件刷新上次清理时间显示。"""
        self.cleanup_section.refresh_display()

    def set_FPS(self,TimePerFrame):
        Fps = 1.0 / float(TimePerFrame)
        Fps = round(Fps, 2)
        self.FPS_Input.setText(str(Fps))

    def set_find_path_state(self, text:str):
        self.state_text.setText(text)
    def set_kill_num(self, num:str):
        self.kill_num_text.setText(num)

    def check_first_launch(self):
        """
        检查是否首次启动，如果是则显示用户协议弹窗
        """
        cache_dir = os.path.join(PATHS["root"], "cache")
        agreement_file = os.path.join(cache_dir, "agreement_accepted.txt")

        # 如果标记文件不存在，则为首次启动
        if not os.path.exists(agreement_file):
            self.show_agreement_dialog(agreement_file)

    def show_agreement_dialog(self, agreement_file):
        """
        显示用户协议弹窗
        :param agreement_file: 协议接受标记文件路径
        """
        dialog = QDialog(self)
        dialog.setWindowTitle("用户协议与免责声明")
        dialog.setModal(True)
        dialog.resize(800, 600)

        # 设置窗口标志，确保弹窗置顶
        dialog.setWindowFlags(dialog.windowFlags() | Qt.WindowStaysOnTopHint)

        layout = QVBoxLayout(dialog)

        # 标题
        title_label = QLabel("欢迎使用模拟权杖系统")
        title_font = QFont()
        title_font.setPointSize(14)
        title_font.setBold(True)
        title_label.setFont(title_font)
        title_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(title_label)

        # 协议内容文本框（带滚动条）
        text_browser = QTextBrowser()
        text_browser.setOpenExternalLinks(True)  # 允许点击链接

        # 读取README.md中的免责声明内容
        disclaimer_content = self.load_disclaimer_content()
        text_browser.setMarkdown(disclaimer_content)

        layout.addWidget(text_browser)

        # 按钮区域
        button_layout = QHBoxLayout()

        decline_btn = QPushButton("拒绝")
        accept_btn = QPushButton("同意并继续")

        # 设置按钮样式
        accept_btn.setStyleSheet("""
            QPushButton {
                background-color: #4CAF50;
                color: white;
                padding: 8px 16px;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #45a049;
            }
        """)

        decline_btn.setStyleSheet("""
            QPushButton {
                background-color: #f44336;
                color: white;
                padding: 8px 16px;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #da190b;
            }
        """)

        button_layout.addWidget(decline_btn)
        button_layout.addWidget(accept_btn)
        layout.addLayout(button_layout)

        # 按钮事件处理
        def on_accept():
            # 创建cache目录（如果不存在）
            cache_dir = os.path.dirname(agreement_file)
            if not os.path.exists(cache_dir):
                os.makedirs(cache_dir)

            # 创建标记文件
            with open(agreement_file, 'w', encoding='utf-8') as f:
                from datetime import datetime
                f.write(f"Agreement accepted at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write("User has read and agreed to the terms and conditions.\n")

            dialog.accept()

        def on_decline():
            sys.exit(0)

        accept_btn.clicked.connect(on_accept)
        decline_btn.clicked.connect(on_decline)

        # 显示弹窗
        dialog.exec_()

    def load_disclaimer_content(self):
        """
        从README.md中加载免责声明内容
        :return: 免责声明的文本
        """
        try:
            readme_path = os.path.join(PATHS["root"], "README.md")
            if os.path.exists(readme_path):
                with open(readme_path, encoding='utf-8') as f:
                    content = f.read()

                # 提取免责声明部分
                start_marker = "# 免责声明 | Disclaimer"
                end_marker = "----------------------------------------------------------------------------------------------"

                start_idx = content.find(start_marker)
                if start_idx != -1:
                    # 从免责声明标题开始查找
                    remaining = content[start_idx:]
                    # 找到下一个分隔线（免责声明结束标记）
                    end_idx = remaining.find(end_marker, len(start_marker))
                    if end_idx != -1:
                        # 提取从标题到分隔线之间的内容
                        disclaimer = remaining[:end_idx].strip()
                        return disclaimer

                # 如果提取失败，返回默认文本
                return self.get_default_disclaimer()
            else:
                return self.get_default_disclaimer()
        except Exception as e:
            print(f"加载免责声明失败: {e}")
            return self.get_default_disclaimer()

    def get_default_disclaimer(self):
        """
        获取默认免责声明文本
        :return: 默认免责声明的markdown文本
        """
        return """
# 免责声明

### 一、软件性质与开源声明
本软件是一个外部开源辅助工具，旨在通过模拟用户操作、与游戏现有用户界面（UI）进行交互，以实现游戏玩法的自动化。本软件被设计成仅通过现有用户界面与游戏交互，不会以任何方式修改任何游戏文件或游戏代码。本软件开源、免费，仅供个人学习、交流与研究自动化技术之用。

### 二、知识产权与权属声明
《崩坏：星穹铁道》游戏及其相关内容的著作权、商标权等一切知识产权，均归米哈游公司（miHoYo）及其关联实体合法所有。本软件仅作为技术学习工具，不主张、不享有任何游戏内容的版权。

### 三、用户使用许可范围
用户通过本软件获取的全部功能，均被严格限定为"个人临时学习研究"之唯一目的，不构成对用户任何明示或默示的商业使用授权。

### 四、用户义务与合规风险提示
用户使用本软件时需遵守国家相关法律法规及米哈游官方发布的用户协议。使用本软件可能会被认定为违反游戏公平性的行为，并可能导致游戏账号遭受处罚。

### 五、风险自担与责任豁免
用户因获取、使用本软件而遭受的任何直接或间接损失、法律纠纷、设备损害、数据丢失、游戏账号被处罚或其他风险，均由用户自行承担全部责任。

**使用本软件即表示您已阅读并同意以上条款。**
"""

def main(show, startup_args=None):
    root_path = os.path.normcase(os.path.realpath(PATHS["root"]))
    mutex_name = f"Local\\Simulated_Scepter_{hashlib.sha256(root_path.encode('utf-8')).hexdigest()}"
    mutex_handle = ctypes.windll.kernel32.OpenMutexW(0x00100000, False, mutex_name)
    if mutex_handle:
        ctypes.windll.kernel32.CloseHandle(mutex_handle)
        show_instance_warning()
        return

    def is_admin():
        try:
            return ctypes.windll.shell32.IsUserAnAdmin()
        except Exception:
            return False


    # 以管理员权限重新运行程序，使用pythonw避免命令行窗口
    def run_as_admin():
        try:
            result = ctypes.windll.shell32.ShellExecuteW(
                None,
                "runas",
                sys.executable,
                subprocess.list2cmdline(
                    [os.path.abspath(__file__), *sys.argv[1:]]
                ),
                None,
                show
            )
            if result <= 32:
                CUS_LOGGER.error("请求管理员权限启动程序失败，ShellExecuteW 返回值：%s", result)
            return result > 32
        except Exception as error:
            CUS_LOGGER.error("请求管理员权限启动程序失败：%s", error, exc_info=True)
            return False


    if not is_admin():

        if run_as_admin():
            sys.exit(0)
        else:
            import tkinter
            from tkinter import messagebox

            root = tkinter.Tk()
            root.withdraw()
            messagebox.showerror("权限错误", "此程序需要管理员权限才能正常运行。请右键点击程序并选择'以管理员身份运行'。")
            root.destroy()
    else:
        instance_lock = acquire_instance_lock(mutex_name)
        if instance_lock is None:
            show_instance_warning()
            return
        app = QApplication.instance() or QApplication(sys.argv)
        window = MainWindow(
            start_task=startup_args.start_task if startup_args else None,
            start_delay=startup_args.start_delay if startup_args else STARTUP_TASK_DELAY_SECONDS,
        )
        window.show()
        try:
            sys.exit(app.exec())
        except SystemExit as e:
            print(f"异常退出，进程已结束,退出代码:{e.code}")
            input("按Enter键退出...")
if __name__ == "__main__":
    startup_args = parse_startup_args()
    fault_log_file = open("logs/crash_dump.txt", "w", encoding="utf-8")
    faulthandler.enable(file=fault_log_file)
    main(1, startup_args)
