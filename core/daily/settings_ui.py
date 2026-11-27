"""日常内核的配置窗口：运行模式、副本、次数、支援、秘技顺序与收尾开关。"""

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QRadioButton,
    QScrollArea,
    QSizePolicy,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from core.daily.relic_targets import (
    INNER_TARGETS,
    OUTER_TARGETS,
    RUNS_CHOICES,
    SUPPORT_ROLE_CHOICES,
    SUPPORT_SLOT_CHOICES,
)
from tool.gui.settings_dialog import SettingsDialog as BaseDialog
from tool.storage import load_module_settings, save_json_values

class RunsSection(QGroupBox):
    """挑战次数区：1~6 单选 + 按开拓力自动推算开关。"""

    def __init__(self, auto, runs, parent=None):
        super().__init__("挑战次数", parent)
        self.group = QButtonGroup(self)

        row = QHBoxLayout()
        for choice in RUNS_CHOICES:
            button = QRadioButton(str(choice))
            button.setProperty("runs", choice)
            self.group.addButton(button)
            row.addWidget(button)
        row.addStretch(1)

        self.auto_check = QCheckBox("自动判断（按开拓力推算）")
        self.auto_check.setChecked(bool(auto))

        layout = QVBoxLayout(self)
        layout.addLayout(row)
        layout.addWidget(self.auto_check)

        selected = next(
            (button for button in self.group.buttons()
             if button.property("runs") == runs),
            None,
        )
        (selected or self.group.buttons()[0]).setChecked(True)

        self.auto_check.toggled.connect(self._apply_auto_state)
        self._apply_auto_state(self.auto_check.isChecked())

    def _apply_auto_state(self, auto):
        for button in self.group.buttons():
            button.setEnabled(not auto)

    def collect(self):
        """收集挑战次数区的选择。

        Returns:
            (是否按开拓力自动推算, 手动选择时使用的次数)。
        """
        return self.auto_check.isChecked(), self.group.checkedButton().property("runs")


class SupportSection(QGroupBox):
    """支援区：开关 + 替换位置。"""

    def __init__(self, enabled, slot, parent=None):
        super().__init__("支援", parent)
        self.check = QCheckBox("开启支援")
        self.check.setChecked(bool(enabled))

        self.group = QButtonGroup(self)
        row = QHBoxLayout()
        row.addWidget(QLabel("替换位置："))
        for choice in SUPPORT_SLOT_CHOICES:
            button = QRadioButton(f"{choice}号位")
            button.setProperty("slot", choice)
            self.group.addButton(button)
            row.addWidget(button)
        row.addStretch(1)

        selected = next(
            (button for button in self.group.buttons()
             if button.property("slot") == slot),
            None,
        )
        (selected or self.group.buttons()[0]).setChecked(True)

        layout = QVBoxLayout(self)
        layout.addWidget(self.check)
        layout.addLayout(row)

        self.check.toggled.connect(self._apply_enabled)
        self._apply_enabled(self.check.isChecked())

    def _apply_enabled(self, enabled):
        for button in self.group.buttons():
            button.setEnabled(enabled)

    def collect(self):
        """收集支援区的选择。

        Returns:
            (是否开启支援, 支援角色要替换的槽位)。
        """
        return self.check.isChecked(), self.group.checkedButton().property("slot")


class SupportPickSection(QGroupBox):
    """支援角色区：用列表里第几个支援角色，以及是否只挑好友；内外圈各有一份。"""

    def __init__(self, index, friend_only, parent=None):
        super().__init__("支援角色", parent)
        self.group = QButtonGroup(self)

        row = QHBoxLayout()
        row.addWidget(QLabel("列表第几个："))
        for choice in SUPPORT_ROLE_CHOICES:
            button = QRadioButton(str(choice))
            button.setProperty("index", choice)
            self.group.addButton(button)
            row.addWidget(button)
        row.addStretch(1)

        selected = next(
            (button for button in self.group.buttons()
             if button.property("index") == index),
            None,
        )
        (selected or self.group.buttons()[0]).setChecked(True)

        self.friend_check = QCheckBox("仅好友支援")
        self.friend_check.setChecked(bool(friend_only))

        layout = QVBoxLayout(self)
        layout.addLayout(row)
        layout.addWidget(self.friend_check)

    def collect(self):
        """收集支援角色区的选择。

        Returns:
            (支援角色列表里用第几个角色, 是否只挑好友支援)。
        """
        return self.group.checkedButton().property("index"), self.friend_check.isChecked()


