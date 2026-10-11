"""自动清理设置的配置、筛选规则与执行逻辑。

三类清理对象只清理符合程序命名规则的文件与目录：

    video  视频录制产生的 第x次轮回-x战-年月日_时分秒.mp4
    log    logs 目录下的 log_年-月-日-时-分.txt
    temp   temp 及其七个子目录下的 年月日_时分秒(.毫秒).png，
           以及 blank_state 下名称带时间的 blank_像素数_年月日_时分秒 调试目录

时间直接取自文件或目录名称中的时间，不依赖文件系统的创建或修改时间。本次运行
正在写入的日志由当前进程占用，删除必然失败，因此不在清理范围内。单个对象删除
失败不会中断清理，失败数量单独统计。配置单独保存在
config/config/cleanup_config.yml，参数不合法时用 example 配置的默认值覆盖。
"""

import glob
import os
import re
import shutil
from dataclasses import dataclass
from datetime import datetime, timedelta

import yaml

from route import PATHS
from tool import EXTRA
from tool.log import CUS_LOGGER, current_log_file, log_emitter

CONFIG_PATH = os.path.join(PATHS["config"], "cleanup_config.yml")
EXAMPLE_PATH = os.path.join(PATHS["example"], "cleanup_config_example.yml")

CATEGORIES = ("video", "log", "temp")

CATEGORY_NAMES = {
    "video": "视频文件",
    "log": "日志文件",
    "temp": "临时文件",
}

# 清理对象的操作按钮文字，清理按钮与手动清理提示共用。
CATEGORY_BUTTONS = {
    "video": "清理视频文件",
    "log": "清理日志文件",
    "temp": "清理临时文件",
}

MODES = ("never", "manual", "periodic", "automatic")

MODE_NAMES = {
    "never": "永不清理",
    "manual": "手动清理",
    "periodic": "周期清理",
    "automatic": "自动清理",
}

TRIGGERS = ("program_start", "task_start", "task_end")

TRIGGER_NAMES = {
    "program_start": "程序启动时",
    "task_start": "任务启动时",
    "task_end": "任务结束时",
}

UNITS = ("year", "month", "day", "hour", "minute")

UNIT_NAMES = {
    "year": "年",
    "month": "月",
    "day": "日",
    "hour": "时",
    "minute": "分",
}

LAST_CLEANUP_FORMAT = "%Y-%m-%d %H:%M:%S"

# 默认参数以 example 配置为准（手动清理 / 程序启动时 / 3 日），这里的取值是
# example 配置不可读时的兜底，保证配置读取始终可用。
DEFAULT_MODE = "manual"
DEFAULT_TRIGGER = "program_start"
DEFAULT_VALUE = 3
DEFAULT_UNIT = "day"


@dataclass(frozen=True)
class CleanupItem:
    """单个清理对象的配置。

    Attributes:
        mode: 清理模式，取 MODES 之一。
        trigger: 清理触发时机，取 TRIGGERS 之一；手动清理与永不清理不使用。
        value: 清理参数数值，大于等于 0 的整数。
        unit: value 的时间单位，取 UNITS 之一。
        last_cleanup: 上次清理时间，格式为 YYYY-MM-DD HH:MM:SS；从未清理时为空字符串。
    """

    mode: str = DEFAULT_MODE
    trigger: str = DEFAULT_TRIGGER
    value: int = DEFAULT_VALUE
    unit: str = DEFAULT_UNIT
    last_cleanup: str = ""


@dataclass(frozen=True)
class CleanupConfig:
    """三个清理对象的自动清理配置。"""

    items: dict[str, CleanupItem]

    def item(self, category: str) -> CleanupItem:
        """取出指定清理对象的配置。

        Args:
            category: 清理对象，取 CATEGORIES 之一。

        Returns:
            该对象的清理配置。
        """
        return self.items[category]


def parse_last_cleanup(value) -> str:
    """校验上次清理时间，返回合法的时间文本或空字符串。

    Args:
        value: 配置文件中的 last_cleanup 原始值。

    Returns:
        YYYY-MM-DD HH:MM:SS 格式的时间文本；非法或从未清理时返回空字符串。
    """
    if not isinstance(value, str):
        return ""
    try:
        datetime.strptime(value, LAST_CLEANUP_FORMAT)
    except ValueError:
        return ""
    return value


