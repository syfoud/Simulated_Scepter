"""「转向后按 w 再出手」的回归测试。

大世界战斗中，程序到达敌人记录点位后会在旋转小地图上找红点，调用
update_direction_data(mode=2) 把镜头转向敌人；但转镜头不改变角色朝向，必须再轻点一次
move_w，角色朝向才会跟随镜头，随后释放的秘技/普攻才会真正打向敌人。敌人已经走离记录
点位时（红点距小地图中心 ds>28 像素），先按住 w 接近到 22 像素以内，再重新识别一次
红点、二次转向、轻点 w，然后才出手。

覆盖 core/any_fate/utils.py：
- _nearest_enemy：在小地图上挑离中心最近的红点；没有红点时返回 None。
- face_enemy：ds<=28 直接转向并轻点 w；ds>28 先按住 w 接近（瞄准红叉出现或外部要求
  停止时提前退出），再重新识别、二次转向；找不到红点/转向失败时返回 False、不按 w。
- 两个攻击入口：get_path_only_minimap 的 z 信息条攻击段、get_path_with_big_map 的
  target_type==1 攻击段，都必须先 face_enemy 再出手。

全部用例离线运行：get_minimap/predict/key_mouse_manager 等外部依赖一律打桩，不截图、
不操作键鼠、不依赖游戏窗口。
"""

import unittest
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np

from tool.utils.image_tool import load_all_images_from_directory

# 内核在导入期就会读图像记忆切片（例如 tool/utils/predict.py），需要先装载图像缓存
ROOT = Path(__file__).resolve().parents[1]
load_all_images_from_directory(str(ROOT / "resource" / "imgs"))

from core.any_fate.utils import FateUtils  # noqa: E402

# 小地图上敌人红点的 BGR 像素值，以及判定为红点的平方差阈值（与实现同值）
RED_BGR = (47, 47, 232)
RED_THRESHOLD = 4500
# 旋转小地图的尺寸与玩家中心：186 = 2 * MINIMAP_RADIUS(93)
MINIMAP_SIZE = 186
MINIMAP_CENTER = (93, 93)
# face_enemy 的攻击距离（小地图像素）
ATTACK_DISTANCE = 28


def make_minimap(points):
    """造一张 186x186 的旋转小地图占位图。

    Args:
        points: 红点像素坐标列表，坐标口径为 (x, y)，原点在图像左上角。

    Returns:
        全黑背景、只在给定坐标写入敌人红点的 BGR 图像。
    """
    minimap = np.zeros((MINIMAP_SIZE, MINIMAP_SIZE, 3), dtype=np.uint8)
    for x, y in points:
        minimap[y, x] = RED_BGR
    return minimap


def make_utils():
    """构造不跑 __init__ 的 FateUtils 替身，只填本轮用例需要的内核状态。

    真 __init__ 会初始化窗口、键鼠、地图并读配置，这里只需要小地图截帧与红点阈值。
    """
    utils = FateUtils.__new__(FateUtils)
    utils.screen = np.zeros((1080, 1920, 3), dtype=np.uint8)
    utils.red_threshold = RED_THRESHOLD
    utils.debug = 0
    utils.is_sprinting = 0
    # 外部停止标记：face_enemy 接近过程中会检查它，接近结束后据此决定是否还轻点 w
    utils._stop = 0
    utils.get_screen = Mock(return_value=utils.screen)
    return utils


class _FakeClock:
    """按固定步长前进的假时钟，让 face_enemy 的按住 w 时长确定性地结束。"""

    def __init__(self, start=1000.0, step=0.1):
        self.now = start
        self.step = step

    def time(self):
        self.now += self.step
        return self.now


class _RecordingClock(_FakeClock):
    """假时钟的加强版：记下每次 time() 的返回值。

    face_enemy 里的 time() 只用于按住 w 的计时，因此首末两次读数之差就是实际计时区间，
    可用来验证「冲刺 12 / 步行 8 像素每秒」两档速度。
    """

    def __init__(self, start=1000.0, step=0.1):
        super().__init__(start=start, step=step)
        self.times = []

    def time(self):
        value = super().time()
        self.times.append(value)
        return value


