# Round 4 protocol draft — NOT EXECUTED

Date: 3 November 2026. This is a planning artifact, **not** a frozen protocol,
download approval, paid-call authorization, selected model, or report. New
training acquisition proposal is fixed at 230 images / 230 conservative screening
groups. The user already authorized continued paid development without a cost
ceiling. This new data download still requires separate approval under AGENTS.md;
downloaded image count is zero. Effective training size `N/G` after blinded pixel
screening remains unresolved. New-source and request limits will be frozen before
the next run; no additional paid-API permission question is required.
No round 3 source, result, protocol or selection is changed.

## Objective and departure

Test one new base route: an independent training-image appearance gallery,
text-embedding retrieval of 12 distinct groups, visual selection of four training
supports, and H-style ingredient/mass estimation against a new-train catalogue.
This is supervised domain training and visual retrieval, explicitly different
from the original FNDDS pipeline. It is not the earlier C-code semantic kNN
regression: C predictions and all G/H/I predictions are excluded from its inputs.

No target achievement is promised. Development is the existing full 84 images /
78 association groups; ASA remains the preserved selected result and is handled
by a separate scorer. Formal validation stays sealed.

**Data strategy chosen after the fixed-proposal coverage audit: pure new external
gallery, catalogue and fallback.** The proposal was not reselected using the
development coverage result. There are 164 training ingredient IDs; coverage is
93.931% by development ingredient mass and 92.263% by protein contribution, with
60/84 dishes completely covered. These diagnostics compare catalogue membership
only, not image recognition or MAE, and can decrease after pixel quarantine.
They do not establish that an external-only gallery is superior. The diagnostic
use of development references is acknowledged as method-development information;
it does not put those references into the frozen base predictor.

Evidence is `proposal/raw_rgb_summary.json` and
`proposal/coverage_diagnostic.json`; the fixed acquisition proposal SHA-256 is
`eddf9a644114f5b4aecc4d906dbdec6ee0eaecd80b97e23743d9edf663e03eb0`.

## Data authorization and isolation gates

1. Preserve the audited fixed 230-image/230-group proposal, its exact inventory
   and exclusion rules. The earlier 600-group target is infeasible. The proposal
   intentionally expanded only the new-training eligibility frame to cached raw
   official RGB entries; original development/validation eligibility is unchanged.
2. Obtain explicit approval for the exact new acquisition list and maximum
   download scope. Unknown candidate pixels require post-download blinded
   byte/RGB duplicate screening before they become training data. No automatic
   replacement URL, extra candidate or label-driven replenishment.
3. Freeze a new training manifest and training labels after exclusion against
   all protected historical/development/validation components required by the
   proposal audit. A conservative screening group is an engineering exclusion
   unit, not proof of physical plate identity. The inference modules consume
   only the resulting exclusion proof/opaque hashes; they never inspect
   validation images or labels.
   Require all 230 pinned downloads and their immutable receipts before pixel
   screening. Decode only candidate RGB PNGs at the expected 640 by 480 size;
   bind their byte and canonical RGB hashes. Compare against the frozen protected
   fingerprint index, without reopening protected images. Quarantine every
   candidate sharing a byte/RGB hash with a protected record and every endpoint
   of a candidate-to-candidate collision, propagating exclusion through the
   conservative screening component. Never replace quarantined images. Require
   at least 12 surviving independent groups before releasing a training freeze.
   Only accepted training IDs may be parsed from the raw metadata: filter the
   first field before decoding numerical labels. Require ingredient sums and
   dish totals to agree within 0.001 absolute units for each of the five targets.
   Freeze the accepted manifest, targets, ingredient catalogue, five component
   medians, receipts and source hashes together; completed preparation verifies
   its bindings without rewriting them.
4. Bind train catalogue, official five-target train-median fallback, gallery
   descriptors/index, model/prompt/source hashes and intended query image
   manifest before the development run. Only new-train labels may construct
   catalogue densities, reference examples or fallback. No dev labels in the
   base inference process or its binding.
5. Resolve the untested 13-image provider capability in a bounded training-only
   integration check under the existing paid authorization, then freeze implementation and the
   complete paid-call envelope. A service rejection is a stop, not permission
   to invent a different rerank implementation.

## Proposed fixed method

- Every source image is one RGB, metadata stripped, maximum native side 1024
  without enlargement. No extra views, depth, downloaded model, crop search or
  image-specific rules.
- Use one identical Sol appearance-description prompt/schema for gallery and
  query. Describe visible food structure/texture/colour/arrangement, thickness
  and actual scale cues, with uncertainty. Supply no ingredient labels, grams,
  nutrients, catalogue, file name, sample ID, dataset ID or C prediction.
- Embed the canonical full parsed description using the existing official
  `text-embedding-3-large` route at 3,072 dimensions. Validate finite nonzero
  vectors and normalize locally. No learnt transform, semantic-class fitting,
  embedding fine-tuning or new FNDDS vector generation.
