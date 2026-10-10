#!/usr/bin/env python3
"""One execution path, every arm, every outcome named.

Earlier comparisons put the frontend's PUBLISHED numbers next to numbers our own
harness produced. Those are not comparable on their own: a difference can come
from the method or from the harness, and there was no way to tell which. Worse,
rows our harness could not evaluate were quietly dropped, which shrinks the
denominator in whichever arm happens to fail -- flattering it.

This module fixes both. Every arm runs through the SAME `execute()`, on the SAME
artefacts, over the SAME mutant ids, and every (task, design, arm) triple gets an
explicit outcome from a closed taxonomy. Nothing is filtered; anything that
cannot be scored is COUNTED as unscoreable and reported.

Fixed reference arms, present in every run:

  literal    the frontend's own `tb_v_driver` bytes, exactly as published.
  primary    ACTIVE-TB-SAFE Channel 1. By construction these are the same bytes,
             so `literal` and `primary` MUST agree; any row where they differ is
             a defect in our packaging and is reported as a divergence.

Then one `combined` arm per `--arm NAME=RUNDIR`:

  combined   V_aug(D) = V1(D) AND NOT ShadowAlarm(D). A Channel 2 warning counts
             AGAINST this arm on a design the official testbench accepts, so a
             false alarm is paid for here rather than hidden.

Three scopes, all printed, never collapsed:

  requested  every task asked for (the pre-registered denominator)
  available  tasks whose frontend artefacts exist and parse
  complete   tasks where the reference arms returned a definite verdict on
             Golden and on at least one mutant

Scoring every arm in one invocation is not just convenience: results are cached
on the sha256 of (driver, design), and Channel 1 is byte-identical across arms,
so it is simulated once instead of once per arm. The cache key is full content,
so caching cannot change any verdict.
"""
from __future__ import annotations

import argparse
import contextlib
import csv
import hashlib
import io
import json
import os
import re
import subprocess
import tempfile
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

LOOSE_FACTOR = 0.8
MISMATCH_RE = re.compile(r"Mismatches:\s*(\d+)\s+in\s+(\d+)\s+samples")

PASS = "PASS"
FAIL = "FAIL"
COMPILE_ERROR = "COMPILE_ERROR"
TIMEOUT = "TIMEOUT"
NO_OUTPUT = "NO_OUTPUT"
CHECKER_ERROR = "CHECKER_ERROR"
SETUP_ERROR = "SETUP_ERROR"
MISSING_ARTIFACT = "MISSING_ARTIFACT"
OUTCOMES = [PASS, FAIL, COMPILE_ERROR, TIMEOUT, NO_OUTPUT, CHECKER_ERROR,
            SETUP_ERROR, MISSING_ARTIFACT]
DEFINITE = {PASS, FAIL}


@contextlib.contextmanager
def _muted():
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        yield


@dataclass
class Result:
    outcome: str
    detail: str = ""

    @property
    def accepted(self) -> Optional[bool]:
        if self.outcome == PASS:
            return True
        if self.outcome == FAIL:
            return False
        return None


def _sha(*parts: str) -> str:
    h = hashlib.sha256()
    for p in parts:
        h.update(p.encode("utf-8", "replace"))
        h.update(b"\x00")
    return h.hexdigest()


