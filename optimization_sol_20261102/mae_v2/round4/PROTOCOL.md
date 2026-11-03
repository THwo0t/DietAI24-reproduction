# Candidate J — frozen external training gallery

Frozen on 3 November 2026, after acquisition and the training-only service probe,
before any J gallery or development inference. This activates the single base
method specified here. The earlier `PROTOCOL_DRAFT.md` and failed preparation
evidence remain unchanged. No performance result is implied by these gates.

## Data and resolved gates

The user approved the fixed 230-image acquisition by replying “确认”. All 230
files completed in 230 HTTP attempts: 104,830,902 response-body bytes, below the
350,000,000-byte cumulative cap. No substitute or extra image was downloaded.
The immutable proposal SHA256 is
`eddf9a644114f5b4aecc4d906dbdec6ee0eaecd80b97e23743d9edf663e03eb0`.

Blind byte/RGB checks retained 230 images in 230 conservative screening groups,
with zero protected or candidate duplicate collisions. The release contains 164
ingredient classes. Training freeze SHA256:
`885f8d1a0573313e9e09771f3c38ec938b807e9ffcc9525d706867d3d0d081cb`.
Protected images and labels were not opened during acquisition/preparation.
The groups are conservative exclusion units, not proof of physical plate identity.
The original development and validation populations and freezes are unchanged.

The initial strict preparation stopped on one official training record whose
ingredient mass sum exceeds official dish mass by exactly 2 g. The sole exception
is registered in `TRAINING_DATA_EXCEPTION.md`, bound by source and raw-row hashes,
and required to occur exactly once. All original values are retained. Every other
mass sum and all four nutrient sums retain the 0.001 absolute tolerance. Catalogue
name/density checks remain unchanged. This is an acknowledged source inconsistency,
not corrected ground truth, rounding, sample removal or a larger general tolerance.

The fixed first 13 training images passed the 13-image service probe with one
successful chat request and no repair. Probe completion SHA256:
`644b3251233ed225b5d3dafaaf53d44d4504c26a53504532f005102afa77022b`.
It proves that this endpoint accepted the image payload and returned the required
selection structure, not retrieval accuracy. The current 213-test synthetic suite
passed with networking disabled; actual model performance is still unmeasured.

## Fixed base method

- Model: `gpt-6.1-sol` through `https://api.zicc.cc/v1/chat/completions`.
  Embeddings: official OpenAI `text-embedding-3-large`, 3,072 dimensions, using
  the separate original official credential. Temperature 1; chat namespace
  `external-gallery-r4.1`. Never publish credentials or raw provider logs.
- Use the source RGB at native aspect ratio, maximum side 1024, no enlargement,
  stripped metadata; no crops, depth, additional views or fixed plate diameter.
- Describe each gallery/query image using the same image-only appearance schema:
  scene, visible foods/texture/arrangement, actual scale cues and uncertainty.
  No filename, dataset ID, ingredient catalogue, mass, nutrition label or earlier
  prediction enters this description. Embed its canonical parsed text, validate
  finite nonzero vectors, and L2-normalize locally.
- Exclude prohibited identity, group and byte/RGB matches. Rank by cosine then
  stable training ID, retain one image per group, and retrieve exactly 12 groups.
- Show the query and these 12 images to Sol, using temporary candidate IDs only.
  Request exactly four distinct ordered supports. Reranking receives no labels,
  nutrition totals or retrieval scores.
- Show only the selected four support images and their original ingredient grams,
  the external training catalogue, and the query to the H-style estimator. Return
  1–20 positive-mass, nonoverlapping ingredients. Known IDs use catalogue density;
  unknown ingredients require model-estimated density. Compute all five totals in
  code. Preserve raw leaves; no model-total override, nutritional clipping,
  duplicated mixed dishes or reference-dependent ingredient invention.
- The gallery, catalogue, support labels and five-component median fallback use
  only the independent external training release. Support total mass derives from
  original ingredient grams; fallback targets use official dish totals. No dev
  labels or earlier C/G/H/I predictions enter this base process.

This is supervised domain adaptation, a methodological departure from original
FNDDS retrieval. The earlier catalogue-coverage diagnostic used development
references during method design, not inside base prediction. Coverage is not MAE.
The hybrid gallery using old development-fold examples remains inactive.

## Requests, failures and immutable execution

Descriptions and reranking have 4,096 completion tokens; estimation has 8,192.
Each chat stage permits one format-only repair containing the original output and
contract error, never a reference target or accuracy hint. Each exact payload has
at most three persistent HTTP transmissions, including repair payloads. An
exhausted payload cannot be reset with a new namespace.

For 230 gallery images and 84 queries, the maximum logical workload is:

| Stage | Initial requests | With format repairs |
|---|---:|---:|
| Gallery descriptions | 230 | 460 |
| Gallery official embeddings | 230 | 230 |
| Query descriptions | 84 | 168 |
| Query official embeddings | 84 | 84 |
| Query visual reranking | 84 | 168 |
| Query ingredient estimation | 84 | 168 |

This is 482 initial / 964 maximum chat requests plus 314 embeddings, or at most
3,834 HTTP transmissions before caches/early failures. The separately bounded
probe permitted two logical chat payloads / six transmissions and used one.
Paid development already has user authorization without a monetary ceiling.
Report actual requests and token usage; use currency only with verifiable prices
or bills. Reasoning tokens already included in completion are not counted twice.

Gallery contract failure stops gallery completion. Query-description or final
estimation contract failure after repair uses the frozen external-training
component medians for the entire query. Rerank contract failure uses retrieval's
first four and records method fallback. Provider/integrity failures stop the batch
and never become nutritional fallbacks. All queries remain in the scoring set.

Bind code, prompts, model parameters, protocol, image bytes and payload hashes,
training release, query manifest, capability seal and gallery seal. Persist exact
stage inputs and raw/parsed results with durable attempts and request references.
Resume only identical unfinished work; do not redraw inaccurate successful answers.
Completed phases verify without provider construction or artifact rewriting.

## Scoring and the single calibration candidate

Run all 84 existing Nutrition5k development images / 78 groups / five fixed folds.
The scorer may open development labels only after the full raw base seal verifies.
Score all 84, including fallbacks, using unrounded MAE and MAE divided by the same
population's reference mean. Report all ten N5 checks, failure/repair counts and
the joint twenty checks with the preserved ASA24 predictions. ASA remains fixed:
99 records, 16 Exact records in nine groups; its conditional MAE checks previously
passed 10/10. The 200-image validation population remains sealed.

Exactly one subsequent grouped OOF aggregate calibration is independently
registered in `CALIBRATION_PROTOCOL.md`, SHA256
`2f921d76f6f08ada8faa87648638fd17c4bff7d78aa0099bacb1318ce81d6e5b`.
It uses raw factors 0.5–2.0 on a 0.001 grid, shrunk 50% toward one, and permits
no extra narrow-range candidate or target-wise profile mixing. Calibration leaves
raw ingredient accounting unchanged and does not claim its adjusted totals equal
raw leaf sums. Fit only other folds, preserve whole fallbacks, and freeze derived
predictions before evaluation. All-development fitted factors are for unseen
inputs only. Protect raw passed checks; select the entire calibrated profile only
if its worst/mean ratio improves under the registered lexicographic rule.

These are exploratory development results, not independent validation. Grouped
10,000-draw bootstrap intervals (seed 20261102) are descriptive; calibration
intervals condition on fixed OOF predictions without repeating fitting/selection.
Do not open validation or write final reports merely because a development run
finishes. If targets fail, preserve the checkpoint, back up the authorized public
source/aggregate scope and continue evidence-led optimization.
