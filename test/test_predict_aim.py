"""tool/utils/predict.py 敌人准星检测的回归测试。

准星检测（方向A）的流程：先把截图裁到准星区域内构造三张掩膜——白色准星掩膜、红色光晕
掩膜、中心红色色度图；再用霍夫圆在 [16, 64] 像素半径内找候选圆；对每个候选校验白色圆弧
的角度覆盖率与中心红色色度，最后按覆盖率从高到低排序。同一时刻屏幕上最多只有一个准星，
predict_enemy 只取覆盖率最高的候选。

全部用例离线运行：_enemy_masks 与 cv2.HoughCircles 都被打桩，不读真实截图、不做真实
霍夫变换；mask 坐标相对准星 ROI 左上角，检测结果会换算回全屏坐标（+255 / +95）。
RealEnemyMasksTest 例外地真实调用 _enemy_masks：它用 BGR 纯色合成图验证颜色语义
（BGR 纯红才是红色光晕），防止「把 BGR 截图当 RGB 解析」的颜色序缺陷回归。
"""

import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import cv2
import numpy as np

from tool.utils.image_tool import load_all_images_from_directory

# predict.py 在导入期就会从图像缓存里取交互掩膜，测试要先装载图像缓存
ROOT = Path(__file__).resolve().parents[1]
load_all_images_from_directory(str(ROOT / "resource" / "imgs"))

import tool.utils.predict as predict_module  # noqa: E402

# 准星 ROI 与全屏坐标的偏移（与实现同值）：1920x1080 截图去掉上下左右边距后是 1380x860
ROI_TOP = 95
ROI_LEFT = 255
ROI_HEIGHT = 860
ROI_WIDTH = 1380
# 白环画多粗由测试控制；5 像素足够覆盖实现里 ±2 像素的半径采样容差
RING_THICKNESS = 5
# 中心红色色度的测试取值（实现要求中心均值 >= 40）
CENTER_RED = 100
# 任意占位截图：_enemy_masks 被打桩，图像内容不参与检测
SCREEN = np.zeros((1080, 1920, 3), dtype=np.uint8)


def make_masks():
    """构造 _enemy_masks 的替身返回值 (white, glow, redness)。

    white / glow 是 0~255 的单通道掩膜，redness 是有符号色度图（R 与 G/B 均值之差）。
    """
    return (
        np.zeros((ROI_HEIGHT, ROI_WIDTH), dtype=np.uint8),
        np.zeros((ROI_HEIGHT, ROI_WIDTH), dtype=np.uint8),
        np.zeros((ROI_HEIGHT, ROI_WIDTH), dtype=np.int16),
    )


def draw_white_ring(white, center, radius, start_angle=0, end_angle=360):
    """在白色准星掩膜上画半径 radius 的圆环。

    不填满 360 度时用椭圆弧画一段缺口，使角度覆盖率低于整圈，但仍高于接受阈值。
    """
    if end_angle - start_angle >= 360:
        cv2.circle(white, center, radius, 255, RING_THICKNESS)
    else:
        cv2.ellipse(
            white, center, (radius, radius),
            0, start_angle, end_angle, 255, RING_THICKNESS,
        )


def fill_center_redness(redness, center, radius, value=CENTER_RED):
    """在候选中心的小圆区域填红色色度，_center_redness 取该区域均值。

    区域大小与实现一致：inner = max(3, int(radius * 0.25))，均值因此正好等于 value。
    """
    inner = max(3, int(radius * 0.25))
    x, y = center
    redness[y - inner:y + inner + 1, x - inner:x + inner + 1] = value


def hough_result(circles):
    """按 cv2.HoughCircles 的输出格式包装候选圆：形状 (1, N, 3)、(x, y, r)。"""
    return np.array([circles], dtype=np.float32)


def blank_screen():
    """返回 1080x1920 全黑 BGR 截图，供真实 _enemy_masks 的合成图用例使用。"""
    return np.zeros((1080, 1920, 3), dtype=np.uint8)


def draw_glow(image, color, roi_center, radius):
    """在全屏图像上以 ROI 相对坐标为中心画实心圆，模拟准星外圈的红色光晕。"""
    x, y = roi_center
    cv2.circle(image, (x + ROI_LEFT, y + ROI_TOP), radius, color, -1)


def draw_ring(image, roi_center, radius, color=(245, 245, 255), thickness=1):
    """在全屏图像上画细白圆环，模拟敌人准星的白色圆弧。"""
    x, y = roi_center
    cv2.circle(image, (x + ROI_LEFT, y + ROI_TOP), radius, color, thickness)


