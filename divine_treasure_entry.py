"""差分宇宙入场、单轮开局和图鉴采集入口。

入场部分不再自建状态机：界面识别与动作写在 `tool/divine_treasure/actions/divine_treasure.json`，
由 `core/common/runtime.py::ScriptKernel` 的 `match_actions` 驱动；本文件只提供两条
需要程序逻辑的动作（配队、协议校验）。
"""

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

from core.common.runtime import ScriptKernel
from tool.GLOBAL import key_mouse_manager
from tool.log import CUS_LOGGER

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "tool" / "divine_treasure"))  # 面具/图鉴模块已归入子包；worker 子进程的 sys.path[0] 只有仓库根
STATES = ("home", "mode", "regular", "ranked", "practice", "masks")

# 队伍槽位（「常规演算」页底部）：第一个槽位为空就说明还没配队。
# 首次使用前需要在游戏里组好队 → 保存为「预设编队」→ 收藏置顶，脚本会点第一个预设。
TEAM_SLOT_POINT = (1149, 967)     # 空槽位，点它弹出「下载角色」面板
TEAM_PRESET_TAB = (425, 132)      # 面板顶部「预设编队」标签
TEAM_PRESET_FIRST = (299, 279)    # 预设列表第一个（即收藏置顶那支）
TEAM_EMPTY_SLOT_BOX = (1112, 1186, 931, 1004)  # 空槽位图标的搜索区 [x1, x2, y1, y2]
TEAM_EMPTY_TEMPLATE = str(ROOT / "tool" / "divine_treasure" / "assets" / "team_empty_slot.png")  # 必须是绝对路径：
# find_image_by_name 对带 "/" 的相对路径会拼到 resource/imgs 下，导致永远读不到
PROTOCOL_BOX = (984, 1040, 873, 930)  # 练习模式页的阈值协议数字
ACTION_SCRIPT = ROOT / "tool" / "divine_treasure" / "actions" / "divine_treasure.json"
_TEAM_EMPTY_TEMPLATE = None


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


def team_empty_template():
    """空槽位图标模板，懒加载。

    首次使用时需要在游戏里：组一支队 → 保存为「预设编队」→ 给它点收藏置顶，
    否则脚本会把空槽位当成「队伍没配」而去点预设列表的第一个，可能点到意料外的队伍。
    """
    global _TEAM_EMPTY_TEMPLATE
    if _TEAM_EMPTY_TEMPLATE is None:
        path = ROOT / "tool" / "divine_treasure" / "assets" / "team_empty_slot.png"
        # 中文路径用 imdecode，cv2.imread 在 Windows 上会读失败
        _TEAM_EMPTY_TEMPLATE = cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), cv2.IMREAD_COLOR)
    return _TEAM_EMPTY_TEMPLATE


