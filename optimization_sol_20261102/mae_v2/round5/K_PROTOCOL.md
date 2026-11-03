# K: component identity comparisons and conserved mass allocation

Registered before K inference or scoring. J and the fixed external-training
ridge experiment remain immutable historical methods. The dense ridge output
is not used by K. Sol remains the visual and main model; no weights are tuned.

## Evidence and question

Completed J uses all 84 development photographs. Its true-weight oracle still
fails fat, carbohydrate and protein thresholds. The catalog covers 93.93% of
reference ingredient mass, but selected exact IDs cover 51.63%; 87.45% of omitted
exact-ID mass is already in that catalog. Shared-ID densities agree to numeric
precision. These are posthoc development diagnostics, not independent acceptance
or proof that every ID disagreement is a visual omission.

Test one fixed two-stage method: do catalog-guided identity hypotheses and
component-specific training comparisons reduce wrong identities and mass
allocation enough to improve the full five-target MAE profile? No alternate
prompt, support rule, density blend or calibration is selected within K.

## Fixed inputs and isolation

Use the existing 230-image independent training release, 164-entry catalog,
training ingredient masses, official cached gallery embeddings and the same
84-image/78-group development cohort. Do not download data. Validation remains
sealed. No query reference ID, mass, nutrient, fold, filename or previous scored
prediction is sent to either inference stage. Development labels enter only the
separate scorer after all 84 K records are sealed.

Verify the complete J service continuation and its source/artifact bindings
before extracting immutable description, embedding, retrieval and rerank stages.
A pure whitelist extractor excludes J estimate, items, raw leaves, predictions,
reference labels and scoring data. Only the cached query embedding and ordered
training IDs needed by the rule below affect support selection. Old stages are
provenance, not new calls. K has its own source hashes, protocol binding, stages,
response namespace, attempt counters and complete seal. Existing J responses,
counters and logs are never appended or rewritten.

## Stage 1: image-grounded component hypotheses

Sol receives the full query RGB at native aspect ratio, longest edge at most
1024 without upsampling, and catalog IDs/names (no nutrient amounts). Return
1–8 food groups covering the foreground serving: stable g1…g8, a concise visual
description, normalized box [x0,y0,x1,y1], single/mixed preparation, zero to two
ordered distinct catalog-ID hypotheses, visual evidence and uncertainty.
Hypotheses are alternatives, not additional foods or votes. Unknown food is
represented by an empty hypothesis list, not a forced nearest catalog ID.

Groups represent edible entities, not both a composite and its ingredients.
Boxes may overlap because foods occlude one another; their mass must not be
counted twice. All coordinates must be finite in [0,1] with x1>x0 and y1>y0.
This stage estimates no mass or nutrition. Format validation gets at most one
format-only repair preserving the initial interpretation.

## Deterministic training comparisons

Sort groups by descending normalized box area, then original group order. The
first four are the major groups for comparisons and crops. This does not limit
the final food count: all groups, plus explicitly marked remaining food, remain
eligible for final estimation.

Process major groups in that order, their hypotheses in returned order. A
training image is eligible for an ID only if it has positive reference mass for
that ID. Rank by (1) whether that mass is at least 25% of the training ingredient
mass sum, descending; (2) cosine with the cached J query embedding, descending;
(3) its ID mass fraction, descending; (4) training ID, ascending. Use only the
frozen official vectors. No query target or ingredient reference enters ranking.
Choose the highest-ranked image whose association group is unused, or reuse the
highest-ranked already-selected image. Record unavailable and budget-limited
hypotheses separately. An arbitrary trace of an ID in a previously selected
image does not automatically satisfy a later hypothesis.

Select at most eight distinct training groups. Fill spare slots using old J's
four reranked IDs in their original order, followed by remaining original
retrieval IDs in order, excluding duplicates and already-used groups. Never
request new searches or embeddings. All query-related group, byte and RGB
exclusions remain enforced. Fewer than eight supports is legal if exhausted.

