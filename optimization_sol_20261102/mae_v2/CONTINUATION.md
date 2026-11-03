# Continued MAE optimization — 2026-11-03

The user requested a GitHub backup of the current failed iteration and continued
optimization. Do not produce a final report for every iteration. Final report
and Mac packaging work is deferred until the target is met.

V2 is preserved as completed: ASA24 10/10 MAE checks on 16 Exact records out of
99 (9 Exact groups); Nutrition5k 0/10 on all 84 development records. The selected
N5 method is calibrated C using A identities, without crops. The current user
priority is MAE first, recognition second. All numerical caps remain unchanged.

The next round must use only the active development population and keep the
200-image validation cohort sealed. Existing raw predictions, freezes, protocol
and selection are immutable. No repeated response sampling based on error and
no dropping difficult records. The next candidates will have a separate
registration and output directory. ASA24's passing method is retained.

The source backup includes current source, synthetic tests, protocol, review,
and aggregate development evidence. It excludes credentials, raw API/process
logs, research images, row predictions, private metadata, local Git history,
and unfinished report artifacts. The unfinished reporting/demo tools are saved
as source only and do not establish a completed delivery or Mac validation.

Round 3's F, G, H and I completed all 84 development images and each passed
0/10 Nutrition5k checks. H/I and the two preregistered fixed ensembles passed
read-only completed-artifact verification with zero new API calls. Each method
has separate frozen source, protocol, response namespace and records. The fixed
raw-CHI median is best by the registered worst-ratio ranking: MAEs 72.9643 g,
110.3213 kcal, 7.8969 g fat, 11.6469 g carbs and 10.0102 g protein. All five
improve on v2's selected C, but still fail every N5 cap. See
`round3/development_checkpoint.json`; do not rewrite the original v2 selection.

The bounded-scalar oracle and all twelve raw-C semantic-neighbor variants also
failed. Do not spend 336 nested H calls on the ruled-out scalar family. Round 4
instead prepares appearance descriptions, official embeddings, top-12 visual
reranking and four-example ingredient/mass estimation. Its base will use only
new external training labels, including its fallback; the existing 84 dev
labels are reserved for scoring and any separately registered OOF calibration.

The independent training proposal is exactly 230 images / 230 conservative
screening groups, 104,830,902 cached bytes. SHA-256:
`eddf9a644114f5b4aecc4d906dbdec6ee0eaecd80b97e23743d9edf663e03eb0`.
The user approved it by replying “确认”. All 230 files downloaded successfully
in 230 attempts, totaling 104,830,902 body bytes. Blind screening retained all
230 images/groups and a 164-class ingredient catalogue. The initial preparation
failed on one official 2 g mass discrepancy; its exact source/row-hash exception
is documented before J, preserving every original field and the strict general
0.001 threshold. The release freeze is
`885f8d1a0573313e9e09771f3c38ec938b807e9ffcc9525d706867d3d0d081cb`.
The image-body transfer cap is 350,000,000 bytes with three durable attempts per fixed URL. Keep all
incoming files unavailable to training until blind pixel deduplication and
quarantine finish; never substitute a new image without approval. Paid project
development already has unlimited user authorization; do not ask for it again.

Round 4 implementation is now complete offline: pinned downloader, blind training
release, training-only 13-image capability probe, image-bound external-gallery
pipeline, persistent artifacts and a separate complete-population scorer.
The earlier 188 synthetic tests passed in the public source copy; the expanded
213-test suite now passes in the workspace with networking disabled. The fixed
training-only 13-image probe passed with one successful request, no repair.
`round4/PROTOCOL.md` is frozen in commit `27a31bd` before gallery/development
inference. This establishes engineering/service behavior, not MAE improvement.
See `round4/README.md` for the resumable command sequence. Raw J is followed only
by the separately preregistered grouped OOF aggregate calibration candidate;
formal validation stays sealed and reports remain deferred.

