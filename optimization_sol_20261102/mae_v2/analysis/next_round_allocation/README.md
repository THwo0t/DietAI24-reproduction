# Development allocation diagnostic

This directory records post-selection research on the frozen 84 Nutrition5k
development images (78 association groups). It is not a formal report, a model
selection run, an acceptance result, or a promise of achievable accuracy.

From the repository root, using the already installed Python 3.10.13 / NumPy
1.26.4 environment:

```sh
unshare -rn .venv/bin/python -B -m unittest discover -s optimization_sol_20261102/mae_v2/analysis/next_round_allocation -p 'test_*.py' -v
unshare -rn .venv/bin/python -B optimization_sol_20261102/mae_v2/analysis/next_round_allocation/analyze.py
unshare -rn .venv/bin/python -B optimization_sol_20261102/mae_v2/analysis/next_round_allocation/analyze.py --check
```

No SciPy, API, installation, download, image read, validation data read, F output
read, or credential read is needed. The script directly opens a fixed five-file
allowlist and itself; it does not invoke a study or cohort loader. It verifies
that the selected result retained exactly the raw C leaves and raw vector,
checks leaf arithmetic and scalar-only share changes, checks group fold
separation, and rechecks input bytes before returning. The JSON contains only
aggregate statistics, hashes, solver settings, and five-fold fitted parameters.
It never exports sample IDs, groups, raw descriptions, row vectors, or labels.

The oracle starts from **raw C**, not a fit using each row's label. Its targets
then deliberately use that same row's four reference nutrients; the true-mass
scenarios also use its reference weight. This makes them diagnostic oracles,
not deployable predictions. All four C nutrient densities and food-code support
stay fixed. Shares are nonnegative and sum to one. The bounded variant restricts
each share to one-half through twice its original value; the free variant can
zero a leaf. A separate scenario fixes the selected C predicted mass instead of
using true mass. All scenarios keep all 84 images.

The objective is half the squared four-nutrient error standardized by fixed
per-dish MAE caps. This is not the acceptance MAE objective. Full-precision MAE
and per-unit MAE are evaluated separately with strict `<` comparisons. Per-unit
MAE is MAE divided by the population mean reference amount, not mean per-image
percentage error. Solver output reports convergence, feasibility, projected
gradient mapping, and the Frank-Wolfe gap. An approximate feasible solution is
still a valid existence witness for its measured error, but is not asserted to
be the optimal attainable value. The raw and selected C shares are checked to
coincide, so using raw shares with true mass is equivalent to removing the
selected scalar mass factor first.

The coordinatewise density interval diagnostic is an optimistic lower bound on
each nutrient separately. Different nutrients may need incompatible allocations;
these bounds are not jointly attainable predictions. Outside-support cases do
not distinguish wrong FNDDS density, wrong food identity, omitted foods, or
annotation differences. Current dev labels contain aggregate totals only, so
those causes are not separately identifiable here.

Two additional exploratory five-fold fits use only **raw**, uncalibrated C
features, train on the other group folds, and score the held-out fold: independent
target scalars and nine first-code-digit mass coefficients. Their settings are
fixed in the script. These are post-selection experiments on a repeatedly used
development set, not a nested selection study. Their results must not be
described as validation performance.

A possible later candidate would replace all oracle targets with independent
image-only F predictions. It would fix total mass to F's predicted mass and
project F's four nutrient targets onto the C-density support with a preregistered
positive prior penalty on raw C shares. That is a distinct, label-blind method;
it is **not implemented here**, and this directory reads no F artifacts. It
cannot create omitted components or correct code densities. Numerical failures,
fallbacks, and whether zero shares are allowed must be fixed before evaluation.
