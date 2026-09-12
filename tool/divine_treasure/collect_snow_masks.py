"""从 ex 图鉴布局逐项采集雪鸮面具效果，保存截图、OCR 和 Markdown。"""

import re
import sys
import time

import cv2

from pathlib import Path
# 直接运行本脚本时保证能导入仓库根目录的入口模块。
REPO_ROOT = str(Path(__file__).resolve().parents[2])
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)
from divine_treasure_entry import (
    capture_game,
    click_game,
    main,
    read_rows,
    save_evidence,
)

BRANCHES = tuple(f"雪鸮面具·{suffix}" for suffix in "序破终极淬绽解霸开超")


def inspect_screen(image, ocr):
    rows = read_rows(cv2.resize(image, (1920, 1080)), ocr)
    cards, selected = {}, None
    for text, x, y in rows:
        # ex样本中选中的“序”卡片读作“雪号”，其他卡片读作“雪鸡”。
        match = re.fullmatch(r"雪[鸮鹄鸡号]面具[·.・•]?([序破终极淬绽解霸开超])", text)
        if not match:
            continue
        name = f"雪鸮面具·{match[1]}"
        if 140 < x < 1250 and 450 < y < 800:
            if name in cards:
                raise RuntimeError(f"Duplicate gallery card: {name}")
            cards[name] = (x, y)
        elif 1420 < x < 1880 and 100 < y < 180:
            selected = name
    end = next((y for text, x, y in rows if text == "适用面具" and x > 1400 and y > 360), None)
    effect = "" if end is None else "".join(
        text for text, x, y in sorted(rows, key=lambda row: (row[2], row[1]))
        if x > 1420 and 360 < y < end - 15)
    valid = (set(cards) == set(BRANCHES) and selected is not None and len(effect) >= 10
             and any(text == "惊世奇迹" and x < 400 and y < 100 for text, x, y in rows))
    return {"state": "gallery" if valid else "unknown", "cards": cards, "selected": selected,
            "effect": effect, "rows": rows}


def write_document(records, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["# 雪鸮面具分支效果", "", "游戏名称为雪鸮面具，对应需求中所称的雪鹄面具。", "",
             f"采集进度：{len(records)}/10。效果为游戏截图 OCR 原文，数字与标点仍需对照证据图校对；尚未设置策略权重。",
             "", "| 分支 | 效果 | 截图证据 |", "| --- | --- | --- |"]
    for name in BRANCHES:
        record = records.get(name)
        effect = record["effect"].replace("|", "\\|") if record else "待采集"
        source = f"[截图](<{record['source']}>)" if record else ""
        lines.append(f"| {name} | {effect} | {source} |")
    lines += ["", "## 后续权重依据", "", "先核对招聘、优化、区域等级、随机信标等效果的原文与数字，"
              "再根据事件区域增加量、触发次数和前置条件设计权重。图鉴文字不能证明实际触发收益。", ""]
    path.write_text("\n".join(lines), encoding="utf-8")


def run(ocr, output):
    import win32api
    import win32con

    records = {}
    report = output / "snow-mask-effects.md"
    write_document(records, report)
    try:
        image, hwnd, rect = capture_game()
        result = inspect_screen(image, ocr)
        save_evidence(output, "start", image, result)
        if result["state"] != "gallery":
            raise RuntimeError("Expected ex gallery layout with all ten snow-mask cards and readable details")
        for index, name in enumerate(BRANCHES, 1):
            if result["selected"] != name:
                click_game(hwnd, rect, result["cards"][name])
            deadline = time.monotonic() + 10
            stable, count = None, 0
            while time.monotonic() < deadline:
                time.sleep(0.3)
                image, current_hwnd, current_rect = capture_game()
                if current_hwnd != hwnd or current_rect != rect:
                    raise RuntimeError("Game window or geometry changed during collection")
                result = inspect_screen(image, ocr)
                signature = (result["selected"], result["effect"])
                if result["state"] == "gallery" and result["selected"] == name:
                    count = count + 1 if signature == stable else 1
                    stable = signature
                    if count >= 2:
                        evidence = f"{index:02d}"
                        save_evidence(output, evidence, image, result)
                        records[name] = {"effect": result["effect"],
                                         "source": (output / f"{evidence}.png").resolve().as_posix()}
                        write_document(records, report)
                        print(f"Collected {index}/10: {name}", flush=True)
                        break
                else:
                    stable, count = None, 0
            else:
                save_evidence(output, f"{index:02d}-timeout", image, result)
                raise TimeoutError(f"No stable matching details for {name}; partial report: {report}")
        print(f"SUCCESS: 10/10\nReport: {report}\nEvidence: {output}", flush=True)
        return records
    finally:
        win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, 0, 0)


if __name__ == "__main__":
    sys.exit(main(default_stage="gallery"))
