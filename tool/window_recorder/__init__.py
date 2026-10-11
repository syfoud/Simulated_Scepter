"""窗口录像：分片 MP4 录制、写盘解耦与录制后的转封装。

对外只暴露 `WindowRecorder`，调用方通过它录制游戏窗口：

    from tool.window_recorder import WindowRecorder

模块划分：

- `window_recorder`：窗口定位、截图循环与录制生命周期。
- `recorder_writer`：编码与写盘（独立线程 + 有界队列）。
- `video_remux`：把分片 MP4 转封装为可跳转的标准 MP4。
"""

from tool.window_recorder.recorder_writer import RecorderWriter
from tool.window_recorder.video_remux import (
    convert_in_background,
    convert_to_standard_mp4,
    convert_with_tail_trimmed,
    needs_conversion,
)
from tool.window_recorder.window_recorder import WindowRecorder

__all__ = [
    "RecorderWriter",
    "WindowRecorder",
    "convert_in_background",
    "convert_to_standard_mp4",
    "convert_with_tail_trimmed",
    "needs_conversion",
]