class _NoopThread:
    """替身线程：start() 什么都不做，避免测试里真的起更新地图/移动线程。"""

    def __init__(self, *args, **kwargs):
        pass

    def start(self):
        pass


def make_minimap_check():
    """按 check 的 path/fresh 语义返回结果，而不是按调用次数排的固定序列。

    get_path_only_minimap 里 "z" 有两处不同用途：入口处的 fresh 检查必须返回 False 才会
    继续走图；攻击段内再次 fresh 确认怪物信息条仍在时要返回 True 才会进入出手流程。按
    参数语义构造结果后，实现多调一次 check 也只是多问一次，不会耗尽序列抛 StopIteration。
    """
    z_fresh_calls = 0

    def check(path, *args, **kwargs):
        nonlocal z_fresh_calls
        if path != "z":
            return False  # interact / auto_2 都不命中
        if kwargs.get("fresh"):
            z_fresh_calls += 1
            return z_fresh_calls > 1
        return True  # 非 fresh 的 "z" 就是攻击段入口，必须命中

    return check


class NearestEnemyTest(unittest.TestCase):
    """_nearest_enemy：在小地图红点里挑离玩家中心最近的一个。"""

    def test_returns_the_red_point_closest_to_minimap_center(self):
        """多个红点：返回距小地图中心 (93,93) 最近的点，而不是排在前面的点。"""
        utils = make_utils()
        # 三个红点与中心的距离分别是 89、27、7：最近的是 (100,93)
        minimap = make_minimap([(30, 30), (93, 120), (100, 93)])

        with patch("core.any_fate.utils.get_minimap", return_value=minimap):
            self.assertEqual((100, 93), utils._nearest_enemy())

    def test_returns_none_without_red_points(self):
        """小地图上没有红点：返回 None，交给 face_enemy 决定放弃出手。"""
        utils = make_utils()

        with patch("core.any_fate.utils.get_minimap", return_value=make_minimap([])):
            self.assertIsNone(utils._nearest_enemy())


