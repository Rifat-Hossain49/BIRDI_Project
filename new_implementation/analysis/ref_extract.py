#!/usr/bin/env python3
"""Reference-accuracy pilot, input builder (DEVELOPMENT set: ConfiBench-4o only).

The repair pipeline replaces ConfiBench's expected values with a two-family
consensus. That is only safe if the consensus is right. This builds the inputs to
measure exactly that, on ConfiBench's own stimulus, for every task where both
judge families already have designs. No new generation is needed.

ConfiBench-4o-mini is deliberately NOT extracted: it stays untouched as the
held-out confirmation set.
"""
from __future__ import annotations

import json
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ZIP = ROOT / "baselines/confibench_drive/TODAES_opensource_result.zip"
BASE = "saves_inEDA/TODAES/ConfiBench_4o/"
J1 = ROOT / "kaggle_runs/xjudge_j1b_s2/j1_candidates.jsonl"
J0 = ROOT / "analysis/j0_candidates.jsonl"
GOLDEN = ROOT / "kaggle_upload_safe_cbx/dataset/active_tb_safe_cbx/golden.jsonl"
OUT_TB = ROOT / "analysis/ref_subtbs.jsonl"
OUT_DUT = ROOT / "analysis/ref_duts.jsonl"


def load_jsonl(p: Path):
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]


def main() -> None:
    j1 = load_jsonl(J1)
    j0 = load_jsonl(J0)
    fam_a = {r["task_id"] for r in j1}
    fam_b = {r["task_id"] for r in j0}
    tasks = sorted(fam_a & fam_b)
    golden = {r["task_id"]: r["module_code"] for r in load_jsonl(GOLDEN)}

    z = zipfile.ZipFile(ZIP)
    n_sub = 0
    ctypes = {}
    with OUT_TB.open("w", encoding="utf-8", newline="\n") as fh:
        for n in z.namelist():
            if not (n.startswith(BASE) and n.endswith("/data.json")):
                continue
            rel = n[len(BASE):].split("/")
            if len(rel) != 3 or rel[1] not in tasks:
                continue
            run, task = rel[0], rel[1]
            d = json.loads(z.read(n).decode("utf-8", "replace"))
            ctypes[task] = d.get("circuit_type", "?")
            for mb in d.get("multibench_info") or []:
                if not isinstance(mb, dict) or not mb.get("TB_code_v"):
                    continue
                fh.write(json.dumps({
                    "run": run, "task_id": task, "iter_id": str(mb.get("iter_id")),
                    "circuit_type": ctypes[task], "eval1_pass": bool(d.get("Eval1_pass")),
                    "scen_mask": mb.get("scen_mask"),
                    "tb_v": mb["TB_code_v"], "tb_py": mb.get("TB_code_py", "")}) + "\n")
                n_sub += 1

    duts = []
    for t in tasks:
        duts.append({"task_id": t, "role": "golden", "family": "golden",
                     "candidate_id": f"golden_{t}", "rtl": golden[t]})
    for r in j1:
        if r["task_id"] in tasks:
            duts.append({"task_id": r["task_id"], "role": "judge", "family": "A_qwen35_27b",
                         "candidate_id": r["candidate_id"], "rtl": r["rtl"]})
    for r in j0:
        if r["task_id"] in tasks:
            duts.append({"task_id": r["task_id"], "role": "judge", "family": "B_small_pool",
                         "candidate_id": r["candidate_id"], "rtl": r["rtl"]})
    OUT_DUT.write_text("".join(json.dumps(x) + "\n" for x in duts), encoding="utf-8")

    ct = {}
    for t in tasks:
        ct[ctypes.get(t, "?")] = ct.get(ctypes.get(t, "?"), 0) + 1
    print(f"tasks with both families: {len(tasks)}  {ct}")
    print(f"sub-testbenches (4o, all records incl. Eval1 failures): {n_sub}")
    print(f"DUTs: {len(duts)} (golden {len(tasks)}, "
          f"family A {sum(1 for x in duts if x['family'].startswith('A'))}, "
          f"family B {sum(1 for x in duts if x['family'].startswith('B'))})")


if __name__ == "__main__":
    main()
