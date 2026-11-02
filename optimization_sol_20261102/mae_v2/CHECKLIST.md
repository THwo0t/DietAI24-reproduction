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
