#!/usr/bin/env python3
"""Mis-keyed Scenario Detection, evaluated exactly on ConfiBench's own runs.

Implements MISKEY_PREREGISTRATION.md. Nothing here re-simulates or calls a model:
every verdict is recovered from ConfiBench's released logs, which record each
checker's failure list BEFORE the scenario mask is applied.

Scoring starts from ConfiBench's RECORDED result and applies only the changes the
new masks cause, each verified mutant by mutant from the raw logs. So:

  * with no changes, the score IS ConfiBench's published number, exactly;
  * the method is credited only with flips the logs prove;
  * where a change cannot be verified, the method is charged, never credited.

Two validity gates run first and are printed before any result.
"""
from __future__ import annotations

import argparse
import json
import math
import random
import re
import zipfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

LOOSE = 0.8
MISMATCH_RE = re.compile(r"Mismatches:\s*(\d+)\s+in\s+(\d+)\s+samples")
EVAL_RE = re.compile(
    r"^([^/]+)/([^/]+)/\d+_\d+_TBeval/(?:"
    r"eval1_GoldenRTL/(\d+)/run_info_py\.txt"
    r"|eval2_GoldenTB_and_mutants/mutant_(\d+)/GoldenTB/run_info\.txt"
    r"|eval2_GoldenTB_and_mutants/mutant_(\d+)/GeneratedTB/(\d+)/run_info_py\.txt)$")


# ---------------------------------------------------------------- ConfiBench rule

def confibench_confidence(rs: List[List[int]], n: int) -> List[float]:
    """Verbatim port of confidence.py:conf_gen (exp_std penalty, log_std reward)."""
    rows = [r for r in rs if not all(v == -1 for v in r)]
    if not rows:
        return [1.0] * n
    full = sum(1 for r in rows if all(v == 1 for v in r))
    reward = 0.1 * math.log(full / len(rows) + 1)
    out = []
    for s in range(n):
        col = [r[s] for r in rows]
        zero_frac = sum(1 for v in col if v == 0) / len(col)
        out.append(min(1.0, max(0.0, 1 - (math.exp(zero_frac) - 1) + reward)))
    return out


def _rankdata_average(vals: Sequence[float]) -> List[float]:
    order = sorted(range(len(vals)), key=lambda i: vals[i])
    ranks = [0.0] * len(vals)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and vals[order[j + 1]] == vals[order[i]]:
            j += 1
        avg = (i + j) / 2 + 1
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    return ranks


def confibench_mask(rs: List[List[int]], n: int, m: float = 0.15,
                    k: float = 8.0) -> List[bool]:
    """Port of conf_bool_gen with e_rank_super. True = scenario kept."""
    conf = confibench_confidence(rs, n)
    rank = [r / len(conf) for r in _rankdata_average(conf)]
    eb = 1.0 / (math.exp(k * (1 - m)) - math.exp(k * m))
    a = math.exp(k * (1 - m)) * eb
    b = math.log(eb)
    return [rank[i] + math.exp(k * conf[i] + b) > a for i in range(n)]


# ---------------------------------------------------------------- proposed rule

def discrimination(rs: List[List[int]], s: int) -> Optional[float]:
    """Item-rest (point-biserial) correlation for scenario s; None if undefined."""
    xs, rests = [], []
    for row in rs:
        if all(v == -1 for v in row) or row[s] == -1:
            continue
        others = [v for j, v in enumerate(row) if j != s and v != -1]
        if not others:
            continue
        xs.append(1.0 if row[s] == 1 else 0.0)
        rests.append(sum(1 for v in others if v == 1) / len(others))
    if len(xs) < 3:
        return None
    mx, mr = sum(xs) / len(xs), sum(rests) / len(rests)
    vx = sum((x - mx) ** 2 for x in xs)
    vr = sum((r - mr) ** 2 for r in rests)
    if vx == 0 or vr == 0:
        return None
    cov = sum((x - mx) * (r - mr) for x, r in zip(xs, rests))
    return cov / math.sqrt(vx * vr)


def miskey_mask(recorded: List[bool], rs: List[List[int]], tau: float = 0.0
                ) -> Tuple[List[bool], List[int]]:
    """ConfiBench's mask, except masked scenarios with discrimination > tau."""
    new = list(recorded)
    changed = []
    for s, keep in enumerate(recorded):
        if keep:
            continue
        d = discrimination(rs, s)
        if d is not None and d > tau:
            new[s] = True
            changed.append(s)
    return new, changed


# ---------------------------------------------------------------- log parsing

def raw_failed(txt: str) -> Optional[List[int]]:
    a, b = txt.rfind("["), txt.rfind("]")
    if a == -1 or b < a:
        return None
    body = txt[a + 1:b].replace("'", "").strip()
    if not body:
        return []
    out = []
    for tok in body.split(","):
        d = "".join(ch for ch in tok if ch.isdigit())
        if d:
            out.append(int(d))
    return out


