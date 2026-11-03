# N: uncertain food identity and canonical FNDDS portions

Registered working design after complete M failure and its remote-verified
backup a227a740f473ac964cc0b536228b819f23da0e45. Not an execution freeze.
Implement, test, independently review once, fix and freeze before paid N calls.
Existing development-call authorization persists; no new download is needed.
All new DietAI24 subagents explicitly use gpt-6.1-sol; no global model override.

## Decision and evidence

Reject M. Both datasets' full-serving five MAEs worsen relative to M0; ASA
coding is9/99 in both, below the15-record floor. M0 fails4/10 ASA and10/10 N5;
M fails9/10 ASA and10/10 N5. N5 errors are broad, of both signs, and contain
mass and effective-density discrepancies. Whole collapse occurs on only8/84
N5 images and no ASA image; reclassification and new quantity draws also change
results. Neither arm qualifies for validation.

The released nutrition implementation averages multiple selected FNDDS code
densities per physical food (`code/nutrient_estimate_mix.py:66–80`). The paper
does not explicitly specify this averaging, but it describes standard portions
and unit/count adjustment (paper.txt:179–186). M uses single-code leaves and
free total-ratio quantities. Restoring either mechanism is a hypothesis, not a
guarantee. Old E already failed with units on old C/A identities; that result
requires this bounded comparison, not an assertion that units must improve.

## Fixed shared upstream and populations

Unchanged ASA99/23 groups and N584/78 groups, same5 folds and image fingerprints.
Keep original tests diagnostic-only and validation sealed. No labeled gallery,
ingredient-ID dictionary, examples, crop, calibration, direct nutrient estimate,
new food region or reference-directed correction.

Import the completed M0 upstream computations exactly: raw-C image layout and
hybrid32 child candidate banks on both datasets. M0 N5 is historical raw C;
ASA M0 is the new round7 result. Preserve all original parents, geometry,
physical leaves and descriptions. Do not use M whole-collapse results.
Preparation must complete the existing zero-Provider M replay, verify the full
367-record seal, and bind each imported identity, candidate bank and old leaf
mass. No approximate reuse or manufactured modern service receipt.

For a fresh image N-density explicitly runs M0 layout, hybrid32 retrieval,
original single-code selection and original total-ratio quantity before its N
identity/density intervention. Historical grams are not a standalone input
requirement for a new user. N-units uses that same M0 layout/retrieval identity
upstream, then the N identity and new quantity; the old quantity is unnecessary
for its predictions. Keep the exact upstream source/version in the freeze.
Dataset identity enters only fixed population,
failure and scoring adapters. Native RGB aspect, longest edge1024, no upscale.
Sol gpt-6.1-sol at the existing zicc route; official text-embedding-3-large for
the inherited retrieval. This fixed batch reuses verified upstream vectors and
banks; no new embedding request is required or silently permitted.

## One shared identity stage

For each existing physical leaf, use original pixels, its parent/child visual
description and its existing candidate bank. Display a globally deduplicated
generic table of code, food description and catalog category, without nutrient
targets or numeric nutrient densities. No query reference, true code or option
catalog enters the request.

Return one to three distinct ranked plausible identity codes for every leaf.
Use three when three candidates plausibly describe that same visible physical
food; use fewer when fewer are plausible. These are alternative identities,
never three additional foods or a composite plus its ingredients. First is
primary. Every code must belong to that leaf's bank and the FNDDS catalog.
Neither a new leaf nor a changed geometry is accepted. One format-only repair.

Compute the arithmetic mean of the chosen code densities for that physical
leaf, then multiply by its one gram amount. Count each physical leaf's mass
once. This follows the released averaging mechanism without claiming its
correctness or forcing the true code into an output.

Freeze coding before quantity. Sort leaves by descending parent box area,
parent ID, then component ID. Emit all primary codes in that order, then second
alternatives, then third alternatives; stable deduplicate. ASA retains the first
three and designates the first primary. N5 uses all leaves in nutrient totals.
Coding uses no estimated grams or reference labels and survives portion failure.

## Two bounded complete profiles, both datasets

N-density: keep each physical leaf's exactly imported M0 continuous grams;
revalue nutrition with the new mean density. This is an identity/density
intervention with fixed quantities, not a fresh independent M0 mass draw.

N-units: share exactly the N-density identity/coding, then infer new leaf
quantities from generic primary-code FNDDS physical-unit options. Preserve the
old E usable-unit filter for this experiment; do not expand its vocabulary or
candidate cap in this round. Before new identities, it covers95/103 ASA and
338/384 N5 M0 leaves. Coverage after N selection is separately reported.

Programmatically normalize the option's leading positive decimal/fraction/mixed
number to one unit. For example an original `1/2 cup` with100g becomes a
`1 cup` measurement with200g/unit. The model outputs1.5 cups, and the program
computes300g; it never multiplies the half-cup fraction twice. Preserve original
option ID, text, gram weight, exact rational quantity and conversion provenance.
Do not invent a new food unit, silently average conflicting unit weights or use
ASA's reference-specific legal options as generic units.

