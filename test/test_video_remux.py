"""验证分片 MP4 转封装：不重编码、就地替换、失败时保留原文件。"""

import glob
import os
import threading
import time
import unittest

import av
import numpy as np

from tool.window_recorder.recorder_writer import RecorderWriter
from tool.window_recorder.video_remux import (
    TEMP_SUFFIX,
    convert_in_background,
    convert_to_standard_mp4,
    convert_with_tail_trimmed,
    needs_conversion,
)

TEMP_PREFIX = ".remux-test-"
WIDTH, HEIGHT, FPS = 320, 240, 30


def make_frame(index):
    gradient = np.linspace(0, 255, WIDTH, dtype=np.float32)
    row = np.tile(gradient, (HEIGHT, 1)).astype(np.uint8)
    base = np.dstack([row, np.roll(row, 20, 1), np.roll(row, 40, 1)])
    band = (index * 5) % HEIGHT
    base[band:band + 30, :, :] = 240 - base[band:band + 30, :, :] // 2
    return base


def top_level_boxes(path, limit=8):
    found, total, offset = [], os.path.getsize(path), 0
    with open(path, "rb") as file:
        while offset + 8 <= total and len(found) < limit:
            file.seek(offset)
            header = file.read(8)
            if len(header) < 8:
                break
            size = int.from_bytes(header[:4], "big")
            found.append(header[4:8].decode("ascii", "replace"))
            if size == 0:
                break
            offset += size
    return found


def decode_count(path):
    with av.open(path) as container:
        return sum(1 for _ in container.decode(video=0))


