# Region-atlas training pilot

Read `PROTOCOL.md` and `CHECKLIST.md`. This is a 25-query, five-fold external
training pilot, with a paired raw-J baseline and one region-atlas candidate.
It has no new download, embedding call, calibration, development inference or
validation access. Sol remains the visual/main model.

Implementation and 95 network-disabled synthetic tests completed before new
user steering. No L API request, real preflight or training-region annotation
has started. This N5-only pilot is now shelved: the CLI refuses `base`, including
`--allow-paid`. Its source is preserved for possible engineering reuse. Existing
tests of injected synthetic `base()` execution do not authorize real inference.

Every subsequent full candidate must use a defined common method on both
ASA24 and Nutrition5k and obtain fresh predictions for both. Old ASA results
cannot be used as L/J/K scores. Complete project review and a new dual-dataset
protocol must precede further paid experimentation. Existing download and paid
development authorization persists; this is a scientific scope correction.

The previous failed K iteration and completed posthoc diagnostic are backed up
at public commit `111ec3dc7f6a70f605d3a0d90b93ab68d814dd27` on
`THwo0t/DietAI24-reproduction`, branch `codex/mae-v2-backup-20261103`.
Raw J remains the selected development method and still fails all N5 checks.
ASA remains unchanged. Validation is sealed and final reports remain deferred.