Deduplicate identical normalized text and grams/unit, retaining source IDs.
Exclude a normalized unit label if its source options imply conflicting gram
weights; record these exclusions rather than displaying indistinguishable
units or averaging their weights. For each primary code
sort by unit family (cup, tablespoon, teaspoon, count), normalized text,
grams/unit and source ID, then retain at most12. This selection is label-blind.
Provide unit IDs/descriptions to the model; gram conversion remains in program.

Every eligible leaf must select one canonical unit and a finite positive
quantity. A leaf without a usable physical unit instead estimates finite
positive grams directly, with that mode explicitly recorded. Do not retain old
grams as a silent fallback, assume measured plate size, clip large predictions,
omit a leaf or change identity in this stage. One format-only repair.

Both profiles calculate five full-serving totals in program, with one mean
density times one mass per physical leaf. No direct nutrient overrides.

## Target adapters and failure populations

After all predictions seal, ASA Exact is the reference code in the fixed top3.
For each Exact row sum grams of nonoverlapping physical leaves whose chosen
alternative-code list contains that code. Map to that code's complete frozen
legal option catalog using the round7 nearest-option/tie rules. Conditional
nutrition uses that exact code density and chosen option, separately from
whole-serving mean-density totals. All Exact rows score; failed portions use
the frozen legal median option. Truth/options never enter model requests.

N5 primary retains all84, including failures. Identity failure yields no invented
codes; quantity failure preserves fixed codes. Whole-serving failures use the
unchanged, other-fold componentwise fallback vectors prepared before M; preserve
their training-fold and reference-hash provenance. Unit-free direct estimates
are native predictions, not fallback successes. Service/model/auth/integrity
faults stop the batch instead of becoming food-prediction fallbacks.

Failure is atomic per image/profile: one missing/illegal identity leaf invalidates
the entire new identity, with no invented codes. One missing quantity, illegal
unit, invalid number or nonfinite conversion invalidates that profile's entire
quantity vector, preserving its already fixed codes. Never keep a partial
nutrient sum, fill a missing leaf with zero, or pass an illegal product into the
ASA option adapter. N-density's imported quantity status and N-units' newly
estimated quantity status are separate evidence, not interchangeable successes.

## Frozen scoring, selection and service limits

Keep all original1.3×paper caps and full-precision decisions. Per-unit is
MAE/reference mean on the same task population, never MAPE. Display every ten
checks per dataset, at most two failures in each separately; also strict20/20.
ASA requires at least15/99 Exact and5 independent Exact groups; separately
report the original18% target, primary hit rate and average final code count.
Always display ASA99 E2E and conditional Exact counts, three size strata,
native/repair/fallback counts and full N584 metrics.

Compare N-density and N-units as whole profiles on both datasets. Apply the
same frozen rank as M (maximum per-dataset failures, worst cap ratio, total
failures, mean ratio, simplicity); ties prefer N-density. Never splice dataset
winners. Coding is shared, so quantity comparison uses identical Exact membership.
Copy the existing M0 aggregate only as a clearly scoped control, not a new draw.
Use association-group95% bootstrap,10,000 replicates, seed20261102. Intervals
are descriptive and do not include repeated development selection uncertainty.

New namespace and own logs/counters/caches under round8/provider/N. No parent
chat-cache import. Fixed temperature1, max_completion_tokens8192, two workers,
read600/connect30/write120/pool120 seconds. Three fsynced reservations per exact
payload, never reset. New successful log/value/cache/ref digests must agree.
Every completed scientific stage reparses from exact raw-response evidence.

In addition to per-payload counters, persist an admission ledger bound to the
freeze and the finite `(sample_id, identity_or_units_stage, initial_or_repair)`
slot universe. Each slot is permanently bound to its first payload hash;
changed messages/order cannot obtain a new budget on restart. At most732 slots
and unique admitted payloads, and2196 total transport reservations. Reserve
slot/payload/total allowances atomically under one durable ledger lock before
transmission, retain unknown-outcome reservations, and verify ledger/cache/log
consistency on startup and completion. Frozen code and registered stage graph
must constrain direct service access as well as cached scientific stages.

Maximum new initial chat payloads:183 identity+183 unit quantity=366; at most
732 with one structural repair,2196 transmissions including transport retries.
No new baseline, embedding or download request. Report actual usage; reasoning
is included in completion. Third-party money remains unverified without billing.

Freeze source, prompts, catalog/options, imported upstream provenance, fallback,
retry rules and scorer after one independent Sol review and fixes. Then run
both profiles for both complete datasets once, verify without a Provider, and
score only after full sealing. If qualified, prepare/review independent validation
without looking early. Otherwise preserve failure, repeat full-project review,
safe-backup the explicit inventory, and register the next bounded mechanism.
No per-iteration formal report or claim of target attainment.
