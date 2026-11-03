# External-training ingredient-mass prior: fixed offline utility experiment

Status: **registered design and synthetic implementation only; not executed on
real training data**. This experiment does not replace Sol, select a final
model, claim paper-threshold achievement, or authorize access to J predictions,
development data/labels, or validation. All new work stays under `round5/`.
No API call, new embedding, image inspection, or download is needed.

## Question and fixed population

Does a small supervised model of cached visual-caption embeddings contain useful
ingredient-mass information that could later be supplied to Sol as a provisional,
visually rejectable reference? Sol remains the main visual model. Failure of the
advance gate below ends this prior route: do not forward the prior to Sol.

The eventual real-data run must contain all **230 accepted external-training
images and 230 screening groups**, using their already sealed gallery captions
and 3,072-dimensional official embedding vectors. No row is selected by errors
or omitted after prediction. Use only the external-training manifest, official
five-target labels, ingredient masses/nutrient amounts, and sealed training
gallery. The loader must not call `context.load_context`, `run_base.base`, a
provider, or any development/validation reader. Real training inputs are not read
until the coordinator commits this protocol and separately starts that run.

## One fixed model, no search

Normalize each cached embedding to unit Euclidean norm. For a training split,
let `X` be the row matrix of these vectors and `Y` the matrix of raw ingredient
masses in grams. Its columns are exactly the ingredient IDs with positive mass
in that training split. An ingredient absent from a training dish has target
zero; zero-mass entries with zero nutrients are ignored. No held-out ingredient
vocabulary, catalogue entry, mass, or nutrient value enters model fitting.

Center using training means only: `Xc = X - mean_train(X)` and
`Yc = Y - mean_train(Y)`. Fit the **linear** kernel-ridge model

`alpha = (Xc @ Xc.T + 1.0 * I)^(-1) @ Yc` and `B = Xc.T @ alpha`.

The intercept is `mean_train(Y)`. For query vector `x`, use
`g = max(0, mean_train(Y) + (x - mean_train(X)) @ B)` componentwise.
This is the unaveraged squared-loss objective with L2 penalty `lambda = 1.0`.
It is **not RBF**, not a direct MAE fit, and has no logarithm/square-root target
transform, kernel bandwidth, `k`, lambda sweep, pruning threshold, fitted global
mass multiplier, or post-hoc parameter change. Negative grams are truncated to
zero. Positive predictions, however small, remain in the quantitative prior.
The full vector is a regression prior, not a claim that every positive ID is a
visually verified food or a fabricated Sol item list.

For each ingredient, derive the fold catalogue from training rows alone:
`density_per_100g = 100 * sum(training nutrient amount) / sum(training grams)`.
Calculate total weight by summing predicted grams and all four nutrients by
summing `grams * density / 100`. A held-out ingredient absent from the training
catalogue has no model output; its missed mass is counted in composition error.
Do not borrow a density or an ID from the held-out row.

If every predicted gram is zero, use that fold's componentwise median of the
**official five dish targets**, mark a whole fallback, and emit no invented
ingredient decomposition. Invalid/missing inputs or numerical solve failures
stop the experiment; they are not row deletion or a new hyperparameter choice.

## Fixed grouped OOF procedure

Take the distinct screening-group strings, sort by
`(SHA256(UTF8("external-gram-prior-r5.1\0" + group_id)), group_id)`, and assign
the sorted positions round-robin to folds `0,1,2,3,4`. This makes 46 groups per
fold for the registered population, rather than risking empty/unbalanced folds
through `hash % 5`. Every row of a group remains in that fold.

For each fold, fit normalization means, intercept, coefficients, ingredient
vocabulary, densities, and official-target median fallback on the other four
folds only. The held-out embedding is label-free input. All held-out ingredient
and official dish labels are used only after its prediction, for scoring. Cached
gallery captions/vectors may be reused because their original generation did
not receive ingredient/mass/nutrient labels. A future loader must verify their
original seals, image association and source hashes without opening protected
development/validation inputs.

Predict every held-out row once. Assemble all 230 OOF results before computing
aggregate metrics. Record fold assignments, train/held-out group counts, and
training IDs used by each fit. This OOF experiment estimates usefulness on the
external training population; it is not independent final acceptance.

## Comparison and advance gate

For each of weight, energy, fat, carbs and protein, compare full-population OOF
MAE against the corresponding same-fold official-target median baseline. All
fallback rows remain in both denominators. No confidence interval, paper cap,
per-target model splicing, or development-based selection is required here.

Advance only if **all** these prespecified conditions hold at full precision:

1. At least three of the five candidate MAEs are strictly smaller than baseline.
2. The arithmetic mean of the five `candidate_MAE / baseline_MAE` ratios is
   strictly below 1.
3. No individual ratio exceeds 1.10.

A zero or nonfinite baseline MAE makes the gate invalid/rejected; never serialize
infinity or treat an undefined ratio as zero/pass. A tie does not count as an
improvement. Gate failure means no Sol experiment using this prior. Gate success
only means a separately registered Sol-prior experiment may be worth testing.
Any later Sol run uses the user's existing unlimited paid-development
authorization and must be explicitly launched by the coordinator after its
method is registered. Passing this gate does not claim an MAE target was reached.

Report composition diagnostics without changing predictions: predicted-positive
ID count and count with at least 1 g, negative grams/count removed by the fixed
truncation, mass assigned to IDs truly absent in that held-out dish, its fraction
of predicted ingredient mass, omitted true-ID mass, and ingredient-vector L1
error. The 1 g threshold is reporting only. These ingredient diagnostics exclude
whole fallbacks and explicitly report their excluded count; five-target MAEs
always include all 230 rows.

The accepted training source contains one dish whose official weight is 2 g
less than the ingredient-mass sum. Preserve it unchanged. **Official five dish
totals are the OOF scoring truth**; the candidate is computed from predicted
grams and fold densities. Report official-minus-ingredient total discrepancies
with the existing 0.001 absolute diagnostic tolerance, without relabeling either
side or forcing the model's component total to the official reference.

## Minimal implementation and review boundary

`src/gram_prior.py` is pure NumPy and standard Python. It supplies `assign_folds`,
`fit`, `predict`, `evaluate_oof`, and the independent arithmetic `advance_gate`.
Inputs are explicit in-memory training rows/vectors/ingredient records/official
targets. There is no filesystem, image, network, provider, or global dataset
loader in that module. Tests use invented 3,072-vectors and invented labels.

After protocol commit and an explicit coordinator launch, a small train-only adapter may
read the exact released training files and gallery seal, hash its source/input
bindings, call this module, and write aggregate results plus private OOF/fold
audit. It must enforce the registered 230/230 population and retain the source
weight discrepancy. No new ArtifactStore framework is needed. The existing
round-four execution/continuation sources, protocols, predictions and seals are
not modified.
