# Round9 independent review

Pending one independent offline review of R9-A..D: b5cf9d7, 6324697,
8f1e542 and the R9-D guard/readiness commit. Read PROTOCOL.md and paper.txt's
MAE/per-unit definitions. Fourteen synthetic tests pass in `unshare -Urn`.
No new label analysis, diagnostic execution, paid call or validation access.

Focus: one physical mass vector across all targets; full84 and fixed4 failures;
all retained-eight patterns; exact feasible dual certificate and conservative
numerical interpretation; fixed ASA Exact membership versus coding upper bound;
post-completion reference gate, private witnesses and public aggregate boundary.

Reviewer edits only this file; no real labels/images/keys, no paid API. Record
all findings once, P1/P2/P3 and file:line evidence. No repeat formal review.

## Independent review — 2026-11-03

Scope: complete diffs of b5cf9d7, 6324697, 8f1e542 and e1b763e,
plus directly used scorer, source-pin, artifact-store and gate implementations.
No implementation conversation was consulted. Only this review is retained as
a workspace change. No real per-record labels, images or credentials were read;
no API, real diagnostic or guarded diagnostic was run.

Paper evidence: `/home/lelouch/Documents/Codex/DietAI24_Claude_Handoff_20261023/workspace/work/paper/paper.txt`:
242–259 describes nutrient MAE; 324–326 and 348–350 define per-dish MAE and
per-unit normalization by the average reference amount. The common-mass LP,
retained-eight allowance, exact dual checks, reference-informed ASA option
oracle, freeze and isolation gates are new engineering/diagnostic protocol,
not a procedure or a predictive result claimed by the paper.

### Item decisions

- **R9-A — approved.** `PROTOCOL.md:11–46,50–77` preserves full84/fixed4,
  explicitly registers reference use and the optimistic representation, and
  separates fixed ASA Exact membership from recognition upper bounds and
  future prediction. Its metric definition agrees with paper.txt:324,348.
- **R9-B — approved, with P3 R-R9-B-1 below.** `joint_lp.py:54–104` shares
  each nonnegative physical mass across all five coordinates and retains fixed
  fallback vectors; `:20–35` matches `_stats` arithmetic
  (`src/opt_metrics.py:139–158`, paper.txt:324,348). `:38–51` covers the strict
  pattern and all 45 retained-eight subsets by effective-cap deduplication.
  `:107–142` repairs and verifies every dual column over exact binary-float
  rationals, rounds reported lower bounds down and uses a strict margin;
  `:145–200` rescoring, residual checks and universal-negative classification
  are conservative for the represented numerical LP. No marginal/support
  bound is passed off as a common witness.
- **R9-C — changes requested.** `run_diagnostic.py:85–139` has the intended
  label timing and complete-N seal/follower/replay prerequisites; `:142–195`
  retains 84/four failures and fixed ten ASA Exact rows, computes ONE legal
  five-vector per Exact row, and reports candidate/top-three/primary counts,
  groups and the 15/99 guard separately. `:43–56` correctly expresses the
  preceding-bank two-code cover criterion. However R-R9-C-1 through C-3 below
  leave source/runtime and baseline-statistics evidence incomplete.
- **R9-D — changes requested.** `guarded_run.py:80–97` audits the aggregate
  before export, while `run_diagnostic.py:239–243` uses the private sealed
  ArtifactStore for witnesses. The guard is not yet sufficient for its declared
  isolation claim; fix R-R9-D-1 and D-2 before labels/execution.

### Required findings

1. **R-R9-C-1 — P2, changes requested: freeze the actual pre-label gate helper.**
   `run_diagnostic.py:26,88` executes `require_scored` imported from
   `round7/tools/diagnose_completed_m.py`, but `:59–62` does not hash that file.
   N's transitive pins do not repair this: `round8/src/context_n.py:35–44`
   incorporates `round7/src/context_m.py` pins, whose `:105–112` includes src
   files and artifacts, not this tools helper. A helper change can therefore
   change follower/score gating without invalidating either freeze. Include
   every executed diagnostic dependency in the reviewed freeze; add a synthetic
   mutation case proving refusal before the label hook. Engineering requirement
   from PROTOCOL:11–12,54–55,73–74; no paper isolation claim is implied.

2. **R-R9-C-2 — P2, changes requested: cover the native solver runtime.**
   `run_diagnostic.py:65–78` hashes only `.py`/`.so` descendants of the numpy
   and scipy package directories. The installed wheel has a sibling
   `round9/runtime/packages/scipy.libs` directory; its loaded native libraries
   are outside that inventory. A recorded wheel digest does not verify that
   installed sibling files still equal the wheel. Include native dependency
   directories (and other executed runtime members) in the immutable runtime
   manifest or verify installed members against the wheel, and demonstrate
   refusal for a synthetic changed member. Enforce the registered Python3.10
   requirement explicitly rather than accepting any version merely because it
   matches a newly prepared freeze (`:77,207–208`). Engineering reproducibility
   requirement, PROTOCOL:50–55.

