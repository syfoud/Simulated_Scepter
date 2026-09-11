"""完成一轮开局，保留雪鸮及目标奇迹，未命中则结算回首页。"""

import json
import re
import sys
import time

import cv2

from pathlib import Path
# 直接运行本脚本时保证能导入仓库根目录的入口模块。
REPO_ROOT = str(Path(__file__).resolve().parents[2])
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)
from divine_treasure_entry import capture_game, click_game, read_rows, save_evidence

SNOW_NAMES = ("雪鸮面具", "雪鹄面具", "雪鸡面具", "雪号面具")
SAMPLE_STATES = ("masks", "masks", "masks", "mask_selected", "mask_obtained",
                 "equations", "equation_selected", "blessings", "wonders", "wonder_selected",
                 "first_area", "pause", "settle_confirm", "settlement", "home")


def inspect_screen(image, ocr):
    image = cv2.resize(image, (1920, 1080))
    rows = read_rows(image, ocr)

    def find(text, rect):
        x0, y0, x1, y1 = rect
        return next(((x, y) for value, x, y in rows
                     if text in value and x0 <= x <= x1 and y0 <= y <= y1), None)

    state, target, selected, refresh = "unknown", None, None, None
    rerolls, reroll_target = None, None
    cards = []
    if find("欢愉假面", (0, 0, 400, 150)):
        cards = [(text, x, y) for text, x, y in rows
                 if "面具" in text and 300 < x < 900 and 300 < y < 850]
        counts = [re.fullmatch(r"([01])/1", text) for text, x, y in rows
                  if 280 < x < 430 and 900 < y < 1000]
        refresh = next((int(m[1]) for m in counts if m), None)
        target = find("确定", (1300, 900, 1850, 1030))
        selected = next((text for text, x, y in rows
                         if "面具" in text and 1050 < x < 1600 and 150 < y < 300), None)
        if len(cards) == 3:
            state = "mask_selected" if target and selected else "masks"
    elif find("点击空白处关闭", (650, 950, 1300, 1040)):
        target = (960, 1000)
        selected = next((text for text, x, y in rows
                         if "面具" in text and 600 < x < 1300 and 150 < y < 320), None)
        if selected:
            state = "mask_obtained"
        elif find("获得祝福", (650, 80, 1300, 180)):
            state = "blessings"
    elif find("请选择方程", (650, 100, 1250, 190)):
        target = find("确认", (1550, 920, 1880, 1030))
        if target:
            # 样本6/7确认按钮底色均值为28/225。
            state = "equation_selected" if image[958:980, 1580:1630].mean() > 180 else "equations"
    elif find("选择惊世奇迹", (650, 80, 1300, 190)):
        cards = [(text, x, y) for text, x, y in rows
                 if "面具" in text and 250 < x < 1700 and 450 < y < 590]
        target = find("确认", (950, 920, 1350, 1030))
        # 样本9按钮为“重随3/3”；样本10选中卡片后变成“重随0/3”。
        for text, x, y in rows:
            match = re.search(r"([0-3])/3$", text)
            if match and 550 < x < 900 and 930 < y < 1010:
                rerolls, reroll_target = int(match[1]), (x, y)
                break
        if target and cards:
            # 样本9/10确认按钮底色均值为101/175。
            state = "wonder_selected" if image[958:980, 980:1020].mean() > 140 else "wonders"
    elif find("结束并结算", (1200, 900, 1800, 1030)) and find("暂离", (1200, 830, 1800, 940)):
        state, target = "pause", find("结束并结算", (1200, 900, 1800, 1030))
    elif find("提示", (800, 350, 1150, 470)) and find("将进行结算", (450, 470, 1500, 560)):
        target = find("确认", (1050, 610, 1400, 730))
        if target:
            state = "settle_confirm"
    elif find("探索中断", (250, 300, 650, 500)) and find("返回主界面", (650, 920, 1250, 1040)):
        state, target = "settlement", find("返回主界面", (650, 920, 1250, 1040))
    elif find("差分宇宙", (0, 0, 400, 160)) and find("开始游戏", (1300, 900, 1850, 1040)):
        state = "home"
    elif any("第一位面" in text and "战斗" in text and "1/20" in text
             and x < 500 and y < 130 for text, x, y in rows) and sum(
                 1500 < x < 1900 and 300 < y < 600 for _, x, y in rows) >= 2:
        state = "first_area"
    return {"state": state, "target": target, "cards": cards, "selected": selected,
            "refresh": refresh, "rerolls": rerolls, "reroll_target": reroll_target, "rows": rows}


