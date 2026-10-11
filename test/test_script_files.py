"""验证脚本校验、保存失败保护和可视化编辑往返，不运行游戏。"""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QApplication, QFileDialog, QMessageBox, QTableWidgetItem

from route import PATHS
from tool.gui.script_editor import ScriptEditor, new_event
from tool.script_files import (
    discover_scripts,
    parse_script,
    read_script,
    save_script,
    script_key,
    script_path,
    validate_script,
)

ROOT = Path(__file__).resolve().parents[1]


class ScriptFileTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        self.enterContext(patch.dict(PATHS, {"root": str(self.root)}))
        self.path = self.root / "actions" / "脚本.json"
        self.data = [new_event()]

    def test_existing_module_scripts_are_valid_without_mutation(self):
        for path in [*ROOT.glob("core/*/actions/*.json"), ROOT / "actions/farmgluttony.json"]:
            with self.subTest(path=path):
                original = json.loads(path.read_text(encoding="utf-8"))
                self.assertEqual(read_script(path), original)

    def test_save_roundtrip_preserves_unknown_fields_methods_and_numeric_strings(self):
        self.data[0]["annotation"] = {"custom": True}
        self.data[0]["trigger"]["module_option"] = 7
        self.data[0]["actions"] = ["select_event", {"sleep": "0.6", "extra": "keep"}]
        save_script(self.path, self.data)
        self.assertEqual(read_script(self.path), self.data)

    def test_invalid_structure_coordinates_and_times_are_rejected(self):
        invalid = [[], {}, [{"name": "事件"}], [dict(new_event(), trigger={})]]
        for step in (17, "bad.method", {}, {"position": [0]}, {"sleep": -1}, {"sleep": "bad"}, {"sleep": True}, {"sleep": float("nan")}):
            invalid.append([dict(new_event(), actions=[step])])
        for data in invalid:
            with self.subTest(data=data), self.assertRaises(ValueError):
                validate_script(data)

    def test_json_error_reports_line_and_column(self):
        with self.assertRaisesRegex(ValueError, "第 2 行"):
            parse_script('[\n{"name": } ]')

    def test_failed_atomic_save_keeps_existing_file_and_removes_temporary_file(self):
        save_script(self.path, self.data)
        before = self.path.read_bytes()
        with patch("tool.storage.os.replace", side_effect=OSError("模拟写入失败")), self.assertRaises(OSError):
            save_script(self.path, [dict(new_event(), name="修改")])
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(list(self.path.parent.glob(".config-*")), [])

    def test_path_keys_and_discovery_include_valid_scripts_only(self):
        save_script(self.path, self.data)
        (self.path.parent / "metadata.json").write_text('{"a": "b"}', encoding="utf-8")
        (self.path.parent / "broken.json").write_text("[", encoding="utf-8")
        registry = Mock()
        registry.runnable.return_value = []
        self.assertEqual(discover_scripts(registry), [self.path])
        self.assertEqual(script_key(self.path), "actions/脚本.json")
        self.assertEqual(script_path(script_key(self.path)), self.path)
        external = self.root.parent / "external.json"
        self.assertEqual(script_path(script_key(external)), external.resolve())


class ScriptEditorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        self.enterContext(patch.dict(PATHS, {"root": str(self.root)}))
        self.path = self.root / "actions/编辑.json"
        self.data = [new_event()]
        self.data[0]["extra"] = {"keep": [1, 2]}
        self.data[0]["actions"].append("select_event")
        save_script(self.path, self.data)
        registry = Mock()
        registry.runnable.return_value = []
        self.editor = ScriptEditor(registry, str(self.path))
        self.addCleanup(self.editor.deleteLater)

    def test_parameters_source_and_save_roundtrip_preserve_extensions(self):
        table = self.editor.step_fields.table
        table.setItem(0, 1, QTableWidgetItem("2"))
        self.editor.tabs.setCurrentIndex(1)
        source = json.loads(self.editor.source_edit.toPlainText())
        self.assertEqual(source[0]["actions"][0], {"sleep": 2})
        source[0]["trigger"]["interval"] = 3
        self.editor.source_edit.setPlainText(json.dumps(source, ensure_ascii=False))
        self.editor.tabs.setCurrentIndex(0)
        self.assertEqual(self.editor.trigger_fields.value()["interval"], 3)
        self.assertTrue(self.editor.save())
        self.assertEqual(read_script(self.path), source)
        self.assertFalse(self.editor.isWindowModified())

    def test_invalid_source_cannot_leave_tab_or_overwrite_script(self):
        before = self.path.read_bytes()
        self.editor.tabs.setCurrentIndex(1)
        self.editor.source_edit.setPlainText("[")
        self.editor.tabs.setCurrentIndex(0)
        self.assertEqual(self.editor.tabs.currentIndex(), 1)
        self.assertFalse(self.editor.save())
        self.assertEqual(self.path.read_bytes(), before)
        self.assertTrue(self.editor.isWindowModified())

    def test_invalid_parameter_keeps_selected_step_and_unsaved_input(self):
        self.editor.step_fields.table.setItem(0, 1, QTableWidgetItem("bad json"))
        self.editor.step_list.setCurrentRow(1)
        self.assertEqual(self.editor.step_list.currentRow(), 0)
        self.assertEqual(self.editor.step_fields.table.item(0, 1).text(), "bad json")
        self.assertIn("JSON", self.editor.status_label.text())

    def test_event_clone_reorder_and_step_add_remove(self):
        self.editor.clone_event_btn.click()
        self.assertEqual(len(self.editor.document), 2)
        self.assertEqual(self.editor.document[1]["extra"], self.data[0]["extra"])
        self.editor.event_up_btn.click()
        self.assertIn("副本", self.editor.document[0]["name"])
        self.editor.step_type.setCurrentText("点击坐标")
        self.editor.add_step_btn.click()
        self.assertEqual(self.editor.step_fields.value(), {"position": [960, 540]})
        self.editor.step_up_btn.click()
        self.assertEqual(self.editor.step_list.item(1).data(Qt.UserRole), {"position": [960, 540]})
        self.editor.remove_step_btn.click()
        self.assertEqual(self.editor.step_list.count(), 2)
        self.assertTrue(self.editor.save())
        self.assertEqual(len(read_script(self.path)), 2)

    def test_save_as_emits_new_path_without_mutating_original(self):
        before = self.path.read_bytes()
        destination = self.path.parent / "新脚本.json"
        saved = Mock()
        self.editor.script_saved.connect(saved)
        self.editor.event_name.setText("另存为事件")
        with patch.object(QFileDialog, "getSaveFileName", return_value=(str(destination), "JSON")):
            self.assertTrue(self.editor.save(as_new=True))
        saved.assert_called_once_with(str(destination))
        self.assertEqual(read_script(destination)[0]["name"], "另存为事件")
        self.assertEqual(self.path.read_bytes(), before)

    def test_cancel_file_switch_and_close_keep_unsaved_document(self):
        self.editor.mark_dirty()
        self.editor.event_name.setText("未保存事件")
        with patch.object(QMessageBox, "question", return_value=QMessageBox.Cancel):
            self.editor.new_script()
            self.editor.reject()
        self.assertEqual(self.editor.event_name.text(), "未保存事件")
        self.assertTrue(self.editor.isWindowModified())
        self.assertEqual(read_script(self.path), self.data)

    def test_function_action_edit_is_preserved_as_string(self):
        self.editor.step_list.setCurrentRow(1)
        self.editor.step_fields.table.setItem(0, 1, QTableWidgetItem('"other_method"'))
        self.assertTrue(self.editor.save())
        self.assertEqual(read_script(self.path)[0]["actions"][1], "other_method")


if __name__ == "__main__":
    unittest.main()