The gallery subsequently completed all 230. J stopped after its coordinator
reported 49/84, because one rerank payload exhausted three ReadTimeout attempts.
Outstanding workers left 52 sealed estimate stages, 53 descriptions/embeddings/
retrievals and 52 reranks. No full J seal, score or calibration exists. Preserve
this failed run and every successful answer. `round4/service_interruption.json`
records safe counts/usage. A separate service continuation is registered in
`round4/continuation/SERVICE_CONTINUATION_PROTOCOL.md`: 600-second read timeout,
one extra transmission only for the exact exhausted payload (cumulative cap 4),
all other payloads retain cap 3, and original stage/counter provenance is kept.
Its new runner/evaluator must be tested and frozen before actual continuation.

The continuation implementation has now passed its one independent review, with
R-SC-1/2/3 fixed and 36 offline tests passing. A network-isolated real import
preflight validated all 263 sealed stages and 52 complete old predictions without
creating a provider or new run. The private registration binds 35 old source
files, 7 new source files, 792 old artifacts, 213 original counters and 212
successful response caches. Only the remaining 32 queries require completion.
Use the separate continuation entry points in `round4/README.md`; do not change
the original J or open validation. The continuation has now sealed all 84 base
records (completion `11fc4c720a3bd9c5b59cd5f3cca8fb291b0865e9ebc8e32e8643498d3ae22b1f`).
It used 126 successful requests and two timeouts. Its last estimate returned on
its third cumulative attempt; no further exception or service fallback was used.
Offline full-population scoring/calibration is complete. Request/token aggregates
are recorded separately in `round4/service_completion.json`; timeout-side billing
is unknown. `round4/development_checkpoint.json` records the completed decision:
raw MAEs are 67.20238 g weight, 102.18845 kcal, 8.36883 g fat, 10.52197 g carbs,
and 8.96837 g protein. Raw and calibrated each pass 0/10 N5 checks. Calibration
reduces mean threshold ratio but worsens the maximum from 1.77803 to 1.79571;
the fixed rule therefore retains raw. ASA remains 10/10, joint 10/20. There are
two format repairs, no whole/method fallback, and no missing prediction. Formal
validation remains sealed. The posthoc mass/density/catalog-coverage diagnostic
has 18 passing synthetic tests and completed only after the final score seal.
Its independently verified aggregate is `round4/diagnostics/development_diagnostic.json`
(completion `7212c0eaf8771aeedae85faa411268275aba98d5dce0c355a3877dc485452658`).
Even oracle true-weight scaling leaves fat/carbs/protein MAEs at 8.50032,
8.41922 and 7.38517 g; this is a nondeployable diagnostic, not a new candidate.
Exact present IDs cover 51.63% of reference mass, with 44.57% exact mass overlap.
Omitted exact-ID mass averages 148.02 g, of which 129.45 g is already available
in the training catalog and 18.57 g is outside it. Exact-ID disagreement is not
proof of visual omission. Shared-ID density differences are numerical roundoff;
identity/composition and mass allocation need investigation before another run.

A zero-API external-training prior experiment was separately preregistered in
`round5/PRIOR_PROTOCOL.md` before fitting. Its fixed 230/230 five-fold OOF and
33 synthetic tests completed. Relative to fold median baselines, four of five
MAEs improved and the mean ratio was 0.9131544756; however 86.10% of predicted
ingredient mass was allocated to absent exact IDs. The gate permits further
investigation only. This dense regression is not a final predictor or a food
recognition result, and no Sol-prior experiment has been launched. All evidence
is in `round5/training_checkpoint.json`; private OOF/fold records stay local.

The public backup branch is `codex/mae-v2-backup-20261103` in
`THwo0t/DietAI24-reproduction`. Public commit `36be2b8` is confirmed pushed and
contains completed J/scoring/diagnostics plus the separate training-prior source,
with 193 explicitly allowlisted members. Reachable-history/worktree scans and exact plus
truncated checks against both actual credentials passed. New research data,
per-query outputs and API logs remain private. Final reports remain deferred.


