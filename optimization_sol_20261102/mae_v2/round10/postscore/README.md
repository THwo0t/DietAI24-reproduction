# Separate completed-O diagnostic

This helper is outside O's frozen inference modules. It cannot fit, select,
bootstrap or send a prediction request. Do not execute on a partial batch.
The original completed scores, verification, source/input bindings and private
artifact seals must agree before any development label is opened. It uses
the existing raw/OOF outputs, not a new calibration fit. Validation is excluded.

After the same O follower reaches `development_scored`:

```bash
unshare -Urn .venv/bin/python -B optimization_sol_20261102/mae_v2/round10/postscore/guarded_diagnose_o.py
```

The wrapper forbids network/Provider/key/image/validation access and protects
earlier prepared/run/service files by size/mtime. The once-only private seal
is `round10/diagnostics/completed_o`; an existing completion refuses recompute.
Inspect its existing aggregate instead. No new predictor or threshold is chosen.

The aggregate reproduces point errors with full denominators, signed bias and
error concentration; checks standard/unit/gram accounting; and decomposes
whole-serving nutrient error into symmetric mass and density algebraic terms.
Those terms can cancel and are not additive MAE contributions or ingredient
causes. Missing component annotations prevent a true omission/duplication or
recipe-cause rate. ASA continuous-to-option diagnostics are separate from the
official conditional legal-option scores, which retain all Exact fallbacks.