def last_cleanup_text(value: str) -> str:
    """把上次清理时间转换为 UI 文本。

    Args:
        value: YYYY-MM-DD HH:MM:SS 格式的时间文本，空字符串表示从未清理。

    Returns:
        UI 显示文本，未清理过时为“上次清理：从未清理”。
    """
    if not value:
        return "上次清理：从未清理"
    return f"上次清理：{value}"


def parse_value(value):
    """校验清理参数数值。

    Args:
        value: 配置文件中的 value 原始值。

    Returns:
        大于等于 0 的整数；非法时返回 None。
    """
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value if value >= 0 else None


def validate_item(item: CleanupItem) -> list[str]:
    """校验一个清理对象的配置，返回不合法参数的说明。

    Args:
        item: 待校验的清理配置。

    Returns:
        每条为一句中文说明；全部合法时为空列表。
    """
    errors = []
    if item.mode not in MODES:
        errors.append(f"清理模式不合法：{item.mode}")
    if item.trigger not in TRIGGERS:
        errors.append(f"触发时机不合法：{item.trigger}")
    if parse_value(item.value) is None:
        errors.append(f"数值必须为大于等于 0 的整数：{item.value}")
    if item.unit not in UNITS:
        errors.append(f"时间单位不合法：{item.unit}")
    return errors


def validate_config(config: CleanupConfig) -> list[str]:
    """校验全部清理对象的配置，返回带对象名称的说明。

    Args:
        config: 待校验的自动清理配置。

    Returns:
        每条为一句中文说明；全部合法时为空列表。
    """
    errors = []
    for category in CATEGORIES:
        errors.extend(
            f"{CATEGORY_NAMES[category]}：{error}"
            for error in validate_item(config.item(category))
        )
    return errors


def read_raw_config(path) -> dict | None:
    """读取 YAML 配置文本。

    Args:
        path: 配置文件路径。

    Returns:
        解析后的字典；文件不存在、无法读取或存在语法错误时返回 None。
    """
    if not os.path.exists(path):
        return None
    with EXTRA.FILE_LOCK:
        try:
            with open(path, encoding="utf-8") as config_file:
                values = yaml.safe_load(config_file)
        except (OSError, yaml.YAMLError):
            return None
    return values if isinstance(values, dict) else None


def load_example_item(category: str) -> CleanupItem:
    """读取 example 配置中某个清理对象的默认参数。

    单个参数非法时该参数回退到代码内置默认值，保证返回值始终可用。

    Args:
        category: 清理对象，取 CATEGORIES 之一。

    Returns:
        该对象在 example 配置中的默认参数。
    """
    values = read_raw_config(EXAMPLE_PATH)
    example = values.get(category) if values else None
    if not isinstance(example, dict):
        example = {}

    mode = example.get("mode")
    trigger = example.get("trigger")
    value = parse_value(example.get("value"))
    unit = example.get("unit")
    return CleanupItem(
        mode=mode if mode in MODES else DEFAULT_MODE,
        trigger=trigger if trigger in TRIGGERS else DEFAULT_TRIGGER,
        value=value if value is not None else DEFAULT_VALUE,
        unit=unit if unit in UNITS else DEFAULT_UNIT,
    )


def load_cleanup_config(path=None) -> CleanupConfig:
    """读取自动清理配置，非法参数用 example 配置的默认值覆盖。

    配置文件不存在时先由 example 配置创建，随后按默认参数读取；YAML 语法
    错误时整份配置使用 example 配置的默认参数。缺失、类型错误或取值越界
    的单个参数只覆盖该参数，其他合法参数保持不变。

    Args:
        path: 配置文件路径，默认使用正式配置。

    Returns:
        可直接使用的自动清理配置。
    """
    path = os.fspath(path or CONFIG_PATH)
    if not os.path.exists(path) and path == CONFIG_PATH and os.path.exists(EXAMPLE_PATH):
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with EXTRA.FILE_LOCK:
            with open(EXAMPLE_PATH, encoding="utf-8") as example_file:
                example_text = example_file.read()
            with open(path, mode="w", encoding="utf-8") as config_file:
                config_file.write(example_text)

    values = read_raw_config(path)

    items = {}
    for category in CATEGORIES:
        fallback = load_example_item(category)
        raw = values.get(category) if values else None
        if not isinstance(raw, dict):
            raw = {}

        mode = raw.get("mode")
        trigger = raw.get("trigger")
        value = parse_value(raw.get("value"))
        unit = raw.get("unit")
        items[category] = CleanupItem(
            mode=mode if mode in MODES else fallback.mode,
            trigger=trigger if trigger in TRIGGERS else fallback.trigger,
            value=value if value is not None else fallback.value,
            unit=unit if unit in UNITS else fallback.unit,
            last_cleanup=parse_last_cleanup(raw.get("last_cleanup")),
        )
    return CleanupConfig(items=items)


