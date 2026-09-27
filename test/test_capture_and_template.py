import ctypes
import unittest
from threading import Event, Thread
from unittest.mock import patch

import cv2
import numpy as np

from tool import screenshot
from tool.utils.image_tool import match_template_soft


class FakeFunction:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def __call__(self, *args):
        self.calls.append(args)
        return self.result(*args) if callable(self.result) else self.result


class FakeGdi:
    def __init__(self, frames, bitblt=1, bitmap=303):
        self.frames = iter(frames)
        self.selected = 404
        self.CreateCompatibleDC = FakeFunction(202)
        self.CreateCompatibleBitmap = FakeFunction(bitmap)
        self.SelectObject = FakeFunction(self._select_object)
        self.DeleteObject = FakeFunction(lambda obj: int(obj != self.selected))
        self.DeleteDC = FakeFunction(1)
        self.BitBlt = FakeFunction(bitblt)
        self.GetDIBits = FakeFunction(self._get_bits)

    def _select_object(self, dc, obj):
        previous = self.selected
        self.selected = obj
        return previous

    def _get_bits(self, dc, bmp, start, lines, data, bmi, usage):
        # GetDIBits 的前提是截图位图已从内存 DC 取消选择。
        assert self.selected == 404
        frame = next(self.frames)
        ctypes.memmove(data, frame.tobytes(), frame.nbytes)
        return frame.shape[0]


