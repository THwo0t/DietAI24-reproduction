# Full-project decision record after rejected N

Development only; not the final report. All original records are preserved.
Independent validation remains sealed; no final report or Mac-package refresh.
Use round7/PROJECT_REVIEW.md for the earlier full source/method retrospective.

## Complete result and task populations

Both N profiles completed all183 pairs (ASA99/23 groups, N584/78 groups),
sealed, passed zero-Provider replay and were scored before any posthoc diagnosis.
Both fail19/20 numerical checks: ASA9/10, N510/10. Only ASA absolute fat MAE
passes; no target passes both absolute and per-unit caps. Neither profile is
selected. Original1.3-times-paper limits and full-precision decisions are unchanged.

Five MAEs below are weight g / energy kcal / fat g / carbs g / protein g.

| Completed method/population | Five MAEs | Failed checks |
|---|---|---|
| M0 ASA conditional9 Exact/7 groups |30.416667 /36.308333 /.374681 /8.249944 /.707861 |4/10 |
| N-density ASA conditional10 Exact/6 groups |66.425 /75.8815 /1.2988825 /14.098615 /2.41109 |9/10 |
| N-units same10 Exact/6 groups |69.625 /90.3375 /1.8025375 /16.156225 /2.8552 |9/10 |
| M0 N5 all84 |82.988095 /126.693157 /8.628053 /14.582201 /11.228450 |10/10 |
| N-density N5 all84,4 fixed fallbacks |82.25 /128.639641 /8.647276 /14.679024 /11.110071 |10/10 |
| N-units N5 all84,same4 fallbacks |96.385655 /159.074402 /10.224339 /18.922410 /10.878692 |10/10 |

ASA recognition is10/99 (10.10%),6 independent Exact groups, below15-record
floor and original18-record target. Primary hits7/99, candidate recall19/99,
average final codes2.686869. More alternatives did not resolve the coding gap.
ASA all99 E2E also fails10/10 in each arm: N-density five MAEs64.971919 /
117.208907 /8.126256 /15.218978 /5.814530; N-units73.048788 /149.407948 /
9.319433 /17.093212 /5.923467. These are distinct from conditional option scores.

Full values, reference means, intervals, twenty checks, group/size strata,
median baselines and fallback populations are in development_checkpoint.json.
No samples were deleted or reanswered because of their measured error.

## What the paired mechanism checks establish

N-density preserves all99 ASA masses and all80 complete N5 masses exactly.
Its N5 weight improvement of0.738095g comes entirely from4 identity failures
using the frozen median vector (3 row errors improve,1 worsens). It is not
improved physical estimation. Code lists change on all80 successful N5 rows;
nutrition identity/density revaluation changes energy/fat/carbs/protein MAE by
+1.946485 /+.019222 /+.096823 /-.118378. This combined identity/density
intervention is not evidence that code averaging alone was isolated.

N-units shares exact identity/coding with N-density. On80 complete N5 pairs,
all weights change, no code list changes, mean predicted mass ratio is1.070605.
Whole-population MAE changes are+14.135655g,+30.434761kcal,+1.577064g fat,
+4.243385g carbs and-.231380g protein. Weight improves on34 rows and worsens
on46; carbs improves on27 and worsens on52. The intervention includes native
direct grams where units are absent; it is not a unit-only causal experiment.
The program verifies the per-leaf mass/density difference identities to about
2.3e-13, which does not imply an additive decomposition of absolute error.

ASA M0 and N-density share only8 Exact rows/6 groups, with equal per-row
absolute errors on all five targets. One M0-only and two N-only matched rows
change the own-Exact score. N-density and N-units share all10 Exact rows;
quantity changes worsen their five conditional MAEs by3.2g/14.456kcal/
.503655g/2.05761g/.44411g. Do not attribute different own-Exact populations to
paired estimation improvement.

Errors remain broad: largest10 N5 errors contribute28.9–41.6% across profiles
and targets, leaving most total error in the remaining74. N-density signed
biases are+7.869g,+27.683kcal,-.701g fat,+9.244g carbs,-2.813g protein;
N-units+32.400g,+64.525kcal,+1.215g fat,+13.724g carbs,-2.256g protein.
Both identity/density and mass/allocation remain unresolved. This does not
justify a universal rescaling or removal of a few exceptional images.

## Whole-project interpretation, including original workflow

Historical evidence remains scope-specific:

