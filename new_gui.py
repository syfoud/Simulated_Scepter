import ctypes
import json
import os
import shutil
import sys
import time

import keyboard
from PyQt5.QtGui import QFont

from route import PATHS
from tool import EXTRA
from tool.countdown_config import (
    DECISION_MODES, MC_SETTING_FIELDS, load_finger_snap_settings,
    save_finger_snap_settings,
)
from tool.log import log_emitter
from tool.thread import ThreadWithException
from tool.utils.image_tool import find_image_by_name, load_all_images_from_directory

load_all_images_from_directory()
import faulthandler

from PyQt5.QtCore import Qt, pyqtSignal, pyqtSlot
from PyQt5.QtWidgets import (
    QApplication,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
)

from align_angle import main as align_angle_main
from currencywar import CurrencyWar
from diver import DivergentUniverse
from finger_snap import FingerSnap
from iron_blood import IronBloodUniverse
from logger_printer import QMainWindowLog
from simul import SimulatedUniverse
from tool.diver.config import config as config_diver
from tool.simul.config import config as config_simul

HOTKEY_DEBOUNCE_SECONDS = 1.0


class MainWindow(QMainWindowLog):
    calibration_finished = pyqtSignal(object)
    hotkey_pressed = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        # 任务管理相关属性
        self.current_task = None
        self.task_thread = None
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

        # 检查是否首次启动并显示用户协议
        self.check_first_launch()

    def start_task(self, task_func):
        """
        启动一个新任务
        """
        if self.is_task_running():
            raise RuntimeError("已有任务正在运行")
        self.task_thread = ThreadWithException(target=task_func,name="主任务线程")
        self.task_thread.start()
        # 更新任务状态标签为"运行中"
        self.Label_RunningState.setText("任务序列线程状态: 运行中")

    def is_task_running(self):
        """
        检查是否有任务正在运行
        """
        return self.task_thread is not None and self.task_thread.is_alive()

    def stop_task(self):
        """
        停止当前任务
        """
        # 设置全局停止标志（用于__init__中的阻塞等待）
        from tool.GLOBAL import set_global_stop_flag
        set_global_stop_flag(True)

        if self.current_task and hasattr(self.current_task, 'stop'):
            self.current_task.stop()
            self.task_thread = None
            self.current_task = None
            # 更新任务状态标签为"未运行"
            self.Label_RunningState.setText("任务序列线程状态: 未运行")
            set_global_stop_flag(False)
            return True

        set_global_stop_flag(False)
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
        # 检查模型文件是否存在
        self.check_model_file()

        # 连接按钮信号
        self.run_simul_btn.clicked.connect(self.run_simul)
        self.run_diver_btn.clicked.connect(self.run_diver)
        self.iron_blood_btn.clicked.connect(self.run_iron_blood)
        self.finger_snap_btn.clicked.connect(self.run_finger_snap)
        self.currency_war_btn.clicked.connect(self.run_currency_war)
        self.calibrate_btn.clicked.connect(self.calibrate)
        self.test_btn.clicked.connect(self.test)
        self.print_btn.clicked.connect(self.test_2)
        self.stop_btn.clicked.connect(self.stop_task)
        self.clear_logs_btn.clicked.connect(self.clear_logs)

        # 初始化模拟宇宙配置界面
        self.Simul_bonus_checkbox.setChecked(bool(config_simul.bonus))
        self.Simul_debug_checkbox.setChecked(bool(config_simul.debug_mode))
        self.Simul_speed_checkbox.setChecked(bool(config_simul.speed_mode))
        self.Simul_slow_checkbox.setChecked(bool(config_simul.slow_mode))
        self.Simul_difficulty_combo.addItems(["1", "2", "3", "4", "5"])
        self.Simul_difficulty_combo.setCurrentText(str(config_simul.difficult))
        self.Simul_fate_combo.addItems([
            "存护", "记忆", "虚无", "丰饶", "巡猎", "毁灭", "欢愉", "繁育", "智识"
        ])
        self.Simul_fate_combo.setCurrentText(config_simul.fate)
        self.Simul_timezone_combo.addItems(["Default", "Asia", "America", "Europe"])
        self.Simul_timezone_combo.setCurrentText(config_simul.timezone)
        self.Simul_max_run_input = QLineEdit(str(config_simul.max_run))

        # 初始化差分宇宙配置界面
        self.Diver_debug_checkbox.setChecked(bool(config_diver.debug_mode))
        self.Diver_speed_checkbox.setChecked(bool(config_diver.speed_mode))
        self.Diver_weekly_checkbox.setChecked(bool(config_diver.weekly_mode))
        self.Diver_cpu_checkbox.setChecked(bool(config_diver.cpu_mode))
        self.Diver_difficulty_combo.addItems(["1", "2", "3", "4", "5"])
        self.Diver_difficulty_combo.setCurrentText(str(config_diver.difficult))
        self.Diver_team_combo.addItems(["追击", "dot", "终结技", "击破", "盾反"])
        self.Diver_save_cnt_combo.addItems(["0", "1", "2", "3", "4"])
        self.Diver_save_cnt_combo.setCurrentText(str(config_diver.save_cnt))
        self.Diver_timezone_combo.addItems(["Default", "Asia", "America", "Europe"])
        self.Diver_timezone_combo.setCurrentText(config_diver.timezone)
        self.Diver_max_run_input = QLineEdit(str(config_diver.max_run))

        # 连接配置保存按钮
        self.config_save_btn.clicked.connect(self.save_config)
        self.Iron_blood_save_btn.clicked.connect(self.save_iron_config)
        self.Finger_snap_save_btn.clicked.connect(self.save_finger_snap_config)
        self.Aboutupdatelock.clicked.connect(self.show_unlock_dialog)

        settings_path = PATHS["root"] + "\\config\\config\\settings.json"
        example_path = PATHS["root"] + "\\config\\config\\settings_example.json"
        if not os.path.exists(settings_path) and os.path.exists(example_path):
            shutil.copy2(example_path, settings_path)
        with EXTRA.FILE_LOCK:
            with open(settings_path, encoding="UTF-8") as file:
                data = json.load(file)
        self.recording_checkBox.setChecked(data.get("recording_state", True))
        self.recording_checkBox2.setChecked(data.get("recording_iron_blood", True))
        self.recording_label_checkbox.setChecked(data.get("record_add_label", True))
        self.early_stop_checkbox.setChecked(data.get("early_stop", False))
        self.recording_time_input.setText(str(data.get("del_record_time", 31)))
        self.record_event_map_checkbox.setChecked(data.get("record_event_map", False))
        self.Iron_blood_max_run_input.setText(str(int(data.get("max_run_time", 0))))
        self.Iron_blood_first_plane_input.setText(str(data.get("first_plane", 14)))
        self.Iron_blood_second_plane_input.setText(str(data.get("second_plane", 31)))
        self.Iron_blood_battle_weight_input.setText(str(data.get("battle_weight", 1.2)))
        self.Iron_blood_first_plane_min_weight_input.setText(str(data.get("first_plane_min_weight", 6)))
        self.Iron_blood_interact_time_input.setText(str(data.get("max_interact_time", 40)))
        self.debug_checkox2.setChecked(data.get("debug", True))

        finger_snap = load_finger_snap_settings()
        for field in MC_SETTING_FIELDS:
            getattr(self, f"Finger_snap_{field}_input").setText(str(finger_snap[field]))
        for plane, target in enumerate(finger_snap["plane_targets"], 1):
            getattr(self, f"Finger_snap_plane{plane}_target_input").setText(str(target))
        for mode, label in DECISION_MODES.items():
            self.Finger_snap_decision_mode_combo.addItem(label, mode)
        self.Finger_snap_decision_mode_combo.setCurrentIndex(
            self.Finger_snap_decision_mode_combo.findData(finger_snap["decision_mode"]))
        self.Finger_snap_dp_early_stop_checkbox.setChecked(finger_snap["dp_early_stop"])
        self.Finger_snap_win_rate_dp_early_stop_checkbox.setChecked(
            finger_snap["win_rate_dp_early_stop"])
        self.Finger_snap_mc_dp_early_stop_checkbox.setChecked(
            finger_snap["mc_dp_early_stop"])
        self.Finger_snap_first_plane_threshold_input.setText(
            str(finger_snap.get("first_plane_threshold", 0.0)))
        self.Finger_snap_record_keep_count_input.setText(
            str(finger_snap.get("record_keep_count", 31)))

        # 初始化快捷键配置输入框
        hotkey_config = data.get("hotkeys", {})
        self.stop_hotkey_input.setText(hotkey_config.get("stop", "f5"))
        self.test_hotkey_input.setText(hotkey_config.get("test", "f6"))
        self.print_hotkey_input.setText(hotkey_config.get("print", "f7"))

        # 更新按钮文本显示当前快捷键
        self.update_button_hotkey_text(hotkey_config)

        # 设置控件的启用/禁用状态
        self.update_dependent_controls_state()

        # 连接信号以实现动态更新
        self.connect_dependency_signals()

        self.restore_action.triggered.connect(self.run_iron_blood)



    def load_hotkey_config(self):
        """从 settings.json 加载快捷键配置"""
        default_config = {
            "stop": "f5",
            "test": "f6",
            "print": "f7"
        }

        try:
            settings_path = PATHS["root"] + "\\config\\config\\settings.json"
            example_path = PATHS["root"] + "\\config\\config\\settings_example.json"
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

    def save_ui_settings(self):
        """保存 ui 的状态到 settings.json"""

        settings_path = PATHS["root"] + "\\config\\config\\settings.json"
        example_path = PATHS["root"] + "\\config\\config\\settings_example.json"
        if not os.path.exists(settings_path) and os.path.exists(example_path):
            shutil.copy2(example_path, settings_path)
        with EXTRA.FILE_LOCK:
            with open(settings_path, encoding="UTF-8") as file:
                data = json.load(file)

        data["recording_state"] = self.recording_checkBox.isChecked()
        data["recording_iron_blood"] = self.recording_checkBox2.isChecked()
        data["record_add_label"] = self.recording_label_checkbox.isChecked()
        data["early_stop"] = self.early_stop_checkbox.isChecked()
        data["del_record_time"] = int(self.recording_time_input.text())
        data["record_event_map"] = self.record_event_map_checkbox.isChecked()
        data["max_run_time"] = int(self.Iron_blood_max_run_input.text())
        data["first_plane"] = int(self.Iron_blood_first_plane_input.text())
        data["second_plane"] = int(self.Iron_blood_second_plane_input.text())
        data["battle_weight"] = float(self.Iron_blood_battle_weight_input.text())
        data["first_plane_min_weight"] = int(self.Iron_blood_first_plane_min_weight_input.text())
        data["max_interact_time"] = int(self.Iron_blood_interact_time_input.text())
        data["debug"] = self.debug_checkox2.isChecked()

        # 保存快捷键配置
        data["hotkeys"] = {
            "stop": self.stop_hotkey_input.text().strip(),
            "test": self.test_hotkey_input.text().strip(),
            "print": self.print_hotkey_input.text().strip()
        }

        with EXTRA.FILE_LOCK:
            with open(PATHS["root"] + "\\config\\config\\settings.json", mode="w", encoding="UTF-8") as file:
                json.dump(data, file, ensure_ascii=False, indent=4)
        self.opt = data
        self.hotkey_config = data["hotkeys"]
        self.refresh_keyboard_listener()
        self.update_button_hotkey_text(self.hotkey_config)

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
        debug_enabled = self.debug_checkox2.isChecked()
        debug_and_recording = debug_enabled and self.recording_checkBox2.isChecked()
        self.recording_label_checkbox.setEnabled(debug_and_recording)
        self.recording_time_input.setEnabled(self.recording_checkBox2.isChecked())
        # 事件地图录图属于调试功能，仅在调试模式下展示。
        self.record_event_map_checkbox.setVisible(debug_enabled)
        self.record_event_map_checkbox.setEnabled(debug_enabled)
        finger_snap_visible = debug_enabled or (0 <= time.localtime().tm_hour < 6)
        self.finger_snap_btn.setVisible(finger_snap_visible)
        self.Finger_snap_group.setVisible(finger_snap_visible)
        early_stop_enabled = self.early_stop_checkbox.isChecked()
        self.Iron_blood_first_plane_input.setEnabled(early_stop_enabled)
        self.Iron_blood_second_plane_input.setEnabled(early_stop_enabled)
        self.Iron_blood_first_plane_min_weight_input.setEnabled(early_stop_enabled)

    def connect_dependency_signals(self):
        self.debug_checkox2.stateChanged.connect(lambda: self.update_dependent_controls_state())
        self.recording_checkBox2.stateChanged.connect(lambda: self.update_dependent_controls_state())
        self.early_stop_checkbox.stateChanged.connect(lambda: self.update_dependent_controls_state())

    def closeEvent(self, event):
        """
        窗口关闭事件，清理键盘监听器
        """
        keyboard.unhook_all()
        super().closeEvent(event)

    def clear_logs(self):
        """
        清除logs目录下的所有文件，跳过被占用的文件
        """
        try:
            logs_dir = "logs"
            if not os.path.exists(logs_dir):
                QMessageBox.warning(self, "警告", "日志目录不存在")
                return

            failed_files = []
            success_count = 0

            # 删除logs目录下的所有文件和子目录
            for filename in os.listdir(logs_dir):
                file_path = os.path.join(logs_dir, filename)
                try:
                    if os.path.isfile(file_path) or os.path.islink(file_path):
                        os.unlink(file_path)
                    elif os.path.isdir(file_path):
                        shutil.rmtree(file_path)
                    success_count += 1
                except Exception:
                    failed_files.append(filename)

            if failed_files:
                QMessageBox.warning(
                    self,
                    "完成（部分失败）",
                    f"成功删除 {success_count} 个文件/目录\n以下文件/目录删除失败:\n" + "\n".join(failed_files)
                )
            else:
                QMessageBox.information(self, "成功", f"成功删除 {success_count} 个文件/目录")

        except Exception as e:
            QMessageBox.critical(self, "错误", f"清除日志失败: {str(e)}")

    def test(self):
        def task():
            su = SimulatedUniverse(
                1,
                int(config_simul.debug_mode),
                int(config_simul.speed_mode),
                int(config_simul.use_consumable),
                int(config_simul.slow_mode),
                int(config_simul.max_run),
                bonus=config_simul.bonus
            )
            self.current_task = su
            # 等待游戏窗口(可被中断)
            su.save_screen()

        try:
            self.start_task(task)
        except RuntimeError as e:
            QMessageBox.warning(self, "警告", str(e))

    def test_2(self):

        def task():
            su = SimulatedUniverse(
                1,
                int(config_simul.debug_mode),
                int(config_simul.speed_mode),
                int(config_simul.use_consumable),
                int(config_simul.slow_mode),
                int(config_simul.max_run),
                bonus=config_simul.bonus
            )
            self.current_task = su
            print_text = self.PrintEdit.text()
            if self.PrintPhoto.isChecked():
                su.click_target(find_image_by_name(print_text), 0.9, True, use_binary=False)
            elif self.PrintText.isChecked():
                su.click_text(print_text,click=0,find_all=True)
            else:
                su.click_text(print_text,click=1)

        try:
            self.start_task(task)
        except RuntimeError as e:
            QMessageBox.warning(self, "警告", str(e))
    def run_simul(self):
        def task():
            su = SimulatedUniverse(
                1,
                int(config_simul.debug_mode),
                int(config_simul.speed_mode),
                int(config_simul.use_consumable),
                int(config_simul.slow_mode),
                int(config_simul.max_run),
                bonus=config_simul.bonus
            )
            self.current_task = su
            su.start()


        try:
            self.start_task(task)
        except RuntimeError as r:
            QMessageBox.warning(self, "警告", str(r))
        except Exception as e:
            QMessageBox.critical(self, "错误", str(e))

    def run_diver(self):

        def task():
            su = DivergentUniverse(
                int(config_diver.debug_mode),
                int(config_diver.max_run),
                int(config_diver.speed_mode)
            )
            self.current_task = su
            su.start()

        try:
            self.start_task(task)
        except RuntimeError as r:
            QMessageBox.warning(self, "警告", str(r))
        except Exception as e:
            QMessageBox.critical(self, "错误", str(e))

    def run_iron_blood(self):
        def task():
            su = IronBloodUniverse()
            self.current_task = su
            su.start()

        try:
            self.start_task(task)
        except RuntimeError as r:
            QMessageBox.warning(self, "警告", str(r))
        except Exception as e:
            QMessageBox.critical(self, "错误", str(e))

    def run_finger_snap(self):
        can_run = (
            self.opt.get("debug", True)
            and self.opt.get("recording_iron_blood", True)
            and self.opt.get("record_add_label", True)
        )
        if not can_run:
            QMessageBox.information(
                self, "提示", "非开发人员，当前无测试资格，暂不支持运行")
            return

        def task():
            su = FingerSnap()
            self.current_task = su
            su.start()

        try:
            self.start_task(task)
        except RuntimeError as r:
            QMessageBox.warning(self, "警告", str(r))
        except Exception as e:
            QMessageBox.critical(self, "错误", str(e))

    def run_currency_war (self):
        def task ():
            su = CurrencyWar()
            self.current_task = su
            su.start()

        try:
            self.start_task(task)
        except RuntimeError as r:
            QMessageBox.warning(self, "警告", str(r))
        except Exception as e:
            QMessageBox.critical(self, "错误", str(e))

    def calibrate(self):
        def task():
            try:
                res = align_angle_main()
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


    def save_config(self):
        # 保存模拟宇宙配置
        config_simul.bonus = int(self.Simul_bonus_checkbox.isChecked())
        config_simul.debug_mode = int(self.Simul_debug_checkbox.isChecked())
        config_simul.speed_mode = int(self.Simul_speed_checkbox.isChecked())
        config_simul.slow_mode = int(self.Simul_slow_checkbox.isChecked())
        config_simul.difficult = self.Simul_difficulty_combo.currentText()
        config_simul.fate = self.Simul_fate_combo.currentText()
        config_simul.timezone = self.Simul_timezone_combo.currentText()
        try:
            config_simul.max_run = int(self.Simul_max_run_input.text())
        except ValueError:
            pass

        # 保存差分宇宙配置
        config_diver.debug_mode = int(self.Diver_debug_checkbox.isChecked())
        config_diver.speed_mode = int(self.Diver_speed_checkbox.isChecked())
        config_diver.weekly_mode = int(self.Diver_weekly_checkbox.isChecked())
        config_diver.cpu_mode = int(self.Diver_cpu_checkbox.isChecked())
        config_diver.difficult = self.Diver_difficulty_combo.currentText()
        config_diver.team = self.Diver_team_combo.currentText()
        config_diver.timezone = self.Diver_timezone_combo.currentText()
        config_diver.save_cnt = int(self.Diver_save_cnt_combo.currentText())
        try:
            config_diver.max_run = int(self.Diver_max_run_input.text())
        except ValueError:
            pass

        # 保存配置到文件
        config_simul.save()
        config_diver.save()

        self.save_ui_settings()

        QMessageBox.information(self, "提示", "配置已保存")
    def save_iron_config(self):
        self.save_ui_settings()
        QMessageBox.information(self, "提示", "配置已保存")
    def save_finger_snap_config(self):
        try:
            values = {
                "control_rollouts": int(self.Finger_snap_control_rollouts_input.text()),
                "evaluation_rollouts": int(self.Finger_snap_evaluation_rollouts_input.text()),
                "min_visits": int(self.Finger_snap_min_visits_input.text()),
                "epsilon_start": float(self.Finger_snap_epsilon_start_input.text()),
                "epsilon_end": float(self.Finger_snap_epsilon_end_input.text()),
                "seed": int(self.Finger_snap_seed_input.text()),
                "win_rate_noise_floor_percent": float(
                    self.Finger_snap_win_rate_noise_floor_percent_input.text()),
                "path_reward_bonus": float(self.Finger_snap_path_reward_bonus_input.text()),
                "path_event_bonus": float(self.Finger_snap_path_event_bonus_input.text()),
                "path_trade_bonus": float(self.Finger_snap_path_trade_bonus_input.text()),
                "path_adventure_bonus": float(self.Finger_snap_path_adventure_bonus_input.text()),
                "path_bugevent_bonus": float(self.Finger_snap_path_bugevent_bonus_input.text()),
                "decision_mode": self.Finger_snap_decision_mode_combo.currentData(),
                "dp_early_stop": self.Finger_snap_dp_early_stop_checkbox.isChecked(),
                "win_rate_dp_early_stop": (
                    self.Finger_snap_win_rate_dp_early_stop_checkbox.isChecked()),
                "mc_dp_early_stop": (
                    self.Finger_snap_mc_dp_early_stop_checkbox.isChecked()),
                "plane_targets": [int(getattr(
                    self, f"Finger_snap_plane{plane}_target_input").text())
                    for plane in range(1, 4)],
                "first_plane_threshold": float(
                    self.Finger_snap_first_plane_threshold_input.text()),
                "record_keep_count": int(
                    self.Finger_snap_record_keep_count_input.text()),
            }
            save_finger_snap_settings(values)
        except (TypeError, ValueError) as error:
            QMessageBox.warning(self, "参数错误", f"弹指一挥参数无法保存：{error}")
            return
        QMessageBox.information(
            self, "提示", "弹指一挥配置已独立保存；下次启动弹指任务时生效。")
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

    def show_unlock_dialog(self):
        """
        显示高级用户功能解锁说明弹窗
        """
        dialog = QDialog(self)
        dialog.setWindowTitle("高级用户功能解锁说明")
        dialog.setModal(True)
        dialog.resize(700, 550)

        # 设置窗口标志，确保弹窗置顶
        dialog.setWindowFlags(dialog.windowFlags() | Qt.WindowStaysOnTopHint)

        layout = QVBoxLayout(dialog)

        # 标题
        title_label = QLabel("🔓 高级用户功能解锁")
        title_font = QFont()
        title_font.setPointSize(16)
        title_font.setBold(True)
        title_label.setFont(title_font)
        title_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(title_label)

        # 分隔线
        line1 = QLabel("─" * 50)
        line1.setAlignment(Qt.AlignCenter)
        layout.addWidget(line1)

        # 说明内容文本框（带滚动条）
        text_browser = QTextBrowser()
        text_browser.setOpenExternalLinks(True)  # 允许点击链接

        unlock_content = """
# 如何解锁高级用户功能？

## 📌 解锁方式

为了获得高级用户功能的访问权限，您需要完成以下步骤：

### 方式一：GitHub 免费 Star 支持（推荐）

1. **访问本项目 GitHub 仓库**
   - 项目地址：[https://github.com/syfoud/Simulated_Scepter](https://github.com/syfoud/Simulated_Scepter)

2. **点击 Star 按钮**
   - 在页面右上角找到 ⭐ Star 按钮
   - 点击即可为项目点亮 Star

3. **截图保存**
   - 截取包含您的 GitHub 用户名和 Star 状态的完整页面
   - 确保截图中能清晰看到您已 Star 该项目

### 方式二：赞助开发者

如果您希望进一步支持项目开发，可以选择赞助：

- **赞助方式**：请联系开发者获取赞助渠道
- **赞助金额**：随意，一杯咖啡即可 ☕
- **赞助福利**：优先技术支持 + 高级功能解锁

---

## 📸 联系开发者

完成上述任一方式后，请按以下步骤操作：

### 步骤 1：准备截图
- GitHub Star 截图 **或** 赞助凭证截图
- 确保截图清晰可见

### 步骤 2：加入 QQ 群
- **QQ 一群**：1072802257（已满）
- **QQ 二群**：870863632

### 步骤 3：提交申请
- 私聊联系开发者
- 发送您的截图
- 说明申请解锁高级功能

### 步骤 4：使用密钥
- 下载群文件加密压缩包
- 使用开发者告知您的密钥解压
- 将解压的onnx文件放置于/resource/models/目录下方
- 重新启动本软件
---
"""

        text_browser.setMarkdown(unlock_content)
        layout.addWidget(text_browser)

        # 按钮区域
        button_layout = QHBoxLayout()

        github_btn = QPushButton("前往 GitHub")
        close_btn = QPushButton("关闭")

        # 设置按钮样式
        github_btn.setStyleSheet("""
            QPushButton {
                background-color: #24292e;
                color: white;
                padding: 10px 20px;
                border-radius: 5px;
                font-weight: bold;
                font-size: 12px;
            }
            QPushButton:hover {
                background-color: #1b1f23;
            }
        """)


        close_btn.setStyleSheet("""
            QPushButton {
                background-color: #6c757d;
                color: white;
                padding: 10px 20px;
                border-radius: 5px;
                font-size: 12px;
            }
            QPushButton:hover {
                background-color: #5a6268;
            }
        """)

        button_layout.addWidget(github_btn)
        button_layout.addWidget(close_btn)
        layout.addLayout(button_layout)

        # 按钮事件处理
        def open_github():
            import webbrowser
            webbrowser.open("https://github.com/syfoud/Simulated_Scepter")  # 请替换为实际的 GitHub 地址


        github_btn.clicked.connect(open_github)
        close_btn.clicked.connect(dialog.close)

        # 显示弹窗
        dialog.exec_()
def main(show):
    def is_admin():
        try:
            return ctypes.windll.shell32.IsUserAnAdmin()
        except Exception:
            return False


    # 以管理员权限重新运行程序，使用pythonw避免命令行窗口
    def run_as_admin():
        try:
            ctypes.windll.shell32.ShellExecuteW(
                None,
                "runas",
                sys.executable,
                __file__,
                None,
                show
            )
            return True
        except Exception:
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
        app = QApplication(sys.argv)
        window = MainWindow()
        window.show()
        try:
            sys.exit(app.exec())
        except SystemExit as e:
            print(f"异常退出，进程已结束,退出代码:{e.code}")
            input("按Enter键退出...")
if __name__ == "__main__":
    fault_log_file = open("logs/crash_dump.txt", "w", encoding="utf-8")
    faulthandler.enable(file=fault_log_file)
    main(1)
