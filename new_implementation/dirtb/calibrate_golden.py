#!/usr/bin/env python3
"""Two checks that have to pass before any pipeline number is trusted. DEV tasks only.

GATE: our official verdicts (local Icarus) reproduce the official verdicts that
ConfiBench's own logs recorded for the same mutants. If they do not, our Eval2 is
not on ConfiBench's scale.

CALIBRATION: use GOLDEN itself as the reference. Eval1 is then 1 by construction,
and Eval2 measures the stimulus alone -- how often our driver reaches the same
verdict as the official testbench when the expected values are perfect. This is
the ceiling the stimulus imposes on the whole pipeline, and tells whether stimulus
is a bottleneck in its own right. Golden is used ONLY here, for calibration, on
dev tasks; the pipeline itself never sees it.
"""
from __future__ import annotations

import json
import re
import zlib
import sys
import zipfile
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dirtb.bench import ZIP, load                                  # noqa: E402
from dirtb.evaluate import evaluate, official, save_cache          # noqa: E402
from dirtb.hdl import build_driver, parse_header, simulate         # noqa: E402

MM = re.compile(r"Mismatches:\s*(\d+)\s+in\s+(\d+)\s+samples")


def gate(tasks) -> None:
    z = zipfile.ZipFile(ZIP)
    run = "saves_inEDA/TODAES/ConfiBench_4o/NO1_20250305_104636/"
    want = {t["task_id"]: t for t in tasks}
    recorded = {}
    for n in z.namelist():
        if not n.startswith(run):
            continue
        m = re.match(r"([^/]+)/\d+_\d+_TBeval/eval2_GoldenTB_and_mutants/mutant_(\d+)/GoldenTB/run_info\.txt$", n[len(run):])
        if m and m.group(1) in want:
            mm = MM.search(z.read(n).decode("utf-8", "replace"))
            if mm:
                recorded[(m.group(1), int(m.group(2)))] = int(mm.group(1)) == 0
    jobs = list(recorded)
    with ThreadPoolExecutor(max_workers=8) as ex:
        ours = list(ex.map(lambda k: official(want[k[0]], k[1]), jobs))
    agree = sum(1 for k, o in zip(jobs, ours) if o == recorded[k])
    save_cache()
    print(f"GATE  local official verdict == ConfiBench's recorded verdict: {agree}/{len(jobs)} "
          f"= {agree/max(1,len(jobs)):.1%}")
    for k, o in zip(jobs, ours):
        if o != recorded[k]:
            print(f"      differs: {k[0]} mutant {k[1]}: ours {o}, recorded {recorded[k]}")


def calibrate(tasks, marathons: bool = False, tag: str = "dev") -> None:
    res = []
    for t in tasks:
        iface = parse_header(t["header"])
        driver = build_driver(iface, seed=zlib.crc32(t["task_id"].encode()), marathons=marathons)
        expected = simulate(t["eval_golden"], driver, timeout=300)
        if expected.status != "RAN":
            print(f"   {t['task_id']}: golden did not run under our driver ({expected.status}) {expected.detail[:120]}")
            continue
        res.append(evaluate(t, driver, expected))
    save_cache()
    for ct in ("CMB", "SEQ", None):
        rs = [r for r in res if ct is None or r["circuit_type"] == ct]
        if not rs:
            continue
        n = len(rs)
        print(f"   {ct or 'ALL':4s} n={n:3d}  Eval1 {sum(r['eval1'] for r in rs)/n:.3f}  "
              f"Eval2 {sum(r['eval2'] for r in rs)/n:.3f}  "
              f"missed {sum(r['missed'] for r in rs)}  false-rejects {sum(r['false_reject'] for r in rs)}")
    bad = [r for r in res if not r["eval2"]]
    print("   tasks failing Eval2 with a PERFECT reference:",
          ", ".join(f"{r['task_id']}(m{r['missed']}/fr{r['false_reject']})" for r in bad))
    Path(__file__).with_name(f"calibration_golden_{tag}.json").write_text(json.dumps(res, indent=1), encoding="utf-8")


if __name__ == "__main__":
    dev = load("dev")
    if "--marathons" in sys.argv:
        print("CALIBRATION  golden as reference, stimulus WITH long runs, dev tasks:", flush=True)
        calibrate(dev, marathons=True, tag="dev_marathons")
    else:
        gate(dev)
        print("\nCALIBRATION  golden as reference, our stimulus, dev tasks:")
        calibrate(dev)
