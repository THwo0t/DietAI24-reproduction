# MAE v2 implementation checklist

Approved by the user on 2026-11-02. All changes and new artifacts stay in this
directory. v1 remains historical evidence. English commit messages begin with
the item or review finding ID. No paid validation until the development gate
and independent checkpoint-one review pass.

| Item | Deliverable | Status |
|---|---|---|
| M2-1 | Register the MAE-first protocol and finite candidate tree | approved or fixed after checkpoint one |
| M2-2 | Isolated linkage audit, exposure closure, v2 cohorts and dev-only verification | fixed after checkpoint one; 58 approved replacement images downloaded and sealed |
| M2-3 | Component accounting, same-RGB crops, A–E inference and contract tests | approved or fixed after checkpoint one |
| M2-4 | 15% coverage, grouped OOF, one mass factor, selection and metric tests | approved or fixed after checkpoint one |
| M2-5 | Persistent provider attempts, stage provenance, resumable experiment CLI | approved or fixed after checkpoint one |
| M2-6 | Run registered development experiments and record complete results | approved; finite tree complete, 10/20 MAE checks pass |
| M2-7 | Independent checkpoint one; fix findings and confirm offline | approved or fixed after checkpoint one |
| M2-8 | Freeze and run one validation batch only if development gates pass | not run: development gate failed; validation stays sealed |
| M2-9 | English MD/PDF/DOCX, gap analysis, Mac handoff and checkpoint two | deferred by user on 2026-11-03: GitHub source backup first, continue MAE optimization, write final report after success |

Checkpoint one covers M2-1–M2-6, protocol compliance, paid request accounting,
label isolation, data linkage, and development decisions. If development fails,
review the failure conclusion; validation stays sealed. Checkpoint two covers
the final results/report/delivery. Each checkpoint receives one independent
review; P1/P2 fixes receive offline confirmation without another review.

Paper basis: DietAI24 Tables 1–2 supply the unchanged MAE reference values;
Methods describes image recognition, FNDDS retrieval and portion estimation.
Nutrition5k documentation establishes incremental scans and motivates linkage
auditing; our 600-second linkage rule is an engineering heuristic, not a
published physical plate identifier.

## Continued optimization requested on 2026-11-03

| Item | Development experiment | Status |
|---|---|---|
| R3-1 | F: independent direct estimates | complete, all 84; N5 0/10 |
| R3-2 | G: four training-fold RGB demonstrations | complete, all 84; N5 0/10 |
| R3-3 | H: training-fold ingredient catalog and masses | complete, all 84; N5 0/10 |
| R3-4 | I: isolated visual-check prompt ablation | complete, all 84; N5 0/10 |
| R3-5 | Fixed HI mean and raw-CHI median | complete offline, all 84 each; N5 0/10 |
| R3-6 | Calibration bounds and semantic-neighbor diagnostics | complete offline; no passing method |
| R4-1 | Independent external training-gallery proposal | authorized and downloaded all 230; training release retains 230 groups/164 ingredient classes, with one explicitly registered official 2 g mass discrepancy |
| R4-2 | Appearance retrieval and visual reranking pipeline | gallery 230 and continuation all 84 complete; raw and calibrated N5 each 0/10; selected raw by registered worst-ratio rule |
| R4-3 | Training-only service probe and isolated complete-population scorer | fixed 13-image probe passed with one request; repeated verification constructs no provider |
| R4-4 | One grouped aggregate calibration candidate | completed all 84 OOF; worst ratio increased from 1.77803 to 1.79571, so not selected; raw and all OOF evidence preserved |
| R4-8 | Explicit service continuation | all 84 base records sealed; 126 successful continuation requests and 2 read timeouts; original artifacts preserved, singleton fourth attempt used exactly once |
| R4-9 | Posthoc mass and density diagnostics | complete offline on all 84; true-weight oracle still fails fat/carbs/protein; 87.45% of omitted exact-ID mass is already in catalog; 18 synthetic tests |
| R5-1 | External-training ingredient-mass prior | protocol committed before data fitting; one fixed linear kernel ridge, no API or parameter search |
| R5-2/3 | Fixed 230-image training OOF and isolated loader | complete; 33 offline tests; 4/5 improvements versus fold medians and mean ratio 0.91315, but 86.10% absent-ID mass; not promoted to a Sol experiment |

`round3/development_checkpoint.json` records the whole-method comparison. The
fixed CHI median improves all five MAEs relative to the original selected v2 C,
but fails the acceptance gate. Original selection and all member records remain
immutable. Continue development; do not open validation or generate final reports.
