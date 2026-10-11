"""录像写入：fMP4 编码 + 独立写线程，让写盘不再阻塞采集。

录制线程只取帧并投递到有界队列，编码与写盘在单独的写入线程内完成。磁盘或编码器
一旦卡住，卡住的是写入线程，采集循环与主任务可以继续运行。

输出为分片 MP4（moov 在文件开头，之后每个分片可独立解码），因此进程被强制结束时
已写入的分片仍然可以播放，不再出现“文件体积正常却打不开”的情况。
"""

import queue
import threading
import time
from fractions import Fraction

import av

from tool.log import CUS_LOGGER

# 队列按帧计。1080p BGR 每帧约 6MB，15 帧约 90MB 上限。
# 深度只用于吸收写盘抖动，不需要更长：堆积越久，画面与实时差得越多。
FRAME_QUEUE_SIZE = 15

# 分片间隔（秒）。分片按关键帧切分，该值同时决定崩溃时最多损失多少录像。
# 注意这里的时间是「成片时间」：采集并非实时（每帧还要花时间截图），
# 因此一个分片在真实时间上可能跨越数秒，崩溃时实际损失的真实时长会相应更长。
FRAGMENT_SECONDS = 1

# 停止时等待写入线程收尾的上限，与录制线程的等待上限保持一致。
CLOSE_TIMEOUT = 3.0

# 关于丢帧：队列按帧数限长，「瞬时投递速度远超编码速度」时必然丢帧——例如把 30 帧
# 在一个循环里瞬间全部入队（编码需要约 0.2 秒），会丢掉十几帧。这是有意的背压：
# 宁可丢画面也不阻塞采集线程。按实时节奏投递时不会丢帧（1080p30 实测丢帧率 0）。


class _DirectFile:
    """把写入直接交给操作系统。

    av.open 默认在内存里缓冲整份输出，close() 才写盘；进程被强制结束时会丢掉
    全部内容。绕过用户态缓冲后，muxer 每次向文件写出分片都会真正落盘。
    """

    def __init__(self, path):
        self._raw = open(path, "wb", buffering=0)

    def write(self, data):
        return self._raw.write(data)

    def flush(self):
        self._raw.flush()

    def close(self):
        self._raw.close()


class RecorderWriter:
    """把采集到的帧编码写入 fMP4 文件，写盘在独立线程内完成。

    采集方调用 `write()` 入队，队列满时丢弃当前帧并计数，绝不阻塞；`stop()` 等待
    写入线程收尾，返回 False 表示写入失败或线程未能结束（此时文件可能只有部分内容，
    但已写入的分片仍可播放）。
    """

    def __init__(self, path, width, height, fps):
        self.path = path
        self.width = width
        self.height = height
        self.fps = fps
        # PyAV 的 add_stream(rate=...) 只接受整数或分数，浮点帧率需要先转成分数
        self._rate = Fraction(fps).limit_denominator()
        self.frames_written = 0
        self.frames_dropped = 0
        self.failed = False
        self.stop_event = threading.Event()
        self.queue = queue.Queue(maxsize=FRAME_QUEUE_SIZE)
        self._stop_lock = threading.Lock()
        self._stopped = False
        self._shutdown_ok = False

        self._started_at = time.monotonic()
        self._sink = _DirectFile(path)
        self._container = av.open(self._sink, mode="w", format="mp4", options={
            "movflags": "+frag_keyframe+empty_moov+default_base_moof",
        })
        self._stream = self._container.add_stream("libx264", rate=self._rate)
        self._stream.width = width
        self._stream.height = height
        self._stream.pix_fmt = "yuv420p"
        self._stream.options = {"crf": "23", "preset": "veryfast"}
        # 分片按关键帧切分，因此关键帧间隔就是崩溃时的最大损失时长。
        self._stream.gop_size = max(1, int(self._rate * FRAGMENT_SECONDS))

        self.thread = threading.Thread(target=self._write_loop, name="录像写入", daemon=True)
        self.thread.start()

    def write(self, frame):
        """投递一帧；队列已满时丢弃该帧，避免阻塞采集。

        Args:
            frame: BGR 顺序的 numpy 帧。
        """
        try:
            self.queue.put_nowait(frame)
        except queue.Full:
            self.frames_dropped += 1

    def stop(self):
        """停止写入并收尾，返回写入是否正常结束。

        录制线程与停止流程都会调用这里，因此可重复调用：第二次直接返回首次结果，
        不会再次等待或再次关闭容器。

        队列里仍有积压时不做长时间收尾：录制线程停不下来的场景本就意味着写入线程
        可能也已卡住，继续等它只会连带卡住停止流程。

        Returns:
            写入线程已正常结束（或本来就没有积压需要写）时为 True。
            为 False 表示写入失败或线程未能结束，此时文件可能只有部分内容。
        """
        self.stop_event.set()
        with self._stop_lock:
            if self._stopped:
                return self._shutdown_ok
            self._stopped = True
            self._shutdown_ok = self._shutdown()
            return self._shutdown_ok

    def _shutdown(self):
        if not self.thread.is_alive():
            return not self.failed

        backlog = self.queue.qsize()
        if backlog:
            CUS_LOGGER.debug(f"等待写入线程写出剩余 {backlog} 帧...")

        self.thread.join(timeout=CLOSE_TIMEOUT)
        if self.thread.is_alive():
            CUS_LOGGER.error(
                f"写入线程在 {CLOSE_TIMEOUT} 秒内未结束，本次录像可能不完整"
                "（已写入的分片仍可播放）"
            )
            return False

        if self.frames_dropped:
            CUS_LOGGER.warning(
                f"本次录制因写盘跟不上丢弃 {self.frames_dropped} 帧，"
                f"共写入 {self.frames_written} 帧"
            )
        return not self.failed

    def _write_loop(self):
        """写入线程主体：取帧、编码、复用。"""
        try:
            index = 0
            while True:
                try:
                    frame = self.queue.get(timeout=0.1)
                except queue.Empty:
                    if self.stop_event.is_set():
                        break
                    continue
                self._mux(frame, index)
                index += 1
            self._flush()
        except Exception as e:
            self.failed = True
            CUS_LOGGER.error(f"录像写入失败，本次录制提前结束：{e}")

    def _mux(self, pixels, index):
        frame = av.VideoFrame.from_ndarray(pixels, format="bgr24")
        frame.pts = index
        # 每捕获一帧占 1/fps：录制并非实时采集，播放时长等于帧数/fps
        frame.time_base = Fraction(1, 1) / self._rate
        for packet in self._stream.encode(frame):
            self._container.mux(packet)
        self.frames_written += 1

    def _flush(self):
        """刷出编码器余量并关闭容器与文件。

        container.close() 不会关闭我们自己传入的文件对象，句柄会一直留着；
        在 Windows 上那会导致文件既删不掉也改不了名，因此这里显式关闭。
        """
        for packet in self._stream.encode(None):
            self._container.mux(packet)
        self._container.close()
        self._sink.close()
