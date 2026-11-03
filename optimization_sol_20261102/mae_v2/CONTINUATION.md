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
`THwo0t/DietAI24-reproduction`. Source commit `a740851` is confirmed pushed and
contains completed round 3 comparisons plus reviewed continuation source, with 181
explicitly allowlisted members. Reachable-history/worktree scans and exact plus
truncated checks against both actual credentials passed. New research data,
per-query outputs and API logs remain private. Final reports remain deferred.