class EnemyCandidatesTest(unittest.TestCase):
    """enemy_candidates：合法候选被接受、按覆盖率排序，各类非法候选被拒绝。"""

    def _detect(self, white, glow, redness, circles):
        """打桩掩膜与霍夫圆后调用 enemy_candidates。"""
        with (
            patch.object(
                predict_module, "_enemy_masks", return_value=(white, glow, redness)
            ),
            patch.object(predict_module.cv2, "HoughCircles", return_value=circles),
        ):
            return predict_module.enemy_candidates(SCREEN)

    def test_accepts_high_coverage_ring_with_red_center(self):
        """白环覆盖完整、中心有红光：接受候选，中心换算成全屏坐标，覆盖率与色度达标。"""
        white, glow, redness = make_masks()
        center = (500, 430)
        radius = 24
        draw_white_ring(white, center, radius)
        fill_center_redness(redness, center, radius)

        candidates = self._detect(
            white, glow, redness, hough_result([[*center, radius]])
        )

        self.assertEqual(1, len(candidates))
        candidate = candidates[0]
        # ROI 内坐标换算成全屏坐标：+ROI_LEFT / +ROI_TOP
        self.assertEqual(
            (center[0] + ROI_LEFT, center[1] + ROI_TOP), candidate["center"]
        )
        self.assertEqual(radius, candidate["radius"])
        self.assertAlmostEqual(1.0, candidate["coverage"])
        self.assertAlmostEqual(CENTER_RED, candidate["center_red"])

    def test_sorts_candidates_by_coverage_descending(self):
        """多个候选：整圈覆盖的排在缺角圆弧前面，而不是保持 Hough 的原始顺序。"""
        white, glow, redness = make_masks()
        strong = (500, 430)
        weak = (700, 430)
        radius = 30
        draw_white_ring(white, strong, radius)
        fill_center_redness(redness, strong, radius)
        # 只画 300 度圆弧：覆盖率约 0.875，高于 0.75 的接受阈值但低于整圈
        draw_white_ring(white, weak, radius, start_angle=0, end_angle=300)
        fill_center_redness(redness, weak, radius)

        # 故意把弱候选放在 Hough 返回结果的第一位
        candidates = self._detect(
            white,
            glow,
            redness,
            hough_result([[*weak, radius], [*strong, radius]]),
        )

        self.assertEqual(2, len(candidates))
        self.assertEqual(
            (strong[0] + ROI_LEFT, strong[1] + ROI_TOP), candidates[0]["center"]
        )
        self.assertEqual(
            (weak[0] + ROI_LEFT, weak[1] + ROI_TOP), candidates[1]["center"]
        )
        self.assertAlmostEqual(1.0, candidates[0]["coverage"])
        self.assertGreater(candidates[0]["coverage"], candidates[1]["coverage"])
        self.assertLess(candidates[1]["coverage"], 1.0)
        self.assertGreaterEqual(candidates[1]["coverage"], 0.75)

    def test_rejects_candidate_when_ring_coverage_too_low(self):
        """Hough 半径与白环半径相差 10 像素：采样点落在白环外，覆盖率不足被拒绝。"""
        white, glow, redness = make_masks()
        center = (500, 430)
        draw_white_ring(white, center, 30)
        fill_center_redness(redness, center, 30)

        candidates = self._detect(
            white, glow, redness, hough_result([[*center, 40]])
        )

        self.assertEqual([], candidates)

    def test_rejects_candidate_when_center_redness_missing(self):
        """白环完整但中心没有红色色度（全 0）：准星不在红光里，被拒绝。"""
        white, glow, redness = make_masks()
        center = (500, 430)
        radius = 30
        draw_white_ring(white, center, radius)
        # redness 保持全 0

        candidates = self._detect(
            white, glow, redness, hough_result([[*center, radius]])
        )

        self.assertEqual([], candidates)

    def test_rejects_candidate_when_center_redness_is_negative(self):
        """中心红色色度为负值：同样不满足中心红光校验，被拒绝。"""
        white, glow, redness = make_masks()
        center = (500, 430)
        radius = 30
        draw_white_ring(white, center, radius)
        fill_center_redness(redness, center, radius, value=-50)

        candidates = self._detect(
            white, glow, redness, hough_result([[*center, radius]])
        )

        self.assertEqual([], candidates)

    def test_rejects_candidate_inside_horizontal_red_sign(self):
        """候选落在横向红色招牌上：红光被招牌撑成横条，按横向红色背景排除。"""
        white, glow, redness = make_masks()
        center = (500, 430)
        radius = 30
        draw_white_ring(white, center, radius)
        fill_center_redness(redness, center, radius)
        # 以候选为中心铺一条横向长条红光（宽 400、高 11），纵向几乎没有红色
        glow[center[1] - 5:center[1] + 6, center[0] - 200:center[0] + 201] = 255

        candidates = self._detect(
            white, glow, redness, hough_result([[*center, radius]])
        )

        self.assertEqual([], candidates)

    def test_returns_empty_when_hough_finds_no_circle(self):
        """霍夫圆没有找到任何候选（返回 None）：结果为空列表。"""
        white, glow, redness = make_masks()

        self.assertEqual([], self._detect(white, glow, redness, None))


