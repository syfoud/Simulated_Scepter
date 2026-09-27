"""真实次数裁剪、历史模板及空白输入的识别回归。"""

import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np

from tool.utils import ocr_num

ROOT = Path(__file__).resolve().parents[1]


class ActionCountSamplesTests(unittest.TestCase):
    def recognize(self, crop, directory):
        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        frame[707:740, 1660:1700] = crop
        return ocr_num.match_roll_count_in_region(frame, unmatched_dir=directory)

    def test_retained_failure_crops_recover_at_existing_threshold(self):
        samples = sorted((ROOT / 'test/fixtures/action_count').glob('*.png'))
        self.assertEqual(len(samples), 25, "应完整保留已标注的 25 张数字裁剪")
        with tempfile.TemporaryDirectory() as directory:
            for path in samples:
                with self.subTest(sample=path.name):
                    crop = cv2.imread(str(path))
                    self.assertEqual(self.recognize(crop, directory), int(path.stem.split('_')[0]))

    def test_existing_and_new_templates_keep_their_labels(self):
        with tempfile.TemporaryDirectory() as directory:
            for path in sorted((ROOT / 'resource/imgs/roll_count_num').glob('*.png')):
                with self.subTest(template=path.name):
                    crop = cv2.imread(str(path))
                    self.assertEqual(self.recognize(crop, directory), int(path.stem.split('_')[0]))

    def test_empty_and_noise_crops_remain_unrecognized(self):
        rng = np.random.default_rng(27)
        with tempfile.TemporaryDirectory() as directory:
            for crop in (np.zeros((33, 40, 3), dtype=np.uint8),
                         rng.integers(0, 256, (33, 40, 3), dtype=np.uint8)):
                self.assertIsNone(self.recognize(crop, directory))


if __name__ == '__main__':
    unittest.main()
