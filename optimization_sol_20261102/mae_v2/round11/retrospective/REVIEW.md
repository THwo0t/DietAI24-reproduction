# Independent whole-project MAE retrospective after O

Date: 2026-11-04. Scope reviewed once. This is a scientific-method retrospective,
not another review of the already reviewed O engineering node. Verdict:
**changes requested for the next experimental design; O remains rejected**.
No code change, API, network, download, image/label inspection, provider response
inspection, validation access, or per-record oracle-weight access was performed.
Only this file is written. References below are relative to
`optimization_sol_20261102/mae_v2/` unless prefixed `code/` or `paper.txt`.
The paper is the supplied handoff `workspace/work/paper/paper.txt`.

## Evidence status and completed outcome

The coordinator identifies original O freeze
`0815819980716aa6be5a5e77a71de6c007f8985566bf5503f5b007d201164d92`
and unchanged 42 source pins, with successful original offline verify and score.
I inspected its ID-free checkpoint and automatic follow-up, not its private
verification inputs. `round10/launch/automatic_followup.json:2–20` records
development_scored, rejection, ASA zero failed checks and N5 ten failed checks
for both raw and OOF_mass, no new paid requests and unopened validation.

O ASA: 99 records/23 groups; 17 Exact/9 groups (17.17%), 15 first-code hits,
27 retrieval hits. Conditional raw and OOF both pass 10/10; this is not all-99
E2E success. The original 18% target remains unmet; the current 15% guard passes
and is secondary to MAE. N5: 84 records/78 groups, 81 native plus 3 repaired,
zero fallback. MAEs (weight/energy/fat/carbs/protein) are raw
106.7414/142.5901/9.8077/14.3029/13.3896 and OOF
105.2217/143.1608/9.8774/14.5623/13.3615. Each fails all ten N5 checks.
Thus only 10/20 checks pass; neither strict 20/20 nor at-most-two-failures-per-
dataset acceptance is met. Sources: `round10/development_checkpoint.json:7–33`,
`:549–566`, `:2092–2190`; `round10/PROTOCOL.md:83–87`.

The additional completed_o aggregate is a distinct, posthoc artifact. Its only
read record is `round10/diagnostics/completed_o/records/ee3c65b5c7f4dd0ebed8bf046725e273e3eeed3c6776b0667b9deb6432f6c3ea.json:1`
(one-line JSON, `name=aggregate`; called **D** below). Its completion exists,
but at review time the original guard receipt is missing and read-only recovery
is pending. D is **not treated as having passed the original guard**, nor used
to override original scoring. The changing recovery code is outside this review.

## Findings

### R11-R-1 [P1, scientific design must change] Conditional ASA success cannot diagnose the N5 bottleneck

The old ASA raw success was real but task-specific: 16 Exact/9 groups out of99,
not a full-population pass (`round10/PROTOCOL.md:9–15`). After identities are
fixed, the permitted adapter supplies the correct food code and its complete
legal catalogue (`src/legacy_adapter.py:109–119`). Continuous-option inference
receives the food's generic description, estimates grams, then programmatically
projects to a legal option and computes nutrition from that correct code
(`src/opt_pipeline.py:562–588`, `:605–609`). This removes identity-density error
from that conditional task and restricts quantities to legal values. Controlled
single-food ASA photography also differs from N5 mixed dishes (paper.txt:199–218).
These are concrete reasons why the task is easier, **not a causal proof of how
much each factor produced the pass**. Selecting Exact rows also changes the
evaluated population. The old raw pass shows calibration was not necessary;
it does not show raw grams, every legal projection, or all99 rows were accurate.

O restores this adapter and passes again, while failing N5. Do not spend the next
round on reproducing the already demonstrated conditional pass. Preserve it as
a guard/control, separately report all99 E2E and original18% recognition, and
make full-population N5 MAE the main mechanism test. Paper.txt:242–254 makes
nutrient agreement the ultimate outcome; its portion state machine is at179–186.

### R11-R-2 [P1, scientific design must change] Stop repeating rescaling/unit substitutions as the main hypothesis

