#!/usr/bin/env python3
"""Dev-only comparison of reference policies: plurality vs disagreement-scoped abstention.

The oracle diagnostic showed that with 5 candidates the binding constraint is candidate
correctness, not selection: many units have no correct candidate. A reference that is
wrong where the pool disagrees fails Eval1. Abstention marks an output bit don't-care
(x) exactly where the candidate pool does not agree strongly enough, and keeps every
sufficiently agreed observation as a check.

Policies (tau = required fraction of simulated candidates agreeing on a bit):
  plurality        largest class per unit (current pipeline)
  classX@tau       plurality class per unit; bits where fewer than tau of candidates
                   agree with that class become x
  vote@tau         per bit, the most common value across candidates; x below tau
  tail@1.0         plurality class; from the first row in a unit where any output bit
                   disagrees, every output bit to the end of the unit becomes x

Each policy's expected trace is scored exactly as dirtb/evaluate.py does (golden and
mutants simulated once per task and reused across policies). Golden is read, so this
is dev-only.
"""
from __future__ import annotations

import argparse
import json
import sys
import zlib
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dirtb.bench import load                                                # noqa: E402
from dirtb.evaluate import eval2_pass, official, save_cache                 # noqa: E402
from dirtb.hdl import Trace, build_driver, matches, parse_header, simulate  # noqa: E402
from dirtb.resolve import group, reference_trace, resolve, simulate_candidates  # noqa: E402
from dirtb.run_pipeline import confibench_per_task                          # noqa: E402

TAUS = (0.6, 0.8, 1.0)


def bit_stats(values):
    """values: candidate strings for one signal. -> per bit Counter."""
    return [Counter(v[i] for v in values) for i in range(len(values[0]))]


