# P-B bounded preparation-component review

## Awaiting independent review

Implementation checkpoint:8fbe2fb. Scope: new `n5_identity.py`, `n5_pool.py`,
`n5_sources.py`, `n5_preparation.py`, `asa_identity.py`, `asa_eligibility.py`,
their six test files, CHECKLIST.md and EXPANSION_DRAFT.md. Relevant commits:
13461f0,2bf0d4d,a4df21a,e74eb29,1244aff,8fbe2fb. P-A's already reviewed cache/
strict graph helpers and frozen O source are reference dependencies, outside
this new review. This is not the full actual-data or paid-runtime checkpoint.

Root evidence: all57 unique preparation tests passed in `unshare -Urn` with
bytecode disabled, synthetic temporary sources and MockTransport only. The new
scope includes restricted15-source binding, a complete reader-to-pool fixture,
original variable-width parser and ASA portion-source differential comparison,
poisoned protected targets, full raw/recipe/byte closure and validation bridges.
No actual data/source audit, label analysis, selection, download or API call.

Special attention: source authenticity and fixed-path limits; no recursive
protected-file access through old inventories; role/old-exclusion preservation;
new validation/ambiguity linkage; absent byte coverage never claiming global
independence; original eligibility versus disclosed source-quality extensions;
aggregate/private separation and false readiness claims. A trusted actual
phase runner, latest exposure discovery, ASA source adapter, fixed registration
and post-download closure remain pending. Production must not expose synthetic
anchor/count overrides. Passing this scope cannot authorize those missing parts.

Reviewer must use independent context and explicit gpt-6.1-sol, write only this
file, review the scope once, run only offline synthetic checks, and return
approved or changes requested with P1/P2/P3 evidence/source references. No real
research data, running O output, validation material, credentials or network/API.
Root handles findings in isolated English commits, confirms with offline
negative evidence and continues without a second formal review of this scope.

## Independent P-B review — 2026-11-04

Decision: **changes requested**. Reviewed checkpoint8fbe2fb (current9bd4d51
adds only the awaiting-review record) in independent context using
gpt-6.1-sol. This is the single bounded component review, not a P-C/P-D
integration or actual-data approval. One P2 finding; no P1 or P3 findings.

### R-PB-1 — P2 — detect conflicting exact mappings before dropping zero sentinels

`asa_eligibility.py:46-50` skips a zero FoodWeights value before recording or
checking that exact `(Food Code, Portion Code)` key. A supplied source with
both0 and10 grams for the same key therefore silently retains10, in either
row order, and presents its rows as unambiguous. The same code correctly
refuses10 versus11. A zero-only nonquantitative mapping should remain
ineligible, but it must not erase conflicting source evidence for a key that
also has a positive mapping.

Source requirement: `EXPANSION_DRAFT.md:23-25` requires exact FNDDS mapping
and valid unambiguous weights; `:213-221` claims conflicting-unit checks.
Original `code/asa24_proc.py:44-54` resolves the exact FoodCode/PortionCode
mapping, with only the documented gram98 override, rather than selecting one
of contradictory records. This is a source-quality extension, not a new
paper eligibility rule; paper.txt:214-219 describes predefined FNDDS portion
weights as the reference quantities.

Synthetic reproduction, using only `ASALegalPortionTests.setUp()` and adding
`{'Food Code':t.code,'Portion Code':1,'Portion Weight':0}` to its existing
10-gram mapping: `legal_rows` returns4 rows, selects PortionCode1 and reports
zero ambiguous pairs; reversing the source mapping rows returns4 again.
The existing fixture's gram98 alternative means the source conflict can also
silently influence the dominant portion-code choice. Expected: refuse the
conflicting exact source mapping (or return an explicit source-repair conflict
that the caller must resolve) before eligibility; preserve exclusion of a
zero-only sentinel and acceptance of identical duplicate mappings. Add an
offline regression for zero/positive duplicates in both orders, alongside the
existing positive/positive conflict test.

### Other component conclusions

