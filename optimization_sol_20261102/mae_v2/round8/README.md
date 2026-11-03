# N development entry point

Read PROTOCOL.md, CHECKLIST.md and REVIEW.md before running. This is one common
method on ASA99 and Nutrition5k84, with two quantity profiles, not two dataset
winners. No independent validation or new dataset download is authorized here.
Existing development paid-call approval persists. Every subagent is explicitly
`gpt-6.1-sol`; root is the sole implementation writer.

Use the existing project `.venv`, Python3.10+ and locked project dependencies.
Run commands from the repository root. No command prints credentials.

```
.venv/bin/python -B optimization_sol_20261102/mae_v2/round8/src/run_n.py prepare
.venv/bin/python -B optimization_sol_20261102/mae_v2/round8/src/run_n.py preflight --pre-review
# Complete the independent review and all P1/P2 fixes before freezing:
.venv/bin/python -B optimization_sol_20261102/mae_v2/round8/src/run_n.py freeze
.venv/bin/python -B optimization_sol_20261102/mae_v2/round8/src/run_n.py preflight
.venv/bin/python -B optimization_sol_20261102/mae_v2/round8/src/run_n.py base --allow-paid
.venv/bin/python -B optimization_sol_20261102/mae_v2/round8/src/run_n.py verify
.venv/bin/python -B optimization_sol_20261102/mae_v2/round8/src/run_n.py score
```

Use a persistent coordinator and inspect its private launch receipt before any
resume. Never run two coordinators, change frozen files, reset the ledger or
repeat completed answers based on their errors. Resume the same base command
only after checking saved state. Zero-Provider verification precedes scoring.
The score phase requires the full183-pair seal before loading development labels.
`--pre-review` is available only for preflight, never for paid execution.

The fixed batch imports exactly verified M0 layout/banks/old masses and frozen
other-fold fallback vectors. It sends no new embedding requests. Fresh-image
N uses the full M0 retrieval method and the official embedding route, as defined
in the protocol; this fixed-batch CLI is not a fresh-image demo claim.

Private prepared imports, per-image stages/records, provider replies, launch
receipts and diagnostic details are ignored. Public candidates must use an
explicit allowlist and secret scan; never copy the working tree wholesale.
No new formal report is written for a failed iteration. Keep validation sealed
until a qualified frozen method has its independent-validation wrapper reviewed.
