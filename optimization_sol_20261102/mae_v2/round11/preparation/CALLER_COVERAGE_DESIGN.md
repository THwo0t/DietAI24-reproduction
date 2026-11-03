# Finite caller coverage through completed O: source-only registration design

This document inspects source, not run artifacts. Paths below are relative to
`optimization_sol_20261102/mae_v2/` unless explicitly prefixed `repo:`. Numbers
are source line numbers, not evidence of execution. A manifest, paid-capable
function, cache, intent or completion file being present does not prove that an
image reached an API. Register conservative potential inputs first; any later
actual-exposure claim needs separately authenticated request/admission evidence.
No world-wide filesystem or arbitrary historical account completeness is required.
The boundary is the finite checked-in F-through-O caller set below, inherited
v1 source roles, and the already completed mechanical inventory's local aliases.

## Caller and role table

| Caller / capability | Registered query envelope | Support / training envelope | Alternate entry and interruption scope | Source evidence |
|---|---|---|---|---|
| F direct estimator | N5 development84/78 groups from frozen dev manifest | No support images; other-fold development median fallback | `run(allow_paid, workers, evaluate_only)` has no CLI path/population override. Pending-record path includes attempted/interrupted queries, so protect full84 without inferring which ran. | `round3/src/run_round3.py:97-124`, CLI `:167-169` |
| G example estimator | Same N5 development84 | Four other-fold, distinct-group N5 development support images per query; protect union of all84 before exact assignment proof | `--evaluate-only` does not enlarge envelope; assignment/import records are not needed to conservatively protect all84. Python function or provider substitution is not a separate demonstrated run. | `round3/src/run_examples.py:114-124`, `:158-176`, `:318-329`, `:378-423`, `:476-478` |
| H ingredient catalog estimator | Same N5 development84 | Development-supervised, fold-excluded ingredient catalogs; no additional image source beyond frozen development | Numerical ingredient records must stay unopened by identity audit. Register their dataset/fold provenance from source and existing hashes. | `round3/src/run_catalog.py:116-126`, `:213-238`, `:471-482`; `round3/src/dev_ingredients.py:2-13`, `:35-41` |
| I visual ingredient examples | Same N5 development84 | G-bound other-fold examples plus H fold catalog; all84 sufficient as conservative image union | Full source contract checks G assignments and H provenance; identity closure must not call old context builders because they read private ingredients/results. | `round3/src/run_visual.py:117-127`, `:245-270`, `:368-438`, `:519-533`, `:583-629` |
| J capability probe | First13 lexical accepted-training sample IDs, one query +12 candidate images | Accepted N5 training manifest; protect all230 proposals regardless acceptance | Public `probe(base=None, provider_factory=None, verify_train=None)` is Python-overridable; CLI offers paid/verify flags only. Register capability as distinct from J development even if incomplete. | `round4/src/capability_probe.py:1-7`, `:33-50`, `:64-102`, `:194-201`, `:236-237` |
| J gallery + original J base | Gallery: every accepted N5 training image; base: N5 development84 | Accepted train gallery, four selected train supports and catalog; all230 proposed training candidates remain protected | `preflight/gallery/base/verify`; interruption before completion does not remove proposed inputs. `load_context(base, verify_train, verify_capability)` is a private/programmatic alternate-root surface to register explicitly, not silently assume used. | `round4/src/context.py:107-155`, `:176-179`; `round4/src/run_base.py:145-188`, `:192-205`, `:233-235` |
| J service continuation | Same original J dev84 and training gallery | Original held exact-input stages plus the same training supports | Distinct continuation store/provider registration; preserve original stopped stages and attempted envelopes. Do not scan/replay response bodies to discover IDs. | `round4/continuation/runner.py:114-139`, `:194-207`, `:222-240`, `:276-278` |
| Training prior (round5) | Offline train-only OOF over accepted230 | Training manifest/gallery vector union; no additional image API caller | `run(execute=False, base=ROOT)` and `--run` are explicit computation/root surfaces; classify source capability separately from paid calls. Protect all proposals already. | `round5/src/run_train_prior.py:30-38`, `:149-203`, `:242-253`, `:271` |
| K component supports | N5 development84/78, verified J continuation prefix | Component retrieval can choose up to8 accepted train support images; query crops derive from original query, not new samples | Fixed CLI phases, paid/workers only. Prefix import and unfinished K store are separate provenance dispositions inside same envelope. | `round5/src/run_component.py:33-47`, `:58-94`, `:182-207`, `:239-251`, `:289-291` |
| L prototype / shelved training pilot | Deterministic25 training-only queries (five per fold) | Fold-local184 supports; full230 training union conservatively protected | CLI explicitly rejects `base`; callable `base(root=ROOT, context_loader=None)` remains paid-capable engineering source. Record **shelved CLI, programmatic capability unresolved**, not executed or absent exposure. | `round6/src/train_context.py:70-100`, `:130-167`, `:174-228`; `round6/src/run_pilot.py:209-228`, `:259-271` |
| M / M0 | Full frozen183 development = ASA99/23 + N584/78 | Generic FNDDS catalog/vectors, imported N5 C stages/embeddings; cross-fold development fallback totals, no external ASA support gallery | `run(ctx, allow_paid)` accepts supplied context programmatically. CLI binds `runtime_context()`; prepare/score access development targets and must never be reused for identity-only audit. | `round7/src/context_m.py:15-32`, `:79-100`, `:133-158`; `round7/src/run_m.py:33`, `:190-208` |
| N | Same183, rows equal M imported rows | M identity/portion imports, generic catalog and frozen M fallbacks | Pre-review switch is confined to preflight. Injectable Python context remains a finite unresolved caller-registration question, not a license to read arbitrary roots. | `round8/src/context_n.py:24-29`, `:62-79`; `round8/src/upstream_n.py:61-97`; `round8/src/run_n.py:28`, `:194-207` |
| Round9 diagnostic | Offline completed-N183 identity universe | Diagnostic LP/candidate banks, no new image inference | Requires completed N; label-based diagnostic must not be called or read for this identity audit. Its source is included so it is not mistaken for a missing paid candidate. | `round9/run_diagnostic.py:111-164`, `:171-198`, `:227-273` |
| O identities / whole / ASA conditional | Same183, fixed stage slots; conditional branch is ASA only | Generic catalog/vectors, frozen M fallback bound through N freeze; no external image support | `run(ctx, ledger, trace, adapter_runner, workers)` has programmatic injection. CLI uses fixed runtime context. Conditional adapter uses ASA reference **codes/options** after coding seal; audit records protocol condition without opening labels. Launch/resume/completed paths stay within registered183 but are not evidence every slot was used. | `round10/context_o.py:40-61`, `:105-128`; `round10/service_o.py:36-50`; `round10/run_o.py:47-52`, `:83-137`, `:233-234`; `round10/adapter_o.py:19-33`; `round10/launch_o.py:23-44` |