class Runner:
    """Executes designs against drivers, memoised on content hashes."""

    def __init__(self, work: Path, timeout: int = 120):
        self.work = work
        self.timeout = timeout
        self._cache: Dict[str, Result] = {}
        self.calls = 0
        self.hits = 0

    def _clean(self) -> None:
        for f in self.work.glob("*"):
            if f.is_file():
                f.unlink()

    def execute(self, rtl: str, driver: str, checker_src: str) -> Result:
        """Run one design against one driver, scored by its frozen checker.

        This is the only path any arm uses. Sharing it is the point: a difference
        between arms is then a difference in artefacts, never in the harness.
        """
        if not rtl or not driver:
            return Result(MISSING_ARTIFACT, "empty rtl or driver")
        if not checker_src:
            return Result(MISSING_ARTIFACT, "no checker")
        key = _sha(rtl, driver, checker_src)
        if key in self._cache:
            self.hits += 1
            return self._cache[key]
        self.calls += 1
        res = self._execute_uncached(rtl, driver, checker_src)
        self._cache[key] = res
        return res

    def _execute_uncached(self, rtl: str, driver: str, checker_src: str) -> Result:
        try:
            self._clean()
            (self.work / "dut.v").write_text(rtl, encoding="utf-8")
            (self.work / "tb.v").write_text(driver, encoding="utf-8")
        except OSError as exc:
            return Result(SETUP_ERROR, f"{type(exc).__name__}: {exc}"[:160])
        try:
            c = subprocess.run(["iverilog", "-g2012", "-o", "sim", "dut.v", "tb.v"],
                               cwd=self.work, capture_output=True, text=True,
                               timeout=self.timeout)
        except subprocess.TimeoutExpired:
            return Result(TIMEOUT, "iverilog")
        except OSError as exc:
            return Result(SETUP_ERROR, f"iverilog unavailable: {exc}"[:160])
        if c.returncode != 0:
            first = (c.stderr.strip().splitlines() or [""])[0]
            return Result(COMPILE_ERROR, first[:160])
        try:
            subprocess.run(["vvp", "sim"], cwd=self.work, capture_output=True,
                           text=True, timeout=self.timeout)
        except subprocess.TimeoutExpired:
            return Result(TIMEOUT, "vvp")
        out = self.work / "TBout.txt"
        if not out.is_file():
            return Result(NO_OUTPUT, "no TBout.txt")
        tbout = out.read_text(encoding="utf-8", errors="replace")

        cwd = os.getcwd()
        with tempfile.TemporaryDirectory(prefix="rec_") as td:
            Path(td, "TBout.txt").write_text(tbout, encoding="utf-8")
            try:
                os.chdir(td)
                ns: Dict[str, object] = {}
                cut = checker_src.find('with open("TBout.txt"')
                defs = checker_src if cut == -1 else checker_src[:cut]
                with _muted():
                    exec(compile(defs, "<frozen>", "exec"), ns)
                    vecs = ns["SignalTxt_to_dictlist"](tbout)
                    failed = list(ns["check_dut"](vecs))
            except Exception as exc:
                return Result(CHECKER_ERROR, f"{type(exc).__name__}: {exc}"[:160])
            finally:
                os.chdir(cwd)
        return Result(PASS if not failed else FAIL, f"{len(failed)} failing")

    def official(self, rtl: str, official_tb: str) -> Result:
        """The reference verdict, from VerilogEval's own testbench."""
        if not rtl or not official_tb:
            return Result(MISSING_ARTIFACT, "no official testbench")
        key = _sha("OFFICIAL", rtl, official_tb)
        if key in self._cache:
            self.hits += 1
            return self._cache[key]
        self.calls += 1
        res = self._official_uncached(rtl, official_tb)
        self._cache[key] = res
        return res

    def _official_uncached(self, rtl: str, official_tb: str) -> Result:
        try:
            self._clean()
            (self.work / "dut.sv").write_text(rtl, encoding="utf-8")
            (self.work / "tb.sv").write_text(official_tb, encoding="utf-8")
            c = subprocess.run(["iverilog", "-g2012", "-o", "sim", "dut.sv", "tb.sv"],
                               cwd=self.work, capture_output=True, text=True,
                               timeout=self.timeout)
        except subprocess.TimeoutExpired:
            return Result(TIMEOUT, "official iverilog")
        except OSError as exc:
            return Result(SETUP_ERROR, str(exc)[:120])
        if c.returncode != 0:
            return Result(COMPILE_ERROR, "official tb")
        try:
            r = subprocess.run(["vvp", "sim"], cwd=self.work, capture_output=True,
                               text=True, timeout=self.timeout)
        except subprocess.TimeoutExpired:
            return Result(TIMEOUT, "official vvp")
        m = MISMATCH_RE.search(r.stdout)
        if not m:
            return Result(NO_OUTPUT, "no Mismatches line")
        return Result(PASS if int(m.group(1)) == 0 else FAIL,
                      f"{m.group(1)}/{m.group(2)}")