For each major group, crop its query box with 5% of box width/height as margin,
clipped to image boundaries, using floor for left/top and ceil for right/bottom.
Require a nonempty crop. Preserve RGB and native aspect, do not upsample, and
encode to PNG with longest edge at most 1024. Do not alter image content.

## Stage 2: identity decision and mass budget

Sol receives the full query, up to four query crops, up to eight distinct
training images with actual ingredient IDs/names/masses, the complete training
catalog and the stage-one hypotheses/evidence. At most 13 images are sent, within
the previously verified service capability. Hypotheses can be rejected or
replaced based on the image and real comparisons. Supports are separate dishes;
their whole-plate recipe is never automatically a query component's density.

First estimate the complete edible serving mass, then allocate it to groups and
non-overlapping ingredient leaves. Output total_grams and parents for every
stage-one group, plus an optional remainder parent for visible food missed by
stage one. Each parent gives grams and zero or more leaves; a rejected group
has zero grams and no leaves. Every positive parent has positive leaves with
unique leaf IDs, description, grams, a catalog ID or null, and estimated_density.
Catalog leaves use exactly the frozen density and null estimated_density;
unknowns supply four finite nonnegative per-100g densities. Maximum 20 positive
leaves overall. Sum(children grams)=parent grams and sum(parent grams)=total
within 0.001 g. Programmatic leaf sums, not a model nutrition total, determine
the five predictions. No rescaling repairs inconsistent sums.

Count a prepared composite once, either through a supported composite catalog
ID or through non-overlapping children. A mixed/obscured ingredient can remain
uncertain. Unobserved oil or seasonings are not standalone visible leaves;
uncertain latent recipe possibilities are recorded as text, not hard-added
mass. Do not turn a whole training plate's ingredient list into a component
recipe or modify catalog values to match commercial expectations. Visually
supported prepared-food/unknown density inference remains explicit.

The stage has at most one format-only repair. Store raw replies, parsing,
identity decisions, mass allocations, exact densities and provenance. Native
success, repaired success, method fallback and whole fallback stay separate.

## Service, failures and completed-run behavior

Both new stages use gpt-6.1-sol at the existing zicc route, temperature 1;
completion limits 4096 and 8192 respectively. Reuse original dual-route
credential validation, model checking, secret sanitization, local-image-only
payloads and durable three-transmission request budgets. Read timeout is 600 s,
connect 30 s, write/pool 120 s; maximum two workers. Use the distinct chat
namespace `component-comparison-r5-k.1`. No new embeddings are requested.
Authentication, model mismatch or exhausted service budgets stop the batch and
preserve completed stages. They are never converted into successful fallbacks.

After one structural repair, an invalid stage-one or final response uses the
same fixed external-training five-target medians as J, marking whole fallback.
Do not substitute a previous method's answer or drop a row. No retry depends on
error magnitude. A completed run verifies and replays locally with no Provider
construction or new request. All 84 predictions must seal before any score.

## Predefined evaluation and falsification

Keep ASA24's existing passing conditional method unchanged. K uses every one of
84 Nutrition5k records, including fixed fallback, with existing reference means,
full-precision absolute and per-unit caps and grouped bootstrap reporting.
Report all 20 combined checks; no per-target splicing. Compare K to unmodified
raw J by lexicographic (maximum cap ratio, mean cap ratio) over the ten
Nutrition5k checks. The unchanged ASA24 checks remain in the joint hard gate
but do not select a Nutrition5k profile. Promote only strict whole-profile
improvement, with no formerly passing check crossing its cap.
No additional K calibration or blend is registered.

After scoring, run the same descriptive exact-ID/mass diagnostics separately;
never call exact-ID misses visual omissions by definition. The proposed
mechanism is unsupported if available-ID reference coverage and exact-ID mass
overlap do not improve, or if shared-ID mass error does not decrease. Improving
these diagnostics alone does not establish MAE improvement or acceptance. A
failure is backed up safely and motivates another separately registered method;
it does not open validation or trigger per-iteration formal reports.