`src/pipeline_v2.py:1-22`, `:164-165`, `:221-246`, `:254-277`
defines a pixel/generic-catalog pipeline, including query-derived crops. It
accepts caller-supplied image paths; it cannot itself prove a manifest or role.
Do not classify all corpus images as exposed because this API exists. The caller
registration must bind each concrete runner above to its frozen identity envelope.

## Fixed identity-only reader slots

A future reviewed reader should open only the following finite slots with fixed
anchors; hold bytes and revalidate before/after projection. Do not invoke old
runtime/context/scoring loaders: for example `context_m.manifest():30` opens
images, `context_o.inputs():51-55` loads numeric fallbacks, and old dev loaders
open labels (`src/cohorts_v2.py:636-676`). Never follow image paths or artifact
inventories to additional files.

1. Existing authenticated source inventory plus existing fixed controls and
   source/implementation pins; do not rediscover files or rerun O. Reuse its
   local alias/hash projection and retain unmatched local potential identities.
2. V2 `data/cohorts/dev_freeze.json` and `data/cohorts/dev.jsonl`: exactly the
   seven identity fields,183 rows/ASA99/N584, groups23/78, original fold bindings.
   Labels/image hashes in a seal are bindings only; no corresponding bodies.
3. `round4/data/train/freeze.json`, `round4/data/train/manifest.jsonl`,
   `round4/data/train/audit.json`, `round4/proposal/private_train_pool_proposal.json`,
   `round4/proposal/raw_rgb_summary.json`, and
   `round4/proposal/private_audit_index.json`: project only dish/sample/group,
   split/fold, paths, byte/RGB hashes, accepted/rejected reason identities and
   proposal/manifest counts. The full proposal230 is protected, including
   rejected/quarantined candidates; accepted-only proof must never shrink it.
   Do not open `labels.json`, `ingredients.json`, catalog/fallback numeric bodies,
   gallery records, private audit ingredient masses or model responses.
