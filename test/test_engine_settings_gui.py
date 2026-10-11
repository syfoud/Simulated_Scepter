"""用真实配置窗口与临时配置文件验证解耦后的保存和联动。"""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml
from PyQt5.QtCore import Qt
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QMessageBox,
    QTextBrowser,
    QWidget,
)

from core.common import config as runtime_config
from route import PATHS
from test.core_fixture import copy_core
from tool.registry import KernelRegistry
from tool.settings import load_settings, update_settings
from tool.storage import config_path, load_module_settings, update_module_settings


class EngineSettingsGuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.config = Path(folder.name) / "config"
        self.config.mkdir()
        self.settings = self.config / "settings.json"
        self.models = Path(folder.name) / "models"
        self.models.mkdir()
        (self.models / "kesln.onnx").write_bytes(b"UI authorization fixture")
        data = json.loads((Path(PATHS["example"]) / "settings_example.json").read_text(encoding="utf-8"))
        data.update({"early_stop": False, "other": {"keep": True}, "any_fate": "巡猎"})
        self.settings.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        self.core = copy_core(Path(folder.name) / "core")
        for module, legacy in (("simulated", "info_old.yml"), ("divergent", "info.yml"),
                               ("currency", "currency_config.yml")):
            (self.config / legacy).write_bytes((self.core / module / "config/default.yml").read_bytes())
        self.enterContext(patch.dict(PATHS, {"config": str(self.config), "model": str(self.models), "core": str(self.core), "backup": str(Path(folder.name) / "backup")}))

        self.registry = KernelRegistry()
        self.paths = {}
        # 首次迁移单独测试；打开窗口前完成迁移后，取消不得写入任何配置。
        for spec in self.registry.specs.values():
            self.paths[spec.id] = config_path(spec.folder / "settings_ui.py")

    def values(self, engine):
        return json.loads(self.paths[engine].read_text(encoding="utf-8"))

    def dialog(self, engine):
        dialog = self.registry.create_settings(engine)
        self.addCleanup(dialog.deleteLater)
        dialog.show()
        self.app.processEvents()
        return dialog

    def save(self, dialog):
        dialog.buttons.button(QDialogButtonBox.Save).click()
        self.assertEqual(dialog.result(), QDialog.Accepted)

    def test_all_settings_windows_load_and_cancel_without_writing(self):
        before = {file.name: file.read_bytes() for file in self.config.iterdir()}
        for engine in (spec.id for spec in self.registry.runnable()):
            with self.subTest(engine=engine):
                dialog = self.dialog(engine)
                self.assertTrue(dialog.section.isVisible())
                dialog.buttons.button(QDialogButtonBox.Cancel).click()
                self.assertEqual(dialog.result(), QDialog.Rejected)
        self.assertEqual(before, {file.name: file.read_bytes() for file in self.config.iterdir()})

    def test_common_settings_share_one_file_with_inheriting_kernels(self):
        dialog = self.dialog("Common")
        dialog.runtime.Iron_blood_max_run_input.setText("12")
        self.save(dialog)
        self.assertEqual(self.values("Common")["max_run_time"], 12)
        inherited = self.dialog("AnyFate")
        self.assertEqual(inherited.runtime.Iron_blood_max_run_input.text(), "12")
        self.assertNotIn("max_run_time", self.values("AnyFate"))

    def test_factory_imports_only_the_selected_module(self):
        with patch("tool.registry.import_module") as importer:
            for spec in self.registry.runnable():
                self.registry.create_settings(spec.id)
                importer.assert_called_with(f"core.{spec.folder.name}.settings_ui")
            self.assertEqual(importer.call_count, len(self.registry.runnable()))

    def test_legacy_role_slot_is_migrated_before_any_configuration_window_opens(self):
        self.paths["Common"].unlink()
        update_settings({"silver_wolf_switch": "三号位"})
        loaded = load_module_settings(runtime_config.__file__)
        self.assertEqual(loaded["silver_wolf_switch"], 3)
        self.assertNotIn("silver_wolf_switch", load_settings())
        self.assertEqual(load_settings()["other"], {"keep": True})

    def test_yaml_settings_save_only_the_selected_engine_and_restore_visible_values(self):
        for engine, filename, field in (
            ("Simulated", "info_old.yml", "Simul_max_run_input"),
            ("Divergent", "info.yml", "Diver_max_run_input"),
        ):
            with self.subTest(engine=engine):
                others = {p.name: p.read_bytes() for p in self.config.iterdir() if p.name != filename}
                dialog = self.dialog(engine)
                getattr(dialog.section, field).setText("7")
                if engine == "Divergent":
                    dialog.section.Diver_team_combo.setCurrentText("击破")
                self.save(dialog)
                values = yaml.safe_load(self.paths[engine].read_text(encoding="utf-8"))["config"]
                self.assertEqual(values["max_run"], 7)
                reopened = self.dialog(engine)
                self.assertEqual(getattr(reopened.section, field).text(), "7")
                if engine == "Divergent":
                    self.assertEqual(reopened.section.Diver_team_combo.currentText(), "击破")
                self.assertEqual(others, {p.name: p.read_bytes() for p in self.config.iterdir() if p.name != filename})

    def test_shared_runtime_keys_and_specialized_keys_round_trip_without_duplication(self):
        dialog = self.dialog("AnyFate")
        dialog.section.Any_fate_combo.setCurrentText("智识")
        dialog.runtime.Iron_blood_max_run_input.setText("8")
        dialog.runtime.pig_switch_2_role.setChecked(True)
        dialog.runtime.silver_wolf_switch_combo.setCurrentIndex(2)
        self.save(dialog)
        iron = self.dialog("IronBlood")
        self.assertEqual(iron.runtime.Iron_blood_max_run_input.text(), "8")
        self.assertEqual(iron.runtime.silver_wolf_switch_combo.currentData(), 3)
        iron.section.Iron_blood_first_plane_input.setText("19")
        self.save(iron)
        finger = self.dialog("FingerSnap")
        finger.section.Finger_snap_seed_input.setText("123")
        self.save(finger)
        stored = load_settings() | self.values("Common") | self.values("AnyFate") | self.values("IronBlood") | self.values("FingerSnap")
        self.assertEqual(stored["any_fate"], "智识")
        self.assertEqual(stored["first_plane"], 19)
        self.assertEqual(stored["max_run_time"], 8)
        self.assertEqual(stored["finger_snap_model"]["seed"], 123)
        self.assertEqual(stored["other"], {"keep": True})
        self.assertNotIn("gui_debug", stored)

    def test_finger_snap_early_stop_controls_follow_existing_master_switch(self):
        dialog = self.dialog("FingerSnap")
        ui = dialog.section
        checkboxes = tuple(getattr(ui, f"Finger_snap_{key}_checkbox") for key in (
            "dp_early_stop", "win_rate_dp_early_stop", "mc_dp_early_stop"))
        inputs = tuple(getattr(ui, "Finger_snap_" + key) for key in (
            "plane1_target_input", "plane2_target_input", "plane3_target_input", "record_keep_count_input"))
        for widget in checkboxes:
            widget.setChecked(True)
        for widget, value in zip(inputs, ("15", "75", "80", "31"), strict=True):
            widget.setText(value)
        for enabled in (False, True, False):
            dialog.runtime.early_stop_checkbox.setChecked(enabled)
            for widget in (*checkboxes, *inputs):
                self.assertEqual(widget.isEnabled(), enabled)
            for widget in checkboxes:
                if not enabled:
                    widget.click()
                self.assertTrue(widget.isChecked())
            for widget, value in zip(inputs, ("15", "75", "80", "31"), strict=True):
                if not enabled:
                    QTest.keyClicks(widget, "9")
                self.assertEqual(widget.text(), value)
            self.assertTrue(ui.Finger_snap_seed_input.isEnabled())
            self.assertTrue(ui.Finger_snap_first_plane_threshold_input.isEnabled())

    def test_missing_model_disables_advanced_early_stop_controls(self):
        update_module_settings(runtime_config.__file__, {"early_stop": True})
        with patch.dict(PATHS, {"model": str(self.config / "missing")}):
            for engine in ("AnyFate", "IronBlood", "FingerSnap"):
                dialog = self.dialog(engine)
                self.assertFalse(dialog.runtime.early_stop_checkbox.isEnabled())
                self.assertTrue(dialog.runtime.Aboutupdatelock.isVisible())
                if engine == "IronBlood":
                    self.assertFalse(dialog.section.Iron_blood_first_plane_input.isEnabled())
                elif engine == "FingerSnap":
                    for field in ("dp_early_stop_checkbox", "win_rate_dp_early_stop_checkbox", "mc_dp_early_stop_checkbox",
                                  "plane1_target_input", "plane2_target_input", "plane3_target_input", "record_keep_count_input"):
                        self.assertFalse(getattr(dialog.section, "Finger_snap_" + field).isEnabled())

    def test_authorized_early_stop_is_under_advanced_heading_and_unlock_prompt_is_hidden(self):
        for engine in ("AnyFate", "IronBlood", "FingerSnap"):
            with self.subTest(engine=engine):
                dialog = self.dialog(engine)
                self.assertTrue(dialog.runtime.early_stop_checkbox.isEnabled())
                self.assertTrue(dialog.runtime.Aboutupdatelock.isHidden())
                self.assertEqual(dialog.runtime.advanced_label.text(), "高级用户功能")
                self.assertLess(dialog.runtime.advanced_label.y(), dialog.runtime.early_stop_checkbox.y())

    def test_unlock_button_opens_shared_instructions_in_every_early_stop_window(self):
        captured = []

        def capture(dialog):
            self.assertEqual(dialog.windowTitle(), "高级用户功能解锁说明")
            text = dialog.findChild(QTextBrowser).toPlainText()
            self.assertIn("kesln.onnx", text)
            self.assertIn("resource/models/", text)
            captured.append(text)
            return QDialog.Rejected

        with patch.dict(PATHS, {"model": str(self.config / "missing")}), \
                patch.object(QDialog, "exec_", new=capture):
            for engine in ("AnyFate", "IronBlood", "FingerSnap"):
                dialog = self.dialog(engine)
                dialog.runtime.Aboutupdatelock.click()
        self.assertEqual(len(captured), 3)
        self.assertEqual(len(set(captured)), 1)

    def test_auth_check_requires_a_file_and_does_not_accept_a_named_directory(self):
        model = self.models / "kesln.onnx"
        model.unlink()
        model.mkdir()
        dialog = self.dialog("FingerSnap")
        self.assertFalse(dialog.runtime.early_stop_checkbox.isEnabled())
        self.assertTrue(dialog.runtime.Aboutupdatelock.isVisible())

    def test_kernel_settings_do_not_offer_debug_toggles_or_overwrite_debug_flags(self):
        for engine, filename, old_control in (
            ("Simulated", "info_old.yml", "Simul_debug_checkbox"),
            ("Divergent", "info.yml", "Diver_debug_checkbox"),
        ):
            path = self.paths[engine]
            values = yaml.safe_load(path.read_text(encoding="utf-8"))
            values["config"]["debug_mode"] = 1
            path.write_text(yaml.safe_dump(values, allow_unicode=True), encoding="utf-8")
            dialog = self.dialog(engine)
            self.assertIsNone(dialog.findChild(QWidget, old_control))
            self.save(dialog)
            self.assertEqual(yaml.safe_load(path.read_text(encoding="utf-8"))["config"]["debug_mode"], 1)

    def test_invalid_model_input_does_not_partially_save_runtime_settings(self):
        dialog = self.dialog("FingerSnap")
        before = self.paths["Common"].read_bytes()
        dialog.runtime.Iron_blood_max_run_input.setText("8")
        dialog.section.Finger_snap_seed_input.setText("invalid")
        with patch.object(QMessageBox, "warning") as warning:
            dialog.buttons.button(QDialogButtonBox.Save).click()
            warning.assert_called_once()
        self.assertEqual(dialog.result(), QDialog.Rejected)
        self.assertTrue(dialog.isVisible())
        self.assertEqual(self.paths["Common"].read_bytes(), before)

    def test_write_failure_keeps_dialog_open_and_reports_failure(self):
        dialog = self.dialog("AnyFate")
        before = self.settings.read_bytes()
        with patch("core.any_fate.settings_ui.save_json_configs", side_effect=OSError("无法写入")), \
                patch.object(QMessageBox, "critical") as critical:
            dialog.buttons.button(QDialogButtonBox.Save).click()
            critical.assert_called_once()
        self.assertTrue(dialog.isVisible())
        self.assertEqual(self.settings.read_bytes(), before)

    def test_yaml_write_failure_restores_running_configuration(self):
        import core.simulated.settings_ui as module

        dialog = self.dialog("Simulated")
        previous = module.config.max_run
        before = self.paths["Simulated"].read_bytes()
        dialog.section.Simul_max_run_input.setText("99")
        with patch.object(module.config, "save", side_effect=OSError("无法写入")), \
                patch.object(QMessageBox, "critical") as critical:
            dialog.buttons.button(QDialogButtonBox.Save).click()
            critical.assert_called_once()
        self.assertEqual(module.config.max_run, previous)
        self.assertEqual(self.paths["Simulated"].read_bytes(), before)
        self.assertTrue(dialog.isVisible())

    def test_battle_weight_warning_intercepts_first_edit_and_survives_reopening(self):
        update_module_settings(runtime_config.__file__, {"early_stop": True})
        update_module_settings(self.registry.specs["IronBlood"].folder / "settings_ui.py", {"battle_weight_warning_shown": False})
        dialog = self.dialog("IronBlood")
        field = dialog.section.Iron_blood_battle_weight_input
        original = field.text()
        with patch.object(QMessageBox, "exec_", return_value=QMessageBox.Ok) as warning:
            QTest.keyClick(field, Qt.Key_2)
            self.assertEqual(field.text(), original)
            warning.assert_called_once()
            QTest.keyClick(field, Qt.Key_A, Qt.ControlModifier)
            QTest.keyClick(field, Qt.Key_2)
            self.assertEqual(field.text(), "2")
            warning.assert_called_once()
        self.assertTrue(self.values("IronBlood")["battle_weight_warning_shown"])
        reopened = self.dialog("IronBlood")
        with patch.object(QMessageBox, "exec_") as warning:
            QTest.keyClick(reopened.section.Iron_blood_battle_weight_input, Qt.Key_2)
            warning.assert_not_called()

    def test_priority_editor_save_preserves_strategy_and_reopens_saved_order(self):
        from core.currency.priority_ui import CurrencyPriorityDialog

        path = self.paths["Currency"]
        before = yaml.safe_load(path.read_text(encoding="utf-8"))
        dialog = CurrencyPriorityDialog()
        self.addCleanup(dialog.deleteLater)
        values = dialog.collect_current()
        values["prior_envir"] = ["自定义环境", *values["prior_envir"]]
        dialog.populate_lists(values)
        with patch.object(QMessageBox, "information"):
            dialog.save_button.click()
        stored = yaml.safe_load(path.read_text(encoding="utf-8"))
        self.assertEqual(stored["priority"], values)
        self.assertEqual({key: value for key, value in stored.items() if key != "priority"},
                         {key: value for key, value in before.items() if key != "priority"})
        reopened = CurrencyPriorityDialog()
        self.addCleanup(reopened.deleteLater)
        self.assertEqual(reopened.collect_current(), values)

    def test_currency_strategy_save_preserves_priority_and_other_fields(self):
        path = self.paths["Currency"]
        values = yaml.safe_load(path.read_text(encoding="utf-8"))
        values["custom"] = "保留"
        path.write_text(yaml.safe_dump(values, allow_unicode=True), encoding="utf-8")
        dialog = self.dialog("Currency")
        dialog.section.Currency_exit_plane_combo.setCurrentIndex(2)
        dialog.section.Currency_prior_exit_plane_combo.setCurrentIndex(2)
        dialog.section.Currency_exit_if_no_prior_checkbox.setChecked(True)
        self.save(dialog)
        stored = yaml.safe_load(path.read_text(encoding="utf-8"))
        self.assertEqual(stored["exit_after_plane"], 3)
        self.assertEqual(stored["prior_exit_plane"], 2)
        self.assertTrue(stored["exit_if_no_prior"])
        self.assertEqual(stored["priority"], values["priority"])
        self.assertEqual(stored["custom"], "保留")
        reopened = self.dialog("Currency")
        self.assertEqual(reopened.section.Currency_exit_plane_combo.currentData(), 3)


if __name__ == "__main__":
    unittest.main()
