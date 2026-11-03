# First complete P cohort/runtime/scoring review

Decision: **changes requested**. Findings: **1 P1, 1 P2, 0 P3**. This is the single first integrated review, including postscore; it is not a second review of the earlier bounded service component. No runtime/postscore approval gate, science freeze, paid run, independent acceptance designation, or Mac hardware acceptance is granted. The coordinator must fix both findings in isolated commits and confirm them offline before enabling actual inference. No second formal review is requested.

Reviewed stable source at `9ee076d86271cbc80f98f45eb59b44b48486b55a`, including runtime `d66a987`, scoring `ba37284`, and freeze `9ee076d`. The content inventory below identifies the actual reviewed implementation, including then-untracked modules. Documentation read: AGENTS.md; round11 DESIGN, CHECKLIST, CAPACITY_AMENDMENT, PAIRED_CONTEXT_DESIGN, PAIRED_FAILURE_DESIGN, PAIRED_ASA_ADAPTER_DESIGN, PREPARATION_PROTOCOL, FREEZE_PROTOCOL and POSTSCORE_PROTOCOL. The separate preparation review and its R-PC6-1 correction are inherited evidence, not replaced by this review.

## R-P-1 — P1: freeze the implementation that authenticates blind coding

`identity_gate_p.py:19` and `adapter_p.py:20` import `round11/verified_identity.py`, whose `VerifiedIdentitySnapshot.verify/load/revalidate_full` controls the complete-coding proof before semantic ASA code access and authenticates later scientific replay. However `context_p.py:27-52` REQUIRED, `freeze_p.py:25-27` EXTRA, `postscore_p.py:21-26` SOURCES, and `prepare_p.py:42-60` preparation inventory all omit this implementation. The production freezer unions these inventories (`freeze_p.py:53-58`), and context source validation hashes only that declared set (`context_p.py:174-183`). The resulting science freeze can therefore remain valid after this critical implementation changes; the isolated adapter and completed-run verifier then execute an unbound snapshot implementation.

Evidence: an isolated synthetic ContextTests fixture loaded successfully and `ctx.verify_sources()` still returned true after a newly created, omitted synthetic `round11/verified_identity.py` changed. Import-only discovery of current project runtime/freezer/scorer modules found this as the sole imported implementation absent from the union of runtime, preparation, freeze and postscore source inventories. No real implementation was mutated.

Required correction: make this source mandatory in the scientific runtime freeze and postscore review/source inventory, and add an offline missing-pin/drift regression against the actual production inventory. Do not change historical preparation receipt pins or falsely claim the earlier preparation review covered an unused runtime dependency. This violates FREEZE_PROTOCOL.md:9-15 and :26-29 (bind source/parser modules and completed-run authentication), and PAIRED_CONTEXT_DESIGN.md's frozen-source/snapshot contract. It can invalidate scientific authentication and the label-isolation prerequisite, hence P1.

## R-P-2 — P2: report D-selected first-code recognition separately

`records_p.py:173-182` correctly retains original primary and records D's selected `density_primary_code`/`match.reported_primary_code`, but `scoring_p.py:224-250` sends unchanged `primary_code` to `opt_metrics.evaluate` and adds no recognition report for the D-selected primary. `src/opt_metrics.py:191-209` computes all first-code and size-specific first-code counts solely from that original field. Consequently D and Q+D recognition reports silently describe the original O first code even when D chose a different one; stored private row fields do not supply the required aggregate recognition comparison.

Evidence: five synthetic ASA rows with wrong original primary, true code retained in the common final set, and correct D-selected density primary produced D `first_n=0`, identical to O, with no density-recognition metric. Common Exact stayed complete. Existing 167 tests all passed despite this omission.

Required correction: preserve original-primary recognition and add explicit D-selected-primary first-code counts/rates (including relevant size/stratum reporting and explicit unavailable D failures), without changing common code membership, Exact denominator, adapter truth code, physical grams, or method selection. Add a synthetic disagreement/failure regression. PAIRED_ASA_ADAPTER_DESIGN.md:9-12 explicitly requires both original and post-D primary reporting including first-code recognition; DESIGN.md R11-R-2/R11-R-3 also require primary-order reporting.

## Actual completed preparation examined

After coordinator confirmation of completed preparation, independently inspected only the fixed new seven-field blind manifest, common/cohort/source-closure metadata, fallback/calibration membership proofs, preparation pins, and opaque label byte hashes. Never decoded development nutrient labels, inspected research/validation images, read credentials/key fragments, opened historical predictions/raw logs, ran actual P/O, or used API/network/downloads.

