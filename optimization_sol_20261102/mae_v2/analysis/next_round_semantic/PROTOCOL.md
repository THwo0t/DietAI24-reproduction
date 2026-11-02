# Fixed semantic-neighbor development exploration

Registered before this exploration is evaluated, 3 November 2026. This is a
supervised retrieval method, not the original FNDDS inference pipeline, a formal
candidate selection, or independent validation. Prior eight-family experiments
used global corrections of five C totals; none used semantic-neighbor labels.

- Population: all 84 Nutrition5k development images / 78 association groups in
  the existing five folds. No row filtering, imputation, new split, validation
  access, image access, API call, or new embedding. Invalid/missing inputs fail.
- Features: call the unchanged `round3/src/examples.py::build_features` on the
  original, uncalibrated C records and frozen FNDDS embedding arrays. It takes
  the L2-normalized code-embedding mean weighted by raw leaf grams. No H/G/I
  predictions, query truth, train errors, label-derived features, or fitted
  feature transform enter retrieval.
- For each query, exclude its entire fold and association group. Sort eligible
  rows by descending cosine similarity, then ascending sample ID. Keep the first
  row from each distinct training group, then take the top k. This chooses each
  group's most similar member before the top-k cut. No similarity cutoff and
  no relaxed rule if fewer than k groups are available.
- Fix k to **3, 7, 15**. Equal neighbor weights mean ordinary componentwise
  median; cosine ranks but never weights the references.
- Family A: five componentwise medians of the neighbors' true totals.
- Family B: median true weight; each other target is that weight multiplied by
  the median of that target's **per-image target / true weight** ratios among
  the same neighbors. Positive reference weights are required. This is a
  median of densities, not a ratio of medians or pooled density.
- For every family/k pair also predict the fixed 50/50 arithmetic blend with
  the query's raw C five-target vector. Exactly **12 candidates**, with no
  adaptive k, targetwise winner mixture, fitted blend, or posthoc retries.
- Retrieval is completed without a labels argument. Per-query estimation is
  given only the selected training labels; current query and same-fold labels
  are unavailable at that boundary. Scoring uses the complete development
  references only after predictions are produced.
- Score each fixed candidate and raw C using the unchanged `opt_metrics`
  definition: full-population MAE and MAE / population reference mean, ten
  published checks, full-precision comparisons. Export all 12 outcomes, no
  row identifiers/truth/predictions. Include per-target signed error, fold
  aggregates, input hashes and neighbor-isolation verification counts.
- This is posthoc development exploration after C was already selected on these
  data. Comparing the 12 OOF results does not provide unbiased model-selection
  performance or authorize opening validation. No winner becomes selected.
  Independent medians and blends need not correspond to a coherent leaf-level
  mass/density decomposition. No metric improvement is promised.

Recompute from `mae_v2` with the existing environment:

```sh
../../.venv/bin/python -B -m unittest discover -s analysis/next_round_semantic -p test_explore.py -v
../../.venv/bin/python -B analysis/next_round_semantic/explore.py
```

The script writes only `analysis/next_round_semantic/aggregate.json`, rejecting
a different existing result. Synthetic negative tests exercise the production
selector and estimator directly; tests require no private data or network.
