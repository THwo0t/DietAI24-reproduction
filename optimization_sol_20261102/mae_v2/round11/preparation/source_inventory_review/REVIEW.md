# P-C3 bounded independent source-inventory review

Reviewed commit: `2da7dae668b554a547cdcb649d01f66db90c24e2`.
Decision: **changes requested** (one P2; one P3 suggestion). No P1 found.

Scope: `local_input_inventory.py`, `local_content_inventory.py`,
`legacy_input_identity.py`, `asa_source_capture.py`, `n5_potential_identity.py`,
`source_inventory_capture.py`, and their six test modules. Read `AGENTS.md`,
`DESIGN.md`, `COHORT_REPAIR_DESIGN.md`, and
`preparation/SOURCE_INVENTORY_DESIGN.md`. Existing lineage, development-identity,
census, and source primitives were read only to understand integration; this is
not another review of those previously reviewed components.

## R-PC3-1 — P2 — Revalidate empty and missing legacy sources after composition

Evidence: `round11/source_inventory_capture.py:92-95` rehashes only sources whose
status is `captured_prospective`. `round11/legacy_input_identity.py:114-119`
changes an empty captured CSV to `empty_unresolved`, retaining its hash, and its
own final revalidation finishes before the remaining integrated collection.
Thus empty files are excluded from the integrated final binding check; missing
files are likewise never checked for appearance there.

Synthetic negative evidence: using the existing orchestration fixture, set one
fixed legacy source to `empty_unresolved` with its original SHA, then replace its
bytes during `rebuild_core_folds`. `_collect_at` still returns
`mechanical_source_inventory_captured_role_closure_pending`. Setting a source to
`missing_unresolved` and creating that fixed path at the same point also returns
success. Neither case reaches `legacy_inventory_source_changed`. These probes
used synthetic bodies and temporary paths only.

This is a snapshot-integrity issue even though closure and action flags remain
false: the saved source status/hash no longer describes the source at final
collection. The design explicitly requires missing/empty/changed legacy inputs
to remain visible (`SOURCE_INVENTORY_DESIGN.md:43-47`) and before/after source-body
binding (`:49-51`). Final validation must rehash every captured body, including
empty sources, and confirm each originally missing fixed source is still absent.
Add negative tests for empty-source change/removal and missing-source appearance
after the loader returns, without following CSV image paths.

## R-PC3-2 — P3 — Preserve inherited top1000 provenance when it exists

Evidence: `round11/asa_source_capture.py:93-99` verifies an inherited top1000 pin
when present, but always labels its origin `prospective_fixed_source_capture`.
The existing `test_inherited_top1000_pin_must_match_prospective_bytes` explicitly
expects this unconditional label. A synthetic matching inherited pin reproduces
that output.

The current hash is safely checked and no historical authentication is invented,
so this does not block the inventory. However, the record discards the fact that
an authenticated historical protocol actually supplied the same pin. Consider
recording the inherited origin separately from the prospective rehash, or using
distinct origin values for inherited-and-confirmed versus previously absent.
This makes the design's conditional prospective-pin rule auditable
(`SOURCE_INVENTORY_DESIGN.md:31-35`).

## Validation and accepted boundaries

All six scoped modules passed in an isolated network namespace:

```text
unshare -Urn /home/lelouch/Data/Projects/DietAI24_original/.venv/bin/python -B \
  -m unittest test_local_input_inventory test_local_content_inventory \
  test_legacy_input_identity test_asa_source_capture \
  test_n5_potential_identity test_source_inventory_capture
Ran 73 tests in 0.488s — OK
```

Working directory was `optimization_sol_20261102/mae_v2/round11`. The 73 count
includes inherited test cases. An initial inventory-pattern discovery also passed
27 tests; a first six-module invocation used a relative interpreter from the
wrong directory and failed before executing tests, then was corrected to the
absolute interpreter above. Additional synthetic negative probes reproduced
both findings. No actual dataset, census, private artifact, label, photograph,
credential, network request, or paid API was used.

The inventory correctly keeps source-corpus versus selected/potential-input role
closure pending. It does not need to finish cohort preparation to pass this
bounded review. The finite authenticated image projection retains copies and
dependencies; mechanical decoding is explicitly allowed even for sealed copies,
while numeric dish targets and labels are not interpreted. The N5 overlay retains
unassigned rows, preserves original core bindings and prior exclusions, and
keeps the new fold proposal provisional. The integrated final ASA check covers
all five fixed sources. The production entry point uses fixed roots/output,
refuses CLI overrides, requires network isolation, and delegates exclusive private
0700-parent/0600-file writing to the existing reviewed writer. All completeness,
eligibility, selection, download, inference, and actual-exposure grants remain
false. No actual capture was performed or authorized by this review.

Per the one-pass workflow, implementation should address R-PC3-1 in an isolated
English commit citing its ID, document disposition of R-PC3-2, and proceed to
coordinator offline verification; no second review is requested.

## Root disposition — R-PC3-1

Fixed: final collection now validates all fixed legacy statuses, rehashes empty
and nonempty bodies, confirms missing files remain absent, and rejects removed
empty files with a stable code. The ten scoped entry-point tests pass offline.
The three new negative cases against reviewed2da7dae fail as expected: three
failures, zero errors. No actual inputs were used and no re-review occurred.
R-PC3-2 is being adopted separately before the first mechanical invocation.

## Root disposition — R-PC3-2

Adopted: an inherited matching top1000 pin retains inherited protocol origin;
a source absent from old protocols retains prospective origin. Both still
receive fresh fixed-path byte/hash revalidation. All nine ASA supplement tests
pass; the updated matching-inherited regression fails once, with zero errors,
against reviewed2da7dae. No second review or actual source access occurred.

## Root runtime discovery — D-PC3-WB-1

The first mechanical invocation and one restricted stable-code probe stopped
before saving an inventory: the official AssociatedCodes geometry is253072x10,
exceeding the prototype2000000-cell range. Structural-only ZIP metadata confirms
the bound, with no dish-target interpretation. The declared range bound is now
4000000 cells; existing row/column/source-byte limits remain. A sparse real-XLSX
fixture retains the identity at row253072, while a400001x10 range still refuses.
All ten workbook tests pass offline; the old source fails the new tail-record
regression once, zero errors. This is an input-bound fix, not model tuning or
a repeated scientific run. The ID-free refusal receipt preserves the original
stop; full source/role isolation and cohort actions remain pending.

## Root subsequent runtime discovery — D-PC3-PNG-1

Workbook identity now completes (253071 source rows), but the next actual
capture stops at the first source PNG: RGBA,160x160,single frame, alpha0..182.
Only structural features were probed; no food visual analysis/label/model was
used. The old strict decoder remains represented by its refusal receipt. A
separately versioned model-input-RGB delta is submitted to its own first bounded
review before further capture; this record does not approve that new delta.