class FaceEnemyTest(unittest.TestCase):
    """face_enemy：转向敌人 + 轻点 w，让秘技/普攻打向敌人。"""

    def setUp(self):
        self.manager = Mock()
        self.enterContext(patch("core.any_fate.utils.key_mouse_manager", self.manager))
        self.enterContext(patch("core.any_fate.utils.CUS_LOGGER", Mock()))

    def _record_key_calls(self, calls):
        """把键鼠调用记进 calls，用于断言「先按住接近、再轻点」的先后顺序。"""
        self.manager.keyDown.side_effect = lambda key: calls.append(("keyDown", key))
        self.manager.keyUp.side_effect = lambda key: calls.append(("keyUp", key))
        self.manager.press.side_effect = (
            lambda key, *args, **kwargs: calls.append(("press", key))
        )

    def test_enemy_within_attack_range_turns_once_and_taps_w(self):
        """ds<=28：只转一次视角、轻点一次 w，不按住 w 接近。

        ds 恰好等于 28 是边界值：不应触发「按住 w 接近」的远距离分支。
        """
        utils = make_utils()
        calls = []

        def turn(mode=None, target=None):
            calls.append(("turn", mode, target))
            return ATTACK_DISTANCE

        utils.update_direction_data = Mock(side_effect=turn)
        self._record_key_calls(calls)

        with patch(
            "core.any_fate.utils.get_minimap",
            return_value=make_minimap([(MINIMAP_CENTER[0], MINIMAP_CENTER[1] + 27)]),
        ):
            self.assertTrue(utils.face_enemy())

        utils.update_direction_data.assert_called_once_with(
            mode=2, target=((93, 120), 3)
        )
        # 先转视角，再轻点 w；角色朝向才会跟上镜头
        self.assertEqual(
            [("turn", 2, ((93, 120), 3)), ("press", "move_w")], calls
        )
        self.manager.keyDown.assert_not_called()
        self.manager.keyUp.assert_not_called()

    def test_far_enemy_is_approached_then_reacquired_and_turned_again(self):
        """ds>28：先按住 w 接近，再重新识别红点、二次转向，最后轻点 w。

        断言完整的调用顺序，防止把「先接近再转向」写成「先转向再接近」或漏掉二次识别。
        """
        utils = make_utils()
        utils.is_sprinting = 0
        far_point = (93, 140)   # 距中心 47 像素，超出攻击距离
        near_point = (93, 110)  # 接近后重新识别到的红点，距中心 17 像素
        distances = iter([40.0, 20.0])  # 第一次转向后仍需接近，二次转向后已在攻击距离内
        calls = []

        def turn(mode=None, target=None):
            calls.append(("turn", mode, target))
            return next(distances)

        utils.update_direction_data = Mock(side_effect=turn)
        self._record_key_calls(calls)
        # 两次识别各返回一张小地图：接近前红点在远处，按住 w 走完后重新识别到更近的红点
        minimaps = [make_minimap([far_point]), make_minimap([near_point])]

        with (
            patch("core.any_fate.utils.get_minimap", side_effect=minimaps) as get_minimap,
            patch("core.any_fate.utils.predict", return_value={"enemy": None}),
            patch(
                "core.any_fate.utils.time",
                SimpleNamespace(time=_FakeClock().time),
            ),
        ):
            self.assertTrue(utils.face_enemy())

        # 每识别一次红点就转向一次：get_minimap 被调用两次即两次识别
        self.assertEqual(2, get_minimap.call_count)
        self.assertEqual(
            [
                ("turn", 2, (far_point, 3)),
                ("keyDown", "move_w"),
                ("keyUp", "move_w"),
                ("turn", 2, (near_point, 3)),
                ("press", "move_w"),
            ],
            calls,
        )

    def test_aim_cross_during_approach_stops_walking_early(self):
        """接近途中出现瞄准红叉：立即停止接近，不再跑满按住时长。

        即使提前退出，也必须先松开 w，再重新识别红点、二次转向，最后轻点 w。
        """
        utils = make_utils()
        utils.is_sprinting = 0
        far_point = (93, 140)
        near_point = (93, 110)
        distances = iter([40.0, 20.0])
        calls = []

        def turn(mode=None, target=None):
            calls.append(("turn", mode, target))
            return next(distances)

        utils.update_direction_data = Mock(side_effect=turn)
        self._record_key_calls(calls)
        minimaps = [make_minimap([far_point]), make_minimap([near_point])]

        with (
            patch("core.any_fate.utils.get_minimap", side_effect=minimaps),
            # 接近循环的第一帧就检测到瞄准红叉
            patch(
                "core.any_fate.utils.predict",
                return_value={"enemy": (960, 540)},
            ) as predict,
            patch("core.any_fate.utils.time", SimpleNamespace(time=_FakeClock().time)),
        ):
            self.assertTrue(utils.face_enemy())

        predict.assert_called_once()
        # 只截了初始、接近循环一帧、松键后重识别一帧；跑满 follow-up 时长需要约 22 次截帧
        self.assertLess(utils.get_screen.call_count, 5)
        self.assertEqual(
            [
                ("turn", 2, (far_point, 3)),
                ("keyDown", "move_w"),
                ("keyUp", "move_w"),
                ("turn", 2, (near_point, 3)),
                ("press", "move_w"),
            ],
            calls,
        )

    def test_sprinting_holds_w_for_the_dash_duration(self):
        """is_sprinting=1：按住时长按冲刺 12 像素/秒算，ds=46 时约 2.0 秒。

        步行 8 像素/秒时同样的 ds 需要 3.0 秒，用计时区间约等于哪个值把两档速度区分开。
        """
        utils = make_utils()
        utils.is_sprinting = 1
        clock = _RecordingClock()
        far_point = (93, 140)
        utils.update_direction_data = Mock(side_effect=[46.0, 20.0])
        minimaps = [make_minimap([far_point]), make_minimap([(93, 110)])]

        with (
            patch("core.any_fate.utils.get_minimap", side_effect=minimaps),
            patch("core.any_fate.utils.predict", return_value={"enemy": None}),
            patch("core.any_fate.utils.time", SimpleNamespace(time=clock.time)),
        ):
            self.assertTrue(utils.face_enemy())

        elapsed = clock.times[-1] - clock.times[0]
        # (46 - 22) / 12 = 2.0 秒；假时钟按 0.1 秒步进，用 delta 容纳最后一次步进误差，
        # 不卡 >= 2.0 的浮点边界。步行 8 像素/秒时同样的 ds 会是 3.0 秒，两档可区分。
        self.assertAlmostEqual(elapsed, 2.0, delta=clock.step)

    def test_second_scan_without_red_point_skips_retry_turn_but_keeps_w_tap(self):
        """接近后第二次识别不到红点：不二次转向，但仍然松开 w、轻点 w、返回 True。"""
        utils = make_utils()
        utils.is_sprinting = 0
        far_point = (93, 140)
        calls = []

        def turn(mode=None, target=None):
            calls.append(("turn", mode, target))
            return 40.0

        utils.update_direction_data = Mock(side_effect=turn)
        self._record_key_calls(calls)
        # 接近前有红点，按住 w 走完后小地图上已经看不到红点
        minimaps = [make_minimap([far_point]), make_minimap([])]

        with (
            patch("core.any_fate.utils.get_minimap", side_effect=minimaps) as get_minimap,
            patch("core.any_fate.utils.predict", return_value={"enemy": None}),
            patch("core.any_fate.utils.time", SimpleNamespace(time=_FakeClock().time)),
        ):
            self.assertTrue(utils.face_enemy())

        self.assertEqual(2, get_minimap.call_count)  # 接近前后各识别一次
        utils.update_direction_data.assert_called_once_with(
            mode=2, target=(far_point, 3)
        )
        self.assertEqual(
            [
                ("turn", 2, (far_point, 3)),
                ("keyDown", "move_w"),
                ("keyUp", "move_w"),
                ("press", "move_w"),
            ],
            calls,
        )

    def test_stop_during_approach_releases_w_and_skips_tap(self):
        """接近过程中外部要求停止：提前退出、松开 w、返回 False，不再轻点 w。"""
        utils = make_utils()
        utils.is_sprinting = 0
        far_point = (93, 140)
        calls = []

        def turn(mode=None, target=None):
            calls.append(("turn", mode, target))
            return 40.0

        utils.update_direction_data = Mock(side_effect=turn)
        self._record_key_calls(calls)

        def stop_on_detection(*args, **kwargs):
            utils._stop = 1
            return {"enemy": None}

        with (
            patch(
                "core.any_fate.utils.get_minimap",
                return_value=make_minimap([far_point]),
            ),
            patch("core.any_fate.utils.predict", side_effect=stop_on_detection),
            patch("core.any_fate.utils.time", SimpleNamespace(time=_FakeClock().time)),
        ):
            self.assertFalse(utils.face_enemy())

        # 停止后不再二次识别红点、不再转向、不轻点 w
        utils.update_direction_data.assert_called_once_with(
            mode=2, target=(far_point, 3)
        )
        self.assertEqual(
            [
                ("turn", 2, (far_point, 3)),
                ("keyDown", "move_w"),
                ("keyUp", "move_w"),
            ],
            calls,
        )

    def test_exception_during_approach_releases_w_and_reraises(self):
        """接近途中抛异常：异常原样抛出，但 finally 仍松键并把松键冲刷进键鼠线程。

        异常路径不轻点 w、不做二次识别，所以 get_minimap 只调用 1 次。
        """
        utils = make_utils()
        utils.is_sprinting = 0
        far_point = (93, 140)
        calls = []

        def turn(mode=None, target=None):
            calls.append(("turn", mode, target))
            return 40.0

        utils.update_direction_data = Mock(side_effect=turn)
        self._record_key_calls(calls)

        with (
            patch(
                "core.any_fate.utils.get_minimap",
                return_value=make_minimap([far_point]),
            ) as get_minimap,
            patch("core.any_fate.utils.predict", side_effect=RuntimeError("boom")),
            patch("core.any_fate.utils.time", SimpleNamespace(time=_FakeClock().time)),
        ):
            with self.assertRaises(RuntimeError):
                utils.face_enemy()

        self.assertEqual(1, get_minimap.call_count)  # 异常后不再二次识别红点
        self.manager.keyUp.assert_called_once_with("move_w")
        # wait 共两次：一次是计时前的冲刷，一次在 finally 里保证松键真正生效
        self.assertEqual(2, self.manager.wait.call_count)
        self.manager.press.assert_not_called()
        self.assertEqual(
            [
                ("turn", 2, (far_point, 3)),
                ("keyDown", "move_w"),
                ("keyUp", "move_w"),
            ],
            calls,
        )

    def test_returns_false_without_red_point_and_does_not_turn_or_tap_w(self):
        """没有红点：返回 False，不转向、不按 w，把出手机会留给后续逻辑。"""
        utils = make_utils()
        utils.update_direction_data = Mock()
        calls = []
        self._record_key_calls(calls)

        with patch("core.any_fate.utils.get_minimap", return_value=make_minimap([])):
            self.assertFalse(utils.face_enemy())

        utils.update_direction_data.assert_not_called()
        self.assertEqual([], calls)

    def test_returns_false_when_turn_reports_failure(self):
        """转向失败（update_direction_data 返回 False）：不轻点 w 就返回 False。"""
        utils = make_utils()
        utils.update_direction_data = Mock(return_value=False)
        calls = []
        self._record_key_calls(calls)

        with patch(
            "core.any_fate.utils.get_minimap",
            return_value=make_minimap([(93, 120)]),
        ):
            self.assertFalse(utils.face_enemy())

        self.assertEqual([], calls)


