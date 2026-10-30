"""手动录图工具：人在房间内手动走路，脚本自动记录地图并标注交互点。

> 本文件由 AI 辅助实现（DeepSeek），并经单元测试与真机验证后提交。
>
> **适用范围**：仅支持非战斗房间——事件（event）/ 休整（rest）/ 交易（trade）。
> 战斗房间走原生录图流程（敌人红点、技能与战斗寻路语义不同），本工具不适用。

解决场景：或自动探路一直找不到交互点。
用户需要站进房间后运行本脚本，完整手动走一遍事件关路线：
- 脚本自动保存 init.jpg（房间识别快照）；
- 自动跟踪你的位置并画成蓝色路径（你绕开桌子的走法就是最佳路线）；
- 每次画面出现交互提示（交互文字左侧的对话图标）时：
  **第 1 次 = 黄绿交互点，第 2 次 = 黄色终点**
  （支持"事件点 + 觐见装置"的双交互流程；多余的会被忽略）；
- 交互提示消失后且间隔超过 3 秒，才会认下一次，避免同一提示被重复记录；
- 事件对话等界面打开时自动暂停记录（通过 big_world 图标判断），
  不会把界面画面当轨迹录进去；
- 走完全部流程后，在命令行窗口按回车结束：只要有交互点就自动转正。

用法（房间类型：event / rest / trade）：
    uv run python tool/scripts/manual_record_map.py event

注意：
- 需要 1920x1080 的本地或云游戏窗口，简体中文，无遮挡；
- **请在正常进入房间后（站在出生点）立即开始录制**；暂离重进会改变
  出生点，导致地图起点与回放时的真实起点不一致；
- 运行期间不要打开任何覆盖小地图/交互提示区域的界面；
- 走到交互点后请自己按游戏内交互键（默认 F）继续流程（脚本只记录，不代按）；
- 走完全部流程后回到本窗口按回车：脚本会写入绿色起点、蓝色连续路线、
  黄绿交互点与纯黄终点（路线尽头），然后自动转正目录。
"""

import msvcrt
import os
import random
import sys
import time
from collections import deque

import cv2 as cv
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from route import PATHS  # noqa: E402
from tool.mask import MASK  # noqa: E402
from tool.screenshot import Screen  # noqa: E402
from tool.utils.game_window import (  # noqa: E402
    find_game_window,
    get_client_screen_rect,
)
from tool.utils.image_tool import (  # noqa: E402
    find_image_by_name,
    load_all_images_from_directory,
)
from tool.utils.minimap_util import (  # noqa: E402
    MINIMAP_RADIUS,
    POSITION_SEARCH_SCALE,
    get_minimap,
    re_get_position,
)
from tool.utils.mminimap import PositionPredict  # noqa: E402

# 交互提示检测参数（识别区域与 UniverseUtils.check("interact", mask=MASK["interact_icon"]) 一致）
INTERACT_THRESHOLD = 0.96
# big_world 图标：屏幕右侧中部偏下的鼠标右键提示图标，仅在"可自由行动"时可见，用于暂停录制
# 坐标按 1920x1080 截图记录，原点在左上角
WORLD_X = 1801
WORLD_Y = 941
WORLD_THRESHOLD = 0.98
CROP_PAD = 60
SCREEN_W = 1920
SCREEN_H = 1080

# 轨迹采样、交互提示状态机与录制时长
TRACE_STEP = 8.0
INTERACT_MIN_INTERVAL = 3.0    # 两次交互记录之间的最小间隔（配合“提示消失后”判定防重复）
MAX_SECONDS = 600

MAP_ROOTS = {
    "event": os.path.join(PATHS["image"], "event_nmaps"),
    "rest": os.path.join(PATHS["image"], "rest_nmaps"),
    "trade": os.path.join(PATHS["image"], "trade_nmaps"),
}


