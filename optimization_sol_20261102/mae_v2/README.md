# DietAI24 MAE v2

This directory implements the approved MAE-first second round and preserves
the previous study unchanged. The registered v2 development batch is complete: ASA24 passes 10/10 MAE checks, Nutrition5k passes 0/10. Formal validation remains sealed.
The saved completion record contains the outcome. Final reports are deferred by the user until optimization succeeds; a passing
software test does not establish that the MAE targets have been reached.

Start with `PROTOCOL.md` for the fixed scientific method, `CHECKLIST.md` for
implementation status, and `REVIEW.md` for the two independent reviews.

All development uses Sol for vision/chat and the original official OpenAI
embedding route. Local credentials are never packaged. Existing sealed
validation remains unavailable to development entrypoints.

## Research workflow

Run these commands from the original repository root, using its existing
research environment. The research workflow requires the private original
data and v1 response archives. The public Mac demonstration has a separate,
self-contained entry point described in `START_HERE_MAC.md`.

```bash
.venv/bin/python -B optimization_sol_20261102/mae_v2/src/study.py verify-dev
.venv/bin/python -B optimization_sol_20261102/mae_v2/src/study.py dev --allow-paid --workers 4
.venv/bin/python -B optimization_sol_20261102/mae_v2/src/diagnostics_v2.py
.venv/bin/python -B optimization_sol_20261102/mae_v2/src/report_v2.py
```

The second command makes paid requests and requires prior authorization plus
the two local credentials. The other commands are offline. `dev` resumes
completed stages and retains the persistent HTTP-attempt budget; it rejects
changes to its source, configuration, inputs or completed response seals.
Do not delete a cache or rerun a valid response to seek a better answer.
Concurrent development jobs are rejected by a process lock.

The diagnostic command runs only after the finite development batch completes.
It produces a training-fold median benchmark, a paired comparison on the same
Nutrition5k images and a reference-weight diagnostic. The last deliberately
uses true weight to explain residual nutrient error; it is never a prediction,
candidate, calibration choice or acceptance result.

`freeze` and `validate` remain blocked until all twenty development MAE checks,
the amended ASA24 coverage floor, completed data preparation and independent
checkpoint-one review pass. A completed formal batch cannot run again through
this entry point. Both arms must finish before reference nutrients are scored.
When development fails, keep validation sealed and report the remaining gaps.

## Evidence and delivery

- `runs/development/`: private response seals, candidate results, selection,
  usage and completion state. These files are excluded from publication.
- `analysis/`: paper limits and safe historical or post-selection aggregates.
- `reports/`: the English report, its aggregate evidence snapshot, and the
  portable demonstration profile after development finishes.
- `evidence/`: test, preparation, review and document-rendering evidence.
- `tools/`: portable offline/live demonstration and exact publication-package
  checks. Live demonstration requires explicit paid authorization and local
  credentials; offline demonstration requires neither.

The portable dependency lock covers inference and demonstration. Rebuilding
DOCX/PDF additionally uses the Codex document runtime and its renderer; those
authoring dependencies are not required to present saved results. The source
package includes research code, but private research inputs are not bundled.
Linux installation checks cannot establish actual Mac hardware compatibility.
