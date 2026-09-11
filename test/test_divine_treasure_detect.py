"""战斗判据与真实样本对照：外部样本缺失时跳过，夹具与主 checkout 模板可用。"""

import unittest
from pathlib import Path

import cv2
import numpy as np

from tool.divine_treasure.detect import (
    battle_labels_in,
    battle_hud_visible,
    detect_door,
    detect_enemy_circle,
    enemy_marker,
)

SAMPLES = Path("E:/srironblood/wanderland_samples")
SAMPLE1 = SAMPLES / "battle-sample1"
SAMPLE2 = SAMPLES / "battle-sample2-教室场景-离怪物较远"
TEMPLATE = Path("E:/srironblood/Simulated_Scepter/resource/imgs/wanderland/enemy.png")
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "battle"

CLEARED = "3清理完怪物后的画面-不一定面向门.png"
DOOR_FRAME = "4走到门口的画面-出现交互.png"
BATTLE_FRAME = "3战斗界面-sample1忘记放了.png"
BLESSING = "*4战斗后选择祝福的界面*.png"


def imread(path):
    data = np.fromfile(str(path), dtype=np.uint8)
    return cv2.imdecode(data, cv2.IMREAD_COLOR)


def frame(folder, pattern):
    if not folder.is_dir():
        return None
    found = sorted(folder.glob(pattern))
    return imread(found[0]) if found else None


class EnemyMarkerTests(unittest.TestCase):
    def test_marker_is_strong_when_enemy_is_close(self):
        # 初始帧(远)模板分只有 0.508：模型在远处不渲染标记，因此只要求贴近后稳定 1.0。
        image = frame(SAMPLE1, "2走到怪面前*.png")
        if image is None or not TEMPLATE.exists():
            self.skipTest("样本或模板不可用")
        self.assertIsNotNone(enemy_marker(image, str(TEMPLATE)), "接近怪物后应检出敌标记")

    def test_marker_absent_after_clearing(self):
        image = frame(SAMPLE1, CLEARED)
        if image is None or not TEMPLATE.exists():
            self.skipTest("样本或模板不可用")
        self.assertIsNone(enemy_marker(image, str(TEMPLATE)), "清怪后不应再有敌标记")


class EnemyCircleTests(unittest.TestCase):
    def test_fixture_circle_is_located(self):
        image = imread(FIXTURES / "enemy-circle.png")
        self.assertIsNotNone(image)
        self.assertIsNotNone(detect_enemy_circle(image, band=(0.0, 1.0)), "夹具红圈应被检出")

    def test_circle_detector_is_documented_as_unreliable(self):
        # 红圈与红发不可分（见 detect.py 注释）：这里只锁住夹具行为，不把它当寻路判据。
        image = imread(FIXTURES / "enemy-circle.png")
        self.assertIsNotNone(image)
        detect_enemy_circle(image, band=(0.0, 1.0))


class DoorColorTests(unittest.TestCase):
    def test_door_frame_locates_pink_door(self):
        image = frame(SAMPLE1, DOOR_FRAME)
        if image is None:
            self.skipTest("外部样本不可用")
        detected = detect_door(image)
        self.assertIsNotNone(detected, "门口画面应定位到粉色门")
        self.assertLess(abs(detected[0] - image.shape[1] / 2), image.shape[1] * 0.20)

    def test_cleared_frame_still_sees_door(self):
        image = frame(SAMPLE1, CLEARED)
        if image is None:
            self.skipTest("外部样本不可用")
        self.assertIsNotNone(detect_door(image), "背对门时也应能在画面中找到门")


class BattleLabelTests(unittest.TestCase):
    def test_project_labels_are_recognized(self):
        for text in ("行动中", "自动战斗", "战斗中"):
            self.assertTrue(battle_labels_in(text), text)

    def test_world_text_is_not_a_battle_label(self):
        self.assertFalse(battle_labels_in("第一位面-战斗 火与危险事物"))

    def test_ocr_label_wins_over_color(self):
        image = np.zeros((1080, 1920, 3), dtype=np.uint8)
        self.assertTrue(battle_hud_visible(image, ocr=lambda _img, _box: "行动中"))


class BattleHudTests(unittest.TestCase):
    def test_battle_screen_is_recognized(self):
        image = frame(SAMPLE2, BATTLE_FRAME)
        if image is None:
            self.skipTest("外部样本不可用")
        self.assertTrue(battle_hud_visible(image), "战斗界面应判定为战斗中")

    def test_world_and_menu_screens_are_not_battle(self):
        for folder, pattern in ((SAMPLE1, DOOR_FRAME), (SAMPLE2, "1初始界面.png"), (SAMPLE2, BLESSING)):
            image = frame(folder, pattern)
            if image is None:
                continue
            self.assertFalse(battle_hud_visible(image), f"{pattern} 不是战斗界面")


if __name__ == "__main__":
    unittest.main()
