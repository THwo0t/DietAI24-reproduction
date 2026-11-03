# Source role audit entry review

Reviewed commit: `d45b97087dac554c06297d65e7dce73b2a79e239`.

Decision: **approved** for this bounded entry prototype. P1: none. P2: none. P3: none.

Scope is the three new files `round11/source_role_audit.py`, `round11/test_source_role_audit.py`, and `round11/preparation/SOURCE_ROLE_AUDIT_ENTRY.md`, relative to `optimization_sol_20261102/mae_v2/`. Direct reader, inventory verification, graph and exclusive-writer contracts were inspected only to check their use by this entry. This is not a review or approval of full cohort preparation, eligibility, caller exposure closure, a paid runner, or actual source data.

## Evidence

- The documented receipt-registration stop (`preparation/SOURCE_ROLE_AUDIT_ENTRY.md:7-12`) is enforced by `source_role_audit.py:17` and `source_role_audit.py:47-52`: the initial `None` is rejected before the inventory read. The missing-registration negative test patches the read to fail if reached (`test_source_role_audit.py:85-89`). Registering the exact independently trusted completed receipt is still required before production use.
- The held completed-but-unresolved status and false/zero action fields are checked before source use (`source_role_audit.py:54-60`). Capture implementation and fixed control bindings are compared (`source_role_audit.py:61-65`); fixed N5/development reader projections are compared to the held inventory (`source_role_audit.py:66-70`). The receipt, readers, ASA and legacy bodies, controls and implementation are revalidated around role loading and graph evaluation (`source_role_audit.py:72-92`), consistent with `preparation/SOURCE_ROLE_AUDIT_ENTRY.md:14-19`.
- The entry passes deep copies of held mechanical/local identities and the role reader projection into the phase graph (`source_role_audit.py:86-88`). The called graph preserves original/current manifest bindings and original group/fold/hash evidence (`asa_phase_graph.py:106-123`) and retains unresolved role/source reasons and false action flags (`asa_phase_graph.py:127-152`). The entry makes no fold repair and does not replace or modify old inputs.
- Unresolved caller registration, training/retired proof, source coverage and exposure are retained explicitly in the result (`source_role_audit.py:93-113`), matching `preparation/SOURCE_ROLE_AUDIT_ENTRY.md:28-31`. Aggregate output is whitelisted and type checked (`source_role_audit.py:96-107`); private role/graph projections are confined to the artifact value (`source_role_audit.py:108-115`).
- Production accepts no CLI overrides, requires the network namespace guard and a fresh output, and invokes the fixed private writer (`source_role_audit.py:118-126`). The existing writer bounds serialized size and uses private-directory checks plus `O_EXCL`/`O_NOFOLLOW` with mode `0600` (`source_census.py:284-316`). Failure stdout exposes only status and exception type (`source_role_audit.py:129-134`). There is no entry configuration from environment variables.

## Offline verification

Executed from the repository root:

```sh
unshare -Urn .venv/bin/python -B -m unittest discover \
  -s optimization_sol_20261102/mae_v2/round11 -p test_source_role_audit.py
```

Result: **7 tests passed**, 0.036 seconds reported by unittest. Tests cover synthetic unresolved success, poisoned identities/action grants, control/source/implementation/receipt drift, changed held bytes, missing registration before read, CLI rejection and preservation of an existing output. These are orchestration tests with mocked source/graph contracts, not an actual-data integration run.

No actual inventory, census, images, labels, credential files or `.env` was opened. No network request, API call, download, production entry run, staging or commit was performed. Only this review file was created.
