import os
import re
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from route import PATHS
from tool import EXTRA

RUN_START_ACTION = "选择难度后开始对局"
RUN_END_ACTION = "重开最终"
DEFAULT_RECORD_PATH = os.path.join(PATHS["backup"], "currency_count.txt")
_COUNT_PATTERN = re.compile(r"对局次数\s*[：:]\s*(\d+)")


def get_newly_unlocked_investment(
    texts: Sequence[str],
    icon_presence: Sequence[bool],
    selected_index: int,
) -> str | None:
    """Return the selected investment only when its compendium icon is present."""
    if not 0 <= selected_index < len(texts) or selected_index >= len(icon_presence):
        return None
    if not icon_presence[selected_index]:
        return None

    text = texts[selected_index].strip()
    return text or None


@dataclass
class CurrencyRunHistory:
    record_path: str = DEFAULT_RECORD_PATH
    clock: Callable[[], float] = time.time
    _started_at: float | None = field(default=None, init=False)
    _unlocked_investments: list[str] = field(default_factory=list, init=False)

    @property
    def is_active(self) -> bool:
        return self._started_at is not None

    def start_run(self) -> None:
        self._started_at = self.clock()
        self._unlocked_investments.clear()

    def record_unlocked_investment(self, investment: str) -> bool:
        investment = investment.strip()
        if not self.is_active or not investment or investment in self._unlocked_investments:
            return False

        self._unlocked_investments.append(investment)
        return True

    def finish_run(self) -> str | None:
        if self._started_at is None:
            return None

        elapsed = max(0, int(self.clock() - self._started_at))
        investments = "、".join(self._unlocked_investments) or "无"

        try:
            with EXTRA.FILE_LOCK:
                run_count = self._read_last_run_count() + 1
                record = (
                    f"对局次数：{run_count}，本局解锁的投资策略：{investments}，"
                    f"用时：{elapsed // 60}分{elapsed % 60}秒"
                )
                os.makedirs(os.path.dirname(self.record_path), exist_ok=True)
                with open(self.record_path, "a", encoding="utf-8") as file:
                    file.write(record + "\n")
        finally:
            self._started_at = None
            self._unlocked_investments.clear()

        return record

    def _read_last_run_count(self) -> int:
        if not os.path.exists(self.record_path):
            return 0

        with open(self.record_path, encoding="utf-8", errors="replace") as file:
            for line in file:
                match = _COUNT_PATTERN.search(line)
                if match:
                    last_count = max(last_count, int(match.group(1)))
        return last_count
