# MAE v2 independent reviews

This file is the review ledger for the approved two-checkpoint workflow.
Reviewers receive repository evidence in an independent
context and make no paid calls. They edit only this file.

## Checkpoint one — ready for review (2026-11-02 UTC)

Scope: M2-1–M2-6, starting from historical baseline `4707add`, including
`7cb244f`, `e2dbeb4`, `24deb60`, `7d6375d`, `4c90763`, `ad19523`, and the
M2-6 commit containing this request. Nine bound core sources remained unchanged
through every paid stage. The finite registered development tree completed at
2026-11-02 16:25:15 UTC. No formal inference or scoring was opened.

Evidence: `evidence/development-summary.json`, private
`runs/development/{completion,selection,candidates,round2_decision}.json`, each
stage's sealed outputs, metrics and usage, and `analysis/diagnostics_v2.json`.
Final development selection is ASA24 retrieval-portion plus calibrated C for
Nutrition5k: 10/20 MAE checks pass; ASA24 Exact is 16/99 in nine groups. The
actual freeze gate was checked offline and rejects this result. The 200-image,
188-group Nutrition5k validation cohort remains sealed.

Offline evidence: 168 core tests before inference; 237 current research and
delivery tests plus 37 authoring tests, all passing. Source/test hashes and
logs are in `evidence/implementation-final-source-manifest.json` and the paired
test summaries. No tests call paid APIs. Review should distinguish the bound
research implementation from the still-uncommitted M2-9 presentation tools.

Please especially examine grouped cross-validation, calibration and candidate
selection, conditional ASA24 denominators, bootstrap boundary behavior,
strict failure accounting, provider routing/resumption, linkage/exposure
isolation and the decision to withhold validation. The post-selection common
Exact and reference-weight diagnostics do not alter selection or acceptance.

## Checkpoint one — independent review (2026-11-03 Singapore)

Reviewed snapshot: `4707add..25088ec`, restricted to `mae_v2`. This is the single
checkpoint-one review. The reviewer read repository evidence and the paper,
not implementation conversations, and changed only this ledger. Uncommitted
M2-9 report, rendering, packaging and Mac-delivery files are outside this review.
All paths below are relative to `optimization_sol_20261102/mae_v2` unless stated
otherwise. `paper.txt` is the two-column extraction specified by the root
`CHECKLIST.md:31`:
`/home/lelouch/Documents/Codex/DietAI24_Claude_Handoff_20261023/workspace/work/paper/paper.txt`.

**Overall: changes requested — four P2 findings, no P1 finding, one optional P3
suggestion.** The recorded development failure and decision to keep validation
closed are approved. Approval of that conclusion does not mean the executed
method exactly matches every preregistered detail. Fixes must preserve the
existing raw responses, source bindings, cohort freezes and as-run metrics.
This review does not authorize another paid candidate, a replacement run,
validation inference, or changing historical artifacts to look conformant.

| Item | Decision | Scope |
|---|---|---|
| M2-1 | approved | Fixed thresholds, conditional population limits and finite experiment registration |
| M2-2 | changes requested | Linkage/exposure separation accepted within the verification scope; ASA fold rule mismatch R-M2-2-1 |
| M2-3 | changes requested | Leaf accounting and bounded A–E dependencies accepted; crop and candidate-context deviations R-M2-3-1/2 |
| M2-4 | changes requested | Actual point estimates, fitting and selection accepted; bootstrap boundary R-M2-4-1 |
| M2-5 | approved | Actual routing, retries, seals and validation gate; optional raw-response retention R-M2-5-1 |
| M2-6 | approved | As-run 10/20 failure, finite executed candidate set and withholding validation; carry the deviations below into the final account |

### Required findings

