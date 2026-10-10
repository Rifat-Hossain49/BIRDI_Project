#!/usr/bin/env python3
"""ACTIVE-TB-SAFE: run both channels over the frozen frontend.

Channel 1 is emitted verbatim from the frozen generator's own stimulus. It is
never re-derived, re-selected or re-ordered here, so whatever the generator
scored, it still scores.

Channel 2 synthesises shadow tests from differential BMC between spec-only
candidate RTLs, adjudicated by the frozen checker, and emits them as a separate
driver. A DUT failing a shadow test is a WARNING, not a verdict.

The frontend is a parameter: `--frontend` selects which generator's artefacts to
freeze, so re-anchoring to ConfiBench later needs no code change.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tempfile
import time
from pathlib import Path
from typing import Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "amp"))

from checker_state import build_model, validate_model
from frontend_adapter import FrozenChecker, parse_driver, recover_expectations
from formal_witness import tools_available
from shadow_verify import (channel1_accepts, design_from_parse,
                           differential_witnesses, emit_shadow_driver,
                           guess_reset, init_prefix, random_witnesses,
                           repair_tests, self_consistent, suite_simulates,
                           translation_audit)

ROOT = Path(__file__).resolve().parent.parent
# Frontend selection is data only: the method below is frozen and identical for
# every entry here, which is what makes a transfer run a genuine
# frontend-independence test rather than a re-tuning.
FRONTENDS = {
    "correctbench": ROOT / "baselines/ConfiBench/data/CorrectBenchResults/run_info_and_codes.jsonl",
    "autobench": ROOT / "baselines/ConfiBench/data/AutoBenchResults/run_info_and_codes.jsonl",
    "confibench": ROOT / "baselines/ConfiBench/data/ConfiBenchResults/run_info_and_codes.jsonl",
}
CANDIDATES = ROOT / "kaggle_runs/spec_only_full_repair_v2_complete/active_tb_s_repaired_oracles_full_v1"


def load_frontend(name: str) -> Dict[str, dict]:
    path = FRONTENDS[name]
    if not path.is_file():
        raise SystemExit(f"frontend artefacts absent: {path}")
    out: Dict[str, dict] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            r = json.loads(line)
            out.setdefault(r["task_id"], r)
    return out


def load_candidates(task_ids) -> Dict[str, Dict[str, str]]:
    """Spec-only candidate RTL, keyed task -> candidate_id -> rtl."""
    per: Dict[str, Dict[str, str]] = {t: {} for t in task_ids}
    for fname in ("qwen_candidates.jsonl", "llama_candidates.jsonl",
                  "codegemma_candidates.jsonl"):
        f = CANDIDATES / fname
        if not f.is_file():
            continue
        for line in f.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            r = json.loads(line)
            if r["task_id"] in per and r.get("compiled") and r.get("interface_ok"):
                per[r["task_id"]][r["candidate_id"]] = r["rtl"]
    return per


def emit_channel1(parse, original_driver: str) -> str:
    """Channel 1 is the frozen generator's driver, shipped verbatim.

    An earlier build reconstructed the driver from the parsed event stream. That
    was a mistake: reconstruction lost fidelity badly enough that 80 of 150
    suites failed to compile and Golden acceptance fell from the generator's own
    0.78 to 0.35. Non-regression is only a real guarantee if Channel 1 is
    literally the generator's bytes, so it is passed through untouched and the
    parse is used solely to describe the interface for Channel 2.
    """
    return original_driver


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--frontend", default="correctbench", choices=sorted(FRONTENDS))
    ap.add_argument("--tasks", type=Path, default=ROOT / "amp" / "pilot_tasks.json")
    ap.add_argument("--bounds", default="4,8,16,32")
    ap.add_argument("--timeout", type=float, default=90.0)
    ap.add_argument("--max-pairs", type=int, default=6)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--gate", default="translation",
                    choices=("translation", "blessed"),
                    help="translation: fidelity of the emitted suite against the "
                         "native checker path (default). blessed: the original "
                         "Case-A rule, kept only as an experimental control.")
    ap.add_argument("--pair-order", default="baseline-aware",
                    choices=("baseline-aware", "fixed"),
                    help="baseline-aware: spend the solver budget first on "
                         "candidate pairs Channel 1 cannot separate. fixed: the "
                         "original name order, kept as the ablation arm.")
    ap.add_argument("--no-repair", dest="repair", action="store_false",
                    help="drop a suite wholesale when the audit finds a bad "
                         "point, instead of masking or truncating it.")
    ap.set_defaults(repair=True)
    ap.add_argument("--stimulus", default="bmc", choices=("bmc", "random"),
                    help="bmc: differential BMC witnesses. random: the matched "
                         "stimulus ablation -- same test count and lengths, "
                         "same checker, same gate, random inputs.")
    ap.add_argument("--match-manifest", type=Path,
                    help="for --stimulus random: a formal arm's manifest whose "
                         "per-task test budget this run reproduces exactly.")
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()

    match: Dict[str, dict] = {}
    if args.match_manifest and args.match_manifest.is_file():
        match = json.loads(args.match_manifest.read_text()).get("reports", {})
        print(f"matching test budget from {args.match_manifest} "
              f"({len(match)} task report(s))")

    formal_ok, msg = tools_available()
    print(f"toolchain: {'ok' if formal_ok else msg}")
    if not formal_ok:
        print("  Channel 2 disabled; Channel 1 still emits so the frozen "
              "generator's verdict is preserved regardless.")

    frontend = load_frontend(args.frontend)
    wanted = [t for t in json.loads(args.tasks.read_text()) if t in frontend]
    cands = load_candidates(wanted)
    bounds = [int(x) for x in args.bounds.split(",")]

    suites = args.out / "suites"
    suites.mkdir(parents=True, exist_ok=True)
    manifest = {"frontend": args.frontend, "gate": args.gate,
                "stimulus": args.stimulus, "seed": args.seed,
                "pair_order": args.pair_order, "repair": args.repair,
                "bounds": bounds, "max_pairs": args.max_pairs,
                "channel1": {}, "channel2": {}, "reports": {}, "skipped": {}}

    with tempfile.TemporaryDirectory(prefix="safe_") as td:
        work = Path(td)
        for tid in wanted:
            row = frontend[tid]
            parse = parse_driver(row.get("tb_v_driver") or "")
            checker = FrozenChecker(row.get("tb_py_checker") or "")

            # Channel 1 FIRST, and unconditionally. It is the frontend's own
            # bytes; it needs neither the parse nor the checker, which exist
            # only to describe the interface to Channel 2.
            #
            # An earlier order emitted it after both gates, so a driver the
            # ADAPTER could not parse produced no suite at all -- 6 tasks on
            # CorrectBench and 21 on AutoBench shipped nothing where the
            # frontend had a working testbench, 15 of which its own bytes pass.
            # That silently broke the architecture's central claim, that
            # whatever the generator scored it still scores, and it cost more
            # Eval1 (+0.032 / +0.064) than every Channel 2 change put together.
            driver_bytes = (row.get("tb_v_driver") or "")
            if driver_bytes:
                c1 = emit_channel1(parse, driver_bytes).encode("utf-8")
                n1 = f"{tid}__CHANNEL1.v"
                (suites / n1).write_bytes(c1)
                manifest["channel1"][tid] = {
                    "file": n1, "sha256": hashlib.sha256(c1).hexdigest(),
                    "cycles": len(parse.events) if parse.supported else None,
                    "adapter_parsed": parse.supported}
            else:
                manifest["skipped"][tid] = "frontend produced no driver"
                continue

            # Channel 2 needs both, so its gates come after Channel 1 is safe.
            if not parse.supported:
                manifest["skipped"][tid] = f"channel2: driver unparsed ({parse.reason})"
                continue
            if not checker.supported:
                manifest["skipped"][tid] = f"channel2: checker ({checker.reason})"
                continue

            if not formal_ok:
                manifest["skipped"][tid] = f"channel2: toolchain unavailable ({msg})"
                continue

            pool = cands.get(tid, {})
            fams = {c.rsplit("_", 1)[0] for c in pool}
            if len(fams) < 2:
                manifest["skipped"][tid] = f"channel2: only {len(fams)} candidate family"
                continue

            exp, _ = recover_expectations(parse, checker, max_bits=12)
            if exp is None:
                manifest["skipped"][tid] = "channel2: expectations unrecoverable"
                continue
            # The adjudication model follows the CHECKER'S SHAPE, read from the
            # artefact itself: stateful checkers expose a GoldenDUT, stateless
            # ones are a pure function of one row. Choosing by shape rather than
            # by frontend name is what lets a ConfiBench transfer run unchanged.
            model, shape = build_model(row["tb_py_checker"], parse,
                                       parse.output_signals, parse.widths)
            good, why = validate_model(model, parse, exp)
            if not good:
                manifest["skipped"][tid] = \
                    f"channel2: state model unusable [{shape}] ({why[:60]})"
                continue

            reset_name, reset_active = guess_reset(parse)
            design = design_from_parse(parse, reset_name, reset_active)
            started = time.time()
            pre = init_prefix(parse)
            c1_src = emit_channel1(parse, row["tb_v_driver"])

            # Baseline-aware search: ask the FROZEN Channel 1 suite which
            # candidates it already separates, then spend the solver budget
            # first on pairs it cannot tell apart. Golden is not consulted --
            # this is the generator's own verdict on candidate RTL, available at
            # generation time exactly as at deployment.
            accepts = None
            if args.pair_order == "baseline-aware" and args.stimulus == "bmc":
                accepts = channel1_accepts(pool, c1_src, row["tb_py_checker"], work)
                info_acc = {"accepted": sum(1 for v in accepts.values() if v is True),
                            "rejected": sum(1 for v in accepts.values() if v is False),
                            "no_run": sum(1 for v in accepts.values() if v is None)}
            else:
                info_acc = {"accepted": None, "rejected": None, "no_run": None}

            if args.stimulus == "random":
                # Matched-resource ablation: identical test count and lengths to
                # the formal arm's own manifest, so only the way the stimulus is
                # CHOSEN differs. Everything after this point is identical.
                lengths = (match.get(tid, {}).get("witness_lengths") or []) \
                    if match else [bounds[0]] * args.max_pairs
                if not lengths:
                    manifest["skipped"][tid] = \
                        "channel2: formal arm produced no test to match"
                    continue
                report = random_witnesses(tid, design, model, lengths,
                                          args.seed, prefix=pre)
            else:
                report = differential_witnesses(tid, pool, design, model, bounds,
                                                args.timeout, work, args.max_pairs,
                                                prefix=pre, accepts=accepts)
            info = report.to_dict()
            info["init_prefix_cycles"] = len(pre)
            info["channel1_on_candidates"] = info_acc
            info["pair_order"] = args.pair_order
            info["checker_shape"] = shape
            info["wall_seconds"] = round(time.time() - started, 2)
            manifest["reports"][tid] = info

            if report.tests:
                # Both gates are always evaluated and recorded; only the one
                # named by --gate decides. Running them together is what makes
                # the two arms a paired comparison on identical suites rather
                # than two runs that could differ for unrelated reasons.
                audit = translation_audit(parse, report.tests, model,
                                          row["tb_py_checker"])
                tests = list(report.tests)
                repair_note = ""
                if not audit["ok"] and audit["bad"] and args.repair:
                    # Keep the sound part rather than discarding the suite whole.
                    tests, repair_note = repair_tests(tests, audit["bad"],
                                                      stateless=(shape == "stateless"))
                    if tests:
                        audit = translation_audit(parse, tests, model,
                                                  row["tb_py_checker"])
                    else:
                        audit = {"ok": False, "why": "no test survived repair",
                                 "bad": {}, "points": 0}

                shadow_src = emit_shadow_driver(parse, tests, reset_name,
                                                reset_active) if tests else ""
                sim_ok, sim_why = (suite_simulates(shadow_src, c1_src, pool, work)
                                   if tests else (False, "no tests"))
                bl_ok, bl_why = (self_consistent(shadow_src, c1_src,
                                                 row["tb_py_checker"], pool, work)
                                 if tests else (False, "no tests"))
                info["gate_translation"] = {"ok": audit["ok"], "why": audit["why"],
                                            "points": audit["points"]}
                info["gate_simulates"] = {"ok": sim_ok, "why": sim_why}
                info["gate_blessed"] = {"ok": bl_ok, "why": bl_why}
                info["repair"] = repair_note
                info["tests_after_repair"] = len(tests)
                if args.gate == "translation":
                    ok2 = audit["ok"] and sim_ok
                    why2 = audit["why"] if not audit["ok"] else sim_why
                else:
                    ok2 = bl_ok
                    why2 = bl_why
                info["self_consistent"] = ok2
                info["self_consistency"] = why2
                if ok2:
                    c2 = shadow_src.encode("utf-8")
                    n2 = f"{tid}__CHANNEL2.v"
                    (suites / n2).write_bytes(c2)
                    manifest["channel2"][tid] = {
                        "file": n2, "sha256": hashlib.sha256(c2).hexdigest(),
                        "cycles": sum(t.cycles for t in tests),
                        "tests": len(tests),
                        "asserted_points": sum(t.asserted_points for t in tests)}
                else:
                    manifest["skipped"][tid] = f"channel2 dropped: {why2}"
            print(f"  {tid:22s} C1={len(parse.events):5d}cyc  "
                  f"pairs={info['pairs_attempted']:2d} wit={info['witnesses_found']:2d} "
                  f"tests={info['shadow_tests']:2d} "
                  f"C2cyc={info['shadow_cycles']:4d} {info['wall_seconds']:6.1f}s",
                  flush=True)

    blob = json.dumps(manifest, sort_keys=True, indent=1)
    (args.out / "safe_manifest.json").write_text(blob, encoding="utf-8")
    (args.out / "safe_manifest.sha256").write_text(
        hashlib.sha256(blob.encode()).hexdigest() + "\n", encoding="utf-8")
    print(f"\nchannel1 suites: {len(manifest['channel1'])}")
    print(f"channel2 suites: {len(manifest['channel2'])}")
    print(f"skipped: {len(manifest['skipped'])}")


if __name__ == "__main__":
    main()
