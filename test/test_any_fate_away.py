"""
any_fate 主循环「暂离」判定的回归测试。

背景（logs/log_2026-10-25-07-36.txt 第 88536 行起）：角色寻路卡住、超过 max_interact_time
没有有效交互后触发暂离。旧的暂离判定排在整段走图逻辑之后——程序先寻路、施放银狼秘技，
紧接着才按 esc。秘技施放动画期间 esc 唤不出暂离界面，3 秒轮询全部失败；而失败路径又不更新
last_interact_time，下一轮超时条件依旧成立，于是形成「寻路 → 施放秘技 → esc 无效 → 轮询失败」
的死循环（该日志里连续 188 次，直到某一轮碰巧没施放秘技才退出）。

现在的行为（core/any_fate/engine.py 的 normal）：
- need_away（need_end 表示本局提前结束并结算；或超过 max_interact_time 没有有效交互）在任何
  走动、施放秘技、寻路之前判定，需要离开时这段走图逻辑整段跳过。
- 3 秒内没识别到「暂离」文字就直接 return 1 回到主循环，本轮不再走动或施放秘技；
  同时不动 last_interact_time，下一轮仍然判定需要暂离（暂离请求因此不会被丢掉）。
- 识别到「暂离」后清空 self.area：暂离会回到「黑塔的办公室」，重进本局后区域名要重新识别
  （init_map 只在 new_node 为真时才清 area，回到同一节点时不会清，于是会一直拿旧区域名寻路）。
"""

import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np

from tool.utils.image_tool import load_all_images_from_directory

# 内核在导入期就会读图像记忆切片（例如 tool/utils/predict.py），需要先装载图像缓存
ROOT = Path(__file__).resolve().parents[1]
load_all_images_from_directory(str(ROOT / "resource" / "imgs"))

from core.any_fate.engine import AnyFateUniverse

# normal() 里按 esc 后轮询「暂离」文字的识别框（与真实现同值：改 real 代码时这里要跟着改）
AWAY_BOX = [1321, 1383, 787, 821]
# 超时暂离的判定阈值（秒）
MAX_INTERACT_TIME = 40
# 暂离时长按期间所在的区域名（区域名只用于寻路，暂离成功后被清空）
AREA = "战斗"
# normal() 需要的画面：只做占位，OCR 与模板匹配都被打桩
SCREEN = np.zeros((1080, 1920, 3), dtype=np.uint8)


class _FakeClock:
    """按固定步长前进的假时钟：3 秒轮询窗口要确定性结束，不能真的等 3 秒。"""

    def __init__(self, start=1000.0, step=0.1):
        self.now = start
        self.step = step

    def time(self):
        self.now += self.step
        return self.now


def make_engine(last_interact_time=1000.0, need_end=False):
    """
    只提供 normal() 所需接口的替身。

    真正的 __init__ 会初始化窗口、键鼠、地图、银狼管理器并读配置，单测里不需要也不该走那一套。
    """
    engine = AnyFateUniverse.__new__(AnyFateUniverse)
    engine.state = "run"
    engine.area = AREA
    engine.quan = engine.bai_e = False
    engine.need_end = need_end
    engine.need_record = engine.auto_attack_breakable = False
    engine.last_interact_time = last_interact_time
    engine.attack_time = last_interact_time
    engine.max_interact_time = MAX_INTERACT_TIME
    engine.fail_count = 0
    engine.now_map = 1
    engine.now_map_sim = 0.5
    engine.debug = 0
    engine.opt = {}
    engine.loaded_map_root = None
    engine.screen = SCREEN
    engine.get_screen = Mock(return_value=SCREEN)
    engine.ts = Mock()
    # run_static 打桩：本文件只验证走图与暂离的先后顺序，不加载 insect.json
    engine.run_static = Mock(return_value=("", 0))
    engine.check = Mock(return_value=False)
    # 暂离界面出现与否由各用例指定
    engine.click_text = Mock(return_value=True)
    engine.update_state = Mock()
    engine.init_map = Mock()
    engine.is_pig_node = Mock(return_value=False)
    engine.switch_current_role = Mock()
    engine.switch_to_configured_role = Mock()
    engine.navigate_battle = Mock(return_value=True)
    engine.record_special_map_or_navigate = Mock(return_value=False)
    engine.get_adventure = Mock(return_value=False)
    engine.check_minimap_icon = Mock(return_value=False)
    return engine