def run(ocr, output):
    import pyautogui
    import win32api
    import win32con
    import win32gui

    from tool.utils.game_window import get_client_screen_rect

    phase = "choose_mask"
    chosen, restart, refreshed = None, False, False
    before_refresh = None
    rerolls_used, before_reroll, chosen_wonder = 0, None, None
    stable, count, actions = None, 0, 0
    deadline = time.monotonic() + 20
    expected = {"confirm_mask": "mask_selected", "close_mask": "mask_obtained",
                "confirm_equation": "equation_selected", "close_blessings": "blessings",
                "confirm_wonder": "wonder_selected", "area": "first_area",
                "settle": "pause", "confirm_settle": "settle_confirm",
                "close_settlement": "settlement", "home": "home"}
    try:
        while time.monotonic() < deadline:
            image, hwnd, rect = capture_game()
            result = inspect_screen(image, ocr)
            state = result["state"]
            names = tuple(card[0] for card in result["cards"])
            signature = (state, names, result["selected"], result["refresh"], result["rerolls"])
            match = re.fullmatch(r"雪[鸮鹄鸡号]面具[·.・•]([序破终极淬绽解霸开超])",
                                 names[0]) if len(names) == 1 else None
            observed_wonder = match[1] if match else None
            count = count + 1 if signature == stable else 1
            stable = signature
            if state == "unknown" or count < 2:
                time.sleep(0.3)
                continue
            target, next_phase = None, None
            if phase == "after_refresh":
                if state == "masks" and result["refresh"] == 0 and names != before_refresh:
                    phase = "choose_mask"
                else:
                    time.sleep(0.3)
                    continue
            if phase == "after_reroll":
                if state == "wonders" and result["rerolls"] == before_reroll - 1:
                    phase = "choose_wonder"
                else:
                    time.sleep(0.3)
                    continue
            if phase == "choose_mask" and state == "masks":
                snow = next((card for card in result["cards"] if card[0] in SNOW_NAMES), None)
                if snow:
                    chosen, x, y = snow
                    target, next_phase = (x, y), "confirm_mask"
                elif result["refresh"] == 1 and not refreshed:
                    refreshed, before_refresh = True, names
                    target, next_phase = (168, 946), "after_refresh"
                elif result["refresh"] == 0:
                    fallback = next((card for card in result["cards"] if "点子王" not in card[0]), None)
                    if fallback is None:
                        raise RuntimeError("No ordinary fallback mask is readable")
                    chosen, x, y = fallback
                    restart = True
                    target, next_phase = (x, y), "confirm_mask"
                else:
                    raise RuntimeError("Refresh counter is unreadable or inconsistent")
            elif phase == "choose_equation" and state in ("equations", "equation_selected"):
                # 样本7选择中央方程；本阶段不设方程权重。
                target, next_phase = (960, 500), "confirm_equation"
                if state == "equation_selected":
                    target, next_phase = result["target"], "close_blessings"
            elif phase == "choose_wonder" and state in ("wonders", "wonder_selected"):
                if len(result["cards"]) != 1:
                    raise RuntimeError("Expected exactly one opening wonder; no weight selection implemented")
                if not restart and observed_wonder is None:
                    raise RuntimeError("Opening snow-mask wonder is unreadable or belongs to another mask")
                _, x, y = result["cards"][0]
                chosen_wonder = observed_wonder
                target, next_phase = (x, y), "confirm_wonder"
                if state == "wonder_selected":
                    target, next_phase = result["target"], "area"
                if not restart and chosen_wonder not in ("绽", "解", "霸"):
                    if state == "wonder_selected":
                        raise RuntimeError("Unwanted opening wonder was already selected; rerolls are unavailable")
                    remaining = result["rerolls"]
                    if remaining is None or result["reroll_target"] is None:
                        raise RuntimeError("Opening wonder reroll counter is unreadable")
                    if remaining > 0:
                        if rerolls_used >= 3:
                            raise RuntimeError("Opening wonder reroll count is inconsistent")
                        before_reroll = remaining
                        rerolls_used += 1
                        target, next_phase = result["reroll_target"], "after_reroll"
                    else:
                        restart = True
                        print("No preferred opening wonder after available rerolls; settle this run", flush=True)
            elif state == expected.get(phase):
                if phase in ("confirm_mask", "close_mask"):
                    observed = result["selected"]
                    if observed != chosen and not (observed in SNOW_NAMES and chosen in SNOW_NAMES):
                        raise RuntimeError(f"Selected mask changed: {chosen} -> {observed}")
                if phase == "confirm_wonder" and not restart and observed_wonder != chosen_wonder:
                    raise RuntimeError("Opening wonder changed before confirmation")
                if (phase == "area" and not restart) or phase == "home":
                    result.update(chosen=chosen, wonder=chosen_wonder, restart=restart,
                                  actions=actions, rerolls_used=rerolls_used)
                    save_evidence(output, "success", image, result)
                    print(f"SUCCESS: {'returned home for restart' if restart else 'snow mask and preferred wonder in first combat area'}", flush=True)
                    return result
                if phase == "area":
                    target, next_phase = "esc", "settle"
                else:
                    next_phase = {"confirm_mask": "close_mask", "close_mask": "choose_equation",
                                  "confirm_equation": "close_blessings", "close_blessings": "choose_wonder",
                                  "confirm_wonder": "area", "settle": "confirm_settle",
                                  "confirm_settle": "close_settlement", "close_settlement": "home"}[phase]
                    target = result["target"]
            if target is None:
                time.sleep(0.3)
                continue
            if actions >= 17:
                raise RuntimeError("Action limit reached")
            result.update(phase=phase, chosen=chosen, wonder=chosen_wonder, restart=restart,
                          rerolls_used=rerolls_used, action=target)
            save_evidence(output, f"{actions:02d}-{phase}", image, result)
            if time.monotonic() >= deadline:
                raise TimeoutError("Recognition exceeded the current step deadline")
            if target == "esc":
                if win32api.GetAsyncKeyState(win32con.VK_F8) & 0x8000:
                    raise InterruptedError("F8 pressed")
                if win32gui.GetForegroundWindow() != hwnd or get_client_screen_rect(hwnd) != rect:
                    raise RuntimeError("Game focus or geometry changed before Escape")
                pyautogui.press("esc")
            else:
                click_game(hwnd, rect, target)
            print(f"Action {actions + 1}: {phase} -> {next_phase}", flush=True)
            actions += 1
            phase, stable, count = next_phase, None, 0
            deadline = time.monotonic() + (45 if phase in ("area", "close_settlement", "home") else 15)
            time.sleep(0.4)
        save_evidence(output, "timeout", image, dict(result, phase=phase))
        raise TimeoutError(f"No confirmed next screen: {phase}")
    except Exception as error:
        output.mkdir(parents=True, exist_ok=True)
        (output / "state.json").write_text(json.dumps(
            {"phase": phase, "chosen": chosen, "wonder": chosen_wonder, "restart": restart,
             "rerolls_used": rerolls_used, "actions": actions, "error": str(error)},
            ensure_ascii=False, indent=2), encoding="utf-8")
        raise
    finally:
        win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, 0, 0)
        win32api.keybd_event(win32con.VK_ESCAPE, 0, win32con.KEYEVENTF_KEYUP, 0)