def write_config(config: CleanupConfig, path=None) -> None:
    """以统一结构写入自动清理配置。

    Args:
        config: 待写入的自动清理配置，调用方需保证参数合法。
        path: 配置文件路径，默认使用正式配置。
    """
    path = os.fspath(path or CONFIG_PATH)
    content = {}
    for category in CATEGORIES:
        item = config.item(category)
        content[category] = {
            "mode": item.mode,
            "trigger": item.trigger,
            "value": item.value,
            "unit": item.unit,
            "last_cleanup": item.last_cleanup,
        }
    with EXTRA.FILE_LOCK:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, mode="w", encoding="utf-8") as config_file:
            yaml.safe_dump(content, config_file, allow_unicode=True, sort_keys=False)


def update_last_cleanup(category: str, cleaned_at: str, path=None) -> bool:
    """只更新某个清理对象的上次清理时间，保留其余配置。

    写入失败不影响本次清理结果，由调用方决定如何提示。

    Args:
        category: 清理对象，取 CATEGORIES 之一。
        cleaned_at: 本次清理触发时间，格式为 YYYY-MM-DD HH:MM:SS。
        path: 配置文件路径，默认使用正式配置。

    Returns:
        写入成功返回 True；读取或写入失败返回 False。
    """
    try:
        config = load_cleanup_config(path)
        items = dict(config.items)
        current = config.item(category)
        items[category] = CleanupItem(
            mode=current.mode,
            trigger=current.trigger,
            value=current.value,
            unit=current.unit,
            last_cleanup=cleaned_at,
        )
        write_config(CleanupConfig(items=items), path)
    except (OSError, yaml.YAMLError) as error:
        CUS_LOGGER.warning(
            "上次清理时间写入失败：%s（%s）", CATEGORY_NAMES[category], error
        )
        return False
    return True


# ---------------------------------------------------------------------------
# 执行：命中规则的收集、删除与触发时机判断
# ---------------------------------------------------------------------------
# 程序产生的临时文件统一在此目录及其子目录下。
TEMPDIRS = (
    "angle",
    "bigmaperror",
    "blank_state",
    "kill",
    "no_red2",
    "stop",
    "unmatched_action_count",
)
# 目录型临时文件只出现在 blank_state 下。
BLANK_STATE_DIR = "blank_state"

VIDEO_PATTERN = re.compile(r"(\d{8})_(\d{6})\.mp4$")
LOG_PATTERN = re.compile(r"log_(\d{4})-(\d{2})-(\d{2})-(\d{2})-(\d{2})\.txt$")
TEMP_PATTERN = re.compile(r"(\d{8})_(\d{6})(?:_\d+)?\.png$")
# blank_state 下每次调试都会新建一个“blank_像素数_年月日_时分秒”目录，目录名本身带时间。
TEMP_DIRECTORY_PATTERN = re.compile(r"blank_\d+_(\d{8})_(\d{6})$")

# 是否已有一次触发清理正在执行，用于跳过重叠的触发时机。
_cleanup_running = False


@dataclass(frozen=True)
class CollectFile:
    """命中清理规则的一个文件或目录。

    Attributes:
        path: 文件或目录的绝对路径。
        created_at: 从名称解析出的时间，作为清理判断依据。
        is_directory: 命中目录时为 True，删除时连同目录内容一起删除。
    """

    path: str
    created_at: datetime
    is_directory: bool = False


@dataclass(frozen=True)
class CleanupResult:
    """一次清理的执行结果。

    Attributes:
        category: 清理对象，取 CATEGORIES 之一。
        success_count: 成功删除的文件数量。
        failure_count: 删除失败的文件数量。
        cleaned_at: 本次清理的触发时间。
    """

    category: str
    success_count: int
    failure_count: int
    cleaned_at: str

    @property
    def summary(self) -> str:
        """返回清理结果文案。"""
        return f"清理成功：{self.success_count}个文件，清理失败：{self.failure_count}个文件"


