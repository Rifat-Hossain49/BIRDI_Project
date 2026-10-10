#!/usr/bin/env python3
"""The complete loss funnel for Channel 2, with a reason attached to every loss.

Reading only the headline "17 of 156 tasks ship a shadow suite" says the channel
is narrow but not WHY, and the why decides what to fix. This walks every stage
from requested task to emitted suite and attributes each drop, so an improvement
can be aimed at the stage that actually dominates rather than at the stage that
is easiest to change.

Stages are in execution order and each task is charged to the FIRST stage that
rejects it, so the counts partition the population exactly.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Dict, List, Tuple

STAGES: List[Tuple[str, str]] = [
    ("requested",        "tasks requested"),
    ("frontend_present", "frontend produced a testbench"),
    ("driver_parsed",    "driver parsed by the adapter"),
    ("checker_loaded",   "python checker loadable"),
    ("channel1_emitted", "Channel 1 emitted (frozen bytes)"),
    ("toolchain",        "formal toolchain available"),
    ("two_families",     "two or more candidate families"),
    ("expectations",     "checker expectations recoverable"),
    ("state_model",      "state model validated vs check_dut"),
    ("pairs_attempted",  "candidate pairs submitted to BMC"),
    ("witness_found",    "BMC returned SAT (a disagreement exists)"),
    ("witness_usable",   "witness parsed and legal"),
    ("adjudicated",      "frozen checker had an opinion"),
    ("tests_built",      "shadow tests built"),
    ("gate_passed",      "safety gate passed"),
    ("suite_emitted",    "Channel 2 suite shipped"),
]

_SKIP_MAP = [
    ("driver:",                "driver_parsed"),
    ("checker:",               "checker_loaded"),
    ("channel2: toolchain",    "toolchain"),
    ("channel2: only",         "two_families"),
    ("channel2: expectations", "expectations"),
    ("channel2: state model",  "state_model"),
    ("channel2: formal arm",   "pairs_attempted"),   # random arm, nothing to match
    ("channel2 dropped:",      "gate_passed"),
]


def classify_skip(reason: str) -> str:
    for pref, stage in _SKIP_MAP:
        if reason.startswith(pref):
            return stage
    return "unclassified"


def gate_reason(why: str) -> str:
    """Bucket a gate rejection by mechanism.

    The split that matters: A and C are the OLD gate's own artefacts (it needed
    a Channel-1-passing candidate, and it treated a rejection of one as a fault),
    while D and E are genuine defects in the emitted suite.
    """
    w = why.lower()
    if "no candidate is blessed" in w:
        return "A. no candidate passed Channel 1 (gate had nothing to test)"
    if ("failed to simulate" in w or "fails to run" in w
            or "did not simulate" in w or "cannot check" in w):
        return "B. shadow suite did not simulate"
    if "rejects checker-blessed" in w:
        return "C. shadow rejects a Channel-1-passing candidate (DISCARDED DETECTION)"
    if "unsatisfiable" in w or "no satisfiable assertion" in w:
        return "D. unsatisfiable assertion point (genuine defect)"
    if "path disagreement" in w:
        return "E. check_dut disagrees with load()/check() (genuine defect)"
    if "survived repair" in w:
        return "F. every assertion point was defective; nothing left after repair"
    if "raised" in w or "unusable" in w:
        return "G. checker raised / sweep unusable"
    return "H. other: " + why[:60]


def build(manifest: dict, requested: List[str]) -> dict:
    reports = manifest["reports"]
    skipped = manifest["skipped"]
    ch1, ch2 = manifest["channel1"], manifest["channel2"]

    surviving = {k: 0 for k, _ in STAGES}
    lost: Dict[str, Counter] = {k: Counter() for k, _ in STAGES}

    surviving["requested"] = len(requested)
    present = [t for t in requested if t in ch1 or t in skipped or t in reports]
    surviving["frontend_present"] = len(present)
    lost["frontend_present"]["no frontend record for this task"] = \
        len(requested) - len(present)

    for stage in ("driver_parsed", "checker_loaded"):
        n = sum(1 for r in skipped.values() if classify_skip(r) == stage)
        lost[stage][stage.replace("_", " ") + " failed"] = n
    surviving["driver_parsed"] = (surviving["frontend_present"]
                                  - sum(lost["driver_parsed"].values()))
    surviving["checker_loaded"] = (surviving["driver_parsed"]
                                   - sum(lost["checker_loaded"].values()))
    surviving["channel1_emitted"] = len(ch1)

    run = surviving["channel1_emitted"]
    for stage in ("toolchain", "two_families", "expectations", "state_model"):
        n = 0
        det: Counter = Counter()
        for r in skipped.values():
            if classify_skip(r) == stage:
                n += 1
                det[r.split("channel2: ", 1)[-1][:60]] += 1
        lost[stage].update(det)
        run -= n
        surviving[stage] = run

    surviving["pairs_attempted"] = sum(1 for r in reports.values()
                                       if r["pairs_attempted"] > 0)
    lost["pairs_attempted"]["no pair formed / every pair errored"] = \
        surviving["state_model"] - surviving["pairs_attempted"]

    surviving["witness_found"] = sum(1 for r in reports.values()
                                     if r["witnesses_found"] > 0)
    lost["witness_found"]["BMC found no disagreement (UNSAT / timeout / unsupported)"] = \
        surviving["pairs_attempted"] - surviving["witness_found"]

    usable = [r for r in reports.values()
              if r["witnesses_found"] > 0
              and r["witnesses_found"] > (r["witnesses_unparsed"]
                                          + r["witnesses_rejected_illegal"])]
    surviving["witness_usable"] = len(usable)
    unp = sum(r["witnesses_unparsed"] for r in reports.values())
    ill = sum(r["witnesses_rejected_illegal"] for r in reports.values())
    lost["witness_usable"][
        "every witness unparsed (%d across all tasks) or illegal (%d)" % (unp, ill)] = \
        surviving["witness_found"] - surviving["witness_usable"]

    surviving["adjudicated"] = sum(1 for r in reports.values() if r["adjudicated"] > 0)
    lost["adjudicated"]["checker abstained at every witness point"] = \
        surviving["witness_usable"] - surviving["adjudicated"]

    surviving["tests_built"] = sum(1 for r in reports.values() if r["shadow_tests"] > 0)
    lost["tests_built"]["adjudicated but no test survived assembly"] = \
        surviving["adjudicated"] - surviving["tests_built"]

    gated: Counter = Counter()
    for r in reports.values():
        if r["shadow_tests"] and not r.get("self_consistent", True):
            gated[gate_reason(r.get("self_consistency", ""))] += 1
    surviving["gate_passed"] = surviving["tests_built"] - sum(gated.values())
    lost["gate_passed"].update(gated)

    surviving["suite_emitted"] = len(ch2)
    lost["suite_emitted"]["passed the gate but was not written"] = \
        surviving["gate_passed"] - surviving["suite_emitted"]

    return {"surviving": surviving, "lost": {k: dict(v) for k, v in lost.items()}}


def render(name: str, f: dict) -> str:
    out = [("### " + name), "",
           "| # | stage | tasks surviving | lost here | reason |",
           "|---|---|---:|---:|---|"]
    for i, (key, label) in enumerate(STAGES):
        losses = {k: v for k, v in f["lost"][key].items() if v}
        tot = sum(losses.values())
        reason = "; ".join("%s (%d)" % (k, v) for k, v in
                           sorted(losses.items(), key=lambda kv: -kv[1])) or "--"
        out.append("| %d | %s | %d | %s | %s |"
                   % (i, label, f["surviving"][key], tot or "--", reason))
    return "\n".join(out)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", action="append", required=True,
                    help="name=path, repeatable")
    ap.add_argument("--tasks", type=Path, required=True)
    ap.add_argument("--out", type=Path)
    args = ap.parse_args()

    requested = json.loads(args.tasks.read_text())
    blocks, data = [], {}
    for spec in args.manifest:
        name, path = spec.split("=", 1)
        f = build(json.loads(Path(path).read_text()), requested)
        data[name] = f
        blocks.append(render(name, f))
    text = "\n\n".join(blocks)
    print(text)
    if args.out:
        args.out.write_text(text + "\n", encoding="utf-8")
        args.out.with_suffix(".json").write_text(
            json.dumps(data, indent=1, sort_keys=True), encoding="utf-8")


if __name__ == "__main__":
    main()
