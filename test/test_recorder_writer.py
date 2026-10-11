"""验证录像写入器：分片 MP4 可播、队列满时丢弃而不阻塞、可重复停止。

这里使用真实的 PyAV 与真实帧数据，因为被验证的正是编码与落盘行为本身。
"""

import glob
import os
import subprocess
import time
import unittest

import numpy as np

from tool.window_recorder.recorder_writer import FRAME_QUEUE_SIZE, RecorderWriter

TEMP_PREFIX = ".writer-test-"
WIDTH, HEIGHT, FPS = 320, 240, 30


def make_frame(index):
    """生成一帧可压缩的画面，index 决定平移量。"""
    gradient = np.linspace(0, 255, WIDTH, dtype=np.float32)
    row = np.tile(gradient, (HEIGHT, 1)).astype(np.uint8)
    shift = (index * 4) % WIDTH
    return np.dstack([np.roll(row, shift, axis=1),
                      np.roll(row, shift + 20, axis=1),
                      np.roll(row, shift + 40, axis=1)])


def top_level_boxes(path, limit=12):
    """列出顶层 ISO BMFF box 顺序，用于确认 moov 在文件开头。"""
    found = []
    total = os.path.getsize(path)
    offset = 0
    with open(path, "rb") as file:
        while offset + 8 <= total and len(found) < limit:
            file.seek(offset)
            header = file.read(8)
            if len(header) < 8:
                break
            box_size = int.from_bytes(header[:4], "big")
            found.append(header[4:8].decode("ascii", "replace"))
            if box_size == 0:
                break
            offset += box_size
    return found


def decode_frame_count(path):
    """解码整个文件并返回成功解出的帧数，用于确认内容真的可读。"""
    import av

    count = 0
    with av.open(path) as container:
        for frame in container.decode(video=0):
            count += 1
    return count


