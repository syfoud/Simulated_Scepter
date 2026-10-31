"""差分宇宙入场、单轮开局和图鉴采集入口。"""

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import cv2
import numpy as np

from tool.log import CUS_LOGGER

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "tool" / "divine_treasure"))  # 面具/图鉴模块已归入子包；worker 子进程的 sys.path[0] 只有仓库根
STATES = ("home", "mode", "regular", "ranked", "practice", "masks")


def read_rows(image, ocr):
    rows = []
    for box, (text, confidence) in ocr.ocr(image):
        if confidence >= 0.7:
            center = np.mean(box, axis=0)
            rows.append((re.sub(r"\s+", "", text), int(center[0]), int(center[1])))
    return rows


def click_game(hwnd, rect, target):
    import pyautogui
    import win32api
    import win32con
    import win32gui

    from tool.utils.game_window import get_client_screen_rect

    if win32api.GetAsyncKeyState(win32con.VK_F8) & 0x8000:
        raise InterruptedError("F8 pressed")
    if win32gui.GetForegroundWindow() != hwnd or get_client_screen_rect(hwnd) != rect:
        raise RuntimeError("Game focus or geometry changed during recognition")
    x, y = target
    pyautogui.click(rect[0] + round(x * (rect[2] - rect[0]) / 1920),
                    rect[1] + round(y * (rect[3] - rect[1]) / 1080))


def inspect_screen(image, ocr):
    image = cv2.resize(image, (1920, 1080))
    rows = read_rows(image, ocr)

    def find(text, rect):
        x0, y0, x1, y1 = rect
        return next(((x, y) for value, x, y in rows
                     if text in value and x0 <= x <= x1 and y0 <= y <= y1), None)

    header = (0, 0, 400, 160)
    bottom = (650, 930, 1900, 1040)
    state, target, protocol = "unknown", None, None
    if find("欢愉假面", header) and sum(
        "面具" in value and 200 < y < 850 for value, _, y in rows
    ) >= 2:
        state = "masks"
    elif find("差分宇宙", header) and find("开始游戏", bottom):
        state, target = "home", find("开始游戏", bottom)
    elif find("模式选择", header) and find("常规演算", (0, 200, 750, 480)):
        state, target = "mode", find("常规演算", (0, 200, 750, 480))
    elif find("常规演算", header) and find("进入星阶模式", bottom):
        state, target = "regular", find("进入星阶模式", bottom)
    elif find("星阶模式", header) and find("启动", bottom):
        target = find("练习模式", (960, 100, 1260, 180))
        # 样本4/5：练习页右侧标签为白底，且中央显示不影响星阶。
        selected = float(image[128:151, 990:1020].mean()) > 200
        if target and selected and find("不影响星阶", (650, 580, 1280, 720)):
            state, target = "practice", find("启动", bottom)
            digit_crop = image[873:930, 984:1040]
            digits = [re.sub(r"\s+", "", text) for _, (text, score) in ocr.ocr(digit_crop)
                      if score >= 0.7]
            if len(digits) == 1 and digits[0].isdigit():
                protocol = int(digits[0])
        elif target and not selected:
            state = "ranked"
    return {"state": state, "target": target, "protocol": protocol, "rows": rows}


