#!/usr/bin/env python3
"""Eval1 / Eval2 exactly as ConfiBench computes them, for any (driver, expected) pair.

  Eval1  the testbench accepts the golden design.
  Eval2  per mutant, the testbench's verdict agrees with the official VerilogEval
         testbench's verdict (both accept or both reject); ratio over ALL of the
         task's mutants; Eval2 = Eval1 and ratio >= 0.8, with ConfiBench's
         m2014_q3 exception. Mirrors TB4_eval.py and analyze.py.

Official verdicts are cached on disk: they are a fixed property of each mutant and
the official testbench, so they are computed once.
"""
from __future__ import annotations

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Dict, List, Optional

from dirtb.hdl import Trace, matches, official_accepts, simulate

LOOSE = 0.8
CACHE = Path(__file__).resolve().parent / "official_cache.json"
_lock = threading.Lock()


def _load_cache() -> Dict[str, Optional[bool]]:
    if CACHE.is_file():
        return json.loads(CACHE.read_text(encoding="utf-8"))
    return {}


_cache = _load_cache()


def official(task: dict, idx: int) -> bool:
    key = f"{task['task_id']}#{idx}"
    with _lock:
        if key in _cache:
            return bool(_cache[key])
    v = official_accepts(task["eval_mutants"][idx - 1], task["eval_official_tb"])
    with _lock:
        _cache[key] = bool(v)          # ConfiBench counts an unreadable run as a rejection
    return bool(v)


def save_cache() -> None:
    with _lock:
        CACHE.write_text(json.dumps(_cache, indent=0, sort_keys=True), encoding="utf-8")


def eval2_pass(task_id: str, eval1: bool, n_mut: int, failed: List[int]) -> bool:
    if not eval1 or n_mut == 0:
        return False
    ok = (n_mut - len(failed)) / n_mut >= LOOSE
    if task_id == "m2014_q3":
        return sorted(failed) == [3, 4, 7, 8, 9, 10] or ok
    return ok


def evaluate(task: dict, driver: str, expected: Trace, workers: int = 6) -> dict:
    muts = task["eval_mutants"]
    golden_ok = matches(expected, simulate(task["eval_golden"], driver, timeout=300))

    def one(i):
        ours = matches(expected, simulate(muts[i - 1], driver, timeout=120))
        off = official(task, i)
        return i, ours, off

    with ThreadPoolExecutor(max_workers=workers) as ex:
        results = list(ex.map(one, range(1, len(muts) + 1)))
    failed = [i for i, ours, off in results if ours != off]
    return {
        "task_id": task["task_id"], "circuit_type": task["circuit_type"], "split": task["split"],
        "eval1": golden_ok, "n_mutants": len(muts), "failed_mutants": failed,
        "ratio": (len(muts) - len(failed)) / max(1, len(muts)),
        "eval2": eval2_pass(task["task_id"], golden_ok, len(muts), failed),
        "missed": sum(1 for _, ours, off in results if ours and not off),
        "false_reject": sum(1 for _, ours, off in results if not ours and off),
    }
