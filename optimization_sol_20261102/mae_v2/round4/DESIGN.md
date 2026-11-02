# Round 4 independent training gallery: module design

**Status: implemented offline; real-data execution has not started.** No new data download,
actual-image inspection, API request, embedding, validation access or round 3
source change is authorized by this document. The fixed acquisition proposal is
230 images / 230 conservative screening groups; it is awaiting download
authorization and none of its images are downloaded. Effective training `N/G`
may decrease after blinded pixel screening. Do not automatically replace any
quarantined entry or interpret the infeasible earlier 600-group target as data.

The proposed base method uses an independent new training gallery. Sol describes
each training image without labels; official text embeddings index those
descriptions. A query receives the same description, retrieves 12 different
training groups, and Sol visually selects four supports. A new H-style estimator
uses those four training images, their ingredient masses, and a catalogue built
only from the new training labels. The program calculates nutrients from the
predicted ingredient masses and densities. Development labels are absent from
this entire dependency graph, including fallback construction. This pure
external-training route is the one selected design direction, not evidence that
external-only supports will predict better.

The fixed-proposal aggregate coverage diagnostic reports 164 training ingredient
IDs, 93.931% of development reference ingredient mass, 92.263% of reference
protein contribution, and complete ID coverage for 60/84 dishes. The respective
H fold-catalogue figures are 93.174%, 87.485%, and 57/84. These are catalogue
availability diagnostics, **not prediction metrics**; they used development
references only after the proposal was fixed and did not change it. They support
testing the simpler isolated route, while recognition and mass accuracy remain
unknown. Pixel quarantine can lower this coverage. Sources:
`proposal/raw_rgb_summary.json` and `proposal/coverage_diagnostic.json`; fixed
proposal SHA-256 `eddf9a644114f5b4aecc4d906dbdec6ee0eaecd80b97e23743d9edf663e03eb0`.

## Existing interfaces verified from local source

| Existing interface | Observed behavior | Round 4 use |
|---|---|---|
| `opt_provider.Provider(run_dir, allow_paid=False, namespace=..., ...)` | Construction rejects missing paid authorization; production construction may read local credentials. | Inject a fake provider for offline development. Construct a real provider only in a later authorized entry point. |
| `provider.chat(messages, max_completion_tokens=4096)` | Fixed Sol model/route, temperature 1; accepts only 4096 or 8192 caps and inline PNG/JPEG image data. Returns a string. | Description/rerank: 4096; final estimate: 8192. No adapter or round 3 changes required. |
| `provider.embed(texts)` | 1–12 nonempty strings, each at most 12,000 characters; **one HTTP request per string**, not one batch request. Returns one 3,072-vector per string, official route/model fixed. | Use `embed([canonical_description])[0]`; chunking an index build is scheduling only, not a reduction in paid requests. |
| `opt_pipeline.encode_image(path, "native")` | RGB, longest side at most 1024 without enlargement, metadata removed, inline PNG. | One source RGB per dish; no extra views or derived crop search. |
| `round3/catalog_estimator.infer(provider, query_path, examples, catalog)` | Four support images plus query, exact catalogue/support schemas, known/unknown item branches, programmatic totals, one format repair. | Copy its contract into an independently versioned round 4 estimator; do not monkeypatch or edit round 3. |

The provider persists response caches keyed by exact endpoint/payload and chat
namespace, and reserves at most three HTTP transmissions per payload across
restarts. A format repair has a different payload and its own transmission
budget. Embeddings use a global exact-payload cache namespace; identical text
can reuse a validated vector, but this does not certify a gallery's corpus or
prompt provenance. Provider errors raise `ProviderStop`, a `BaseException`.
Only the future top-level runner may catch it to mark the run interrupted.

`chat` returns neither usage nor response metadata. Join stage request digests
to `requests.jsonl` for transmitted-call usage; keep separate stage cache-hit
counts. Current non-`stop` completions become an empty string before the stage
receives them; logs retain finish reason for transmitted requests. Do not claim
the module preserves text that the existing provider discards. Any future
adapter change would require a separate source binding and review.

