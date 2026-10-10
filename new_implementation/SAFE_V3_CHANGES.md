# ACTIVE-TB-SAFE v3 — what changed, and what each change is measured against

The architecture is unchanged. Channel 1 is still the frozen generator's driver
shipped as literal bytes; Channel 2 still produces warnings only. What changed is
the machinery inside Channel 2, plus four defects in the shared adapter that were
suppressing it.

This document is written **before** the v3 measurement lands, so the claims it
makes about what was fixed are separable from the claims about what that bought.
Numbers marked *(pending)* come from the v3 Kaggle run.

---

## 1. The gate was defeating the channel's own purpose

`self_consistent()` called a candidate **blessed** if it passed the *original
Channel 1 testbench*, then dropped any shadow suite that rejected such a
candidate.

Surviving the original suite does not make a design correct. Finding a design
that escapes the original tests and then fails a new, checker-adjudicated test is
the entire point of the channel. The old rule discarded precisely those, and its
headline "zero false alarms" was partly purchased with them.

Measured cost on the v2 run (156 tasks, both frontends):

| Gate outcome | CorrectBench | AutoBench |
|---|---:|---:|
| Tasks reaching the gate | 54 | 26 |
| Shipped | 17 | 9 |
| **A.** no candidate passed Channel 1 (gate had nothing to test) | 21 | 15 |
| **B.** shadow suite did not simulate | 10 | 0 |
| **C.** rejected a Channel-1-passing candidate — *discarded detection* | 6 | 2 |

Tasks lost to C: `2012_q2fsm, alwaysblock2, count15, dff8p, fsm1s, fsm3s`
(CorrectBench); `count1to10, fsm1s` (AutoBench).

### The replacement: `translation_audit`

The question the gate should ask needs **no candidates at all**. Expectations are
computed through `load()`/`check()`, but a deployed suite is scored through
`check_dut()` over a rendered TBout — two different paths through the same frozen
checker, and only the first is used when the expectations are built. So: replay
the suite's own trace, fill every observation point with a value the checker
itself accepts, and run the native `check_dut` over the result.

Two defect classes, separated as required, and **neither is a detection**:

- **unsatisfiable point** — the checker accepts *no* output value there, so the
  suite would reject every design, Golden included;
- **path disagreement** — `check_dut` rejects what `load()`/`check()` predicted.

A candidate merely *failing* a shadow test is now a detection and no longer
causes rejection. The old rule is retained verbatim as `--gate blessed`; both
gates are evaluated and recorded on every run, so the arms are paired on
identical suites rather than compared across two runs.

Locating the offending point uses a growing prefix and failure **counts**, never
the reported labels — see defect 3 for why labels cannot be trusted.

---

## 2. Comma-separated port declarations were invisible

`_PORT_RE` required a single name immediately before `;`, so `wire o2, o1, o0;`
matched *nothing at all* and the whole statement was skipped. Those signals did
not exist as far as the adapter was concerned, and every downstream stage
compared against zeros for them.

- **60 drivers** across the two frontends gain at least one signal.
- **0 regressions**: no signal the old pattern found is lost, and no width
  changes. Verified by differencing both patterns over all 312 driver records.
- `vector0` went from 1 recovered expectation out of 7 to **7 of 7**.

---

## 3. `recover_expectations` returned *wrong* expectations, silently

The fast single-pass recovery attributes a reported failure to a position by
relabelling each event with its index and reading the labels back. That only
works if `scenario` is an **argument** of the driver's `$fdisplay`.

Many drivers instead bake the label into the format string —
`$fdisplay(file, "scenario: 1, a = %d, out = %d", a, out)` — so every row renders
as `scenario: 1`, relabelling does nothing, and every position collapses onto
one.

The existing guard compared the failure **count** before and after relabelling.
When relabelling has no effect that count is trivially unchanged, so the guard
passed **vacuously** and wrong expectations were returned rather than none.

| Frontend | scenario controllable | **hard-coded** | unparsed |
|---|---:|---:|---:|
| CorrectBench | 146 | 4 | 6 |
| AutoBench | 69 | **66** | 21 |

Fixed by `scenario_controllable()` plus `_recover_positionwise()`, an O(n²)
fallback that replays the real prefix per position, guarded by a work budget.
`mux2to1` went from 5 of 7 positions disagreeing to **8 of 8 clean**.

---