class RecorderWriterTests(unittest.TestCase):
    def setUp(self):
        self.test_dir = os.path.dirname(os.path.abspath(__file__))
        self.writers = []

    def tearDown(self):
        # 写入器必须关闭，否则 Windows 仍锁定文件；失败路径也要保证收尾。
        for writer in self.writers:
            try:
                writer.stop()
            except Exception:
                pass
        for path in glob.glob(os.path.join(self.test_dir, f"{TEMP_PREFIX}*")):
            try:
                os.remove(path)
            except OSError:
                pass

    def new_path(self, name):
        return os.path.join(self.test_dir, f"{TEMP_PREFIX}{name}")

    def new_writer(self, name):
        writer = RecorderWriter(self.new_path(name), WIDTH, HEIGHT, FPS)
        self.writers.append(writer)
        return writer

    def wait_for(self, predicate, timeout=15):
        """轮询等待条件成立，避免用固定 sleep 猜测编码耗时。"""
        deadline = time.time() + timeout
        while time.time() < deadline:
            if predicate():
                return True
            time.sleep(0.05)
        return predicate()

    def feed(self, writer, frames):
        """按编码速度投递若干帧，不触发丢弃。

        队列只有 FRAME_QUEUE_SIZE 个位置，一次性灌入大量帧必然丢帧；
        需要“全部帧都落盘”的用例应当用本方法投递。
        """
        for index in range(frames):
            while writer.queue.full():
                time.sleep(0.01)
            writer.write(make_frame(index))

    def test_writes_playable_fragmented_mp4(self):
        writer = self.new_writer("normal.mp4")
        for index in range(FPS * 2):
            writer.write(make_frame(index))

        self.assertTrue(writer.stop())
        self.assertFalse(writer.failed)

        boxes = top_level_boxes(writer.path)
        # moov 必须出现在任何分片之前，这是崩溃后仍可播放的前提。
        self.assertEqual(boxes[0], "ftyp")
        self.assertIn("moov", boxes[:2])
        self.assertIn("moof", boxes)
        self.assertGreater(writer.frames_written, 0)

    def test_moov_precedes_every_fragment_on_disk(self):
        # 崩溃后可播的前提：磁盘上出现任何分片之前，moov 必须已经在文件里，
        # 且必须排在分片之前。（拿到首帧前 PyAV 不会刷出文件头，因此写到分片边界再断言。）
        writer = self.new_writer("moov-first.mp4")
        self.feed(writer, FPS * 3)

        self.assertTrue(self.wait_for(
            lambda: "moof" in top_level_boxes(writer.path)),
            f"始终没有分片落盘: {top_level_boxes(writer.path)}")
        boxes = top_level_boxes(writer.path)

        self.assertIn("moov", boxes)
        self.assertLess(boxes.index("moov"), boxes.index("moof"))
        self.assertEqual(boxes[0], "ftyp")

    def test_frames_are_written_without_waiting_for_stop(self):
        # 解耦的核心：写入线程持续把队列里的帧写到盘上，不必等 stop()。
        # 需跨过第一个分片边界（第二个关键帧）才会刷出分片，故多喂一个 GOP。
        writer = self.new_writer("streaming.mp4")
        self.feed(writer, FPS * 2)

        self.assertTrue(self.wait_for(
            lambda: os.path.getsize(writer.path) > 0))
        self.assertTrue(self.wait_for(lambda: "moof" in top_level_boxes(writer.path)))

    def test_queue_full_drops_frames_instead_of_blocking(self):
        writer = self.new_writer("drop.mp4")
        # 一次投递远超队列容量的帧，采集侧不应被阻塞
        start = time.perf_counter()
        for index in range(FRAME_QUEUE_SIZE * 20):
            writer.write(make_frame(index))
        elapsed = time.perf_counter() - start

        self.assertLess(elapsed, 1.0)
        self.assertGreater(writer.frames_dropped, 0)

    def test_stop_releases_file_handle(self):
        # container.close() 不会关闭我们传入的文件对象；若不显式关闭，Windows 上
        # 文件会既删不掉也改不了名，录制文件的重命名逻辑会直接失败。
        writer = self.new_writer("release.mp4")
        writer.write(make_frame(0))
        self.assertTrue(writer.stop())

        renamed = writer.path + ".renamed"
        os.rename(writer.path, renamed)
        self.assertTrue(os.path.exists(renamed))

    def test_stop_is_idempotent(self):
        writer = self.new_writer("idempotent.mp4")
        writer.write(make_frame(0))

        first = writer.stop()
        second = writer.stop()

        self.assertEqual(first, second)
        self.assertTrue(os.path.exists(writer.path))
        self.assertTrue(writer.stop())

    def test_file_without_stop_is_still_decodable(self):
        # 模拟进程突然死亡：录制进行约 3 秒后进程直接消失，不做任何收尾。
        # 每分钟 1 个分片，因此此时磁盘上应已有完整分片且可解码。
        path = self.new_path("abrupt.mp4")
        script = "\n".join([
            "import os, time",
            "import numpy as np",
            "from tool.window_recorder.recorder_writer import RecorderWriter",
            f"writer = RecorderWriter({path!r}, {WIDTH}, {HEIGHT}, {FPS})",
            "def frame(i):",
            f"    g = np.linspace(0, 255, {WIDTH}, dtype=np.float32)",
            f"    row = np.tile(g, ({HEIGHT}, 1)).astype(np.uint8)",
            "    return np.dstack([np.roll(row, i*4, 1), np.roll(row, i*4+20, 1), np.roll(row, i*4+40, 1)])",
            "deadline = time.time() + 3.0",
            "i = 0",
            "while time.time() < deadline:",
            "    writer.write(frame(i))",
            "    i += 1",
            "    time.sleep(1 / 60)",
            "print('written', writer.frames_written, flush=True)",
            "os._exit(1)",  # 突然死亡：不收尾
        ])
        result = subprocess.run([os.sys.executable, "-c", script],
                                cwd=os.path.dirname(self.test_dir),
                                capture_output=True, text=True, timeout=120)
        self.assertEqual(result.returncode, 1, result.stderr[:300])

        boxes = top_level_boxes(path)
        self.assertIn("moov", boxes[:2])
        self.assertIn("moof", boxes, f"已写入分片缺失: {boxes}")
        self.assertGreater(os.path.getsize(path), 0)
        # 真正解码一遍，确认已写入的分片解得出画面，而不只是结构看起来齐全。
        self.assertGreater(decode_frame_count(path), 0)


if __name__ == "__main__":
    unittest.main()
