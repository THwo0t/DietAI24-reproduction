# Posthoc exploration of Nutrition5k statistical corrections

Date: 3 November 2026. This is development-only exploration after the registered
v2 selection. It changes no registered candidate, selection, acceptance gate,
run artifact, protocol or report. It is not independent validation and does not
justify opening the sealed validation set.

## Conclusion

None of the eight tested correction families reaches even one of the ten N5
checks on the unchanged population of 84 development images in 78 association
groups. A training-only density correction improves several errors, especially
carbohydrate, but protein remains about 2.18 times its absolute MAE cap. These
results do not support expecting 10/10 from global statistical corrections of
the existing C totals alone. They do not establish an impossibility result for
new features or other models.

| Method | Weight MAE g | Energy MAE kcal | Fat MAE g | Carbs MAE g | Protein MAE g |
|---|---:|---:|---:|---:|---:|
| Raw C reference | 82.988 | 126.693 | 8.628 | 14.582 | 11.228 |
| Registered calibrated C reference | 78.396 | 118.500 | 8.318 | 13.201 | 11.085 |
| Five independent multipliers | 76.822 | 109.586 | 8.019 | 9.020 | 11.103 |
| Multipliers shrunk halfway to one | 78.880 | 115.111 | 8.156 | 11.043 | 11.084 |
| Residual median offsets | 80.357 | 123.045 | 8.633 | 13.997 | 11.295 |
| Raw and training median mixture | 81.594 | 108.145 | 7.738 | 9.318 | 11.088 |
| Nonnegative slope and free intercept | 78.992 | 107.118 | 7.680 | 8.169 | 11.083 |
| Nonnegative density correction | 76.822 | 104.935 | 7.672 | 8.206 | 11.001 |
| Halfway density correction | 78.880 | 109.608 | 7.835 | 10.017 | 11.017 |
| Training median only | 126.714 | 166.839 | 9.990 | 13.101 | 15.949 |
| Nested choice of one entire family | 81.080 | 113.635 | 7.996 | 9.700 | 11.436 |
| Effective cap for both checks | 58.630 | 87.648 | 4.958 | 6.813 | 5.044 |

All rows above other than the caps are 0/10. The effective cap is the smaller of
the published absolute cap and the per-unit cap multiplied by this population's
mean reference value. Per-unit is MAE divided by the mean reference, not MAPE.
Protein requires about a further 54% MAE reduction from the displayed density
model to meet its 5.044 g cap. Even the lowest displayed carbohydrate MAE,
8.169 g, exceeds both the absolute 7.774 g and effective 6.813 g caps.

## Fit and population controls

Every exploratory feature is from `C/predictions.json` raw five-target vectors.
The saved registered calibration is read from `C/calibration-round1.json`, whose
predictions reproduce the selected aggregate metrics. `C/oof_predictions.json`
contains the uncalibrated first-stage vectors; it is not the retained calibrated
reference. No saved calibrated OOF vector is fed into a second learned model:
its training-row values could otherwise indirectly depend on an outer held-out
label through the earlier calibration.

All 84 rows have a successful original C prediction; no fallback or missing row
was removed. The existing five grouped folds have 17, 16, 17, 16 and 18 rows.
Every median, multiplier, intercept and density coefficient is fitted on the
other four folds, with no association group shared across training and held-out
sets. The fit loss is image-weighted absolute error, matching the evaluation
denominator. Coefficients are nonnegative where specified; additive and affine
outputs are clipped at zero. The exact two-coefficient LAD solution enumerates
residual-line intersections and constraint-boundary minima. There is no random
optimizer, fitted full-data feature scaler, new image call or external data.

The density family predicts each nutrient as `a * raw nutrient + b * raw weight`
with `a,b >= 0`, and predicts mass with one multiplier: nine coefficients in
total. This is a low-dimensional correction of predicted density. It is not a
physically reconciled food composition model. Independent target calibration
and intercepts also depart from v2's registered one-mass-factor rule; a future
protocol would have to state that explicitly and decide how energy and nutrient
consistency will be enforced.

## Selection optimism and stability