class SkillOrderSection(QGroupBox):
    """秘技顺序区：输入 1~4 号位的释放顺序，并设置释放节奏。"""

    def __init__(self, order, delay, switch_delay, parent=None):
        super().__init__("秘技顺序", parent)

        hint = QLabel(
            "按队伍槽位输入 1~4 的顺序，例如 1342 表示依次用 1、3、4、2 号位施放秘技。"
            "数字不可重复，留空表示不释放秘技。「释放延迟」是放完秘技到切下一名角色的等待，"
            "「切换间隔」是切到新角色到按秘技的等待。"
        )
        hint.setWordWrap(True)

        self.input = QLineEdit()
        self.input.setText(str(order or ""))
        self.input.setPlaceholderText("例如：1342；留空表示不释放")

        self.delay_input = QDoubleSpinBox()
        self.delay_input.setRange(0.1, 3.0)
        self.delay_input.setSingleStep(0.1)
        self.delay_input.setValue(float(delay))

        self.switch_input = QDoubleSpinBox()
        self.switch_input.setRange(0.0, 2.0)
        self.switch_input.setSingleStep(0.1)
        self.switch_input.setValue(float(switch_delay))

        form = QHBoxLayout()
        form.addWidget(QLabel("释放延迟："))
        form.addWidget(self.delay_input)
        form.addWidget(QLabel("切换间隔："))
        form.addWidget(self.switch_input)
        form.addStretch(1)

        layout = QVBoxLayout(self)
        layout.addWidget(hint)
        layout.addWidget(self.input)
        layout.addLayout(form)

    def collect(self):
        """收集秘技顺序与释放节奏。

        Returns:
            (1~4 号位的释放顺序, 释放延迟秒, 切换间隔秒)；顺序留空表示不释放秘技。

        Raises:
            ValueError: 秘技顺序包含 1~4 以外的字符，或有重复数字。
        """
        raw = self.input.text().strip()
        if raw:
            if not all(char in "1234" for char in raw):
                raise ValueError("秘技顺序只能包含 1/2/3/4")
            if len(set(raw)) != len(raw):
                raise ValueError("秘技顺序不能有重复数字")
        return raw, self.delay_input.value(), self.switch_input.value()


class RelicSelectSection(QGroupBox):
    """副本选择区：下拉选择，下方显示所选副本的位置或掉落。"""

    def __init__(self, targets, selected, parent=None):
        super().__init__("副本选择", parent)
        self.details = {}

        self.combo = QComboBox()
        self.combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.combo.setMinimumContentsLength(14)
        self.combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.combo.setMaxVisibleItems(16)
        for name, detail in targets:
            self.combo.addItem(name, name)
            self.details[name] = detail
            self.combo.setItemData(self.combo.count() - 1, detail, Qt.ToolTipRole)

        self.detail_label = QLabel()
        self.detail_label.setWordWrap(True)

        self.combo.currentIndexChanged.connect(self._sync_detail)

        layout = QVBoxLayout(self)
        layout.addWidget(self.combo)
        layout.addWidget(self.detail_label)

        self._select_or_default(selected)

    def _select_or_default(self, name):
        index = self.combo.findData(name) if name else -1
        self.combo.setCurrentIndex(index if index >= 0 else 0)
        self._sync_detail()

    def _sync_detail(self, *_):
        name = self.combo.currentData()
        if name is None:
            return
        detail = self.details[name]
        self.detail_label.setText("位置/掉落：" + detail)
        self.combo.setToolTip(detail)

    def collect(self):
        """收集副本选择区的选择。

        Returns:
            下拉框当前选中的副本展示名。
        """
        return self.combo.currentData()


class SettingsDialog(BaseDialog):
    """日常内核的独立配置窗口。"""

    def __init__(self, parent=None):
        super().__init__("日常内核配置", parent)
        scroll = self.findChild(QScrollArea)
        if scroll is not None:
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.content_layout.setContentsMargins(0, 0, 0, 0)
        self.content_layout.setSpacing(0)

        data = load_module_settings(__file__)["daily_relic"]
        self.section = DailyRelicSection(data, self)
        self.content_layout.addWidget(self.section)

    def persist(self):
        save_json_values(__file__, {"daily_relic": self.section.collect()})


