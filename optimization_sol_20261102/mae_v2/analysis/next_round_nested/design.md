# H grouped nested calibration: design only

This is a development-only design, not an implemented or executed API run.
It does not change H/G, their bindings, or their as-run protocol. The population
is **84 Nutrition5k development images / 78 groups**, not the historical 100.
ASA24 stays unchanged; validation remains sealed.

## Strict outer/inner construction and cost

Use the five existing group folds, with image counts `[17, 16, 17, 16, 18]`.
For outer held-out fold `f`, generate a new calibration-training prediction for
each image in every other fold `g`. Each such prediction must exclude **both
`f` and `g`**, including all their association groups, from:

- The ingredient catalog and all density/name/support statistics.
- The gallery eligible for the same label-blind four-example selector.
- The four examples' ingredient/mass references.
- The whole-dish median used if inference fails.

The query's uncalibrated C feature and other eligible rows' raw C features can
be reused because they are label-blind. Pass only the eligible gallery to the
selector; require four distinct groups and retain the existing hard failure.
Do not put either excluded fold's labels into a prompt, fallback, catalog,
example-selection feature, or calibration fit. Hash the excluded-fold pair,
eligible groups, catalog, support assignments, source/config and responses.

Each outer fit then sees `[67, 68, 67, 68, 66]` inner predictions respectively:
**336 additional primary image requests total**, not 336 per calibrator.
There are ten unordered excluded-fold pairs; their catalogs can be cached,
but their image predictions still total 336. At most one structural repair per
prediction gives 672 logical requests; the existing three-transport-attempt
cap gives at most 2,016 HTTP attempts. Attempts and charged usage are distinct.
Do not assume exact cached requests exist. Expected spend is roughly four H
batches, with smaller inner catalogs; price it from completed H usage before
any decision to run. All requests retain at most four workers.

Apply each outer fit only to the **existing raw H predictions of fold `f`**;
these already excluded `f` from their catalog/gallery. No new 84-image outer
inference is required if the H source, request and raw-response bindings remain
unchanged. Keep all 84 evaluation images and their whole-dish fallbacks.

Ordinary H OOF predictions cannot train an outer-`f` calibrator: a prediction
for a training row in fold `g` excluded `g`, but its catalog was built with
fold `f` labels. The problem persists even if its four chosen images happen
not to be in `f`. Only exact equality of the complete allowed request/catalog/
support/source bindings could justify mechanical cache reuse.

## Two finite calibrators sharing those 336 predictions

Register both options, the fit rule and retention rule before generating inner
predictions; select a whole method, never the best target/image separately.
Both use the previous raw grid `0.800..1.250`, step `0.001`, then
`applied_factor = 1 + 0.5 * (raw_factor - 1)`, giving **`[0.9, 1.125]`**.
Do not widen the grid or drop shrinkage after inspecting a result.

1. **One shared mass factor.** Fit on successful inner predictions using the
   existing lexicographic objective: worst of ten threshold ratios, mean ratio,
   distance from one, then grid order. Multiply every predicted ingredient's
   grams by the same applied factor and recompute all five quantities with the
   existing known/model-density sources. This preserves ingredient accounting.
2. **Five target factors.** Fit one grid factor for each of weight, energy, fat,
   carbohydrate and protein by its training MAE, with distance from one and grid
   order for ties, then apply the same 50% shrinkage. This is a separate
   aggregate calibration method: independently scaling nutrients no longer
   equals the known catalog's original grams-times-density result. Retain raw H
   items/totals and disclose that loss of physical accounting; do not claim
   unchanged H nutrient calculation or silently edit catalog densities.

As in prior v2 calibration, exclude failed inference records from fitting,
require at least five eligible training groups, and use factor one when the
minimum fails. Evaluate all rows. A failed query keeps its registered
training-only whole-dish median, unscaled. Log this policy and eligibility
counts; do not treat failure filtering as removal from the scoring population.
The existing generic few-shot calibration prohibition must not be bypassed:
any implementation needs a separate adapter that verifies these nested proofs.

The inner catalogs/gallery use three folds (49–52 images), while each outer H
query used four folds (66–68). This is ordinary base-model refitting in a nested
stack, but the changed catalog coverage can make fitted factors transfer poorly.
Group isolation prevents leakage; it does not guarantee that calibration helps.

## Final fit and fixed inference state

After choosing the calibrated family using the nested outer development
results, fit its final factor(s) on **the original 84 ordinary raw H OOF
predictions**, paired with their 84 development labels, using the same grid,
shrinkage and eligibility rules. Each prediction excluded its own fold; at
this final-fit stage there is no held-out development fold whose labels must
be excluded from other training features. Do not train on the 336 repeated
inner predictions, average the five outer fitted parameters, or use historical
inactive rows. Never report final-fit rescoring of these same 84 predictions
as another unbiased OOF result; report the nested outer result instead.

Build the deployment catalog once from **all 84 development images / 78 groups**
and freeze its per-ID names/densities. Freeze the same 84-image eligible gallery,
their development ingredient references, raw C feature vectors, official
embedding inventory, selector code and deterministic tie-breaks. A new query's
label-blind C feature selects four distinct development groups; the query's
reference ingredients/weight/nutrients never participate. Bind the all-dev
fallback median, final calibrator and complete source/config/image/catalog
hashes. Any blind association exclusion required by the cohort protocol still
applies. No validation labels may construct this state or alter its selection.

## When calibration is not worth the cost

Do not start 336 calls just because a method misses a threshold. First inspect
the completed H aggregate errors and existing unknown/failure audits. A stable
same-direction multiplicative bias is a plausible target; omitted foods, wrong
catalog IDs, missing classes, cooked/dry ambiguity, and plate-dependent portion
errors are not repaired by a small global multiplier. Earlier raw-C scalar and
code-bucket OOF explorations scored 0/10; this is cautionary evidence, not proof
about the still separate H result.

A free **post-hoc diagnostic only** can rule out this factor family: for each
existing H outer fold and each target, find the smallest held-out MAE over the
applied grid `[0.9, 1.125]` (step `0.0005`), retaining failures unchanged. This
uses that fold's own truth and is explicitly an oracle, never a candidate.
The pooled per-target minima optimistically relax both proposed methods. If
any minimum still fails either its MAE cap or its per-unit cap, neither the
shared-factor nor five-factor nested method with this fixed H base can pass
all ten checks on these 84 rows. Stop this calibration path. If the oracle
passes, that only shows numerical room; it does not establish learnability or
justify paid inference by itself.

A cheaper separately registered alternative uses only one fixed calibration
fold `g=(f+1) mod 5` per outer fold, excluding `f` and `g` from its base inputs.
It costs 84 additional primary requests, but fits each calibrator on only
16–18 images and has higher variance. It is not the full 336-prediction nested
design and should not be renamed as equivalent evidence. No API run or free
oracle computation is performed by this document.
