"""日常遗器本设置窗口。"""

from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import (
    QButtonGroup,
    QCheckBox,
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

from core.daily_relic.targets import INNER_TARGETS, OUTER_TARGETS
from tool.gui.settings_dialog import SettingsDialog as BaseDialog
from tool.storage import load_module_settings, update_module_settings


RUNS_CHOICES = (1, 2, 3, 4, 5, 6)


class RunsSection(QGroupBox):
    """「挑战次数」设置区：1~6 单选，加一个「自动判断」复选框。"""

    def __init__(self, auto, runs, parent=None):
        super().__init__("挑战次数", parent)
        self.group = QButtonGroup(self)
        layout = QVBoxLayout(self)

        row = QHBoxLayout()
        for choice in RUNS_CHOICES:
            button = QRadioButton(str(choice))
            button.setProperty("runs", choice)
            self.group.addButton(button)
            row.addWidget(button)
        row.addStretch(1)
        layout.addLayout(row)

        self.auto_check = QCheckBox("自动判断")
        self.auto_check.setChecked(bool(auto))
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
        return self.auto_check.isChecked(), self.group.checkedButton().property("runs")


class SkillOrderSection(QGroupBox):
    """内圈「秘技顺序」设置区。"""

    def __init__(self, order, parent=None):
        super().__init__("秘技顺序", parent)
        layout = QVBoxLayout(self)

        hint = QLabel(
            "按队伍槽位输入 1~4 的顺序，例如 1342 表示先按 1 号位施放秘技，"
            "再按 3、4、2 号位。数字不可重复，留空表示不释放秘技。"
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self.input = QLineEdit()
        self.input.setText(str(order or ""))
        self.input.setPlaceholderText("例如：1342；留空表示不释放")
        layout.addWidget(self.input)

    def collect(self):
        return self.input.text().strip()


class DailyRelicSection(QWidget):
    """日常遗器本主配置区：副本选择 + 挑战次数 + 秘技顺序。"""

    def __init__(self, data, parent=None):
        super().__init__(parent)
        self.inner_group = QButtonGroup(self)
        self.outer_group = QButtonGroup(self)
        self._module_value = data.get("daily_relic_module", "inner")

        self.tabs = QTabWidget(self)
        self.tabs.addTab(self._build_relic_page(INNER_TARGETS, self.inner_group),
                         "饰品提取（内圈）")
        self.tabs.addTab(self._build_relic_page(OUTER_TARGETS, self.outer_group),
                         "侵蚀隧洞（外圈）")
        self.tabs.addTab(self._build_settings_page(data), "设置")

        layout = QVBoxLayout(self)
        layout.addWidget(self.tabs)

        self._select_or_default(self.inner_group, data.get("daily_relic_inner"))
        self._select_or_default(self.outer_group, data.get("daily_relic_outer"))
        self.tabs.setCurrentIndex(0 if self._module_value == "inner" else 1)

    def _build_relic_page(self, targets, group):
        page = QWidget()
        page_layout = QVBoxLayout(page)
        hint = QLabel("请选择一个副本，两个模块各自独立。")
        font = QFont()
        font.setBold(True)
        hint.setFont(font)
        page_layout.addWidget(hint)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        inner = QWidget()
        inner_layout = QVBoxLayout(inner)
        inner_layout.setContentsMargins(8, 8, 8, 8)
        inner_layout.setSpacing(6)
        for name, detail in targets:
            radio = QRadioButton(f"{name}    {detail}")
            radio.setProperty("relic_name", name)
            group.addButton(radio)
            inner_layout.addWidget(radio)
        inner_layout.addStretch(1)
        scroll.setWidget(inner)
        page_layout.addWidget(scroll)
        return page

    def _build_settings_page(self, data):
        """构建「设置」页：内圈与外圈各一个子 Tab，内圈多一项秘技顺序。"""
        page = QWidget()
        page_layout = QVBoxLayout(page)

        self.inner_runs = RunsSection(
            data.get("daily_relic_inner_auto", False),
            data.get("daily_relic_inner_runs", RUNS_CHOICES[0]),
            self,
        )
        self.inner_skill = SkillOrderSection(
            data.get("daily_relic_inner_skill_order", ""),
            self,
        )
        self.outer_runs = RunsSection(
            data.get("daily_relic_outer_auto", False),
            data.get("daily_relic_outer_runs", RUNS_CHOICES[0]),
            self,
        )

        inner_page = QWidget()
        inner_layout = QVBoxLayout(inner_page)
        inner_layout.addWidget(self.inner_runs)
        inner_layout.addWidget(self.inner_skill)
        inner_layout.addStretch(1)

        outer_page = QWidget()
        outer_layout = QVBoxLayout(outer_page)
        outer_layout.addWidget(self.outer_runs)
        outer_layout.addStretch(1)

        self.settings_tabs = QTabWidget(page)
        self.settings_tabs.addTab(inner_page, "内圈设置")
        self.settings_tabs.addTab(outer_page, "外圈设置")
        page_layout.addWidget(self.settings_tabs)
        return page

    @staticmethod
    def _select_or_default(group, name):
        if name:
            for button in group.buttons():
                if button.property("relic_name") == name:
                    button.setChecked(True)
                    return
        buttons = group.buttons()
        if buttons:
            buttons[0].setChecked(True)

    def collect(self):
        inner_auto, inner_runs = self.inner_runs.collect()
        outer_auto, outer_runs = self.outer_runs.collect()
        index = self.tabs.currentIndex()
        if index == 0:
            module = "inner"
        elif index == 1:
            module = "outer"
        else:
            module = self._module_value
        return {
            "daily_relic_module": module,
            "daily_relic_inner": self.inner_group.checkedButton().property("relic_name"),
            "daily_relic_outer": self.outer_group.checkedButton().property("relic_name"),
            "daily_relic_inner_auto": inner_auto,
            "daily_relic_inner_runs": inner_runs,
            "daily_relic_outer_auto": outer_auto,
            "daily_relic_outer_runs": outer_runs,
            "daily_relic_inner_skill_order": self.inner_skill.collect(),
        }


class SettingsDialog(BaseDialog):
    """日常遗器本内核的独立配置窗口。"""

    def __init__(self, parent=None):
        super().__init__("日常遗器本设置", parent)
        data = load_module_settings(__file__)
        self.section = DailyRelicSection(data, self)
        self.content_layout.addWidget(self.section)

    def persist(self):
        update_module_settings(__file__, self.section.collect())