# Provisional P context contract

This is a source-only reader design pending the first integrated context and
runner review. It creates no preparation, cohort freeze, review approval, paid
entry, result or scientific claim. `runtime_context()` has no override or
pre-review mode. `gate_p.frozen_gate` remains independently closed until its
full integration is reviewed.

P reads only `round11/prepared/common.json` and `freeze.json` as its entry
artifacts. The exact common schema binds fixed role paths for new development
manifest, protected labels, association lineage, cohort freeze, fallbacks,
calibration and an explicit empty embedding manifest. Labels are hashed as
opaque source bytes for drift detection; they are never parsed or supplied to
the predictor. No O inputs, medians, historical predictions, calibrated results
or old cohort freeze are reused.

Rows have exactly the seven blind fields enforced by service_p. All five folds
must occur in each dataset, complete association groups cannot cross folds, and
lineage must match each row in canonical manifest order. Images have a separate
fixed new-cohort development directory. The immutable producer cohort status is exactly
`prepared_development_pending_integrated_review`; it binds the full
source-closure artifact and never impersonates a runtime science approval.
The loader accepts this pending preparation only after verifying a separate
`approved_or_fixed` runtime gate with scope
`P_first_integrated_context_runner`. Missing or pending gates refuse loading.
No producer output is rewritten after review. The copied source proof also
binds the genuine earlier `P_capacity_v4_preparation` gate, its review digest,
all authenticated preparation source pins and immutable receipt hashes. Runtime
checks those bound proof relationships without reopening raw source corpora. A reader can
verify these attestations and bytes; proving raw association closure and correct
median computation remains the separate preparer's and independent reviewer's
responsibility.

Every fallback and calibration fold records canonical training/heldout IDs and
groups. The reader reconstructs these memberships and rejects overlap, omitted
members or altered folds. Five-component nonnegative finite medians are required
for each dataset/fold. Inference-time calibration is an explicitly disabled identity placeholder:
each fold records `enabled: false`, `status: preregistered_disabled_identity`,
and all five multipliers equal to one, alongside the canonical training/heldout
membership proofs. No fitted parameters, future Exact population or predictions
are required before inference. The reader rejects enabled or nonidentity
calibration in this inference artifact. Neither labels nor fitting are consumed
by this context.

Calibration selection and fitting occur only in post-inference OOF development
processing, when predictions and the Exact population exist. Future fitted
values and results must be separate immutable postscore artifacts with their
own training-fold provenance and review. They must never mutate the inference
freeze, its disabled placeholders, or the live context, and cannot retroactively
change a request or its predictions.

The embedding manifest explicitly declares `fresh_P_queries_only`, empty entries,
and a sorted unique blocked-hash list. Historical query imports are disabled for
this phase. `assets_p.assets` loads P's new fixed
`round11/prepared/catalog.json`, never the old catalog as the inference catalog.
It compares against `data/catalog.json`: every top-level key and all generic
foods, nutrient densities, descriptions, categories and standard options stay
exact. Every old ASA code's option list remains an exact unchanged prefix, including
IDs, descriptions, weights and order. Fresh legal entries may append with unique
IDs and new description/weight pairs; existing entries cannot change, reorder or
disappear. Absent ASA-option codes may also be added, within the same
fixed 5,624-code food bank, with legal option validation. The preparer must build
the full catalogue for ALL safe eligible broader-frame codes before choosing the
20 groups; a selected-true-code-only catalogue is forbidden. That population
proof belongs in the separately reviewed copied cohort source-closure evidence.

`common.asset_files` is exactly the old base catalog, new P catalog, vector
manifest, and every fixed vector file declared by that manifest (including codes
and NPY). The official embedding model, 5,624 unique code join, 3,072 dimensions,
per-file hashes and finite float32 matrix are checked. NPY headers, shape, order,
file length and no-follow descriptors are validated before array allocation.
The unchanged generic vectors feed a read-only retriever. No query embedding
or corpus embedding call is made by asset loading. All query embeddings use
P's fresh durable budget or its own exact cache.

The frozen source inventory must include the new scientific/runtime modules,
parsers, prompts, model routing/environment, design, review, new cohort inputs,
fallback/calibration artifacts and generic assets. Required pins now also cover
records/run/identity-gate/adapter/assets, preparation and source-scope/capacity/
ASA-expansion/caller/training modules, the prospective capacity amendment, and
finite source-disposition design. The large raw ASA archive and full mechanical
inventory are never runtime source files. Their authenticated immutable receipt
hashes belong in the copied `cohort/source_closure.json` proof verified during
preparation. Runtime binds that bounded proof, code, frozen development images,
opaque label digest, catalogs and vectors; it does not reopen raw source corpora. Review scope is exactly
`P_first_integrated_context_runner`; unresolved P1/P2 issues prevent loading.
Files have a 32 MiB bound. Only streaming digest-only reads of the exact fixed
`data/vectors/embeddings.npy` asset permit up to 96 MiB; full-body reads and all
other raw-body paths retain the 32 MiB bound. The fixed NPY is separately
loaded through a held no-follow array descriptor with the same 96 MiB file bound;
it is never materialized as a large raw byte string. All files are regular files reached through component-wise
O_NOFOLLOW opens under the fixed root. Sources and environment are rechecked by
the returned verifier. No public CLI or preparation shortcut is provided.


R-P-1 correction: the scientific runtime and postscore source inventories
explicitly bind `round11/verified_identity.py`, which implements the full coding
snapshot authentication used before the isolated ASA projection and completed
replay. Missing pins or later source drift refuse use. This adds a runtime and
postscore dependency; historical preparation review/source receipt pins and
immutable prepared artifacts remain unchanged.
