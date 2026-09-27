import unittest
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np

from tool.utils import minimap_util, mminimap


def _synthetic_arrow_minimap(coarse):
    """由粗筛图集截取箭头并合成 34x34 彩色小地图样本。

    Args:
        coarse: ArrowRotateMap 灰度图集，每 17x17 为一个角度模板。

    Returns:
        以 DIRECTION_ARROW_COLOR 着色的 34x34x3 小地图。
    """
    arrow = cv2.resize(coarse[34:51, 34:51], (68, 68), interpolation=cv2.INTER_LINEAR)
    shifted = cv2.warpAffine(
        arrow, np.float32([[1, 0, 1], [0, 1, 1]]), (68, 68),
        flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE,
    )
    alpha = cv2.resize(shifted, (34, 34), interpolation=cv2.INTER_AREA)
    color = np.array(minimap_util.DIRECTION_ARROW_COLOR, dtype=np.float32)
    return np.uint8(np.round(alpha[..., None] / 255 * color))


class MinimapTrackingTests(unittest.TestCase):
    def setUp(self):
        with patch.object(mminimap.PositionPredict, "set_now_map"):
            self.predictor = mminimap.PositionPredict((10.0, 20.0))
        self.predictor.scale = 1.0
        self.predictor.rotation = 30
        self.predictor.direction = 30
        self.predictor.rotation_confidence = 0.5
        self.predictor.direction_similarity = 0.5

    def test_same_frame_reuses_center_for_both_minimap_crops(self):
        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        with (
            patch.object(mminimap, "get_minimap_center", return_value=(138, 149)) as find_center,
            patch.object(mminimap, "get_minimap", return_value=frame[:34, :34]) as crop_map,
            patch.object(mminimap, "update_direction", return_value=(45.0, 0.7)),
            patch.object(mminimap, "update_rotation", return_value=(45, 0.6)),
        ):
            self.assertEqual(self.predictor.update_minimap_data(frame), (45, 45.0))

        find_center.assert_called_once_with(frame)
        self.assertEqual(crop_map.call_count, 2)
        self.assertTrue(all(call.kwargs["center"] == (138, 149) for call in crop_map.call_args_list))
        self.assertEqual(self.predictor.direction_similarity, 0.7)
        self.assertEqual(self.predictor.rotation_confidence, 0.6)

    def test_unreliable_direction_does_not_reuse_prior_heading(self):
        minimap = np.zeros((34, 34, 3), dtype=np.uint8)
        with patch.object(mminimap, "update_direction", return_value=(None, 0.0)):
            self.assertEqual(
                self.predictor.update_minimap_data(
                    rotation_minimap=minimap, direction_minimap=minimap
                ),
                (30, None),
            )
        self.assertIsNone(self.predictor.direction)
        self.assertEqual(self.predictor.direction_similarity, 0.0)
        self.assertEqual(self.predictor.rotation_confidence, 0.0)

    def test_zero_rotation_confidence_clears_direction_but_keeps_rotation(self):
        minimap = np.zeros((34, 34, 3), dtype=np.uint8)
        with (
            patch.object(mminimap, "update_direction", return_value=(45.0, 0.7)),
            patch.object(mminimap, "update_rotation", return_value=(123, 0.0)),
        ):
            result = self.predictor.update_minimap_data(
                rotation_minimap=minimap, direction_minimap=minimap
            )

        self.assertEqual(result, (123, None))
        self.assertEqual(self.predictor.rotation, 123)
        self.assertIsNone(self.predictor.direction)
        self.assertEqual(self.predictor.rotation_confidence, 0.0)
        self.assertEqual(self.predictor.direction_similarity, 0.7)

    def test_recognition_exception_invalidates_previous_heading(self):
        minimap = np.zeros((34, 34, 3), dtype=np.uint8)
        with patch.object(mminimap, "update_direction", side_effect=RuntimeError("atlas failed")):
            self.assertEqual(self.predictor.update_minimap_data(
                rotation_minimap=minimap, direction_minimap=minimap,
            ), (30, None))
        self.assertEqual(self.predictor.direction_similarity, 0)
        self.assertEqual(self.predictor.rotation_confidence, 0)

    def test_empty_arrow_and_flat_rotation_have_no_confidence(self):
        minimap = np.zeros((34, 34, 3), dtype=np.uint8)
        diagnostics = {}
        self.assertEqual(mminimap.update_direction(
            minimap=minimap, with_confidence=True, diagnostics=diagnostics,
        ), (None, 0.0))
        self.assertEqual(diagnostics, {"reason": "arrow_missing", "arrow_pixels": 0})
        self.assertEqual(minimap_util.peak_confidence(np.ones(186)), 0.0)
        _, confidence = mminimap.update_rotation(
            minimap=np.zeros((186, 186, 3), dtype=np.uint8), with_confidence=True
        )
        self.assertEqual(confidence, 0.0)




    def test_degraded_atlas_arrow_passes_but_color_noise_does_not(self):
        images = Path(__file__).resolve().parents[1] / "resource" / "imgs" / "gray_image"
        coarse = cv2.imread(str(images / "ArrowRotateMap.png"), cv2.IMREAD_GRAYSCALE)
        precise = cv2.imread(str(images / "ArrowRotateMapAll.png"), cv2.IMREAD_GRAYSCALE)
        minimap = _synthetic_arrow_minimap(coarse)
        color = np.array(minimap_util.DIRECTION_ARROW_COLOR, dtype=np.float32)
        noise = np.uint8(np.random.default_rng(6).random((34, 34, 1)) < 0.15) * color.astype(np.uint8)

        with (
            patch.object(mminimap, "ArrowRotateMap", coarse),
            patch.object(mminimap, "ArrowRotateMapAll", precise),
        ):
            direction, score = mminimap.update_direction(minimap=minimap, with_confidence=True)
            noise_direction, _ = mminimap.update_direction(minimap=noise, with_confidence=True)

        self.assertIsNotNone(direction)
        self.assertGreaterEqual(score, mminimap.DIRECTION_MIN_SIMILARITY)
        self.assertIsNone(noise_direction)

    def test_precise_similarity_below_threshold_rejects_direction(self):
        images = Path(__file__).resolve().parents[1] / "resource" / "imgs" / "gray_image"
        coarse = cv2.imread(str(images / "ArrowRotateMap.png"), cv2.IMREAD_GRAYSCALE)
        precise = cv2.imread(str(images / "ArrowRotateMapAll.png"), cv2.IMREAD_GRAYSCALE)
        minimap = _synthetic_arrow_minimap(coarse)

        # 粗筛保留真实箭头，精筛替换为无箭头的固定随机纹理，验证精筛
        # 自身拒绝低相关。翻转图集仍含有效箭头，不能作为低相关负例。
        noise = np.random.default_rng(6).integers(0, 256, precise.shape, dtype=np.uint8)
        diagnostics = {}
        with (
            patch.object(mminimap, "ArrowRotateMap", coarse),
            patch.object(mminimap, "ArrowRotateMapAll", noise),
        ):
            direction, score = mminimap.update_direction(
                minimap=minimap, with_confidence=True, diagnostics=diagnostics,
            )

        self.assertIsNone(direction)
        self.assertEqual(diagnostics["reason"], "arrow_precise")
        self.assertGreater(diagnostics["coarse_score"], mminimap.DIRECTION_MIN_SIMILARITY)
        self.assertGreater(score, 0.0)
        self.assertLess(score, mminimap.DIRECTION_MIN_SIMILARITY)

    def test_stall_confidence(self):
        # 2026-09-27 实机停滞帧，仅保留 34x34 箭头裁剪。旧实现误取精筛
        # 候选范围外的滤波边缘峰，分别以 0.264/0.272 拒绝清晰箭头。
        images = Path(__file__).resolve().parents[1] / "resource" / "imgs" / "gray_image"
        fixtures = Path(__file__).parent / "fixtures" / "minimap"
        coarse = cv2.imread(str(images / "ArrowRotateMap.png"), cv2.IMREAD_GRAYSCALE)
        precise = cv2.imread(str(images / "ArrowRotateMapAll.png"), cv2.IMREAD_GRAYSCALE)
        for name, expected in (("arrow_4k_115.png", 115), ("arrow_4k_107.png", 107)):
            with (
                self.subTest(name=name),
                patch.object(mminimap, "ArrowRotateMap", coarse),
                patch.object(mminimap, "ArrowRotateMapAll", precise),
            ):
                arrow = cv2.imread(str(fixtures / name))
                self.assertIsNotNone(arrow)
                diagnostics = {}
                direction, score = mminimap.update_direction(
                    minimap=arrow, with_confidence=True, diagnostics=diagnostics,
                )
                self.assertIsNotNone(direction)
                self.assertLess(abs((direction - expected + 180) % 360 - 180), 3)
                self.assertGreater(score, 0.95)
                self.assertEqual(diagnostics["reason"], "ok")

    def test_low_position_similarity_does_not_change_search_origin(self):
        state = minimap_util.PositionPredictState(
            sim=0.005, precise_sim=0.005, global_loca=(100.0, 200.0)
        )
        with (
            patch.object(mminimap, "deal_minimap", return_value=np.zeros((8, 8), dtype=np.uint8)),
            patch.object(self.predictor, "_predict_position", return_value=state),
            patch.object(mminimap, "_predict_precise_position", return_value=state),
        ):
            position, similarity = self.predictor.update_position(
                np.zeros((8, 8), dtype=np.uint8), scale_list=[1.2]
            )

        self.assertEqual(position, (100.0, 200.0))
        self.assertEqual(similarity, 0.005)
        self.assertEqual(self.predictor.position, (10.0, 20.0))
        self.assertEqual(self.predictor.scale, 1.0)

        state.sim = 0.2
        state.precise_sim = 0.2
        with (
            patch.object(mminimap, "deal_minimap", return_value=np.zeros((8, 8), dtype=np.uint8)),
            patch.object(self.predictor, "_predict_position", return_value=state),
            patch.object(mminimap, "_predict_precise_position", return_value=state),
        ):
            self.predictor.update_position(np.zeros((8, 8), dtype=np.uint8), scale_list=[1.2])
        self.assertEqual(self.predictor.position, (100.0, 200.0))
        self.assertEqual(self.predictor.scale, 1.2)





class PeakConfidenceTests(unittest.TestCase):
    """固定峰值显著性语义：无峰为零，单峰为一，多峰取相对差。"""

    def test_single_peak_returns_full_confidence(self):
        arr = np.zeros(120, dtype=np.float64)
        arr[60] = 100.0
        self.assertEqual(minimap_util.peak_confidence(arr), 1.0)

    def test_no_peak_returns_zero(self):
        self.assertEqual(minimap_util.peak_confidence(np.zeros(120)), 0.0)

    def test_two_peaks_return_relative_gap(self):
        arr = np.zeros(120, dtype=np.float64)
        arr[30] = 100.0
        arr[90] = 60.0
        self.assertAlmostEqual(minimap_util.peak_confidence(arr), 0.4)


if __name__ == "__main__":
    unittest.main()