The adapter has no image-count check, but actual service acceptance of one
13-image rerank request is **unverified**. Synthetic payload tests can verify
our side only. A later authorized training-only integration check must resolve
this before the 84-query run; no automatic contact-sheet or multi-call variant
is permitted on rejection.

## Implemented modules and their boundaries

The modules below are new files under `round4/src/`.
Functions receive validated values and paths explicitly, never
discover labels by walking a dataset directory.

| Module | Minimum public interface | Ownership and permitted inputs |
|---|---|---|
| `train_data.py`, `context.py` | `prepare()`, `verify_train_only()`, `load_context()` | New-train ingredient catalogue and fixed fallback; frozen query images without query labels. No fold catalogue or C/G/H/I outputs. |
| `vision_stages.py` | `describe(provider, image_path)`; `embedding_text(parsed)`; `rerank(provider, query_path, candidates)` | Same image-only description prompt for train/query; reranking receives exactly 12 temporary candidate IDs/images without labels or scores. |
| `retrieval.py` | `build_index(entries, vectors_by_id)`; `retrieve(index, query_vector, exclusions, k=12)` | Pure array/checksum operations. Exclusion identities are opaque metadata. Cosine sorting and group deduplication cannot inspect labels or errors. |
| `catalog_estimator.py` | `infer(provider, query_path, examples, catalog) -> EstimateResult` | Exactly four `{image_path, ingredients:[{ingredient_id, grams}]}` supports. Canonical catalogue entries contain only ID/name/per-100-g density. H-compatible output contract. |
| `artifacts.py` | `ArtifactStore.initialize()`, `stage_runner(...)`, `finalize(records)`, `verify_completed()` | Immutable envelopes, persistent intents, source/input hashes and external seals. No paid calls or label-based decisions. |
| `pipeline.py` | `describe_and_embed(...)`, `infer(...)` | Explicit train assets and query metadata; injectable stage persistence, no dataset loaders. |
| `trace_provider.py`, `image_guard.py` | `TraceProvider`, `ImageGuard` | Request digests without messages/keys; exact ordered image payload checks before the provider receives a request. |

The thin `run_base.py` composes the modules; a separate `score_dev.py` reads
the completed base seal before development labels. The base entry point accepts `QueryManifest`,
`TrainAssets`, `GalleryIndex`, and an injected provider; it has **no labels
argument** for queries and no implicit dataset loader.

### Narrow data contracts

- `TrainManifest`: frozen new-train scope, source/acquisition hashes, approved
  population, and rows with private `train_id`, relative `image_path`, image
  byte hash, decoded-RGB hash, and conservative `screening_group_id`. Keep
  original component IDs and recipe hashes as audit metadata, not prompts.
  Consume the proposal audit's exclusion proof; never open validation to build
  an exclusion set here. Unknown pixels are not screened merely because a URL
  passed a metadata audit.
- `TrainLabels`: exact same training IDs, positive finite total weight, finite
  nonnegative five official targets, and ingredient IDs/names/grams/four nutrient
  amounts. Cross-row ID/name/density conflicts stop asset construction. Reject
  zero grams with nonzero nutrients; zero/zero ingredients may be excluded from
  positive-mass support lists only with explicit counts. No invented one-gram
  serving or nutrient density is allowed.
- `TrainAssets`: canonical catalogue plus source proofs and one fixed
  componentwise median of the official five totals across **all frozen new
  training rows**. This fallback uses image weighting, not retrieval weights.
  Catalogue density is pooled nutrient amount / pooled ingredient grams after
  consistency checks. Counts/provenance are stripped before model calls. The
  existing development-only `build_fold_catalog` must not be reused unchanged:
  its scope and exclusion rules are different.