class VideoRemuxTests(unittest.TestCase):
    def setUp(self):
        self.test_dir = os.path.dirname(os.path.abspath(__file__))

    def tearDown(self):
        for path in glob.glob(os.path.join(self.test_dir, f"{TEMP_PREFIX}*")):
            try:
                os.remove(path)
            except OSError:
                pass

    def new_path(self, name):
        return os.path.join(self.test_dir, f"{TEMP_PREFIX}{name}")

    def make_recording(self, name, frames=FPS * 3):
        """产出一份分片 MP4 录像。"""
        path = self.new_path(name)
        writer = RecorderWriter(path, WIDTH, HEIGHT, FPS)
        for index in range(frames):
            writer.write(make_frame(index))
        self.assertTrue(writer.stop())
        return path

    def test_converts_fragmented_recording_to_standard_mp4(self):
        path = self.make_recording("normal.mp4")
        self.assertIn("moof", top_level_boxes(path))
        frames_before = decode_count(path)

        self.assertTrue(convert_to_standard_mp4(path))

        boxes = top_level_boxes(path)
        # 分片消失，变成带完整样本表的普通 mp4
        self.assertNotIn("moof", boxes)
        self.assertIn("moov", boxes)
        # 不重新编码：帧数与内容都不变
        self.assertEqual(decode_count(path), frames_before)
        self.assertFalse(os.path.exists(path + TEMP_SUFFIX))

    def test_keeps_original_when_source_missing(self):
        path = self.new_path("missing.mp4")

        self.assertFalse(convert_to_standard_mp4(path))
        self.assertFalse(os.path.exists(path))

    def test_keeps_original_when_conversion_fails(self):
        # 非视频文件：转封装必然失败，原文件必须原样保留
        path = self.new_path("notavideo.mp4")
        with open(path, "wb") as file:
            file.write(b"this is not a video")

        self.assertFalse(convert_to_standard_mp4(path))

        self.assertTrue(os.path.exists(path))
        with open(path, "rb") as file:
            self.assertEqual(file.read(), b"this is not a video")
        self.assertFalse(os.path.exists(path + TEMP_SUFFIX))

    def test_strict_mode_keeps_killed_recording_untouched(self):
        # 标准流程（UI 手动转换的默认）：校验源文件，尾部残缺时不转换，交给用户决定
        path = self.make_recording("killed-strict.mp4", frames=FPS * 6)
        full = os.path.getsize(path)
        with open(path, "r+b") as file:
            file.truncate(int(full * 0.55))
        truncated = os.path.getsize(path)

        self.assertFalse(convert_to_standard_mp4(path, check_source=True, check_output=True))

        self.assertEqual(os.path.getsize(path), truncated)
        self.assertIn("moof", top_level_boxes(path))

    def test_rescue_mode_converts_or_keeps_original(self):
        # 抢救模式尽力把可复用的包封装出去。截断落在不同位置时可能连复用都无法完成，
        # 那就必须保留原文件。两种结果都可接受，但绝不能丢数据或留下临时文件。
        path = self.make_recording("killed-rescue.mp4", frames=FPS * 6)
        full = os.path.getsize(path)
        with open(path, "r+b") as file:
            file.truncate(int(full * 0.55))
        truncated_size = os.path.getsize(path)

        converted = convert_to_standard_mp4(path, check_source=False, check_output=False)

        self.assertFalse(os.path.exists(path + TEMP_SUFFIX))
        boxes = top_level_boxes(path)
        if converted:
            self.assertNotIn("moof", boxes)
            self.assertIn("moov", boxes)
        else:
            # 无法抢救：原分片文件原样保留
            self.assertEqual(os.path.getsize(path), truncated_size)
            self.assertIn("moof", boxes)

    def test_auto_conversion_skips_checks(self):
        # 录制正常结束时写入器已收尾，文件结构完整，两个校验都关掉也应转换成功
        path = self.make_recording("auto.mp4")
        frames_before = decode_count(path)

        self.assertTrue(convert_to_standard_mp4(
            path, check_source=False, check_output=False))

        self.assertNotIn("moof", top_level_boxes(path))
        self.assertEqual(decode_count(path), frames_before)

    def test_standard_flow_agrees_on_healthy_recording(self):
        for check_source, check_output in ((True, True), (False, False), (True, False)):
            with self.subTest(check_source=check_source, check_output=check_output):
                path = self.make_recording(f"healthy-{check_source}-{check_output}.mp4")
                frames_before = decode_count(path)

                self.assertTrue(convert_to_standard_mp4(
                    path, check_source=check_source, check_output=check_output))

                self.assertNotIn("moof", top_level_boxes(path))
                self.assertEqual(decode_count(path), frames_before)

    def test_keeps_original_when_target_cannot_be_replaced(self):
        # 文件仍被占用（例如别处还开着句柄）时不能丢数据
        path = self.make_recording("locked.mp4")
        size_before = os.path.getsize(path)
        holder = open(path, "rb")
        self.addCleanup(holder.close)

        self.assertFalse(convert_to_standard_mp4(path))

        self.assertEqual(os.path.getsize(path), size_before)

    def test_background_conversion_returns_immediately(self):
        path = self.make_recording("background.mp4")
        results = []

        start = time.perf_counter()
        thread = convert_in_background(path, on_finished=results.append)
        返回耗时 = time.perf_counter() - start
        thread.join(timeout=30)

        # 调用方不应被转换阻塞
        self.assertLess(返回耗时, 0.5)
        self.assertEqual(results, [True])
        self.assertNotIn("moof", top_level_boxes(path))

    def test_background_conversion_reports_failure(self):
        results = []
        thread = convert_in_background(self.new_path("missing2.mp4"), on_finished=results.append)
        thread.join(timeout=30)

        self.assertEqual(results, [False])


    def test_needs_conversion_detects_fragmented_only(self):
        # 分片格式需要封装；封装成标准 mp4 之后不再需要
        path = self.make_recording("detect.mp4")
        self.assertTrue(needs_conversion(path))

        self.assertTrue(convert_to_standard_mp4(path))

        self.assertFalse(needs_conversion(path))

    def test_needs_conversion_ignores_non_video(self):
        path = self.new_path("notvideo.mp4")
        with open(path, "wb") as file:
            file.write(b"not a video at all")
        self.assertFalse(needs_conversion(path))

    def test_strict_trim_writes_target_and_keeps_source(self):
        # UI 的严格模式：输出到「原文件名-严格模式.mp4」，原文件保留
        path = self.make_recording("strict-src.mp4", frames=FPS * 6)
        target = self.new_path("strict-out.mp4")
        self.addCleanup(lambda: os.path.exists(target) and os.remove(target))

        self.assertTrue(convert_with_tail_trimmed(path, target, del_frames=False))

        self.assertTrue(os.path.exists(path))
        self.assertTrue(needs_conversion(path))
        self.assertTrue(os.path.exists(target))
        self.assertNotIn("moof", top_level_boxes(target))
        self.assertGreater(decode_count(target), 0)
        self.assertFalse(os.path.exists(target + TEMP_SUFFIX))

    def test_strict_trim_removes_undecodable_tail(self):
        # 严格模式的意义：末尾坏帧被丢弃，产物解码干净。
        # 写入器按背压可能丢帧，帧数太少时截断后可能整段都解不出来——
        # 那属于合法失败（保留原文件），因此两种结果都接受，但各自的约束都要满足。
        path = self.make_recording("strict-broken.mp4", frames=FPS * 6)
        full = os.path.getsize(path)
        with open(path, "r+b") as file:
            file.truncate(int(full * 0.55))
        target = self.new_path("strict-broken-out.mp4")
        self.addCleanup(lambda: os.path.exists(target) and os.remove(target))
        source_before = os.path.getsize(path)

        converted = convert_with_tail_trimmed(path, target, del_frames=False)

        # 源文件始终保留且内容不变
        self.assertTrue(os.path.exists(path))
        self.assertEqual(os.path.getsize(path), source_before)

        if converted:
            self.assertTrue(os.path.exists(target))
            self.assertNotIn("moof", top_level_boxes(target))
            with av.open(target) as container:
                self.assertGreater(sum(1 for _ in container.decode(video=0)), 0)
        else:
            # 失败时不能留下半成品
            self.assertFalse(os.path.exists(target))
            self.assertFalse(os.path.exists(target + TEMP_SUFFIX))

    def test_rescue_mode_writes_target_and_keeps_source(self):
        # UI 的抢救模式：接受尾部损坏，输出到新文件，原文件保留
        path = self.make_recording("rescue-src.mp4", frames=FPS * 6)
        full = os.path.getsize(path)
        with open(path, "r+b") as file:
            file.truncate(int(full * 0.55))
        target = self.new_path("rescue-out.mp4")
        self.addCleanup(lambda: os.path.exists(target) and os.remove(target))

        converted = convert_to_standard_mp4(
            path, check_source=False, check_output=False, target=target)

        self.assertTrue(os.path.exists(path))
        if converted:
            self.assertTrue(os.path.exists(target))
            self.assertNotIn("moof", top_level_boxes(target))
        else:
            self.assertFalse(os.path.exists(target))

    def test_rescue_mode_never_touches_source(self):
        # 即便转换成功，原文件也必须原样保留（UI 要求不删除原文件）
        path = self.make_recording("rescue-keep.mp4")
        size_before = os.path.getsize(path)
        target = self.new_path("rescue-keep-out.mp4")
        self.addCleanup(lambda: os.path.exists(target) and os.remove(target))

        self.assertTrue(convert_to_standard_mp4(
            path, check_source=False, check_output=False, target=target))

        self.assertEqual(os.path.getsize(path), size_before)
        self.assertTrue(needs_conversion(path))

    def test_concurrent_conversion_of_same_file_is_serialized(self):
        # 两次任务结束间隔很短时，上一次转封装可能还没结束。同一路径并发转换会
        # 共用同一个临时文件而互相覆盖，必须串行化：只允许一个真正执行。
        path = self.make_recording("concurrent.mp4", frames=FPS * 6)
        results = []
        lock = threading.Lock()

        def run():
            outcome = convert_to_standard_mp4(path)
            with lock:
                results.append(outcome)

        threads = [threading.Thread(target=run) for _ in range(3)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=60)

        # 全部返回成功（后两个把工作交给正在进行的那个），且没有异常逃逸
        self.assertEqual(sorted(results), [True, True, True])
        self.assertNotIn("moof", top_level_boxes(path))
        self.assertFalse(os.path.exists(path + TEMP_SUFFIX))
        self.assertGreater(decode_count(path), 0)


if __name__ == "__main__":
    unittest.main()