def save_evidence(output, name, image, result):
    output.mkdir(parents=True, exist_ok=True)
    cv2.imencode(".png", image)[1].tofile(output / f"{name}.png")
    (output / f"{name}.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def capture_game():
    import win32api
    import win32con
    import win32gui
    from PIL import ImageGrab

    from tool.utils.game_window import get_client_screen_rect, is_usable_game_window

    if win32api.GetAsyncKeyState(win32con.VK_F8) & 0x8000:
        raise InterruptedError("F8 pressed")
    hwnd = win32gui.GetForegroundWindow()
    if not is_usable_game_window(hwnd):
        raise RuntimeError("Game must remain in the foreground; stopped without clicking")
    rect = get_client_screen_rect(hwnd)
    width, height = rect[2] - rect[0], rect[3] - rect[1]
    if abs(width / height - 16 / 9) > 0.015:
        raise RuntimeError(f"Expected a 16:9 game client, got {width}x{height}")
    image = cv2.cvtColor(np.asarray(ImageGrab.grab(bbox=rect, all_screens=True)), cv2.COLOR_RGB2BGR)
    return image, hwnd, rect


def enter_universe(ocr, output):
    """首页 → 面具页。

    状态驱动：每帧只认屏幕当前是什么界面，不记录「第几步」，也不预期下一步是谁。
    界面乱序、重复出现或卡住都不会误点；加新界面只需往 handlers 加一行。
    """
    import win32api
    import win32con

    from tool.divine_treasure.flow import FlowDone, run_flow

    ctx = {"hwnd": None, "rect": None, "image": None, "sequence": 0, "last_state": None}

    def capture():
        image, hwnd, rect = capture_game()
        ctx["hwnd"], ctx["rect"], ctx["image"] = hwnd, rect, image
        return image

    def on_frame(snapshot, image):
        ctx["image"] = image
        if snapshot["state"] != ctx["last_state"]:
            ctx["last_state"] = snapshot["state"]
            CUS_LOGGER.debug(f"Observed: {snapshot['state']}", extra={"flush": True})
            save_evidence(output, f"{ctx['sequence']:02d}-{snapshot['state']}", image, snapshot)
            ctx["sequence"] += 1

    def click(snapshot):
        if snapshot["target"] is not None:
            CUS_LOGGER.debug(f"Click: {snapshot['state']} at {snapshot['target']}", extra={"flush": True})
            click_game(ctx["hwnd"], ctx["rect"], snapshot["target"])

    def click_practice(snapshot):
        if snapshot["protocol"] != 5:
            raise RuntimeError(f"Protocol must be 5, observed {snapshot['protocol']}; no adjustment made")
        click(snapshot)

    def on_masks(snapshot):
        CUS_LOGGER.debug("SUCCESS: mask selection detected; no mask selected", extra={"flush": True})
        raise FlowDone()

    handlers = {"home": click, "mode": click, "regular": click,
                "ranked": click, "practice": click_practice, "masks": on_masks}

    try:
        run_flow(capture, lambda image: inspect_screen(image, ocr), handlers,
                 on_frame=on_frame, cooldown=2.0, unknown_timeout=20.0)
    except TimeoutError:
        if ctx["image"] is not None:
            save_evidence(output, "timeout-last-frame", ctx["image"], {"state": ctx["last_state"]})
        raise
    finally:
        # 仅使用短点击；即使异常也释放本脚本可能按下的左键。
        win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, 0, 0)


