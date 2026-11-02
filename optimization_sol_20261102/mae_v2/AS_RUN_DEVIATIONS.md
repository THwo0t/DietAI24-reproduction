# MAE v2 as-run deviations

This ledger records differences between the preregistered protocol and the
completed implementation. It does not amend the original protocol, cohort
freezes, manifests, raw responses, predictions, calibration files or selection.
The executed development experiment remains the source of the reported results;
documenting a deviation does not create a new selection or acceptance result.

## R-M2-2-1 — ASA24 retained archived folds

**Registered rule.** `PROTOCOL.md:52-54` keeps the ASA24 connected groups and
specifies seed `dietai24-mae-v2-20261102`, SHA-256 group ordering and index modulo
five for fold assignment. There is no registered ASA exception. The seed and
five-fold construction are project rules, not a procedure attributed to the
paper. The paper context is the related ASA portion sizes and N5 sampling
(`paper.txt:230-237`) and reproducibility discussion (`paper.txt:298-307`), as
identified by the independent checkpoint-one review.

**Executed rule.** `src/cohorts_v2.py` computes N5 folds with the v2 seed but
copies the archived ASA24 rows, including their original groups and folds.
ASA24 therefore used its established v1 folds; only N5 applied the v2 seed.
The global seed field in the preserved development freeze must not be read as
evidence that both datasets were reassigned. The original preparation evidence
already describes retaining ASA folds (`evidence/M2-2_cohorts.md:19-20`);
that describes execution, not an exception in the preregistration.

The separate offline check in `tools/audit_folds_v2.py` covers both datasets:

| Dataset | Active images / groups | Compared with registered v2 seed | Executed-policy check |
|---|---:|---:|---|
| ASA24 | 99 / 23 | 69 images in 17 groups have different folds | All archived v1 groups and folds retained |
| Nutrition5k | 84 / 78 | 0 images / 0 groups differ | All assignments follow the registered v2 seed |

**Resolution and result boundary.** Preserve the as-run experiment and disclose
this execution deviation. No replacement fold manifest, reselection, paid run
or retrospective protocol edit is made. The new audit compares assignment
metadata and hashes the original protocol, development freeze/manifest,
completion, selection, selected OOF predictions and ASA raw/OOF/calibration
artifacts before and after; it neither reads reference labels/images nor opens
validation. Exact hashes and aggregate fold counts are in the separate
`evidence/R-M2-2-1_fold_audit.json`.

The independent checkpoint-one review reports its own read-only registered-fold
recalculation: fitted fold factors changed (including one to 1.047), while zero
conditional prediction vectors and none of the ten ASA primary metric values
changed. This observation is attributed to `REVIEW.md`, R-M2-2-1; the new
assignment audit does not independently recompute those predictions or metrics.
No protocol-conformant derived score artifact is published by this fix. Any
future such analysis must have separate provenance/hashes and rebuild all
fold-dependent parameters offline, and must remain an explanatory analysis
outside selection and acceptance. The as-run 10/20 failure conclusion and
decision to keep formal validation closed remain unchanged.

**Offline verification.** Run from the repository root with networking disabled:

```bash
timeout 120 unshare -rn .venv/bin/python -B -m unittest discover \
  -s optimization_sol_20261102/mae_v2/tests -p 'test_audit_folds_v2.py' -v
timeout 60 unshare -rn .venv/bin/python -B \
  optimization_sol_20261102/mae_v2/tools/audit_folds_v2.py --write-evidence
```

Seven synthetic tests cover both datasets, separate group/image mismatch
counts, old-ASA and new-N5 policy drift, groups spanning folds, malformed or
non-development rows, missing datasets, manifest/protocol binding, forbidden
reads, immutable evidence and changes to original artifacts during the audit.
Evidence creation is idempotent for identical content and refuses replacement
of different content. The same tool without `--write-evidence` is read-only.

## R-M2-3-1 — B crop ordering corrected prospectively