def rejects(fails: Optional[List[int]], mask: Optional[List[bool]]) -> Optional[bool]:
    """Does this sub-testbench reject, given its raw failures and a mask?"""
    if fails is None:
        return None
    if not fails:
        return False
    if mask is None:
        return True
    return any(not (0 < s <= len(mask)) or mask[s - 1] for s in fails)


def eval2_pass(task: str, eval1: bool, n_mut: int, failed: Sequence[int]) -> bool:
    if not eval1 or n_mut == 0:
        return False
    ok = (n_mut - len(failed)) / n_mut >= LOOSE
    if task == "m2014_q3":
        return sorted(failed) == [3, 4, 7, 8, 9, 10] or ok
    return ok


# ---------------------------------------------------------------- evaluation

def load(zpath: Path, variant: str):
    z = zipfile.ZipFile(zpath)
    base = f"saves_inEDA/TODAES/{variant}/"
    data, gold, off, gen = {}, {}, {}, {}
    for n in z.namelist():
        if not n.startswith(base):
            continue
        rel = n[len(base):]
        if rel.endswith("/data.json") and rel.count("/") == 2:
            run, task = rel.split("/")[:2]
            data[(run, task)] = n
            continue
        m = EVAL_RE.match(rel)
        if not m:
            continue
        run, task = m.group(1), m.group(2)
        txt = z.read(n).decode("utf-8", "replace")
        if m.group(3):
            gold[(run, task, m.group(3))] = raw_failed(txt)
        elif m.group(4):
            mm = MISMATCH_RE.search(txt)
            off[(run, task, int(m.group(4)))] = None if not mm else int(mm.group(1)) == 0
        else:
            gen[(run, task, int(m.group(5)), m.group(6))] = raw_failed(txt)
    recs = {k: json.loads(z.read(v).decode("utf-8", "replace")) for k, v in data.items()}
    return recs, gold, off, gen


def score(recs, gold, off, gen, rule: str, tau: float = 0.0):
    """Per-record (eval1, eval2) under a masking rule, plus an audit."""
    out = {}
    audit = Counter()
    for (run, task), d in recs.items():
        e1 = bool(d.get("Eval1_pass"))
        failed = set(d.get("Eval2_failed_mutant_idxes") or [])
        n_mut = len(d.get("mutants") or [])
        subs = [mb for mb in (d.get("multibench_info") or [])
                if isinstance(mb, dict) and mb.get("scen_mask") is not None
                and any((run, task, i, str(mb.get("iter_id"))) in gen
                        for i in range(1, n_mut + 1))]
        if rule == "recorded" or not subs or not e1:
            out[(run, task)] = (e1, eval2_pass(task, e1, n_mut, sorted(failed)))
            continue

        new_masks, rec_masks = {}, {}
        for mb in subs:
            sid = str(mb["iter_id"])
            rec_masks[sid] = list(mb["scen_mask"])
            nm, ch = miskey_mask(mb["scen_mask"], mb.get("RSmatrix") or [], tau)
            new_masks[sid] = nm
            audit["scenarios unmasked"] += len(ch)
            audit["scenarios masked by ConfiBench"] += sum(1 for v in mb["scen_mask"] if not v)

        # Eval1 under the new masks. Unmasking can only break it. Where it cannot
        # be verified for a changed sub-testbench, the method is CHARGED.
        e1_new = e1
        for sid, nm in new_masks.items():
            if nm == rec_masks[sid]:
                continue
            g = gold.get((run, task, sid))
            if g is None:
                e1_new = False
                audit["Eval1 charged: golden log missing"] += 1
                break
            if rejects(g, nm):
                e1_new = False
                audit["Eval1 broken by an unmask"] += 1
                break

        # Eval2: flip only mutants whose logs prove the verdict changed.
        failed_new = set(failed)
        for i in range(1, n_mut + 1):
            o = off.get((run, task, i))
            if o is None:
                continue
            before = after = None
            ok = True
            rb, ra = False, False
            for sid in new_masks:
                f = gen.get((run, task, i, sid))
                vb = rejects(f, rec_masks[sid])
                va = rejects(f, new_masks[sid])
                if vb is None or va is None:
                    ok = False
                    break
                rb, ra = rb or vb, ra or va
            if not ok:
                continue
            before, after = (not rb), (not ra)       # True = ConfiBench accepts
            consistent = ((o != before) == (i in failed))
            if not consistent:
                audit["mutant skipped: reconstruction disagrees with record"] += 1
                continue
            if before and not after:
                audit["mutant verdict flipped to reject"] += 1
                if o is False:
                    failed_new.discard(i)
                    audit["  ...a missed detection recovered"] += 1
                else:
                    failed_new.add(i)
                    audit["  ...a FALSE rejection introduced"] += 1
        out[(run, task)] = (e1_new, eval2_pass(task, e1_new, n_mut, sorted(failed_new)))
    return out, audit