**R-M2-2-1 [changes requested] — P2: ASA24 retains the old folds while the
protocol registers the v2 seed for group-to-fold assignment.**
`PROTOCOL.md:52-54` retains the ASA connected groups and then specifies
`dietai24-mae-v2-20261102`, SHA-256 ordering and index modulo five for folds.
`src/cohorts_v2.py:279-283,494` applies that rule to N5, but `:586-592` copies
ASA rows, including their existing fold, unchanged. `evidence/M2-2_cohorts.md:19-20`
explicitly describes retaining the established ASA folds; the protocol does not
register that exception. Comparing the active dev manifest with `five_folds`
finds **17/23 ASA groups, containing 69/99 images**, assigned differently from
the stated v2 seed; N5 has zero mismatches. A read-only recalculation using the
registered ASA folds changes fitted fold factors (including one to 1.047) but,
for these responses, changes **zero conditional prediction vectors** and none
of the ten ASA primary metrics. It therefore does not rescue or invalidate the
10/20 failure conclusion. Required: reconcile the as-run fold policy explicitly
and preserve its provenance; do not claim both retention of old folds and
application of the new seed. If emitting a protocol-conformant derived fold
analysis, give it separate hashes and rebuild fold-dependent parameters offline,
retaining the original freeze/results. Add a check covering both datasets, not
only N5. Paper basis: `paper.txt:230-237` describes related ASA portion sizes and
N5 sampling; `:298-307` supplies the reproducibility context. The exact five-fold
seed is a project rule, not a claim made by the paper.

**R-M2-3-1 [changes requested] — P2: B's actual crop priority contains additional
unregistered tie-breakers that change which regions are supplied.**
`PROTOCOL.md:88-91` specifies uncertain identity, mixed region, other regions,
then stable parent ID. `src/pipeline_v2.py:247-254` inserts protein-family, sauce
and bounding-box area ahead of parent ID; `:261` takes the first four. This is
not just an unused branch: across the 84 saved B identities, 14 layouts have
more than four parents, **10 choose a different crop set**, and **40 have a
different ordered crop list** under the registered ordering. For example,
`runs/development/B/identities/61bdd697bf5a1b2228af3822.json` stores
`p1,p5,p6,p4`, whereas the registered ordering gives `p1,p5,p6,p2`.
Required: record this execution deviation and its counts in the final evidence;
align the future implementation with the stated ordering and add a synthetic
five-parent regression that makes the membership difference observable.
Preserve B's original responses and label them as produced by the old ordering;
changing code is not grounds to rerun B or to relabel existing B as corrected.
Paper basis: `paper.txt:237-240` specifies the original 256×256/no-extra-processing
baseline. Same-image crops and their ordering are declared v2 engineering
changes, whose actual implementation must agree with `PROTOCOL.md`.

**R-M2-3-2 [changes requested] — P2: the candidate prompt omits the registered
official category field.**
`PROTOCOL.md:82-84` includes official description/category and per-100-g density.
All **5,624** entries in the supplied generic catalog have a nonempty category,
but `src/pipeline_v2.py:297-304` emits only code, description, density and inferred
relationship hints. Passing category into `relation_hints` does not transmit
the official category itself. Both ordinary selection (`:325-337`) and D review
(`:564-567`) use this reduced context. Required: either provide the official
category explicitly in the prospective candidate contract or explicitly narrow
the method description to the executed context; in either case document the
as-run omission and test the actual candidate object supplied to a prompt.
Do not rewrite saved requests/results or claim the missing field was present.
Paper basis: `paper.txt:151-177` grounds retrieval/selection in official FNDDS
descriptions; `:198-211,256-259` explains food-code categories. The explicit extra
category field is the v2 protocol's requirement, not an original paper API schema.

**R-M2-4-1 [changes requested] — P2: the main metric bootstrap reports an interval
with only one association group.**
`PROTOCOL.md:146-149` says fewer than two groups yields no interval.
`src/opt_metrics.py:233-265` instead resamples the single group repeatedly, and
`:285-286` exposes the resulting degenerate interval. A synthetic one-row,
one-group N5 population with absolute error 10 yields `group_count=1`, a
95% `weight.mae` interval `[10,10]`, and 100 valid replicates, rather than an
undefined interval. The post-selection helpers already handle this boundary
(`src/diagnostics_v2.py:45-47,110-115`), but the primary scoring path does not.
Required: make the main bootstrap return explicit absent intervals/reason for
zero or one group, with focused negative tests; keep point estimates intact.
The current 23-group ASA/78-group N5 result is not affected by this boundary.
Paper basis: `paper.txt:249-254,324-325,348-349` supplies MAE and normalization;
`:298-307` discusses statistical reproducibility. Group bootstrap and this
minimum-group rule are registered additions, not paper-mandated statistics.

### Accepted findings and evidence