def abstain_trace(units, good, n_in, template, base_rows, mode, tau):
    """base_rows: plurality reference values per row (tuple of strings)."""
    cids = list(good)
    n = len(cids)
    rows, total, xed = [], 0, 0
    tail_from = {}
    if mode == "tail":
        for u in units:
            for i in u.row_idx:
                vals = {good[c].rows[i][2][n_in:] for c in cids}
                if len(vals) > 1:
                    tail_from[u.key] = i
                    break
    unit_of = {i: u.key for u in units for i in u.row_idx}
    for i, (s, st, _) in enumerate(template.rows):
        base = base_rows[i]
        outs = list(base[n_in:])
        if mode == "tail":
            t0 = tail_from.get(unit_of[i])
            if t0 is not None and i >= t0:
                total += sum(len(o) for o in outs)
                xed += sum(len(o) for o in outs)
                outs = ["x" * len(o) for o in outs]
            else:
                total += sum(len(o) for o in outs)
        else:
            for k in range(len(outs)):
                cand_vals = [good[c].rows[i][2][n_in + k] for c in cids]
                total += len(outs[k])
                if all(v == cand_vals[0] for v in cand_vals):
                    if mode == "vote":
                        outs[k] = cand_vals[0]
                    continue
                if any(len(v) != len(outs[k]) for v in cand_vals):
                    xed += len(outs[k])
                    outs[k] = "x" * len(outs[k])
                    continue
                stats = bit_stats(cand_vals)
                new = []
                for b, cnt in enumerate(stats):
                    if mode == "classX":
                        v = outs[k][b]
                        ok = cnt[v] / n >= tau
                    else:
                        v, c = cnt.most_common(1)[0]
                        ok = c / n >= tau
                    if ok and v not in "xXzZ":
                        new.append(v)
                    else:
                        new.append("x")
                        xed += 1
                outs[k] = "".join(new)
        rows.append((s, st, tuple(base[:n_in]) + tuple(outs)))
    return Trace("RAN", rows), (xed / total if total else 0.0)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--candidates", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    cands = defaultdict(list)
    for l in args.candidates.read_text(encoding="utf-8").splitlines():
        if l.strip():
            r = json.loads(l)
            if r.get("rtl"):
                cands[r["task_id"]].append(r)
    tasks = [t for t in load("dev") if t["task_id"] in cands]
    cb = confibench_per_task()
    policies = ["plurality"] + [f"{m}@{tau}" for m in ("classX", "vote") for tau in TAUS] + ["tail@1.0"]
    results = []
    for t in tasks:
        tid = t["task_id"]
        iface = parse_header(t["header"])
        clk = iface.clock
        n_in = len([p for p in iface.inputs if p.name != clk])
        driver = build_driver(iface, seed=zlib.crc32(tid.encode()), marathons=True)
        traces = simulate_candidates(driver, cands[tid])
        units, n_rows = group(iface, traces)
        rec = {"task_id": tid, "circuit_type": t["circuit_type"], "n_ran": len(traces),
               "confibench_eval1": cb.get(tid, (0, 0))[0], "confibench_eval2": cb.get(tid, (0, 0))[1],
               "policies": {}}
        if not units:
            for p in policies:
                rec["policies"][p] = {"eval1": False, "eval2": False, "x_frac": 1.0, "note": "no candidate ran"}
            results.append(rec)
            print(f"  {tid:22s} no candidate ran", flush=True)
            continue
        good = {k: tr for k, tr in traces.items() if len(tr.rows) == n_rows}
        template = next(iter(good.values()))
        chosen, _ = resolve(t, units, None)
        base = reference_trace(units, chosen, template)
        base_rows = [r[2] for r in base.rows]
        gold = simulate(t["eval_golden"], driver, timeout=300)
        muts = t["eval_mutants"]
        with ThreadPoolExecutor(max_workers=6) as ex:
            mtr = list(ex.map(lambda m: simulate(m, driver, timeout=120), muts))
        offs = [official(t, i) for i in range(1, len(muts) + 1)]
        line = []
        for p in policies:
            if p == "plurality":
                exp, xf = base, 0.0
            else:
                mode, tau = p.split("@")
                exp, xf = abstain_trace(units, good, n_in, template, base_rows, mode, float(tau))
            e1 = matches(exp, gold)
            ours = [matches(exp, m) for m in mtr]
            failed = [i + 1 for i in range(len(muts)) if ours[i] != offs[i]]
            e2 = eval2_pass(tid, e1, len(muts), failed)
            rec["policies"][p] = {"eval1": e1, "eval2": e2, "x_frac": round(xf, 4), "failed_mutants": failed,
                                  "missed": sum(1 for i in range(len(muts)) if ours[i] and not offs[i]),
                                  "false_reject": sum(1 for i in range(len(muts)) if not ours[i] and offs[i])}
            line.append(f"{p}:{int(e1)}{int(e2)}")
        results.append(rec)
        print(f"  {tid:22s} {t['circuit_type']} ran {len(traces)}  " + " ".join(line), flush=True)
    save_cache()
    args.out.write_text(json.dumps(results, indent=1), encoding="utf-8")

    print()
    for ct in ("CMB", "SEQ", None):
        rs = [r for r in results if ct is None or r["circuit_type"] == ct]
        n = len(rs)
        if not n:
            continue
        print(f"== {ct or 'ALL'} n={n}   ConfiBench-4o Eval1 {sum(r['confibench_eval1'] for r in rs)/n:.3f} "
              f"Eval2 {sum(r['confibench_eval2'] for r in rs)/n:.3f}")
        for p in policies:
            ps = [r["policies"][p] for r in rs]
            print(f"   {p:12s} Eval1 {sum(x['eval1'] for x in ps)/n:.3f}  Eval2 {sum(x['eval2'] for x in ps)/n:.3f}  "
                  f"mean x-fraction {sum(x['x_frac'] for x in ps)/n:.3f}  "
                  f"missed {sum(x.get('missed', 0) for x in ps)}  false-reject {sum(x.get('false_reject', 0) for x in ps)}")


if __name__ == "__main__":
    main()
