#!/usr/bin/env python3
"""Sequential-only characterisation of the benchmark gap.

Uses the published AutoBench and CorrectBench run records plus the HDLBits task
definitions. Task families are assigned from the specification text and
interface, never from ACTIVE-TB results, so the taxonomy cannot be tuned to
favour this work.
"""
from __future__ import annotations

import argparse
import collections
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "baselines" / "ConfiBench" / "data"


def load_jsonl(path: Path):
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def frac(text):
    if isinstance(text, str) and "/" in text:
        a, b = text.split("/")
        b = float(b)
        return (float(a), b) if b else None
    return None


# Family rules are ordered; the first match wins. Keyed on specification text
# and interface only.
FAMILY_RULES = [
    ("lfsr_shift", r"\blfsr\b|linear feedback|shift register|\bshift\b|rotat"),
    ("fsm", r"\bfsm\b|state machine|moore|mealy|state diagram|next state|\bstates?\b.*transition"),
    ("counter", r"\bcount(er|ing|s)?\b|decade|modulo|\btally\b|wrap"),
    ("dff_register", r"\bflip-?flop\b|\bd ff\b|\bdff\b|\bregister\b|\blatch\b"),
    ("stateful_controller", r"\bprotocol\b|\bhandshak|\bpacket\b|\bserial\b|\bps/?2\b|\bhdlc\b|"
                            r"\btimer\b|\bcontroller\b|arbiter|\bfifo\b|\bmemory\b|\bcache\b"),
]


def classify(task) -> str:
    blob = f"{task.get('description','')}\n{task.get('header','')}".lower()
    for name, pattern in FAMILY_RULES:
        if re.search(pattern, blob):
            return name
    return "other_sequential"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json-out", type=Path)
    args = ap.parse_args()

    ab = load_jsonl(DATA / "AutoBenchResults" / "run_info_and_codes.jsonl")
    cb = load_jsonl(DATA / "CorrectBenchResults" / "run_info.jsonl")
    tasks = {t["task_id"]: t for t in load_jsonl(DATA / "HDLBits" / "HDLBits_data.jsonl")}

    ctype = {}
    for r in cb + ab:
        ctype.setdefault(r["task_id"], r.get("circuit_type"))
    seq = sorted(t for t, c in ctype.items() if c == "SEQ")
    print(f"sequential tasks: {len(seq)} of {len(ctype)}\n")

    def agg(rows):
        by = collections.defaultdict(list)
        for r in rows:
            by[r["task_id"]].append(r)
        out = {}
        for t, rs in by.items():
            n = len(rs)
            e1 = sum(1 for r in rs if r.get("Eval1_pass"))
            e2 = sum(1 for r in rs if r.get("Eval2_pass"))
            pairs = [frac(r.get("Eval2_ratio")) for r in rs]
            kn = sum(p[0] for p in pairs if p)
            kd = sum(p[1] for p in pairs if p)
            out[t] = {"runs": n, "eval1": e1 / n, "eval2": e2 / n,
                      "kill": kn / kd if kd else None}
        return out

    A, C = agg(ab), agg(cb)

    fam = {t: classify(tasks[t]) for t in seq if t in tasks}
    for t in seq:
        fam.setdefault(t, "other_sequential")

    print("=== Per-task sequential results ===")
    print(f"{'task':22s} {'family':22s} {'AB E1':>6s} {'AB E2':>6s} {'CB E1':>6s} {'CB E2':>6s}")
    never = []
    for t in seq:
        a, c = A.get(t, {}), C.get(t, {})
        if a.get("eval2", 0) == 0 and c.get("eval2", 0) == 0:
            never.append(t)
        print(f"{t:22s} {fam[t]:22s} {a.get('eval1',0):6.2f} {a.get('eval2',0):6.2f} "
              f"{c.get('eval1',0):6.2f} {c.get('eval2',0):6.2f}")

    print("\n=== By sequential family ===")
    print(f"{'family':22s} {'n':>3s} {'AB E1':>6s} {'AB E2':>6s} {'CB E1':>6s} {'CB E2':>6s} {'never':>6s}")
    rows_out = {}
    for f in sorted(set(fam.values())):
        ts = [t for t in seq if fam[t] == f]
        n = len(ts)
        def m(src, k):
            vals = [src.get(t, {}).get(k, 0) or 0 for t in ts]
            return sum(vals) / len(vals) if vals else 0.0
        nv = sum(1 for t in ts if t in never)
        rows_out[f] = {"n": n, "ab_eval1": m(A, "eval1"), "ab_eval2": m(A, "eval2"),
                       "cb_eval1": m(C, "eval1"), "cb_eval2": m(C, "eval2"),
                       "never_solved": nv, "tasks": ts}
        print(f"{f:22s} {n:3d} {m(A,'eval1'):6.3f} {m(A,'eval2'):6.3f} "
              f"{m(C,'eval1'):6.3f} {m(C,'eval2'):6.3f} {nv:6d}")

    print(f"\nsequential tasks never solved by either baseline: {len(never)} of {len(seq)}")
    print("  by family:", dict(collections.Counter(fam[t] for t in never)))

    # Applicability of the state-directed / BMC machinery, judged from the
    # interface and specification only.
    print("\n=== Applicability of state-directed + BMC machinery ===")
    applic = {}
    for t in seq:
        task = tasks.get(t, {})
        hdr = task.get("header", "")
        outs = re.findall(r"output\s+(?:reg\s+|wire\s+)?(?:\[(\d+):(\d+)\]\s*)?(\w+)", hdr)
        width = 0
        for hi, lo, _ in outs:
            width += (int(hi) - int(lo) + 1) if hi else 1
        has_clk = bool(re.search(r"\bclk\b|\bclock\b", hdr, re.I))
        has_rst = bool(re.search(r"\breset\b|\brst\b", hdr, re.I))
        # BMC is tractable when the observable output space is small enough to
        # enumerate distinguishing objectives at modest bounds.
        applic[t] = {"out_bits": width, "has_clk": has_clk, "has_reset": has_rst,
                     "bmc_tractable": width <= 16 and has_clk}
    tract = [t for t in seq if applic[t]["bmc_tractable"]]
    print(f"  has clock: {sum(1 for t in seq if applic[t]['has_clk'])}/{len(seq)}")
    print(f"  has reset port: {sum(1 for t in seq if applic[t]['has_reset'])}/{len(seq)}")
    print(f"  output width <= 16 bits and clocked (BMC tractable): {len(tract)}/{len(seq)}")
    wide = [t for t in seq if not applic[t]["bmc_tractable"]]
    print(f"  excluded as wide/unclocked: {sorted(wide)}")

    if args.json_out:
        args.json_out.write_text(json.dumps({
            "sequential_tasks": seq, "family": fam, "never_solved": never,
            "by_family": {k: {kk: vv for kk, vv in v.items()} for k, v in rows_out.items()},
            "applicability": applic,
            "autobench": {t: A.get(t) for t in seq},
            "correctbench": {t: C.get(t) for t in seq},
        }, indent=2), encoding="utf-8")
        print(f"\nwrote {args.json_out}")


if __name__ == "__main__":
    main()
