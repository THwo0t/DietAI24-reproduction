# Next development coverage phase — draft, no new run

User authorization relayed by Dot on2026-11-04 permits more API allowance and
testing-image downloads after the existing O batch finishes. O must complete
unchanged and be scored first. This document records source-only preparation;
it is not a sample freeze, completed audit, download or prediction registration.
Independent validation stays sealed. No final report is requested at this stage.

## Population proposal to finalize after O

- Keep the current ASA99/23 development groups and N584/78 groups as a named
  historical core, preserving its exact IDs, photos, labels and fingerprints.
- N5 proposed total300: add216, not200, because the current usable core is84.
  The old100-row manifest cannot silently restore the16 removed images.
  Use the existing official overhead-RGB candidate inventory and metadata,
  fixed seeded ordering, then the full exposure/association exclusions below.
  No seed switching, error-based selection or automatic replacement after
  failed downloads. Freeze actual completeness before any new model inference.
- ASA original284-code eligible frame has no unused independent group: all46
  historically safe groups were assigned23 development/23 validation. Expand
  coverage within the23 existing development groups using all eligible portions,
  keeping the original99 as the paired core. New rows do not create new groups.
- Separately audit a broader ASA frame by removing ONLY the top1000 rank filter.
  Retain exact FNDDS2019–2020 mapping, PORTION, ModCode0, valid unambiguous
  weights and at least3 distinct weights. Target20 additional safe groups with
  fixed group ordering; if fewer qualify, retain all and report the shortfall.
  Do not borrow any validation group or reroll. Report this expanded-frame
  population separately from the original-frame core; do not hide changed scope
  inside one apparently paper-identical denominator. Actual row count is unknown.

These are proposals, not claims that216 dishes or20 ASA groups already pass
the audit. Final cohort rules/counts and download limits must be registered
before selection/download; the predictive method is chosen only after O score
and full-project retrospective. Every complete candidate is evaluated on BOTH
datasets, with core and expanded strata and the full frozen denominators.

## Blind preparation requirements

ASA metadata sources: ASA24_ImageMetadata.xlsx AssociatedCodes and
ImageFileInventory; local portion-image ZIP inventory; FoodWeights.csv; FNDDS
food codes and original top1000 table. Build complete code—image—byte-hash
connected components BEFORE eligibility filtering. Do not assume17135 PNG
members are17135 independently evaluable foods. A prior SHA registry can be
reused only if it covers the additional images exactly; otherwise hash local
ZIP members in the isolated preparer. Export only aggregate isolation proofs,
not validation rows or code membership, to the implementation conversation.

N5 metadata sources: both complete variable-length cafe dish tables, available
metadata and official realsense_overhead_objects.json. Preserve existing food
signature, largest-mass representative, available-RGB and complete-label rules.
Also retain mae_v2's complete raw-cafe scan linkage: equal positive ingredient
mass vectors, exact/adjacent scan extensions within600 seconds, ambiguity
quarantine, byte duplicates and decoded-RGB duplicates. Recipe-name equality
alone is insufficient. Reuse the pure parse_metadata/build_components logic
from src/cohorts_v2.py, with its source hash and full-universe grouping frozen.
Exclude old dish IDs, ingredient-signature associations, byte duplicates,
all registered original test/dev/smoke/gallery/reference/interrupted selections,
the current clean development core,230 selected training images and all frozen
validation/replacement associations. Current registries must be reconciled
before claiming the initial theoretical1425 unused dishes are still available.

Validation metadata/byte hashes may only be used mechanically by the isolated
association adapter to reject intersections. No validation image inspection,
nutrient/weight distribution analysis, model prediction or method selection.
New images sharing a dish, recipe or photo component stay in one group; folds
operate on full association groups. Old exposed samples may be engineering
regressions but are never renamed fresh independent observations.
If new linkage evidence connects a current development component with sealed
validation, stop preparation and report the blind intersection count. Do not
silently drop only the new bridge, relabel the graph, alter validation or claim
that prior isolation survived. Register any required repair separately.

Proposed new N5 transport budget:200 MiB response bytes including retries,
5 MiB per image response, at most3 attempts per fixed URL, official source only.
No extra ASA network download is assumed while the full local ZIP is available.
Record URL/source version, HTTP result, bytes, type/dimensions, SHA and retries
privately; verify eligibility and blind duplicate isolation before cohort freeze.
Do not publish new research data or raw logs under the source-backup permission.