## 4. `init_prefix` swallowed the entire driver trace

Only some templates mark observation points with a `[check]` prefix. Where no
event is marked, the old loop scanned for the first marked event, found none,
fell off the end, and returned **every event** as the initialisation prefix.

- **76 of 150** CorrectBench and **66 of 135** AutoBench drivers are unmarked.

Every shadow suite on those re-ran the whole original stimulus before its
witness. That inflated the reported shadow cost and, worse, made a warning
impossible to attribute to the witness rather than to the replayed original
trace. Where the checker observes every row, the first observation point is row 0
and the prefix is empty.

---

## 5. Stateless checkers were rejected for the wrong reason

45 of 156 AutoBench checkers expose no `GoldenDUT`: `check_dut` loops over rows
and compares each against a helper, carrying nothing between rows. `StateModel`
rejected all 45 — the single largest addressable loss on that frontend — even
though structurally these are the *easiest* checkers, not the hardest.

`StatelessModel` adjudicates them by running the frontend's own `check_dut` over
a rendered one-row TBout. The checker is still executed verbatim.

**Statelessness is verified, not assumed.** `validate_stateless` requires that
`check_dut` flag exactly the rows it flags when each row is presented alone. A
checker that accumulates across the loop fails and is rejected as before. The
positional form of that check costs O(n²) renderings; above 64 events it falls
back to an aggregate count, and **the reason string names which level was
applied**, so the weaker check is never mistaken for the stronger one.

`build_model` picks the model from the **checker's shape read out of the
artefact**, never from the frontend's name — which is what lets a ConfiBench
transfer run with no code change.

---

## 6. Local model-validation yield (funnel stages 2–8)

Pure Python, no simulator, so measured locally over all 156 tasks.

| | CorrectBench | AutoBench |
|---|---:|---:|
| **Models validated (v3)** | **134** | **114** (56 stateful + 58 stateless) |
| Models validated (v2 run) | 108 | 52 |
| driver unparsed | 6 | 21 |
| expectations unrecoverable | 10 | 10 |
| model rejected | 6 | 11 |

AutoBench more than doubles. That is the combined effect of defects 2–5: the
stateless model supplies most of it, but it only helps because the port and
scenario-attribution fixes let those tasks recover expectations at all.

The v2 figures are after the candidate-family filter and the v3 figures are not,
so these are indicative rather than exactly paired; the v3 Kaggle funnel is the
paired comparison.

The rejections are worth reading as evidence that the gates still bite. On
AutoBench, `mt2015_q4` is rejected with *"not stateless: 0 failure(s) in context
vs 7 judged one row at a time"* — a checker that does accumulate across the loop,
caught by the verification rather than assumed away. Nine stateful models are
rejected for direct-drive disagreement, exactly as before.

A repeat of the CorrectBench validation after the `verdict()` scratch-directory
optimisation returned **134 again, unchanged**, confirming that change is a pure
speedup.

---

## 7. Baseline-aware witness selection

A witness is only worth solver time if it separates designs Channel 1 does *not*
already separate. `channel1_accepts()` asks the frozen suite for its verdict on
each candidate (Golden is never consulted — this is the generator's own verdict
on candidate RTL, available at generation time exactly as at deployment), and
`rank_pairs()` orders cross-family pairs:

| tier | meaning |
|---:|---|
| 0 | both accepted by Channel 1 — the blind spot the channel exists to cover |
| 1 | one accepted, one rejected |
| 2 | neither accepted — both already caught |
| 3 | unknown (did not run) |

Passing `accepts=None` restores the original fixed order, which is the ablation
arm. This targets the funnel's largest single loss: **80 tasks** (54 + 26) where
BMC found no disagreement within budget.

---

## 8. Assertion-level retention instead of suite-level rejection

Rejecting a whole suite over one untranslatable point throws away every other
assertion and the stimulus that reached them. `repair_tests()` keeps the sound
part, and the repair differs by checker shape **because soundness differs**:

- **stateless → mask.** The offending step still drives its stimulus and still
  costs a period, so the DUT advances identically; it is simply not printed, so
  the checker never judges it.
- **stateful → truncate.** A stateful checker advances once per *printed* row, so
  masking would cost it a clock and desynchronise every later expectation.
  Truncation preserves the stimulus prefix and the checker's history exactly.

