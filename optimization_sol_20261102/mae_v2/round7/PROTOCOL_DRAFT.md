# M: shared FNDDS accounting on ASA24 and Nutrition5k

Design draft, not an execution freeze. No M paid request is authorized by this
file alone; implementation, offline tests, one independent review, fixes and
the final source/configuration freeze precede execution. Existing user paid
development authorization persists. No new download is planned. All old
sources/results remain immutable and validation stays sealed.

## User requirements and scope

Each complete candidate must have same-method evidence on **both** datasets.
Old ASA scores cannot stand in for this candidate's ASA run. Reuse is permitted
only for an explicitly verified identical historical computation, with its
original provenance and zero new requests disclosed. Review the entire project
after each failure, including method drift and engineering progress, then back
up only an explicit secret-scanned public inventory. Final reports remain
deferred until the intended outcome is ready.

Sol is the main/visual API model at the existing zicc route; embeddings use the
original official OpenAI text-embedding-3-large route and credential. Codex
subagents in this project must explicitly use gpt-6.1-sol. The latter restriction
is project-specific; other projects inherit their main conversation's model.

## Shared task and fixed populations

Use the current 99-image ASA development population and 84-image/78-group N5
population, unchanged groups/folds/images/labels. No validation inputs, new
images, training recipe gallery, N5 ingredient-ID dictionary, crops, direct
nutrient prediction, examples, ensemble or calibration.

The shared core accepts RGB pixels and generic FNDDS catalog/retrieval assets,
never a dataset name or query reference. Native aspect, longest edge <=1024,
no enlargement; one RGB image. Sol temperature 1, completion limit 8192,
maximum one format-only repair per chat stage. Use the same fixed 5,624-vector
FNDDS index, code associations and density projection as the audited raw C.
Preserve its missing explicit-category candidate projection rather than silently
restoring fields. The complete catalog retains category: it still contributes
to the original relationship hints.
Its whole-serving quantity is the sum of all nonoverlapping accounted leaves.

## M0 baseline

Use the original uncalibrated C core: A's image-only layout and fixed-leaf code
selection, followed by C's total-grams x parent-ratio x child-ratio portion stage.
There are at most eight parent regions and twenty leaves. No crop review.
Identity metadata remains A's `portion_mode=direct`; actual portion inference
uses `total_ratio`. Do not rename or rewrite old identity objects.

ASA M0 obtains all new layout, selection and portion responses. N5 M0 imports
the 84 sealed original raw C computations only through a new read-only importer.
It must bind historical A/C trees and reviewed source-drift exceptions, validate
actual image bytes against the frozen dev manifest, replay raw layout/selection/
mass parsing, official query vectors and all candidate ordering, and recompute
leaf grams/nutrients exactly. It must not call the old runner, construct a
Provider, mutate old artifacts or manufacture modern service receipts.

Only the reviewed crop-priority fix (unused with crop=false) and bootstrap fix
(not inference) may differ from old hashes, under explicit review evidence.
Exact reconstructed request/payload and cached-answer provenance must also be
checked where available; a value hash alone is insufficient. Of the 530 exact
historical child query texts, 461 have persistent counters and 69 came from the
older parent provider, which did not implement a persistent counter. For those
69 only, bind the exact old provider source, payload/cache and original successful
official-model log, explicitly recording `historical_counter_available=false`.
Do not manufacture a modern counter or imply proof of the old cumulative retry
count. This is a disclosed historical import limitation, not an exception to any
new M transmission budget. Any other incompatibility
stops import and requires resolution before paid execution. Imported historical
work and new requests are reported separately. No calibrated C prediction is
used as a raw baseline.

## M candidate: allow one-way composite collapse after retrieval

Share M0's label-blind layout and child candidate bank. For every parent initially
marked `components`, retrieve whole-dish alternatives from its existing
`parent.description`: one exact text, dense top12 + lexical top12, RRF constant
60, at most 24 unique whole candidates. Do not duplicate that text to pretend
there are two queries or generate another broad description. Other parents use
their original composite child bank. Existing child hybrid32 banks stay fixed.

Then jointly choose code and accounting route using the original image and
generic candidate descriptions/densities. Each initial components parent may
retain all its original children with one legal code each, or collapse to one
whole FNDDS candidate. Initial composite parents cannot be split. Preserve all
parent IDs, boxes and physical region ownership; omit no parent. Never account
for both the composite and its children or add unobserved foods/oil from labels.
All final codes must belong to their corresponding retrieved branch.

Deduplicate the global candidate table in the prompt and reference it by code;
do not repeatedly print the same nutrient row for every branch. Record initial
and final paths, replaced child IDs and a distinct whole-entity identifier, even
if the legacy quantity parser needs a local `pNc1` ID. Never attach an old
child's grams to the new whole entity. Run a new C-style total-ratio portion
stage for every candidate image, even where no collapse is available. Its
programmatic `grams * FNDDS density / 100` is the sole nutrient computation.
Every logical stage is invoked and reparsed separately. If two stages in this
paired batch have exactly identical payloads and namespace, their one successful
response may be reused by the durable payload cache with explicit shared refs.
This is not an independent second model draw; request counts distinguish logical
stages from transmissions. No approximate-match or accuracy-based reuse occurs.

This is a bounded whole-method intervention (extra whole candidates plus joint
route/code selection), not proof of an isolated single-factor causal effect.
It cannot repair incorrect initial parent regions or reveal hidden recipes.

