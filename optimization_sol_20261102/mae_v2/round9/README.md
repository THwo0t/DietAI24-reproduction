# Round9 zero-API diagnostic

Read PROTOCOL.md. This directory contains a label-informed mathematical bound,
not a deployable estimator or an accuracy claim. No paid requests, data downloads
or independent validation belong here. Preserve all frozen N files.

The old environment remains unchanged. The local diagnostic uses Python3.10.13,
its existing NumPy1.26.4 and SciPy1.15.3 installed with `--no-deps --target` under
the ignored `runtime/packages`. The pinned wheel is retained under
`runtime/wheels`; runtime member and wheel digests enter the private freeze.
SciPy API: https://docs.scipy.org/doc/scipy-1.15.3/reference/optimize.linprog-highs.html

From the project root, synthetic tests require no research data:

```bash
unshare -Urn .venv/bin/python -B -m unittest discover \
  -s optimization_sol_20261102/mae_v2/round9 -p 'test_*.py' -v
```

Only after the independent review, fixes and immutable freeze, the guarded
coordinator may call `run_diagnostic.run()` once. It requires complete N scoring,
both full development cohorts, pinned runtime and review gate. Private artifacts
store aggregate results and oracle witnesses separately. Do not rerun after a
completion seal: inspect existing aggregate evidence instead. Public exports
must exclude oracle weights, sample IDs, labels and original API logs.

The once-only diagnostic has completed. Do not execute it again. Read
`joint_checkpoint.json` and `DECISION.md`. Its guarded entrypoint was
`unshare -Urn .venv/bin/python -B .../round9/guarded_run.py`; the direct runner
now refuses execution. The constructive all10-check oracle is not a predictor.