- The current-cohort plain/global adapted baseline already exists: all183 rows
  were exactly imported from completed Sol/zicc v1, not manufactured from a
  different N5 cohort. It uses free description,6 dense4 queries,global24 codes,
  single primary density and free-name N5 grams, not RawC parent/leaf hybrid32.
  It has ASA16 Exact/10 groups but7/10 numeric failures; N5 five MAEs109.369 /
  146.041 /8.756 /12.353 /15.116, all10 failing. Source: src/opt_pipeline.py:
  343–377,529–555; src/study.py:166–175,457–466; runs/development/baseline/metrics.json.
- The later v2 ASA retrieval/portion method achieved10/10 conditional checks
  on16 Exact/9 groups, while its all99 E2E remained poor. Its separate N5 C
  selection was78.396/118.500/8.318/13.201/11.085, all10 failing. Those two
  results are not evidence for a new shared M/N method.
- F direct nutrients, G examples, H/I ingredient catalog/checklist and CHI
  ensemble all failed N5. Raw J remains the best historical whole N5 profile:
  67.202/102.188/8.369/10.522/8.968. Its OOF calibration and K did not reach
  any N5 check; K worsened most MAEs. J/K used supervised galleries and lack
  newly executed common-method ASA evidence. They cannot be spliced into N.
- L region-atlas source was implemented but had no real preflight/annotation/
  paid result and is shelved. M and N ran both complete datasets and failed.
  M only collapsed8 N5 images; changing code selection and quantity also
  confounded that result. N isolates fixed shared upstream more clearly but
  does not correct RawC's existing representation and density limitations.

The original release averages multiple selected codes per physical food; the
paper describes standard portion classification, then unit adjustment when
none is suitable. N's always-continuous canonical-unit count is not the complete
published portion mechanism. Plain/global retrieval plus multi-code density
plus the full original portion mechanism has not been executed as one complete
current-cohort arm. That is a remaining source-compatibility gap, not proof
that restoring it would reach the target. Direct nutrients and the older E
unit experiment already provide negative evidence against simple alternatives.

ASA conditional task scope also matters. The original user protocol explicitly
permits an isolated adapter supplying the true food code and COMPLETE legal
option catalog after codes are frozen and the row is Exact; it forbids current
true weight/nutrients/selected option/size bin. legacy_adapter.py:113–119 uses
that task. M/N instead apply nearest legal options to label-free whole-serving
masses. Their failure does not falsify the less restrictive allowed conditional
task. Future methods may restore that adapter only when explicitly registered,
keeping new ASA99 E2E and recognition results separate and running both datasets.
Historical successful ASA numbers still cannot substitute for a new method.

## Engineering, service and next decision

One independent R8-G review found0P1/3P2, all fixed before freeze; independent
Sol coordination confirmed45 offline tests and the guarded183-input preflight.
N science remains frozen at e581d24372a4ad1f4d8baf5f0f26e1490242c949368a48cb5107c3165945011d,
with36 source/input pins unchanged. Six separate post-score diagnostic tests
bring the current suite to51; they are not accuracy evidence. The diagnostic
had one small-scope independent check,0P1/P2; its P3 gate negatives were added.

331 unique successful payloads,375 logical bound slots and333 transmissions
include2 HTTP502 errors, both recovered within original durable budgets; zero
unknown outcomes. No new embedding request or download. Reported chat usage:
1,591,364 prompt +103,913 completion =1,695,277 tokens. The47,386 reasoning
tokens are already included in completion. Third-party money remains unverified;
old imported work is separate. Model names match the requested Sol route.

Post-score diagnostic guard preserved14254 old M/N inference/preparation/service
files, counted10 label opens only after complete scoring, and prohibited image,
validation,key,Provider and network access. It performs no new bootstrap or
method selection. Aggregates are development_diagnostic.json; raw research
artifacts remain private. Public frozen-source backup568c411 is already verified.

Reject both N profiles; validation stays sealed. First safely back up this
complete failure and full-project review. Then preregister one zero-API
joint-feasibility diagnostic before any new label analysis: determine whether
fixed current identities and then a clearly optimistic relaxation of frozen
candidate densities admit ONE shared per-image mass allocation satisfying the
joint thresholds. Report current failure populations and separate optimistic
failure relaxation. Separate ASA fixed-Exact quantity feasibility from candidate
recognition upper bounds; never select easy Exact rows. This is a nondeployable
bound, not tuning, a candidate prediction or acceptance. Use it with the prior
C allocation-oracle evidence to decide what can still be learned from the
representation, rather than treating a mathematical pass as model success.