class ScreenTests(unittest.TestCase):
    def make_screen(self, frames, **kwargs):
        gdi = FakeGdi(frames, **kwargs)
        user32 = type("FakeUser32", (), {})()
        user32.GetWindowDC = FakeFunction(101)
        user32.ReleaseDC = FakeFunction(1)
        def dll(name):
            return gdi if name == "gdi32" else user32
        return gdi, user32, patch.object(screenshot.ctypes, "WinDLL", side_effect=dll, create=True)

    def test_scaled_frame_matches_previous_pixels_and_owns_its_data(self):
        rng = np.random.default_rng(17)
        first = rng.integers(0, 256, (8, 8, 4), dtype=np.uint8)
        second = rng.integers(0, 256, (8, 8, 4), dtype=np.uint8)
        gdi, user32, dll_patch = self.make_screen([first, second])
        with dll_patch:
            screen = screenshot.Screen(8, 8, 4, 4)
            one = screen.grab(0, 0)
            expected = cv2.resize(first[:, :, :3], (4, 4), interpolation=cv2.INTER_AREA)
            np.testing.assert_array_equal(one, expected)
            two = screen.grab(0, 0)
            np.testing.assert_array_equal(one, expected)
            self.assertFalse(np.shares_memory(one, two))
            screen.close()
            screen.close()
        self.assertEqual(len(gdi.DeleteObject.calls), 1)
        self.assertEqual(len(gdi.DeleteDC.calls), 1)
        self.assertEqual(len(user32.ReleaseDC.calls), 1)
        self.assertEqual(gdi.SelectObject.calls[-1], (202, 404))

    def test_4k_capture_is_normalized_to_1080p(self):
        raw = np.full((2160, 3840, 4), 77, dtype=np.uint8)
        raw[100:140, 200:260, :3] = [12, 33, 199]
        gdi, _, dll_patch = self.make_screen([raw])
        with dll_patch:
            screen = screenshot.Screen(3840, 2160, 1920, 1080)
            frame = screen.grab(100, 80)
            screen.close()
        self.assertEqual(frame.shape, (1080, 1920, 3))
        np.testing.assert_array_equal(frame[50, 100], [12, 33, 199])
        self.assertEqual(gdi.BitBlt.calls[0][3:5], (3840, 2160))
        self.assertEqual(gdi.BitBlt.calls[0][6:8], (100, 80))

    def test_unscaled_frame_owns_its_data(self):
        first = np.full((3, 4, 4), 12, dtype=np.uint8)
        second = np.full((3, 4, 4), 77, dtype=np.uint8)
        _, _, dll_patch = self.make_screen([first, second])
        with dll_patch:
            screen = screenshot.Screen(4, 3)
            one = screen.grab(0, 0)
            screen.grab(0, 0)
            np.testing.assert_array_equal(one, first[:, :, :3])
            screen.close()





    def test_bitblt_failure_is_reported_without_stale_frame(self):
        gdi, _, dll_patch = self.make_screen([], bitblt=0)
        with dll_patch, patch.object(screenshot.time, "sleep"):
            screen = screenshot.Screen(4, 3)
            with self.assertRaisesRegex(RuntimeError, "BitBlt"):
                screen.grab(0, 0)
            self.assertEqual(len(gdi.GetDIBits.calls), 0)
            screen.close()

    def test_getdibits_failure_is_reported(self):
        gdi, _, dll_patch = self.make_screen([])
        gdi.GetDIBits = FakeFunction(0)
        with dll_patch, patch.object(screenshot.time, "sleep"):
            screen = screenshot.Screen(4, 3)
            with self.assertRaisesRegex(RuntimeError, "GetDIBits"):
                screen.grab(0, 0)
            self.assertEqual(len(gdi.GetDIBits.calls), 10)
            screen.close()

    def test_partial_initialization_releases_acquired_handles(self):
        gdi, user32, dll_patch = self.make_screen([], bitmap=0)
        with dll_patch:
            with self.assertRaisesRegex(RuntimeError, "位图"):
                screenshot.Screen(4, 3)
        self.assertEqual(len(gdi.DeleteDC.calls), 1)
        self.assertEqual(len(user32.ReleaseDC.calls), 1)

    def test_failed_restore_keeps_bitmap_and_dc_for_retry(self):
        gdi, user32, dll_patch = self.make_screen([])
        restore_attempts = 0

        def select(dc, obj):
            nonlocal restore_attempts
            if obj == 303:
                return gdi._select_object(dc, obj)
            restore_attempts += 1
            return 0 if restore_attempts == 1 else gdi._select_object(dc, obj)

        gdi.SelectObject.result = select
        with dll_patch:
            screen = screenshot.Screen(4, 3)
            screen.close()
            self.assertEqual((screen.oldbmp, screen.bmp, screen.memdc), (404, 303, 202))
            self.assertEqual(len(gdi.DeleteObject.calls), 0)
            self.assertEqual(len(gdi.DeleteDC.calls), 0)
            self.assertEqual(len(user32.ReleaseDC.calls), 1)
            with self.assertRaisesRegex(RuntimeError, "已关闭"):
                screen.grab(0, 0)
            screen.close()
            self.assertIsNone(screen.bmp)
            self.assertIsNone(screen.memdc)
            self.assertEqual(len(gdi.DeleteObject.calls), 1)
            self.assertEqual(len(gdi.DeleteDC.calls), 1)

    def test_capture_restore_failure_closes_capture_and_releases_handles(self):
        frame = np.full((3, 4, 4), 12, dtype=np.uint8)
        gdi, user32, dll_patch = self.make_screen([frame])
        with dll_patch:
            screen = screenshot.Screen(4, 3)

            def select(dc, obj):
                if obj == 303:
                    return 0
                return gdi._select_object(dc, obj)

            gdi.SelectObject.result = select
            with self.assertRaisesRegex(RuntimeError, "恢复截图"):
                screen.grab(0, 0)
            with self.assertRaisesRegex(RuntimeError, "已关闭"):
                screen.grab(0, 0)
            screen.close()
            screen.close()
        self.assertEqual(gdi.selected, 404)
        self.assertIsNone(screen.bmp)
        self.assertIsNone(screen.memdc)
        self.assertEqual(len(gdi.BitBlt.calls), 1)
        self.assertEqual(len(gdi.DeleteObject.calls), 1)
        self.assertEqual(len(gdi.DeleteDC.calls), 1)
        self.assertEqual(len(user32.ReleaseDC.calls), 1)

    def test_partial_frame_is_retried_and_only_complete_pixels_are_returned(self):
        partial = np.full((2, 4, 4), 12, dtype=np.uint8)
        complete = np.full((3, 4, 4), 77, dtype=np.uint8)
        gdi, _, dll_patch = self.make_screen([partial, complete])
        with dll_patch, patch.object(screenshot.time, "sleep"):
            screen = screenshot.Screen(4, 3)
            result = screen.grab(10, 20)
            screen.close()
        np.testing.assert_array_equal(result, complete[:, :, :3])
        self.assertEqual(len(gdi.GetDIBits.calls), 2)


    def test_close_waits_for_inflight_capture(self):
        entered = Event()
        release = Event()
        closing = Event()
        closed = Event()
        results = []
        frame = np.full((3, 4, 4), 77, dtype=np.uint8)

        def bitblt(*args):
            entered.set()
            if not release.wait(2):
                raise RuntimeError("测试截图未释放")
            return 1

        gdi, _, dll_patch = self.make_screen([frame], bitblt=bitblt)
        with dll_patch:
            screen = screenshot.Screen(4, 3)

            def capture():
                try:
                    results.append(screen.grab(0, 0))
                except Exception as exc:
                    results.append(exc)

            def close():
                closing.set()
                screen.close()
                closed.set()

            capture_thread = Thread(target=capture)
            close_thread = Thread(target=close)
            capture_thread.start()
            try:
                self.assertTrue(entered.wait(1))
                close_thread.start()
                self.assertTrue(closing.wait(1))
                self.assertFalse(closed.wait(0.02))
                self.assertEqual(len(gdi.DeleteObject.calls), 0)
            finally:
                release.set()
                capture_thread.join(2)
                if close_thread.ident is not None:
                    close_thread.join(2)
                screen.close()
            self.assertFalse(capture_thread.is_alive())
            self.assertFalse(close_thread.is_alive())
        self.assertEqual(len(results), 1)
        np.testing.assert_array_equal(results[0], frame[:, :, :3])
        self.assertIsNone(screen.bmp)
        self.assertIsNone(screen.memdc)


