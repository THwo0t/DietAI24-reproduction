# P-C2 bounded lineage component review

## Pending scope received

Review snapshot `5b3cb93a4f4f11f5f987dd5969ce6f19d6603065` once, offline, restricted to
`cohort_lineage_v3.py`, `development_identity.py` and their two synthetic test
files. Read AGENTS.md, DESIGN.md, COHORT_REPAIR_DESIGN.md, both relevant
CHECKLIST.md files, and source primitives as constraints. No actual research
artifacts, census, private output, labels, photos, providers or network APIs
are in scope. Root remains the only implementation writer.

Root clarification: root serialized integration and commits; new disjoint pure
implementation files were delegated to explicit Sol subagents. This reviewer
received independent source context and did not join implementation work.

## Final review — approved within this component scope

Reviewed commit: `5b3cb93a4f4f11f5f987dd5969ce6f19d6603065`.
Findings: **0 P1, 0 P2, 0 P3**. No changes requested.

Evidence:

- `cohort_lineage_v3.py:48-109` reconstructs supplied raw/screening closure,
  checks registered core/original-development/training/legacy-reserved counts,
  and blocks every old role, historical exclusion, ambiguity and exposed recipe.
  Legacy reservation is explicit; no empty validation role is passed to the old
  pool. The original `n5_identity.reconcile` remains unchanged and its refusing
  guard is exercised by inherited tests.
- `cohort_lineage_v3.py:24-43,97-104` retains original identity rows and the
  sealed label hash, checks image hashes against supplied dish fingerprints and
  original group bindings, and rejects extra label fields. Authenticating these
  supplied inputs remains the caller's obligation, as explicitly documented.
- `cohort_lineage_v3.py:112-131` uses full screening associations for core folds,
  pools ambiguous core components into one uncertainty unit, records old fold
  bridges and refuses fewer than five units without changing original rows.
- `cohort_lineage_v3.py:134-153` preserves the existing group/dish hash ordering
  contract from `n5_pool.choose_new_dishes`, proposes 216 then 200 distinct
  component representatives, reports shortfalls and leaves acceptance boundary
  confirmation and all action permissions pending.
- `development_identity.py:25-92` reads only the fixed seal and development
  manifest through the bounded source reader. It authenticates 183 seven-field
  identity rows split 99/84, image path/hash bindings and the recorded label
  hash. It never opens images or labels. Fresh revalidation remains explicit.

Validation performed in the round11 directory, with network disabled:

```
unshare -Urn /home/lelouch/Data/Projects/DietAI24_original/.venv/bin/python -B -m unittest -v test_cohort_lineage_v3 test_development_identity
```

Result: 29 executions pass, including 6 imported original-guard tests executed
again through LineageTests (23 unique test implementations). Negative paths
cover changed identity/index/pixel bindings, omitted core rows, label payloads,
old validation bridges, insufficient fold units, symlinks, malformed/duplicate
JSON, nonfinite fields, special/oversized files, seal/manifest drift and attempted
public path overrides. Poison image/label symlinks remain unopened.

An additional ephemeral synthetic-only network-isolated probe confirmed the
production default 216+200 counts with 420 independent supplied components,
permutation stability, disjoint selections, and rejection of an empty legacy
reservation with `registered_identity_population_changed`.

Limitations, not findings: these are pure provisional helpers plus an identity
reader, not a full cohort preparer. Full latest exposure/source authentication,
availability/complete-label eligibility, expanded-row fold integration, final
fingerprints/freeze, ASA closure, download gating and paid-run review remain
pending. Supplied safe-candidate status is a caller precondition. This review
neither confirms completeness/isolation nor authorizes sampling, downloads,
acceptance designation, fitting or inference. No paper estimator or metric is
changed by these modules; their applicable protocol is the prospectively
registered identity/fold repair. No actual data or paid call was used.

## Root disposition

Approved within the reviewed component scope, with no fixes required. Root
confirmed the complete then-current offline suite: 181 distinct unittest IDs
passed (including inherited historical tests; this is not 181 new checks).
The later local metadata size projection passes its five scoped tests.
No production cohort action, eligibility, download or inference follows from
this component approval; the full source and runner gates remain pending.