class PredictEnemyTest(unittest.TestCase):
    """predict_enemy：只取覆盖率最高的候选，返回示意图与中心点数组。"""

    def _predict(self, white, glow, redness, circles):
        with (
            patch.object(
                predict_module, "_enemy_masks", return_value=(white, glow, redness)
            ),
            patch.object(predict_module.cv2, "HoughCircles", return_value=circles),
        ):
            return predict_module.predict_enemy(SCREEN)

    def test_returns_best_candidate_center_and_draw_mask(self):
        """有候选：draw 与截图同尺寸、在最佳候选处画出圆环，points[0] 是最佳中心。"""
        white, glow, redness = make_masks()
        best = (500, 430)
        radius = 30
        draw_white_ring(white, best, radius)
        fill_center_redness(redness, best, radius)
        # 另一个弱候选：覆盖率更低，不应被选中
        weak = (700, 430)
        draw_white_ring(white, weak, radius, start_angle=0, end_angle=300)
        fill_center_redness(redness, weak, radius)

        draw, points = self._predict(
            white,
            glow,
            redness,
            hough_result([[*weak, radius], [*best, radius]]),
        )

        self.assertEqual(SCREEN.shape[:2], draw.shape)
        self.assertEqual(1, len(points))
        best_center = (best[0] + ROI_LEFT, best[1] + ROI_TOP)
        self.assertEqual(best_center, tuple(points[0]))
        # 示意图用全屏坐标画圆：最佳候选圆环上必须有像素（draw 只画圆环、不填中心）
        self.assertGreater(draw[best_center[1], best_center[0] + radius], 0)

    def test_returns_empty_points_without_candidate(self):
        """无候选：draw 全黑、points 为空数组。"""
        white, glow, redness = make_masks()

        draw, points = self._predict(white, glow, redness, None)

        self.assertEqual(0, len(points))
        self.assertEqual(0, int(draw.sum()))


class PredictInterfaceTest(unittest.TestCase):
    """predict：生产调用点消费的返回结构不变，只拿 'enemy' / 'item' 两个键。"""

    def _predict(self, circles):
        """同样打桩掩膜与霍夫圆，但走 predict() 的对外接口。"""
        white, glow, redness = make_masks()
        center = (500, 430)
        radius = 30
        if circles is not None:
            draw_white_ring(white, center, radius)
            fill_center_redness(redness, center, radius)
        with (
            patch.object(
                predict_module, "_enemy_masks", return_value=(white, glow, redness)
            ),
            patch.object(predict_module.cv2, "HoughCircles", return_value=circles),
            patch.object(predict_module, "CUS_LOGGER", Mock()),
        ):
            return predict_module.predict(SCREEN, enemy=True, item=False)

    def test_predict_enemy_only_returns_enemy_and_none_item(self):
        """enemy=True/item=False 且无候选：返回 {'enemy': None, 'item': None}。"""
        result = self._predict(None)

        self.assertEqual({"enemy", "item"}, set(result))
        self.assertIsNone(result["enemy"])
        self.assertIsNone(result["item"])  # item 分支未开启，保持 None

    def test_predict_returns_detected_center(self):
        """有候选：'enemy' 是检测到的全屏中心坐标，'item' 仍为 None。"""
        result = self._predict(hough_result([(500.0, 430.0, 30.0)]))

        self.assertEqual({"enemy", "item"}, set(result))
        self.assertEqual((500 + ROI_LEFT, 430 + ROI_TOP), result["enemy"])
        self.assertIsNone(result["item"])