## Engineering before the enlarged paid batch

The ongoing O implementation repeatedly replays full identity service proofs
inside conditional task validation. Do not patch its frozen run. For the next
phase, implement one in-process verified identity snapshot: full semantic proof
on creation/restart, exact content hashes and identity-related admission
projection checked on every use, unchanged per-task payload/repair/Exact/menu
validation, full final audit. Never trust completion existence, mtime or size
alone. No on-disk verified=true shortcut and no silent cache refresh on drift.

Synthetic checks must cover same-size/mtime tampering, symlink substitution,
changed old bindings/outcomes/import vectors/sources, legal ledger append,
caller mutation, restart and partial seals, and cached-versus-uncached task /
record / failure equivalence. Then one independent bounded review and fixes.
Only after this, register the selected common predictor and new scale-bound
service slots, fallback/OOF rules, failure denominators and comparison/stop rule.
Existing identical completed answers may be reused only through an explicit
same-payload provenance import, never by mixing historical method scores.

Keep Sol and official embedding credential routes separate. Record actual
requests and prompt/completion tokens by provider, imported logical answers
separately; reasoning tokens are already in completion. Report money only from
verifiable prices or an actual bill. No routine budget question is needed under
the existing authorization. Formal reports and Mac refresh remain deferred.

## Preparation status (no actual data run)

Pure association/ambiguity/group-order helpers and a verified-loader prototype
exist.58 unique synthetic tests pass in `unshare -Urn`; the integration fixture
uses actual temporary ArtifactStores, original TaskGate and MockTransport.
Repeated conditional validation uses one full identity proof, with exact same
payload as the uncached gate. Source/image/catalog/manifest drift, altered
historical outcomes, same-size/mtime file changes and symlink substitution
refuse; legal quantity appends preserve the sealed identity. Terminal full
revalidation and a distinct-process factory call perform the full proof again.
Complete synthetic runner results and service counts match the uncached runner
for native success, permanent whole-task format failure and permanent
conditional-task format failure. Nonempty source/import/legacy file inventories
are exercised; changing any of those dependencies after verification refuses.
The distinct-process completed replay forbids Provider construction. These
fixtures use synthetic temporary files and MockTransport, not real imported
embedding corpora or an actual enlarged cohort.

This is no real-data performance benchmark, completed expansion audit or ready
paid runner. The snapshot is NOT installed into O. Finish the real blind
preparer, freeze final cohort/experimental rules, finish next-phase integration
and one bounded review before any enlarged paid run. No new download or model
request, validation access or method selection has occurred in this phase.

P-B also has a pure N5 candidate-pool prototype: it consumes already verified
full scan/RGB components and all five exposure roles; original recipe and
missing-label rules remain. A validation/exposure bridge or new validation
ambiguity refuses preparation. Selection uses one fixed representative per
complete component and reports a shortfall rather than filling it with related
scans. Seven pool tests pass, including a poison target object proving that
protected components and related recipes are rejected before numerical target
inspection. This negative case catches one failure against the previous pool.
This new pool prototype and the not-yet-written real I/O adapter are outside
the completed P-A cache/component review and require their own full-scope check.
No actual pool, validation file or recipe/target distribution has been loaded.

Source-only adapter advice additionally found that old `load_asa_sources`
filters PORTION/ModCode/ZIP before graph construction, so it cannot establish
the complete broader-frame bridge closure. Build raw code/photo/hash closure
first and only then apply eligibility. The actual exposure registry must prove
coverage of selected/interrupted proposals as well as completed runs; merely
passing five empty role collections to the pure pool is insufficient. Never
call old `cohorts_v2.prepare`, which contains sealed-label loading and obsolete
validation repair logic. Extract only its pure parser/component/fingerprint
rules into the new isolated adapter. These are source-derived obligations,
not evidence that any real exposure audit has been completed.

The fixed R4 private audit index can supply previously audited byte/RGB identity
anchors. Reconcile its seal-bound snapshot/proposal identities with ALL230
training proposal rows and their complete candidate-audit fingerprints, then
rebuild the full raw graph and stricter recipe/byte screening closure. Do not
rehash its entire source-path inventory indiscriminately: some entries point
to validation images/manifests. Compare only permitted seals; unchanged seals
establish an unchanged historical identity snapshot, not a fresh integrity
check of unopened protected files. Protected-file integrity, if required, must
be a separate blind hash-only process. No validation target fields are needed
by this identity adapter. Its actual I/O implementation is still pending.