Verified on real artefacts: `mux2to1` (stateless) keeps 5 of 6 assertion points;
`fsm1s` and `count1to10` (stateful) truncate, preserve their prefixes, and
**re-audit clean**.

---

## 9. The arms, and what each one isolates

All arms share tasks, candidate pool and solver budget
(`--bounds 4,8,16,32 --timeout 60 --max-pairs 4`).

| arm | configuration | isolates |
|---|---|---|
| `control` | Case-A gate, fixed order, no repair | the v2 method, on the fixed adapter |
| `improved` | translation gate, baseline-aware, repair | the full v3 change |
| `fixedorder` | translation gate, fixed order, repair | what pair ordering alone contributes |
| `random` | random stimulus matched test-for-test to `improved` | what the *formal search* contributes |

**The adapter fixes (defects 2–5) apply to every arm, including `control`.** They
are corrections to defects, not method choices, so no arm gets an unfair
advantage — but it also means `control` does **not** reproduce the published v2
suite counts. Attribution is therefore three-way:

- v2 record → v3 `control` = the adapter defects,
- v3 `control` → v3 `improved` = the gate, ordering and repair,
- v3 `improved` → `fixedorder` / `random` = ordering and formal search separately.

The v2 artefacts are preserved untouched in
`kaggle_runs/safe_full_v2/` and are not overwritten.

---

## 10. Scoring: one execution path, nothing filtered

`reconcile_eval.py` replaces the earlier side-by-side of published numbers and
our own. Every arm runs through the same `execute()`, on the same artefacts, over
the same mutant ids, and every `(task, design, arm)` triple gets one outcome from
a closed taxonomy: `PASS, FAIL, COMPILE_ERROR, TIMEOUT, NO_OUTPUT, CHECKER_ERROR,
SETUP_ERROR, MISSING_ARTIFACT`.

- `literal` (the frontend's own bytes) and `primary` (our Channel 1) are the same
  bytes by construction, so they **must** agree; every divergence is reported as
  a defect in our packaging rather than absorbed.
- `combined` is `V_aug(D) = V₁(D) ∧ ¬ShadowAlarm(D)`. A shadow alarm on Golden
  costs the arm its Eval1, and an alarm on an officially-accepted mutant costs it
  agreement. **False alarms are paid for here, not hidden.**
- Three scopes are always printed — `requested` (156), `available`, `complete` —
  and the denominator is the scope size, so a row we cannot score counts as a
  failure rather than vanishing.

Results are cached on the sha256 of `(driver, design, checker)`; since Channel 1
is byte-identical across arms it is simulated once, not once per arm. The key is
full content, so caching cannot change a verdict.

---

## 11. What is still open

- Whether the new gate raises **detection** or raises **false alarms** is not yet
  known. Eight suites that Case A discarded may be genuine catches or broken
  translations, and only the combined-verdict measurement decides it. It will be
  reported either way.
- **Async resets are modelled as synchronous.** `design_from_parse` hardcodes
  `reset_sync=True` even for ports `guess_reset` identifies by an async name.

  | | CorrectBench | AutoBench |
  |---|---:|---:|
  | no reset port identified (driven as a free input) | 102 | 89 |
  | sync-named reset | 34 | 32 |
  | **async-named reset, modelled as sync** | **14** | **14** |

  This is a **completeness** defect, not a soundness one, and the distinction is
  what makes it safe to defer. A wrong miter can only cause us to miss a
  disagreement or to find one that does not really separate the pair; it cannot
  corrupt a shipped test, because the expected value at every point comes from
  the frozen checker replaying the witness, never from the miter. The emitted
  driver also changes inputs only on `#10` boundaries with the clock toggling
  every `#5`, so reset transitions align with clock edges regardless.

  Suggestively, the three slowest BMC tasks in the v2 run — `history_shift`
  (243 s), `lemmings2` (222 s), `fsm3s` (215 s) — are all in the async group.
  Whether fixing the model converts that solver time into witnesses is exactly
  what the v3 funnel's stage-10 numbers will show, so it is deferred until then
  rather than guessed at.

  `guess_reset` also missed the name `aresetn` (2 tasks); added. Every other
  reset-like input name in the 191 "no reset identified" tasks is correctly left
  as a free input, which is the conservative direction — the solver may drive it
  any way it likes.
- ConfiBench transfer is pending the artefact download; the method is frozen
  first, as agreed.
