# P-C1D blind proposal-overlap diagnostic — ready for review

Scope: `proposal_overlap.py`, its seven synthetic tests, PROPOSAL_OVERLAP.md and
the new checklist/refusal aggregate. Prior reviewed source capture and fixed
readers are reference-only; original reconcile must remain unchanged.

Seven module tests pass offline. No actual overlap diagnostic has been run.
The actual mechanical capture refused with the stable linkage code before ASA
source pixels; this diagnostic is designed only to distinguish authenticated
old rejected proposals from accepted training inputs, without lifting the guard.

Independent reviewer may modify only this REVIEW.md. Read AGENTS.md, DESIGN.md
and source references, including the original training audit/manifest emitter.
No actual research artifacts/receipts/data/images, credentials, network/API or
production command. Synthetic tests under unshare are permitted. Record all
findings once with stable R-PC1D-n IDs, priorities and file:line evidence. Root
fixes P1/P2 in isolated English commits and confirms offline without re-review.
Check pin chain, accepted/rejected semantics, no target/image opens, correct
source/hash/count validation, conservative unresolved claims, output privacy,
and that diagnosis grants no sampling, role repair or inference permission.

## Independent bounded review — 2026-11-04 — changes requested

Reviewed commit `b4a4f60` once against AGENTS.md, round11/DESIGN.md,
`round4/src/train_data.py`, the fixed identity-source reader and existing linkage
helpers. This is a source/synthetic review only. No actual research source,
receipt, metadata table, image, credential, production diagnostic, network or
API was opened/run. Only this REVIEW.md was modified by the reviewer.

### R-PC1D-1 — P2 — report ambiguity after full screening closure

**Changes requested.** `round11/proposal_overlap.py:106-124` reconstructs the
full raw and recipe/byte/RGB screening graph, but its sole ambiguity count is
`len({mapping[dish] for dish in validation} & quarantine)`. This counts only
validation's own ambiguous raw components. The unchanged stop instead projects
*all* quarantined raw components into screening closure before intersecting
validation (`round11/n5_identity.py:120-124`). A validation raw component linked
by recipe to another ambiguous raw component therefore triggers the original
stop while this diagnostic reports zero validation ambiguity. That omission
prevents the diagnostic from fully explaining the guard without a misleading
zero. It also falls short of DESIGN.md's source-closure-before-selection rule
and full raw scan/recipe/byte/RGB accounting.

An isolated, synthetic-only extension of the supplied fixture reproduced:
`validation_ambiguous_raw_components = 0`, while the original guard's projected
validation/ambiguous-screening intersection count was `1`. Two synthetic adjacent
scans shared an ingredient anchor but decreased another mass; one shared the
validation recipe while remaining in a different raw component. No real source
was read. Preserve the raw-component metric if useful, but add a separately named
screening-closure ambiguity count using the original guard's projection, and a
synthetic regression covering this indirect bridge. Keep every non-grant and the
original reconcile stop unchanged.

### Other checked areas — approved within this scope

The accepted/rejected distinction follows the original emitter's nonempty-reason
quarantine and exact accepted-manifest semantics (`round4/src/train_data.py:324-345,
512-535`). Fixed source anchors and the hash-bound audit/manifest chain, candidate
and accepted counts, reason count reconciliation, full-universe association
construction, source revalidation and private exclusive output are consistent
with the requested diagnostic boundary. Target/image inventory paths are not
followed; accepted admission is explicitly distinguished from actual API use.
No code change to `n5_identity.reconcile`, role repair, eligibility, sampling,
download or inference approval is supplied by this review.

Validation: seven existing synthetic tests passed with
`unshare -Urn .venv/bin/python -B -m unittest discover -s optimization_sol_20261102/mae_v2/round11 -p test_proposal_overlap.py`.
The additional pure synthetic ambiguity reproduction ran in the same isolated
namespace. Root must fix R-PC1D-1 in an isolated English commit and record offline
confirmation; this is the first and only review, with no re-review requested.

## Root disposition — R-PC1D-1 — fixed

Added `validation_ambiguous_screening_components` using the unchanged guard's
projection of every quarantined raw component through full screening closure.
The separate raw ambiguity count remains. The new synthetic adjacent-scan/
recipe bridge has raw ambiguity0 but screening ambiguity1; original reconcile
still refuses. The regression against b4a4f60 catches one expected failure and
zero errors. All8 diagnostic tests pass under unshare. Root confirmation only,
no second formal review. No actual diagnostic has yet run and no guard or
eligibility/download/inference grant has changed.
