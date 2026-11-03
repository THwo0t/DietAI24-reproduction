# Candidate J calibration protocol — registered before J result access

Date: 3 November 2026. Implementation and synthetic testing are authorized.
No J predictions, J scores or new training images were accessed to choose this
method. This document registers exactly one supervised postprocessing candidate;
it does not authorize changing the base method or opening formal validation.

## Fixed candidate and disclosed departure

Fit five independent multiplicative corrections to the raw whole-meal targets
`weight`, `energy`, `fat`, `carbs`, `protein`. For each target, enumerate raw
factors `0.500, 0.501, ..., 2.000` and minimize the sum of absolute errors on the
eligible training observations. Resolve equal losses by distance from 1, then
the smaller raw factor. Apply `1 + 0.5 * (raw_factor - 1)`, giving the fixed
applied range `[0.75, 1.5]`. Fit on the unshrunk factor and shrink only afterward.
Use full precision for all loss, threshold and selection decisions.

This deliberately replaces the earlier proposed raw range `[0.8, 1.25]`. The
narrow range is not another candidate in this round. Do not change the range,
grid, shrinkage, objective or inclusion rules after seeing J results. There are
no target-specific searches, intercepts, clipping, image rules or error trimming.

Five independent factors change aggregate predictions and need not be consistent
with the raw leaf masses and catalogue densities. Preserve every raw record and
its leaves/densities unchanged. New records explicitly identify calibration as
aggregate-only and identify leaf accounting as applying to raw predictions only.
Do not fabricate adjusted ingredient masses or densities to explain the totals.

## Integrity and fitting population

Before reading development labels, verify the completed J base through
`run_base.base(verify_only=True)`: exactly 84 Nutrition5k records, no provider
construction, no validation access, a complete external-only training binding,
and the unchanged frozen base sources and training release. Verify the base
intent/completion bindings and the registered development manifest SHA-256
`ec02c058653b5505b01abee882c8b04a4711ec93b0c08496b962c2faf1586fe9`.

The manifest has 84 Nutrition5k images, 78 conservative association groups and
the original five folds; every group belongs to exactly one fold. The full
development manifest also has the preserved 99 ASA24 images / 23 groups. Pin
development labels to
`b29dedc788c1facee28afd32c96fe22a897b6a220ddd786e43957ec9ef5b5849`,
preserved ASA prediction source to
`91671dcd2b885cfeaf59544698bb0e84ad3579a2b2784c9aa98b4f3e0df434de`,
and reviewed `opt_metrics.py` to
`15d71fd2c2379f7f723707cddfeb2e2868c0dd84b027edd12ef9185303a1e63e`.

Each outer fold fits only the other four folds; exclude the held-out fold and
all its group IDs before any training labels enter the fitter. Eligibility is
fixed without residual inspection: include every valid raw base estimate with
`fallback=False`, including successful format repairs and rerank method
fallbacks. Require all five finite nonnegative targets and positive raw weight.
Malformed or missing records are integrity failures, not dropped observations.
Whole-query fallback records are excluded from fitting and remain unchanged
when applying calibration. If fewer than five distinct eligible training groups
remain for a fold, use factor 1 for all targets. A target with an identically
zero raw predictor naturally resolves to factor 1 by the registered tie-break.
Fit each target with equal observation weight, matching per-image MAE.

The external gallery, catalogue, support references and base fallback depend
only on the independently released new training data. Therefore base predictions
used to fit an outer calibration fold do not depend on that fold's labels, and
ordinary grouped five-fold calibration needs no additional inference calls.
This reasoning does not apply to a future hybrid gallery using old dev labels.

## Outputs and one whole-profile decision

Retain all 84 observations in the OOF calibrated population, including unchanged
whole fallbacks. Independently seal all 84 calibrated records, five fold fitting
audits (training IDs/groups, eligible IDs/groups, raw/applied factors and fitting
losses), and one final factor set fitted on all eligible development observations
for possible future unseen inputs. The final all-development factors must never
be used to score these 84 observations as OOF results.

Report the raw and calibrated full ten Nutrition5k checks, absolute MAE, per-unit
MAE, grouped bootstrap confidence intervals and failure counts. Also report both
joint twenty-check summaries using the exact preserved ASA predictions. Use the
reviewed evaluator with 10,000 group bootstrap draws and seed 20261102. Raw J
records and original scoring artifacts remain untouched.

Choose one complete Nutrition5k profile, never a target-wise mixture. The
calibrated profile is eligible only if every check already passed by raw J still
passes. Among eligible profiles compare the maximum of the ten full-precision
MAE-to-cap ratios first, then their arithmetic mean: choose calibrated only if
its maximum is strictly smaller, or if the maxima are exactly equal and its mean
is strictly smaller. An exact tie selects raw. ASA remains unchanged in either
case. Record the selected profile and the reason without changing the original
base selection or publishing a formal-validation claim.

All outputs are scoped `development_not_independent_validation`. Repeated method
development remains a source of selection optimism. Calibration makes no API
calls and performs no image inference or validation access. Its mandatory base
integrity verifier may reread already-bound training/development images to check
their hashes; the calibration module itself reads no images. Existing paid
authorization is unaffected.

## Immutable execution and checks

Bind this protocol and calibration/scoring source hashes, base completion and
record hashes, external training proof, pinned manifest/labels/ASA inputs and
the fixed algorithm configuration. Freeze calibrated predictions and parameter
audits before producing evaluation/selection artifacts in a separate seal.
Completed runs recompute and compare read-only; changed inputs or results are
rejected, not overwritten. Synthetic tests must cover hand-computed factors,
missing labels/records, fallback denominators, fold/group isolation, held-out
label poisoning, unchanged raw leaves, deterministic ties and whole-profile
selection. Do not execute against actual J while implementing or testing.
