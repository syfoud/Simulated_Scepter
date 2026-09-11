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
    import win32api
    import win32con

    last_clicked = -1
    stable_state, stable_count = None, 0
    deadline = time.monotonic() + 20
    sequence = 0
    try:
        while time.monotonic() < deadline:
            image, hwnd, rect = capture_game()
            result = inspect_screen(image, ocr)
            state = result["state"]
            stable_count = stable_count + 1 if state == stable_state else 1
            if state != stable_state:
                print(f"Observed: {state}", flush=True)
                save_evidence(output, f"{sequence:02d}-{state}", image, result)
                sequence += 1
            stable_state = state
            if state != "unknown" and stable_count >= 2:
                index = STATES.index(state)
                if state == "masks":
                    if last_clicked != 4:
                        raise RuntimeError("Mask page appeared before this probe launched a run")
                    save_evidence(output, "success-masks", image, result)
                    print("SUCCESS: mask selection detected; no mask selected", flush=True)
                    return
                if index > last_clicked:
                    if index != last_clicked + 1:
                        raise RuntimeError(f"Unexpected page {state}; start from sample 1")
                    if state == "practice" and result["protocol"] != 5:
                        raise RuntimeError(f"Protocol must be 5, observed {result['protocol']}; no adjustment made")
                    print(f"Click once: {state} at {result['target']}", flush=True)
                    click_game(hwnd, rect, result["target"])
                    last_clicked = index
                    deadline = time.monotonic() + (45 if state == "practice" else 15)
                    stable_count = 0
            time.sleep(0.4)
        save_evidence(output, "timeout-last-frame", image, result)
        raise TimeoutError(f"No confirmed next page after {STATES[last_clicked] if last_clicked >= 0 else 'start'}")
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

        print(f"Stage: {args.stage}\nOutput: {output}\nFocus the matching start screen within 5 seconds. F8 or switching away stops.", flush=True)
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
            print(f"STOPPED: {type(error).__name__}", flush=True)
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
                print(f"Sample {number}: {result['state']}, {'PASS' if passed else 'FAIL'}", flush=True)
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
            print(f"Sample {number}: {result['state']}, protocol={result['protocol']}, {'PASS' if passed else 'FAIL'}", flush=True)
        print(f"Offline evidence: {output}", flush=True)
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
                print(f"Restarting opening: attempt {attempt}", flush=True)
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
        print(f"STOPPED: {error}\nEvidence: {output}", flush=True)
        return 2


if __name__ == "__main__":
    sys.exit(main())