def match_in_box(image, template, box, threshold=0.8):
    """在 box=[x1, x2, y1, y2] 区域内匹配模板。

    Returns:
        命中返回 (score, (x, y))（坐标为区域内的中心点，1920×1080 基准），否则 None。
    """
    x1, x2, y1, y2 = box
    if template is None:
        return None
    roi = image[y1:y2, x1:x2]
    if roi.size == 0:
        return None
    result = cv2.matchTemplate(roi, template, cv2.TM_CCOEFF_NORMED)
    _, max_val, _, max_loc = cv2.minMaxLoc(result)
    if max_val < threshold:
        return None
    height, width = template.shape[:2]
    return max_val, (x1 + max_loc[0] + width // 2, y1 + max_loc[1] + height // 2)


def inspect_screen(image, ocr):
    """离线识别（--samples 用）。在线流程由 JSON 触发器完成同样的判断。"""
    image = cv2.resize(image, (1920, 1080))
    rows = read_rows(image, ocr)

    def find(text, rect):
        x0, y0, x1, y1 = rect
        return next(((x, y) for value, x, y in rows
                     if text in value and x0 <= x <= x1 and y0 <= y <= y1), None)

    header = (0, 0, 400, 160)
    bottom = (650, 930, 1900, 1040)
    state, target, protocol, team_empty = "unknown", None, None, False
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
        team_empty = match_in_box(image, team_empty_template(), TEAM_EMPTY_SLOT_BOX) is not None
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
    return {"state": state, "target": target, "protocol": protocol,
            "team_empty": team_empty, "rows": rows}


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


class DivineTreasureKernel(ScriptKernel):
    """入场内核：界面识别与动作由 `actions/divine_treasure.json` 驱动。

    只补两条需要程序逻辑的动作；其余「识别到某界面就点某个按钮」全部写在 JSON 里。
    """

    window_timeout = 5        # 测试用短等待；正式运行可调回 300
    require_foreground = True  # 游戏窗口切走就停
    action_groups = None       # None = 跑 JSON 里全部组

    def run_static(self, json_path=None, json_file=None, action_list=None, skip_check=False):
        # 按 --stage 指定的组运行，便于只验证当次改动的那一段
        return self.match_actions(json_path, json_file, action_list or self.action_groups, skip_check)

    def get_screen(self):
        import win32api
        import win32con

        from tool.utils.game_window import get_foreground_game_window

        if win32api.GetAsyncKeyState(win32con.VK_F8) & 0x8000:
            CUS_LOGGER.error("F8 pressed, stopping")
            self.stop()
        elif self.require_foreground and get_foreground_game_window() is None:
            CUS_LOGGER.error("游戏窗口不在前台，停止")
            self.stop()
        return super().get_screen()

    def fill_team(self):
        """队伍为空时套用预设编队：空槽位 → 预设编队标签 → 预设列表第一个。"""
        if not self.check(TEAM_EMPTY_TEMPLATE, mask=TEAM_EMPTY_SLOT_BOX):
            return
        CUS_LOGGER.debug("队伍为空：空槽位 → 预设编队 → 第一个预设", extra={"flush": True})
        for point, wait in ((TEAM_SLOT_POINT, 1.2), (TEAM_PRESET_TAB, 0.8), (TEAM_PRESET_FIRST, 1.0)):
            self.click_position(point)
            key_mouse_manager.wait()
            time.sleep(wait)
        # 面板不会自动关闭，但也不遮挡「进入星阶模式」，后续动作照常点击

    def check_protocol(self):
        """练习模式的阈值协议必须是 5，否则就地停下。"""
        text = self.ts.ocr_one_row(self.get_screen(), list(PROTOCOL_BOX))
        digits = "".join(ch for ch in (text or "") if ch.isdigit())
        if digits and digits != "5":
            raise RuntimeError(f"Protocol must be 5, observed {digits}; no adjustment made")


def main(default_stage="entry"):
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--samples", type=Path, help="Offline recognition only, never sends input")
    mode.add_argument("--run", action="store_true", help="One bounded sequence; F8 stops input")
    mode.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--stage", choices=("entry", "team", "masks", "opening", "gallery"), default=default_stage,
                        help="entry: 全流程到面具页；team: 只验证配队那一段；masks/opening: 开局筛选")
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

        CUS_LOGGER.debug(f"Stage: {args.stage}\nOutput: {output}\nFocus the game within 5 seconds. F8 or switching away stops.", extra={"flush": True})
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

    if sample_dir:
        from tool.onnxocr.onnx_paddleocr import ONNXPaddleOcr

        ocr = ONNXPaddleOcr(use_angle_cls=False, cpu=True)
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

    from tool.action_script import run_script

    kernel = DivineTreasureKernel()
    if args.stage == "team":
        kernel.action_groups = ["team"]
    try:
        if args.stage in ("entry", "team"):
            run_script(kernel, str(ACTION_SCRIPT))
        if args.stage in ("masks", "opening"):
            from divine_treasure_masks import run

            attempt = 1
            deadline = time.monotonic() + 240
            while time.monotonic() < deadline:
                result = run(kernel.ts, output / f"attempt-{attempt:02d}" / "masks")
                if not result["restart"]:
                    break
                if time.monotonic() >= deadline:
                    raise TimeoutError("Opening retry time limit reached")
                attempt += 1
                CUS_LOGGER.debug(f"Restarting opening: attempt {attempt}", extra={"flush": True})
                run_script(kernel, str(ACTION_SCRIPT))
        if args.stage == "gallery":
            from collect_snow_masks import run

            run(kernel.ts, output)
        return 0
    except Exception as error:
        output.mkdir(parents=True, exist_ok=True)
        (output / "error.txt").write_text(f"{type(error).__name__}: {error}\n", encoding="utf-8")
        CUS_LOGGER.error(f"STOPPED: {error}\nEvidence: {output}", extra={"flush": True})
        return 2
    finally:
        kernel.stop()


if __name__ == "__main__":
    sys.exit(main())