def check_icon(screen, name, threshold, x=None, y=None, region=None):
    """检测画面指定位置或识别区域是否出现目标图标。返回 (是否出现, 相似度)。"""
    target = find_image_by_name(name)
    if target is None:
        return False, -1.0
    if region is not None:
        local = screen[region[2]: region[3], region[0]: region[1], :]
    else:
        height, width = target.shape[0], target.shape[1]
        sx, sy = height + CROP_PAD, width + CROP_PAD
        bx = int(x)
        by = int(y)
        local = screen[
            max(0, by - sx // 2): min(SCREEN_H, by + sx // 2),
            max(0, bx - sy // 2): min(SCREEN_W, bx + sy // 2),
            :,
        ]
    result = cv.matchTemplate(local, target, cv.TM_CCORR_NORMED)
    _, max_val, _, _ = cv.minMaxLoc(result)
    return max_val > threshold, max_val


def new_map_dir(map_root):
    while True:
        name = "my_" + str(random.randint(0, 99999))
        path = os.path.join(map_root, name)
        try:
            os.makedirs(path)
            return name, path + os.sep
        except FileExistsError:
            continue


def update_cut(cut_pos, position, big):
    """复制 cut_map 的扩张逻辑：以当前位置为圆心 93px 半径逐步扩张。"""
    radius = 93
    x_limit, y_limit = big.shape[1], big.shape[0]
    pos = re_get_position(position, need_int=False)
    if cut_pos is None:
        return [
            max(0, pos[0] - radius * POSITION_SEARCH_SCALE),
            min(x_limit, pos[0] + radius * POSITION_SEARCH_SCALE),
            max(0, pos[1] - radius * POSITION_SEARCH_SCALE),
            min(y_limit, pos[1] + radius * POSITION_SEARCH_SCALE),
        ]
    left, right, top, bottom = cut_pos
    return [
        max(0, min(left, pos[0] - radius * POSITION_SEARCH_SCALE)),
        min(x_limit, max(right, pos[0] + radius * POSITION_SEARCH_SCALE)),
        max(0, min(top, pos[1] - radius * POSITION_SEARCH_SCALE)),
        min(y_limit, max(bottom, pos[1] + radius * POSITION_SEARCH_SCALE)),
    ]


def write_map(map_file, big, cut_pos, start_pos, trace, interactions, map_number, end_pos=None):
    """把轨迹画成蓝色连续线、交互点画成黄绿小点、终点画成纯黄小点。

    与示例一致的标注约定：绿色起点 / 蓝色路径 / 黄绿交互点 / 纯黄终点
    （事件房间没有攻击目标，不画红色攻击点）。
    """
    left, right, top, bottom = (
        int(cut_pos[0]), int(cut_pos[1]), int(cut_pos[2]), int(cut_pos[3])
    )
    if right <= left or bottom <= top:
        return
    color = cv.cvtColor(big, cv.COLOR_GRAY2BGR)

    def to_px(point):
        x, y = re_get_position(point)
        return int(x), int(y)

    def inside(x, y):
        return left <= x < right and top <= y < bottom

    start_x, start_y = to_px(start_pos)
    if inside(start_x, start_y):
        cv.circle(color, (start_x, start_y), 1, (0, 255, 0), -1)
    # 蓝色路线：细线（线宽 1，非抗锯齿保持纯色可被解析器识别）
    line_pts = []
    for point in trace:
        x, y = to_px(point)
        if inside(x, y):
            line_pts.append((x, y))
    if len(line_pts) >= 2:
        deduped = [line_pts[0]]
        for point in line_pts[1:]:
            if max(
                abs(point[0] - deduped[-1][0]), abs(point[1] - deduped[-1][1])
            ) >= 2:
                deduped.append(point)
        if len(deduped) >= 2:
            poly = np.array(deduped, dtype=np.int32)
            cv.polylines(color, [poly], False, (255, 0, 0), thickness=1)
        line_pts = deduped
    for point in line_pts:
        cv.circle(color, point, 1, (255, 0, 0), -1)
    # 黄绿交互点 / 纯黄终点：小点（半径 1），目标图存 PNG 无损保证可解析
    for point in interactions:
        x, y = to_px(point)
        if inside(x, y):
            cv.circle(color, (x, y), 1, (29, 230, 181), -1)
    if end_pos is not None:
        x, y = to_px(end_pos)
        if inside(x, y):
            cv.circle(color, (x, y), 1, (0, 242, 255), -1)
    for name in os.listdir(map_file):
        if name.startswith("map_") or name.startswith("target_"):
            os.remove(os.path.join(map_file, name))
    quality = [cv.IMWRITE_JPEG_QUALITY, 100]
    cv.imwrite(
        map_file + f"map_{map_number}_({start_pos[0]},{start_pos[1]}).jpg",
        big[top:bottom, left:right],
        quality,
    )
    # 目标标注图用 PNG 无损保存：颜色精确、点位完整，解析器/回放均兼容
    cv.imwrite(map_file + f"target_{left}_{top}.png", color[top:bottom, left:right])


def promote_dir(map_file):
    old_dir = map_file.rstrip("/\\")
    old_name = os.path.basename(old_dir)
    root = os.path.dirname(old_dir)
    while True:
        new_name = str(random.randint(100000, 999999))
        new_dir = os.path.join(root, new_name)
        if not os.path.exists(new_dir):
            break
    os.rename(old_dir, new_dir)
    print(f"[manual_record] 地图目录已由 {old_name} 转正为 {new_name}")
    return new_name


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in MAP_ROOTS:
        print("用法: uv run python tool/scripts/manual_record_map.py event|rest|trade")
        return 1
    map_root = MAP_ROOTS[sys.argv[1]]
    load_all_images_from_directory(PATHS["image"])

    window = find_game_window(prefer_foreground=True)
    if window is None:
        print("[manual_record] 未找到游戏窗口（崩坏：星穹铁道，1920x1080，需置于前台）")
        return 1
    left, top, _, _ = get_client_screen_rect(window.hwnd)
    screen_cap = Screen()
    print(f"[manual_record] 已定位游戏窗口 ({left},{top})，开始录制，去走一圈吧")

    predictor = PositionPredict()
    cut_pos = None
    trace = []
    interactions = []
    start_pos = None
    map_name = None
    map_file = None

    def capture():
        return screen_cap.grab(left, top)

    screen = capture()
    best = predictor.match_multiple_maps(screen)
    position = best.get("position")
    if position is None:
        print("[manual_record] 定位失败：小地图不可见或不在可识别地图范围内")
        return 1
    # 起点：站在出生点多帧采样取中值，抑制低相似度地图的定位噪声
    samples = [np.round(position, 1)]
    for _ in range(6):
        time.sleep(0.35)
        pos, _ = predictor.update_position(capture())
        samples.append(np.round(pos, 1))
    start_pos = tuple(np.median(np.array(samples), axis=0))
    print(f"[manual_record] 起点: {start_pos}（匹配地图 {best.get('map_name')}，7 帧中值）")
    map_name, map_file = new_map_dir(map_root)
    initial_map = get_minimap(screen, radius=MINIMAP_RADIUS, copy=True)
    cv.imwrite(map_file + "init.jpg", initial_map)
    print(f"[manual_record] 已创建目录 {map_name}")

    start_time = time.time()
    last_pos = None
    recent = deque(maxlen=3)
    interact_count = 0
    interact_await_clear = False
    interact_last_time = 0.0
    end_pos = None
    print("[manual_record] 走完全部流程后，回到本窗口按回车结束录制")
    while True:
        screen = capture()
        in_world, _ = check_icon(
            screen, "big_world", WORLD_THRESHOLD, WORLD_X, WORLD_Y
        )
        elapsed = int(time.time() - start_time)
        if not in_world:
            print(
                f"[manual_record] (界面中，暂停记录) 交互点{len(interactions)}个 "
                f"轨迹{len(trace)}点 用时{elapsed}s",
                end="\r",
            )
        else:
            position, sim = predictor.update_position(screen)
            recent.append(np.round(position, 1))
            # 该房间对地面特征的匹配度可能很低，定位在多个估计间跳动；
            # 取近 3 帧中值，抑制轨迹与交互点的位置噪声。
            smoothed = tuple(np.median(np.array(recent), axis=0))
            position = smoothed
            end_pos = position
            if last_pos is None or np.linalg.norm(
                np.array(position) - np.array(last_pos)
            ) >= TRACE_STEP:
                trace.append(position)
                last_pos = position
            big = predictor.assets_floor_feat
            if big is not None:
                cut_pos = update_cut(cut_pos, position, big)
                write_map(
                    map_file, big, cut_pos, start_pos, trace, interactions,
                    predictor.map_num, end_pos,
                )
            found_interact, interact_sim = check_icon(
                screen, "interact", INTERACT_THRESHOLD, region=MASK["interact_icon"]
            )
            if not found_interact:
                # 交互提示消失后，才允许认下一次（防止同一提示被重复记录）
                interact_await_clear = False
            elif (
                not interact_await_clear
                and time.time() - interact_last_time > INTERACT_MIN_INTERVAL
            ):
                # 新的一次交互：第 1 次 = 黄绿交互点，第 2 次 = 黄色终点
                interact_count += 1
                interact_last_time = time.time()
                interact_await_clear = True
                if interact_count == 1:
                    interactions.append(position)
                    print(f"\n[manual_record] 第1次交互（黄绿交互点）已标注: {position}")
                elif interact_count == 2:
                    end_pos = position
                    print(f"\n[manual_record] 第2次交互（黄色终点）已标注: {position}")
                else:
                    print(f"\n[manual_record] 第{interact_count}次交互 已忽略（仅保留交互点与终点）")
            print(
                f"[manual_record] 位置{position} 交互图标相似度{interact_sim:.2f} "
                f"交互点{len(interactions)}个 轨迹{len(trace)}点 用时{elapsed}s",
                end="\r",
            )
        if msvcrt.kbhit() and msvcrt.getch() in (b"\r", b"\n"):
            print()
            break
        if elapsed > MAX_SECONDS:
            print()
            break
        time.sleep(0.3)

    big = predictor.assets_floor_feat
    if big is not None and cut_pos is not None:
        write_map(
            map_file, big, cut_pos, start_pos, trace, interactions,
            predictor.map_num, end_pos,
        )
    if interactions or end_pos is not None:
        promote_dir(map_file)
        print(
            f"[manual_record] 完成！交互点 {len(interactions)} 个"
            f"{'、黄色终点 1 个' if end_pos is not None else ''}，"
            "下次脚本进入该房间将自动按此地图寻路。"
        )
        return 0
    print(
        f"[manual_record] 未检测到任何F，地图（仅路径）已保存至 {map_name}，"
        "可下次续录或人工补交互点"
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
