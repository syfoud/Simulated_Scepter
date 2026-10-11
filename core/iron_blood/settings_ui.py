"""铁血战士早停与半自动参数的独立配置界面。"""

from PyQt5.QtCore import QEvent, Qt
from PyQt5.QtGui import QKeySequence
from PyQt5.QtWidgets import QMessageBox

from core.common import config as runtime_config
from core.common.config import load_runtime_settings
from core.common.runtime_ui import RuntimeSettings
from tool.gui.settings_dialog import SettingsDialog as BaseDialog
from tool.log import CUS_LOGGER
from tool.storage import (
    load_module_settings,
    resource_path,
    save_json_configs,
    update_module_settings,
)


class SettingsDialog(BaseDialog):
    def __init__(self, parent=None):
        super().__init__("铁血战士配置", parent)
        data = load_runtime_settings() | load_module_settings(__file__)
        self.runtime = RuntimeSettings(data, self)
        self.content_layout.addWidget(self.runtime)
        self.section = ui = self.add_section(resource_path(__file__, "ui/settings.ui"))
        for key, default, field in (
            ("first_plane", 14, "first_plane"), ("second_plane", 31, "second_plane"),
            ("battle_weight", 1.2, "battle_weight"), ("first_plane_min_weight", 8.0, "first_plane_min_weight"),
            ("third_plane_pause_count", 0, "third_plane_pause"), ("boss_before_pause_count", 0, "boss_before_pause"),
        ):
            getattr(ui, f"Iron_blood_{field}_input").setText(str(data.get(key, default)))
        self._battle_weight_warning_shown = data.get("battle_weight_warning_shown", False)
        ui.Iron_blood_battle_weight_input.installEventFilter(self)
        self.runtime.early_stop_checkbox.toggled.connect(self.update_controls)
        self.update_controls()

    def update_controls(self):
        for field in ("first_plane", "second_plane", "battle_weight", "first_plane_min_weight",
                      "third_plane_pause", "boss_before_pause"):
            getattr(self.section, f"Iron_blood_{field}_input").setEnabled(self.runtime.early_stop_enabled())

    def persist(self):
        ui = self.section
        values = {}
        for key, field, convert in (
            ("first_plane", "first_plane", int), ("second_plane", "second_plane", int),
            ("battle_weight", "battle_weight", float), ("first_plane_min_weight", "first_plane_min_weight", float),
            ("third_plane_pause_count", "third_plane_pause", int), ("boss_before_pause_count", "boss_before_pause", int),
        ):
            values[key] = convert(getattr(ui, f"Iron_blood_{field}_input").text())
        shared = self.runtime.collect() | {"battle_weight": values.pop("battle_weight")}
        save_json_configs([(runtime_config.__file__, shared), (__file__, values)])

    def eventFilter(self, obj, event):
        """
        在战斗格权重首次被编辑前拦截本次操作
        """
        if (obj is self.section.Iron_blood_battle_weight_input
            and not getattr(self, "_battle_weight_warning_shown", True)
            and self.is_battle_weight_edit_event(event)):
            self.show_battle_weight_warning()
            return True
        return super().eventFilter(obj, event)

    @staticmethod
    def is_battle_weight_edit_event(event):
        """
        识别会修改 QLineEdit 内容的常见用户操作
        """
        if event.type() in (QEvent.InputMethod, QEvent.Drop, QEvent.ContextMenu):
            return True
        if event.type() != QEvent.KeyPress:
            return False

        if event.key() in (Qt.Key_Backspace, Qt.Key_Delete):
            return True
        if event.matches(QKeySequence.Cut) or event.matches(QKeySequence.Paste):
            return True
        if event.matches(QKeySequence.Undo) or event.matches(QKeySequence.Redo):
            return True

        modifier_keys = Qt.ControlModifier | Qt.AltModifier | Qt.MetaModifier
        return bool(event.text()) and not (event.modifiers() & modifier_keys)

    def show_battle_weight_warning(self):
        """
        显示首次编辑确认提示
        """
        if self._battle_weight_warning_shown:
            return
        self._battle_weight_warning_shown = True
        try:
            update_module_settings(__file__, {"battle_weight_warning_shown": True})
        except (OSError, ValueError) as error:
            CUS_LOGGER.warning(f"首次编辑权重提示的状态未能保存，下次打开可能再次提示：{error}")
        msg = QMessageBox(self)
        msg.setIcon(QMessageBox.Warning)
        msg.setWindowTitle("警告（本窗口仅会弹出一次）")
        msg.setText("修改权重前请先阅读以下内容：\n\n"
                    "1、权重原理：\n"
                    "        在铁血战士程序中，“权重”表示某一类型的格子内遇到的战斗数量期望。不同类型的格子拥有不同的权重，例如战斗格默认为1.2（85%概率刷出单怪、10%概率刷出双怪、5%概率刷出三怪），精英格为1（必定单怪），交易格为0（必定无怪）等等，详见“常见问题与更新日志”。权杖会根据权重选择最优路径、骰子最佳替换节点。\n\n"
                    "2、修改战斗格权重的影响：\n"
                    "        本质是为了多战收益而增大断战风险。作者认为，提高战斗格的权重不能提高战斗数的分布，因为大数定律确保了这个数一定收敛于期望附近，改激进并不会对一局产生有益的帮助，只能有助于更早的重开。\n\n"
                    "3、其他因素：\n"
                    "        在没有骰子替换战斗的前提下，这个模型基本没有问题。但是，某个位置的期望还应该叠加上这条路径上自然产生的替换战斗的差分的期望。本模型尚未考虑该因素。\n\n"
                    "        若尝试修改此项，需同时修改下方的“第一面最低期望权重”以匹配。计算方法：新权重 = 原权重 + 一面平均战斗格数量 × 战斗格权重变化量。可以尝试多种组合，比较轮回结果的进二面+三面概率，选择适合自己的最佳组合。")
        ok_button = msg.button(QMessageBox.Ok)
        if ok_button is not None:
            ok_button.setText("我已知悉")
        msg.setWindowFlags(Qt.Dialog | Qt.CustomizeWindowHint | Qt.WindowTitleHint)
        msg.setEscapeButton(None)
        msg.exec_()

