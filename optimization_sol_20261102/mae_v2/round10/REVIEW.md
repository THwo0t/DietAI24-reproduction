# O one-time independent review

Pending review of O-A..F through the O-F readiness commit. Major implementation
commits:48055f2,0647d79,858d07a,75c26af,cefe89a,041da88,966fff9.
Review the complete round10 source and protocol, not implementation messages.

38 unique synthetic tests pass in `unshare -Urn`; the complete artificial
coding→offline adapter→whole/conditional predictions→seal→zero-Provider replay
uses MockTransport only. Real guarded preparation/import/preflight touched
183 existing development images and3360 registered official embedding successes,
with0 query-label,key,validation,Provider/network/API access. No O paid request,
development accuracy result or validation run exists.

Paper: /home/lelouch/Documents/Codex/DietAI24_Claude_Handoff_20261023/workspace/work/paper/paper.txt.
Relevant lines95–104 (portion classification),172–186 (standard first/unit
adjustment),324/348 (MAE/reference-mean normalization). The source code's mean
over alternate-code densities, Sol substitution, conditional task adapter,
calibration and current populations are disclosed deviations/extensions.

Only edit this REVIEW.md. No real labels/images/credentials, no paid API or
actual launch/adapter/scoring run. Offline synthetic tests and source-only
review are permitted. List all findings once, P1/P2/P3 with numbered IDs and
file:line evidence; P1/P2 must be fixed in isolated cited commits. Root remains
the implementation writer; coordinator confirms offline fixes, no formal re-review.

Focus: common algorithm, mass counted once, frozen identities before code-only
ASA role, Exact failures retained, all84 N5 including fallback; actual parser
repair proof, both credential routes, durable unknown/resume semantics,
explicit import provenance and exact task reconstruction; OOF fold boundaries
and legal-option calibration; all20 checks, strict/relaxed/recognition guards;
public export has no per-record labels/weights/IDs; real launcher/follower must
not duplicate requests or reopen validation.

## Independent review — 2026-11-04 — changes requested

Reviewed O-A..F, commits `48055f2..9315b0d` (including O-A itself), against the
source and preregistered protocol. This is the one formal review, not a review
of implementation conversations. No real per-sample labels, research images,
credentials or historical prediction contents were opened. No paid API,
actual runner/adapter/launcher/scoring entrypoint or validation was executed.
The review does not establish service compatibility or scientific improvement.

Validation: the explicitly allowed network-disabled command
`unshare -Urn .venv/bin/python -B -m unittest discover -s optimization_sol_20261102/mae_v2/round10 -p 'test_*.py' -v`
passed all 38 synthetic tests (0.723 seconds). Tests exercise MockTransport,
actual Pipeline task reconstruction/parser repairs, separate credential routes,
recovery, sealed coding→conditional→records, and zero-Provider replay. This
result does not substitute for the outstanding production run.

### Findings (complete one-time list)

**R-O-1 — P2 — Keep main repair provenance independent of the conditional task.**
Changes requested. `round10/records_o.py:71` ORs a successful conditional repair
into the top-level `repair_used`, while retaining the main-only
`native_complete`, `fallback` and `main_repair_used` from lines 35–43.
`src/opt_metrics.py:166–179` then uses that merged flag to calculate the ASA
main/E2E `repair_success_n` and rate. A native main result plus a repaired
conditional result is therefore counted both as main native and main repaired;
conversely a failed main result plus repaired conditional result is excluded
from that repair count by the unrelated main fallback flag. The separate
`conditional_success` section (`round10/scoring_o.py:55–59`) does not correct
this misleading main statistic. Engineering/protocol basis: PROTOCOL's
separate all99 E2E and Exact task, and its required native/repair/fallback
reporting; paper.txt:184–190 defines system success from valid estimates.
Keep the generic/main repair field main-only (or supply explicit main and
conditional provenance to the evaluator) and retain conditional provenance
only in its branch/explicit conditional statistic. Add synthetic assertions
for native main + repaired conditional, repaired main + native conditional,
and main fallback + conditional success. Numeric MAE is unaffected, so this
is P2 rather than a result-changing P1.

**R-O-2 — P3 — Document and test offline follower restart after partial completion.**
Suggestion. `round10/watch_o.py:36–47` refuses any existing phase log, including
when verify completed successfully but the follower died before score. A new
follower starts at verify and refuses that existing log; `launch_o.py:27–32`
correctly refuses a second launch. This fails safely and does not silently
rerun paid inference, but README.md:27–33 only gives general reconciliation
instructions. Document the precise safe manual verify/score continuation, or
make the follower recognize sealed verification/scoring receipts without
replacing logs. Cover death after verification and a failed offline phase.
Engineering basis: protocol's recoverable failure policy and immutable
completed stages. This does not block freezing once R-O-1 is fixed.

### Item dispositions and evidence

- **O-A approved.** PROTOCOL explicitly identifies the older ASA mechanism as
  the hypothesis and distinguishes its conditional subset from new O results;
  Sol, fixed five-fold assignment, conditional task and supervised OOF are
  disclosed extensions. Historical numerical claims were not independently
  re-scored because reading historical sample artifacts was outside scope.