This project did more than calibration: F tested direct visual nutrients;
G/H/I changed supervised examples/catalogues/checklists; CHI combined outputs;
J used an external supervised gallery; K changed reasoning/prior inputs; M/N/O
changed representation, identity, densities and quantity. It would be inaccurate
to call all work mere calibration. Nevertheless the repeatedly revisited
quantity/postprocessing family has not solved N5. The historical completed
summary records every F–K N5 profile failing all ten checks, including J and its
OOF correction (`round7/PROJECT_REVIEW.md:18–36`). J's calibration even used five
independent target factors, explicitly breaking mass-density accounting
(`round4/CALIBRATION_PROTOCOL.md:10–27`), without reaching a check.

N-units holds N-density identities fixed and worsens weight, energy, fat and
carbs; N-density itself changes successful-row nutrition little. Its tiny
whole-population weight gain comes from the four fallback vectors, not better
mass estimation (`round8/PROJECT_REVIEW.md:39–61`). O's true standard-first
state machine is a meaningful source correction, but its complete result now
rejects sufficiency of that correction (`round10/PROTOCOL.md:45–79`; checkpoint
:2092–2190). OOF improves O weight about1.52g while worsening energy/fat/carbs;
all ten N5 checks remain failed. No larger factor grid, another unit vocabulary,
or target-wise splice is justified as the default next main experiment.
Paper.txt:172–189 supports the conversion mechanism, not a guarantee that a
generic unit or common scalar identifies image scale, composition or density.

### R11-R-3 [P2, scientific design must change] Define a paired intervention before attributing failure to scale or density

Prediction is sum(mass × nutrient density), so total scale, allocation among
foods, identity and effective density interact. The released implementation
averages selected-code densities (`code/nutrient_estimate_mix.py:66–80`), while
the paper only states the retrieval/portion/nutrient chain (paper.txt:162–189).
Restoring averaging is compatibility, not evidence that its density is correct.
N's fixed identities admit a reference-informed joint passing allocation, but
that optimistic witness permits zero masses/unconstrained reallocations and
does not establish visual learnability or a sole cause (`round9/DECISION.md:7–15`).
No individual oracle weights were inspected or proposed for deployment here.

D's aggregate decomposition explicitly says its algebraic mass/density terms
are not additive MAE shares or causal ingredient errors. Total-mass discrepancy
can include missing/duplicated foods; whole-dish density cannot separate recipe,
water content, code choice or FNDDS mismatch. Its N5 raw signed errors are
approximately -60.35g weight, -54.75kcal energy, -3.29g fat, +1.30g carbs and
-9.63g protein, with errors of both signs. This supports joint unresolved
mass/composition problems; it does not prove a universal underestimate, fixed
plate scale, missing oil, particular ingredient omission, or bad database.
Treat these D observations as provisional until recovery evidence is completed.
Mandatory next protocol: name the changed variable, hold the rest fixed where
possible, score the same full populations, and distinguish predictive comparison
from mechanistic causality. Do not infer causes from changing own-Exact subsets
(`round8/PROJECT_REVIEW.md:56–61`) or engineer ingredients from reference errors.

### R11-R-4 [P2, scientific design must change] Repeated development reuse requires a new frozen comparison, not a stitched result

F–K did not newly execute a shared ASA core; their old-ASA/new-N5 joint10/20 was
bookkeeping, not a tested common candidate (`round7/PROJECT_REVIEW.md:9–14`).
M/N/O correct that scope but all fail. Historical differences also span
information regimes: F direct nutrient inference, J/K supervised labelled
galleries and original zero-shot FNDDS are different methods, not a clean model
leaderboard. Paper.txt:295–296 specifies pretrained zero-shot use. Changing
resolution, split policy, information access and multiple stages together cannot
isolate one cause. Repeated development selection makes OOF postprocessing
honest about fitting folds, not independent evidence for the whole research
search. Original validation remains sealed. User authorization to enlarge both
development sets, download test images and make more calls is not selection of
a candidate, approval of P-C preparation, or approval of a P-E paid run here.

Require a prospective, paired, frozen design with one common core on both
datasets and target-only ASA adapters. Keep historical controls scope-labelled;
never concatenate old ASA success with a newly successful N5 method. Keep
current and expanded-development results distinguishable; no error-based
replacement. Paper.txt:230–240 also confirms that populations and preprocessing
are material experimental conditions.

### R11-R-5 [P3, recommendation] Credit engineering separately and resist restarting untested branches without a question

