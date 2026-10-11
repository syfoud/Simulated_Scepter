"""隔离窗口与编码依赖，验证录制停止请求、录制文件处置与写入器协作。"""

import glob
import importlib.util
import os
import sys
import time
import types
import unittest
from pathlib import Path
from unittest.mock import Mock

from PIL import Image

from tool.window_recorder.recorder_writer import RecorderWriter as RealRecorderWriter

FAKE_WINDOW_RECT = (623, 5, 2565, 1141)
TEMP_PREFIX = ".recorder-test-"

# 分片 MP4 的最小可播放前缀：moov 在文件开头，之后是分片。
FTYP_BOX = b"\x00\x00\x00\x0cftypisom"
MOOV_BOX = b"\x00\x00\x00\x0cmoovmvhd"
MOOF_BOX = b"\x00\x00\x00\x0cmoofmfhd"
MDAT_BOX = b"\x00\x00\x00\x0cmdat\x00\x00\x00\x00"


class FakeRecorderWriter:
    """写入器替身：记录调用，并按需把文件写成“已写入分片”的样子。"""

    instances = []

    def __init__(self, path, width, height, fps):
        self.path = path
        self.width = width
        self.height = height
        self.fps = fps
        self.frames_written = 0
        self.frames_dropped = 0
        self.failed = False
        self.stop_calls = 0
        self.stop_ok = True
        with open(path, "wb") as file:
            file.write(FTYP_BOX)
            file.write(MOOV_BOX)
        FakeRecorderWriter.instances.append(self)

    def write(self, _frame):
        self.frames_written += 1
        with open(self.path, "ab") as file:
            file.write(MOOF_BOX)
            file.write(MDAT_BOX)

    def stop(self):
        self.stop_calls += 1
        return self.stop_ok


def load_recorder_module(stubs):
    """加载录制器模块，用替身隔离 OpenCV、截图、线程与写入器实现。"""
    stub_names = {
        "cv2": stubs["cv2"],
        "numpy": stubs["numpy"],
        "PIL": types.ModuleType("PIL"),
        "PIL.ImageGrab": stubs["image_grab"],
        "win32gui": stubs["win32gui"],
        "win32ui": Mock(),
        "route": stubs["route"],
        "tool.log": stubs["logger"],
        "tool.thread": stubs["thread"],
        "tool.window_recorder.recorder_writer": stubs["writer"],
        "tool.utils.game_window": stubs["game_window"],
        "tool.window_recorder.video_remux": stubs["remux"],
    }
    # time 需要真实模块（fps 节流会调用 time.sleep），但允许替换 sleep 以便观测节奏
    if "time" in stubs:
        stub_names["time"] = stubs["time"]
    saved = {name: sys.modules.get(name) for name in stub_names}

    # 这里可能新建 tool / tool.utils 两个包壳（真实运行时它们来自项目）。
    # 必须一并记录：否则空壳会留在 sys.modules 里，导致后续测试
    # import tool.action_script 之类的子模块全部失败。
    for name in ("tool", "tool.utils", "tool.window_recorder"):
        saved.setdefault(name, sys.modules.get(name))

    # 注意：saved 里存的是模块对象本身，而下面会把 __path__ 改掉——
    # 那是对同一个对象的原地修改，所以 __path__ 必须单独留底，否则恢复等于没恢复。
    missing = object()
    saved_paths = {
        name: (module, getattr(module, "__path__", missing))
        for name, module in saved.items()
        if module is not None
    }

    for name in ("tool", "tool.utils"):
        module = sys.modules.setdefault(name, types.ModuleType(name))
        module.__path__ = []
    # 这些属性是挂在真实模块对象上的，恢复 sys.modules 不足以还原，需要逐个记下原值
    attached = (
        ("tool", "log"),
        ("tool", "thread"),
        ("tool.window_recorder", "recorder_writer"),
        ("tool.window_recorder", "video_remux"),
        ("tool.utils", "game_window"),
    )
    previous_attrs = {}
    for module_name, attr in attached:
        module = sys.modules.get(module_name)
        if module is not None:
            previous_attrs[(module_name, attr)] = getattr(module, attr, None)

    sys.modules["tool"].log = stubs["logger"]
    sys.modules["tool"].thread = stubs["thread"]
    sys.modules["tool.window_recorder"].recorder_writer = stubs["writer"]
    sys.modules["tool.window_recorder"].video_remux = stubs["remux"]
    sys.modules["tool.utils"].game_window = stubs["game_window"]
    sys.modules.update(stub_names)

    try:
        path = Path(__file__).resolve().parents[1] / "tool" / "window_recorder" / "window_recorder.py"
        spec = importlib.util.spec_from_file_location("window_recorder_under_test", path)
        recorder_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(recorder_module)
    finally:
        for name, previous in saved.items():
            if previous is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = previous
        # 还原被原地改掉的 __path__
        for module, previous_path in saved_paths.values():
            if previous_path is missing:
                if hasattr(module, "__path__"):
                    del module.__path__
            else:
                module.__path__ = previous_path
        for (module_name, attr), previous in previous_attrs.items():
            module = sys.modules.get(module_name)
            if module is None:
                continue
            if previous is None:
                if hasattr(module, attr):
                    delattr(module, attr)
            else:
                setattr(module, attr, previous)

    return recorder_module