class AttackEntryTest(unittest.TestCase):
    """两个攻击入口都必须在出手前调用 face_enemy。"""

    def setUp(self):
        self.manager = Mock()
        self.enterContext(patch("core.any_fate.utils.key_mouse_manager", self.manager))
        self.enterContext(patch("core.any_fate.utils.CUS_LOGGER", Mock()))

    @staticmethod
    def _navigation_patches(minimap):
        """打桩寻路过程的外部依赖：小地图、冲刺标记、技能数字 OCR、更新地图线程。"""
        stack = ExitStack()
        stack.enter_context(patch("core.any_fate.utils.get_minimap", return_value=minimap))
        stack.enter_context(patch("core.any_fate.utils.sprint"))
        stack.enter_context(
            patch("core.any_fate.utils.match_skill_numbers_in_region", return_value=None)
        )
        stack.enter_context(
            patch("core.any_fate.utils.ThreadWithException", _NoopThread)
        )
        return stack

    def _make_only_minimap_utils(self):
        """只填 get_path_only_minimap 走到 z 信息条攻击段所需的状态。"""
        utils = FateUtils.__new__(FateUtils)
        utils.debug = 0
        utils.screen = np.zeros((1080, 1920, 3), dtype=np.uint8)
        utils.red_threshold = RED_THRESHOLD
        # 已有初始角度，跳过「读小地图推测初始角度」那一步
        utils.initial_angle = 359
        utils.mini_state = 0
        utils.quan = 1
        utils.bai_e = 0
        # 非 4/8/13 层：施放秘技后本轮直接返回，不必反复走位
        utils.floor = 1
        utils.skill_num = 5
        utils._stop = 0
        utils.get_screen = Mock(return_value=utils.screen)
        utils.move_to_red_point = Mock(return_value=True)
        utils.auto_update_map = Mock()
        utils.is_run = Mock(return_value=True)
        utils.update_state = Mock()
        utils.use_e = Mock()
        utils.face_enemy = Mock()
        # 按 check(path, fresh) 的语义返回：不依赖调用次数序列，实现多调一次也不会耗尽
        utils.check = Mock(side_effect=make_minimap_check())
        return utils

    def _make_big_map_utils(self, *, trust_annotated=False, quan=1):
        """只填 get_path_with_big_map 走到 target_type==1 攻击段所需的状态。"""
        target = ((12, 34), 1)
        utils = FateUtils.__new__(FateUtils)
        utils.debug = 0
        utils.screen = np.zeros((1080, 1920, 3), dtype=np.uint8)
        utils.red_threshold = RED_THRESHOLD
        utils.target = {target}
        utils.target_loc = target[0]
        utils.now_loc = target[0]
        utils.target_type = 1
        utils.trust_annotated_attack_targets = trust_annotated
        utils.quan = quan
        utils.bai_e = 0
        utils.skill_num = 5
        utils.is_sprinting = 0
        utils._stop = False
        utils.last_interact_time = 0
        utils.get_screen = Mock(return_value=utils.screen)
        utils.get_loc = Mock(return_value=True)
        utils.get_recent_target = Mock(return_value=target)
        # 首帧距离取远离目标的值，避免进入「靠近目标点」的收尾分支
        utils.update_direction_data = Mock(return_value=100)
        utils.check = Mock(return_value=False)
        utils.face_enemy = Mock()
        utils.use_e = Mock()
        return utils

    def test_z_monster_info_attack_faces_enemy_before_technique(self):
        """小地图外侧没有遇敌红圈：先 face_enemy，再施放秘技。"""
        utils = self._make_only_minimap_utils()
        order = []
        utils.face_enemy.side_effect = lambda: order.append("face_enemy")
        utils.use_e.side_effect = lambda **kwargs: order.append("use_e")

        with self._navigation_patches(make_minimap([])):
            utils.get_path_only_minimap()

        utils.face_enemy.assert_called_once_with()
        self.assertEqual(3, utils.use_e.call_count)
        self.assertLess(order.index("face_enemy"), order.index("use_e"))

    def test_nearby_red_ring_already_means_enemy_is_close(self):
        """小地图外侧已有遇敌红圈：敌人就在旁边，不需要再转向找人。"""
        utils = self._make_only_minimap_utils()

        # 红点放在 mask_minimap_outside 保留的圆环上（距中心 85 像素）
        with self._navigation_patches(make_minimap([(93, 178)])):
            utils.get_path_only_minimap()

        utils.face_enemy.assert_not_called()
        self.assertEqual(3, utils.use_e.call_count)

    def test_big_map_attack_faces_enemy_before_technique(self):
        """target_type==1 且非信任标注：先 face_enemy 再施放秘技。"""
        utils = self._make_big_map_utils(quan=1)
        order = []
        utils.face_enemy.side_effect = lambda: order.append("face_enemy")
        utils.use_e.side_effect = lambda **kwargs: order.append("use_e")

        # 圆环红点在主循环第一轮就会让程序判定「敌人就在旁边」并跳出寻路
        with self._navigation_patches(make_minimap([(93, 178)])):
            utils.get_path_with_big_map()

        utils.face_enemy.assert_called_once_with()
        self.assertEqual(2, utils.use_e.call_count)
        self.assertLess(order.index("face_enemy"), order.index("use_e"))

    def test_big_map_attack_faces_enemy_before_normal_attack(self):
        """没有秘技/战技可用时：先 face_enemy，再点画面中心普攻。"""
        utils = self._make_big_map_utils(quan=0)
        order = []
        utils.face_enemy.side_effect = lambda: order.append("face_enemy")
        self.manager.click_point.side_effect = (
            lambda *args, **kwargs: order.append("click_point")
        )

        with self._navigation_patches(make_minimap([(93, 178)])):
            utils.get_path_with_big_map()

        utils.face_enemy.assert_called_once_with()
        self.manager.click_point.assert_called_once_with(960, 540)
        self.assertLess(order.index("face_enemy"), order.index("click_point"))

    def test_trusted_annotated_red_target_skips_facing_and_clicks_once(self):
        """信任标注的特殊地图红点：不找小地图红点、不转向，直接按标注点普攻一次。"""
        utils = self._make_big_map_utils(trust_annotated=True)

        with self._navigation_patches(make_minimap([])):
            utils.get_path_with_big_map()

        utils.face_enemy.assert_not_called()
        self.manager.click_point.assert_called_once_with(960, 540)
        self.assertNotIn(((12, 34), 1), utils.target)


if __name__ == "__main__":
    unittest.main()