class AwayBeforeMovementTest(unittest.TestCase):
    def setUp(self):
        self.manager = Mock()
        self.enterContext(patch("core.any_fate.engine.key_mouse_manager", self.manager))
        self.logger = Mock()
        self.enterContext(patch("core.any_fate.engine.CUS_LOGGER", self.logger))
        self.clock = _FakeClock()
        self.enterContext(
            patch(
                "core.any_fate.engine.time",
                SimpleNamespace(time=self.clock.time, sleep=Mock()),
            )
        )

    def _pressed_keys(self):
        return [c.args[0] for c in self.manager.press.call_args_list]

    def test_timeout_away_presses_esc_without_walking_or_casting_first(self):
        """超时暂离：这一轮只按 esc 找「暂离」，不寻路、不空打一拳、不施放秘技。"""
        engine = make_engine(last_interact_time=0.0)

        self.assertEqual(engine.normal(), 1)

        self.assertEqual(self._pressed_keys(), ["esc"])
        self.manager.keyUp.assert_called_once_with("w")
        self.manager.click.assert_not_called()  # 空打一拳是 click(0.5, 0.5)
        engine.navigate_battle.assert_not_called()
        engine.switch_current_role.assert_not_called()
        engine.ts.find_with_box.assert_not_called()  # 区域名 OCR 属于走图逻辑
        engine.click_text.assert_called_once_with(
            text="暂离", box=AWAY_BOX, click=False, allow_fail=True
        )

    def test_away_clears_area_and_hands_over_to_ui_state(self):
        """识别到「暂离」后进入 ui 状态，并清空区域名（暂离回到「黑塔的办公室」，不再处于原区域）。"""
        engine = make_engine(last_interact_time=0.0)

        self.assertEqual(engine.normal(), 1)

        engine.update_state.assert_called_once_with("ui")
        engine.init_map.assert_called_once_with()
        self.assertEqual(engine.floor_init, 0)
        self.assertEqual(engine.area, "")

    def test_esc_miss_returns_to_the_main_loop_without_walking(self):
        """3 秒没唤出暂离界面：直接回主循环，不补按 esc、不走动、不施放秘技。"""
        engine = make_engine(last_interact_time=0.0)
        engine.click_text = Mock(return_value=False)
        start = engine.last_interact_time

        self.assertEqual(engine.normal(), 1)

        # 只按一次 esc：再按一次可能把已经弹出的暂停菜单关掉
        self.assertEqual(self._pressed_keys(), ["esc"])
        self.manager.click.assert_not_called()
        engine.navigate_battle.assert_not_called()
        # 没离开跑图状态：状态与区域名都不动，界面也没换
        engine.update_state.assert_not_called()
        engine.init_map.assert_not_called()
        self.assertEqual(engine.area, AREA)
        # last_interact_time 不动：下一轮依旧判定需要暂离，暂离请求不会被丢掉
        self.assertEqual(engine.last_interact_time, start)
        self.assertTrue(any("未识别到暂离文本" in c.args[0] for c in self.logger.debug.call_args_list))

    def test_need_end_leaves_for_settlement_even_if_recently_interacted(self):
        """need_end（本局提前结束并结算）优先于交互计时：刚交互过也要立刻走暂离流程。"""
        engine = make_engine(last_interact_time=1000.5, need_end=True)

        self.assertEqual(engine.normal(), 1)

        self.assertEqual([c.args for c in engine.update_state.call_args_list], [("ui",), ("exit",)])
        self.assertEqual(self._pressed_keys(), ["esc"])
        engine.navigate_battle.assert_not_called()
        self.assertEqual(engine.area, "")

    def test_run_path_still_walks_when_away_is_not_needed(self):
        """不需要离开时不按 esc，照原样寻路（防止把 need_away 写成一直接通）。"""
        engine = make_engine(last_interact_time=1000.0)

        self.assertEqual(engine.normal(), 1)

        engine.navigate_battle.assert_called_once_with()
        self.assertEqual(self._pressed_keys(), [])
        engine.update_state.assert_not_called()
        self.assertEqual(engine.area, AREA)


if __name__ == "__main__":
    unittest.main()