Verified 843 unique blind rows: ASA 529 = 99 core + 200 legal extras + 230 broader-frame; N5 314 = 84 core + 230 explicitly reused historical support. ASA has 43 association groups and fold row counts 98/70/82/72/207; N5 has 293 fold units and counts 62/61/62/66/63. Every group stays in one fold; both datasets cover all five folds. All fallback/calibration train and heldout memberships match the manifest exactly and have disjoint groups. All seven common role digests match actual files, including digest-only opaque labels. All 48 preparation source pins and five receipt bindings match the copied source proof; current preparation source files remain unchanged. Nutrient median values were not independently recomputed because doing so would require prohibited semantic labels; their numerical correctness remains covered by the earlier preparation review and synthetic tests.

Source/exposure completeness remains explicitly false; this preparation does not claim complete global association closure. Acceptance proposals have real shortfalls: N5 102 retained / 0 new / 92 groups; ASA 75 retained / 0 new / 22 groups. These are pending proposals, not completed 200/78 allocations, designations, downloads or acceptance evidence. No independent validation targets were opened and no new downloads/API calls occurred. These declared shortfalls do not block the separately authorized development population. Future acceptance boundary confirmation and actual Mac validation remain separate pending work.

Authenticated preparation receipts:

- ID-free completion evidence: `f3a19332aa173e82cb6fd6f15179b781d26976e78172757738321012bb979673`.
- common: `93e3960780a4286db18e7ab7a906cb98fb99284c5a38636bda26e980ab587167`.
- blind manifest: `23460f3958e2e53f23cb697e3d3bab08dbe03cc63104a270e35bf9fabf013c7f`.
- copied source closure: `3532f6689a8ee89cf6fcc7eab66e52e5568333dc189cea2fae7923bbeb5d383c` (8,165,375 bytes).
- pending producer cohort freeze: `402523eec6ff9ef412cd9e2b78fad1fedb47b1d4a2043b169887cec94c409847`.

## Verification and scope

Independently ran `unshare -Urn .venv/bin/python -B -m unittest discover -s optimization_sol_20261102/mae_v2/round11 -p 'test_*p.py'`: **167 tests passed in 22.125 s**, plus the two isolated negative fixtures above and an import-only source-inventory audit. Coordinator separately reports all 512 distinct round11 tests passed in 57.998 s; that broader count is coordinator evidence, not this reviewer's independently rerun count.

The pass covered coherent O/Q/D/Q+D algebra and stable item joins, exact paired native/repaired physical masses, explicit failure/fallback populations, strict one-repair parsing, shared conditional legal-option adapter after complete blind coding, fresh-P-only embedding policy, exact request/model/image/cache/matrix replay and three completion seals, durable reservations and transport/auth stop, redaction/routing, Linux separate clean-environment network-isolated child, fixed production roots/arguments, private write-once/resume artifacts, opaque main-process label hashing, training-fold-only OOF and fallback recomputation, bounded half-shrunk L1 fitting, no-lost-pass calibration, coherent MAE-first selection, separate 15%/five-group and original 18% guards, full five-target caps/per-unit definitions, grouped bootstrap, strata, and postscore selected-method fit. Apart from the numbered findings, no additional actionable defect was found in this pass. Synthetic tests establish those exercised contracts, not real provider access, actual full-cohort scientific replay, accuracy, independent acceptance, or Mac portability.

## Reviewed implementation content inventory

Canonical SHA-256 of the sorted repository-relative-to-MAE-v2 path-to-digest JSON map (UTF-8, sorted keys, compact separators): `154d25b04ce4763af7be94c3e7e0231fe9c07da009830d056240a8d34c80df7f`.

