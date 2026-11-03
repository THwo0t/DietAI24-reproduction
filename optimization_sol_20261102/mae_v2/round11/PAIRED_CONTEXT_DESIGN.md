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
fixed new-cohort development directory. The new-cohort freeze attests reviewed
complete preparation and binds the full source-closure artifact. A reader can
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
this phase. Generic catalog and vector assets may use context_m.assets only
after the complete catalog/vector files have passed new source pins. That helper
loads no cohort or labels. All query embeddings use P's fresh durable budget or
P's own exact cache.

The frozen source inventory must include the new scientific/runtime modules,
parsers, prompts, model routing/environment, design, review, new cohort inputs,
fallback/calibration artifacts and generic assets. Review scope is exactly
`P_first_integrated_context_runner`; unresolved P1/P2 issues prevent loading.
Files have a 32 MiB bound. Only streaming digest-only reads of the exact fixed
`data/vectors/embeddings.npy` asset permit up to 96 MiB; full-body reads and all
other paths retain the 32 MiB bound. All files are regular files reached through component-wise
O_NOFOLLOW opens under the fixed root. Sources and environment are rechecked by
the returned verifier. No public CLI or preparation shortcut is provided.
