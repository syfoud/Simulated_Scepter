"""鼠标坐标拾取：鼠标移到哪、按 Ctrl 就记录哪，输出相对游戏窗口的 1920x1080 坐标。

用途：不依赖 OCR 和模板图，直接肉眼把鼠标放到图标上点一下，就知道它在基准坐标里的位置。

独立运行：
    python -m tool.coordinate_picker          # 聚焦游戏窗口后采集，右键停止
    python -m tool.coordinate_picker --no-focus

用 Ctrl 而不是点击采样：点击会把游戏里的卡片按钮真的点下去，界面一变后续坐标就不准。
注意：游戏鼠标被锁定时（FPS 视角），按住 Alt 才能自由移动光标；这是游戏行为，本工具不做拦截。
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterable

import win32api
import win32con

from tool.utils.game_window import (
    BASE_HEIGHT,
    BASE_WIDTH,
    GameWindow,
    find_game_window,
    get_client_screen_rect,
    set_game_foreground,
)

POLL_INTERVAL = 0.02  # 秒；轮询精度足够人手点击，不会明显吃 CPU


def to_base(x: int, y: int, rect: Iterable[int]) -> tuple[int, int]:
    """把屏幕物理像素换算成 1920x1080 基准坐标（与 click_game 的换算互为逆运算）。"""
    left, top, right, bottom = rect
    width, height = right - left, bottom - top
    if width <= 0 or height <= 0:
        raise ValueError(f"游戏窗口尺寸无效：{width}x{height}")
    return (
        round((x - left) * BASE_WIDTH / width),
        round((y - top) * BASE_HEIGHT / height),
    )


def format_point(base: tuple[int, int], screen: tuple[int, int], rect: Iterable[int]) -> str:
    """输出一行便于复制进代码的坐标。"""
    left, top = list(rect)[:2]
    window_x, window_y = screen[0] - left, screen[1] - top
    return (f"({base[0]}, {base[1]})   基准1920x1080 | "
            f"窗口内 ({window_x}, {window_y}) | 屏幕 ({screen[0]}, {screen[1]})")


def pick_coordinates(
    hwnd: int | None = None,
    on_point: Callable[[tuple[int, int], tuple[int, int], str], None] | None = None,
    should_stop: Callable[[], bool] | None = None,
    focus: bool = True,
) -> list[tuple[int, int]]:
    """阻塞采集，直到右键或 should_stop() 返回 True。

    Args:
        hwnd: 目标窗口句柄；为空时自动找游戏窗口。
        on_point: 每采集到一个点回调 (基准坐标, 屏幕坐标, 文本)。
        should_stop: 外部停止条件（GUI 用按钮/窗口关闭触发）。
        focus: 是否先把游戏窗口切到前台。

    Returns:
        采集到的 1920x1080 基准坐标列表。
    """
    if hwnd is None:
        window: GameWindow | None = set_game_foreground() if focus else find_game_window()
        if window is None:
            raise RuntimeError("没有找到游戏窗口；请先打开游戏，或取消『优先聚焦』")
        hwnd = window.hwnd

    rect = get_client_screen_rect(hwnd)
    points: list[tuple[int, int]] = []
    # 采样用 Ctrl 而不是点击：点击会把游戏里的卡片/按钮真的点下去，界面一变后面的坐标就不准了
    trigger_was_down = False

    try:
        while True:
            if should_stop is not None and should_stop():
                break
            if win32api.GetAsyncKeyState(win32con.VK_RBUTTON) & 0x8000:
                break

            trigger_down = bool(win32api.GetAsyncKeyState(win32con.VK_CONTROL) & 0x8000)
            # 只在按下的那一帧采点，按住不放不会重复刷屏
            if trigger_down and not trigger_was_down:
                screen = win32api.GetCursorPos()
                base = to_base(screen[0], screen[1], rect)
                if 0 <= base[0] <= BASE_WIDTH and 0 <= base[1] <= BASE_HEIGHT:
                    points.append(base)
                    if on_point is not None:
                        on_point(base, screen, format_point(base, screen, rect))
            trigger_was_down = trigger_down
            time.sleep(POLL_INTERVAL)
    finally:
        # 不让残留按键状态影响后续自动化
        trigger_was_down = False

    return points


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="鼠标坐标拾取（右键停止）")
    parser.add_argument("--no-focus", action="store_true", help="不强制把游戏窗口切到前台")
    args = parser.parse_args()

    print("鼠标移到目标位置、按 Ctrl 记录（不会点击游戏），右键停止；窗口外会忽略。", flush=True)
    try:
        points = pick_coordinates(focus=not args.no_focus, on_point=lambda b, s, text: print(text, flush=True))
    except RuntimeError as error:
        print(error, flush=True)
        return 1
    print(f"共采集 {len(points)} 个点。", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
