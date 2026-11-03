# P-C4 ASA role-source and phase-graph component review

Decision: **approved for this component only**. Findings: **0 P1 / 0 P2 / 0 P3**.

Reviewed source snapshot: `12e90c5`, inspected at HEAD
`d265ded6a63c86a372757d983b8586585264a395` on 2026-11-04. The four scoped
files are unchanged between those commits: `asa_role_sources.py`,
`asa_phase_graph.py`, `test_asa_role_sources.py`, `test_asa_phase_graph.py`.
This is their one independent component review, not approval of complete ASA
roles, source/exposure closure, cohort repair, candidate selection or any run.

Read AGENTS.md, the round11 CHECKLIST, ASA_ROLE_AUDIT_DESIGN.md and
COHORT_REPAIR_DESIGN.md; checked identity/path conventions against original
`src/cohorts.py:332-386` and `mae_v2/src/cohorts_v2.py:577-618`.
The governing source contract is ASA_ROLE_AUDIT_DESIGN.md:7-35, rather than a
new paper protocol or numerical-result claim.

The reader enforces the fixed original and sealed identity populations and
preserved sample/group/fold/hash projection while allowing registered renamed
paths (`asa_role_sources.py:35-107`). Exact Decimal normalization and finite
fixed/census historical CSV reads retain unresolved inherited pins explicitly
(`asa_role_sources.py:25-33,109-151`). Five roles remain represented and missing
caller/training/retired registration grants no completeness or action permission
(`asa_role_sources.py:152-169`). Held caller projections must still be
revalidated by the eventual caller as expressly required by the design; their
unfinished registration is not an additional finding in this component scope.

The pure graph preserves original/current bindings, attaches local aliases
through trusted byte identities, retains unmatched local inputs and full
metadata/orphan associations, and delegates v3 byte/RGB closure without treating
the complete source corpus as exposure (`asa_phase_graph.py:17-105`). Missing
original-image verification remains explicit; core-validation intersections,
old-group merges and old-fold bridges are reported separately without changing
folds (`asa_phase_graph.py:106-152`). Private identities remain in the private
graph; the supplied aggregate contains counts, fixed status/reason names and
permission flags.

Validation used only synthetic fixtures in a disabled-network namespace:

```
unshare -Urn /home/lelouch/Data/Projects/DietAI24_original/.venv/bin/python -B -m unittest test_asa_role_sources test_asa_phase_graph
```

Result: **25 tests passed**, run from round11. Four additional in-memory
synthetic checks passed: missing ZIP hash evidence remains unverified and
stopped; absent protected hash anchors are rejected; an alternate source name
with equal bytes does not silently verify the missing original image; a
verified original photo associated to the wrong code is rejected. Existing
negative tests cover mutated seals/sources/manifest bindings, invalid code
serializations and generations, unsafe extra inventory references, incompatible
pixel semantics and local/archive hash conflicts. Test output and this review
contain no research identities.

No actual datasets, private artifacts, census, images, targets, credentials,
network or API were opened. No other files were edited, staged or committed.
The complete source/role reconciler, caller completeness, ASA bridge disposition
and subsequent first full-scope preparation/run review remain pending.

## Root disposition

Approved within the reviewed identity/graph component scope with no fixes
required. Root confirmed the then-complete307 distinct offline unittest IDs.
Actual role loading and complete caller/role dispositions remain pending; no
cohort repair or model permission follows from this component approval.