Candidate K is registered in `round5/K_PROTOCOL.md`: one image-grounded
component-hypothesis stage, deterministic identity-specific training supports,
then parent/leaf mass allocation with conserved totals. It reuses immutable J
upstream data and the same 230 training / 84 development images. No dense ridge
prior, extra calibration, target splicing, new download or validation access is
part of K. Its one independent review approved K1/2/3/5 and required R5-K4-1.
That fix is committed in `5b73b0a`: read-only cache/log/counter checks at resume
and replay, scoped per-request audits, and a separate completion-provenance
stage. All 154 synthetic tests pass with networking disabled, including actual
MockTransport sealed-run tampering and interrupted-reservation budget tests.
The original preflight passed before the engineering fix and remains an as-of
receipt only; a post-fix persistent network-isolated preflight has passed all 84 queries
and 230 training images, with zero API calls. Its hashes and the 154-test
public-copy pass are recorded in `round5/readiness.json`.
K subsequently completed inference and full scoring. Keep all inference sources,
tests and artifacts unchanged. Follow `round5/README.md`; final reports remain
deferred, and the validation cohort remains sealed.


K development was then launched persistently with two workers. Its PID is in
the private launch receipt.
The private receipt is `round5/launch/K_launch.json` and log is
`round5/launch/K.log`; public source/readiness backup `cb2dc4d` is confirmed
remote. Do not start a second K run, change frozen source, reset counters, or
score partial results. The first 84 log progress events are parent-J cached
verification, not K predictions; actual K progress follows them. A service stop
requires preserving/reconciling state, not regenerating completed answers.

K has now sealed all 84 records, including one fixed external-training median
fallback. There were 181 successful HTTP requests, no HTTP errors, 12 identity
format repairs and one unsuccessful mass format repair. No new embeddings were
requested. Returned usage is 2,796,448 prompt and 106,552 completion tokens;
31,384 reasoning tokens are already included in completion. Billing is unverified.
See `round5/service_completion.json` for safe counts only.

The independent network-disabled scorer completed all checks and preserved ASA.
K MAEs are 83.11905 g weight, 120.71628 kcal energy, 8.97862 g fat, 10.44311 g
carbs and 10.53377 g protein. K passes 0/10 N5 checks, 10/20 combined, and is
rejected: its worst N5 threshold ratio is 2.08838 versus raw J's 1.77803.
Four MAEs worsened; only carbs improved slightly. Raw J remains selected and
still fails the target. The score seal is
`54833d081661b21fc9c00c3e32bf4482ca8c83be1a72f39036c69f198b38a2f9`.
`round5/development_checkpoint.json` contains the safe full aggregate.
The independent posthoc diagnostic completed with networking disabled. Exact-ID
mass overlap fell from J's 44.57% to K's 37.23%; reference mass with predicted
present IDs fell from 51.63% to 43.64%. K has 83 decomposable rows plus its
fallback versus J's 84, so shared-ID-only error changes do not establish an
improvement. Even true-weight oracle scaling leaves energy/fat/carbs/protein
MAEs at 93.91897 / 8.74002 / 8.98778 / 8.19471, all failing. The proposed
mechanism is unsupported. See `round5/development_diagnostic.json`, completion
`88ca175c290f5462da7f43e5eaf75915db7850a77242d78e770b19713fe6bb25`.
Back up this failed iteration, then continue without a new formal report.

`round6/PROTOCOL.md` registers a training-only 25-group paired pilot: return to
J, keep the same four supports, and test automatic ingredient-region hints/crops.
Five-fold assets exclude the query's entire fold. The fixed advance gate must
pass before a new 84-image development candidate is even registered. Sources
are in implementation; no L request or real training annotation has begun.

## Latest steering and working state (supersedes the L plan above)