**R-M2-1-1 [approved]: registration and metric interpretation.**
`analysis/paper_targets.json:19-23,34-38,49-53,64-68,79-83,104-108,119-123,134-138,149-153,164-168`
and `src/opt_metrics.py:24-28` retain all twenty limits at 1.3 times the paper
values. `src/opt_metrics.py:139-158` divides absolute MAE by the reference mean
of that same scored population and gates full-precision values.
`PROTOCOL.md:11-18` correctly separates ASA Exact-conditional estimation from
E2E and avoids asserting identical paper populations. The 15% floor is explicit,
and `evidence/development-summary.json:130-134` also discloses failure of the
former 18% floor. Paper evidence: Tables 1–2, `paper.txt:309-349`, and the metric
definition `:249-259`.

**R-M2-2-2 [approved, verification scope stated]: leakage components and sealed
development access.** The complete-universe graph implements the registered
Decimal mass, same-cafe, time-window, full-sequence adjacency, image-equality
and ambiguity rules (`src/cohorts_v2.py:126-168,191-257`). Exposure propagation,
retirement and replacement selection are explicit (`:476-523`), and the
development loader only accepts the development seal's permitted paths
(`:636-676`). Synthetic linkage/download tests pass, including noncandidate
bridges, 600/601-second boundaries, contradictory adjacency, exact pixels,
authorization and durable transfer limits. Independent recomputation from
neutral `data/freeze/final_source_snapshot.json` and `cohort_proposal.json`
confirms 200 proposed validation images in 188 groups (177 singletons, ten pairs,
one triple), with zero group intersection with historical exposure, the full
original dev100 closure, or quarantined components. The proposal hash agrees
with `validation_freeze.json`. This review did **not** reopen actual sealed
images or nutrient labels or rerun their hashing; those file-content checks
remain the preparation evidence in `evidence/M2-2_cohorts.md:114-139`.
Paper evidence: `paper.txt:207-219,235-240`; the 600-second component heuristic
and its independence limitations are correctly identified as project additions
in `PROTOCOL.md:64-65` and `evidence/M2-2_cohorts.md:38-66`.

**R-M2-3-3 [approved]: positive leaf accounting, scoped inputs and bounded
enhancements.** `src/pipeline_v2.py:106-153,307-323,387-411,414-473` enforces
stable unique parent/leaf IDs, a single candidate code per leaf, positive leaf
grams and parent aggregation without counting parent nutrients twice.
`src/legacy_adapter.py:81-120` supplies ASA true code/catalog only through the
conditional adapter, while image encoding removes filenames and metadata
(`src/opt_pipeline.py:99-114`). D preserves the base structure and leaf grams,
uses at most one new retrieval/selection, and rolls back the whole enhancement
on contract failure (`src/pipeline_v2.py:555-638`); E excludes unspecified and
ambiguous serving units and multiplies complete option descriptions
(`:640-728`). Real C raw/calibrated leaves and reaggregated nutrients match the
saved outputs. Paper evidence: `paper.txt:151-189` gives per-100-g multiplication,
food-item summation and legal portion mapping. Contract changes beyond the
paper are explicit in the protocol; the two prompt deviations above remain.

**R-M2-4-2 [approved]: actual OOF fitting, finite selection and complete scoring.**
Independent stdlib arithmetic reproduces every raw/retained candidate and the
final twenty metrics to within `1e-12`. Independent grid search reproduces all
ten OOF fits and both final fits: ASA full-development factor
`1.219 -> 1.1095`; C `0.895 -> 0.9475`. Calibration strictly improves the worst
ratio with no formerly passed check lost. ASA scales continuous grams and then
remaps a legal option; C scales leaves and reaggregates. All 45 raw-fold and ten
calibrated-fold parameter records have disjoint training/held-out IDs/groups;
all 168 example references avoid the target sample, group and fold.
Evidence: `src/metrics_v2.py:254-330,334-451`,
`src/legacy_adapter.py:123-154`, `runs/development/C/calibration-summary.json:964-968`,
`runs/development/asa-retrieval-portion/calibration-summary.json:1632-1636`.
The preserved ASA-fold discrepancy is separately identified in R-M2-2-1.

The actual N5 raw worst ratios are A 2.776434, B 2.947100, C 2.226100,
D 2.256867 and E 3.559596. Therefore C correctly uses A identities and remains
the first/second-round raw winner; D/E both bind raw C, their registered
nutrient/weight triggers are met, and no second-round new calibration is fitted.
C's 84 images have 338 usable standard-portion leaves out of 384. References
remain compared; final selection uses one method per dataset, not per sample or
nutrient (`src/study.py:457-527`; `runs/development/round2_decision.json:2-4`).
Failure/fallback rows remain in N5's 84-image denominator. ASA has Exact 16/99
in nine groups, with no more than three codes per image; 15 required hits pass,
18 do not (`runs/development/selection.json:1370-1379`). Paper evidence:
`paper.txt:200-228,249-254,324-325,348-349`; five-fold fitting, bounded selection
and fallback scoring are v2 protocol additions.

