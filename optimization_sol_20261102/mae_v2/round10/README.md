# O common-method development entrypoint

Read PROTOCOL.md and CHECKLIST.md. O starts from the older passing ASA mechanism,
but both full development cohorts must run freshly. R9 oracle weights are not
training data or predictions. One independent review is complete; its mandatory
fix and recovery suggestion have offline confirmation. No O predictive result
exists at this readiness checkpoint; freeze, backup and the single run follow.

From the project root:

```bash
.venv/bin/python -B optimization_sol_20261102/mae_v2/round10/run_o.py prepare
unshare -Urn .venv/bin/python -B -m unittest discover \
  -s optimization_sol_20261102/mae_v2/round10 -p 'test_*.py' -v
unshare -Urn .venv/bin/python -B optimization_sol_20261102/mae_v2/round10/run_o.py preflight-pre-review
```

After the one independent review and all P1/P2 fixes, finalize review_gate.json,
then freeze and guarded preflight. Launch only once using the existing paid
development authorization and local dual credentials:

```bash
.venv/bin/python -B optimization_sol_20261102/mae_v2/round10/run_o.py freeze
unshare -Urn .venv/bin/python -B optimization_sol_20261102/mae_v2/round10/run_o.py preflight
.venv/bin/python -B optimization_sol_20261102/mae_v2/round10/launch_o.py
```

Always inspect private launch/O_launch.json, O_process.json, O.log and
automatic_followup.json before any continuation. Existing launch receipts
refuse duplicate coordinators. The detached follower waits for this same base,
then runs verify/score in network-disabled namespaces. Do not start another
paid batch or manually reset any slot/payload budget. A stopped batch keeps all
answers and requires state reconciliation, not replacing completed estimates.

If the base completion is sealed but the offline follower stops, retain its
existing logs and inspect `automatic_followup.json` plus the last phase log.
Do not rerun `launch_o.py` or remove the launch/phase receipts. The follower
deliberately refuses an existing phase log, including a successful verify log
left before score. After reconciling the failure, continue only the offline
steps directly (these never construct a Provider or restart paid inference):

```bash
unshare -Urn .venv/bin/python -B optimization_sol_20261102/mae_v2/round10/run_o.py verify
unshare -Urn .venv/bin/python -B optimization_sol_20261102/mae_v2/round10/run_o.py score
```

Run score only after verify exits0. Verify checks the same sealed records and
binds its receipt to the current completion/freeze; an already completed replay
does not replace any prediction. Score refuses a missing/mismatched verification
receipt and checks an existing sealed score for exact equality. A failed verify
is a blocker for score; preserve all state and resolve its integrity error.
An incomplete paid base needs separate ledger reconciliation, not this shortcut.

The main process never loads full current labels. After the full coding seal,
adapter_o.py runs as an offline subprocess and supplies only Exact true code
and complete legal options. It cannot construct a client or open network.
All E2E/main predictions stay independent of the task context. Failed whole
images and all Exact conditional failures remain in their scoring populations.

The private full score includes fold provenance, predictions, service outcomes
and calibration. The public development_checkpoint.json is aggregate only.
Money remains unverified; requests and reported tokens are separate from old
embedding imports. New research images/logs/labels stay private. Validation and
final report/Mac refresh remain deferred until a qualified method exists.