`n5_identity.py` now implements the pure reconciliation part: reproduce the
supplied original full raw and recipe/byte screening partitions before merging
all selected training pixels; enforce registered84/200/100/230 identity counts
in the future production caller; project all five protected roles; preserve
every old blocked screening exclusion even without a separately named reason;
and refuse any new validation/role or validation/ambiguity linkage. Its private
return retains identities, while its aggregate contains only fixed counts.
Six synthetic tests cover missing quarantined-training pixels, byte/RGB bridges,
changed snapshots/index/counts, retired original dev and transitive unselected
recipe bridges. Input authentication and latest exposure completeness remain
the future isolated I/O caller's obligation. No real files were reconciled.

`asa_identity.py` separately preserves every supplied metadata code/photo edge
even when its actual bytes are unavailable. Known byte hashes are a sequence
so conflicting ZIP basenames cannot be hidden by dict overwrite; unknown image
names must match the exact uncovered metadata names. It reports observed
protected intersections and unresolved components. Any missing byte or unmatched
protected anchor prevents a complete supplied-graph byte claim globally;
quarantining only the unknown component cannot prove independence elsewhere.
Even a fully covered supplied graph does not authenticate source completeness.
Six synthetic tests cover these limits. The strict previously reviewed
`qualification.associations` interface is unchanged. The real preparer must
prove complete source/member coverage and stop on new dev/validation bridges.
New links merging old development folds also require an explicitly registered
fold repair before the enlarged phase; never silently preserve leaking folds
or rewrite the current O/core bindings. No real metadata or archive was opened.

The N5 fixed identity reader and pool-computation path now exist as prototypes:
`n5_sources.py` authenticates exactly15 named seals/audit/metadata sources through
fixed or seal-bound hashes. It never follows arbitrary paths in old source
inventories, nor opens validation manifests, images, labels or credentials.
It projects only identity/fingerprint fields from training audits. The captured
raw CSVs are consumed by `n5_preparation.py`, which reproduces the original
variable-width parser, rebuilds the supplied identity closure first, then parses
the five numerical targets ONLY for unblocked original-frame candidates.
Official object-name/size and recipe-dedup rules remain; individual zero nutrient
values are valid and all-four-zero missing nutrition is excluded.

Thirteen new synthetic tests include a complete restricted-reader→pool path,
original parser equivalence, poisoned protected targets, arbitrary inventory
paths, symlink/same-size drift, ambiguous pins, duplicate/nonfinite JSON,
listing mismatch and a new validation bridge that refuses before candidate
target parsing. These functions have no real-data CLI, selection, download,
inference or source-audit receipt. A reviewed phase runner, actual latest
exposure inventory/discovery, source-completeness proof, ASA adapter, registered
sampling rules and post-download dedup are still required. No production
anchor override may be exposed by that runner; fixture overrides are for tests.
All50 current unique preparation tests passed offline using synthetic inputs.

`asa_eligibility.py` adds the pure legal-portion stage after an authenticated
complete identity screen: preserve PORTION/ModCode0, exact FoodCode/PortionCode
weight mapping, gram98, dominant portion code, one-percent consistency,
single-weight portion descriptions and at least three distinct weights. The
broader frame removes only top1000 membership. Same-code/same-byte conflicts
are explicitly returned for source repair checks; missing portions and
nonquantitative weights are not accepted. Protected codes are skipped before
numerical conversion. Seven synthetic tests include differential comparison
with original `asa24_proc.add_weights/select_image_links`, poison protection,
exact one-percent boundary and invalid/conflicting units. Original core
reference/fold pins still require a separate exact comparison before any real
phase freeze; no old dataset is rewritten by this helper.

The bounded P-B component scope is ready for its first independent review,
tracked in CHECKLIST.md.57 unique tests passed. This is separate from the old
P-A cache review and from the pending full P-C/P-D data/run integration review.

The single bounded P-B component review is complete:0P1/1P2/0P3. R-PB-1 is
fixed by checking exact-key conflicts before zero-only sentinel exclusion;
both0/positive source orders refuse, identical duplicate mappings and gram98
behavior remain. The added negative test catches2 old-source failures,0errors;
all58 current unique tests pass. Actual-data completeness, phase guards,
sampling/download and common-predictor integration remain unapproved/pending.
