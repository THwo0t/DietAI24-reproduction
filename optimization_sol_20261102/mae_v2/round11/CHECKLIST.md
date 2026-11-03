# Expanded development phase — preparation checkpoints

The existing O batch must finish and score unchanged before actual new data
auditing, sampling, downloading or candidate inference. No result or enlarged
run is claimed here. Independent validation remains sealed.

| Item | Scope | Status |
|---|---|---|
| P-A | Verified identity cache and strict graph primitives, synthetic runner/restart equivalence | fixed; one bounded engineering review completed |
| P-B | Restricted N5 identity sources and pure pool computation; ASA metadata/byte inventory and legal portion eligibility | fixed; one bounded review, R-PB-1 corrected and confirmed offline |
| P-C | Actual source/ZIP readers and latest exposure discovery, phase guard, cohort/fold registration, private freeze and post-download closure | pending; no real data run |
| P-D | Common predictor chosen after complete O diagnosis; expanded runtime/slots, provenance, fallback, OOF and stopping rules | pending |
| P-E | Independent full-scope run review/fixes, frozen paid development on both datasets, offline replay and scoring | pending |
| P-F | Qualification decision, independent acceptance if warranted, final reports and Mac transfer package | pending |

P-B review scope is the new `n5_identity.py`, `n5_pool.py`, `n5_sources.py`,
`n5_preparation.py`, `asa_identity.py`, `asa_eligibility.py`, their six test files,
and the expansion draft. Previously reviewed P-A code and frozen O are outside
the new review. Reviewer may inspect original preparer/paper source as reference,
but no actual data, run outputs, validation files, credentials, network or API.
Only `preparation/REVIEW.md` may be written. This component review cannot approve
P-C/P-D or authorize any actual source audit or enlarged paid batch.

Root implementation remains the sole code writer. All58 unique preparation
tests pass in `unshare -Urn`; fixtures include full restricted-reader-to-pool,
poisoned protected numerical targets, original parsers/portion mapping, changed
source/index/pixel proofs, missing hashes and new validation bridges. No actual
research data was used. Review findings receive isolated English fixes and root
offline confirmation, without a second formal review of the same scope.

P-B review found0P1/1P2/0P3. R-PB-1 now rejects both source orders of a zero/
positive exact-key conflict before sentinel exclusion; the old implementation
catches2 negative failures,0 errors. Identical duplicates and zero-only sentinel
behavior are preserved. The review approves only these component contracts;
all actual source/exposure discovery, cohort/download and predictor integration
remain pending P-C/P-D and their own first full-scope checkpoint.
