"""黄泉 use_e 连续两次秘技的回归测试。

游戏对过快的重复秘技只认第一次，所以两次 e 之间必须真的等一段间隔。
`press(..., force=True)` 会插到键鼠队列最前、把 sleep 排到第二次 e 之后，
因此这里用普通 press + key_mouse_manager.sleep 保证顺序。
"""

import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from tool.utils.image_tool import load_all_images_from_directory

# core.any_fate.utils 导入期会读图像缓存（predict 的掩膜等），先装载
ROOT = Path(__file__).resolve().parents[1]
load_all_images_from_directory(str(ROOT / "resource" / "imgs"))

from core.any_fate.utils import FateUtils  # noqa: E402


class UseETechniqueOrderTest(unittest.TestCase):
    """use_e 内部两次秘技、以及 fixed 时改普攻的行为。"""

    def _run_use_e(self, *, fixed):
        utils = FateUtils.__new__(FateUtils)
        utils.quan = 1
        utils.bai_e = 0
        manager = Mock()
        with patch("core.any_fate.utils.key_mouse_manager", manager):
            utils.use_e(fixed=fixed)
        return manager

    def test_quan_presses_technique_twice_with_sleep_between(self):
        """两次 technique 之间必须先执行 sleep，不能把两下 e 连按完再 sleep。"""
        manager = self._run_use_e(fixed=False)

        calls = []
        for call in manager.method_calls:
            name = call[0]
            if name in ("press", "sleep", "wait"):
                calls.append((name,) + tuple(call[1]))
        self.assertEqual(
            [
                ("press", "technique"),
                ("wait",),
                ("sleep", 0.2),
                ("press", "technique"),
                ("wait",),
                ("wait",),
            ],
            calls,
        )
        # 不能带 force=True：强制按键会插队到 sleep 前面
        for call in manager.press.call_args_list:
            self.assertEqual(("technique",), call.args)
            self.assertEqual({}, call.kwargs)

    def test_fixed_uses_one_click_without_technique(self):
        """fixed=True（秘技点不足）只普攻一次，不按 e。"""
        manager = self._run_use_e(fixed=True)

        manager.press.assert_not_called()
        manager.click_point.assert_called_once_with(960, 540)
        manager.wait.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
