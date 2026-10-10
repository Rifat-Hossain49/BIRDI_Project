# Reference-accuracy pilot — results (development set, ConfiBench-4o)

Question: is an LLM-design reference accurate enough to *correct* ConfiBench's
checker and *add* assertions? 33 tasks (10 CMB, 23 SEQ), 522 sub-testbenches,
4,250 simulations on ConfiBench's own stimulus. Golden rows compared row by row.

## Pre-registered decision (two-family reference): NO-GO

| reference | CMB rows | SEQ rows |
|---|---|---|
| Qwen3.5-27B alone | precision 0.9448, coverage 0.985 | precision 0.9957, coverage 0.985 |
| 7-8B pool alone | precision 0.5421, coverage 0.542 | precision **0.0485**, coverage 0.818 |
| two families agree | precision 1.0000, coverage 0.292 | precision **0.9582**, coverage 0.039 |

Rule fixed beforehand: >= 0.99 on both CMB and SEQ. SEQ is 0.9582: **NO-GO.** The
small pool's sequential designs are almost all wrong (one early error propagates
through every later cycle), so requiring agreement with it discards 96% of
coverage and still admits 514 wrong rows.

## Exploratory: scenario level, strong family alone

Row precision flatters long sequential traces. A checker repair needs every row of
a scenario right:

| Qwen3.5-27B | coverage | scenario precision | wrong scenarios |
|---|---:|---:|---:|
| CMB, unanimous | 0.843 | 0.9628 | 35 |
| CMB, majority | 1.000 | 0.9526 | 53 |
| **SEQ, unanimous** | 0.635 | **0.6706** | 414 |
| **SEQ, majority** | 0.896 | **0.6588** | 605 |

185 SEQ sub-testbenches were skipped because fewer than 3 Qwen designs compiled —
the hardest tasks — so the true sequential figure is likely lower.

## Conclusion

On sequential circuits the best open model runnable on Kaggle hardware is a
correct reference for only about two scenarios in three, and unanimity among its
samples does not raise that (same-family errors are shared). Any pipeline that
uses it to correct or extend ConfiBench's sequential testbenches would break
correct designs far more often than it repairs wrong checkers.

This is the same limit reached by every earlier direction, now measured directly:
beating ConfiBench on sequential requires a reference **more reliable than
ConfiBench's own GPT-4o on exactly the circuits GPT-4o gets wrong**. With the
models available here, no such reference exists.