Every complete improvement now requires the same common method on both ASA24
and N5. The old ASA score cannot be combined with J/K/L to imply a common-method
dual-dataset experiment. The user allows one or two failing MAE items in each
dataset; `round7/PROTOCOL_DRAFT.md` conservatively preregisters at most two of
ten numerical checks per dataset, retaining all original caps and strict20/20
reporting. This draft is not an execution freeze.

L source is retained and its paid CLI is explicitly shelved. It has 96 passing
network-disabled synthetic tests in the public copy, no real preflight, no
annotation and no paid request. The next common M design returns to zero-shot
FNDDS and tests an exclusive children-versus-whole accounting route. No supervised
recipe dictionary, examples, crops or calibration are part of M. Original 4o/Sol
test comparisons are descriptive diagnostics only, never method-selection data.

Round7 R7-B implements the common accounting core and has 18 passing synthetic
tests. R7-C onward (historical importer, dual-role runtime, isolated adapters,
scorer and runner) remain unfinished. No M service client or paid request has
been created. See `round7/CHECKLIST.md`; complete the one independent review,
fixes and immutable freeze before paid execution. Validation remains sealed.

The latest confirmed public backup is `ed179b0b5d87ba825d9e19bd3c26597adac31638`
on `codex/mae-v2-backup-20261103` in THwo0t/DietAI24-reproduction: K failure,
full-project review, L source/shelving and the project-only subagent policy.
It contains 235 explicitly allowlisted payloads. The newer M draft/core and
latest policy wording are not yet public. Never publish local Codex config.

All newly created subagents in DietAI24 explicitly use gpt-6.1-sol, with no
Astra fallback. The global subagent-model override was removed after the user's
scope correction; unrelated projects inherit the main conversation model.
Only project `.codex/config.toml` sets the Sol default. Do not wake legacy
subagents whose prior model cannot be changed.

Dot's separate first-formal 4o/Sol diagnostic is now implemented and executed in
`round7/tools/diagnose_original_comparison.py`. It reproduces all300 prediction
rows, using prediction-column whitelists and original generic FNDDS densities,
without importing inference/config modules, loading query labels, opening any
validation file or calling an API. Safe aggregates are
`round7/original_comparison_diagnostic.json`; private per-dish chains are ignored
under `round7/diagnostics/original_comparison/`. Coverage86/118/common79 is
reproduced. The paired79 show74 changed final-code sets and41 changed item
counts. These are descriptive historical observations, not causal findings or
selection data. No M source/configuration was changed based on this audit.

## M is now implemented, reviewed and frozen

R7-C/D/E/F are implemented in `round7/src/`. One independent gpt-6.1-sol review
found only R7-G-1(P2): new cache answers lacked a success-log value digest. It
is fixed in `2c36c3e` with both chat and valid-vector tamper negatives; all38
network-disabled synthetic tests pass. The reviewer independently replayed all84
raw-C inputs and all3159 imported embedding sources. See round7/REVIEW.md.

The final protocol is round7/PROTOCOL.md; review_gate.json and private prepared
freeze.json bind the approved/fixed state. Freeze file SHA256 is
`b2d832529ed8453d2c5d9bebf645e8716f3d39185e0e3070e78cd4b3b486261b`.
The guarded real preflight passed183 dev images,84 imported raw-C computations,
3159 old embeddings and20 source/input pins, without Provider/credential/query
label/validation access or file/mtime changes. No M accuracy result exists yet.
Use round7/README.md for resumable commands. Do not change frozen method files,
reset counters, rerun completed answers for accuracy, or open validation early.

M is now launched persistently from frozen source commit `9d74f25`, with two
workers. Inspect `round7/launch/M_launch.json` and its private M.log before any
resume; do not start a second coordinator. The initial real responses returned
HTTP200 and the expected reported model names for both Sol chat and official
embedding. No complete M score is available. All-science completion precedes
offline verification and paired full-population scoring; source files remain
unchanged while this run is active.