- `n5_identity.py`: **approved** within its pure supplied-input contract.
  Lines84-100 reproduce the complete original raw/recipe screening partition;
  lines116-140 include all selected-training fingerprints, refuse validation
  bridges and retain unnamed old exclusions. Compared with
  `src/cohorts_v2.py:149-182,210-250` and
  `round4/proposal/audit_pool.py:134-157`. The full candidate audit source is
  consistent with `round4/src/train_data.py:519-525`, including quarantined
  proposals. No claim of latest exposure completeness is approved.
- `n5_pool.py` and `n5_preparation.py`: **approved** for supplied authenticated
  frames. Pool lines37-45 and preparer lines78-87 exclude protected identities
  before target conversion; full graph reconciliation precedes this stage at
  preparer lines94-100. Recipe/available-frame checks preserve the frozen
  input's deduplication, rather than selecting new representatives by labels.
  Original sources: `code/nutrition5k_proc.py:70-75,94-100,138-144` and
  paper.txt:235-237. Fixed-seed group selection remains a helper, not a
  registered real selection or proof of physical-plate independence.
- `n5_sources.py`: **approved** for its fixed, registered historical reader
  contract. Lines68-94 restrict paths, regular files, hashes and revalidation;
  lines114-145 project named identity fields without following protected
  inventory paths. Synthetic anchor/count overrides are documented fixture
  affordances; a future production entry point must not expose them. The
  reader's fixed historical seals do not establish current protected-file
  integrity or latest exposure coverage.
- `asa_identity.py`: **approved** for observed supplied topology. Lines49-63
  retain unknown-image metadata edges; lines79-95 globally withhold complete
  byte closure for any byte gap or unmatched anchor and distinguish external
  completeness. Protected intersections are reported, not silently repaired.
  Actual complete metadata/ZIP source coverage and hard phase guards remain
  pending as explicitly stated in `EXPANSION_DRAFT.md:34-44`.
- `asa_eligibility.py`: **changes requested** for R-PB-1. Otherwise the reviewed
  ordinary valid-input mapping/portion behavior, protected-code numerical
  bypass, exact1% check and disclosed same-byte source-conflict check are
  consistent with the bounded scope and original
  `code/asa24_proc.py:58-83`. Existing-core reference/fold preservation still
  needs a separately reviewed caller.

### Independent verification and limits

Ran `unshare -Urn .venv/bin/python -B -m unittest discover -s
optimization_sol_20261102/mae_v2/round11 -p 'test_*.py'`:57 tests passed in
5.973s. Read all six in-scope synthetic test files; existing P-A tests were
executed as regression checks, without reopening their formal review.
The additional synthetic zero/positive source-conflict probe above reproduced
R-PB-1. No source or test file was edited. No actual research data, protected
validation material, private JSON, archive, image, credential, O output,
network or API was accessed. Only this review file was written.

P1/P2 fixes require isolated English commits citing the review ID and root
offline confirmation, not a second formal review. Neither this review nor
subsequent correction authorizes real source audit, latest exposure discovery,
ASA I/O, real cohort freezing/downloads, predictor registration or paid runs.

## Coordinator response — R-PB-1 fixed

Exact-key consistency is now checked against every finite nonnegative mapping
before zero-only sentinels are removed. Both0→10 and10→0 refuse with the stable
conflicting-mapping error. Identical positive duplicates still produce the
original legal series, identical zero-only mappings remain nonquantitative,
and the documented gram98 alternative is unchanged. Without that alternative,
zero-only mappings produce no legal rows.

Root negative confirmation: the new assertion against2b36454's old source
catches2 failures,0 errors, one for each source order. After correction all58
unique preparation tests pass offline in `unshare -Urn`; the ordinary valid
source still matches original `asa24_proc` mapping/series selection. No actual
datasets, current O outputs, credentials or network were accessed. Status fixed;
one formal review only,0 unresolved P1/P2. This is coordinator offline fix
confirmation, not a second review or actual P-C/P-D readiness approval.