class RealEnemyMasksTest(unittest.TestCase):
    """真实调用 _enemy_masks 的合成图用例（不 mock 掩膜构造）。

    前面的用例都 patch 了 _enemy_masks，只验证候选筛选逻辑；本类用纯色合成图验证
    「BGR 截图按 BGR 语义解析」这一层：BGR 纯红必须被当成红色光晕，BGR 纯蓝不允许，
    白色准星必须来自三通道都亮的像素。颜色序改错（把 BGR 当 RGB 送进 YUV、或取错通道）
    时这几个用例会直接失败。
    """

    ROI_CENTER = (700, 400)  # 准星 ROI 内相对坐标；全屏坐标是 (955, 495)
    FULL_CENTER = (ROI_CENTER[0] + ROI_LEFT, ROI_CENTER[1] + ROI_TOP)
    RING_RADIUS = 30
    GLOW_RADIUS = 40

    def test_bgr_red_pixels_become_red_glow(self):
        """BGR 纯红 (0,0,255)：必须进入红色光晕，且红色色度为正（证明用的是 R 通道）。"""
        image = blank_screen()
        draw_glow(image, (0, 0, 255), self.ROI_CENTER, self.GLOW_RADIUS)

        white, glow, redness = predict_module._enemy_masks(image)

        self.assertEqual((ROI_HEIGHT, ROI_WIDTH), white.shape)
        self.assertEqual(0, int(white.sum()))  # 纯红不是白色准星
        x, y = self.ROI_CENTER
        self.assertGreater(int(glow[y, x]), 0)
        self.assertGreater(int(redness[y, x]), 0)

    def test_bgr_blue_pixels_are_not_red_glow(self):
        """BGR 纯蓝 (255,0,0)：必须既不进光晕、中心色度也不为正（不能把蓝当红）。"""
        image = blank_screen()
        draw_glow(image, (255, 0, 0), self.ROI_CENTER, self.GLOW_RADIUS)

        white, glow, redness = predict_module._enemy_masks(image)

        x, y = self.ROI_CENTER
        self.assertEqual(0, int(white.sum()))
        self.assertEqual(0, int(glow.sum()))
        self.assertLessEqual(int(redness[y, x]), 0)

    def test_bright_ring_enters_white_mask(self):
        """细白圆环必须进入 white 掩膜；1 像素环经中值滤波后覆盖率仍应达标。"""
        image = blank_screen()
        draw_ring(image, self.ROI_CENTER, self.RING_RADIUS)

        white, glow, redness = predict_module._enemy_masks(image)

        self.assertEqual((ROI_HEIGHT, ROI_WIDTH), white.shape)
        self.assertGreater(int(np.count_nonzero(white)), 0)
        coverage = predict_module._ring_coverage(
            white, self.ROI_CENTER, self.RING_RADIUS
        )
        self.assertGreaterEqual(coverage, predict_module.AIM_ENEMY_RING_COVERAGE_MIN)
        # 白环本身只在 R 上高 10，达不到 20 的红色光晕阈值，不应产生 glow
        self.assertEqual(0, int(glow.sum()))

    def test_synthetic_crosshair_is_detected_end_to_end(self):
        """真实掩膜 + 打桩霍夫圆：红晕 + 白环的合成准星能被 enemy_candidates 检出。"""
        image = blank_screen()
        draw_glow(image, (0, 0, 255), self.ROI_CENTER, self.GLOW_RADIUS)
        draw_ring(image, self.ROI_CENTER, self.RING_RADIUS)
        circles = hough_result(
            [[
                float(self.ROI_CENTER[0]),
                float(self.ROI_CENTER[1]),
                float(self.RING_RADIUS),
            ]]
        )

        with patch.object(predict_module.cv2, "HoughCircles", return_value=circles):
            candidates = predict_module.enemy_candidates(image)
            draw, points = predict_module.predict_enemy(image)

        self.assertEqual(1, len(candidates))
        self.assertEqual(self.FULL_CENTER, candidates[0]["center"])
        self.assertEqual(self.RING_RADIUS, candidates[0]["radius"])
        self.assertGreaterEqual(
            candidates[0]["coverage"], predict_module.AIM_ENEMY_RING_COVERAGE_MIN
        )
        self.assertGreaterEqual(
            candidates[0]["center_red"], predict_module.AIM_ENEMY_CENTER_RED_MIN
        )
        self.assertEqual(self.FULL_CENTER, tuple(points[0]))
        self.assertEqual(image.shape[:2], draw.shape)


class PredictItemSmokeTest(unittest.TestCase):
    """predict_item 是开发中分支，这里只做不抛异常的冒烟测试。"""

    def test_predict_item_on_black_screen_returns_two_ndarrays(self):
        """全黑画面：没有青色光晕，返回 (draw, points) 两个 ndarray，不抛异常。"""
        draw, points = predict_module.predict_item(SCREEN)

        self.assertIsInstance(draw, np.ndarray)
        self.assertIsInstance(points, np.ndarray)
        self.assertEqual(SCREEN.shape[:2], draw.shape)
        self.assertEqual(0, points.shape[0])  # 全黑画面没有物品瞄准圈


if __name__ == "__main__":
    unittest.main()
