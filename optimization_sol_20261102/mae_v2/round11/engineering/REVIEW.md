# Bounded engineering component review

Review date: 2026-11-04. Reviewed commits: `fca0ab4`, `813fc36`.
Decision: **changes requested** for the verified identity component (one P2).
The association and ordering primitives are approved within their documented
complete-input contract, with one P3 hardening suggestion. No P1 found.

## Scope and boundaries

This is the single bounded review of `round11/verified_identity.py`,
`identity_gate.py`, `qualification.py` and their three `test_*.py` files.
`EXPANSION_DRAFT.md` supplied prototype boundaries. Reused pure source was read
only to understand ArtifactStore, Ledger, import provenance and TaskGate behavior.
No real dataset, labels, images, per-sample outputs, credentials, validation,
preparer or model endpoint was accessed. The temporary synthetic image was
created by the existing test fixture. O was neither modified nor controlled.
This review does not approve the unimplemented blind preparer, expanded cohort,
next paid experiment or O itself, and is not a second O review.

## Findings

### R-P-A-1 — P2 — Freeze identity repair admission proofs too

Evidence: `round11/verified_identity.py:29-35` projects only bindings,
reservations and outcomes; `round11/identity_gate.py:48-54` uses that projection
as its admission drift evidence. `round10/service_o.py:154-163` merely checks
the schema of `repairs`; it does not compare a historical repair's values with
the values at snapshot construction. Thus a schema-valid repair proof for an
already frozen identity initial slot can be inserted, removed or altered while
`load()` continues to return the verified cached identity. This violates the
new component's exact identity-related admission projection invariant; quantity
appends should be exempt, historical identity repair authorization should not.

Reproduced offline with the integrated fixture: construct `build_loader`, read
its temporary Ledger, choose a bound identity chat slot with ordinal zero,
insert `repairs[sid] = {'raw_hash': '0'*64, 'error':
'changed_synthetic_error', 'parser_sha256': ledger.parser_sha256}`, save, then
call `snap.load()`. It succeeds (`identity_repair_mutation_accepted=True`).
This is a snapshot invariant gap, not evidence of changed predictions or an O
regression; the existing original sealed proof also omits these repair entries.

Required fix: include the identity-related initial-slot repair proofs (including
absence) in immutable projection evidence. Account for a repaired identity whose
proof includes the repair slot but needs its initial slot's authorization.
Add synthetic cases for changed/removed/added historical identity repair proofs
and a legal new quantity repair, preserving the latter's allowed append behavior.

### R-P-A-2 — P3 — Reject missing image hashes at the association boundary

Evidence: `round11/qualification.py:44-45` builds image edges and hash edges in
separate loops without checking that every image in `pairs` has a hash.
`associations([('11111111', 'one.png')], {}, protected)` succeeds and reports
zero dev/validation intersection when dev anchors that code and validation
anchors a SHA. Without the image's hash, the helper cannot prove byte isolation.

The module explicitly requires the future preparer to supply complete hashes,
so this is a caller-contract hardening suggestion, not a demonstrated failure
for valid complete inputs. Recommend rejecting missing pair-image hashes, or
returning an explicit incomplete result that cannot authorize selection, and
adding a negative test. The missing external association universe still must be
proved by the future isolated adapter; this local check cannot establish that.

## Validation and accepted behavior

Command, with network namespace isolation and bytecode disabled:

```sh
unshare -Urn .venv/bin/python -B -m unittest discover \
  -s optimization_sol_20261102/mae_v2/round11 -p 'test_*.py'
```

Result: 13 tests passed. An initial system-Python attempt ran nine pure tests
but could not import `httpx` for the integrated suite; the existing project venv
resolved this without installation or network. Two additional inline negative
probes used only temporary synthetic state and produced the findings above.

The reviewed implementation performs the original completed-store/proof checks
before constructing a cache; every load recomputes content hashes and frozen
context/import fingerprints, and returns deep copies. Tests demonstrate
same-size/mtime and symlink rejection, image/manifest/catalog drift rejection,
old outcome rejection, legal quantity append, terminal full verification and a
second generic factory invocation. Complete supplied graph inputs retain bridge
codes and byte duplicates before filtering; same-code/same-byte weight conflicts
and fixed seeded whole-group order behave as tested.

Evidence limits: the integrated fixture deliberately has empty source and import
file inventories (`test_identity_gate.py:21-22`); it does not directly exercise
nonempty source pins or imported embedding-vector files. Its original-vs-cached
comparison covers one successful conditional payload and changed payload/context
rejection (`:35-55`), not a complete task/record/failure matrix. Restart is tested
as a fresh generic factory call, not a distinct-process integrated restart.
These limits do not certify future runtime integration or the draft's broader
preparation claims. Before that integration is approved, its bounded synthetic
acceptance should exercise those nonempty dependencies and failure paths.

No source or tests were changed during review; only this review file was created.

## Coordinator response — R-P-A-1 fixed

The immutable admission projection now includes repair proofs and their absence
for the ENTIRE identify/select/embedding slot universe, including unreachable
identity slots. Whole/conditional slots remain outside that projection, so
legitimate quantity work can append. The full factory/revalidation additionally
checks bound identity repair slots have their initial authorization and checks
every identity repair against the actual frozen parser and initial raw answer;
a schema-valid forged proof is insufficient even before snapshot construction.

The integrated fixture now uses a real format-repaired synthetic identity.
Changed, removed and newly inserted identity repair proofs refuse after cache
creation and at the full factory boundary. A real MockTransport whole-task
format repair remains an allowed append, and terminal full revalidation passes.
Coordinator negative confirmation: the same after-cache assertions against
813fc36's old projection catch3 failures,0 errors; all16 current unique tests
pass in a network namespace. No actual datasets, credentials, O runtime or API
were accessed. Status fixed; no second formal review. R-P-A-2 remains a separate
optional hardening item. Future full runtime integration is still unapproved.

## Coordinator response — R-P-A-2 hardened

The association helper now rejects a missing hash for any supplied pair image,
before returning component or intersection counts. The synthetic dev-code /
validation-hash example refuses with incomplete fingerprints; supplying the
matching image hash correctly reports one intersecting component. The same
negative assertion catches one failure against813fc36,0 errors. All17 unique
current component tests pass offline. This local coverage check does not prove
the external association table or protected exposure registry is complete;
the future isolated preparer still must establish that. No real source audit,
download or O execution occurred. Status addressed; no second formal review.

## Coordinator follow-up — bounded runner evidence

`test_runner_equivalence.py` adds complete temporary runner comparison for
native success, permanent whole-task format failure and permanent conditional
format failure. Cached/uncached final scientific records and service counts
are identical in all three cases. Its source/import/legacy file inventories
are nonempty, and changing each file after verification refuses a cached use.
A distinct Python subprocess reconstructs the synthetic context and performs
a completed replay plus full snapshot construction/terminal validation, while
Provider construction is forbidden. All24 unique next-phase preparation tests
passed with network namespace isolation; the strengthened runner test also
passed independently after adding the nonempty-file drift assertions.

This closes the listed synthetic runner/restart evidence gaps, not the external
source-registry completeness obligation. The imported file fixtures do not
constitute a real embedding-corpus audit. No actual data, O source/runtime,
Provider or network was used. All42 frozen O source fingerprints remain equal.
This is coordinator offline confirmation, not a second formal review or
approval of the unimplemented expanded preparer/paid runner.
