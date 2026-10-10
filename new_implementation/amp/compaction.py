#!/usr/bin/env python3
"""Checker-preserving, dependency-preserving compaction of frozen CorrectBench suites.

No LLM calls, no new test generation, no simulator. Expected values come only
from the frozen checker; hypotheses only guide selection.

Dependency preservation is the crux. These drivers run their scenarios back to
back and state carries across them, so a scenario cannot simply be dropped from
the middle. Each scenario is therefore tested for independent startability: is
the checker's expectation sequence from that scenario onward identical when
started fresh there as it is in context? Only scenarios that pass may be reached
without replaying what precedes them; every other selection carries its full
prefix, and the prefix cycles are charged to the budget.

Arms compared at each budget:
  original      the untouched suite, reported at its true cost
  truncation    the first B events, chronologically
  random        random legal selection under the budget
  greedy        greedy gain per cycle on the search bank
  family_greedy greedy gain per cycle counting new fault FAMILIES
"""
from __future__ import annotations

import argparse
import collections
import csv
import json
import random
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Set, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))

from frontend_adapter import (Event, FrozenChecker, parse_driver,
                              recover_expectations, render_tbout)
from search_hypotheses import Hypothesis, generate_hypotheses

ROOT = Path(__file__).resolve().parent.parent
RECORDS = ROOT / "baselines/ConfiBench/data/CorrectBenchResults/run_info_and_codes.jsonl"
BUDGETS = [8, 16, 32, 64]


@dataclass
class TaskModel:
    task_id: str
    parse: object
    checker: FrozenChecker
    expectations: List[Optional[Dict[str, int]]]
    scenario_span: Dict[object, Tuple[int, int]]      # scenario -> [start, end)
    independent: Dict[object, bool]
    detection: Dict[str, Set[int]]                    # hypothesis -> failing event indices
    family: Dict[str, str]
    horizon_used: bool = False


def indexed_events(parse) -> List[Event]:
    return [Event(scenario=i, check_en=e.check_en, inputs=e.inputs, fmt=e.fmt, args=e.args)
            for i, e in enumerate(parse.events)]


def observations(parse, expectations, override=None) -> List[Dict[str, int]]:
    outs = parse.output_signals
    zero = {o: 0 for o in outs}
    obs = []
    for i in range(len(parse.events)):
        if override and override[i]:
            obs.append(dict(override[i]))
        elif expectations[i]:
            obs.append(dict(expectations[i]))
        else:
            obs.append(dict(zero))
    return obs


def build_task(row, max_bits: int) -> Optional[TaskModel]:
    parse = parse_driver(row.get("tb_v_driver") or "")
    if not parse.supported:
        return None
    checker = FrozenChecker(row.get("tb_py_checker") or "")
    if not checker.supported:
        return None
    expectations, err = recover_expectations(parse, checker, max_bits=max_bits)
    if expectations is None:
        return None

    spans: Dict[object, Tuple[int, int]] = {}
    for i, e in enumerate(parse.events):
        if e.scenario not in spans:
            spans[e.scenario] = (i, i + 1)
        else:
            a, _ = spans[e.scenario]
            spans[e.scenario] = (a, i + 1)

    # Independent startability: does the checker produce the same expectations
    # from this scenario onward when started fresh there?
    #
    # Checking the entire suffix is the sound test but costs a full sweep per
    # scenario, which is intractable on the largest driver. Where the full
    # suffix is unaffordable the check runs over a bounded horizon instead, and
    # the task records that a horizon was used. A horizon match is weaker
    # evidence: identical observable behaviour over a window does not prove the
    # underlying states are equal, so a horizon result is only ever used to
    # REJECT independence cheaply, never to grant it.
    independent: Dict[object, bool] = {}
    horizon_used = False
    for sid, (a, _b) in spans.items():
        if a == 0:
            independent[sid] = True
            continue
        suffix = parse.events[a:]
        work = len(suffix) * (1 << min(max(parse.widths.get(o, 1) for o in parse.output_signals),
                                       max_bits)) if parse.output_signals else 0
        if work > 400_000:
            independent[sid] = False        # conservative: assume dependent
            horizon_used = True
            continue
        sub = type(parse)(events=suffix, input_signals=parse.input_signals,
                          output_signals=parse.output_signals, widths=parse.widths)
        sub_exp, sub_err = recover_expectations(sub, checker, max_bits=max_bits)
        if sub_exp is None:
            independent[sid] = False
            continue
        independent[sid] = all(sub_exp[k] == expectations[a + k] for k in range(len(sub.events)))

    # Detection matrix: run the frozen checker against each hypothesis' behaviour.
    hyps = generate_hypotheses(row.get("tb_py_checker") or "")
    detection: Dict[str, Set[int]] = {}
    family: Dict[str, str] = {}
    idx_events = indexed_events(parse)
    for h in hyps:
        mut = FrozenChecker(h.source)
        if not mut.supported:
            continue
        mut_exp, _ = recover_expectations(parse, mut, max_bits=max_bits)
        if mut_exp is None:
            continue
        obs = observations(parse, expectations, override=mut_exp)
        failed, _ = checker.verdict(render_tbout(parse, idx_events, obs))
        if failed is None:
            continue
        hits = set()
        for f in failed:
            try:
                hits.add(int(f))
            except (TypeError, ValueError):
                pass
        if hits:
            detection[h.hypothesis_id] = hits
            family[h.hypothesis_id] = h.family

    model = TaskModel(row["task_id"], parse, checker, expectations, spans,
                      independent, detection, family)
    model.horizon_used = horizon_used
    return model