3. **R-R9-C-3 — P2, changes requested: independently recompute original N point statistics.**
   `run_diagnostic.py:118–121` establishes only equality of score/checkpoint
   JSON and service proof; the scoring JSON itself is not one of the sealed
   prediction records. `:209–216` immediately computes new oracle statistics,
   without rebuilding the original N full84 and ASA fixed-Exact statistics
   from sealed predictions and bound labels. Two mutually consistent stale or
   altered score files can therefore pass. After the allowed label gate, before
   any oracle solve, recompute original MAE/reference mean/per-unit, membership,
   n and pass flags using the frozen scorer and compare to saved results;
   include both N profiles where their scoring is claimed as verified. Add a
   synthetic case where both score copies agree but a point statistic is wrong.
   This is audit evidence for the completed-N premise, not rerunning inference.
   Metric basis: paper.txt:324,348; engineering gate: PROTOCOL:11–12.

4. **R-R9-D-1 — P2, changes requested: enforce network isolation at the executable boundary.**
   `guarded_run.py:25–76` never verifies a network namespace or absence of
   external interfaces/routes; patching Python socket constructors is not the
   registered network namespace boundary (native code or subprocesses bypass
   it). `run_diagnostic.py:247–251` also exposes an executable entrypoint that
   bypasses the read/write/Provider guard. Provide a single supported guarded
   entrypoint which refuses before labels outside verified network isolation;
   prevent the direct runner from silently satisfying the execution contract.
   Synthetic refusal tests must not perform network traffic. This is
   PROTOCOL:12,74 engineering isolation, not a paper requirement.

5. **R-R9-D-2 — P2, changes requested: use an explicit readable-input boundary.**
   `guarded_run.py:44–59` defaults reads to allowed and restricts validation
   paths only under this exact `BASE/data`; arbitrary JSON/JSONL outside it,
   historical run copies or credentials with other names remain readable.
   No guard flag tracks such accesses. Synthetic in-memory probe: with
   diagnostic.run and persistence mocked, opening the non-existent path
   `/tmp/synthetic-validation-labels.json` through a mocked underlying stream
   succeeds, and guard reports `forbidden_opens=0`. No real file was opened.
   Deny reads outside reviewed source/runtime and explicit frozen scientific
   inputs; keep the development-label exception gated. Add negative cases for
   out-of-root label/credential copies, pre-gate labels and images. Also cover
   filesystem mutations such as rename/unlink/link if claiming a general write
   boundary, because `:63–73` intercepts only opens. This is PROTOCOL:11–12,74
   engineering isolation. The current source does not itself intentionally
   open validation, but the claimed guard does not enforce that invariant.

### Suggestion

- **R-R9-B-1 — P3, approved with suggestion.** `joint_lp.py:187–189` stops
  immediately when the initial strict solve rescored witness passes eight or
  nine checks. PROTOCOL:24–28 instead says to enumerate retained-eight patterns
  if that witness does not pass all ten. Both establish the requested existence
  result, so this does not invalidate feasibility; align the stopping rule or
  explicitly register this harmless early-stop deviation before freeze.

### Validation and disposition

`unshare -Urn .venv/bin/python -B -m unittest discover -s
optimization_sol_20261102/mae_v2/round9 -p 'test_*.py' -v`: **14/14 passed**.
Additional guard probe used only mocks and a synthetic in-memory stream.
These tests do not verify real cohorts, stored N scores, API service history,
installed runtime integrity or real execution isolation. No P1 found; five P2
and one P3 recorded. **Do not freeze or execute R9 until the P2 findings are
fixed and coordinator offline checks confirm them.** No second formal review
is requested; retain each finding ID in its isolated fix commit and record the
implementation response here as required by AGENTS.md.

## Implementation response and coordinator evidence

- R-R9-C-1 fixed9f3287d: executed pre-label helper is a source pin; a
  synthetic mutation refuses before the label hook.
- R-R9-C-2 fixed29ed828: all non-bytecode package members and sibling
  native-library members are hashed, including `.so.3`; Python3.10 is explicit.
  Synthetic native-member mutation and unsupported-Python negatives pass.
- R-R9-C-3 fixed333cc5c: both frozen N profiles are independently rescored
  with original scorer, zero bootstrap, before any bound. Point statistics,
  population/membership aggregates, flags and tolerance must exactly reproduce.
  A synthetic mutually consistent but incorrect saved statistic is rejected.
- R-R9-D-1 fixed6dd4fd7: supported entrypoint checks loopback-only interfaces
  and no external v4/v6 routes before inputs and again inside installed guards.
  Direct runner refuses. Synthetic interface/route negatives use no traffic.
- R-R9-D-2 fixedfdd4362: explicit frozen readable paths/runtime roots replace
  default allow. External copied labels/credentials, pre-gate references and
  images are rejected; rename/link/unlink and related mutations are checked
  before underlying calls. Synthetic negative evidence passes.
- R-R9-B-1 resolved1b43ef9 before freeze: protocol expressly permits a single
  strict-objective witness that already passes8/10 to end the existence test.
  Remaining failed checks still appear; this is not strict10/10 success.

Coordinator ran22/22 synthetic tests in `unshare -Urn` after all fixes.
This confirms offline regression/negative evidence, not a second formal review
or real-data feasibility result. No P1/P2 remains; items R9-A..D approved/fixed.
The original single independent review and its limitations remain above.
