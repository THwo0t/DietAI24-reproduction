# Project review after rejected K and new user steering

Working decision record, not a final report. All source, data and evidence stay
under `mae_v2`. Validation remains sealed. Existing paid-development and approved
download authorizations persist; no additional download is planned.

## Correct interpretation of completed evidence

The original reproduction ran both datasets using the paper's overall FNDDS
chain. Later methods diverged: v1 chose different configurations by dataset;
v2 retained the ASA retrieval/portion method while A–E and F–K changed N5 only.
Their historical `joint 10/20` combines old ASA with new N5. It is a bookkeeping
aggregate, **not evidence that J/K/L is one method tested on both datasets**.
Preserve old seals unchanged and label this limitation in all new comparisons.

Five MAEs below are weight g / energy kcal / fat g / carbs g / protein g.

| Completed development evidence | Population and method scope | Five MAEs |
|---|---|---|
| v2 ASA retrieval/portion | 99 images; 16 Exact records, 9 Exact groups; conditional option score | 23.594 / 29.672 / 0.949 / 4.843 / 1.014 |
| Same ASA whole-population E2E | All 99; distinct evaluation task | 71.710 / 141.367 / 9.450 / 16.504 / 6.716 |
| v2 selected calibrated C | N5 84 images / 78 groups; ASA did not run C | 78.396 / 118.500 / 8.318 / 13.201 / 11.085 |
| F direct nutrients | Same N5 84; no new ASA run | 121.012 / 190.740 / 11.801 / 24.413 / 11.005 |
| G supervised whole-dish examples | Same N5 84; no new ASA run | 82.845 / 140.131 / 9.659 / 17.273 / 10.660 |
| H ingredient catalog and examples | Same N5 84; no new ASA run | 69.012 / 114.980 / 9.209 / 11.791 / 10.411 |
| I H plus visual checklist | Same N5 84; no new ASA run | 74.226 / 112.528 / 7.922 / 11.298 / 10.683 |
| CHI fixed median ensemble | Same N5 84; no new ASA run | 72.964 / 110.321 / 7.897 / 11.647 / 10.010 |
| Raw J | Same N5 84; 230 independent supervised training images; no new ASA run | 67.202 / 102.188 / 8.369 / 10.522 / 8.968 |
| J OOF calibration, rejected | Same N5 84; no new ASA run | 67.640 / 99.720 / 8.308 / 8.911 / 9.058 |
| K, rejected | Same N5 84, including one fallback; no new ASA run | 83.119 / 120.716 / 8.979 / 10.443 / 10.534 |

These are rounded display values from completed aggregates, not rescored or
independent acceptance results. Every listed N5 v2–K profile fails all ten
registered N5 absolute/per-unit checks. Raw J is the best historical selected
whole N5 profile, but is not a complete dual-dataset candidate. The ASA
conditional result cannot establish full-population E2E success.

Evidence: `evidence/development-summary.json`, `round3/development_checkpoint.json`,
`round4/development_checkpoint.json`, `round5/development_checkpoint.json`.
Original comparison populations differ (150-image complete subsets; v1 N5 100
with later association exclusions), so do not treat their differences from the
fixed 84 as a clean improvement curve. See `REPORT.md` at the project root,
`../reports/REPORT.md`, and `evidence/M2-2_cohorts.md`.

## What K falsified

K worsened four of five MAEs. J/K exact-ID mass overlap fell 44.57% to 37.23%;
reference mass associated with predicted present IDs fell 51.63% to 43.64%.
Even oracle true-weight scaling leaves K energy/fat/carbs/protein MAEs at
93.919 / 8.740 / 8.988 / 8.195, all failing. K has 83 decomposable rows versus
J's 84, so smaller shared-ID-only errors do not establish improvement. Exact-ID
disagreement itself is not proof of visual omission (aliases and composite
representations differ). See `round5/development_diagnostic.json`.

Posthoc error concentration on all 84 K records also shows that the ten largest
errors contribute 36.2–42.0% of each target's total absolute error. The remaining
74 still contribute most error. Mean signed errors are -21.19 g weight,
-19.19 kcal energy, -2.58 g fat, +2.77 g carbs and -2.94 g protein; positive and
negative errors coexist (weight splits 42/42). Neither discarding a few outliers
nor one universal upward/downward multiplier is justified. No sample was removed
or rerun. See `round5/error_concentration.json`.

The old FNDDS C diagnostic also rejects total-mass scaling as a sufficient
solution: its true-weight-only oracle passes only 2/10, whereas a nondeployable
true-weight/free-allocation oracle can pass 10/10. Composition/accounting and
mass allocation require joint attention. This is diagnostic evidence, not an
achievable-performance guarantee.

## Engineering progress versus scientific progress

Completed engineering includes conservative association splits, frozen cohorts,
dual credential routing/redaction, complete-population scoring, grouped
bootstrap, durable per-payload budgets, raw-answer and service evidence,
zero-Provider replay, independent reviews and safe GitHub backups. The external
230-image release and training gallery are complete. Do not download them again.
These improve auditability; they do not constitute MAE improvement.

L's region-atlas training pilot was implemented with 95 passing network-disabled
synthetic tests (58.096 s), but had **no real preflight, annotation, API request or
accuracy result** when the new user requirement arrived. Preserve the source;
the N5-only paid CLI is shelved and separately tested to refuse execution.
There is no ongoing paid run to interrupt or restart.

## Scope corrections before another paid experiment