The table reports every specified family rather than concealing unsuccessful
ones. Choosing its best row after observing these OOF outcomes remains
optimistic. The density family has the lowest displayed worst normalized error,
2.181, compared with 2.198 for registered calibration. Its outer-fold worst
ratios range from 1.734 to 2.722, so none of its folds meets all ten checks.

A separate nested calculation chooses one complete five-target family using
only the other four folds' inner OOF predictions, ranks by maximum ratio, mean
ratio, coefficient-count proxy and fixed family order, refits that family on
the outer training set, and scores the untouched outer fold. Inner choices are
median mixture, half density correction, multiplier, median mixture and half
multiplier. The combined outer result is still 0/10 and its worst ratio rises
to 2.267. This is evidence against treating the best displayed family's small
protein gain as a reliable general improvement. The original choice of C itself
was made on this same development cohort; this nesting cannot undo that earlier
selection or the posthoc choice of the present model families.

Descriptive paired resampling of the 78 association groups, 10,000 replicates,
gives the displayed density family's MAE differences from registered calibration:

| Target | Difference | 95% descriptive interval |
|---|---:|---:|
| Weight g | -1.574 | [-5.306, 2.071] |
| Energy kcal | -13.565 | [-29.038, 1.137] |
| Fat g | -0.647 | [-1.641, 0.311] |
| Carbs g | -4.995 | [-8.176, -1.948] |
| Protein g | -0.084 | [-0.676, 0.529] |

These intervals hold fitted OOF predictions fixed: they do not refit the models,
account for model selection or prove physical independence of association groups.
They are not inferential acceptance tests. The independent carbohydrate factors
are relatively stable across training folds, 0.631 to 0.633; this supports a
systematic correction hypothesis for carbohydrate, not a solution to protein.

## What further information is needed

Two deliberately infeasible diagnostics use reference labels at prediction time.
They are neither candidates nor algorithm results. Substituting the true total
mass while retaining raw C's densities yields nutrient MAEs 94.959 kcal energy,
8.228 g fat, 13.060 g carbohydrate and 8.614 g protein. None of the eight nutrient
checks passes; only the two mass checks pass by construction. Thus perfect total
mass alone is insufficient for the current inferred composition. Conversely,
substituting the true nutrient densities while retaining raw total mass yields
82.988 g mass, 95.203 kcal energy, 4.882 g fat, 6.821 g carbohydrate and 7.022 g
protein MAE: only three checks pass. Both mass and composition need attention;
these substitutions do not identify which recognition, amount, preparation-state
or database-density error is causally responsible for each residual.

A defensible next step is a small, separately specified experiment that extracts
component-level evidence useful for protein and mass: explicit protein-bearing
components, edible versus nonedible parts, cooking state, relative thickness or
volume, and visible sauces or oils. These are hypotheses about useful features,
not findings from image inspection; this analysis opened no images. Single RGB
does not supply a known physical scale unless a real reference is available.

Before another paid pass, a bounded offline alternative could assign the
existing raw leaves to a few broad food classes using only their label-blind
descriptions or catalog metadata, and fit a small nonnegative class correction
inside training folds. The class mapping, parameter count and shrinkage must be
fixed without consulting held-out nutrient errors. This has not been tested
here. It should not become an expanding per-food or per-code lookup on 78 groups.
Whichever route is chosen, register a few candidates, retain the full population,
fit all preprocessing inside the folds, and use nested selection when comparing
calibrations. Repeated tuning of the same 84 rows cannot create an independent
acceptance set.

## Reproduction and evidence

From `mae_v2`, using the existing Python 3.10.13 environment:

```sh
../../.venv/bin/python -B -m unittest discover -s analysis/next_round_exploratory -p test_explore.py -v
../../.venv/bin/python -B analysis/next_round_exploratory/explore.py
```

Eight synthetic tests cover grouped fold leakage, outer-label isolation in both
fit and inner selection, full denominators and missing-value rejection, the
per-unit definition, and exact constrained two-parameter fitting. `results.json`
contains only aggregate scores, fold-level coefficients, input hashes and
runtime provenance; no row identifiers, labels, images or predictions are
exported. The seven exact text inputs are allowlisted in the script. The two
development text artifacts are hash-checked against the freeze; image artifact
entries are neither opened nor hashed. Source input hashes are rechecked before
the isolated result is written. No API calls or validation access occurred.