def parse_file_time(filename: str, pattern: re.Pattern) -> datetime | None:
    """从文件名中解析时间。

    捕获组依次为年月日与时分秒：视频文件为 8 位日期加 6 位时间，日志与
    临时文件为多段数字。

    Args:
        filename: 文件名。
        pattern: 该清理对象的文件名规则。

    Returns:
        文件名中记录的时间；文件名不含时间或时间非法时返回 None。
    """
    match = pattern.search(filename)
    if match is None:
        return None

    text = "".join(match.groups())
    try:
        return datetime.strptime(text, "%Y%m%d%H%M%S")
    except ValueError:
        return None


def category_roots(category: str) -> tuple[str, ...]:
    """返回某个清理对象对应的扫描目录。

    Args:
        category: 清理对象，取 CATEGORIES 之一。

    Returns:
        需要扫描的目录路径，不存在的目录也会返回，扫描时自动跳过。
    """
    if category == "video":
        return (PATHS["video"],)
    if category == "log":
        return (PATHS["logs"],)
    # 文件按各子目录的命名规则匹配；目录型清理对象只在 blank_state 下出现。
    return tuple(os.path.join(PATHS["temp"], name) for name in TEMPDIRS)


def directory_root(category: str) -> str | None:
    """返回某个清理对象中可能有目录型临时文件的根目录。

    Args:
        category: 清理对象，取 CATEGORIES 之一。

    Returns:
        目录型清理对象的扫描根目录；该清理对象没有目录型内容时返回 None。
    """
    if category != "temp":
        return None
    return os.path.join(PATHS["temp"], BLANK_STATE_DIR)


def category_pattern(category: str) -> re.Pattern:
    """返回某个清理对象的文件名规则。"""
    return {
        "video": VIDEO_PATTERN,
        "log": LOG_PATTERN,
        "temp": TEMP_PATTERN,
    }[category]


def collect_files(category: str) -> list[CollectFile]:
    """收集某个清理对象下所有符合命名规则的清理对象。

    只处理名称含有时间结构的文件与目录：文件按自身文件名解析时间；目录按
    目录名解析时间，命中时整个目录（含其中内容）算作一次清理。用户自行放
    入或改名的其他文件与目录不受影响。

    Args:
        category: 清理对象，取 CATEGORIES 之一。

    Returns:
        命中规则的清理对象列表，顺序未定义。
    """
    pattern = category_pattern(category)
    files = []
    seen = set()
    for root in category_roots(category):
        for path in glob.glob(os.path.join(glob.escape(root), "**", "*"), recursive=True):
            if path in seen or not os.path.isfile(path):
                continue
            created_at = parse_file_time(os.path.basename(path), pattern)
            if created_at is None:
                continue
            seen.add(path)
            files.append(CollectFile(path=path, created_at=created_at))

    # blank_state 每次调试都会新建“blank_像素数_年月日_时分秒”目录，目录名本身带时间。
    root = directory_root(category)
    if root is not None and os.path.isdir(root):
        for path in glob.glob(os.path.join(glob.escape(root), "**", "*"), recursive=True):
            if path in seen or not os.path.isdir(path):
                continue
            created_at = parse_file_time(os.path.basename(path), TEMP_DIRECTORY_PATTERN)
            if created_at is None:
                continue
            seen.add(path)
            files.append(CollectFile(
                path=path, created_at=created_at, is_directory=True))
    return files


def subtract_duration(moment: datetime, value: int, unit: str) -> datetime:
    """按时间单位往前推算时间点。

    Args:
        moment: 基准时间。
        value: 时间长度数值。
        unit: 时间单位，取 year/month/day/hour/minute。

    Returns:
        往前推算得到的时间。年为 365 日、月为 30 日。
    """
    if unit == "minute":
        return moment - timedelta(minutes=value)
    if unit == "hour":
        return moment - timedelta(hours=value)
    if unit == "day":
        return moment - timedelta(days=value)
    if unit == "month":
        return moment - timedelta(days=30 * value)
    return moment - timedelta(days=365 * value)