- `DescriptionResult`: `{raw_outputs, parsed, embedding_text, repair_used,
  failure}`. Proposed exact JSON: `{scene: str, foods: [{appearance: str,
  placement: str}], scale_cues: [str], uncertainties: [str]}`. One to 20 food
  entries; maximum 300 characters per text field, at most eight entries in each
  final list; canonical serialized embedding text at most 12,000 characters.
  Reject oversize output and use the one format repair; never silently truncate.
  The prompt asks for visible colour, texture, structure, preparation cues,
  arrangement, thickness/stacking and real scale cues. It requests no grams,
  nutrients or fixed vessel diameter. Food names may be visual hypotheses, not
  reference labels. Do not attach labels to the embedding text.
- `Candidate`: private train/group/hash metadata plus cosine, rank and a local
  image path. After retrieval, a separate adapter exposes only temporary ID and
  image path to reranking. Retrieval ranks by descending cosine then train ID,
  keeps each group's first/highest-cosine image, then takes 12. No similarity
  threshold or same-group padding. Support paths and image hashes must differ
  from the query and one another.
- `RerankResult`: `{raw_outputs, selected_ids, repair_used, failure}` with exactly
  four distinct IDs from the presented 12, in best-first order. Request visual
  food/texture/structure and portion-scale resemblance, independently of unseen
  labels. Present the query clearly first and each candidate separately; no
  image-specific food-list hint or known plate-size claim.
- `EstimateResult`: H's `raw_outputs/items/prediction/repair_used/failure/audit`.
  Known IDs use the training catalogue and `estimated_density=null`; unknown
  IDs remain null and supply four nonnegative finite densities. Grams are
  strictly positive; 1–20 non-overlapping items. Program sums five targets;
  macro-mass excess is an audit flag, not clipping. Catalogue/support metadata
  and query labels are rejected at this boundary.

## Failure and persistence boundaries

| Event | Fixed proposed behavior |
|---|---|
| Missing/changed training image, labels, isolation proof or index entry | Integrity stop before further calls. Never replace the file, choose another URL or shrink the gallery silently. |
| Gallery description invalid after one repair | Save terminal failed stage. Gallery cannot be sealed or used for development. Any manifest revision is a new pre-development proposal; no unbounded retry. |
| Query description invalid after one repair | Whole-query fixed **new-train-only** fallback; skip embedding, rerank and estimate. Preserve full scoring denominator and failure reason. |
| Embedding invalid, provider timeout/auth/rate/service error, or exhausted HTTP budget | Propagate `ProviderStop`, retain completed stages and interrupt batch. No nutritional fallback and no fabricated successful completion. |
| Fewer than 12 eligible training groups | Preflight/integrity stop; no relaxation to fewer groups or different source corpus. |
| Rerank invalid after one repair | Use original retrieval top four once; set `method_fallback=true`, preserve both raw attempts, then run the one fixed estimator. Report this path separately. |
| Final item JSON invalid after one repair | Fixed new-train-only whole-query fallback; preserve failed estimate and all upstream artifacts. |
| Valid but inaccurate response | Accept as observed; no resampling, prompt change or reference-driven correction. |

Every stage stores `binding_sha256`, input digest, raw outputs, parsed result,
repair/failure status and result digest in an atomic envelope. Reserve a stage
attempt before sending; never overwrite successful or terminal failed stages.
Provider response cache reuse alone is insufficient: revalidate our stage
binding and parser result. Exact source/prompt/config/input changes invalidate
dependent stages instead of rewriting the old run. State transitions distinguish
`pending`, `running`, `completed`, `contract_failed`, and `interrupted`.

Seal gallery assets only when every frozen training row has a valid descriptor
and vector, every expected hash matches, and at least 12 groups remain eligible
for every intended query. Catalogue and fallback have their own train-label
dependency: description/vector reuse is allowed after a label-only asset revision,
but the catalogue/fallback/final estimate must receive new bindings. Reuse a
query descriptor/vector only for identical image bytes, encoder, prompt/parser,
model and route. Reuse a rerank only for identical query and ordered candidate
image payloads. Reuse a final estimate only for identical four support images,
ingredient references, catalogue and query payload. Failed/nonstop responses
cannot be bypassed by choosing a new namespace.

