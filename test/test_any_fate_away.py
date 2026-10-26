"""
any_fate 主循环「暂离」判定的回归测试。

背景（logs/log_2026-10-25-07-36.txt 第 88536 行起）：角色寻路卡住、超过 max_interact_time
没有有效交互后触发暂离。旧的暂离判定排在整段走图逻辑之后——程序先寻路、施放银狼秘技，
紧接着才按 esc。秘技施放动画期间 esc 唤不出暂离界面，3 秒轮询全部失败；而失败路径又不更新
last_interact_time，下一轮超时条件依旧成立，于是形成「寻路 → 施放秘技 → esc 无效 → 轮询失败」
的死循环（直到某一轮碰巧没施放秘技才退出）。

现在的行为（core/any_fate/engine.py 的 normal）：
- need_away（need_end 表示本局提前结束并结算；或超过 max_interact_time 没有有效交互）在任何
  走动、施放秘技、寻路之前判定，需要离开时这段走图逻辑整段跳过。
- 3 秒内没识别到「暂离」文字就直接 return 1 回到主循环，本轮不再走动或施放秘技；
  同时不动 last_interact_time，下一轮仍然判定需要暂离（暂离请求因此不会被丢掉）。
- 识别到「暂离」后清空 self.area：暂离会回到「黑塔的办公室」，重进本局后区域名要重新识别
  （init_map 只在 new_node 为真时才清 area，回到同一节点时不会清，于是会一直拿旧区域名寻路）。

战斗状态下按 esc 只会把战斗暂停（弹出「继续战斗」），不会出现暂离界面，程序会一直停在暂停
菜单上，因此 insect.json 增加了「战斗暂停」事件负责点回战斗；它必须排在「自动战斗检测」
之前——暂停菜单上 auto_battle 按的 v 键不生效，先命中它就会一直重来。
"""

import json
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np

from tool.utils.image_tool import load_all_images_from_directory

# 内核在导入期就会读图像记忆切片（例如 tool/utils/predict.py），需要先装载图像缓存
ROOT = Path(__file__).resolve().parents[1]
load_all_images_from_directory(str(ROOT / "resource" / "imgs"))

INSECT_JSON = ROOT / "core" / "any_fate" / "actions" / "insect.json"

from core.any_fate.engine import AnyFateUniverse

# normal() 里按 esc 后轮询「暂离」文字的识别框（与实现同值：改实现时这里要跟着改）
AWAY_BOX = [1321, 1383, 787, 821]
# 超时暂离的判定阈值（秒）
MAX_INTERACT_TIME = 40
# 暂离时长按期间所在的区域名（区域名只用于寻路，暂离成功后被清空）
AREA = "战斗"
# 战斗中按 esc 弹出的暂停菜单「继续战斗」按钮（与 insect.json「战斗暂停」同值）
BATTLE_PAUSE_BOX = [1580, 1679, 970, 998]
BATTLE_PAUSE_CLICK = [1631, 983]
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


def load_insect():
    return json.loads(INSECT_JSON.read_text(encoding="utf-8"))


def event_index(events, name):
    return next(i for i, event in enumerate(events) if event["name"] == name)


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


class BattlePauseJsonTest(unittest.TestCase):
    """insect.json 的「战斗暂停」接线：战斗中按 esc 暂停后必须能自动点回战斗。"""

    def test_battle_pause_event_resumes_the_battle(self):
        """「继续战斗」点掉后把状态改回 battle，否则主循环会停在暂停菜单上。"""
        events = load_insect()
        event = events[event_index(events, "战斗暂停")]

        self.assertEqual(event["trigger"]["text"], "继续战斗")
        self.assertEqual(event["trigger"]["box"], BATTLE_PAUSE_BOX)
        self.assertEqual(
            event["actions"], [{"position": BATTLE_PAUSE_CLICK}, {"set_state": "battle"}]
        )

    def test_battle_pause_is_checked_before_auto_battle(self):
        """「战斗暂停」必须排在「自动战斗检测」之前：暂停菜单上 auto_battle 的 v 键不生效，会一直重来。"""
        events = load_insect()

        self.assertLess(event_index(events, "战斗暂停"), event_index(events, "自动战斗检测"))


if __name__ == "__main__":
    unittest.main()
