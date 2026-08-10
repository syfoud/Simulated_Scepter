#!/usr/bin/env python3
"""倒计时 DP 极限图扫描器。

对 countdown_map 三位面地图逐张调用 ExactCountdownDP，求各图 DP 理论最大 CD，
找出每位面 max/min 的图，以及三位面线性相加的 max/min 组合。

用法：
    python test/find_extreme_dp_maps.py                     # 并行扫描全部
    python test/find_extreme_dp_maps.py --sample 10         # 每位面随机抽样 N 张（快）
    python test/find_extreme_dp_maps.py --use-cache         # 只补算未缓存的图
    python test/find_extreme_dp_maps.py --report-only       # 只看缓存中的已有结果
    python test/find_extreme_dp_maps.py --workers 4 -p 3    # 指定并行数 + 位面
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import random
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Optional

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_TEST_DIR = os.path.dirname(os.path.abspath(__file__))

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

logging.disable(logging.CRITICAL)

MAP_DIR = os.path.join(_TEST_DIR, "countdown_map")
CACHE_FILE = os.path.join(_TEST_DIR, "dp_extreme_cache.json")
REPORT_FILE = os.path.join(_TEST_DIR, "dp_extreme_report.txt")

INITIAL_CD_PLANE = {1: 15, 2: 0, 3: 0}
INITIAL_CHEAT = 2
INITIAL_REROLL = 3

MAX_STATES = 250_000
MAX_SPREAD = 50_000


# ======================================================================
@dataclass
class SingleMapResult:
    image_path: str
    plane: int
    max_cd: int
    final_cheat: int
    final_reroll: int
    states: int
    error: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.error is None


# ======================================================================
def _worker(args: tuple) -> dict:
    """子进程：加载地图 -> DP 求解 -> 返回 dict。"""
    image_path, plane, cd, cheat, reroll, project_root, test_dir = args
    sys.path.insert(0, project_root)
    sys.path.insert(0, test_dir)
    logging.disable(logging.CRITICAL)

    result = {"image_path": image_path, "plane": plane, "max_cd": 0,
              "final_cheat": cheat, "final_reroll": reroll, "states": 0, "error": None}

    try:
        from countdown_backend import (
            ALL_EFFECTS, CountdownState, DecisionContext, PHASE_EFFECT)
        from countdown_dp import ExactCountdownDP
        from countdown_map_loader import load_countdown_map

        prepared = load_countdown_map(image_path, plane=plane)
        model = prepared.model
        start_state = CountdownState(
            model.start_idx, model.initial_infected, cd, cheat, reroll)

        best_cd, best_fc, best_fr, best_st = -10**9, cheat, reroll, 0
        for observed in ALL_EFFECTS:
            ctx = DecisionContext(PHASE_EFFECT, start_state, observed)
            try:
                r = ExactCountdownDP(model, max_states=MAX_STATES,
                                     max_spread_outcomes=MAX_SPREAD).solve(ctx)
                if r.max_countdown > best_cd:
                    best_cd, best_st = r.max_countdown, r.states_evaluated
                    if r.steps:
                        best_fc = r.steps[-1].cheat_after
                        best_fr = r.steps[-1].reroll_after
            except Exception:
                pass

        if best_cd == -10**9:
            result["error"] = "DP 所有初始效果均失败"
        else:
            result.update(max_cd=best_cd, final_cheat=best_fc,
                          final_reroll=best_fr, states=best_st)
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"

    return result


# ======================================================================
def _to_dict(r: SingleMapResult) -> dict:
    return {"image_path": r.image_path, "plane": r.plane, "max_cd": r.max_cd,
            "final_cheat": r.final_cheat, "final_reroll": r.final_reroll,
            "states": r.states, "error": r.error}


def _from_dict(d: dict) -> SingleMapResult:
    return SingleMapResult(**{k: d.get(k) for k in [
        "image_path", "plane", "max_cd", "final_cheat", "final_reroll", "states", "error"]})


def load_cache():
    if not os.path.isfile(CACHE_FILE):
        return {}
    with open(CACHE_FILE, "r", encoding="utf-8") as f:
        return {p: _from_dict(v) for p, v in json.load(f).items()}


def save_cache(cache):
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump({p: _to_dict(r) for p, r in cache.items()}, f,
                  ensure_ascii=False, indent=2)


# ======================================================================
def collect_paths():
    planes = {}
    for p in (1, 2, 3):
        d = os.path.join(MAP_DIR, f"map{p}")
        if os.path.isdir(d):
            planes[p] = sorted(
                os.path.join(d, n) for n in os.listdir(d)
                if os.path.splitext(n)[1].lower() in (".png", ".jpg", ".jpeg", ".bmp"))
        else:
            planes[p] = []
    return planes


def compute_maps(task_list, workers):
    """并行计算一批地图，返回更新后的 cache。"""
    cache = load_cache()
    pending = [(path, pl) for path, pl in task_list
               if path not in cache or not cache[path].ok]
    if not pending:
        print("  全部已缓存，跳过。")
        return cache

    worker_args = [(path, pl, INITIAL_CD_PLANE[pl], INITIAL_CHEAT, INITIAL_REROLL,
                    _PROJECT_ROOT, _TEST_DIR) for path, pl in pending]
    total = len(pending)
    workers = max(1, min(workers, total))
    print(f"  待算 {total} 张 -> {workers} 进程并行")
    t0 = time.perf_counter()
    done = fail = 0

    with ProcessPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(_worker, a): a for a in worker_args}
        for fut in as_completed(futs):
            path, pl = futs[fut][0], futs[fut][1]
            try:
                r = _from_dict(fut.result())
            except Exception as exc:
                r = SingleMapResult(path, pl, 0, INITIAL_CHEAT, INITIAL_REROLL, 0,
                                    error=f"Worker异常: {exc}")
            cache[path] = r
            done += 1
            if not r.ok:
                fail += 1
            elapsed = time.perf_counter() - t0
            eta = (elapsed / done) * (total - done) if done > 0 else 0
            print(f"  [{done:4d}/{total}] {eta:5.0f}s剩  "
                  f"{os.path.basename(path):30s}  "
                  f"{'CD=' + str(r.max_cd) if r.ok else 'FAIL'}")
            save_cache(cache)

    print(f"  耗时 {time.perf_counter() - t0:.0f}s  成功 {done - fail}  失败 {fail}")
    return cache


# ======================================================================
def generate_report(ranked):
    """生成文本报告。"""
    lines = []
    w = lines.append

    w("=" * 60)
    w("倒计时 DP 极限图扫描报告")
    w(f"生成时间: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    w(f"初始条件: 位面1 CD=15  位面2/3 CD=0  Cheat={INITIAL_CHEAT}  Reroll={INITIAL_REROLL}")
    w("=" * 60)

    for plane in (1, 2, 3):
        results = ranked[plane]
        if not results:
            w(f"\n[位面 {plane}] 无有效数据")
            continue
        best, worst = results[0], results[-1]
        mean_cd = sum(r.max_cd for r in results) / len(results)
        w(f"\n{'─'*40}")
        w(f"位面 {plane}  --  {len(results)} 张有效图  --  "
          f"平均 DP={mean_cd:.1f}  范围 [{worst.max_cd}, {best.max_cd}]")
        w(f"{'─'*40}")
        w(f"  * 最大: CD={best.max_cd:4d}  "
          f"cheat余{best.final_cheat} reroll余{best.final_reroll}")
        w(f"     -> {os.path.basename(best.image_path)}")
        w(f"  * 最小: CD={worst.max_cd:4d}  "
          f"cheat余{worst.final_cheat} reroll余{worst.final_reroll}")
        w(f"     -> {os.path.basename(worst.image_path)}")

        w(f"  Top 5:")
        for i, r in enumerate(results[:5], 1):
            w(f"    {i}. CD={r.max_cd:4d}  {os.path.basename(r.image_path)}")
        w(f"  Bottom 5:")
        for i, r in enumerate(results[-5:], 1):
            w(f"    {i}. CD={r.max_cd:4d}  {os.path.basename(r.image_path)}")

        w(f"\n  完整排序 ({len(results)} 张):")
        for i, r in enumerate(results, 1):
            w(f"    {i:3d}. CD={r.max_cd:4d}  c={r.final_cheat} r={r.final_reroll}  "
              f"{os.path.basename(r.image_path)}")

    # --- 三位面线性相加组合 ---
    if all(ranked[p] for p in (1, 2, 3)):
        best1, best2, best3 = ranked[1][0], ranked[2][0], ranked[3][0]
        worst1, worst2, worst3 = ranked[1][-1], ranked[2][-1], ranked[3][-1]
        best_sum = best1.max_cd + best2.max_cd + best3.max_cd
        worst_sum = worst1.max_cd + worst2.max_cd + worst3.max_cd

        w(f"\n{'='*60}")
        w("三位面 DP 极限组合（线性相加）")
        w(f"{'='*60}")

        w(f"\n  * 最大组合（和 = {best_sum}）:")
        w(f"    位面1: CD={best1.max_cd}  {os.path.basename(best1.image_path)}")
        w(f"    位面2: CD={best2.max_cd}  {os.path.basename(best2.image_path)}")
        w(f"    位面3: CD={best3.max_cd}  {os.path.basename(best3.image_path)}")

        w(f"\n  * 最小组合（和 = {worst_sum}）:")
        w(f"    位面1: CD={worst1.max_cd}  {os.path.basename(worst1.image_path)}")
        w(f"    位面2: CD={worst2.max_cd}  {os.path.basename(worst2.image_path)}")
        w(f"    位面3: CD={worst3.max_cd}  {os.path.basename(worst3.image_path)}")

    report = "\n".join(lines)
    try:
        print(report)
    except UnicodeEncodeError:
        for line in lines:
            try:
                print(line)
            except UnicodeEncodeError:
                print(line.encode("ascii", errors="replace").decode("ascii"))

    with open(REPORT_FILE, "w", encoding="utf-8") as f:
        f.write(report)
    print(f"\n报告已保存到: {REPORT_FILE}")


# ======================================================================
def main():
    p = argparse.ArgumentParser(description="倒计时 DP 极限图扫描器")
    p.add_argument("--sample", "-s", type=int, default=0,
                   help="每位面随机抽样 N 张（0=全部）")
    p.add_argument("--use-cache", action="store_true", help="跳过已缓存的图")
    p.add_argument("--report-only", action="store_true",
                   help="仅基于现有缓存生成报告，不计算新图")
    p.add_argument("--workers", "-w", type=int, default=min(8, (os.cpu_count() or 4)),
                   help="并行进程数")
    p.add_argument("--plane", "-p", type=int, nargs="+", default=[1, 2, 3],
                   help="只处理指定位面 (如 -p 3)")
    args = p.parse_args()

    planes = collect_paths()
    total = sum(len(v) for v in planes.values())
    print(f"地图文件: map1={len(planes[1])}  map2={len(planes[2])}  "
          f"map3={len(planes[3])}  (共 {total})")

    # --- 计算 ---
    if args.report_only:
        cache = load_cache()
        ok = sum(1 for r in cache.values() if r.ok)
        print(f"报告模式: 缓存中 {ok}/{len(cache)} 张有效，跳过计算。")
    elif args.sample > 0:
        cache = load_cache()
        rng = random.Random(42)
        tasks = []
        for pl in args.plane:
            uncached = [p for p in planes[pl]
                        if p not in cache or not cache[p].ok]
            n = min(args.sample, len(uncached))
            tasks.extend((p, pl) for p in rng.sample(uncached, n))
        print(f"随机抽样 {args.sample} 张/位面 (位面{args.plane}) -> 共 {len(tasks)} 张")
        cache = compute_maps(tasks, args.workers)
    elif args.use_cache:
        cache = load_cache()
        tasks = []
        for pl in args.plane:
            for p in planes[pl]:
                if p not in cache or not cache[p].ok:
                    tasks.append((p, pl))
        if tasks:
            print(f"补算 {len(tasks)} 张未缓存图 (位面{args.plane})")
            cache = compute_maps(tasks, args.workers)
        else:
            print("全部已缓存")
    else:
        cache = load_cache()
        tasks = [(p, pl) for pl in args.plane for p in planes[pl]
                 if p not in cache or not cache[p].ok]
        print(f"全量计算 {len(tasks)} 张... (位面{args.plane})")
        cache = compute_maps(tasks, args.workers)

    # --- 排序 ---
    ranked = {}
    for pl in (1, 2, 3):
        ranked[pl] = sorted(
            (cache[p] for p in planes[pl] if p in cache and cache[p].ok),
            key=lambda x: -x.max_cd)

    for pl in (1, 2, 3):
        r = ranked[pl]
        print(f"位面 {pl}: {len(r)} 张  max={r[0].max_cd if r else '?'}  "
              f"min={r[-1].max_cd if r else '?'}")

    # --- 报告 ---
    generate_report(ranked)


if __name__ == "__main__":
    main()
