#!/usr/bin/env python3
"""Offline prototype of a testbench-correction arbitrator.

The question this answers is whether an arbitrator can tell that a testbench's
*expectation* is wrong, using only evidence available before golden RTL is seen.

Signal used: the five synthesis methods derive expectations independently from
the same oracle candidate pool, and they frequently disagree. Where they
disagree, a vote across methods is a candidate correction. This stands in for
the CorrectBench-style step of arbitrating whether the testbench or the design
under test is at fault, and it is measurable entirely from artefacts already on
disk.

Alignment: two methods' check points are comparable only when they apply the
same stimulus. Scenario *names* differ across methods, so points are keyed by
(reset_first, drive prefix up to the observed cycle, output port) taken from
each method's own suite.json.

Ground truth: the eval1 diagnostic recorded, for every testbench that failed
Eval1 against golden RTL, the first failing check with the value golden actually
produced. Those are known-wrong expectations. Every assertion inside a testbench
that *passed* Eval1 is by construction a known-correct expectation, which is what
makes the false-correction rate measurable.
"""
from __future__ import annotations

import argparse
import collections
import csv
import json
import re
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FAIL_RE = re.compile(r'FAIL\|([^|]*)\|(\d+)\|([^|]*)\|expected=(\w+)')

METHODS = [
    "single_oracle", "homogeneous_ensemble", "diverse_ensemble",
    "diverse_active", "typed_formal_active",
]
# Methods whose candidate pool spans more than one model family.
FAMILY_DIVERSE = ["diverse_ensemble", "diverse_active", "typed_formal_active"]


def load_frozen(zip_path: Path, seed: str):
    """Return {(method, task): {"asserts": [...], "suite": {scenario: scenario}}}."""
    out = {}
    with zipfile.ZipFile(zip_path) as z:
        names = z.namelist()
        tb_names = [n for n in names if n.startswith(f"{seed}/frozen/") and n.endswith("testbench.sv")]
        for tb_name in tb_names:
            parts = tb_name.split("/")
            method, task = parts[2], parts[3]
            if method not in METHODS:
                continue
            text = z.read(tb_name).decode("utf-8", "replace")
            if not text.strip():
                continue
            suite_name = tb_name.rsplit("/", 1)[0] + "/suite.json"
            try:
                suite = json.loads(z.read(suite_name).decode())
            except KeyError:
                continue
            by_name = {s["name"]: s for s in suite}
            asserts = []
            for scen, idx, port, expected in FAIL_RE.findall(text):
                asserts.append({
                    "scenario": scen, "index": int(idx),
                    "port": port.strip(), "expected": expected.lower(),
                })
            out[(method, task)] = {"asserts": asserts, "suite": by_name}
    return out


def point_key(scenario_obj, index: int, port: str):
    """Canonical identity of a check point: the stimulus that produced it."""
    if scenario_obj is None:
        return None
    cycles = scenario_obj.get("cycles", [])
    if index >= len(cycles):
        return None
    prefix = json.dumps([c.get("drive", {}) for c in cycles[: index + 1]], sort_keys=True)
    return (bool(scenario_obj.get("reset_first", True)), prefix, port, index)


def build_index(frozen):
    """Map (task, point_key) -> {method: expected}."""
    index = collections.defaultdict(dict)
    located = collections.defaultdict(dict)
    for (method, task), data in frozen.items():
        for a in data["asserts"]:
            scen = data["suite"].get(a["scenario"])
            key = point_key(scen, a["index"], a["port"])
            if key is None:
                continue
            index[(task, key)][method] = a["expected"]
            located[(method, task)][key] = a["expected"]
    return index, located


def vote(values, restrict=None):
    """Majority expectation over methods, ignoring the method being judged."""
    items = [(m, v) for m, v in values.items() if restrict is None or m in restrict]
    if not items:
        return None, 0, 0
    counts = collections.Counter(v for _, v in items)
    top = counts.most_common()
    if len(top) > 1 and top[1][1] == top[0][1]:
        return None, top[0][1], len(items)      # tie: arbitrator abstains
    return top[0][0], top[0][1], len(items)