**R-M2-5-2 [approved]: current source/record binding, request accounting and
credential isolation.** All nine completed stage configurations bind the same
nine core source hashes, matching both current files and `25088ec`; the
870 retained raw records match their record/identity seals and prediction
copies. Model/config/catalog/vector-manifest and v2 upstream bindings agree
(`src/study.py:71-135`; for example `runs/development/C/run_config.json:9-29`).
Route selection is fixed, credentials are distinct and route-specific, shell
interpolation is disabled, redirects and proxy inheritance are disabled, and
response/log sanitization is tested with fictitious credentials
(`src/opt_provider.py:61-119,131-162,187-224`). No real credential was read by
this review; this is source plus synthetic boundary verification, not a claim
that every possible provider masking pattern has been tested.

Independent request/usage reconciliation finds 850 chat and 626 embedding
attempts, including two A ReadTimeouts followed by successful attempt 2
(`runs/development/A/requests.jsonl:523,540,574,590`). There are 1,474 unique
payloads, 1,476 durable reservations and 1,476 log rows, with no difference,
duplicate/sequence gap, namespace mismatch or attempt above 2. Every successful
chat reports `stop`, and every served model agrees. Prompt/completion tokens
are 7,816,290/543,024; 322,896 reasoning tokens are already included. Official
embedding tokens are 3,355; the summary reports the estimate $0.00043615 and
leaves third-party/combined cost unknown rather than substituting official chat
prices (`evidence/development-summary.json:11732-11888`). Actual credential
values and provider billing were not inspected. Paper evidence:
`paper.txt:155-160,303-306,518-527`; dual routes, nonzero temperature, token
limits and durable retry behavior are registered deviations/additions.

**R-M2-5-1 [changes requested, optional P3]: preserve sanitized partial response
text alongside its invalid status.** `src/opt_provider.py:207-223` replaces any
non-`stop` chat content with an empty string before caching, so an eventual
length-truncated answer's original sanitized text would be lost from the raw
evidence. Prefer storing that text and finish reason separately while still
feeding an explicitly invalid result into the one-repair contract. This is
optional for the completed run: it has zero successful responses with a
non-`stop` finish reason, so no observed evidence was lost by this branch.
Direct project basis: `PROTOCOL.md:134-141` requires raw/parsed provenance;
`paper.txt:303-306` supplies reproducibility context, not a raw-log schema.

**R-M2-6-1 [approved]: development failure, closed validation and post-selection
diagnostic boundary.** Final selected ASA retrieval-portion and calibrated C
pass 10/20 checks: ASA 10/10, N5 0/10. The N5 MAEs are 78.395714 g weight,
118.500201 kcal energy, 8.318445 g fat, 13.201030 g carbohydrate and 11.084974 g
protein; their normalized values also fail. The final selection, completion and
summary agree (`runs/development/selection.json:2293-2310`,
`runs/development/completion.json:2-7`,
`evidence/development-summary.json:432-480`). Calling the real `freeze` entrypoint
offline with sealed-manifest and credential access replaced by hard-fail guards
raises the twenty-metric gate error before either boundary is touched; neither
`runs/frozen/method.json` nor validation completion exists. The failure decision
therefore remains valid independently of the required reporting/contract fixes.

The common-Exact comparison retains only the same ten Exact rows/five groups,
without changing the registered 16-row ASA result. The reference-weight oracle
is explicitly post-selection, carries `not_a_model_or_acceptance_result`, and
does not feed `study.py` selection (`src/diagnostics_v2.py:76-141,144-220`;
`analysis/diagnostics_v2.json:3-14,411-418`). The N5 paired comparison resamples
whole groups in both arms and labels its interval as selected-development
evidence (`src/diagnostics_v2.py:36-73`). No inference feature or new candidate
is created by these diagnostics. Paper basis: `paper.txt:249-259,298-307`; the
oracle and common-Exact analyses are explanatory additions, not acceptance
scores or an identical-population replication claim.

### Reviewer verification record and disposition

- 168 committed core tests passed with networking disabled and a real
  sealed-path/credential-file read guard. An initial overbroad reviewer guard
  misclassified temporary-directory cleanup's relative `os.open` calls; after
  correcting that guard, the suite passed. Those guard-induced cleanup failures
  are not product findings.