class DailyRelicSection(QWidget):
    """日常内核主配置区：运行模式 + 内圈/外圈页签 + 收尾开关。"""

    def __init__(self, data, parent=None):
        super().__init__(parent)

        header = QLabel("日常任务")
        font = QFont()
        font.setBold(True)
        font.setPointSize(font.pointSize() + 2)
        header.setFont(font)

        hint = QLabel("选择刷取副本与战斗参数；内圈、外圈设置分别在下方页签维护。")
        hint.setWordWrap(True)

        self.mode_group = QButtonGroup(self)
        mode_row = QHBoxLayout()
        mode_row.addWidget(QLabel("当前运行模式："))
        for label, value in (("内圈", "inner"), ("外圈", "outer")):
            button = QRadioButton(label)
            button.setProperty("module", value)
            self.mode_group.addButton(button)
            mode_row.addWidget(button)
        mode_row.addStretch(1)

        self.inner_list = RelicSelectSection(INNER_TARGETS, data.get("inner"))
        self.inner_support = SupportSection(
            data.get("inner_support", False), data.get("inner_support_slot", 1))
        self.inner_pick = SupportPickSection(
            data.get("inner_support_index", 1), data.get("inner_support_friend", False))
        self.inner_runs = RunsSection(
            data.get("inner_auto", False), data.get("inner_runs", RUNS_CHOICES[0]))
        self.inner_skill = SkillOrderSection(
            data.get("inner_skill_order", ""),
            data.get("inner_skill_delay", 1.5),
            data.get("inner_skill_switch_delay", 0.3))

        self.outer_list = RelicSelectSection(OUTER_TARGETS, data.get("outer"))
        self.outer_support = SupportSection(
            data.get("outer_support", False), data.get("outer_support_slot", 1))
        self.outer_pick = SupportPickSection(
            data.get("outer_support_index", 1), data.get("outer_support_friend", False))
        self.outer_runs = RunsSection(
            data.get("outer_auto", False), data.get("outer_runs", RUNS_CHOICES[0]))

        self.reward_check = QCheckBox("刷完后领取委托与每日实训奖励（进度卡在 400 时合成奇巧零食）")
        self.reward_check.setChecked(bool(data.get("daily_reward", True)))

        self.tabs = QTabWidget(self)
        self.tabs.addTab(self._build_panel([
            self.inner_list, self.inner_support, self.inner_pick, self.inner_runs, self.inner_skill,
        ]), "内圈设置")
        self.tabs.addTab(self._build_panel([
            self.outer_list, self.outer_support, self.outer_pick, self.outer_runs,
        ]), "外圈设置")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)
        layout.addWidget(header)
        layout.addWidget(hint)
        layout.addLayout(mode_row)
        layout.addWidget(self.tabs, 1)
        layout.addWidget(self.reward_check)

        self._select_mode(data.get("module", "inner"))

    @staticmethod
    def _build_panel(widgets):
        """按单列排版，避免并排布局撑出横向滚动条。"""
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)
        for widget in widgets:
            layout.addWidget(widget)
        layout.addStretch(1)
        return panel

    def _select_mode(self, module):
        for button in self.mode_group.buttons():
            if button.property("module") == module:
                button.setChecked(True)
                return
        self.mode_group.buttons()[0].setChecked(True)

    def collect(self):
        """收集整个配置页的选择。

        Returns:
            可直接写入模块配置的扁平字典，键名与 config/default.json 一致。

        Raises:
            ValueError: 秘技顺序输入不合法。
        """
        inner_support, inner_slot = self.inner_support.collect()
        inner_index, inner_friend = self.inner_pick.collect()
        outer_support, outer_slot = self.outer_support.collect()
        outer_index, outer_friend = self.outer_pick.collect()
        inner_auto, inner_runs = self.inner_runs.collect()
        outer_auto, outer_runs = self.outer_runs.collect()
        skill_order, skill_delay, skill_switch_delay = self.inner_skill.collect()
        return {
            "module": self.mode_group.checkedButton().property("module"),
            "inner": self.inner_list.collect(),
            "outer": self.outer_list.collect(),
            "inner_auto": inner_auto,
            "inner_runs": inner_runs,
            "outer_auto": outer_auto,
            "outer_runs": outer_runs,
            "inner_skill_order": skill_order,
            "inner_skill_delay": skill_delay,
            "inner_skill_switch_delay": skill_switch_delay,
            "inner_support": inner_support,
            "outer_support": outer_support,
            "inner_support_slot": inner_slot,
            "inner_support_index": inner_index,
            "inner_support_friend": inner_friend,
            "outer_support_slot": outer_slot,
            "outer_support_index": outer_index,
            "outer_support_friend": outer_friend,
            "daily_reward": self.reward_check.isChecked(),
        }