def per_task(scores: Dict[Tuple[str, str], Tuple[bool, bool]], idx: int) -> Dict[str, float]:
    acc = defaultdict(list)
    for (run, task), v in scores.items():
        acc[task].append(1.0 if v[idx] else 0.0)
    return {t: sum(v) / len(v) for t, v in acc.items()}


def paired_boot(a: Dict[str, float], b: Dict[str, float], n: int = 10000, seed: int = 0):
    tasks = sorted(set(a) & set(b))
    diffs = [a[t] - b[t] for t in tasks]
    rng = random.Random(seed)
    k = len(diffs)
    boot = sorted(sum(diffs[rng.randrange(k)] for _ in range(k)) / k for _ in range(n))
    return sum(diffs) / k, boot[int(0.025 * n)], boot[int(0.975 * n) - 1], k


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--zip", type=Path, required=True)
    ap.add_argument("--variant", default="ConfiBench_4o")
    ap.add_argument("--tau", type=float, default=0.0)
    ap.add_argument("--bootstrap", type=int, default=10000)
    ap.add_argument("--out", type=Path)
    args = ap.parse_args()

    recs, gold, off, gen = load(args.zip, args.variant)
    print(f"{args.variant}: {len(recs)} records, {len(gold)} golden logs, "
          f"{len(off)} official verdicts, {len(gen)} generated-testbench logs\n")

    # ---- Gate 1: reproduce ConfiBench's mask from its own RS matrices.
    same = diff = 0
    for d in recs.values():
        for mb in d.get("multibench_info") or []:
            if not isinstance(mb, dict) or mb.get("scen_mask") is None or not mb.get("RSmatrix"):
                continue
            n = len(mb["scen_mask"])
            if confibench_mask(mb["RSmatrix"], n) == list(mb["scen_mask"]):
                same += 1
            else:
                diff += 1
    g1 = same / max(1, same + diff)
    print(f"GATE 1  reproduced ConfiBench mask == recorded : {same}/{same+diff} "
          f"= {g1:.1%}   ({'PASS' if g1 >= 0.95 else 'FAIL'}, need >= 95%)")

    # ---- Gate 2: recorded masks reproduce recorded per-mutant verdicts.
    agree = disagree = 0
    for (run, task), d in recs.items():
        if not d.get("Eval1_pass"):
            continue
        failed = set(d.get("Eval2_failed_mutant_idxes") or [])
        n_mut = len(d.get("mutants") or [])
        subs = [mb for mb in (d.get("multibench_info") or [])
                if isinstance(mb, dict) and mb.get("scen_mask") is not None]
        for i in range(1, n_mut + 1):
            o = off.get((run, task, i))
            vs = [rejects(gen.get((run, task, i, str(mb["iter_id"]))), mb["scen_mask"])
                  for mb in subs if (run, task, i, str(mb["iter_id"])) in gen]
            if o is None or not vs or any(v is None for v in vs):
                continue
            acc = not any(vs)
            if (o != acc) == (i in failed):
                agree += 1
            else:
                disagree += 1
    g2 = agree / max(1, agree + disagree)
    print(f"GATE 2  recorded-mask verdicts == recorded     : {agree}/{agree+disagree} "
          f"= {g2:.1%}")
    if g1 < 0.95:
        print("\nGATE 1 FAILED -- reproduction must be fixed before any result is read.")
        return

    base, _ = score(recs, gold, off, gen, "recorded")
    new, audit = score(recs, gold, off, gen, "miskey", args.tau)

    print(f"\n== Mis-keyed Scenario Detection (tau = {args.tau}) vs ConfiBench ==")
    for name, idx in (("Eval1", 0), ("Eval2", 1)):
        b, m = per_task(base, idx), per_task(new, idx)
        mb = sum(b.values()) / len(b)
        mm = sum(m.values()) / len(m)
        d, lo, hi, k = paired_boot(m, b, args.bootstrap)
        print(f"  {name}:  ConfiBench {mb:.4f}   with rule {mm:.4f}   "
              f"delta {d:+.4f}  95% CI [{lo:+.4f}, {hi:+.4f}]  (N={k} tasks)")
    print("\n  audit:")
    for k, v in audit.items():
        print(f"    {v:6d}  {k}")
    if args.out:
        args.out.write_text(json.dumps({
            "variant": args.variant, "tau": args.tau,
            "gate1": g1, "gate2": g2, "audit": dict(audit),
            "baseline": {f"{k[0]}|{k[1]}": v for k, v in base.items()},
            "method": {f"{k[0]}|{k[1]}": v for k, v in new.items()}},
            indent=0), encoding="utf-8")


if __name__ == "__main__":
    main()
