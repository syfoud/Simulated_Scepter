"""调试地图窗口的初值回归：自动更新线程可能早于首次地图匹配就把 debug_map 画出来。"""

import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np

from importing import load_img

load_img()

import core.any_fate.utils as fate_utils  # noqa: E402
from core.any_fate.engine import AnyFateUniverse  # noqa: E402
from core.any_fate.utils import FateUtils  # noqa: E402
from core.common.runtime import ScriptKernel  # noqa: E402


class DebugMapWindowTest(unittest.TestCase):
    def setUp(self):
        self.manager = Mock()
        self.enterContext(patch.object(fate_utils, "set_forground"))
        self.enterContext(patch.object(fate_utils, "get_multi", return_value=1.0))
        self.enterContext(patch.object(fate_utils, "key_mouse_manager", self.manager))
        self.enterContext(patch.object(fate_utils, "PositionPredict"))
        self.enterContext(patch.object(ScriptKernel, "__init__", lambda self: setattr(self, "hwnd", None)))
        self.enterContext(patch.object(FateUtils, "load_img_map"))
        self.enterContext(patch.object(FateUtils, "update_count"))
        self.enterContext(patch.object(FateUtils, "CrTU5s61E1dMnT"))

    def test_engine_initializes_map_offsets_before_any_map_is_matched(self):
        """未匹配到地图时 upx/upy 也必须有初值，调试窗口才能直接绘制。"""
        engine = FateUtils(fate="巡猎")

        self.assertEqual((engine.upx, engine.upy), (0, 0))

    def test_show_map_draws_from_the_debug_map_before_the_first_match(self):
        engine = AnyFateUniverse.__new__(AnyFateUniverse)
        engine._stop = False
        engine.debug_map = np.zeros((120, 120, 3), dtype=np.uint8)
        engine.big_map = None
        engine.now_loc = (60, 60)
        engine.target_loc = None
        engine.target_type = -1
        engine.ang = None
        engine.pos_map = None
        engine.upx = engine.upy = 0
        cv = Mock()
        cv.WINDOW_FREERATIO = 0
        cv.WINDOW_NORMAL = 0
        cv.pollKey.return_value = ord("q")

        with patch("core.any_fate.engine.cv", cv), \
                patch("core.any_fate.engine.set_forground"), \
                patch("core.any_fate.engine.time", SimpleNamespace(sleep=lambda _: None)):
            engine.show_map()

        cv.imshow.assert_called_once()


if __name__ == "__main__":
    unittest.main()
