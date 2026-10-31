"""货币战争备战栏识别、模板采集及补位规则，不操作真实键鼠。"""

import hashlib
import os
import tempfile
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from core.currency.settings import load_currency_settings, save_currency_settings
from tool.log import CUS_LOGGER
from tool.storage import resource_path
from tool.utils.image_tool import find_image_by_name

# 坐标均为 1920×1080 游戏截图中的 [左, 上, 右, 下]，备战栏从左到右编号。
BENCH_BOXES = tuple((383 + 125 * i, 843, 493 + 125 * i, 977) for i in range(9))
# 仅保存头像中心的 40×40 特征，不包含边框、角标和星级。
PORTRAIT_BOX = (35, 47, 75, 87)
AREA_BOXES = {
    "front": ((676, 328, 807, 465), (821, 328, 948, 465),
              (968, 328, 1095, 465), (1109, 328, 1240, 465)),
    "back": ((533, 598, 673, 737), (678, 598, 812, 737),
             (822, 598, 950, 737), (966, 598, 1095, 737),
             (1105, 598, 1238, 737), (1244, 598, 1384, 737)),
}
# 画面上的人数是前台与后台之和，上限随对局进度变化，因此不能按前台落点数校验。
TEAM_CAPACITY = len(AREA_BOXES["front"]) + len(AREA_BOXES["back"])
# 截帧时整栏会和参考图错开几像素，匹配时在四周留出搜索余量。
MATCH_MARGIN = 4
# 缩小后的比对尺度：抵消个别帧里角色画的细微缩放，避免同一角色被采集两份模板。
MATCH_SCALE = 0.4
# 同一角色的比对分数；不同角色实测不超过 0.65，同一角色位移或缩放后仍在 0.95 以上。
MATCH_THRESHOLD = 0.9
# 卡片右上角的角标：有两枚亮色笔画的黑色圆角框；漏识别角标不能作为道具证据。
# templates/badges/ 下按角标图形保存模板（front=前台、back=后台、both=前后台都能放），
# 目录里新增模板即可参与匹配；还没收录的新图形再用下面的形状规则兜底。
BADGE_BOX = (77, 0, 110, 42)  # 卡片内的 [左, 上, 右, 下]
BADGE_THRESHOLD = 0.9         # 角标模板的匹配分数；角色实测 0.98 以上，道具与空格不到 0.31
BADGE_DARK = 45               # 兜底：角标底框的亮度上限（近黑色）
BADGE_BRIGHT = 100            # 兜底：角标笔画的亮度下限（红色的格子灰度约 113）
BADGE_GLYPHS = 60             # 兜底：框内至少这么多亮色像素才算有笔画
# 角标决定这个角色能放哪个区域：上格=前台，下格=后台，实心表示可放。
BADGE_AREAS = {
    "front": ("front",),
    "back": ("back",),
    "both": ("front", "back"),
}
# 场上卡片向画面中心倾斜，四角相对各自 AREA_BOXES，顺序为左上、右上、右下、左下。
# 先还原成 110×134 的备战卡，再取同一头像，不能把透视变形当成普通缩放。
AREA_QUADS = {
    "front": (
        ((14, 0), (130, 0), (123, 136), (0, 136)),
        ((7, 0), (126, 0), (126, 136), (0, 136)),
        ((0, 0), (119, 0), (126, 136), (0, 136)),
        ((0, 0), (117, 0), (130, 136), (8, 136)),
    ),
    "back": (
        ((18, 0), (139, 0), (123, 138), (0, 138)),
        ((12, 0), (133, 0), (125, 138), (0, 138)),
        ((5, 0), (127, 0), (125, 138), (0, 138)),
        ((0, 0), (124, 0), (128, 138), (5, 138)),
        ((0, 0), (121, 0), (132, 138), (12, 138)),
        ((0, 0), (122, 0), (139, 138), (18, 138)),
    ),
}


@dataclass(frozen=True)
class BenchSlot:
    """一次截图中的备战格；template 是可用于优先级配置的模板文件名（无后缀）。"""

    index: int
    template: str
    kind: str  # character、item、empty 或 unknown；未知类型不采集也不上阵。
    areas: tuple[str, ...] = ("front", "back")  # 角标允许上阵的区域。