For completed base runs, verify external record hashes, exact query population,
raw item totals or registered fallback, and the full dependency seal. A rerun
of a completed batch is verification-only and must not instantiate a provider.
Score only after the full 84-query base batch is sealed; never score partial
outputs or treat an interrupted batch as 84 failures. Store development-label
hashes in the **scoring binding**, never the base inference binding.

## Work that can start before data authorization

1. Implement pure schemas/catalogue/fallback and adversarial isolation tests
   using small invented training/query manifests and synthetic labels.
2. Implement all three prompt builders/parsers with fake providers and temporary
   synthetic images; prove no ID/path/truth sentinel reaches image-only stages.
3. Implement exact NumPy cosine/group selection using synthetic 3,072-vectors,
   deterministic tie tests and malformed/missing-vector failures.
4. Implement artifact dependency DAG, write-once seals and crash/resume tests
   with fake call counters. Completion verification must prove zero paid calls.
5. Assemble a no-network, all-synthetic end-to-end fixture. Keep acquisition,
   real gallery build and production entry points disabled pending the new-data
   approval, integrity checks and protocol freeze listed in `PROTOCOL_DRAFT.md`.
   Paid development is already authorized without a monetary ceiling.

Required negative tests include changing every development truth without changing
base outputs, catalogue or fallback; changing a new-train label invalidating
only label-dependent stages; excluding exact/associated query matches; duplicate
training groups before top-k; forged cache/envelope/seal; missing one query;
nonstop/empty JSON repair bounds; provider exceptions never becoming fallback;
and rejecting completed-run source drift without any provider construction.

Because the independent base never uses development labels, later fixed
training-fold calibration may reuse its raw 84 predictions: fitting each fold's
factor uses only the other four development folds. The extra 336 nested **base
inference** calls needed for a development-derived gallery are unnecessary here.
This does not waive nested selection if calibration families/hyperparameters
are chosen adaptively, and cannot undo prior repeated exploration of these 84
images. Any calibration has its own registration and never changes the base.

## Reserve hypothesis, not a second registered candidate

A gallery combining the new training pool with each query's other four old
development folds could increase catalogue mass coverage to 98.919% in the
fixed-proposal diagnostic. It is not activated, implemented by this design, or
run in parallel. If separately reconsidered later, first exclude the query's
whole fold and association group from the old development records **before**
retrieval, catalogue/density construction, consistency checks and support-label
access. This leaves 66–68 old development training images per outer fold, not
all 84. A base OOF evaluation could then be valid, but those base training-row
predictions can depend on another outer fold's labels through their own support
bank. Ordinary second-stage calibration on them is therefore invalid: use
strictly nested inference/calibration or leave that route uncalibrated.

The current pure external route avoids that dependency. Keep fallback based only
on new-train labels even if a future mixed-gallery hypothesis is proposed, unless
a separate protocol explicitly changes that boundary. Do not revise the fixed
230-image proposal to cover missing development ingredients, or create an open
sequence of gallery mixtures from these coverage results.

## Offline integration corrections

Training assets are rechecked against the already verified training freeze when
the inference loader reads them, closing the gap between verification and use.
Verified source bytes are also encoded in memory using the existing native
encoder, and their inline payload hashes are bound to the run. The provider
boundary checks each stage's exact image order before transmitting: one for
description, query plus twelve for rerank, and four supports plus query for
estimation. A changed image therefore cannot be sent under an earlier hash.
The source files still receive the phase-end integrity check.

The base run binds the gallery completion digest, checks it during stages and
revalidates the complete gallery seal before base finalization. Interrupted
stages preserve their exact input intent and provider retry namespace; a sealed
pending response is recovered without reissuing its paid request. Completed
phases verify only and never construct a provider.