def published_eval2(task_id: str, num: int, den: int, eval1: bool,
                    failed_idxes: List[int]) -> bool:
    """Verbatim port of analyze.py:Eval2_pass, task exception included."""
    if not eval1 or den == 0:
        return False
    loose = (num / den) >= LOOSE_FACTOR
    if task_id == "m2014_q3":
        return sorted(failed_idxes) == [3, 4, 7, 8, 9, 10] or loose
    return loose


def load_arm(spec: str) -> Tuple[str, Path, dict]:
    name, path = spec.split("=", 1)
    run = Path(path)
    man = json.loads((run / "safe_manifest.json").read_text())
    return name, run / "suites", man


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--frontend-records", required=True, type=Path)
    ap.add_argument("--arm", action="append", required=True,
                    help="NAME=RUNDIR, repeatable; RUNDIR holds safe_manifest.json "
                         "and suites/")
    ap.add_argument("--golden", required=True, type=Path)
    ap.add_argument("--mutants", required=True, type=Path)
    ap.add_argument("--tasks", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    requested = json.loads(args.tasks.read_text())
    if args.limit:
        requested = requested[:args.limit]
    arms = [load_arm(s) for s in args.arm]
    arm_names = [a[0] for a in arms]
    print(f"arms: {', '.join(arm_names)}")

    rows_fe: Dict[str, dict] = {}
    for line in args.frontend_records.read_text(encoding="utf-8").splitlines():
        if line.strip():
            r = json.loads(line)
            rows_fe.setdefault(r["task_id"], r)
    golden, official, mutants = {}, {}, {}
    for line in args.golden.read_text(encoding="utf-8").splitlines():
        if line.strip():
            r = json.loads(line)
            golden[r["task_id"]] = r["module_code"]
            if r.get("testbench"):
                official[r["task_id"]] = r["testbench"]
    for line in args.mutants.read_text(encoding="utf-8").splitlines():
        if line.strip():
            r = json.loads(line)
            mutants[r["task_id"]] = (r.get("mutants") or [])[:10]

    per_task: List[dict] = []
    gold_tally: Dict[str, Counter] = {"literal": Counter(), "primary": Counter(),
                                      "official": Counter()}
    divergences: List[str] = []

    with tempfile.TemporaryDirectory(prefix="recon_") as td:
        run = Runner(Path(td))
        for i, tid in enumerate(requested, 1):
            fe = rows_fe.get(tid)
            row: dict = {"task_id": tid, "available": bool(fe), "complete": False,
                         "golden_literal": MISSING_ARTIFACT,
                         "golden_primary": MISSING_ARTIFACT,
                         "n_mutants": 0, "n_scored": 0,
                         "agree_literal": 0, "agree_primary": 0,
                         "eval1_literal": "", "eval2_literal": "",
                         "eval1_primary": "", "eval2_primary": "",
                         "eval1_published": "", "eval2_published": "",
                         "unscoreable": "", "note": ""}
            for nm in arm_names:
                row[f"has_c2_{nm}"] = False
                row[f"golden_shadow_{nm}"] = ""
                row[f"agree_{nm}"] = 0
                row[f"alarms_accepted_{nm}"] = 0
                row[f"eval1_{nm}"] = ""
                row[f"eval2_{nm}"] = ""
            if not fe or tid not in golden:
                row["note"] = "no frontend record" if not fe else "no golden"
                per_task.append(row)
                continue

            ck = fe.get("tb_py_checker") or ""
            lit_drv = fe.get("tb_v_driver") or ""
            pri_drv, shadows = "", {}
            for nm, suites, man in arms:
                c1 = man.get("channel1", {}).get(tid)
                if c1 and (suites / c1["file"]).is_file() and not pri_drv:
                    pri_drv = (suites / c1["file"]).read_text(encoding="utf-8")
                c2 = man.get("channel2", {}).get(tid)
                if c2 and (suites / c2["file"]).is_file():
                    shadows[nm] = (suites / c2["file"]).read_text(encoding="utf-8")
                    row[f"has_c2_{nm}"] = True

            g_lit = run.execute(golden[tid], lit_drv, ck)
            g_pri = run.execute(golden[tid], pri_drv, ck)
            row["golden_literal"], row["golden_primary"] = g_lit.outcome, g_pri.outcome
            gold_tally["literal"][g_lit.outcome] += 1
            gold_tally["primary"][g_pri.outcome] += 1
            if g_lit.outcome != g_pri.outcome:
                divergences.append(f"{tid}: literal={g_lit.outcome} "
                                   f"primary={g_pri.outcome}")
            g_sh = {nm: run.execute(golden[tid], drv, ck)
                    for nm, drv in shadows.items()}
            for nm, r in g_sh.items():
                row[f"golden_shadow_{nm}"] = r.outcome

            muts = mutants.get(tid, [])
            row["n_mutants"] = len(muts)
            fails: Dict[str, List[int]] = {k: [] for k in
                                           ["literal", "primary"] + arm_names}
            unscoreable: Counter = Counter()
            for mi, mrtl in enumerate(muts, start=1):
                ref = run.official(str(mrtl), official.get(tid, ""))
                gold_tally["official"][ref.outcome] += 1
                r_lit = run.execute(str(mrtl), lit_drv, ck)
                r_pri = run.execute(str(mrtl), pri_drv, ck)
                if ref.accepted is None or r_lit.accepted is None \
                        or r_pri.accepted is None:
                    unscoreable[f"ref={ref.outcome},lit={r_lit.outcome},"
                                f"pri={r_pri.outcome}"] += 1
                    continue
                row["n_scored"] += 1
                if ref.accepted == r_lit.accepted:
                    row["agree_literal"] += 1
                else:
                    fails["literal"].append(mi)
                if ref.accepted == r_pri.accepted:
                    row["agree_primary"] += 1
                else:
                    fails["primary"].append(mi)
                for nm in arm_names:
                    drv = shadows.get(nm)
                    alarm = False
                    if drv:
                        rs = run.execute(str(mrtl), drv, ck)
                        alarm = (rs.outcome == FAIL)
                    comb = r_pri.accepted and not alarm
                    if alarm and ref.accepted:
                        row[f"alarms_accepted_{nm}"] += 1
                    if ref.accepted == comb:
                        row[f"agree_{nm}"] += 1
                    else:
                        fails[nm].append(mi)

            row["unscoreable"] = "; ".join(f"{k} x{v}"
                                           for k, v in unscoreable.most_common())
            n = row["n_scored"]
            e1 = {"literal": g_lit.outcome == PASS, "primary": g_pri.outcome == PASS}
            for nm in arm_names:
                # A shadow alarm on GOLDEN is a false alarm by definition and
                # costs the combined arm its Eval1. That is the strictest honest
                # reading, and it is the one reported.
                e1[nm] = e1["primary"] and not (nm in g_sh and g_sh[nm].outcome == FAIL)
            for k in ["literal", "primary"] + arm_names:
                row[f"eval1_{k}"] = e1[k]
                if n:
                    agree = row["agree_literal"] if k == "literal" else \
                        (row["agree_primary"] if k == "primary" else row[f"agree_{k}"])
                    row[f"eval2_{k}"] = published_eval2(tid, agree, n, e1[k], fails[k])
            if n:
                row["complete"] = (g_lit.outcome in DEFINITE
                                   and g_pri.outcome in DEFINITE)

            row["eval1_published"] = bool(fe.get("Eval1_pass"))
            ratio = fe.get("Eval2_ratio") or ""
            pnum = pden = 0
            if isinstance(ratio, str) and "/" in ratio:
                a, b = ratio.split("/")
                pnum, pden = int(a), int(b)
            row["eval2_published"] = published_eval2(
                tid, pnum, pden, row["eval1_published"],
                fe.get("Eval2_failed_mutant_idxes") or [])
            per_task.append(row)
            if i % 10 == 0:
                print(f"  {i}/{len(requested)}  sims={run.calls} "
                      f"cached={run.hits}", flush=True)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(per_task[0].keys()))
        w.writeheader()
        w.writerows(per_task)
    print(f"\nwrote {args.out} ({len(per_task)} rows)")

    scopes = {
        "requested": per_task,
        "available": [r for r in per_task if r["available"]],
        "complete":  [r for r in per_task if r["complete"]],
    }
    cols = ["published", "literal", "primary"] + arm_names
    print("\n=== Eval1 / Eval2 by arm and scope (no row is filtered out) ===")
    print(f"{'scope':10s} {'N':>4s}  " + "  ".join(f"{c:>17s}" for c in cols))
    summary_tbl: Dict[str, Dict[str, List[float]]] = {}
    for name, rs in scopes.items():
        n = len(rs) or 1
        cells, rec = [], {}
        for c in cols:
            e1 = sum(1 for r in rs if r.get(f"eval1_{c}") is True)
            e2 = sum(1 for r in rs if r.get(f"eval2_{c}") is True)
            cells.append(f"{e1 / n:7.4f}/{e2 / n:7.4f}")
            rec[c] = [round(e1 / n, 4), round(e2 / n, 4)]
        summary_tbl[name] = rec
        print(f"{name:10s} {len(rs):4d}  " + "  ".join(f"{x:>17s}" for x in cells))
    print("  each cell is Eval1/Eval2; the denominator is the scope size, so a "
          "row we could not score\n  counts as a failure rather than vanishing.")

    print("\n=== Outcome taxonomy on Golden ===")
    print(f"{'outcome':16s}" + "".join(f"{a:>12s}" for a in
                                       ("literal", "primary", "official")))
    for o in OUTCOMES:
        if any(gold_tally[a][o] for a in gold_tally):
            print(f"{o:16s}" + "".join(f"{gold_tally[a][o]:12d}" for a in
                                       ("literal", "primary", "official")))

    print(f"\nliteral-vs-primary divergences: {len(divergences)}")
    for d in divergences[:20]:
        print("   " + d)
    print("\n=== Channel 2 warning cost, per arm ===")
    print(f"{'arm':14s} {'tasks w/ C2':>12s} {'false alarm on Golden':>22s} "
          f"{'alarms on accepted mutants':>28s}")
    alarm_rec = {}
    for nm in arm_names:
        have = sum(1 for r in per_task if r.get(f"has_c2_{nm}"))
        ga = sum(1 for r in per_task if r.get(f"golden_shadow_{nm}") == FAIL)
        ma = sum(r.get(f"alarms_accepted_{nm}", 0) for r in per_task)
        alarm_rec[nm] = {"tasks_with_c2": have, "golden_false_alarms": ga,
                         "alarms_on_accepted_mutants": ma}
        print(f"{nm:14s} {have:12d} {ga:22d} {ma:28d}")

    args.out.with_suffix(".summary.json").write_text(json.dumps(
        {"scopes": {k: len(v) for k, v in scopes.items()},
         "table": summary_tbl, "alarms": alarm_rec,
         "divergences": divergences}, indent=1, sort_keys=True), encoding="utf-8")


if __name__ == "__main__":
    main()
