"""开局词缀采样：记录每局刷出的词缀，并累计出现次数。

刷开局时每局只走到词缀界面就重开，这里负责把「这一把刷出了哪几个词缀」留痕：
明细写 CSV，汇总写一份便于人看的 txt（含"目标词缀出现了几次"）。
"""

import os
import time
from collections import Counter

from core.currency.textmatch import similar
from route import PATHS
from tool import EXTRA

DEFAULT_SAMPLE_PATH = os.path.join(PATHS["backup"], "affix_samples.csv")
DEFAULT_SUMMARY_PATH = os.path.join(PATHS["backup"], "affix_summary.txt")

_CSV_HEADER = "时间,把次,词缀,命中目标\n"


class AffixSampler:
    """累计统计 + 落盘；不依赖 OCR，纯记录。"""

    def __init__(self, sample_path=DEFAULT_SAMPLE_PATH, summary_path=DEFAULT_SUMMARY_PATH):
        self.sample_path = sample_path
        self.summary_path = summary_path
        self.run_index = 0
        self.counter = Counter()

    def record(self, affixes, targets=()):
        """记录一局的词缀列表，返回本次命中的目标词缀。"""
        affixes = [text for text in affixes if text]
        if not affixes:
            return []

        self.run_index += 1
        targets = list(targets)
        # 用形近字容错判断命中：OCR 认错一个字也不该算漏采
        hits = [text for text in affixes if any(similar(text, target) for target in targets)]
        self.counter.update(affixes)
        self._append_csv(affixes, hits)
        self._write_summary(targets)
        return hits

    def _append_csv(self, affixes, hits):
        """一局一行：词缀用「|」拼接，命中目标单独一列。"""
        line = f"{time.strftime('%Y-%m-%d %H:%M:%S')},{self.run_index},{'|'.join(affixes)},{'|'.join(hits)}\n"
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

            CUS_LOGGER.warning("词缀采样 CSV 写入失败：%s", error)

    def _write_summary(self, targets):
        """汇总：按出现次数排序，目标词缀即使 0 次也列出来。"""
        rows = [f"# 开局词缀采样：累计 {self.run_index} 把，共 {len(self.counter)} 种词缀\n"]
        rows.append(f"{'次数':>6}  词缀\n")
        for text, count in self.counter.most_common():
            mark = "  ← 目标" if any(similar(text, t) for t in targets) else ""
            rows.append(f"{count:>6}  {text}{mark}\n")
        missing = [
            text for text in targets
            if not any(similar(seen, text) for seen in self.counter)
        ]
        if missing:
            rows.append("\n# 目标词缀中尚未出现：\n")
            rows.extend(f"      0  {text}  ← 目标\n" for text in missing)
        try:
            with EXTRA.FILE_LOCK:
                os.makedirs(os.path.dirname(self.summary_path) or ".", exist_ok=True)
                with open(self.summary_path, "w", encoding="utf-8") as handle:
                    handle.writelines(rows)
        except OSError as error:
            from tool.log import CUS_LOGGER

            CUS_LOGGER.warning("词缀采样汇总写入失败：%s", error)
