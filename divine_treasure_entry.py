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
PROTOCOL_BOX = (672, 1246, 879, 953)  # 练习模式页底部「阈值协议 ▼ N」整条，只从中提取数字
PROTOCOL_MINUS = (731, 902)           # 阈值协议左侧「−」
PROTOCOL_PLUS = (1142, 902)           # 阈值协议右侧「+」
PROTOCOL_RANGE = (1, 9)               # 协议可选范围，越界时钳制
DEFAULT_PROTOCOL = 4                  # 默认目标协议，可用 --protocol 覆盖
# 默认取 4 而不是 5：协议效果逐级叠加，N5 相对 N4 只多「第一位面 1 次惊世奇迹」，代价是
# 面具愿力需求与方程祝福需求提高；而刷图鉴时战斗时间占比很低，N5 更肉的敌人几乎无感，
# 对刷事件真正有用的是区域数量（N4 起已给足）。评估见 canon/divine-treasure/_02-乐园漫记玩法.md
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
    foreground_grace = 30      # 失焦容忍帧数，约十几秒，给用户切回窗口的时间
    action_groups = None       # None = 跑 JSON 里全部组
    target_protocol = DEFAULT_PROTOCOL  # 目标阈值协议，由 --protocol 覆盖
    _foreground_misses = 0
    _miss_count = 0

    def run_static(self, json_path=None, json_file=None, action_list=None, skip_check=False):
        # 按 --stage 指定的组运行，便于只验证当次改动的那一段
        name, result = self.match_actions(json_path, json_file, action_list or self.action_groups, skip_check)
        if not name:
            # 连续认不出界面时把当前 OCR 到的文字和位置打出来，方便判断卡在哪一页
            self._miss_count += 1
            if self._miss_count % 10 == 1:
                items = [(item["raw_text"], [int(v) for v in item["box"]]) for item in self.ts.res]
                CUS_LOGGER.debug(f"未匹配到任何规则，共 {len(items)} 条：{items}", extra={"flush": True})
        else:
            self._miss_count = 0
        return name, result

    def get_screen(self):
        import win32api
        import win32con

        from tool.utils.game_window import (
            get_foreground_game_window,
            set_game_foreground,
        )

        if win32api.GetAsyncKeyState(win32con.VK_F8) & 0x8000:
            CUS_LOGGER.error("F8 pressed, stopping")
            self.stop()
        elif self.require_foreground:
            # 从终端启动时前台是终端，游戏被抢焦点；这里给十几帧宽限并主动拉回，
            # 不要一失焦就停（用户敲完命令再切回游戏需要时间）
            if get_foreground_game_window() is None:
                self._foreground_misses += 1
                if self._foreground_misses > self.foreground_grace:
                    CUS_LOGGER.error("游戏窗口长时间不在前台，停止")
                    self.stop()
                elif self._foreground_misses % 10 == 1:
                    set_game_foreground()
            else:
                self._foreground_misses = 0
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

    def ensure_practice_mode(self):
        """确保当前在「练习模式」页。

        ranked 与 practice 两页都有「启动」按钮和「阈值协议」，只靠文字区分不开；
        但练习页中部显示「该模式不影响星阶」，拓星页显示「你已至星之尽头」。
        在拓星页误点「启动」会真的影响星阶，所以这一步不能省。
        """
        if any("不影响星阶" in item["raw_text"] for item in self.ts.res):
            return
        items = self.ts.find_with_box([960, 1260, 100, 180], redundancy=10)
        for item in items:
            if "练习模式" in item["raw_text"]:
                box = item["box"]
                CUS_LOGGER.debug("当前不在练习模式，切换标签", extra={"flush": True})
                self.click_position(((box[0] + box[1]) / 2, (box[2] + box[3]) / 2))
                key_mouse_manager.wait()
                time.sleep(0.8)
                return
        CUS_LOGGER.warning("未找到「练习模式」标签，按当前页面继续", extra={"flush": True})

    def read_protocol(self):
        """读当前阈值协议，读不到返回 None。"""
        # find_with_box 用的是最近一次 forward 的结果，这里先刷新一帧再取
        self.ts.forward(self.get_screen())
        items = self.ts.find_with_box(list(PROTOCOL_BOX), redundancy=10)
        digits = "".join(ch for item in items for ch in item["raw_text"] if ch.isdigit())
        return int(digits) if digits else None

    def check_protocol(self):
        """把阈值协议调整到 self.target_protocol（1~9）。

        每局都读一次当前值再按需点 +/− ：游戏会记住上次选择，通常第一次调整后就一直
        相等，不会再点。识别不到数字时只告警并继续，避免把整条入场卡在练习页。
        """
        target = self.target_protocol
        if target is None:
            return
        for _ in range(12):  # 1~9 最大跨度 8 次，留一点余量
            current = self.read_protocol()
            if current is None:
                CUS_LOGGER.warning("未识别到阈值协议数字，跳过调整继续启动", extra={"flush": True})
                return
            if current == target:
                return
            point = PROTOCOL_PLUS if current < target else PROTOCOL_MINUS
            CUS_LOGGER.debug(f"阈值协议 {current} → {target}，点击{'加号' if point == PROTOCOL_PLUS else '减号'}",
                             extra={"flush": True})
            self.click_position(point)
            key_mouse_manager.wait()
            time.sleep(0.35)
        CUS_LOGGER.warning(f"阈值协议未能调整到 {target}，按当前值继续启动", extra={"flush": True})


def main(default_stage="entry"):
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--samples", type=Path, help="Offline recognition only, never sends input")
    mode.add_argument("--run", action="store_true", help="One bounded sequence; F8 stops input")
    mode.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--stage", choices=("entry", "team", "masks", "opening", "gallery"), default=default_stage,
                        help="entry: 全流程到面具页；team: 只验证配队那一段；masks/opening: 开局筛选")
    parser.add_argument("--protocol", type=int, default=DEFAULT_PROTOCOL,
                        help=f"目标阈值协议（{PROTOCOL_RANGE[0]}~{PROTOCOL_RANGE[1]}），默认 {DEFAULT_PROTOCOL}")
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
    kernel.target_protocol = max(PROTOCOL_RANGE[0], min(PROTOCOL_RANGE[1], args.protocol))
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