Durable attempts, full-population scoring, replay, sealing and source pins are
substantial reproducibility progress, not MAE progress. L's region atlas was
implemented but never produced real inference/accuracy evidence
(`round7/PROJECT_REVIEW.md:69–81`). It is not a failed scientific result, nor a
validated next solution. D reports zero mapping/join inconsistencies, but does
not provide an annotated omission/duplication rate; shared codes alone cannot
establish duplicate food accounting. Preserve these distinctions. No additional
engineering-review cycle or more synthetic tests can substitute for a measurable
mechanism hypothesis and an eventual prediction-only full-cohort comparison.

## At most two controllable next mechanism directions

1. **Image-grounded mass and allocation, with identity/density fixed.** Prefer
   this first because N's constructive bound leaves allocation plausible and O
   has not learned it. Register one quantity change: explicitly estimate whole
   edible serving mass with visible scale cues/uncertainty, then allocate that
   same mass to the already frozen disjoint foods using normalized shares.
   Compare against the existing quantity core on the same frozen identities,
   retrieval and densities. This is not another universal multiplier and does
   not assume plate diameter. No true mass, oracle shares, target recipes or
   errors enter requests; no new ingredient may be inserted to balance targets.
   Check physical mass conservation and report all five full-population MAEs,
   target pairs, failure counts and ASA conditional/E2E separately. A failed
   paired result rejects this specific estimator, not all visual mass learning.

2. **Visually justified density/state selection, with physical masses fixed.**
   Test one bounded selection change within the frozen candidate bank: choose
   a single primary food/preparation state instead of an unweighted alternative-
   density mean, using visible evidence and generic catalogue text only. Keep
   the same item list and grams, and label this an identity/density intervention;
   it cannot prove water/recipe causality. No target nutrient hints, reference-
   directed ingredient completion, new food bank or unconstrained fitted mixture.
   Compare one coherent five-target profile, including weight invariance as a
   manipulation check. This revisits a known mechanism only as a controlled
   contrast; historical single-code versus multi-code runs were confounded by
   changed upstream identity/representation and are not this contrast.

These are candidate hypotheses, not chosen/deployed models or instructions to
start either paid run. Choose and freeze one prospective comparison before
accessing expanded development targets. No model search, new data preparation,
validation, P-C or P-E is approved by this retrospective. Address P1/P2 in the
coordinator's next design and record dispositions; this scope is not re-reviewed.

## Coordinator dispositions (not a second review)

- R11-R-1: fixed at the design level in `round11/DESIGN.md`. Full N5 MAE leads
  the next comparison; conditional ASA is retained with explicit denominators,
  all-record E2E and the separate18%/15% recognition definitions. Actual expanded
  predictor implementation, cohort freeze and paid run remain pending. Offline
  confirmation: the design explicitly prohibits target information in blind
  requests and requires a newly executed common predictor for both datasets.
- R11-R-2: fixed at the design level in `round11/DESIGN.md`. The finite next
  comparison targets quantity allocation then density/state selection; another
  factor grid/unit vocabulary is excluded as the main hypothesis. Prior C/K
  mass/share work is explicitly credited. Offline source confirmation: the
  design has at most two interventions and forbids history/target-wise splicing.
  Implementation and completed predictive evidence remain pending.
- R11-R-3: fixed at the design level in `round11/DESIGN.md`. O/Q/D/Q+D are
  prospectively declared; fixed identities/code sets, fixed grams for the
  density contrast, mass conservation, lineage and weight-invariance checks
  isolate the named interventions. The text forbids causal/additive claims from
  algebra or changing Exact subsets. Offline confirmation is a source-contract
  inspection; predictor/schema/paired-result enforcement remains pending P-D.
- R11-R-4: fixed at the design level in `round11/DESIGN.md`. Sampling seed,
  full-association exclusions, core/expanded strata, finite profiles, no reroll,
  source/call freeze, grouped fitting/fallback and sealed validation are
  prospective requirements. Neither old ASA scores nor old partial populations
  can be spliced into the new comparison. Offline confirmation: registration
  precedes actual expanded target access; P-C/P-D implementation, first full
  run review and new predictive evidence remain pending.
- R11-R-5: accepted as a reporting constraint. Engineering checks are labelled
  as such, L has no claimed real accuracy result, and no new synthetic-test
  count is treated as MAE progress. Formal reports remain deferred.