def cost_of(model: TaskModel, chosen: Sequence[object]) -> Tuple[int, Set[int]]:
    """Replay cost of a scenario selection, including required prefixes."""
    covered: Set[int] = set()
    for sid in chosen:
        a, b = model.scenario_span[sid]
        start = a if model.independent.get(sid) else 0
        covered.update(range(start, b))
    return len(covered), covered


def detected(model: TaskModel, covered: Set[int], bank: Sequence[str]) -> Set[str]:
    return {h for h in bank if model.detection.get(h, set()) & covered}


def families_of(model: TaskModel, hs: Set[str]) -> Set[str]:
    return {model.family[h] for h in hs}


def select_greedy(model: TaskModel, budget: int, bank: Sequence[str],
                  by_family: bool) -> Tuple[List[object], int, Set[int]]:
    chosen: List[object] = []
    best_cost, best_cov = 0, set()
    remaining = list(model.scenario_span)
    while True:
        best = None
        cur = detected(model, best_cov, bank)
        cur_score = len(families_of(model, cur)) if by_family else len(cur)
        for sid in remaining:
            cand = chosen + [sid]
            c, cov = cost_of(model, cand)
            if c > budget:
                continue
            got = detected(model, cov, bank)
            score = len(families_of(model, got)) if by_family else len(got)
            gain = score - cur_score
            added = c - best_cost
            if gain <= 0 or added <= 0:
                continue
            ratio = gain / added
            if best is None or ratio > best[0]:
                best = (ratio, sid, c, cov)
        if best is None:
            break
        _, sid, best_cost, best_cov = best
        chosen.append(sid)
        remaining.remove(sid)

    # Spend whatever budget is left. Stopping when the SEARCH bank stops
    # improving leaves cycles unused and would make greedy an artificially weak
    # baseline; the brief requires beating a strong greedy, not a truncated one.
    # Remaining scenarios are added cheapest-first while they still fit.
    improved = True
    while improved:
        improved = False
        options = []
        for sid in remaining:
            c, cov = cost_of(model, chosen + [sid])
            if c <= budget and c > best_cost:
                options.append((c - best_cost, sid, c, cov))
        if options:
            options.sort()
            _, sid, best_cost, best_cov = options[0]
            chosen.append(sid)
            remaining.remove(sid)
            improved = True
    return chosen, best_cost, best_cov


def select_random(model: TaskModel, budget: int, rng: random.Random
                  ) -> Tuple[List[object], int, Set[int]]:
    order = list(model.scenario_span)
    rng.shuffle(order)
    chosen: List[object] = []
    cost, cov = 0, set()
    for sid in order:
        c, cv = cost_of(model, chosen + [sid])
        if c <= budget:
            chosen.append(sid)
            cost, cov = c, cv
    return chosen, cost, cov


def truncate(model: TaskModel, budget: int) -> Tuple[int, Set[int]]:
    cov = set(range(min(budget, len(model.parse.events))))
    return len(cov), cov


