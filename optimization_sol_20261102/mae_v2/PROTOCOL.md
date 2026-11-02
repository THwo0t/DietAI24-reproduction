# DietAI24 MAE-first v2 preregistration

Registered 2026-11-02 before new inference. This implements the user-approved
second-round plan; it does not revise the failed v1 conclusion.

## Objectives and fixed conditions

- All twenty absolute/per-unit limits in `analysis/paper_targets.json` remain
  unchanged. Per unit means MAE divided by the reference mean of exactly the
  scored population; full precision determines passing.
- ASA24 recognition uses all rows and at most three distinct codes, with a
  primary code. The new floor is ceil(0.15*N), i.e. 15/99 or 12/78. Report the
  former 18% target separately. Primary MAE is Exact-conditional legal-option
  estimation, not image-to-nutrient end-to-end accuracy. Report E2E and Exact
  group counts as well. The paper does not establish identical conditional
  populations; no same-population replication claim is made.
- Nutrition5k primary scoring includes every active row, including whole-dish
  fallback. Validation aims at 200 RGB images with disclosed association groups,
  not 200 proven independent physical plates.
- Chat/vision: gpt-6.1-sol at https://api.zicc.cc/v1. Embeddings:
  text-embedding-3-large at https://api.openai.com/v1, with the original official
  credential. Two credentials never cross routes. Temperature is 1. Legacy
  ASA24/reference calls retain 4096 completion tokens; component calls use 8192
  to accommodate up to twenty structured leaves. This is a declared v2 change.
- Inputs are a single RGB image; native processing preserves aspect ratio,
  caps the longest side at 1024, and never upscales. No depth or other views.
- The user authorized paid development without a monetary cap. Usage is still
  recorded. Unverified third-party prices are not replaced by official prices.

## Cohorts and isolation

Preparation runs without an inference provider or credential access. It may
mechanically hash sealed images and inspect ingredient IDs/masses solely for
linkage; it emits no validation images, descriptions or nutrient summaries.
Build the graph from complete raw cafe metadata, before candidate filtering.
Use ingredient IDs mapped to summed positive Decimal grams.

Edges: equal image bytes or decoded RGB pixels; same-cafe equal complete mass
vectors; or same-cafe forward scans within 600 seconds where the earlier scan
has at least two ingredients, all masses are exactly retained, and ingredients
are added. Adjacent full-sequence scans within 600 seconds with at least two
shared ingredients and one exact positive mass anchor also link if all earlier
ingredients are retained without mass reduction and something increases. For
those adjacent eligible pairs, disappearance or reduction marks ambiguous
components, which are quarantined. Zero masses are ignored; malformed,
negative/nonfinite masses or conflicting duplicate IDs stop preparation.

Propagate all historical exposure and the original dev100 through the graph.
Exposed validation records are retired, never converted to training. The dev
set loses only exact duplicates, historical contamination and predefined
ambiguities; it is not replenished or filtered by error. Fewer than five active
N5 groups stops five-fold development. ASA24 existing connected groups remain.
Use seed `dietai24-mae-v2-20261102`: SHA-256 ordering of groups, index modulo five
for folds. Validation replacement uses fixed hash order and group round robin,
preferring groups not already represented. Require 200 eligible images; never
relax linkage rules to fill the set. New downloads beyond the existing approval
require a concrete size/count request before transfer.

Original freezes remain unchanged. The v2 freeze binds raw sources, rule
version, exposure closure, active manifests, exclusions, and image hashes.
All fold-dependent examples, median fallbacks and calibration are rebuilt.
Unsupervised responses with exactly identical inputs may be imported with
explicit source hashes; old OOF scores are historical only. `verify-dev` never
opens a validation file. Linkage groups are heuristic: report image count,
group count, group size distribution, maximum group share, and limitations.

## Inference and accounting

ASA24 keeps retrieval-portion recognition: square256, hybrid cap32, continuous
grams followed by nearest legal option (ties: lighter, then option ID). Only
the isolated Exact adapter provides true code and the complete legal catalog;
no reference Portion, LabelUnit, size, grams, nutrients or image filename may
enter a prompt.