@dataclass(frozen=True)
class Deployment:
    """从备战栏 source 格拖到 area 区域的 target 格，编号均从 0 开始。"""

    source: int
    area: str
    target: int
    outgoing: str | None = None  # None=补空位，空字符串=尚未识别的上阵角色，其余为被替换角色。


def match_score(search, template, method=cv2.TM_CCOEFF_NORMED):
    """在 search 内滑动 template，返回最相似分数（越大越相似）。"""
    if search.shape[0] < template.shape[0] or search.shape[1] < template.shape[1]:
        return 0.0
    scores = cv2.matchTemplate(search, template, method)
    if method == cv2.TM_SQDIFF_NORMED:
        return 1.0 - float(scores.min())
    return float(scores.max())


def match_feature(patch):
    """缩小特征，让细微缩放和单像素抖动不再落到另一个模板摘要上。"""
    return cv2.resize(
        patch, None, fx=MATCH_SCALE, fy=MATCH_SCALE, interpolation=cv2.INTER_AREA
    )


def portrait_score(search, template, method=cv2.TM_CCOEFF_NORMED):
    """先按原尺寸对齐，再比对缩小后的特征。

    原尺寸定位像素位移，缩小后的特征抵消角色画在个别帧里的细微缩放，取两者较高分。
    """
    scores = cv2.matchTemplate(search, template, method)
    if method == cv2.TM_SQDIFF_NORMED:
        _, _, loc, _ = cv2.minMaxLoc(scores)
        best = 1.0 - float(scores.min())
    else:
        _, best, _, loc = cv2.minMaxLoc(scores)
    x, y = loc
    aligned = search[y:y + template.shape[0], x:x + template.shape[1]]
    return max(float(best), match_score(match_feature(aligned), match_feature(template), method))


