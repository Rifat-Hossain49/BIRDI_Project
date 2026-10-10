#!/usr/bin/env python3
"""Extract the sub-testbenches a cross-family judge has to be run on.

Only the ones that can change a verdict: sub-testbenches ConfiBench actually used
in its final evaluation, that carry at least one masked scenario, on records that
passed Eval1 (unmasking can only lower Eval1, so an Eval1-failing record cannot
gain). Everything else is left out so the simulation budget goes where the rule
can act.
"""
from __future__ import annotations

import json
import re
import sys
import zipfile
from pathlib import Path

ZIP = Path(sys.argv[1])
OUT = Path(sys.argv[2])
VARIANTS = ("ConfiBench_4o", "ConfiBench_4omini")
GEN_RE = re.compile(r"^([^/]+)/([^/]+)/\d+_\d+_TBeval/eval2_GoldenTB_and_mutants/"
                    r"mutant_\d+/GeneratedTB/(\d+)/run_info_py\.txt$")

z = zipfile.ZipFile(ZIP)
n_rec = n_sub = 0
with OUT.open("w", encoding="utf-8", newline="\n") as fh:
    for variant in VARIANTS:
        base = f"saves_inEDA/TODAES/{variant}/"
        used = set()
        datas = {}
        for n in z.namelist():
            if not n.startswith(base):
                continue
            rel = n[len(base):]
            m = GEN_RE.match(rel)
            if m:
                used.add((m.group(1), m.group(2), m.group(3)))
            elif rel.endswith("/data.json") and rel.count("/") == 2:
                datas[tuple(rel.split("/")[:2])] = n
        for (run, task), path in sorted(datas.items()):
            d = json.loads(z.read(path).decode("utf-8", "replace"))
            if not d.get("Eval1_pass"):
                continue
            for mb in d.get("multibench_info") or []:
                if not isinstance(mb, dict) or mb.get("scen_mask") is None:
                    continue
                sid = str(mb.get("iter_id"))
                if (run, task, sid) not in used or all(mb["scen_mask"]):
                    continue
                fh.write(json.dumps({
                    "variant": variant, "run": run, "task_id": task,
                    "iter_id": sid, "scen_mask": mb["scen_mask"],
                    "circuit_type": d.get("circuit_type", "?"),
                    "tb_v": mb["TB_code_v"], "tb_py": mb["TB_code_py"],
                }) + "\n")
                n_sub += 1
            n_rec += 1
print(f"wrote {OUT}: {n_sub} masked sub-testbenches from {n_rec} Eval1-passing records")