## Coding and dataset adapters

Food coding is fixed **before portion inference**, following the paper's order.
Rank parents by descending normalized box area, then parent ID; within a parent,
use stable final legacy component ID (whole entity IDs remain separate audit
identifiers). Deduplicate their selected codes in that order. ASA retains
the first three, with the first as primary; a fourth-or-later code is not Exact.
This ranking does not use masses, reference labels or errors. It preserves a
valid recognized code when the subsequent portion stage fails, so that such an
Exact row cannot silently vanish from conditional scoring. All leaves remain
in whole-serving nutrition; top3 is a coding-output limit, not food deletion.

After all model predictions seal, the offline ASA adapter reads the true code
only to score membership in those fixed top3 codes. For each Exact row with a
valid portion, sum continuous grams for that code across its nonoverlapping
leaves, map to the closest option in the code's complete frozen `asa_options`,
ties by lighter grams then lexical option ID. Compute its five targets using
that option's grams and code density. The true code, legal options, reference
unit, selected option, quantity, nutrients and bin enter no model request.

This ASA primary is a **conditional code-specific option task**, not whole-image
E2E. It differs from the old ASA conditional inference path. Score every Exact
row, including a failed-portion row using the median-weight legal option: take
the numerical median of all legal option gram values, then apply the same nearest
option tie rule. An even-count midpoint is never itself an invented option. Also
report complete-serving E2E on all 99, Exact counts/groups, first-code rate,
average code count, three size strata and the two arms' common Exact subset.
Do not treat changed Exact populations as causal improvement evidence.

N5 primary is the same core's full-serving vector on all 84. It receives no ASA
context. Model/structure failures use the same method of dataset-specific
other-fold componentwise five-target median fallback; prepare those fixed
vectors in an isolated step, expose no query target to the runner. Failed
identity gives no invented codes. Failed quantities preserve independently
selected codes and use whole-serving fallback plus the ASA option fallback
where Exact. Service/auth/model/integrity faults stop rather than become food
prediction fallbacks. No row deletion or accuracy-based rerun.

## Metrics, tolerance and selection

Keep the existing 1.3xpaper absolute and per-unit caps unchanged. Per-unit is
MAE divided by the reference mean of the same scoring population, never MAPE.
Use full precision for decisions. Each dataset has **ten numerical checks**:
five absolute MAEs and five per-unit values. Interpret the user's allowed one
or two exceptions conservatively as **at most two failed checks out of ten in
each dataset separately**. All ten must be defined. Also report five target
pairs and the original strict 20/20 rule. No cross-dataset compensation.

ASA's previously accepted 15% coding floor remains a guard against tiny selected
populations; separately report the original 18% target and number of Exact
independent groups. Undefined conditional metrics or fewer than five Exact
groups cannot establish acceptance. Whole-serving E2E is always visible but
cannot silently replace the registered conditional primary task.

Select one whole profile for both datasets. First reject undefined/invalid
populations. Compare by (maximum failed-check count across datasets, maximum
cap ratio across twenty checks, total failed checks, mean cap ratio, simplicity).
Ties retain M0. Display common-Exact paired comparisons separately. A relative
improvement alone is not goal achievement. Freeze the selected method only if
each dataset satisfies its numerical tolerance and coding/population guards;
then prepare one independent frozen validation run, without looking early.

Group bootstrap 95% intervals are descriptive; use ASA full association groups
and N5 dish groups, fixed seed and 10,000 replicates. Point estimates determine
the registered tolerance. Intervals do not include method-selection uncertainty.

## Service, provenance, bounded execution and failure review

New chat namespace and output paths must be distinct from all prior methods.
Use at most two workers, read600/connect30/write120/pool120 seconds and three
durable transmission reservations per exact payload. No counter reset. Ordered
image receipts and exact embedding text/payload hashes bind each stage.

Official query embeddings have shared hash namespace `official-query-v1` in the
old provider. Explicitly separate verified imported embedding successes from
fresh M transmissions; imported hits create no fictional M log or fee. Do not
allow implicit parent-cache copying, unknown foreign counters or value-only
cache validation to bypass provenance. Completed replay constructs no Provider
or credential reader and writes nothing. Freeze scorer and tolerance code too.

Maximum new initial chat requests: ASA M0 297 + M both datasets 366 = 663;
one repair gives at most 1,326 logical chat payloads and 3,978 transmissions.
N5 M0 has zero new requests. ASA condition adapter has zero model requests.
N5 old child query vectors are reused after proof; whole queries are bounded by
the imported layout (79 eligible parent occurrences in the audited source).
ASA child and whole text occurrences are bounded by 3,960 and 792 respectively;
exact-text cache reuse reduces actual embedding requests. No monetary budget
confirmation is needed again. Report actual role-specific requests/tokens;
third-party money requires verified billing/prices, not official Sol list prices.

After any complete failure, publish no new formal report. Preserve scores and
requests, update the project-level retrospective for **both** datasets, inspect
error concentration and representative large errors without dropping them,
audit method deviations and completed/unexecuted engineering, choose one next
registered mechanism, and back up a checked explicit source/aggregate inventory.
Verify remote branch state, use ordinary fast-forward pushes, exclude secrets,
research images/labels/row outputs/raw logs/local config and local Git history.