- For a query, exclude all prohibited hashes/association groups; sort training
  images by descending cosine then stable training ID; retain the first image
  per group and take exactly 12. No truth/error-based choice of representative,
  similarity weighting or adaptive candidate count.
- Send query plus 12 candidate RGB images to one Sol visual-rerank call. Use
  temporary candidate IDs only, and request exactly four distinct candidates
  in order. Reranking receives no ingredient labels, nutrition totals or
  retrieval scores. Labels become visible only for the four chosen supports
  in the final estimation stage.
- Final estimation receives the new-train catalogue plus those four support
  images and actual ingredient grams, then the query. The query is estimated
  independently. Known IDs use the catalogue density; unknown ingredients
  remain allowed with model-estimated per-100-g density. Return 1–20 distinct,
  non-overlapping positive-mass items; count mixed dishes either as a whole or
  through components. Program computes all five totals; no model-total override,
  fabricated oil, fixed plate diameter, or nutrient clipping.
- No calibration in this base. A later fixed OOF calibration can use the other
  four development folds only; it requires its own protocol and leaves raw base
  predictions untouched. No per-image lookup fitted from the current label.

## Bounded requests and failures

Proposed caps: description and rerank 4096 completion tokens; final estimator
8192; provider temperature 1. Each chat stage gets one initial response and at
most one format-only repair. Repair contains the original response and contract
error, never the reference answer, nutrient error or an accuracy hint.

For `N` training images and 84 development queries, before cache hits:

| Resource | Initial requests | Maximum including format repairs |
|---|---:|---:|
| Gallery description chat | `N` | `2N` |
| Gallery official embeddings | `N` | `N` |
| Query description chat | `84` | `168` |
| Query official embeddings | `84` | `84` |
| Visual rerank chat | `84` | `168` |
| Ingredient/mass chat | `84` | `168` |
| All chat | `N + 252` | `2N + 504` |

Embedding `embed(texts)` loops over texts, so the table counts per-text requests.
The existing provider additionally permits at most three persistent HTTP
transmissions for each exact payload, including each distinct repair payload:
the conservative transmission cap is `3 * (3N + 588) = 9N + 1764`, excluding
the bounded training-only capability check. Real usage may be lower
because of cache hits or early terminal stages. Record request and token usage;
quote currency only from a verifiable price or bill. The user's existing paid
development authorization has no monetary ceiling. No new namespace may reset an exhausted
payload's practical retry bound.

At the current proposal upper bound `N=230`, this is 482 initial chat requests,
at most 964 chat requests including repairs, and 314 official embedding requests;
at most 3,834 HTTP transmissions under the existing retry policy, before any
training-only capability check under existing authorization. These are ceilings for planning, not
calls performed or guaranteed billing totals. Execution still waits for the new
data approval, completed integrity checks and frozen implementation.

Gallery-stage contract failures block gallery completion. Query-description
failure after repair produces the fixed new-train median fallback; rerank
contract failure after repair uses retrieval top four with an explicit method
fallback flag; final estimate contract failure uses the same fixed train-median
fallback. Every query remains in the complete scoring population. Provider or
integrity failures interrupt the batch and never become nutritional fallbacks.
These proposed fallback policies must be frozen before real calls, not decided
from observed nutrient errors.

## Seal, scoring and acceptance boundaries

Store all stage outcomes, attempts, request/cache references and hashes. Exact
same-input stages are resumable; changed dependencies require a separate
versioned artifact. A full completion seal requires exactly the intended 84
records, including explicit method/whole fallbacks, verified source/input
bindings and externally sealed record hashes. Completed runs verify only;
they cannot instantiate the paid provider or silently regenerate records.

Only a separate scorer may open `dev_labels.json`, and only after the raw base
seal exists. Score all 84 with the existing full-precision absolute MAE and
per-unit definition; report all ten checks plus failures/repairs/unknown-food
audit rates. Preserve ASA provenance separately if producing a joint summary.
Do not score partial batches, drop failures or label the resulting development
figures independent validation. Repeated development comparison remains
exploratory even with a newly independent training gallery.

The possible alternative of new training plus each query's other four old
development folds is a **reserve hypothesis only**, not an additional active
candidate. Its diagnostic mass coverage is 98.919%, but it would require excluding
the query's whole fold/group before retrieval, catalogue/density construction and
support-label access. Such a base may be evaluated OOF; ordinary second-stage
calibration on its OOF outputs can still leak outer-fold labels and would require
strictly nested inference/calibration or no calibration. Do not switch to it
silently, run both as an expanding grid, or alter the fixed proposal to fill
development-specific ingredient gaps.

Before activating this draft, all pending data/count/authorization/capability
items above must be resolved, the synthetic isolation/resume tests in
`DESIGN.md` must pass, and the actual protocol/source bindings must be frozen.
Until then, work is limited to source design and synthetic offline modules.
