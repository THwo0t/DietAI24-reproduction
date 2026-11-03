# Independent training gallery — implementation checkpoint

The previous failed development iteration is backed up on GitHub. Final reports
remain deferred. Round 4 source and offline tests are implemented; its new
230-image download is approved and complete. All 230 images passed blind
duplicate screening; the fixed training-only 13-image service probe passed in
one call. The original 84-image development and 200-image validation populations
remain unchanged, and validation stays sealed.

The new base predictor uses only independent training labels for its ingredient
catalogue, four visual examples and fallback. Development labels enter only the
separate scorer after the complete base run is sealed. This is a supervised
domain adaptation experiment, not a claim that the paper's MAE has been reached.

## Execution order

Run from `optimization_sol_20261102/mae_v2` with the existing project environment.
These are instructions for the next authorized stage, not an execution receipt.

1. `../../.venv/bin/python -B round4/tools/download_train.py` checks the pinned
   proposal offline. Only after the current user approves this exact new download,
   add `--authorized`. The fixed 230 files are approximately 105 MB; cumulative
   response-body reservation is capped at 350 MB, with three attempts per file.
2. `../../.venv/bin/python -B round4/src/train_data.py --prepare` checks the complete
   receipts, quarantines byte/RGB collisions and publishes a training-only
   release. It never replenishes excluded images or opens protected images.
3. `../../.venv/bin/python -B round4/src/capability_probe.py` checks the fixed first
   13 accepted training images offline. Add `--allow-paid` for the bounded
   13-image service check under the existing paid-development authorization.
   At least 13 accepted independent images are required for this probe.
4. The resolved method is frozen in `PROTOCOL.md`; keep `PROTOCOL_DRAFT.md` as
   historical evidence. A single source mass discrepancy is explicitly registered
   in `TRAINING_DATA_EXCEPTION.md`, with all original labels retained.
5. `../../.venv/bin/python -B round4/src/run_base.py preflight`
6. `../../.venv/bin/python -B round4/src/run_base.py gallery --allow-paid --workers 4`
7. `../../.venv/bin/python -B round4/src/run_base.py base --allow-paid --workers 4`
8. `../../.venv/bin/python -B round4/src/score_dev.py`
9. `../../.venv/bin/python -B round4/src/calibrate_j.py` applies the one separately
   registered grouped OOF candidate after the full base seal; it preserves raw
   records and seals adjusted predictions before evaluating/selecting a profile.

Every completed phase verifies without constructing a provider. Interrupted
phases retain exact stage inputs and durable provider attempt limits; do not
delete artifacts, change namespaces, or rerun inaccurate answers. The scorer
keeps all 84 Nutrition5k queries, includes the unchanged 99 ASA24 records and
reports every threshold at full precision. It neither fits nor selects a model.

## Engineering checks

The synthetic suite runs with network disabled on this Linux host:

```bash
unshare -rn ../../.venv/bin/python -B -m unittest discover -s round4/tests
```

It covers isolation, official versus third-party routing, exact image payloads,
format-repair bounds, failure propagation, training-median fallback, persistent
budgets, crash recovery, concurrent stages and read-only completed verification.
The current expanded suite passed 213 tests, including the exact source exception
and calibration isolation/selection negative paths.
The full pipeline test uses invented images and fake providers; it is not an
online capability or accuracy result. Platform integration on Mac is still
deferred, as previously agreed.

## Public backup scope

The public checkpoint contains code, synthetic tests, protocols and safe
aggregate readiness metadata. Private fixed image inventories, downloaded or
research images, training labels, per-image predictions, raw provider logs and
credentials are excluded. An incomplete research checkpoint is not a portable
final demonstration release. Final English reports and Mac delivery will be
updated after the optimization outcome is ready.