- **O-B approved.** `src/opt_pipeline.py:247–301,393–437` enforces flat disjoint
  region ownership, one ASA item, dense12+lexical12/RRF60/cap32 and bounded
  alternate codes. `round10/source_portions.py:43–139` implements standard
  exact grams, explicit no-fit adjustment, canonical-unit counts, direct grams
  only absent eligible options/units, and complete-image quantity contracts.
  `source_portions.py:77–97` averages selected identities and counts physical
  mass once, matching `code/nutrient_estimate_mix.py:66–80`. The paper supports
  standard-first/adjust-only-if-no-fit (paper.txt:172–186), but not an explicit
  alternate-density mean; the protocol correctly attributes that to source.
- **O-C changes requested: R-O-1.** Otherwise `run_o.py:86–114`,
  `stores_o.py:68–90`, `adapter_o.py:22–38`, and
  `conditional_o.py:8–35` require the complete coding seal before projecting
  only true code/full catalogue. No current true weight, nutrients, selected
  option, bin or filename is passed into the conditional visual task.
  `records_o.py:49–70` retains Exact failures using a legal median option and
  preserves the main vector. The conditional continuous-grams interface is
  a disclosed extension of paper.txt:95–104's multiclass formulation.
- **O-D approved.** `service_o.py:24–96,137–228,254–352` binds fixed role slots,
  8616 maximum slots/three reservations per exact payload, persistent unknown
  reservations, raw outcome/anchor/cache recovery, and no reservation after
  success/fatal state. `imports_o.py:12–113` explicitly imports verified old
  successes, blocks failed/unknown old states, and checks per-use provenance.
  `runtime_o.py:14–72` uses separate chat/embedding routes and keys, sanitizes
  persisted bodies, and stops on fatal/model failures. `gate_o.py:17–153`
  reconstructs actual Pipeline stages/prior answers and actual parser failure;
  it is not just a self-declared task whitelist. `engine_o.py:27–75` and
  `stores_o.py:28–65` bind response replay and scientific/service seals.
- **O-E changes requested: R-O-1; R-O-2 optional.**
  `run_o.py:114–164` keeps complete-image fallbacks and requires replay before
  score. `scoring_o.py:10–63` and `src/metrics_v2.py:268–438` implement
  other-fold-only fitting, five eligible training groups, one shared N5 mass
  factor, continuous ASA scaling before legal projection, and strict
  worst-ratio improvement/no lost passes. `src/opt_metrics.py:139–158,179–226`
  uses MAE/reference mean on the same population (paper.txt:324,348), retains
  all N5 failures, separates ASA E2E/Exact, and exposes complete subsets.
  `round7/src/scoring_m.py:36–73` supplies all20 checks, strict and relaxed
  decisions, five target pairs, 15%/five-group guard and separate18% target.
  `scoring_o.py:66–71` removes per-row fitting IDs from the public aggregate;
  it exports no prediction rows or real per-row labels/weights. Launcher and
  follower fail closed and never automatically restart paid inference.
- **O-F changes requested only for R-O-1's missing negative assertions.**
  The 38 existing synthetic tests pass. Freeze, real service compatibility,
  predictive accuracy, and independent acceptance remain untested/pending.

No P1 finding. One mandatory P2 finding and one optional P3 suggestion.
Resolve P1/P2 in isolated English commits citing the review ID, record the
handling below, and have the coordinating conversation confirm offline
negative-path evidence. Do not conduct a second formal independent review.
Do not mark this review approved or open actual O until R-O-1 is handled.

## Coordinator handling — R-O-1 fixed

Removed the conditional-to-main `repair_used` mutation. Main/E2E provenance is
unchanged when attaching the independent conditional task; its repair flag
remains only `conditional_repair_used`. Added three synthetic integration
assertions through the actual record builder and metric evaluator: native main
with repaired conditional, repaired main with native conditional, and main
fallback with successful repaired conditional. They check the separate native,
repair, fallback and conditional counts as well as all unchanged main fields.

Coordinator offline negative evidence: these same three assertions against
the pre-fix `9315b0d` implementation catch two provenance failures, with no
test errors. The fixed implementation passes all41 unique synthetic tests in
`unshare -Urn`. No labels, real images, credentials, Provider or API were used
by this confirmation. Numeric predictions and scientific protocol are unchanged.
R-O-1 status: fixed. No second formal review was performed.

## Coordinator handling — R-O-2 documented and checked

README now gives the precise manual network-isolated verify→score continuation
after an offline follower interruption, preserving the original logs/receipts.
The follower remains fail-closed rather than automatically replacing a phase
log. Two synthetic tests cover a successful verify log left before score and
a failed verify phase: neither restarts a paid base, deletes evidence or reaches
score. Status: addressed by documentation and fail-stop regression assertions.
Coordinator confirmation: all43 unique synthetic tests pass in `unshare -Urn`;
both interruption assertions use a temporary synthetic completion and mocked
subprocess, with no actual runner, labels, images, credentials or API.
