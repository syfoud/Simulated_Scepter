"""脚本取样与单轮调试，使用调用方提供的内核和公共动作接口。"""

import copy
import os
import re
import tempfile
import time
from pathlib import Path

import cv2 as cv

from route import PATHS
from tool.GLOBAL import get_global_stop_flag, key_mouse_manager
from tool.log import CUS_LOGGER
from tool.public_ocr import merge_text
from tool.utils.game_window import get_foreground_game_window, set_game_foreground


def wait_game_focus(engine, deadline):
    """在期限内确认游戏持续获得焦点，等待期间响应停止。"""
    if engine._stop or get_global_stop_flag():
        raise InterruptedError("操作已停止")
    window = set_game_foreground()
    if window is None:
        raise RuntimeError("未找到游戏窗口，请启动游戏后重试")
    CUS_LOGGER.debug("等待游戏窗口获得焦点；若未自动切换，请点击游戏窗口。")
    focused_since = None
    while time.monotonic() < deadline:
        if engine._stop or get_global_stop_flag():
            raise InterruptedError("操作已停止")
        foreground = get_foreground_game_window()
        if foreground is None or foreground.hwnd != window.hwnd:
            focused_since = None
        elif focused_since is None:
            focused_since = time.monotonic()
        elif time.monotonic() - focused_since >= 0.3:
            return window  # 留出窗口切换与重绘时间，避免切换尚未完成就操作。
        time.sleep(0.05)
    raise RuntimeError("游戏窗口未持续获得焦点，操作未执行；请切换到游戏后重试")


def capture_sample(engine, recognize):
    deadline = time.monotonic() + 6
    while True:
        window = wait_game_focus(engine, deadline)
        screen = engine.get_screen().copy()
        foreground = get_foreground_game_window()
        if foreground is not None and foreground.hwnd == window.hwnd:
            break
        # 截图期间被其他窗口抢占时丢弃画面，在同一期限内重新等待。
    if engine._stop or get_global_stop_flag():
        raise InterruptedError("截图已停止")
    if screen.ndim != 3 or screen.shape[2] != 3 or not screen.size:
        raise ValueError("没有取得有效游戏截图")
    texts = []
    if recognize:
        engine.ts.forward(screen)
        texts = copy.deepcopy(engine.ts.res)
    return {"screen": screen, "texts": texts}


def text_trigger(item):
    text = merge_text([item])
    if not text:
        raise ValueError("所选文字按运行时识别规则处理后为空，请选择其他文字标志")
    return {"text": text, "box": list(item["box"])}


def marker_path(event_name):
    """按事件名生成默认 PNG 路径，保留已有同名图片。"""
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", event_name).strip().rstrip(". ")[:100]
    if not name:
        name = "图片标志"
    if name.split(".")[0].upper() in {"CON", "PRN", "AUX", "NUL", *[f"{prefix}{i}" for prefix in ("COM", "LPT") for i in range(1, 10)]}:
        name = "_" + name
    folder = Path(PATHS["image"]) / "script_markers"
    path = folder / f"{name}.png"
    suffix = 2
    while path.exists():
        path = folder / f"{name} ({suffix}).png"
        suffix += 1
    return path


def save_marker(screen, box, path):
    """保存独立图片标志，并按内核坐标约定生成局部匹配中心。"""
    left, right, top, bottom = box
    height, width = screen.shape[:2]
    if not (0 <= left < right <= width and 0 <= top < bottom <= height):
        raise ValueError("图片框选范围必须位于截图内且具有有效面积")
    crop = screen[top:bottom, left:right].copy()
    success, encoded = cv.imencode(".png", crop)
    if not success:
        raise OSError("图片标志无法编码为 PNG")
    path = Path(path).resolve()
    if path.suffix.lower() != ".png":
        raise ValueError("图片标志必须保存为 PNG 文件")
    path.parent.mkdir(parents=True, exist_ok=True)
    # 同目录临时文件替换，写入失败不会破坏用户选择覆盖的原图。
    file = tempfile.NamedTemporaryFile(dir=path.parent, suffix=".tmp", delete=False)
    temporary = Path(file.name)
    try:
        with file:
            file.write(encoded.tobytes())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    # 图像目录内使用相对路径，外部文件使用绝对路径，避免同名标志串用。
    try:
        photo = path.relative_to(Path(PATHS["image"]).resolve()).as_posix()
        if "/" not in photo:
            photo = "./" + photo
    except ValueError:
        photo = path.as_posix()
    return {"photo": photo, "pos": {"x": 1 - (left + right) / (2 * width),
                                       "y": 1 - (top + bottom) / (2 * height)},
            "threshold": 0.9}, path


def debug_events(engine, events, direct):
    """执行一轮调试，等待已提交的键鼠动作完成后才返回。"""
    if engine._stop or get_global_stop_flag():
        return "调试已停止"
    wait_game_focus(engine, time.monotonic() + 6)
    engine.prepare_script()
    if direct:
        count = 0
        for event in events:
            for step in event["actions"]:
                if engine._stop or get_global_stop_flag():
                    return f"调试已停止，已执行 {count} 个动作"
                CUS_LOGGER.debug("直接调试事件“%s”的动作：%s", event["name"], step)
                engine.do_action(step)
                key_mouse_manager.wait()
                if engine._stop or get_global_stop_flag():
                    return f"调试已停止，已执行 {count} 个动作"
                count += 1
        return f"直接调试完成：{len(events)} 个事件，{count} 个动作"
    engine.ts.forward(engine.get_screen())
    if engine._stop or get_global_stop_flag():
        return "调试已停止"
    # 使用序号保留编辑器的事件顺序，同名事件也不重新分组。
    matched, _ = engine.match_actions(json_file={index: [event] for index, event in enumerate(events)})
    key_mouse_manager.wait()
    if engine._stop or get_global_stop_flag():
        return "调试已停止"
    return f"触发调试完成：已命中“{matched}”并执行动作" if matched else "触发调试完成：当前画面未命中所选触发条件"