- The 11 newly committed diagnostic tests passed separately with networking
  disabled. M2-9's uncommitted delivery/authoring tests were not accepted as part
  of this checkpoint's scope.
- Additional read-only probes covered the one-group bootstrap, deterministic
  ASA fold recomputation, actual B crop order/set, all candidate categories,
  neutral exposure-closure metadata, and the real failed-development freeze
  entrypoint. Independent arithmetic covered metrics, grid fitting, fold and
  example provenance, stage seals, current/committed source hashes, HTTP logs
  and persistent attempt accounting. The reviewer did not independently rerun
  every 10,000-draw interval or reopen historical v1 raw source files.
- Resolve R-M2-2-1, R-M2-3-1, R-M2-3-2 and R-M2-4-1 in isolated English commits
  citing their IDs; state handling of optional R-M2-5-1. Record fixes and offline
  confirmation here. There is no second checkpoint-one review. The development
  gate remains failed; subsequent reporting must preserve that conclusion,
  identify as-run deviations, and keep formal validation sealed.

## Checkpoint-one implementation responses

### R-M2-4-1 — fixed

The primary bootstrap now returns explicit null endpoints, zero performed/valid
replicates and `fewer_than_two_groups` for zero or one group. The requested draw
count is retained separately. Two-or-more-group behavior and point estimates
are unchanged. Thirty-five focused metric tests pass, including both dataset
boundaries. Offline development-only recalculation under the old and corrected
source produces an identical complete metric object, including all 10,000-draw
intervals, to the saved selection. Evidence: `evidence/R-M2-4-1.json`. No saved
run, freeze, response or protocol was rewritten, and no paid call was made.

### R-M2-3-2 — fixed by explicit as-run disclosure

The permitted disclosure resolution is adopted: the completed candidate prompt
contains code, official description, per-100-g density and inferred hints; the
official category is not an explicit prompt field. The catalog category only
feeds the internal lexical hint function. `evidence/R-M2-3-2.md` records this
deviation without amending the preregistration or changing the selected C
prompt. Two focused offline tests capture the selection and D review prompt
boundaries and verify this actual contract. No category-enhanced experiment is
claimed or run. The final report and handoff will carry the same disclosure.

### R-M2-2-1 — fixed by explicit as-run disclosure

The immutable protocol is retained. `AS_RUN_DEVIATIONS.md` distinguishes the
registered seed rule from the executed ASA archived folds. The separate
assignment audit confirms 17/23 ASA groups (69/99 rows) differ, while all 78 N5
groups (84 rows) conform. Twelve original artifact hashes remain unchanged;
the tool reads no labels, images or validation. Seven focused tests were
independently confirmed with networking disabled. This fix does not create
reselected predictions or claim a protocol-conformant rerun. Evidence:
`evidence/R-M2-2-1_fold_audit.json`.

### R-M2-3-1 — fixed prospectively and disclosed

Crop ranking now uses the registered exclusive uncertainty/mixed/other tiers
with parent ID as the only tie-breaker. The primary agent independently
confirmed all 32 pipeline tests offline. The read-only audit reports 10 crop
set and 40 order differences among 84 B layouts; original run trees and
selection hashes are unchanged. Selected C uses A identities without crops,
so its inference path is unaffected. The old B result remains explicitly
as-run, without a claim about the unexecuted corrected-B result. Evidence:
`evidence/R-M2-3-1.json`; disclosure: `AS_RUN_DEVIATIONS.md`.

### R-M2-5-1 — optional P3 deferred

No successful response in the completed run had a non-stop finish reason;
there is no observed partial-response loss. Retaining sanitized partial text
is a future provider improvement. The completed evidence and provider source
are preserved, with this limitation disclosed rather than claimed fixed.

### Checkpoint-one closure

All four required findings are fixed or resolved by the review's permitted
as-run disclosure. Primary-agent offline confirmations passed: metrics 35,
pipeline 32, fold audit 7, candidate context 2. No re-review or paid request
was performed. `evidence/review-one-completion.json` binds original and current
source maps and the unchanged artifacts. Only the prospective B crop ranking
and under-two-group bootstrap behavior differ in core source; selected C(A)
inference and complete saved metrics are unchanged. The compatibility bridge
permits an auditable portable demonstration, not reopening validation. The
20-metric development gate remains failed, so M2-8 remains unexecuted.