def delete_files(files: list[CollectFile]) -> tuple[int, int]:
    """逐个删除命中的文件或目录并统计结果。

    删除失败的对象跳过并计入失败数量，不中断整体清理；命中目录时连同目录
    内容一起删除。正在写入的日志不在待删除列表内，见 skip_current_log。

    Args:
        files: 待删除的文件与目录列表。

    Returns:
        (成功数量, 失败数量)。
    """
    success_count = 0
    failure_count = 0
    for collect_file in files:
        try:
            if collect_file.is_directory:
                shutil.rmtree(collect_file.path)
            else:
                os.remove(collect_file.path)
        except OSError as error:
            failure_count += 1
            CUS_LOGGER.warning("文件清理失败，已跳过：%s（%s）", collect_file.path, error)
            continue
        success_count += 1
    return success_count, failure_count


def skip_current_log(files: list[CollectFile]) -> list[CollectFile]:
    """跳过本次运行正在写入的日志文件。

    该文件由当前进程持有，删除必然失败，把它计入失败数量会让清理结果失真。

    Args:
        files: 待删除的文件与目录列表。

    Returns:
        去掉正在写入的日志文件后的列表。
    """
    current_log = current_log_file()
    return [item for item in files if os.path.basename(item.path) != current_log]


def cleanup_manual(config: CleanupConfig, category: str, now: datetime | None = None) -> CleanupResult:
    """按用户设定的期限执行一次手动清理。

    数值为 0 时清理该类别下所有符合规则且可删除的文件；否则只清理距今已
    超过所设时长的文件。

    Args:
        config: 当前自动清理配置。
        category: 清理对象，取 CATEGORIES 之一。
        now: 清理触发时间，便于验证时指定；默认为当前时间。

    Returns:
        本次清理的成功与失败数量。
    """
    now = now or datetime.now()
    item = config.item(category)
    files = skip_current_log(collect_files(category))
    if item.value > 0:
        cutoff = subtract_duration(now, item.value, item.unit)
        files = [collect_file for collect_file in files if collect_file.created_at < cutoff]
    success_count, failure_count = delete_files(files)
    return CleanupResult(
        category=category,
        success_count=success_count,
        failure_count=failure_count,
        cleaned_at=now.strftime("%Y-%m-%d %H:%M:%S"),
    )


def cleanup_expired(config: CleanupConfig, category: str, now: datetime | None = None) -> CleanupResult:
    """执行一次自动清理，删除超过保存期限的文件。

    数值为 0 时直接清理该类别下所有符合规则且可删除的文件。

    Args:
        config: 当前自动清理配置。
        category: 清理对象，取 CATEGORIES 之一。
        now: 清理触发时间，便于验证时指定；默认为当前时间。

    Returns:
        本次清理的成功与失败数量。
    """
    return cleanup_manual(config, category, now)


def cleanup_all(config: CleanupConfig, category: str, now: datetime | None = None) -> CleanupResult:
    """执行一次周期清理，清理该类别下所有符合条件的文件。

    Args:
        config: 当前自动清理配置。
        category: 清理对象，取 CATEGORIES 之一。
        now: 清理触发时间，便于验证时指定；默认为当前时间。

    Returns:
        本次清理的成功与失败数量。
    """
    now = now or datetime.now()
    success_count, failure_count = delete_files(
        skip_current_log(collect_files(category)))
    return CleanupResult(
        category=category,
        success_count=success_count,
        failure_count=failure_count,
        cleaned_at=now.strftime("%Y-%m-%d %H:%M:%S"),
    )


def needs_periodic_cleanup(config: CleanupConfig, category: str, now: datetime | None = None) -> bool:
    """判断周期清理在本次触发时机是否需要执行。

    从未清理过时立即执行；周期为 0 时每次触发都执行；否则比较当前时间与
    上次清理时间是否已达到所设周期。

    Args:
        config: 当前自动清理配置。
        category: 清理对象，取 CATEGORIES 之一。
        now: 触发时机的时间，便于验证时指定；默认为当前时间。

    Returns:
        需要执行清理时返回 True。
    """
    now = now or datetime.now()
    item = config.item(category)
    last_cleanup = parse_last_cleanup(item.last_cleanup)
    if not last_cleanup:
        return True
    if item.value == 0:
        return True
    last_cleanup_at = datetime.strptime(last_cleanup, "%Y-%m-%d %H:%M:%S")
    period = now - subtract_duration(now, item.value, item.unit)
    return now - last_cleanup_at >= period


