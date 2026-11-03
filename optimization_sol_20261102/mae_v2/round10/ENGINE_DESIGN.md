# O orchestration implementation notes

Engineering notes, not an experiment result or final report. Keep root as the
single writer. No O paid request before complete implementation, one independent
review/fixes, final protocol/freeze and guarded preflight.

## Already implemented

source_portions.py reuses the old flat Pipeline.identify_select flow and owns
the new standard-first/adjustment quantity core. context_o.py imports exact
183 inputs and frozen other-fold medians without query labels. conditional_o.py
is a pure code/catalogue projection requiring complete coding proof. records_o.py
keeps main/E2E and conditional vectors/provenance separate.

service_o.py is a separate N-derived dual-role Ledger with8616 theoreticalslots,
max3 reservations per exact payload, raw outcome→anchor→cache recovery and
explicit import-usage receipts. runtime_o.py has lazy role-separated OProvider,
Trace and verify_reference; exact TaskGate/replay integration is now implemented.
imports_o.py registers old official embedding sources:3159 frozen legacy entries
plus201 verified M successes=3360 unique entries,0 blocked. Real guarded
preparation used0 query-label/key/validation/Provider/network and0API.31 synthetic
tests previously passed; the complete suite now has38 unique passing tests,
including a full ArtifactStore coding→adapter→final seal→Provider-free replay.
Actual O HTTP usage is still ZERO; MockTransport tests are offline.

## Implemented TaskGate and runner design

Reuse exact existing Pipeline.identify_select rather than inventing another
prompt copy. It invokes identify chat, embedding queries, then select chat.
The gate can reconstruct this method using frozen pixels/config and callbacks
that return earlier ledger/import answers and capture the prospective request.
Map actual _stage names identify/select/source_standard_first/
portion_conditional_option_continuous_option to identify/select/whole/conditional.

For live identity dispatch, chat is identify until the first embed callback,
then select. Preserve separate refs lists for these two stages; retrieval refs
span all embedding batches in fixed query order. Trace.expect can accept an
existing refs list so format repair retains ordinal1 across callback scopes.
For whole/conditional calls the chat phase is fixed. Every callback must pass
the frozen gate; the phase dispatcher is not the sole admission authority.

For Gate.validate(sample,stage,ordinal), reconstruct the identity chain using
the real frozen Pipeline and capture exactly the target request before it is
sent. Earlier chat requests must match immutable bound slot/payload/cache/body
provenance; earlier embeddings must match fixed query index/text and verified
import usage or O reservations. Select therefore uses freshly reconstructed
cap32 banks, not arbitrary caller identities. Whole reconstructs identity,
checked_items and portion_context before constructing the quantity task.

For Gate.format_error, a gate-only subclass can intercept _stage's actual parser
at the named target, run it on the recorded initial raw answer and return its
ContractError code (or None for a valid answer). This avoids merely trusting a
caller-declared error and supports the old Pipeline FORMAT repair prefix.

Use separate private ArtifactStores: runs/identities for all183 coding records
plus identity service proof; runs/conditional-adapter for allowed ASA contexts
plus provenance; runs/development for all183 final records plus service proof.
Before sealing identities, replay them with zero Provider and exact request refs.
Identity proof must pin its immutable request bindings/reservations/outcomes/
caches/import-usage subset, not the entire mutable admission.json (later quantity
calls append to it). On conditional admission verify the complete183 identity
seal/proof and the current row's reconstructed identity/coding. Never accept a
caller-provided identity or target context.

Only the isolated post-coding adapter process reads dev labels, confirms frozen
label SHA and coding completion, projects food_code only and supplies complete
generic asa_options after Exact. No weight/nutrient/selected-option/size/bin or
filename goes to the main inference process. Adapter output itself is sealed
and bound to coding completion/source/label digest. All99 E2E remains label-blind.

The runner then completes whole-serving predictions and permitted conditional
branches, atomically falls back failed images/options, seals all183, replays
zero Provider, then separately imports labels for OOF scoring. Reuse current
five folds explicitly; one dataset-level mass factor, not five nutrient winners.
ASA scales continuous grams then projects; final legal option stays unscaled.
Report raw/OOF together and keep every failure. Do not use R9 oracle masses.

Exact stage/replay/label isolation/repair negatives, score/fold/failed-record
checks and a complete synthetic ArtifactStore integration now pass. Real
pre-review preflight passed all183 initial tasks without Provider/keys/query
labels/validation/network. O-C..F is ready for one independent Sol review;
freeze and paid inference remain prohibited until its findings are fixed.
