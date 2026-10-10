#!/usr/bin/env python3
"""Benchmark loading for the Divergence-Resolved Testbench pipeline.

Two strictly separated kinds of data:

  PIPELINE INPUTS   what a testbench generator may see: task id, natural-language
                    specification, module header, circuit type.
  EVALUATION ONLY   golden RTL, the official VerilogEval testbench, and the mutants.
                    The pipeline never reads these; only evaluate.py and the
                    golden-reference calibration do.

Mutants are the exact lists ConfiBench was scored against (verified identical on all
156 tasks), and every mutant is used -- tasks have 5 to 11, not always 10.

Task split, fixed before any pipeline result:
  DEV   the 60 tasks examined in the judge / reference / localized-resolution pilots
  TEST  the remaining 96 tasks, untouched by any design decision
"""
from __future__ import annotations

import json
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ZIP = ROOT / "baselines/confibench_drive/TODAES_opensource_result.zip"
GOLDEN = ROOT / "kaggle_upload_safe_cbx/dataset/active_tb_safe_cbx/golden.jsonl"
MUTANTS = ROOT / "kaggle_upload_safe_cbx/dataset/active_tb_safe_cbx/hidden_bank_a.jsonl"
DEV_LIST = ROOT / "analysis/j1_tasks.jsonl"
OUT = Path(__file__).resolve().parent / "benchmark.jsonl"


def build() -> None:
    z = zipfile.ZipFile(ZIP)
    base = "saves_inEDA/TODAES/ConfiBench_4o/"
    spec = {}
    for n in z.namelist():
        if n.startswith(base) and n.endswith("/data.json") and n[len(base):].count("/") == 2:
            d = json.loads(z.read(n).decode("utf-8", "replace"))
            spec.setdefault(d["task_id"], {"description": d["description"], "header": d["header"],
                                           "circuit_type": d.get("circuit_type", "?")})
    golden = {json.loads(l)["task_id"]: json.loads(l) for l in GOLDEN.read_text(encoding="utf-8").splitlines() if l.strip()}
    muts = {json.loads(l)["task_id"]: json.loads(l)["mutants"] for l in MUTANTS.read_text(encoding="utf-8").splitlines() if l.strip()}
    dev = {json.loads(l)["task_id"] for l in DEV_LIST.read_text(encoding="utf-8").splitlines() if l.strip()}
    rows = []
    for t in sorted(spec):
        rows.append({"task_id": t, "split": "dev" if t in dev else "test", **spec[t],
                     "eval_golden": golden[t]["module_code"], "eval_official_tb": golden[t]["testbench"],
                     "eval_mutants": muts[t]})
    OUT.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    print(f"wrote {OUT}: {len(rows)} tasks, dev {sum(r['split']=='dev' for r in rows)}, "
          f"test {sum(r['split']=='test' for r in rows)}")


def load(split: str | None = None):
    rows = [json.loads(l) for l in OUT.read_text(encoding="utf-8").splitlines() if l.strip()]
    return [r for r in rows if split is None or r["split"] == split]


def pipeline_view(task: dict) -> dict:
    """Everything a generator may see. Nothing prefixed eval_ ever passes through."""
    return {k: v for k, v in task.items() if not k.startswith("eval_")}


if __name__ == "__main__":
    build()