def normalise(bits: str, width_hint: str) -> str:
    """Compare values of differing printed width by zero-extending the shorter."""
    a, b = bits.lower(), width_hint.lower()
    n = max(len(a), len(b))
    return a.zfill(n), b.zfill(n)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--frozen", type=Path,
                    default=ROOT / "kaggle_runs/spec_only_full_synthesis_v1_complete/active_tb_s_frozen_full_v1.zip")
    ap.add_argument("--diagnostic", type=Path,
                    default=ROOT / "kaggle_runs/eval1_diagnostic_v1/eval1_diagnostic/eval1_diagnostic.csv")
    ap.add_argument("--seed", default="seed_017")
    args = ap.parse_args()

    frozen = load_frozen(args.frozen, args.seed)
    index, located = build_index(frozen)
    print(f"frozen testbenches parsed: {len(frozen)}")
    print(f"distinct (task, check point) identities: {len(index)}")
    multi = sum(1 for v in index.values() if len(v) >= 2)
    print(f"  of which asserted by >=2 methods (arbitration possible): {multi}")
    disagree = sum(1 for v in index.values() if len(set(v.values())) > 1)
    print(f"  of which methods disagree: {disagree}\n")

    diag = list(csv.DictReader(args.diagnostic.open(encoding="utf-8")))
    diag = [d for d in diag if d["method"] in METHODS]
    failing = {(d["method"], d["task_id"]): d for d in diag if d["status"] == "FAIL"}
    passing = {(d["method"], d["task_id"]) for d in diag if d["status"] == "PASS"}
    print(f"diagnostic rows: {len(diag)}  failing: {len(failing)}  passing: {len(passing)}\n")

    # ---------- Q1: can the arbitrator identify the known-wrong expectation? ----------
    for label, restrict in (("all methods", None), ("family-diverse methods only", FAMILY_DIVERSE)):
        stats = collections.Counter()
        for (method, task), d in failing.items():
            if d["first_fail_index"] == "" or not d["first_expected"]:
                stats["no_recorded_point"] += 1
                continue
            data = frozen.get((method, task))
            if not data:
                stats["testbench_missing"] += 1
                continue
            scen = data["suite"].get(d["first_fail_scenario"])
            # recover the port from the assertion matching scenario/index/expected
            port = None
            for a in data["asserts"]:
                if (a["scenario"] == d["first_fail_scenario"]
                        and a["index"] == int(d["first_fail_index"])
                        and a["expected"] == d["first_expected"].lower()):
                    port = a["port"]
                    break
            key = point_key(scen, int(d["first_fail_index"]), port) if port else None
            if key is None:
                stats["point_unresolvable"] += 1
                continue
            others = {m: v for m, v in index[(task, key)].items() if m != method}
            if not others:
                stats["no_other_method_asserts_here"] += 1
                continue
            winner, votes, n = vote(others, restrict)
            if winner is None:
                stats["arbitrator_abstains"] += 1
                continue
            truth = d["first_got"].lower()
            w, t = normalise(winner, truth)
            own = d["first_expected"].lower()
            if w == t:
                stats["CORRECTED_to_truth"] += 1
            elif winner == own:
                stats["vote_agrees_with_wrong_expectation"] += 1
            else:
                stats["changed_but_still_wrong"] += 1
        total = sum(stats.values())
        print(f"=== Q1: known-wrong expectations, arbitrator = majority over {label} ===")
        for k, v in stats.most_common():
            print(f"   {k:36s} {v:5d}  ({v/total:6.1%})")
        fixed = stats["CORRECTED_to_truth"]
        print(f"   -> repaired {fixed}/{total} = {fixed/total:.1%} of known-wrong expectations\n")

    # ---------- Q2: how often would it damage a correct expectation? ----------
    for label, restrict in (("all methods", None), ("family-diverse methods only", FAMILY_DIVERSE)):
        checked = changed = 0
        damaged_tbs = set()
        for (method, task) in passing:
            for key, own in located.get((method, task), {}).items():
                others = {m: v for m, v in index[(task, key)].items() if m != method}
                if not others:
                    continue
                checked += 1
                winner, _, _ = vote(others, restrict)
                if winner is None:
                    continue
                w, o = normalise(winner, own)
                if w != o:
                    changed += 1
                    damaged_tbs.add((method, task))
        print(f"=== Q2: known-correct expectations, arbitrator = majority over {label} ===")
        print(f"   assertions inside Eval1-passing testbenches examined: {checked}")
        print(f"   assertions the arbitrator would have altered (all harmful): {changed}"
              f"  ({changed/checked:.2%})" if checked else "   none comparable")
        print(f"   passing testbenches it would have broken: {len(damaged_tbs)} of {len(passing)}"
              f"  ({len(damaged_tbs)/len(passing):.1%})\n" if passing else "\n")

    # ---------- Q4: projected Eval1 ----------
    print("=== Q4: projected Eval1 if corrections were applied ===")
    per_method = collections.defaultdict(lambda: {"n": 0, "pass": 0, "first_fixable": 0, "single_fail": 0})
    for d in diag:
        m = d["method"]
        per_method[m]["n"] += 1
        if d["status"] == "PASS":
            per_method[m]["pass"] += 1
    for (method, task), d in failing.items():
        try:
            nfail = int(d["n_fail_lines"] or 0)
        except ValueError:
            nfail = 0
        if nfail == 1:
            per_method[method]["single_fail"] += 1
    # A failing testbench flips to PASS only if every failing check is repaired.
    # The diagnostic records only the first, so this is sound exactly for the
    # testbenches whose single failing check is the one recorded.
    gained = collections.Counter()
    optimistic = collections.Counter()
    for (method, task), d in failing.items():
        try:
            nfail = int(d["n_fail_lines"] or 0)
        except ValueError:
            continue
        if not d["first_expected"]:
            continue
        single = (nfail == 1)
        data = frozen.get((method, task))
        if not data:
            continue
        port = None
        for a in data["asserts"]:
            if (a["scenario"] == d["first_fail_scenario"]
                    and a["index"] == int(d["first_fail_index"])
                    and a["expected"] == d["first_expected"].lower()):
                port = a["port"]
                break
        scen = data["suite"].get(d["first_fail_scenario"])
        key = point_key(scen, int(d["first_fail_index"]), port) if port else None
        if key is None:
            continue
        others = {m: v for m, v in index[(task, key)].items() if m != method}
        winner, _, _ = vote(others)
        if winner is None:
            continue
        w, t = normalise(winner, d["first_got"].lower())
        if w == t:
            optimistic[method] += 1          # first bad check repaired
            if single:
                gained[method] += 1          # and it was the only bad check

    lost = collections.Counter()
    for (method, task) in passing:
        for key, own in located.get((method, task), {}).items():
            others = {m: v for m, v in index[(task, key)].items() if m != method}
            if not others:
                continue
            winner, _, _ = vote(others)
            if winner is None:
                continue
            w, o = normalise(winner, own)
            if w != o:
                lost[method] += 1
                break

    print(f"{'method':24s} {'n':>4s} {'Eval1 now':>10s} {'-broken':>8s} "
          f"{'Eval1 low':>10s} {'Eval1 high':>11s}")
    for m in METHODS:
        st = per_method[m]
        if not st["n"]:
            continue
        low = (st["pass"] + gained[m] - lost[m]) / st["n"]
        high = (st["pass"] + optimistic[m] - lost[m]) / st["n"]
        print(f"{m:24s} {st['n']:4d} {st['pass']/st['n']:10.4f} {lost[m]:8d} "
              f"{low:10.4f} {high:11.4f}")
    print()
    print("  Eval1 low  assumes only single-failure testbenches can flip. The")
    print("             diagnostic recorded just the first failing check, so a")
    print("             testbench with many failures cannot be shown to flip.")
    print("  Eval1 high assumes repairing the first bad check repairs the whole")
    print("             testbench, which is optimistic and almost certainly")
    print("             unreachable.")
    print("  -broken    is exact: every altered assertion inside an Eval1-passing")
    print("             testbench is a regression by construction.")


if __name__ == "__main__":
    main()