def cleanup_by_mode(config: CleanupConfig, category: str, now: datetime | None = None) -> CleanupResult | None:
    """按清理对象的当前模式执行清理。

    Args:
        config: 当前自动清理配置。
        category: 清理对象，取 CATEGORIES 之一。
        now: 触发时机的时间，便于验证时指定；默认为当前时间。

    Returns:
        本次清理结果；永不清理模式或周期未达到时返回 None。
    """
    item = config.item(category)
    if item.mode == "periodic":
        if not needs_periodic_cleanup(config, category, now):
            CUS_LOGGER.debug(
                "周期清理：%s 距上次清理未达到 %s%s，本次不执行",
                CATEGORY_NAMES[category],
                item.value,
                UNIT_NAMES[item.unit],
            )
            return None
        CUS_LOGGER.debug("周期清理：%s 达到清理周期，开始清理", CATEGORY_NAMES[category])
        return cleanup_all(config, category, now)
    if item.mode == "automatic":
        CUS_LOGGER.debug(
            "自动清理：%s 开始清理超过保存期限的文件", CATEGORY_NAMES[category]
        )
        return cleanup_expired(config, category, now)
    return None


def write_last_cleanup(result: CleanupResult) -> str:
    """记录某个清理对象的上次清理时间。

    只要清理操作被实际触发就更新该时间，与本次成功删除的文件数量无关。

    Args:
        result: 本次清理结果。

    Returns:
        已写入的上次清理时间；写入失败时返回空字符串。
    """
    if not update_last_cleanup(result.category, result.cleaned_at):
        CUS_LOGGER.warning(
            "上次清理时间写入失败，本次清理结果仍然有效：%s",
            CATEGORY_NAMES[result.category],
        )
        return ""
    return result.cleaned_at


def run_scheduled_cleanup(
    trigger: str, config: CleanupConfig | None = None, now: datetime | None = None
) -> list[CleanupResult]:
    """在用户设置的触发时机执行周期清理与自动清理。

    手动清理由清理按钮触发，永不清理不执行任何操作，两者都会被跳过。

    Args:
        trigger: 本次触发时机，取 TRIGGERS 之一。
        config: 本次使用的自动清理配置；默认为读取当前配置文件。
        now: 触发时机的时间，便于验证时指定；默认为当前时间。

    Returns:
        实际执行了清理的清理对象的结果列表，未执行的类别不出现在其中。
    """
    if config is None:
        config = load_cleanup_config()
    now = now or datetime.now()

    results = []
    for category in CATEGORIES:
        if config.item(category).trigger != trigger:
            continue
        result = cleanup_by_mode(config, category, now)
        if result is None:
            continue
        if write_last_cleanup(result):
            results.append(result)
    return results


def log_cleanup_result(result: CleanupResult, is_manual: bool) -> None:
    """按触发方式输出一次清理结果。

    手动清理由用户主动触发，结果通过弹窗反馈，输出到 info 等级；周期清理
    与自动清理无需用户确认，输出到 debug 等级。两者都会进入主程序输出框
    与控制台。

    Args:
        result: 本次清理结果。
        is_manual: 是否为用户点击清理按钮触发。
    """
    text = f"{result.summary}（{CATEGORY_NAMES[result.category]}）"
    if is_manual:
        CUS_LOGGER.info(text)
    else:
        CUS_LOGGER.debug(text)


def run_cleanup(trigger: str) -> list[CleanupResult]:
    """执行一次触发时机驱动的清理，并输出结果。

    清理过程互斥：上一次清理尚未结束时跳过本次触发，避免重复扫描与并发写
    入上次清理时间。本函数由界面在后台线程调用，返回值同时通过
    cleanup_finished_signal 通知界面刷新。

    Args:
        trigger: 本次触发时机，取 TRIGGERS 之一。

    Returns:
        实际执行了清理的清理对象的结果列表；跳过本次触发时为空列表。
    """
    global _cleanup_running
    if _cleanup_running:
        CUS_LOGGER.debug("上一次自动清理尚未结束，跳过本次 %s 触发", trigger)
        return []

    _cleanup_running = True
    try:
        results = run_scheduled_cleanup(trigger)
    finally:
        _cleanup_running = False

    for result in results:
        log_cleanup_result(result, is_manual=False)
    if results:
        log_emitter.cleanup_finished_signal.emit(results)
    return results


def finish_manual_cleanup(result: CleanupResult) -> str:
    """记录并输出一次手动清理的结果。

    Args:
        result: 本次清理结果。

    Returns:
        已写入的上次清理时间；写入失败时返回本次清理时间。
    """
    log_cleanup_result(result, is_manual=True)
    return write_last_cleanup(result) or result.cleaned_at