N5 uses at most eight parents, six components per parent and twenty accounting
leaves. A parent is composite (one leaf) or components (child leaves only).
Each leaf has a stable ID, one FNDDS code and positive grams. Parent mass is
the sum of child masses; parent nutrients are not counted again. Ambiguous
mixtures can remain composite; missing visible residual cannot become zero.
No invisible oil is added from labels. Codes must occur in retrieved candidates.

Two queries per leaf; dense12 and lexical12 per query; code-deduplicated RRF60,
cap32. Candidates include official description/category and per100g density.
Inferred compound relationships are hypotheses, not catalog facts. Alternate
identities do not add mass or have their densities averaged. Nutrients are the
sum of leaf grams times code density divided by 100.

B crops are drawn from A's predicted boxes, expanded 10%, clipped to the image,
and limited to four: uncertain identity first, mixed region next, other regions
last, then stable parent ID. B may revise components but retains parent regions.
One request sees the original image and all selected same-image crops.

## Finite experiments and selection

Rebuild original baseline and examples-2 development references under v2 groups.
Reuse label-blind raw responses only with exact provenance; regenerate example
outputs using new training folds. The reference with examples remains
uncalibrated because fitting from other folds' example-assisted predictions
would introduce indirect held-out label dependencies.

First round: A=components+direct parent grams/child shares; B=A layout+crop
review+new code selection+same portion method; C=best raw A/B identities+whole
plate grams/parent shares/child shares. Run A and B on the full active set;
run C on exactly one selected upstream. Do not form a Cartesian grid.

Choose per dataset: ASA recognition feasibility first, then lowest maximum
of ten metric/threshold ratios, then their mean, estimated main chat count,
and registration order. References remain in final comparisons. Never select
different methods per sample, nutrient, or error-defined subgroup.

After selecting a raw winner, compare one mass calibration, at most once per
round. Fit only non-fallback training predictions with at least five training
groups; otherwise factor1. Search .800 to 1.250 inclusive at .001 spacing by
training max ratio, mean ratio, closeness to1, then lower factor. Shrink halfway
to1 before applying (actual range .9–1.125). N5 scales leaves then reaggregates;
ASA scales continuous grams then remaps a legal option. Do not scale final
option grams. Enable only if OOF maximum ratio strictly improves and no passed
metric becomes failed. Fit final parameters once on full active development.

If N5 still fails, one additional round has at most two candidates. D runs
when any nutrient metric fails: preserve the first-round raw winner's structure
and grams, review codes against image evidence, optionally retrieve once and
select once again with cap32. Unresolved reviews retain the original choice.
E runs when weight MAE or per-unit fails and a usable standard portion exists:
estimate option-ID and multiples of its complete description, then compute
grams programmatically. Exclude unspecified/guideline/ambiguous-serving entries;
missing eligible options retain the original leaf grams. Recompute parent and
total mass, without renormalizing to the old total. D/E each use the same raw
winner, never each other. Failed enhancement uses the entire base prediction,
with an explicit method-fallback flag. No replacement candidate or sixth arm.

## Failure, provenance and acceptance

Each stage has at most one structural repair; each payload at most three HTTP
attempts across process restarts. Invalid/empty/NaN/infinite/negative outputs,
unknown or duplicated IDs/codes and incomplete accounting are explicit failures.
N5 irreparable base failures use training-fold componentwise median targets;
ASA every Exact failure uses median-weight legal option. Authentication, model
mismatch and persistent service faults stop the batch. Never rerun a valid
answer because its accuracy is poor. Persist raw, parsed, calculated and
calibrated outputs, usage, stage hashes, identity seals and complete sample IDs.

Development failure exhausts only the finite tree: retain the sealed validation
and report the remaining gaps. Passing all20 plus ASA15% permits checkpoint-one
review and a full method freeze. Frozen original baseline and final method run
once each; score only after both finish. Use paired group bootstrap with 10000
resamples and the fixed seed for 95% intervals; point estimates gate acceptance.
ASA groups include all sizes; N5 groups use the association graph. Fewer than
two groups yields no interval. Formal results cannot be reused for independent
acceptance after modifying the method in response to them.

Checkpoint two precedes final English Markdown/PDF/DOCX and Mac handoff. Keep
source/runtime/result manifests, offline demo and dual-key small live demo.
No Mac is available: Linux evidence is not Mac hardware verification. New data,
raw logs and credentials are not automatically public. Publishing requires the
explicit agreed content boundary and a credential scan of the exact package.
