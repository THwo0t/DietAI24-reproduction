# O-REC1 independent bounded review

Reviewed HEAD `58c2f76163ff9a45f46a494c5693c4722c93953a` on 2026-11-04.
Decision: **changes requested**. This is the single review of this scope;
the implementation agent should fix P1/P2 and independently confirm the fixes
offline, without requesting a second review.

## Scope and evidence limits

Reviewed `round10/postscore/reverify_sealed_o.py`, its synthetic tests,
the newly production-used `round11/o_completion.py` and its synthetic tests,
and only the D-NS-1 / D-JSON-1 changes in the existing diagnostic modules/tests.
Read the artifact-store implementation and diagnostic helper source to verify
their read/normalization contracts. Did not reopen the original O scientific
review, P-C preparer, or old postscore review. This review does not approve any
preparation, download, paid run, model selection, or new phase action.

No real labels, catalog, images, prepared inputs, run/evidence/diagnostic
artifacts, credentials, provider cache or raw responses were opened. All runtime
checks used generated temporary fixtures in a network-isolated namespace.
The historical diagnostic hash and missing original guard receipt are supplied
facts, not newly verified production-artifact observations in this review.

## Findings

### R-O-REC1-1 — P2 — Close mutation audit events before claiming a read-only recovery

`round10/postscore/reverify_sealed_o.py:124-126` rejects only a subset of
filesystem mutation events. In particular, `os.truncate(path, 0)` emits the
`os.truncate` audit event rather than an `open` event; it therefore passes this
hook even for a path outside every allowed tree. `os.utime` and `os.chown`
likewise bypass this event list. The later source/store hash checks cannot
protect unrelated files; metadata-only changes also evade content hashes.

This contradicts the recovery contract in `round10/postscore/README.md:50`
that the process policy blocks other mutations, and the zero-violation receipt
claim in `reverify_sealed_o.py:145-150` can be produced after an actual forbidden
mutation. This is a runtime guard defect, not a paper-method finding.

Concrete offline negative evidence: reused the existing fresh-child synthetic
entry fixture, created a temporary `outside_policy.txt` containing synthetic
text, and injected only `os.truncate(base/'outside_policy.txt', 0)` into the
mocked `verify_completed_o()` called after hook installation. The child exited
0, the outside-policy file became 0 bytes, the recovery receipt was written,
and `policy.forbidden_open_or_mutation` remained 0. No repository or production
artifact was changed by this probe.

Required fix: reject the supported filesystem mutation audit events, including
truncate and metadata changes, before they execute; retain the sole exclusive
receipt-write exception only for its intended open/write path. Add a fresh
process synthetic negative test proving attempted truncation and metadata
mutation are refused, the victim bytes/metadata stay unchanged, and no recovery
receipt is created. Check the remaining process/mutation event coverage against
the stated guard contract while making this fix.

## Approved observations within the bounded scope

- D-NS-1 uses the calling process's `/proc/self/net/dev`, requires exactly one
  loopback row and strict header/counter shape, and rejects additional or
  malformed interfaces (`guarded_diagnose_o.py:16-32`).
- D-JSON-1 changes only item-count keys to strings before sealing
  (`diagnose_o.py:74`); its JSON-roundtrip test covers the original mismatch
  without modifying or regenerating the existing sealed diagnostic.
- The public recovery CLI rejects caller arguments and uses the pinned O
  freeze (`reverify_sealed_o.py:98-106`). Private pin/root hooks are confined to
  synthetic-call interfaces. The completed-O verifier checks full store
  inventories, frozen source names/hashes, replay binding, score source records,
  OOF population, checkpoint and followup consistency (`o_completion.py:101-169`).
- Recovery closes the original diagnostic input inventory, binds unopened data
  hashes to established freeze/common anchors, verifies the sealed diagnostic,
  and compares all official n/MAE/per-unit/reference-mean points against the
  checkpoint (`reverify_sealed_o.py:39-83`). It does not recompute those points.
- Receipt wording explicitly preserves original guard failure, missing original
  counts/mtime snapshot, absence of a fresh physical data-integrity check,
  no recomputation and no phase-action permission
  (`reverify_sealed_o.py:86-95`). These are appropriately limited claims.

## Offline validation

Both supplied commands passed at the reviewed HEAD:

```text
unshare -Urn .venv/bin/python -B -m unittest discover -s optimization_sol_20261102/mae_v2/round10/postscore -p 'test_*.py'
15 tests, OK
unshare -Urn .venv/bin/python -B -m unittest discover -s optimization_sol_20261102/mae_v2/round11 -p test_o_completion.py
9 tests, OK
```

The additional mutation negative probe failed the intended security property as
described in R-O-REC1-1. No production recovery entry was executed.

## Implementation response and root offline confirmation

R-O-REC1-1: **fixed**, without a second formal review. The mutation list now
includes truncate and metadata/xattr changes, checked against CPython3.10's
official audit table. Remaining documented child-launch events and native
mapping/call paths are refused too. The exclusive receipt-open exception does
not permit these other mutation events.

The fresh-child test now attempts label access, truncation, utime, chmod,
chown and setxattr. All forbidden cases stop before execution, leave victim
bytes/mode/owner/mtime/ctime unchanged, and produce no recovery receipt. The
same truncate/utime cases against committed pre-fix58c2f76 catch2 expected
failures and0errors. All15postscore tests pass offline; the unchanged barrier
dependency's9tests also passed. These are synthetic checks only. Root may now
perform the fixed read-only recovery; no new-data or paid-run action is granted.