1. Every complete candidate must implement one defined shared core and obtain
   same-method evidence on **both** ASA24 and N5. Old ASA scores are historical
   controls only. Reuse of an identical sealed prediction is permitted only
   after exact source/config/input/raw-output verification and must be disclosed;
   similarity of food, prompts or names is insufficient.
2. Return to the paper's image description → official embedding/FNDDS retrieval
   → visual identity → quantity → programmatic catalog nutrition chain. Remove
   N5-only supervised ingredient dictionaries, reference recipe galleries,
   direct nutrient overrides and crop-atlas additions from the next main method.
3. Define the shared RGB processing, food representation, retrieval, route/code
   choice, quantity estimation and nutrient arithmetic once. Keep only necessary
   dataset target/option adapters outside that core. Do not select different
   prompts or algorithms by dataset.
4. Keep ASA conditional option scoring distinct from all-record E2E. Generate
   both anew, report Exact denominators/groups and common-matched comparisons.
   No true query mass, nutrients, selected option, bin or reference portion unit
   enters a model request. N5 remains all 84, including fixed failed-row fallback.
5. Before results, interpret the new tolerance conservatively: each dataset has
   ten numerical checks (five targets × absolute MAE and per-unit); at most **two
   failing checks per dataset**. Also report the five target pairs and strict
   20/20 result. Do not move failures between datasets or change counting later.
   Existing 1.3×paper thresholds and `per unit = MAE/reference mean` are unchanged.
6. After every full failure, repeat this project-level review: both datasets,
   failure populations, largest errors, method deviations, completed/unexecuted
   engineering, service/cost evidence, remaining gap and one next decision.
   Back up a secret-scanned explicit source/aggregate inventory, verify branch
   and remote state, and never force-push or overwrite another writer.

The next protocol is not yet frozen. Its candidate must be selected from these
mechanisms and source compatibility checks, not from validation. No formal
report or Mac delivery update is produced for this failed iteration.

## Original GPT-4o/Sol comparison remains a separate diagnostic

The first formal comparison has 79 jointly complete Nutrition5k dishes. GPT-4o
to Sol weight MAE changes from 96.01 to 62.24 g; energy 126.9 to 131.8 kcal,
fat 7.969 to 9.435 g, carbs 12.27 to 13.66 g and protein 10.00 to 10.06 g.
The four nutrient paired intervals all cross zero: these point estimates do not
establish statistically significant nutrient differences. Coverage is separately
86/150 versus 118/150, with 7 and 39 model-exclusive complete dishes and 25
jointly incomplete. Completeness only covers recognized items, not proof that
every visible food was recognized. Evidence: root `REPORT.md:105–132` and
`runs/comparison-gpt-4o-vs-sol/comparison.md:23–27`.

This was a joint model/required-parameter replacement: temperature 0 to 1,
description `max_tokens=200` to `max_completion_tokens=4096`, and a changed token
budget definition including reasoning. It does not isolate model causality.
The paper uses pretrained GPT zero-shot without task-specific weight tuning;
J/K's labeled training galleries are a separately documented method deviation.

For descriptive diagnosis only, join the two original runs (`runs/test` and
`runs/test-gpt-6.1-sol`) by dish ID through `nutrition5k_food_codes.csv`,
`nutrition5k_portion.csv` and `nutrition5k_nutrition.csv`. Inspect generated
descriptions, item splitting, candidates/final codes, exact-name gram matching,
and average-candidate FNDDS density. Source: `code/rag_food_code.py:256–277`,
`code/rag_portion_size.py:280–296`, `code/nutrient_estimate_mix.py:48–83`.
Keep prediction-only chain inspection separate from reference-aware error
decomposition; retain all 150 coverage statuses and the paired-79 denominator.
Original test labels may explain these archived results, never tune prompts,
rules, candidates or method selection. Any proposed mechanism must be checked
on the independent active development cohorts. K's later diagnostics cannot
serve as evidence for this first comparison.

The requested prediction-side audit is now executed, not merely planned.
`tools/diagnose_original_comparison.py` reads explicit prediction-column lists,
AST-extracts only pure parser functions (no inference/config import), and
recomputes both models' 150 archived rows against the original FNDDS table.
All 300 ingredient/error counts, predicted weights and four nutrient outputs
match their archived values. The historical food/gram-name parser hash equals
both run configurations. Postprocessing sources are separately hashed: those
files were not included in the original inference config's five-file hash map.
No query reference label, image, credential or API client is loaded, and every
input file is rehashed before the separate outputs are written. Validation
remains unopened. See `original_comparison_diagnostic.json` for safe aggregates;
per-dish chains stay in ignored private `diagnostics/original_comparison/`.

The all-150 coverage transitions reproduce exactly: common complete79, 4o-only7,
Sol-only39, neither25. On the common79, final selected-code sets differ in74
dishes and item counts differ in41. Mean parsed items are1.861 versus1.494;
mean visible description lengths are132.67 versus83.89 characters, despite the
larger supported Sol token ceiling. Mean predicted total weights are162.15
versus212.05g. No selected code is outside its saved retrieval candidate set in
either run. Two 4o rows contain parser warning lines; these are retained, not
discarded or reanswered.

An optional symmetric algebraic decomposition of the **predicted nutrient
differences** into total-mass and effective-density terms is also saved. It is
not a decomposition of MAE, proof of omission, an accuracy ranking for those
stages or a causal explanation. Effective density combines code identity,
averaging multiple selected codes, and food-mass allocation. No reference
labels were used in this audit. The M draft/core commits (`e3d6731`, `16c1abb`)
precede this audit; no M prompt, parameter, selection rule or method was changed
using these original test records. Any subsequent predictive hypothesis must
be evaluated on the independent active development data.