def main(default_stage="entry"):
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--samples", type=Path, help="Offline recognition only, never sends input")
    mode.add_argument("--run", action="store_true", help="One bounded sequence; F8 stops input")
    mode.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--stage", choices=("entry", "masks", "opening", "gallery"), default=default_stage,
                        help="entry stops at masks; masks/opening retry until a preferred opening or the time limit")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.samples and args.stage not in ("entry", "masks"):
        parser.error("--samples supports entry or masks only")
    output = (args.output or ROOT / "logs" / f"divine-{args.stage}-{time.time_ns()}").resolve()
    sample_dir = args.samples.resolve() if args.samples else None
    os.chdir(ROOT)
    if args.run:
        import win32api
        import win32con

        CUS_LOGGER.debug(f"Stage: {args.stage}\nOutput: {output}\nFocus the matching start screen within 5 seconds. F8 or switching away stops.", extra={"flush": True})
        time.sleep(5)
        worker = subprocess.Popen(
            [sys.executable, str(ROOT / "divine_treasure_entry.py"), "--worker", "--stage", args.stage,
             "--output", str(output)],
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        try:
            limit = 150 if args.stage == "entry" else 240
            deadline = time.monotonic() + limit
            while worker.poll() is None:
                if win32api.GetAsyncKeyState(win32con.VK_F8) & 0x8000:
                    raise InterruptedError("F8 pressed")
                if time.monotonic() >= deadline:
                    raise TimeoutError(f"{limit}-second hard limit reached")
                time.sleep(0.1)
            return worker.returncode
        except (TimeoutError, InterruptedError, KeyboardInterrupt) as error:
            CUS_LOGGER.error(f"STOPPED: {type(error).__name__}", extra={"flush": True})
            return 2
        finally:
            if worker.poll() is None:
                worker.kill()
                worker.wait(timeout=5)
                win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, 0, 0)
                win32api.keybd_event(win32con.VK_ESCAPE, 0, win32con.KEYEVENTF_KEYUP, 0)

    from tool.onnxocr.onnx_paddleocr import ONNXPaddleOcr

    ocr = ONNXPaddleOcr(use_angle_cls=False, cpu=True)
    if sample_dir:
        if args.stage == "masks":
            from divine_treasure_masks import SAMPLE_STATES
            from divine_treasure_masks import inspect_screen as inspect_masks

            summary = []
            for number, expected in enumerate(SAMPLE_STATES, 1):
                paths = [p for p in sample_dir.glob("*.png") if re.match(rf"^{number}\D", p.name)]
                if len(paths) != 1:
                    raise ValueError(f"Expected one sample {number}, found {len(paths)}")
                image = cv2.imdecode(np.fromfile(paths[0], dtype=np.uint8), cv2.IMREAD_COLOR)
                result = inspect_masks(image, ocr)
                save_evidence(output, f"sample-{number}", image, result)
                passed = result["state"] == expected
                summary.append(passed)
                CUS_LOGGER.debug(f"Sample {number}: {result['state']}, {'PASS' if passed else 'FAIL'}", extra={"flush": True})
            return 0 if all(summary) else 1
        summary = []
        for number, expected in enumerate(STATES[:5], 1):
            paths = list(sample_dir.glob(f"{number}*.png"))
            if len(paths) != 1:
                raise ValueError(f"Expected exactly one sample numbered {number}, found {len(paths)}")
            image = cv2.imdecode(np.fromfile(paths[0], dtype=np.uint8), cv2.IMREAD_COLOR)
            result = inspect_screen(image, ocr)
            save_evidence(output, f"sample-{number}", image, result)
            passed = result["state"] == expected and (number != 5 or result["protocol"] == 5)
            summary.append(passed)
            CUS_LOGGER.debug(f"Sample {number}: {result['state']}, protocol={result['protocol']}, {'PASS' if passed else 'FAIL'}", extra={"flush": True})
        CUS_LOGGER.debug(f"Offline evidence: {output}", extra={"flush": True})
        return 0 if all(summary) else 1
    try:
        if args.stage in ("entry", "opening"):
            enter_universe(ocr, output / "entry")
        if args.stage in ("masks", "opening"):
            from divine_treasure_masks import run

            attempt = 1
            deadline = time.monotonic() + 240
            while time.monotonic() < deadline:
                result = run(ocr, output / f"attempt-{attempt:02d}" / "masks")
                if not result["restart"]:
                    break
                if time.monotonic() >= deadline:
                    raise TimeoutError("Opening retry time limit reached")
                attempt += 1
                CUS_LOGGER.debug(f"Restarting opening: attempt {attempt}", extra={"flush": True})
                enter_universe(ocr, output / f"attempt-{attempt:02d}" / "entry")
            else:
                raise TimeoutError("Opening retry time limit reached")
        if args.stage == "gallery":
            from collect_snow_masks import run

            run(ocr, output)
        return 0
    except Exception as error:
        output.mkdir(parents=True, exist_ok=True)
        (output / "error.txt").write_text(f"{type(error).__name__}: {error}\n", encoding="utf-8")
        CUS_LOGGER.error(f"STOPPED: {error}\nEvidence: {output}", extra={"flush": True})
        return 2


if __name__ == "__main__":
    sys.exit(main())
