# R9-A: Joint feasibility after rejected N

Registered before any new per-record label analysis. This is a zero-API,
development-only, reference-informed diagnostic, not a prediction method,
calibration, acceptance run or final report. N is immutable. Its complete
failure and project review were backed up at public commit
6e87de6110b745f8b0d99fabc9fc449be925f1fd before this registration.

## Scope and finite decisions

1. Verify N's complete 183-pair seal, scoring/follower, zero-Provider replay,
   source pins and full-population manifest before opening development labels.
   No images, credentials, validation records, provider or network access.
2. Nutrition5k primary bound retains all 84 records. The 80 successful N-density
   rows keep their actual per-leaf mean densities. Each leaf receives one free
   nonnegative mass, shared by weight and all four nutrients. Zero mass is an
   explicit optimistic relaxation of the original positive-mass contract. The
   four failures retain their exact frozen fallback five-vectors.
3. Minimize a common cap multiplier t by linear programming: absolute-error
   slack is bounded below by both signed errors; the mean slack for every
   retained target, normalized by its cap, is <=t. Per-unit uses the original
   scorer's MAE/reference mean on the same 84 rows. Both original caps enter
   each target's effective cap; no rounded decisions or MAPE.
4. First solve all ten checks. If the recomputed common witness does not pass
   at least eight, enumerate retained subsets of eight out of ten (45 subsets), in
   lexicographic order, deduplicating identical effective-cap vectors. Stop on
   the first shared witness passing at least eight actual checks. At most 46
   solves before deduplication per representation; no alternative objectives.
   This is a diagnostic for the user's <=2 failures allowance, not selection.
   Review suggestion R-R9-B-1 is resolved before freeze: an initial strict-objective
   witness already passing eight or nine actual checks may stop immediately;
   its remaining failed checks are explicitly reported, never called strict success.
5. If fixed-density feasibility has a verified numerical negative result,
   repeat the same finite procedure on frozen M0 per-leaf candidate densities.
   A physical leaf may distribute mass over its existing candidate codes;
   total physical mass is the sum once. No new food, retrieval, code or label
   enters a candidate bank. The same four N failures remain fixed. This is a
   more optimistic continuous-code cone, not N's deployed 1-3 equal-code mean.
   Skip this expansion if fixed identities already yield a witness, or if the
   first result is numerically indeterminate.
6. Do not repeat a broader failure-relaxed cone: the prior C true-mass/free-share
   diagnostic already supplies a joint witness for its own representation.
   Verify source/cohort containment before reusing that fact. Do not call its
   coordinatewise support bounds a joint optimum or its squared-loss solve an
   L1 optimum. If containment is not established, record it as unverified.
7. ASA24 retains N's fixed ten Exact rows, not an oracle-selected subset. Pick
   each row's legal option nearest to reference weight (deterministic existing
   option tie rule), then evaluate the resulting ONE five-vector per row.
   This explicitly reference-informed quantity witness is not inference.
   Report current 10/99 recognition and candidate/top-three optimistic upper
   bounds separately, including independent groups and the 15/99 guard.
   Top-three feasibility respects frozen leaf order and code deduplication:
   before the earliest truth-containing leaf, <=2 primary codes must cover all
   preceding leaf candidate banks. Primary hit upper bound uses the first leaf.

## Numerical and disclosure rules

Use Python3.10, existing NumPy1.26.4 and isolated SciPy1.15.3 HiGHS dual simplex;
record the wheel digest and source/input/runtime hashes. Do not change the old
project environment. Fix primal/dual tolerance1e-9, time limit60s per solve.
Unknown, nonfinite or unsuccessful solver status is indeterminate, not proof.

Rebuild all five predictions from each returned mass allocation and use the
existing scorer's full-precision arithmetic for every check. A passing witness
requires actual <= thresholds; no tolerance is added to acceptance. Numerical
negative claims require every unique retained-eight pattern to have a checked
dual lower bound >1+1e-6. Repair/check dual feasibility using exact rational
arithmetic over the actual binary-float LP coefficients; otherwise label the
negative result indeterminate. Report primal residual, nonnegativity, solver
objective, checked dual bound/gap and every attempted subset. A mathematical
oracle pass says nothing about whether Sol can learn those masses from images.

Keep per-record masses and references private. Public evidence contains only
aggregate scores, solver/certificate summaries, counts and semantic hashes.
Never export an oracle as a deployment configuration or run independent
validation on the strength of this diagnostic. Freeze this protocol and the
implementation after one independent offline review and fixes, then execute
once with label/network guards. No new report, embedding, paid request or data
download is part of R9. Next predictive mechanism must be separately registered
and tested freshly on both datasets using the existing development/training data.

Solver reference: https://docs.scipy.org/doc/scipy-1.15.3/reference/optimize.linprog-highs.html
