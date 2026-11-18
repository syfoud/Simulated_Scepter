"""货币战争策略配置界面。"""

from core.currency.affix_select_ui import AffixSelectDialog
from core.currency.strategy_select_ui import StrategySelectDialog
from core.currency.deployment_ui import DeploymentDialog
from core.currency.priority_ui import CurrencyPriorityDialog
from core.currency.settings import (
    EXIT_PLANES,
    load_currency_settings,
    save_currency_settings,
)
from tool.gui.settings_dialog import SettingsDialog as BaseDialog
from tool.storage import config_path, resource_path


class SettingsDialog(BaseDialog):
    def __init__(self, parent=None):
        super().__init__("货币战争配置", parent)
        self.path = config_path(__file__)
        settings = load_currency_settings(path=self.path)
        self.section = ui = self.add_section(resource_path(__file__, "ui/settings.ui"))
        for plane in EXIT_PLANES:
            ui.Currency_exit_plane_combo.addItem(f"第 {plane} 位面", plane)
        ui.Currency_exit_plane_combo.addItem("不退出", None)
        ui.Currency_exit_plane_combo.setCurrentIndex(
            ui.Currency_exit_plane_combo.findData(settings["exit_after_plane"]))
        ui.Currency_exit_if_no_prior_checkbox.setChecked(settings["exit_if_no_prior"])
        ui.Currency_prior_exit_plane_combo.addItem("不调整", None)
        for plane in EXIT_PLANES:
            ui.Currency_prior_exit_plane_combo.addItem(f"第 {plane} 位面", plane)
        ui.Currency_prior_exit_plane_combo.setCurrentIndex(
            ui.Currency_prior_exit_plane_combo.findData(settings["prior_exit_plane"]))

        ui.Currency_gamemode_combo.addItem("超频博弈（节点更少）", "overclock")
        ui.Currency_gamemode_combo.addItem("标准博弈（少一次标签点击）", "standard")
        ui.Currency_gamemode_combo.setCurrentIndex(
            ui.Currency_gamemode_combo.findData(settings["gamemode"]))
        ui.Currency_difficulty_mode_combo.addItem("逐级向下找难度 1", "lowest")
        ui.Currency_difficulty_mode_combo.addItem("最高职级（A8-20，开局带词缀）", "top")
        ui.Currency_difficulty_mode_combo.setCurrentIndex(
            ui.Currency_difficulty_mode_combo.findData(settings["difficulty_mode"]))
        self.affix_targets = list(settings["affix_targets"])
        ui.Currency_affix_targets_edit.setText("、".join(self.affix_targets))
        ui.Currency_max_runs_spin.setValue(settings["max_runs"])
        ui.Currency_gather_mode_checkbox.setChecked(settings["gather_mode"])

        self.strategy_targets = list(settings["strategy_targets"])
        self.strategy_avoid = list(settings["strategy_avoid"])
        ui.Currency_strategy_targets_edit.setText("、".join(self.strategy_targets))
        ui.Currency_strategy_avoid_edit.setText("、".join(self.strategy_avoid))
        ui.Currency_auto_exit_plane_checkbox.setChecked(settings["auto_exit_plane"])
        ui.Currency_auto_clear_targets_checkbox.setChecked(settings["auto_clear_targets"])
        ui.Currency_auto_exit_plane_checkbox.toggled.connect(self._sync_exit_plane_widgets)
        self._sync_exit_plane_widgets(settings["auto_exit_plane"])

        ui.Currency_priority_settings_btn.clicked.connect(self.open_priority)
        ui.Currency_deployment_settings_btn.clicked.connect(self.open_deployment)
        ui.Currency_affix_targets_btn.clicked.connect(self.open_affix_targets)
        ui.Currency_strategy_targets_btn.clicked.connect(self.open_strategy_targets)
        ui.Currency_strategy_avoid_btn.clicked.connect(self.open_strategy_avoid)
        self._sync_target_buttons()

    def _sync_exit_plane_widgets(self, auto):
        """勾了「按目标策略自动决定退出位面」后，上面两个手选退出位面就没意义了，直接禁用。"""
        for combo in (
            self.section.Currency_exit_plane_combo,
            self.section.Currency_prior_exit_plane_combo,
        ):
            combo.setEnabled(not auto)

    def open_priority(self):
        CurrencyPriorityDialog(self).exec_()

    def open_deployment(self):
        DeploymentDialog(self).exec_()

    def _sync_target_buttons(self):
        """把已选数量写进按钮，让人一眼看出"点了能改什么、现在选了几个"。"""
        pairs = (
            ("Currency_affix_targets_btn", "选择词缀…", self.affix_targets),
            ("Currency_strategy_targets_btn", "选择目标策略…", self.strategy_targets),
            ("Currency_strategy_avoid_btn", "选择负面策略…", self.strategy_avoid),
        )
        for name, base, chosen in pairs:
            button = getattr(self.section, name, None)
            if button is None:
                continue
            button.setText(f"{base}（已选 {len(chosen)}）" if chosen else base)

    def open_affix_targets(self):
        """三列勾选目标词缀；取消时保持原选择。"""
        dialog = AffixSelectDialog(self.affix_targets, self)
        if dialog.exec_() != dialog.Accepted:
            return
        self.affix_targets = dialog.selected_affixes()
        self._sync_target_buttons()
        self.section.Currency_affix_targets_edit.setText("、".join(self.affix_targets))

    def persist(self):
        ui = self.section
        save_currency_settings({
            "exit_after_plane": ui.Currency_exit_plane_combo.currentData(),
            "exit_if_no_prior": ui.Currency_exit_if_no_prior_checkbox.isChecked(),
            "prior_exit_plane": ui.Currency_prior_exit_plane_combo.currentData(),
            "gamemode": ui.Currency_gamemode_combo.currentData(),
            "difficulty_mode": ui.Currency_difficulty_mode_combo.currentData(),
            "affix_targets": list(self.affix_targets),
            "strategy_targets": list(self.strategy_targets),
            "strategy_avoid": list(self.strategy_avoid),
            "auto_exit_plane": ui.Currency_auto_exit_plane_checkbox.isChecked(),
            "auto_clear_targets": ui.Currency_auto_clear_targets_checkbox.isChecked(),
            "max_runs": ui.Currency_max_runs_spin.value(),
            "gather_mode": ui.Currency_gather_mode_checkbox.isChecked(),
        }, path=self.path)
    def open_strategy_targets(self):
        """目标策略：勾选后优先选它们，并据此推算退出位面。"""
        dialog = StrategySelectDialog(
            self.strategy_targets, self,
            title="选择目标投资策略",
            hint="勾选要优先选、并且希望收集的策略；退出位面会按「还没收到的目标里最晚出现的那一面」自动推算。",
        )
        if dialog.exec_() != dialog.Accepted:
            return
        self.strategy_targets = dialog.selected_strategies()
        self._sync_target_buttons()
        self.section.Currency_strategy_targets_edit.setText("、".join(self.strategy_targets))

    def open_strategy_avoid(self):
        """负面策略：脚本绝不选它们。"""
        dialog = StrategySelectDialog(
            self.strategy_avoid, self,
            title="选择负面投资策略",
            hint="勾选绝对不想选的策略（跨局继承资源、卖掉全场角色之类）。",
        )
        if dialog.exec_() != dialog.Accepted:
            return
        self.strategy_avoid = dialog.selected_strategies()
        self._sync_target_buttons()
        self.section.Currency_strategy_avoid_edit.setText("、".join(self.strategy_avoid))

