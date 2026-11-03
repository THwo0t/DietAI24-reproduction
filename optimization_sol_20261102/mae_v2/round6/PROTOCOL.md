# L pilot: region-grounded training comparisons

Registered before any L API request, training-region annotation, or pilot score.
This is a bounded external-training experiment, not another 84-image development
run or independent acceptance. K was rejected after complete scoring; raw J
remains the failed development baseline. All old sources and artifacts are
immutable. Reports remain deferred. No download or new embedding is needed.

## Question and paired intervention

J/K provide whole training photographs and ingredient masses without supervised
region-to-ingredient correspondence. Test whether Sol-generated region hints
and crops, attached to the same four training references, improve five-target
MAE. These are automatic annotations, never human region ground truth or measured
crop masses. Do not change retrieval, reranking, output grammar, mass arithmetic,
or nutrient calculation between paired branches.

The paper's image-to-description-to-retrieval-to-predicted-identity chain remains
the task reference (paper.txt 162–189; supplementary Algorithms 2–3). This pilot
uses same-domain training supervision and differs from the paper's stated
zero-shot setting (paper.txt 272–296). Paper Table 2 supplies numerical project
targets, not a claim of an information-matched comparison. Query ground-truth
identity, mass, nutrients and regions never enter prediction requests.

## Fixed training-only population

Use only the accepted 230-image/230-group external training release, its sealed
label-blind gallery descriptions and official text embeddings. Inherit their
existing byte/RGB/recipe/group exclusion proof. Verify fixed release and gallery
completion hashes; never follow arbitrary paths in old artifact bindings.
Do not read development or validation images, labels or predictions.

Use the five folds already defined by `external-gram-prior-r5.1`: sort groups
by SHA256(seed + NUL + group_id), then assign positions round-robin. Each fold
contains 46 groups. Within each fold sort by
SHA256(`region-atlas-pilot-r6.1` + NUL + group_id), then group_id; take the first
five groups. All 25 queries are retained irrespective of errors or visibility.
No replacements, resampling, or expansion is allowed within this pilot.

For a query, all 46 groups of its fold are held out. Its retrieval index,
support candidates, ingredient vocabulary/densities and five-target median
fallback are built from the other 184 groups only. Ingredient densities are
100 times nutrient sums divided by gram sums on those training groups.
Preserve official targets and the registered 2 g source discrepancy unchanged.
The cached query description/embedding is label-blind and may be reused.
The train-only preparation adapter may read the frozen 230-row supervision to
construct these five isolated training views. Its prediction context exposes
only fold-training assets and label-free query metadata/vectors; it must not
retain or forward pilot query targets. This is supervised OOF preparation, not
access to the separately sealed development or validation cohorts.

## Shared baseline and region candidate

Both branches use the same cosine top 12 and one visual reranking to four
training images, using the frozen J contracts and deterministic rerank fallback.
Baseline calls the unchanged J estimator on the query and those four supports.
Candidate uses the same catalog, four whole support photographs, full ingredient
lists/grams and programmatically calculated support totals. It adds only region
annotations and at most two crop cards per support (eight total). The query is
the final whole photograph and receives no label-derived region annotation.

Annotation inputs are one support image and all its positive-mass ingredient
IDs/names, with no grams, densities or target totals. Every supplied ID must
have exactly one annotation: `separable`, `partially_visible`,
`mixed_not_separable`, or `not_visible_or_uncertain`; a list of normalized boxes
covering all visible occurrences; visual evidence and uncertainty; and an
optional shared-region identifier for an inseparable mixed entity. Do not force
hidden oils or sauces into a visible region. Each annotation gets at most one
format-only repair; invalid after repair means unavailable atlas for that whole
support, whose original whole image and full recipe remain present.

Crop only `separable` annotations with nonempty boxes and no shared region.
Each card is the bounding rectangle covering all that ID's declared visible
boxes, expanded by 5% of its width/height and clipped to the image. Sort cards
by descending union bounding-rectangle area, then ingredient ID, and take two
per support. Use floor/ceil pixel bounds, RGB PNG, native aspect, longest edge
at most 1024, and no upsampling. Preserve coordinates and source/crop hashes.
No crop is chosen by grams, nutrient targets, query labels, or measured error.
Official ingredient total grams belong to the full support photograph, including
any unseen mass. They must never be exposed as `crop_grams` or guaranteed mass
inside a box. Crops are additional views of the same food, not extra portions.
At most 13 images enter candidate estimation: 4 whole supports + 8 support
crops + 1 query. Baseline uses five. No query crops or K hypothesis stage.

Candidate retains J's flat 1–20 nonoverlapping positive-mass items, known-ID exact
density/null estimated density, explicit unknown densities, programmatic totals
and one format-only repair. Composite/component double counting is forbidden.
No calibration, fixed mass multiplier, ensemble or per-target profile splicing.
Both branches use the same fold-training median fallback after exhausted format
repair, and every query remains in primary scoring. Service/auth/model/integrity
failures stop the batch and preserve completed stages; they are not fallbacks.

## Service and durable evidence

Sol is the sole visual/main model (`gpt-6.1-sol`, zicc, temperature 1); the
original official embedding route remains configured but is never invoked.
Use namespace `region-atlas-pilot-r6-l.1`, read timeout 600 s, connect 30 s,
write/pool 120 s, at most two workers, at most three persistent transmissions
per payload. Annotation/rerank completion cap 4096; both estimates 8192.
Image-bound ordered request receipts, source/input hashes, cached raw answers,
parsers, request budgets and completion provenance must verify on resume and
completed zero-Provider replay. Never regenerate a completed answer for accuracy.

There are 25 shared reranks, 25 baseline estimates, 25 candidate estimates and
U unique support annotations, U <= 100. Hence at most 175 initial logical chat
calls, at most 350 including format repair, and at most 1050 transmissions.
No new embedding requests. Record actual requests/tokens; third-party money
requires verified pricing or bills. Reasoning tokens are inside completion.

## Scoring and fixed advance gate

After preparation, the prediction context contains no held-out target reader.
The scoring reader cannot open held-out references until all 25 paired
predictions seal.
Score all 25, including fallbacks, against unchanged official five dish targets.
Use MAE and MAE/reference mean on this same population; report all ten N5 caps.
These training-pilot metrics do not replace the existing 84-image dev results.

Advance only if all conditions hold at full precision:

1. At least three of five candidate MAEs strictly improve on paired baseline.
2. Mean of five candidate/baseline MAE ratios is <= 0.90.
3. No individual ratio exceeds 1.05.
4. Maximum of ten candidate cap ratios strictly decreases.
5. No previously passing baseline check crosses its cap.

A zero/nonfinite baseline MAE makes the gate invalid/rejected. No error-based
reruns, threshold changes, revised pilot sample, target splicing or cherry-picked
subsets. Report paired group-bootstrap intervals descriptively, native/repair/
fallback rates, atlas availability, exact-ID gram L1 including omitted/extra/
unknown mass, and mass overlap. Shared-ID-only metrics have changing populations
and cannot establish causal mechanism by themselves. The intervention combines
region hints, crops and visual attention, so it cannot identify their separate
causal contributions.

This conservative engineering gate is not significance testing. A pass permits
registration of one fixed 84-image development candidate, not opening validation
or declaring the 1.3x goal met. A fail ends this candidate: back up safe source
and aggregates, diagnose, and keep optimizing through a separately registered
method. No final report for a failed iteration.