| Source | SHA-256 |
|---|---|
| `round10/source_portions.py` | `c156a5e3e354422c28d7bb3beced3f59b6c18394595e7bc87e691364ab7df922` |
| `round11/adapter_p.py` | `fae185bb15a23ebf590e1213d3d191bba31c14f07c1636fdfc3750aaed21fbda` |
| `round11/assets_p.py` | `39b6e447e39ed5131505b7df94357e65f5936df844b5ab90e20be13bf97dba9b` |
| `round11/context_p.py` | `60b484117ccbb0711f26674cf2dae4715edb056d9ca6d5aad2a7e49efe145929` |
| `round11/engine_p.py` | `16121a85ac54286e498fd893ac546bdf5083770255c08f356e48c62bd1fa7108` |
| `round11/freeze_p.py` | `d8b196ee7f1f42001f41b490bced4fc8fa4f06ce7cda24d0de708331b83bd681` |
| `round11/gate_p.py` | `e86a6db3ca5e563afe71fabd94549d81747bca4929e49ac8369ae36a52074816` |
| `round11/identity_gate_p.py` | `a2e37f403543feddbe7f99f3d56dc78281012aec531765aee7049fed8ccb2bc6` |
| `round11/paired_accounting.py` | `a903303ca426f2f988fd02e1d96790ed0a3b5958c0cb36c21fd1da6c509a5245` |
| `round11/paired_failure.py` | `b0effb6e3b12a361d26c5e64724391d65072f6e8ba661c392eec874461a86a07` |
| `round11/paired_stage_pipeline.py` | `b50d1099c12cc82849574bead873e14de2f5a66757611d56aa2639569e610dce` |
| `round11/postscore_p.py` | `0070efd13ce963c4456bc51e74ce7dc1b6889a32b3e229eaf43d216ad340d888` |
| `round11/records_p.py` | `8241409314e8b331cbfe803e41d8f10ea880810813252f5c0a3bba0b313ba362` |
| `round11/run_p.py` | `ca10c1fe510cb335890cec03b47a30649201d505066358ef5b74d6950675a2d6` |
| `round11/runtime_p.py` | `63d205fd91d2861602683a7ea27dd483fdfece652fbf89243c73c9b0f94509d7` |
| `round11/scoring_p.py` | `cb56ebc631feb3a75ff7c143dba87566fb71efc62f739a681445105b222fedd7` |
| `round11/service_p.py` | `da499da9ffd7e93ceadc2d422804f9c0207456c41ed82e704e72010bb8abc69c` |
| `round11/stores_p.py` | `e225485d06e714f50007bafe0da6d593e9e141ab938df2e28ce1d55ad39e8fc6` |
| `round11/verified_identity.py` | `9743a718e82383a7a2ade10dd1402b1520c1a848aae3d0bc7b53e252bfe83580` |
| `round4/src/artifacts.py` | `c80f55cfeeeca87d670f0e517e540c07a1206dd7fd2e902f3e2d403c6254653c` |
| `round7/src/context_m.py` | `825a56935c0ebf632bcce50e7645e50d48f825db673b8bde20c3d6b8948d133f` |
| `round7/src/historical_m.py` | `0c958b00160c0b7074bf20ffadac372d20176a252dcf9ec06299a340c3ee828a` |
| `round7/src/runtime_m.py` | `a58dbc00f964431dabb5910b68a0cc08ae71fe9b5aa959a976897dd999ada3df` |
| `round8/src/uncertain_portions.py` | `357cfa94ed2899940d23c041f7a3d4f8abc5ecf86cb4c3a640150bc262074ffe` |
| `src/metrics_v2.py` | `b97451f19d994e39705136c2759ea91551c955887a46ca58b0775c899474edfc` |
| `src/opt_metrics.py` | `15d71fd2c2379f7f723707cddfeb2e2868c0dd84b027edd12ef9185303a1e63e` |
| `src/opt_pipeline.py` | `940bcb7622c832820866406705fc7e9bc90d7e1bfce83ad33a7aa7d0db08f778` |
| `src/opt_provider.py` | `139917a2d6fc971a0461503fee75cec08534a2654ac5559ccedd9d0c11501367` |
| `src/pipeline_v2.py` | `d061ee894f2a5decf2d755db6ecf270709a010d419a1bbff07057da00ab4e1ce` |

## Coordinator disposition — R-P-1 fixed

`round11/verified_identity.py` is now mandatory in context REQUIRED, freezer
EXTRA and the postscore source inventory. Historical preparation pins and its
immutable843-row outputs are unchanged. New regressions reject a missing pin,
live implementation drift, and disagreement between the science and scoring
gate inventories; the freezer regression exercises its actual default source
union. The coordinator's complete network-isolated suite passed517 distinct
tests in56.354seconds, including all three new R-P-1 regressions. This is fix
confirmation, not a second formal review. R-P-1 is **fixed**; R-P-2 is recorded
separately before any runtime approval is issued.

## Coordinator disposition — R-P-2 fixed

D and Q+D now separately report density-selected primary recognition with
all-ASA denominators, first-code counts/rates, available/unavailable counts and
failure reasons, size/stratum breakdowns and a private code-identity audit.
Original-primary recognition, common final-code membership, shared Exact rows,
physical grams, MAE, calibration and method-selection guards remain unchanged.
Synthetic disagreement and unavailable-density cases confirm that a failed D
choice stays in the denominator without erasing the original recognition report.
All eleven scorer tests, including the two new regressions, are included in the
coordinator's517-test complete offline pass above. This is fix confirmation,
not a second formal review or real scientific replay.

R-P-2 is **fixed; unresolved P1/P2 = 0**. The separately source-bound runtime and
postscore receipts may now be registered, followed by offline science freezing
and the already authorized development batch. No scientific pass, independent
acceptance population approval or Mac hardware acceptance is implied.
