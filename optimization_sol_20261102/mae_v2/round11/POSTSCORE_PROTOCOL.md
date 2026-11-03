# P production postscore contract

`postscore_p.py` is a fixed-path, no-argument, isolated-network entry. It never
constructs a Provider or sends a request. The integrated runtime/scoring review
and a completed immutable P run must precede semantic development-label access.
Opaque label-byte hashing by the context/source verifier is permitted;
`labels_parsed=False` means no parsing or semantic target access. Validation
labels and historical scoring results are not read by this entry.

## Review and science freeze without a self-pin cycle

Before creating the runtime science freeze, complete the full integrated review
covering preparation, runner, verifier, scorer, postscore and this gate contract.
Generate fixed `round11/postscore/review_gate.json` from the actual reviewer text:

- status `approved_or_fixed`, scope `P_first_integrated_postscore`, zero unresolved
  P1/P2, and `review_sha256` for `round11/postscore/REVIEW.md`;
- exact `source_sha256` inventory `postscore_p.SOURCES`, using repository-relative
  paths including the V2 prefix.

The gate does not hash itself or the later science freeze. The later fixed
`round11/prepared/freeze.json` must include every postscore source, review gate
and review body in its existing `source_files` (paths relative to V2). Its source
pins must equal the postscore gate's inventory. No permanent hardcoded future
receipt, CLI root/hash override, or fabricated approval is needed. The gate is
not generated or approved by this postscore entry.

At entry, safely read the fixed science freeze to derive the gate hash. Verify
its source inventory and review body before importing/invoking the runtime
verifier. The completed-run verifier then authenticates that same scientific
binding against immutable run/ledger/store seals. Hold both raw freeze bytes SHA
and the canonical `fingerprint(science)`; reject any subsequent mutation. This
binds the postscore gate to the scientific run rather than accepting an arbitrary
standalone approval JSON.

## Completed-run verifier

Production calls fixed no-argument `run_p.verify_completed()`. It must first
require all final, coding and conditional-adapter completion seals, then execute
only the complete cached scientific verification branch with no Provider. No
incomplete-run admission, recovery, new request or fitting path is allowed.
It authenticates the immutable scientific freeze, model/environment, full
vectors/matrix, all rows/source snapshots, coding and final records, conditional
adapter, reservation/outcome/cache references and fallback provenance. Exact
cached reconstruction must reproduce every `records_p` result for all four
profiles; a missing or altered cache/row/stage refuses. Opaque source/label
hashing is allowed, but no target parsing occurs in this verifier.

Return exactly `rows`, `records`, `catalog`, `strata`, `bindings`, `audit`, and
callable `revalidate`. Rows are both datasets' exact seven-field dev manifest
with all five folds. Records are authenticated complete `records_p` composites
in manifest order. Strata covers every ID. Bindings are precisely:

- `science_sha256`: canonical fingerprint of frozen scientific binding;
- `manifest_sha256`, `labels_sha256`: frozen new-development source digests;
- `record_seal_sha256`, `coding_seal_sha256`, `adapter_seal_sha256`: actual complete
  artifact receipt file digests;
- `model_environment_sha256`: canonical frozen environment fingerprint;
- `matrix_sha256`: authenticated vector matrix digest;
- `request_cache_proof_sha256`: authenticated complete service proof fingerprint;
- `source_snapshot_sha256`: frozen copied source-closure snapshot digest.

Audit fields are completed true, provider_constructed false, labels_parsed false,
validation_opened false, exact_records_reconstructed true, and
all_cache_model_matrix_refs_authenticated true. These are results of actual
verification, not authorization flags to set without checks. `revalidate`
reauthenticates held bindings/records/cache/matrix/source artifacts and rejects
mutation without parsing labels. Private fixture injection is not exposed by the
production CLI. If the reviewed verifier export is absent or refuses, production
fails before semantic labels; no approval or verification capability is invented.

## One score and separate selected-method fit

Only after all gates pass, open the single fixed new-development label slot
`round11/prepared/cohort/dev_labels.json`, verify its authenticated bytes hash
before decoding, and require exact manifest IDs. This entry never opens old
cohort or independent-acceptance labels.

Call `scoring_p.score` once on every row and source-bound stratum, with fixed
2000-replicate grouped bootstrap. Score all coherent profiles/raw and bounded
OOF postprocessing. Selection remains one profile and one whole postprocessor,
without target/dataset splicing or independent-acceptance claims.

If and only if the score selects an eligible method, call the separate
full-development helper on that selected uncalibrated inference arm, explicitly
confirmed by that score decision. Store this as a separate postscore fit field.
A selected raw method exports identity multipliers and full-development fallback
medians; retained calibration exports bounded shrunk parameters. No selected
method means no final fit. Never rewrite the inference freeze or original run.

Revalidate scoring review/source pins, scientific freeze, held verifier snapshot,
complete run and label bytes around scoring/fitting. Write fixed
`round11/postscore/scoring/results.json` exclusively with file0600/parent0700.
An existing output must match complete deterministic bytes; conflict refuses
without overwrite. Standard output contains only status, row count, selected
profile, private artifact SHA, zero API calls and validation-unopened status.
Errors expose status and exception class only. Outputs grant no new action.

## Synthetic verification

```sh
unshare -Urn .venv/bin/python -B -m unittest discover \
  -s optimization_sol_20261102/mae_v2/round11 -p test_postscore_p.py
```

Fixtures cover early review/verifier refusal, incomplete/provider-constructed
proofs, missing matrix binding or row, source/label/held snapshot drift, one score
per invocation, selected-arm-only final fit, private output/resume comparison,
science-derived gate/source consistency and CLI overrides. No actual P replay,
scientific label access, image access, credential access or service call occurred.
Actual reviewed science freeze and completed P run remain prerequisites.


R-P-1 correction: the scientific runtime and postscore source inventories
explicitly bind `round11/verified_identity.py`, which implements the full coding
snapshot authentication used before the isolated ASA projection and completed
replay. Missing pins or later source drift refuse use. This adds a runtime and
postscore dependency; historical preparation review/source receipt pins and
immutable prepared artifacts remain unchanged.
