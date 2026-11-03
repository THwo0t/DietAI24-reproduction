# M common-method development

Working research source, not a final report or an accuracy claim. Protocol,
source and private preparation are frozen after one independent review and the
R7-G-1 fix.38 synthetic tests and a guarded real offline preflight passed.
Original runs, K and the shelved L are immutable. Validation remains sealed.

From the original repository root, use its existing project virtual environment:

```sh
.venv/bin/python -B optimization_sol_20261102/mae_v2/round7/src/run_m.py preflight
.venv/bin/python -B optimization_sol_20261102/mae_v2/round7/src/run_m.py base --allow-paid
.venv/bin/python -B optimization_sol_20261102/mae_v2/round7/src/run_m.py verify
.venv/bin/python -B optimization_sol_20261102/mae_v2/round7/src/run_m.py score
```

Check the private launch receipt before `base`: never start a second coordinator.
Completed pairs/stages and every payload reservation survive interruption. Service
or integrity faults stop the batch; resolve their evidence without resetting
budgets. Completed `verify` constructs no Provider/credential reader, reparses
each exact scientific payload and changes no artifacts. Score runs only after
all183 paired records and the service proof are sealed, then loads dev labels.

The initial `prepare` phase already ran. It alone loads development labels to
prepare fixed other-fold median fallbacks. It also reconstructs raw-C N5 requests
and explicitly inventories old official embedding successes without paid calls.
The predictor's runtime loader opens no query-label file. Existing preparation
and freeze writes are immutable; drift is an integrity error, not permission to
overwrite or restart. No additional download is required.

M0 uses raw C on both datasets, importing only the exactly replayed84 historical
N5 computations. ASA M0 is newly inferred. M applies the same zero-shot FNDDS
whole-or-components accounting core to both datasets, with no labeled gallery,
examples, crops or calibration. Failure medians are supervised aggregate
postprocessing outside that core and are reported as a methodological deviation.
ASA primary remains the explicitly conditional option task; full-population E2E,
coverage, failures, common-Exact comparisons and strict20/20 remain visible.

New service logs/counters/caches live only in `round7/provider/M`; scientific
stages and completion seals in `round7/runs`. Public backups contain an explicit
source/aggregate inventory, excluding these private inputs and outputs. This
working checkout is required for its research data. The root Mac demo entry
points remain the portable historical demo until an optimized final package is
independently ready. Do not claim actual Mac verification from Linux tests.