The executed B implementation added protein, sauce and region-area preferences
to the registered uncertainty/mixed-region ordering. Among 84 saved B layouts,
14 had more than four parents; the registered rule produces 10 different crop
sets and 40 different ordered lists. All 84 saved lists match the old code.
The future implementation now uses exclusive tiers: uncertain, then mixed,
then other regions, with parent ID as the sole within-tier ordering key.

The original B requests, responses, source bindings and scores remain as run.
No corrected-B score or counterfactual winner is claimed. Selected C reuses A
identities with crop review disabled; all 84 C identities equal A and contain
no crops. Its inference path is unaffected. Three new regression tests first
failed under the old implementation (four assertions), then all 32 pipeline
tests passed. Evidence: `evidence/R-M2-3-1.json`.

## R-M2-3-2 — official category omitted from prompt context

The registered candidate context includes the official food category. The
completed A–E selection prompts and D semantic-review prompt instead contain
code, official description, per-100-g nutrient density and inferred relationship
hints. Although all 5,624 catalog entries have a category, that field only feeds
the internal lexical hint function; the official category itself is not sent
as an explicit prompt field. Hints are neither official categories nor recipe
facts.

The resolution is explicit disclosure of this execution deviation, as permitted
by the review. No category field or category-enhanced prompt variant was added.
The selected C contract, saved requests/results, original source bindings and
protocol remain as run; the portable method must carry the same disclosure.
Two offline tests capture both prompt boundaries. Evidence:
`evidence/R-M2-3-2.md`; tests: `tests/test_candidate_context_v2.py`.

## R-M2-4-1 — insufficient-group bootstrap boundary fixed

The original primary bootstrap could report a degenerate interval for a single
association group, contrary to the registered minimum of two. The corrected
implementation returns absent endpoints, zero performed/valid replicates and
`fewer_than_two_groups` for zero or one group, retaining the requested draw
count separately. Point estimates and behavior for two or more groups are
unchanged.

All actual selected development populations have more than one group: ASA24
has 23 and N5 has 78. Offline recalculation using the original and corrected
source reproduced the complete saved metric object, including all actual
10,000-draw intervals, with exact object equality. The original selection,
predictions and freezes were not overwritten. Thirty-five focused metric tests
passed, including the boundary cases for both datasets. Evidence:
`evidence/R-M2-4-1.json`; canonical unchanged metric-object SHA-256:
`932c50272256119bdb9c4eacf16c0a18392612ff1a20de5d6d076ac120021565`.

## R-M2-5-1 — optional partial-response retention deferred

The optional P3 recommendation is to retain sanitized partial response text and
its finish reason separately while continuing to treat non-`stop` completions
as invalid. The completed run contains zero successful responses with a
non-`stop` finish reason; this branch therefore lost no observed response text.
The improvement is deferred for future provider work. No partial-text handling
change, response reconstruction or inference rerun is claimed for this study.
Evidence: the independent request/response accounting in `REVIEW.md`,
R-M2-5-1 and R-M2-5-2.

## Post-selection reference-mass diagnostic

The saved diagnostic on all 84 N5 development images sets total predicted mass
to the reference mass, while retaining predicted codes, component shares and
food-table densities. Weight error becomes numerical zero, but all four
nutrient targets still fail both fixed MAE limits. Their absolute residual MAEs
are 94.959 kcal energy, 8.228 g fat, 13.060 g carbohydrate and 8.614 g protein.
Correcting total mass alone is therefore insufficient for these fixed
predictions. Food-code choice, component shares and food-table or annotation
mismatch are hypotheses requiring separate tests, not established causal
attributions.

This analysis uses reference labels after selection and is not a feasible model,
new candidate, protocol-conformant rerun or acceptance result. It changes neither
the original 10/20 outcome (ASA24 10/10, N5 0/10) nor the closed validation gate.
Source: the aggregate `analysis/diagnostics_v2.json`.