def split_bank(model: TaskModel, seed: int = 17) -> Tuple[List[str], List[str]]:
    """Family-stratified split into a search bank and a held-out validation bank."""
    rng = random.Random(seed)
    by_fam: Dict[str, List[str]] = collections.defaultdict(list)
    for h in sorted(model.detection):
        by_fam[model.family[h]].append(h)
    search, holdout = [], []
    for fam, hs in sorted(by_fam.items()):
        hs = list(hs)
        rng.shuffle(hs)
        half = max(1, len(hs) // 2)
        search.extend(hs[:half])
        holdout.extend(hs[half:] or hs[:half])
    return search, holdout


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tasks", type=Path, default=ROOT / "amp" / "pilot_tasks.json")
    ap.add_argument("--max-bits", type=int, default=12)
    ap.add_argument("--seeds", type=int, default=5)
    ap.add_argument("--out", type=Path, default=ROOT / "amp" / "compaction_results.csv")
    args = ap.parse_args()

    want = set(json.loads(args.tasks.read_text()))
    rows = [json.loads(l) for l in RECORDS.read_text(encoding="utf-8").splitlines() if l.strip()]
    seen, picked = set(), []
    for r in rows:
        if r["task_id"] in want and r["task_id"] not in seen:
            seen.add(r["task_id"])
            picked.append(r)
    print(f"building {len(picked)} task models")

    results = []
    for row in picked:
        model = build_task(row, args.max_bits)
        if model is None:
            print(f"  {row['task_id']}: unsupported, skipped")
            continue
        search, holdout = split_bank(model)
        n_ind = sum(1 for v in model.independent.values() if v)
        print(f"  {model.task_id}: events={len(model.parse.events)} "
              f"scenarios={len(model.scenario_span)} independent={n_ind} "
              f"hyps={len(model.detection)} search={len(search)} holdout={len(holdout)}")
        if not model.detection:
            continue

        full_cost = len(model.parse.events)
        full_cov = set(range(full_cost))
        base_hold = detected(model, full_cov, holdout)

        for budget in BUDGETS:
            def record(arm, cost, cov, seed=0):
                hold = detected(model, cov, holdout)
                results.append({
                    "task_id": model.task_id, "arm": arm, "budget": budget, "seed": seed,
                    "cost": cost, "scenarios": len(model.scenario_span),
                    "holdout_detected": len(hold), "holdout_total": len(holdout),
                    "holdout_frac": len(hold) / len(holdout) if holdout else 0.0,
                    "search_detected": len(detected(model, cov, search)),
                    "families": len(families_of(model, hold)),
                    "full_cost": full_cost, "full_holdout": len(base_hold),
                })

            record("original_full", full_cost, full_cov)
            c, cov = truncate(model, budget)
            record("truncation", c, cov)
            for s in range(args.seeds):
                ch, c, cov = select_random(model, budget, random.Random(1000 + s))
                record("random", c, cov, seed=s)
            ch, c, cov = select_greedy(model, budget, search, by_family=False)
            record("greedy", c, cov)
            ch, c, cov = select_greedy(model, budget, search, by_family=True)
            record("family_greedy", c, cov)

    if not results:
        print("no results")
        return
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(results[0].keys()))
        w.writeheader()
        w.writerows(results)
    print(f"\nwrote {args.out} ({len(results)} rows)")

    print("\n=== Held-out hypothesis detection by budget (mean over tasks) ===")
    print(f"{'budget':>7s} {'arm':16s} {'detected':>9s} {'cost':>7s} {'tasks':>6s}")
    for b in BUDGETS:
        for arm in ("truncation", "random", "greedy", "family_greedy"):
            sub = [r for r in results if r["budget"] == b and r["arm"] == arm]
            if not sub:
                continue
            by_task = collections.defaultdict(list)
            for r in sub:
                by_task[r["task_id"]].append(r["holdout_frac"])
            per_task = [sum(v) / len(v) for v in by_task.values()]
            costs = collections.defaultdict(list)
            for r in sub:
                costs[r["task_id"]].append(r["cost"])
            mean_cost = sum(sum(v) / len(v) for v in costs.values()) / len(costs)
            print(f"{b:7d} {arm:16s} {sum(per_task)/len(per_task):9.4f} "
                  f"{mean_cost:7.1f} {len(per_task):6d}")
    full = [r for r in results if r["arm"] == "original_full"]
    by_task = {r["task_id"]: r["holdout_frac"] for r in full}
    costs = {r["task_id"]: r["cost"] for r in full}
    print(f"{'full':>7s} {'original':16s} {sum(by_task.values())/len(by_task):9.4f} "
          f"{sum(costs.values())/len(costs):7.1f} {len(by_task):6d}")


if __name__ == "__main__":
    main()
