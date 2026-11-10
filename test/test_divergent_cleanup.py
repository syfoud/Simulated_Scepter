"""差分宇宙清理后的结构约束：复用通用内核与静态数据，不再保留自己的重复实现。"""

import json
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from importing import load_img

load_img()

import core.common.ocr as common_ocr  # noqa: E402
import core.common.runtime as common_runtime  # noqa: E402
import core.divergent.config as divergent_config  # noqa: E402
import core.divergent.ocr as divergent_ocr  # noqa: E402
import core.divergent.utils as divergent_utils  # noqa: E402
from core.any_fate.text_key import text_keys  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "core" / "divergent" / "config" / "default.json"


class DivergentReuseTest(unittest.TestCase):
    def test_base_class_is_the_shared_script_kernel(self):
        self.assertTrue(issubclass(divergent_utils.UniverseUtils, common_runtime.ScriptKernel))

    def test_dead_methods_are_gone(self):
        """这些方法已无调用点，差分宇宙改用通用实现或直接删除。"""
        for name in (
            "use_it",
            "use_consumable",
            "get_direc_only_minimap",
            "get_bw_map",
            "nof",
            "move_to_end",
            "get_real_loc",
            "write_map",
            "set_forground",
        ):
            with self.subTest(name=name):
                self.assertNotIn(name, divergent_utils.UniverseUtils.__dict__)

    def test_screen_and_text_helpers_come_from_common(self):
        for name in ("get_screen", "save_screen", "click_text", "calc_point"):
            with self.subTest(name=name):
                self.assertNotIn(name, divergent_utils.UniverseUtils.__dict__)
                self.assertTrue(hasattr(divergent_utils.UniverseUtils, name))

    def test_blessing_data_reuses_the_shared_static_table(self):
        self.assertIs(divergent_utils.text_keys, text_keys)


class DivergentConfigTest(unittest.TestCase):
    def test_machine_level_calibration_fields_are_gone(self):
        config = divergent_config.config
        for name in ("angle", "long_press_sprint"):
            with self.subTest(name=name):
                self.assertFalse(hasattr(config, name))

    def test_default_module_config_does_not_carry_removed_fields(self):
        config = json.loads(DEFAULT_CONFIG.read_text(encoding="utf-8"))["config"]
        for name in ("angle", "long_press_sprint"):
            with self.subTest(name=name):
                self.assertNotIn(name, config)


class DivergentOcrTest(unittest.TestCase):
    def test_ocr_wrapper_extends_the_common_one(self):
        self.assertTrue(issubclass(divergent_ocr.My_TS, common_ocr.My_TS))

    def test_kernel_create_ts_hook_is_overridden(self):
        self.assertIsNot(
            divergent_utils.UniverseUtils.create_ts,
            common_runtime.ScriptKernel.create_ts,
        )


class SharedOcrHookTest(unittest.TestCase):
    def test_default_hook_returns_the_global_wrapper(self):
        sentinel = Mock()

        with patch.object(common_runtime, "get_global_my_ts", return_value=sentinel) as factory:
            result = common_runtime.ScriptKernel.create_ts(Mock())

        self.assertIs(result, sentinel)
        factory.assert_called_once()


if __name__ == "__main__":
    unittest.main()