def save_template(path, patch):
    """原子写入特征模板，编码或写入失败时保留原文件。"""
    success, encoded = cv2.imencode(".png", patch)
    if not success:
        raise OSError(f"备战模板编码失败：{path}")
    descriptor, temporary = tempfile.mkstemp(prefix=".portrait-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as output:
            output.write(encoded.tobytes())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def field_portrait(patch, corners):
    """校正场上卡片的透视，取出与备战栏相同位置的头像。"""
    matrix = cv2.getPerspectiveTransform(
        np.float32(corners), np.float32(((0, 0), (109, 0), (109, 133), (0, 133))),
    )
    tile = cv2.warpPerspective(patch, matrix, (110, 134))
    left, top, right, bottom = PORTRAIT_BOX
    return tile[top:bottom, left:right]


def item_detected(tile):
    """用道具卡底部的青色操作条确认道具，不能根据备战格序号或缺少角标判断。"""
    footer = tile[94:123, 8:102].astype(np.int16)
    blue, green, red = cv2.split(footer)
    cyan = (blue > 140) & (green > 140) & (red < green - 35)
    return float(cyan.mean()) > 0.45


def badge_detected(tile):
    """卡片右上角是否有角标：近黑色圆角框里有两枚亮色笔画。

    角标的具体图形会随角色属性变化（空心、实心、红色等），因此只判断“有没有框和笔画”，
    不枚举具体图形。道具卡在这个角是卡面图案（没有黑色框），空格整片深色（没有笔画）。

    Args:
        tile: 一张备战卡片的截图。

    Returns:
        True 表示有角标，也就是角色。
    """
    left, top, right, bottom = BADGE_BOX
    patch = tile[top:bottom, left:right]
    gray = cv2.cvtColor(patch, cv2.COLOR_BGR2GRAY)
    height, width = gray.shape
    dark = (gray < BADGE_DARK).astype(np.uint8)
    total, _, stats, _ = cv2.connectedComponentsWithStats(dark, connectivity=8)
    for index in range(1, total):
        x, y, box_width, box_height, area = (int(value) for value in stats[index])
        if box_width < width * 0.75 or box_height < height * 0.8:
            continue
        if area < box_width * box_height * 0.5:
            continue
        glyphs = int((gray[y:y + box_height, x:x + box_width] > BADGE_BRIGHT).sum())
        if glyphs >= BADGE_GLYPHS:
            return True
    return False


class BattlePreparation:
    def __init__(self, catalog=None):
        self.catalog = Path(catalog) if catalog is not None else resource_path(
            __file__, "templates/bench"
        )
        self.catalog.mkdir(parents=True, exist_ok=True)
        self.templates = {}
        for path in sorted(self.catalog.glob("*.png")):
            if path.stem.split("_", 1)[0] not in ("character", "item", "empty"):
                raise ValueError(f"无法识别备战模板类型：{path}")
            tile = find_image_by_name(str(path.resolve()))
            if tile is None:
                raise ValueError(f"无法读取备战模板：{path}")
            if tile.shape == (134, 110, 3):
                left, top, right, bottom = PORTRAIT_BOX
                tile = tile[top:bottom, left:right].copy()
                if path.stem.startswith("character_"):
                    save_template(path, tile)  # 保留文件名，已有优先级继续匹配同一角色。
            if tile.shape != (40, 40, 3):
                raise ValueError(f"备战模板应为 40×40 的彩色特征图：{path}")
            self.templates[path.stem] = tile
        self.badges = {}
        for path in sorted(resource_path(__file__, "templates/badges").glob("*.png")):
            badge = find_image_by_name(str(path.resolve()))
            if badge is None:
                raise FileNotFoundError(f"无法读取货币战争角标模板：{path}")
            self.badges[path.stem] = badge
        self.area_tiles = {}
        for area, boxes in AREA_BOXES.items():
            self.area_tiles[area] = []
            for index in range(len(boxes)):
                path = resource_path(__file__, f"templates/areas/{area}_{index}.png")
                tile = find_image_by_name(str(path))
                if tile is None:
                    raise FileNotFoundError(f"缺少货币战争空位模板：{path}")
                self.area_tiles[area].append(tile)
        self.merge_duplicates()
        self.reset_members()

    def same_character(self, first, second):
        """判断两份特征是否来自同一角色；允许几像素位移和细微缩放。"""
        margin = MATCH_MARGIN
        search = cv2.copyMakeBorder(
            self.templates[first], margin, margin, margin, margin, cv2.BORDER_REPLICATE,
        )
        method = cv2.TM_SQDIFF_NORMED if first.startswith("empty_") else cv2.TM_CCOEFF_NORMED
        return portrait_score(search, self.templates[second], method) >= MATCH_THRESHOLD

    def merge_duplicates(self):
        """合并同一角色的重复特征，删除多余文件并把上阵优先级迁移到保留的模板。

        截帧时整栏的缩放和位置会有细微差别，同一角色的两次采集可能落到不同摘要上，
        这里按比对分数合并；先迁移配置再删除文件，迁移失败时保留两份模板。
        """
        duplicates = {}
        names = list(self.templates)
        for index, kept in enumerate(names):
            if kept in duplicates:
                continue
            for other in names[index + 1:]:
                if other in duplicates:
                    continue
                same_kind = other.split("_", 1)[0] == kept.split("_", 1)[0]
                repaired_item = kept.startswith("character_") and other.startswith("item_")
                if not same_kind and not repaired_item:
                    continue
                if self.same_character(kept, other):
                    duplicates[other] = kept
        if not duplicates:
            return
        if not self.migrate_priorities(duplicates):
            return
        for removed in duplicates:
            (self.catalog / f"{removed}.png").unlink(missing_ok=True)
            self.templates.pop(removed, None)
        CUS_LOGGER.warning(
            "重复或误分类的备战模板已合并：%s",
            "，".join(f"{removed} 归入 {kept}" for removed, kept in duplicates.items()),
        )

    def migrate_priorities(self, duplicates):
        """把重复模板上的上阵优先级和名字迁移到保留的模板；返回是否迁移成功。"""
        try:
            deployment = load_currency_settings()["deployment"]
            updated = {}
            changed = False
            for key in ("front_priority", "back_priority"):
                names = []
                for name in deployment[key]:
                    mapped = duplicates.get(name, name)
                    changed = changed or mapped != name
                    if mapped not in names:
                        names.append(mapped)
                updated[key] = names
            names = {}
            for template, name in deployment["names"].items():
                mapped = duplicates.get(template, template)
                changed = changed or mapped != template
                names.setdefault(mapped, name)
            updated["names"] = names
            if changed:
                save_currency_settings({"deployment": updated})
        except (OSError, ValueError) as error:
            CUS_LOGGER.warning("上阵优先级迁移失败，保留重复的备战模板：%s", error)
            return False
        return True

    def reset_members(self):
        """新对局开始时清空场上身份；单次拖拽失败不能清空整队。"""
        self.members = {area: [None] * len(boxes) for area, boxes in AREA_BOXES.items()}

    def read_members(self, vacancies, placed):
        """按本帧空位和 OCR 上阵人数同步身份，避免把漏识别底板算成额外角色。

        空底板没匹配上并不等于格子里有人：已确认身份已经占满 OCR 人数时，其余占位
        按空位处理。

        Returns:
            区域到身份列表的快照；None 表示空位，空字符串表示身份待确认。
        """
        confirmed = 0
        unknown = 0
        for area, entries in self.members.items():
            for index in range(len(entries)):
                if index in vacancies[area]:
                    entries[index] = None
                elif entries[index] is None:
                    entries[index] = ""
                if entries[index]:
                    confirmed += 1
                elif entries[index] == "":
                    unknown += 1
        if unknown and confirmed >= placed:
            for entries in self.members.values():
                for index in range(len(entries)):
                    if entries[index] == "":
                        entries[index] = None
        return {area: entries[:] for area, entries in self.members.items()}

    def confirm_move(self, move, before, after):
        """通过备战栏角色增减确认补位或交换，并记录目标格的角色身份。

        Returns:
            (是否确认, 换回备战栏的角色模板)。补空位时第二项为 None。
        """
        incoming = next(slot.template for slot in before if slot.index == move.source)
        old_counts = Counter(slot.template for slot in before if slot.kind == "character")
        new_counts = Counter(slot.template for slot in after if slot.kind == "character")
        removed = old_counts - new_counts
        added = new_counts - old_counts
        if removed != Counter({incoming: 1}):
            return False, None
        if move.outgoing is None:
            if added:
                return False, None
            outgoing = None
        else:
            if added.total() != 1:
                return False, None
            outgoing = next(iter(added))
        self.members[move.area][move.target] = incoming
        return True, outgoing

    def badge_name(self, tile):
        """返回卡片右上角的角标类型（front、back、both…）；没有角标时返回 None。

        先按 templates/badges/ 里的模板匹配，没匹配上再按“黑框 + 笔画”的形状兜底，
        这样新角标还没收录时也不会把角色当成道具。

        Args:
            tile: 一张备战卡片的截图。
        """
        left, top, right, bottom = BADGE_BOX
        patch = tile[top:bottom, left:right]
        best_name, best_score = None, 0.0
        glyphs = (cv2.cvtColor(patch, cv2.COLOR_BGR2GRAY) > BADGE_BRIGHT).astype(np.uint8)
        for name, badge in self.badges.items():
            score = match_score(patch, badge)
            # 红色/白色实心格表示的区域相同，按笔画形状再匹配一次。
            shape = (cv2.cvtColor(badge, cv2.COLOR_BGR2GRAY) > BADGE_BRIGHT).astype(np.uint8)
            score = max(score, match_score(glyphs, shape))
            if score > best_score:
                best_name, best_score = name, score
        if best_score >= BADGE_THRESHOLD:
            return best_name
        if badge_detected(tile):
            return "unknown"
        return None

    def scan_bench(self, frame):
        """截取九格，匹配已知模板，保存未匹配格并返回识别结果。

        Args:
            frame: 1920×1080、BGR 三通道游戏截图。

        Returns:
            从左到右排列的九个 BenchSlot。只有带角色标识的格子可用于上阵。
        """
        if frame.shape != (1080, 1920, 3):
            raise ValueError("货币战争备战识别需要 1920×1080 的 BGR 截图")
        slots = []
        for index, (left, top, right, bottom) in enumerate(BENCH_BOXES):
            tile = frame[top:bottom, left:right].copy()
            badge = self.badge_name(tile)
            areas = BADGE_AREAS.get(badge, ())
            x1, y1, x2, y2 = PORTRAIT_BOX
            margin = MATCH_MARGIN
            portrait = tile[y1:y2, x1:x2].copy()
            search = tile[y1 - margin:y2 + margin, x1 - margin:x2 + margin].copy()
            # 类型先由本帧卡面证据决定。历史 item 中可能混有角色和过渡画面，不能反过来
            # 用那个文件名前缀认定本帧类型；没有角标时仍允许匹配已确认的角色头像。
            kind = "character" if badge is not None else "unknown"
            if badge is None and item_detected(tile):
                kind = "item"
            elif badge is None and float(np.std(portrait)) < 12:
                kind = "empty"
            best_name, best_score = "", 0.0
            for name, known in self.templates.items():
                prefix = name.split("_", 1)[0]
                if prefix != kind and not (badge is None and prefix == "character"):
                    continue
                # 纯色过渡格的归一化分母为零，完全相同的像素仍应复用模板。
                if np.array_equal(portrait, known):
                    best_name, best_score = name, 1.0
                    break
                # 空格的暗色底板只含细线，使用像素误差，避免细线位置造成相关系数突变。
                method = cv2.TM_SQDIFF_NORMED if name.startswith("empty_") else cv2.TM_CCOEFF_NORMED
                score = portrait_score(search, known, method)
                if score > best_score:
                    best_name, best_score = name, score
            if best_score < MATCH_THRESHOLD:
                if kind in ("unknown", "empty"):
                    # 陌生画面和纯色过渡格都不进入持久模板库。
                    slots.append(BenchSlot(index, "", kind, ()))
                    continue
                digest = hashlib.sha256(portrait.tobytes()).hexdigest()[:12]
                best_name = f"{kind}_{digest}"
                save_template(self.catalog / f"{best_name}.png", portrait)
                self.templates[best_name] = portrait
                CUS_LOGGER.debug("备战格%d采集模板：%s", index + 1, best_name)
            slots.append(BenchSlot(index, best_name, best_name.split("_", 1)[0], areas))
        return slots

    def deployed_templates(self, frame, vacancies):
        """透视校正后识别场上身份，更新对应格子的记录并返回已识别的角色。

        Args:
            frame: 与 scan_bench 同一帧的截图。
            vacancies: read_areas 的结果，用来跳过空格。

        Returns:
            识别出的模板名集合。
        """
        names = set()
        for area, boxes in AREA_BOXES.items():
            for index, (left, top, right, bottom) in enumerate(boxes):
                if index in vacancies[area]:
                    continue
                portrait = field_portrait(
                    frame[top:bottom, left:right], AREA_QUADS[area][index],
                )
                search = cv2.copyMakeBorder(
                    portrait, MATCH_MARGIN, MATCH_MARGIN, MATCH_MARGIN, MATCH_MARGIN,
                    cv2.BORDER_REPLICATE,
                )
                best_name, best_score, runner_up = None, 0.0, 0.0
                for name, known in self.templates.items():
                    if not name.startswith("character_"):
                        continue
                    score = portrait_score(search, known)
                    if score > best_score:
                        runner_up = best_score
                        best_name, best_score = name, score
                    elif score > runner_up:
                        runner_up = score
                # 相似头像必须拉开分数差距，避免用错身份进一步触发错误替换。
                if best_name is not None and best_score >= MATCH_THRESHOLD and best_score - runner_up >= 0.06:
                    names.add(best_name)
                    self.members[area][index] = best_name
                    CUS_LOGGER.debug(
                        "%s第%d格已上阵：%s（score=%.3f）",
                        "前台" if area == "front" else "后台", index + 1, best_name, best_score,
                    )
        return names

    def read_areas(self, frame):
        """返回前台、后台的空位编号，frame 须与 scan_bench 的截图契约一致。"""
        vacancies = {}
        height, width = frame.shape[:2]
        for area, boxes in AREA_BOXES.items():
            vacancies[area] = []
            for index, (left, top, right, bottom) in enumerate(boxes):
                search = frame[max(0, top - MATCH_MARGIN):min(height, bottom + MATCH_MARGIN),
                               max(0, left - MATCH_MARGIN):min(width, right + MATCH_MARGIN)]
                score = match_score(search, self.area_tiles[area][index])
                if score >= MATCH_THRESHOLD:
                    vacancies[area].append(index)
        return vacancies


def plan_deployment(
    slots, vacancies, counts, front_priority, back_priority, members, deployed=(),
):
    """按角标和前后台优先级分配角色。

    counts 是 OCR 读取的 (上阵人数, 人数上限)，两者都按前台与后台之和计算：前台固定四
    个落点，后台六个，上限随对局进度变化。每个角色能放哪个区域由备战栏卡片右上角的角标
    决定（前台、后台、前后台都能放），角标不允许的区域不会安排；区域内的先后顺序按该区
    优先级列表，其次是未配置角色。前台保底优先使用补位角色，缺少补位角色时才借用允许前
    台的后台列表角色；其余后台优先角色留在后台，最后补剩余空位。没有补位动作后按同区优
    先级替换较低优先级的角色，低优先级角色不会被主动换入。已经上
    阵（前台或后台，含场上识别出的身份）的角色不会再从备战栏拖进来，同一角色只占一个位
    置；道具不参与；未知上阵角色的替换需由执行方检查换回的头像，发现原角色优先级更高时
    恢复原位。

    Args:
        slots: scan_bench 的九个备战格。
        vacancies: read_areas 的空位。
        counts: OCR 读取的 (上阵人数, 人数上限)。
        front_priority: 前台优先级列表。
        back_priority: 后台优先级列表。
        members: 已确认的上阵身份。
        deployed: 场上识别出的角色模板名，避免同一个角色再上一份。

    Returns:
        按执行顺序排列的补位或替换动作，无键鼠副作用。
    """
    deployed = set(deployed) | {name for entries in members.values() for name in entries if name}
    characters = []
    for slot in slots:
        if slot.kind != "character" or slot.template in deployed:
            continue
        deployed.add(slot.template)  # 备战栏里同名的第二份也不再重复安排
        characters.append(slot)
    placed, capacity = counts
    if not 0 <= placed <= capacity <= TEAM_CAPACITY:
        raise ValueError(f"上阵人数不合法：{placed}/{capacity}")
    priorities = {"front": front_priority, "back": back_priority}
    ranks = {
        area: {name: index for index, name in enumerate(priority)}
        for area, priority in priorities.items()
    }
    remaining = capacity - placed
    occupied = sum(len(boxes) - len(vacancies[area]) for area, boxes in AREA_BOXES.items())
    if occupied < placed:
        # 识别到的占位比 OCR 人数还少，说明有上阵角色被当成空位，本轮补位会拖到它身上。
        remaining = 0

    moves = []
    open_slots = {area: list(indexes) for area, indexes in vacancies.items()}
    pool = list(characters)
    front_empty = len(open_slots["front"]) == len(AREA_BOXES["front"])

    # 分阶段补位：前台优先角色、前台保底、后台优先角色、两区补位角色。
    # 保底先用补位角色，最后才借用允许前台的后台角色，避免抢占后台核心的名额。
    for stage, area in enumerate(("front", "front", "back", "front", "back")):
        if remaining <= 0:
            break
        if stage in (0, 2):
            candidates = [
                slot for name in priorities[area] for slot in pool
                if slot.template == name and area in slot.areas
            ]
        else:
            candidates = [
                slot for slot in pool if area in slot.areas
                and slot.template not in ranks["front"] and slot.template not in ranks["back"]
            ]
        if stage == 1:
            if not front_empty or any(move.area == "front" for move in moves):
                continue
            if not candidates:
                candidates = [
                    slot for name in back_priority for slot in pool
                    if slot.template == name and "front" in slot.areas
                ]
            candidates = candidates[:1]
        pairs = list(zip(candidates, open_slots[area][:remaining]))
        moves.extend(Deployment(slot.index, area, target) for slot, target in pairs)
        used = {slot.index for slot, _ in pairs}
        pool = [slot for slot in pool if slot.index not in used]
        open_slots[area] = open_slots[area][len(pairs):]
        remaining -= len(pairs)
    if moves:
        return moves

    # 满员后按同区优先级替换；未配置优先级的区域不主动换人。
    for area in ("front", "back"):
        rank = ranks[area]
        if not rank or not characters:
            continue
        incoming = next(
            (
                slot for name in priorities[area] for slot in characters
                if slot.template == name and area in slot.areas
            ),
            None,
        )
        filled = [index for index, name in enumerate(members[area]) if name is not None]
        if incoming is None or not filled:
            continue
        target = max(filled, key=lambda index: rank.get(members[area][index], len(rank)))
        if rank[incoming.template] < rank.get(members[area][target], len(rank)):
            return [Deployment(incoming.index, area, target, members[area][target])]
    return []