class SoftTemplateCacheTests(unittest.TestCase):
    @staticmethod
    def original_match(image, target, method):
        result = cv2.matchTemplate(image, target, method)
        h, w = target.shape[:2]
        for dx in np.arange(-0.5, 0.51, 0.25):
            for dy in np.arange(-0.5, 0.51, 0.25):
                if dx == 0 and dy == 0:
                    continue
                shifted = cv2.warpAffine(
                    target, np.float32([[1, 0, dx], [0, 1, dy]]), (w, h),
                    flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE,
                )
                np.maximum(result, cv2.matchTemplate(image, shifted, method), out=result)
        return result

    def test_repeated_and_mutated_templates_keep_full_response(self):
        rng = np.random.default_rng(7)
        image = rng.integers(0, 256, (42, 48, 3), dtype=np.uint8)
        target = image[12:23, 20:32].copy()
        for method in (cv2.TM_CCORR_NORMED, cv2.TM_CCOEFF_NORMED):
            expected = self.original_match(image, target, method)
            for _ in range(2):
                np.testing.assert_array_equal(
                    match_template_soft(image, target.copy(), True, method), expected
                )
            peak = cv2.matchTemplate(image, target, method).max()
            np.testing.assert_array_equal(
                match_template_soft(image, target, True, method, threshold=peak + 0.05),
                expected,
            )
            target[2, 3, 1] = (int(target[2, 3, 1]) + 71) % 256
            np.testing.assert_array_equal(
                match_template_soft(image, target, True, method),
                self.original_match(image, target, method),
            )


if __name__ == "__main__":
    unittest.main()