class WindowRecorderTests(unittest.TestCase):
    def setUp(self):
        # 录制文件写到工作区根目录：新建子目录在部分环境下不可写，测试只需唯一前缀。
        self.test_dir = Path(__file__).resolve().parents[1]
        self.output_path = str(self.test_dir)
        FakeRecorderWriter.instances = []

        cv2_stub = types.ModuleType("cv2")
        # 采集循环把截图转成 BGR；测试只需保住形状与通道数
        cv2_stub.COLOR_RGB2BGR = 0
        cv2_stub.cvtColor = lambda image, code: image
        image_grab = types.ModuleType("PIL.ImageGrab")
        image_grab.grab = Mock()

        win32gui = types.ModuleType("win32gui")
        win32gui.FindWindow = lambda *args: 1234
        win32gui.GetWindowRect = lambda hwnd: FAKE_WINDOW_RECT
        win32gui.IsWindow = lambda hwnd: True
        win32gui.IsWindowVisible = lambda hwnd: True
        win32gui.ReleaseDC = lambda hwnd, dc: None
        win32gui.DeleteObject = lambda handle: None

        game_window = types.ModuleType("tool.utils.game_window")
        game_window.CLOUD_WINDOW_KIND = "cloud"
        game_window.LOCAL_GAME_TITLE = "崩坏：星穹铁道"
        game_window.find_game_window = lambda **kwargs: None
        game_window.get_client_screen_rect = lambda hwnd: FAKE_WINDOW_RECT
        game_window.get_window_kind = lambda hwnd: "local"
        game_window.is_usable_game_window = lambda hwnd: True

        logger = types.ModuleType("tool.log")
        logger.CUS_LOGGER = Mock()

        # 录制线程替身不执行线程体，is_alive 默认返回 False，启动后即视为已结束。
        self.thread_class = Mock(
            side_effect=lambda **kwargs: Mock(is_alive=Mock(return_value=False)))

        writer = types.ModuleType("tool.window_recorder.recorder_writer")
        writer.RecorderWriter = FakeRecorderWriter

        # 转封装在后台线程里跑；测试里替换掉，只观察是否被正确调用
        self.remux_calls = []
        remux = types.ModuleType("tool.window_recorder.video_remux")
        remux.convert_in_background = lambda path, **kwargs: self.remux_calls.append(path)

        route = types.ModuleType("route")
        route.PATHS = {"video": self.output_path}

        self.stubs = {
            "cv2": cv2_stub,
            # numpy 是本项目依赖且导入无副作用，直接用真实实现，避免替身缺函数掩盖问题
            "numpy": __import__("numpy"),
            "image_grab": image_grab,
            "win32gui": win32gui,
            "game_window": game_window,
            "logger": logger,
            "thread": types.ModuleType("tool.thread"),
            "writer": writer,
            "remux": remux,
            "route": route,
        }
        self.stubs["thread"].ThreadWithException = self.thread_class
        self.module = load_recorder_module(self.stubs)
        self.recorder = self.module.WindowRecorder(
            output_path=self.output_path,
            window_title="崩坏：星穹铁道",
            window_class_name="UnityWndClass",
        )

    def tearDown(self):
        # 录制文件由录像器按「第N次轮回-时间戳.mp4」命名并写在 output_path（工作区根目录），
        # 这里统一清理；只匹配该命名格式，不触碰其它文件。
        # 收尾单独容错：清理失败不应盖住真正导致失败的断言。
        for pattern in ("第*次轮回-*.mp4", f"{TEMP_PREFIX}*"):
            for path in glob.glob(str(self.test_dir / pattern)):
                try:
                    os.remove(path)
                except OSError:
                    pass

    @property
    def output_file(self):
        return self.recorder.output_file

    @property
    def writer(self):
        """最近一次创建出来的写入器替身。"""
        return FakeRecorderWriter.instances[-1]

    def test_idle_stop_does_not_block_next_start(self):
        # restart_recording 的写法是「停止 → 0.8s → 启动」。空闲时的停止若留下
        # 停止意图，配对的启动会被自己拒绝，此后本次运行再也不录制。
        self.recorder.stop_recording(delete_video=True)

        self.assertFalse(self.recorder.stop_event.is_set())

        self.recorder.start_recording(1)

        self.assertTrue(self.recorder.recording)
        self.assertEqual(len(FakeRecorderWriter.instances), 1)

    def test_running_stop_still_allows_paired_restart(self):
        # 会话正在运行时的停止同样不得毒化配对的下一次启动
        self.write_recording()
        self.recorder.stop_recording()

        self.recorder.start_recording(2)

        self.assertTrue(self.recorder.recording)
        self.assertEqual(len(FakeRecorderWriter.instances), 2)

    def test_stop_during_initialization_discards_writer_and_file(self):
        original = FakeRecorderWriter.__init__

        def stop_after_open(writer_self, *args):
            original(writer_self, *args)
            self.recorder.stop_event.set()

        FakeRecorderWriter.__init__ = stop_after_open
        self.addCleanup(setattr, FakeRecorderWriter, "__init__", original)

        self.recorder.start_recording(2)

        self.assertFalse(self.recorder.recording)
        self.assertIsNone(self.recorder.out)
        self.assertEqual(self.writer.stop_calls, 1)
        self.assertFalse(os.path.exists(self.output_file))

    def test_stop_removes_recording_when_requested(self):
        self.recorder.stop_event.clear()
        self.write_recording()
        self.recorder.recording = True

        self.recorder.stop_recording(delete_video=True)

        self.assertFalse(os.path.exists(self.output_file))

    def test_stop_removes_recording_when_write_failed(self):
        # 写入线程已失败（例如编码器不可用），文件里没有可用内容，保留只会留下空文件。
        self.write_recording()
        self.writer.failed = True

        self.recorder.stop_recording()

        self.assertFalse(os.path.exists(self.output_file))

    def test_stop_keeps_partial_recording_when_writer_hangs(self):
        # 写入线程未能结束，但已写入的分片是完整可播的，不能删掉它。
        self.write_recording()
        self.writer.stop_ok = False

        self.recorder.stop_recording()

        self.assertTrue(os.path.exists(self.output_file))

    def test_stop_keeps_recording_and_updates_filename(self):
        self.write_recording()

        self.recorder.stop_recording(battle_count=2)

        self.assertTrue(os.path.exists(self.output_file))
        self.assertIn("2战-", self.output_file)

    def test_stopping_thread_leaves_recording_untouched_and_continues(self):
        # 录制线程卡在无法中断的调用里时，不能强行终止它，也不能去删或重命名一个
        # 仍在写入的文件；本次录制按失败处理，任务本身继续运行。
        self.write_recording(thread_alive=True)

        self.recorder.stop_recording(delete_video=True, battle_count=2)

        self.recorder.recording_thread.join.assert_called_once_with(timeout=3.0)
        self.assertTrue(os.path.exists(self.output_file))
        self.assertNotIn("2战-", self.output_file)

    def test_thread_not_stopped_blocks_further_recording(self):
        # 线程仍在运行时不得启动新会话：启动前会清除停止意图，此时唯一能拦住它的是
        # 「线程仍存活」这一条；否则旧线程退出会释放新会话的写入器。
        self.write_recording(thread_alive=True)
        self.recorder.stop_recording()

        self.recorder.start_recording(9)

        self.assertFalse(self.recorder.recording)
        self.assertEqual(len(FakeRecorderWriter.instances), 1)
        # 没有为第 9 次创建新的录制文件
        self.assertNotIn("第9次轮回", self.recorder.output_file)

    def test_recording_uses_writer_with_capture_size(self):
        self.recorder.start_recording(3)
        writer = self.writer

        # 窗口 1942x1136，偏移 [0,0,0,0]（默认），宽高均为偶数
        self.assertEqual((writer.width, writer.height), (1942, 1136))
        self.assertEqual(writer.fps, self.recorder.fps)
        self.assertEqual(writer.path, self.output_file)

    def test_recording_loop_produces_playable_fragmented_mp4(self):
        """用真实写入器跑一遍采集循环，确认整条链路产出可播放的分片 MP4。"""
        import av
        import numpy as np

        # 本用例用真实写入器，其余依赖仍用替身
        self.stubs["writer"].RecorderWriter = RealRecorderWriter

        # 同步执行线程体，让采集循环在测试线程里真实运行
        inline_thread = type("InlineThread", (), {
            "__init__": lambda self, target, **kwargs: setattr(self, "target", target),
            "start": lambda self: self.target(),
            "is_alive": lambda self: False,
            "join": lambda self, timeout=None: None,
        })
        self.stubs["thread"].ThreadWithException = inline_thread
        module = load_recorder_module(self.stubs)

        recorder = module.WindowRecorder(
            output_path=self.output_path,
            window_title="崩坏：星穹铁道",
            window_class_name="UnityWndClass",
            fps=30,
        )

        captured = []

        def grab(bbox=None):
            captured.append(bbox)
            # 取到若干帧后请求停止，让采集循环自行退出
            if len(captured) >= 40:
                recorder.stop_event.set()
            pixels = np.zeros((bbox[3] - bbox[1], bbox[2] - bbox[0], 3), dtype=np.uint8)
            pixels[:] = (len(captured) * 7) % 256
            return Image.fromarray(pixels, mode="RGB")

        self.stubs["image_grab"].grab = grab
        recorder.start_recording(5)

        # 采集循环在测试线程里同步跑完；这里显式走一次停止流程，让写入器收尾
        self.assertGreater(len(captured), 0, "采集循环没有取到任何帧")
        recorder.stop_recording()

        path = recorder.output_file
        self.assertTrue(os.path.exists(path), f"录制文件未生成: {path}")
        self.assertGreater(os.path.getsize(path), 0)

        # moov 必须在前部（崩溃后可播的前提）
        with open(path, "rb") as file:
            self.assertIn(b"moov", file.read(4096))

        # 文件能被真实解码出画面
        with av.open(path) as container:
            frames = sum(1 for _ in container.decode(video=0))
        self.assertGreater(frames, 0)

    def test_capture_cadence_and_timeline_match_nominal_fps(self):
        """取帧节奏与时间轴：每捕获一帧占 1/fps，与改造前一致。

        录制并非实时采集（每帧还要花时间截图，再补 sleep(1/fps)），因此一段录像的
        播放时长等于「捕获帧数 / fps」。这条不能因为换成 fMP4 而改变。
        """
        import av
        import numpy as np

        self.stubs["writer"].RecorderWriter = RealRecorderWriter

        inline_thread = type("InlineThread", (), {
            "__init__": lambda self, target, **kwargs: setattr(self, "target", target),
            "start": lambda self: self.target(),
            "is_alive": lambda self: False,
            "join": lambda self, timeout=None: None,
        })
        self.stubs["thread"].ThreadWithException = inline_thread

        intervals = []

        # 替换 sleep 以便观测节流间隔，同时保持循环快速推进；
        # monotonic 仍需真实实现（录制循环用它统计已录时长）
        real_time = time
        fake_time = types.ModuleType("time")
        fake_time.sleep = lambda seconds: intervals.append(seconds)
        fake_time.monotonic = real_time.monotonic
        self.stubs["time"] = fake_time
        module = load_recorder_module(self.stubs)

        fps = 10.0
        recorder = module.WindowRecorder(
            output_path=self.output_path,
            window_title="崩坏：星穹铁道",
            window_class_name="UnityWndClass",
            fps=fps,
        )
        captured = []

        def grab(bbox=None):
            captured.append(bbox)
            if len(captured) >= 30:
                recorder.stop_event.set()
            stride = 4
            pixels = np.zeros(
                (bbox[3] - bbox[1], bbox[2] - bbox[0], 3), dtype=np.uint8)
            # 逐帧平移，避免相邻帧完全相同而影响关键帧判断
            pixels[:, (len(captured) * stride) % pixels.shape[1]:, :] = 200
            return Image.fromarray(pixels, mode="RGB")

        self.stubs["image_grab"].grab = grab
        recorder.start_recording(1)
        # 显式停止，确保写入器收尾并把帧全部写出
        recorder.stop_recording()

        # 1) 节流间隔必须等于 1/fps
        self.assertTrue(intervals, "采集循环没有执行帧率节流")
        for value in intervals:
            self.assertAlmostEqual(value, 1 / fps, places=6)

        # 2) 时间轴：播放时长 = 捕获帧数 / fps
        path = recorder.output_file
        with av.open(path) as container:
            decoded = [frame for frame in container.decode(video=0)]
            # container.duration 以 av.time_base（微秒）为单位
            duration = container.duration / av.time_base

        self.assertGreater(len(decoded), 0)
        self.assertAlmostEqual(duration, len(decoded) / fps, places=2)
        self.assertAlmostEqual(duration, len(captured) / fps, places=2)

    def test_stop_converts_recording_for_seeking(self):
        # 分片 MP4 无法被部分播放器拖动进度条；停止后应在后台转封装成标准 MP4，
        # 且使用重命名后的最终文件名。
        self.write_recording()

        self.recorder.stop_recording(battle_count=2)

        self.assertEqual(self.remux_calls, [self.output_file])
        self.assertIn("2战-", self.output_file)

    def test_no_conversion_when_recording_deleted(self):
        self.write_recording()

        self.recorder.stop_recording(delete_video=True)

        self.assertEqual(self.remux_calls, [])

    def test_no_conversion_when_writer_failed(self):
        self.write_recording()
        self.writer.failed = True

        self.recorder.stop_recording()

        self.assertEqual(self.remux_calls, [])

    def test_no_conversion_when_recording_thread_stuck(self):
        # 线程未退出时文件仍在写入，绝不能交给转封装去动
        self.write_recording(thread_alive=True)

        self.recorder.stop_recording()

        self.assertEqual(self.remux_calls, [])

    def test_recording_stops_when_owning_task_ends(self):
        """任务结束（正常退出或异常终止）时，录制必须跟着停止。

        否则录制线程会作为孤儿一直写盘，表现为「任务早就停了，录像文件却一直在长大」。
        """
        import av
        import numpy as np

        self.stubs["writer"].RecorderWriter = RealRecorderWriter

        inline_thread = type("InlineThread", (), {
            "__init__": lambda self, target, **kwargs: setattr(self, "target", target),
            "start": lambda self: self.target(),
            "is_alive": lambda self: False,
            "join": lambda self, timeout=None: None,
        })
        self.stubs["thread"].ThreadWithException = inline_thread
        module = load_recorder_module(self.stubs)

        recorder = module.WindowRecorder(
            output_path=self.output_path,
            window_title="崩坏：星穹铁道",
            window_class_name="UnityWndClass",
            fps=30,
        )
        # 任务从一开始是活的，取到 6 帧后结束
        alive = {"value": True}
        task_thread = types.SimpleNamespace(is_alive=lambda: alive["value"])
        grabs = []

        def grab(bbox=None):
            grabs.append(bbox)
            if len(grabs) >= 6:
                alive["value"] = False
            return Image.fromarray(
                np.zeros((bbox[3] - bbox[1], bbox[2] - bbox[0], 3), dtype=np.uint8),
                mode="RGB")

        self.stubs["image_grab"].grab = grab
        recorder.task_owner = task_thread

        recorder.start_recording(1)
        recorder.stop_recording()

        # 任务结束后只允许再多取一帧（死亡与检查之间的那一帧）
        self.assertLessEqual(len(grabs), 7, f"任务结束后仍在继续取帧: {len(grabs)} 次")
        self.assertFalse(recorder.recording)
        self.assertTrue(os.path.exists(recorder.output_file))
        with av.open(recorder.output_file) as container:
            self.assertGreater(sum(1 for _ in container.decode(video=0)), 0)

    def test_stuck_thread_still_releases_writer(self):
        """线程卡住时也必须释放写入器——那是唯一能止住文件增长的动作。"""
        self.write_recording(thread_alive=True)
        self.assertIsNotNone(self.recorder.out)

        self.recorder.stop_recording()

        # 不再持有写入器，也不去处置仍在写入的文件
        self.assertIsNone(self.recorder.out)
        self.assertEqual(self.writer.stop_calls, 1)
        self.assertTrue(os.path.exists(self.output_file))
        self.assertEqual(self.remux_calls, [])

    def write_recording(self, thread_alive=False):
        """造出一次已开始的录制：创建写入器、写一帧，并固定录制线程的存活状态。

        不直接置 recording：那会让 stop_recording 跳过线程等待，留下一个仍显示存活的
        线程，与真实停止流程不一致。
        """
        self.recorder.stop_event.clear()
        self.recorder.start_recording(1)
        self.writer.write(None)
        self.recorder.recording_thread.is_alive.return_value = thread_alive
