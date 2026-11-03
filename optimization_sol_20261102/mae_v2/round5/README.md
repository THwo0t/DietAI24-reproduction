# Component-comparison development checkpoint

Final reports remain deferred. The completed failed J method and its full
composition diagnostic are backed up at public commit `36be2b8` on
`codex/mae-v2-backup-20261103`. The independent training download is complete;
do not download its 230 images again. All validation data remain sealed.

The fixed ridge experiment in `PRIOR_PROTOCOL.md` is separate from candidate K.
Its dense predicted ingredient vector is not passed to K. `K_PROTOCOL.md`
registers one component-identity comparison and conserved-mass method before
new inference. All experimental code and evidence stay in this directory.

From `optimization_sol_20261102/mae_v2`, using the existing project environment:

```bash
unshare -rn ../../.venv/bin/python -B -m unittest discover -s round5/tests
unshare -rn ../../.venv/bin/python -B -m round5.src.run_component preflight
../../.venv/bin/python -B -m round5.src.run_component base --allow-paid --workers 2
unshare -rn ../../.venv/bin/python -B -m round5.src.run_component verify
unshare -rn ../../.venv/bin/python -B -m round5.src.score_component
```

These commands are the workflow, not an execution receipt. The new base must
wait for final source freeze and new-source real preflight. Its one independent
review is complete; R5-K4-1 is fixed with 154 passing offline synthetic tests. Paid development already has unlimited user authorization. It uses
the existing local dual-route credentials and never prints their values.
Long runs require a persistent process with private logs; completed stages and
HTTP counters must survive interruption. Do not reset them or rerun answers
because their error is high. Completed verification constructs no Provider.

Only after all 84 K records seal may the separate scorer open development
labels. It preserves the 99 ASA24 records and compares all ten Nutrition5k
ratios with raw J. No K calibration, target-wise splicing or validation run is
registered. A failed method receives a safe source/aggregate GitHub backup and
further diagnosis; final reports are written after the agreed outcome is ready.

Public exports exclude new training/development/validation images, private
inventories, labels, row predictions, raw request/process logs, local Git history
and credentials. Source and synthetic tests alone do not establish accuracy or
a completed Mac demonstration.

K validates successful caches, namespace counters and service logs on resume and
completed replay. Its independent completion-provenance stage detects changed
bytes without network access. A successful service log whose cached response
is missing is stopped for reconciliation, not silently regenerated. Unlogged
reserved attempts remain consumed and are reported separately from known HTTP
transmissions. Do not delete or reset evidence to bypass such a stop.