4. Existing N5 fixed identity-reader slots for original/final source snapshots,
   cohort proposal, exclusion registry and validation seal remain authenticated
   inherited role evidence; do not regenerate scans or parse targets for this
   caller-only step. Existing held mechanical scan associations can be consumed.
5. ASA inherited fixed v1 manifests and protocol, v2 validation identity manifest
   and seal, fixed history code/image CSV projection and four legacy manifest
   projections already supplied by the ASA role/source readers. Keep inherited
   historical pins separate from prospective receipt hashes. No new run-file
   glob: use the already registered finite census CSV list only.

No extra result-bearing prepared JSON is necessary to conservatively establish
this caller envelope: M/N/O query rows must equal the fixed183 manifest; F-I/J/K
query rows are its N5 subset; training/capability/L supports are subsets of the
already protected230. A source-code registration can prove this finite union
without parsing imported predictions, `prepared/common.json`, `prepared/upstream.json`,
`prepared/raw_c.json`, `prepared/fallbacks.json`, service responses or raw logs.
If exact historic run bindings are later required, authenticate opaque hashes
from fixed freeze/intent/completion receipts in a separately reviewed projection;
never parse mixed numeric/response payloads merely to extract sample IDs.

## ASA source roles and historical preservation

ASA source archive/workbook membership is source-corpus evidence, not training
or API exposure. The caller table supplies no external ASA gallery analogous to
N5's230. It **does** show all99 ASA core queries in M/N/O and cross-fold core
fallback supervision. Preserve this distinction: external-training source role,
core-as-training support role, query potential role and actual API use are
separate assertions. Existing role anchors for `training` and `retired` cannot
be silently left empty and declared complete.

For this finite boundary, register ASA external-training as **none in the fixed
F-O production CLI call graph**, conditional on explicit disposition of the
listed Python overrides/prototypes and inherited legacy callers. Retired ASA
must be reconciled against the fixed original v1 dev/validation identities,
existing legacy/history identities and any inherited exclusion/retirement
registry identity projection. V2 preparation copies every original ASA row
(`src/cohorts_v2.py:575-592`), so no new ASA retirement is inferred from N5
replacement logic. If inherited sources do not identify a retired set, report
`inherited_retired_role_unresolved`; do not invent one from absent files.

Keep original ASA99/23 development and ASA78/23 validation sample IDs, groups,
folds, splits and image hashes, allowing only the already registered neutral
path migration (`src/cohorts_v2.py:575-592`). Preserve N5 old/proposed roles and
all230 protected proposals. Graph bridges/intersections do not repair folds or
permit selection. Match caller identities through held authenticated byte/RGB
associations; unmatched aliases remain potential inputs needing disposition.

## Finite blockers and acceptance conditions

- Register a code-pinned row for each table entry, including J capability,
  original interrupted J and continuation, K imports, shelved L callable,
  M/N/O imports and O conditional adapter. Distinguish fixed CLI from callable
  fixture/injection surfaces. Obtain a bounded disposition for whether listed
  alternate roots/context/provider injections were used in this project through O;
  if no authenticated evidence is available, retain the conservative union and
  mark that caller unresolved. No arbitrary directory hunt is required.
- Implement the fixed train manifest identity-only projection and verify it
  against its anchored freeze/audit/proposal. Reuse existing dev/N5/ASA readers,
  never training loaders that parse labels or chase images.
- Bind inherited ASA historical/legacy roles and explicitly resolve or preserve
  unresolved external-training/retired statuses. Source-corpus presence alone
  cannot fill these roles. Preserve all old manifest/group/fold bindings.
- Authenticate the completed-O boundary using already fixed controls and receipt
  hashes. This step needs no replay and no new service access. Exact actual API
  exposure may remain unresolved while a conservative potential-input envelope
  is documented; do not rename the latter as actual exposure closure.
- Output only ID-free counts and a private artifact SHA. Keep sampling,
  eligibility, downloads, inference, fitting, O replay and source/exposure-closure
  grants false until separately reviewed conditions are satisfied. Completing
  this source registration alone does not authorize a new cohort or predictor.

This work opened source/documentation only; no real census, inventory, manifest,
image, label, result, raw log, environment or credential was examined. This is a
design deliverable, not evidence that any caller registration or role is closed.
