"""投资策略采样：记录每次「请选择投资策略」出现过的策略，并与 298 条名单对账。

与 `affix_stats` 的区别：策略是"三选一"的界面，一次会出现三张卡，所以这里按「屏」记录，
同时记下这一屏在第几位面（4.7 里同一个策略可能在不同位面出现）。
"""

import os
import time
from collections import Counter

from core.currency.strategies import STRATEGY_NAMES
from route import PATHS
from tool import EXTRA

DEFAULT_SAMPLE_PATH = os.path.join(PATHS["backup"], "strategy_samples.csv")
DEFAULT_SUMMARY_PATH = os.path.join(PATHS["backup"], "strategy_summary.txt")

_CSV_HEADER = "时间,把次,位面,本屏出现,选中,命中目标\n"


class StrategySampler:
    """累计统计 + 落盘；不依赖 OCR，纯记录。"""

    def __init__(self, sample_path=DEFAULT_SAMPLE_PATH, summary_path=DEFAULT_SUMMARY_PATH):
        self.sample_path = sample_path
        self.summary_path = summary_path
        self.run_index = 0
        self.screen_index = 0
        self.seen = Counter()          # 名字 → 出现次数
        self.first_plane = {}          # 名字 → 第一次出现在第几面

    # ---- 记录 ----

    def record(self, plane, options, chosen=None, targets=(), run_index=None):
        """记录一屏策略（三张卡），返回本屏命中的目标策略。"""
        options = [name for name in options if name]
        if not options:
            return []

        if run_index is not None:
            self.run_index = run_index
        self.screen_index += 1
        targets = list(targets)
        hits = [name for name in options if name in targets]

        for name in options:
            self.seen[name] += 1
            self.first_plane.setdefault(name, plane)

        self._append_csv(plane, options, chosen, hits)
        self._write_summary(targets)
        return hits

    # ---- 对账 ----

    @property
    def collected(self):
        """已经刷到过的策略名。"""
        return set(self.seen)

    def missing(self, candidates=None):
        """还没刷到的策略（默认对 298 条全名单）。"""
        pool = list(candidates) if candidates is not None else list(STRATEGY_NAMES)
        return [name for name in pool if name not in self.seen]

    # ---- 落盘 ----

    def _append_csv(self, plane, options, chosen, hits):
        line = (
            f"{time.strftime('%Y-%m-%d %H:%M:%S')},{self.run_index},{plane},"
            f"{'|'.join(options)},{chosen or ''},{'|'.join(hits)}\n"
        )
        try:
            with EXTRA.FILE_LOCK:
                os.makedirs(os.path.dirname(self.sample_path) or ".", exist_ok=True)
                new_file = not os.path.exists(self.sample_path)
                with open(self.sample_path, "a", encoding="utf-8") as handle:
                    if new_file:
                        handle.write(_CSV_HEADER)
                    handle.write(line)
        except OSError as error:
            from tool.log import CUS_LOGGER

            CUS_LOGGER.warning("策略采样 CSV 写入失败：%s", error)

    def _write_summary(self, targets):
        rows = [
            f"# 投资策略采样：{self.run_index} 把 / {self.screen_index} 屏，"
            f"已见过 {len(self.seen)} / {len(STRATEGY_NAMES)} 种\n"
        ]
        if targets:
            pending = [name for name in targets if name not in self.seen]
            rows.append(f"\n# 目标策略：{len(targets)} 条，已收集 {len(targets) - len(pending)} 条\n")
            if pending:
                rows.append("  尚未收集：\n")
                rows.extend(f"    {name}\n" for name in pending)
        missing = self.missing()
        if missing:
            rows.append(f"\n# 全名单尚未出现（{len(missing)} 条）：\n")
            rows.extend(f"    {name}\n" for name in missing)
        try:
            with EXTRA.FILE_LOCK:
                os.makedirs(os.path.dirname(self.summary_path) or ".", exist_ok=True)
                with open(self.summary_path, "w", encoding="utf-8") as handle:
                    handle.writelines(rows)
        except OSError as error:
            from tool.log import CUS_LOGGER

            CUS_LOGGER.warning("策略采样汇总写入失败：%s", error)
