"""定时计划的持久化与时间推进，不依赖窗口和运行内核。"""

import json
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timedelta
from pathlib import Path
from uuid import uuid4

from route import PATHS
from tool.storage import write_data


@dataclass(frozen=True)
class Plan:
    id: str
    name: str
    engine: str
    script: str
    run_at: str
    repeat: str = "once"
    enabled: bool = True
    result: str = "等待执行"
    last_run: str = ""
    interruptible: bool = False

    @classmethod
    def create(cls, name, engine, script, run_at, repeat="once", *, interruptible=False):
        return cls(uuid4().hex, name, engine, script, run_at.isoformat(timespec="seconds"), repeat,
                   interruptible=interruptible)

    def validate(self):
        if not all(isinstance(value, str) and value.strip()
                   for value in (self.id, self.name, self.engine, self.script, self.run_at)):
            raise ValueError("计划名称、内核、脚本和时间不能为空")
        if self.repeat not in ("once", "daily", "weekly") or not isinstance(self.enabled, bool) or not isinstance(self.interruptible, bool):
            raise ValueError("计划的重复方式或开关状态无效")
        when = datetime.fromisoformat(self.run_at)
        if when.tzinfo is not None:
            raise ValueError("计划时间必须采用本机时间")
        if not isinstance(self.result, str) or not isinstance(self.last_run, str):
            raise ValueError("计划执行记录无效")
        return self


def next_run(when, now, repeat):
    """推进每日或每周计划至未来的同一时刻，错过的周期不补跑。"""
    interval = timedelta(days={"daily": 1, "weekly": 7}[repeat])
    return when + max(1, (now - when) // interval + 1) * interval


class ScheduleBook:
    def __init__(self, path=None):
        self.path = Path(path or Path(PATHS["config"]) / "schedules.json")
        self.plans = []
        if self.path.exists():
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(data, list):
                raise ValueError("计划配置必须是列表")
            try:
                self.plans = [Plan(**item).validate() for item in data]
            except (TypeError, AttributeError) as error:
                raise ValueError(f"计划配置格式错误：{error}") from error
            if len({plan.id for plan in self.plans}) != len(self.plans):
                raise ValueError("计划 ID 重复")

    def save(self, plans):
        """先保存再更新内存；失败时原计划及执行机会不变。"""
        for plan in plans:
            plan.validate()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        write_data(self.path, json.dumps([asdict(plan) for plan in plans], ensure_ascii=False, indent=4) + "\n")
        self.plans = plans

    def put(self, plan):
        plans = [plan if item.id == plan.id else item for item in self.plans]
        if not any(item.id == plan.id for item in self.plans):
            plans.append(plan)
        self.save(plans)

    def remove(self, plan_id):
        self.save([plan for plan in self.plans if plan.id != plan_id])

    def skip_missed(self, now):
        plans = []
        for plan in self.plans:
            when = datetime.fromisoformat(plan.run_at)
            if plan.enabled and when < now:
                plan = replace(plan, result="错过时间，未补跑", enabled=plan.repeat != "once",
                               run_at=next_run(when, now, plan.repeat).isoformat(timespec="seconds") if plan.repeat != "once" else plan.run_at)
            plans.append(plan)
        if plans != self.plans:
            self.save(plans)

    def due(self, now):
        return sorted((plan for plan in self.plans if plan.enabled and datetime.fromisoformat(plan.run_at) <= now),
                      key=lambda plan: (plan.run_at, plan.id))

    def claim(self, plan, now):
        """启动前记录本次触发，重启后不会重复发起同一次执行。"""
        when = datetime.fromisoformat(plan.run_at)
        claimed = replace(plan, enabled=plan.repeat != "once", result="已触发",
                          last_run=now.isoformat(timespec="seconds"),
                          run_at=next_run(when, now, plan.repeat).isoformat(timespec="seconds") if plan.repeat != "once" else plan.run_at)
        self.put(claimed)
        return claimed
