# Round 7 independent implementation review

## Pending R7-G review

Scope: common M0/M protocol and source through `aaf4858`; source ranges
`e3d6731..aaf4858` plus the existing R7-B core commit `16c1abb`.
Read `PROTOCOL_DRAFT.md`, `CHECKLIST.md`, the paper methods and scoped diffs.
Do not use original formal test labels or frozen validation to assess accuracy.

Evidence before review:36 network-disabled synthetic tests pass, including
end-to-end two-dataset/two-arm persistence and completed replay with Provider/
credential readers forbidden and file hashes/mtimes unchanged. The unchanged
historical ComponentPipeline suite previously passed32 tests. A real read-only
raw-C replay verified all84 images, exact chat payloads,530 exact embedding
texts,384 ordered banks, raw parsing and full nutrient aggregation. Separate
private prepared artifacts contain other-fold medians and an explicit3159-entry
old official embedding inventory.69 of the original530 queries lack a historical
persistent counter; their old provider/cache/success-log source is disclosed.

No M real-provider preflight, paid request, development accuracy or validation
result exists yet. Final source/data/protocol freeze is blocked until independent
review, required fixes and a matching review gate. Review only once; implementation
fixes are subsequently checked offline without a second formal review.

Pay special attention to exact historical source bridges, imported versus new
dual-role evidence, durable per-payload budgets, concurrency and zero-client
completed replay; isolation of query labels from model requests; fixed coding
before portion; all-Exact ASA option fallback and full-population N5 scoring;
same-profile selection,<=2/10 per dataset and strict20/20 reporting.

## R7-G independent implementation review — 2026-11-03

Reviewed once: `e3d6731..5c562ab`, including shared core `16c1abb`, historical
prediction-only isolation `7bd7e1f`, all round7 source/tests/protocol and relevant
inherited pipeline/provider/scorer/artifact code. Reviewer changed only this file.
No API, credential file, development label file or validation artifact was opened;
no preparation, freeze, inference or score command was run.

| Item | Decision | Evidence |
|---|---|---|
| R7-A | approved | PROJECT_REVIEW.md and PROTOCOL_DRAFT.md distinguish same-method dual-dataset evidence, conditional ASA and full-serving N5, historical diagnostics and development selection; paper.txt:173–185,196–218 support the registered task distinctions. The 7bd7e1f diagnostic uses explicit prediction-only CSV columns and AST-extracted pure parsers, not model-selection inputs. |
| R7-B | approved | shared_accounting.py:22–274 enforces single-text RRF60, branch membership, exclusive ownership, distinct whole entities, bound banks and new total-ratio quantity; paper.txt:173–189 supplies recognition-before-portion and catalog nutrient arithmetic. Synthetic negative contracts pass. |
| R7-C | approved | historical_m.py:201–294 binds reviewed source drift, run configurations/seals, real image hashes, exact chat requests/counters and embedding queries, reparses and recomputes raw C. Verified all 3159 explicit imported vectors and pinned sources; the 530 raw-C exact query texts include exactly 69 with historical_counter_available=false. Protocol historical limitation is explicit, without invented modern receipts. |
| R7-D | changes requested | Independent role paths, exact request hashes, durable reservations, three-attempt exhaustion, source imports and payload-order replay pass; new response provenance still needs R7-G-1. |
| R7-E | approved | records_m.py:14–43 and scoring_m.py:8–70 preserve pre-portion coding, all-Exact legal median-option fallback, full-serving records, one whole profile and separate <=2/10 guards. Failed portions do not remove Exact rows. Paper.txt:175–185,201–218 and PROTOCOL_DRAFT.md coding/metrics sections support these contracts. |
| R7-F | changes requested | Both-arm persistence and completed zero-Provider/no-write replay pass; response provenance needs R7-G-1 before paid execution. The inherited historical review pins cohorts_v2.py indirectly, so it is not an omitted freeze dependency. |

### R7-G-1 — P2 — Bind each new success log to the returned response value

Locations: `src/runtime_m.py:146–148`, `src/service_m.py:73–83` (paths relative
to round7). A successful service log records status/model/usage, but no digest
of the exact sanitized value written to its response cache. The validator checks
only the cache's self-reported value_hash and existence of a success event. Thus,
if a success cache changes before its scientific stage is durably sealed (for
example, interrupted stage publication followed by a cache rewrite), its new
contents can be treated as the original provider answer and used to produce a
new scientific result. Payload/counter provenance alone does not establish which
answer was returned.

Independent network-disabled negative probe: create one genuine synthetic
MockTransport success in each role, edit only the response-cache `value` and recompute
its own `value_hash`, leave the successful request log/counter unchanged;
`audit_target(...)["value"]` returns the changed answer without error for both
chat text and a changed valid 3072-dimensional embedding. This is
not a claim that unchanged completed stage seals can be bypassed: their saved
refs/reparse provide additional protection. It is the unsealed/resume cache
path that lacks an independent answer binding.

Required: record the sanitized returned value digest in every **new M** success
log, require cache/log/ref digest agreement during audit/replay, and add the
same negative probe for both roles. Do not retrofit or invent old historical
receipts. Basis: PROTOCOL_DRAFT.md:179–184 explicitly rejects value-only cache
validation as a provenance bypass and requires durable replay evidence.

### Freeze closure cross-check

`context_m.py:104–112` does not directly enumerate cohorts_v2.py, but this is
**not a finding**: `runtime_context()` calls `verify_imported_c()`, whose
historical review/source verification (`historical_m.py:168–172`) pins the full
nine-source review map including cohorts_v2.py. The fixed REVIEW_SHA binds that
map. A changed loader is therefore rejected before `load_dev()` is called by
the scorer. No redundant direct pin is required to establish this constraint.
`score_completed()` does not recheck sources after scoring, but no supported
single-writer path mutates them during the pure scorer; this alone is not a
must-fix issue.

### Independent validation and gate

`unshare -rn .venv/bin/python -B -m unittest discover -s
optimization_sol_20261102/mae_v2/round7/tests`: **36 tests passed** (0.801s).
This includes wrong model/vector, unknown inherited embedding state, orphan
cache, missing counter, exhausted/reconstructed budget, unlogged reservations,
redaction, payload-order mismatch, all-Exact option fallback, undefined metrics,
per-dataset exceptions, same-profile tie, paired execution and immutable completed
replay. Additional isolated temporary negative probe reproduced R7-G-1.
Read-only source audit independently verified raw-C seals/records/source bridge
and all 3159 imported embedding values/sources. A separate network-disabled
`import_raw_c()` invocation independently reconstructed all 84 real image
requests, original raw parsers, ordered retrieval banks and nutrient aggregation;
the full returned bundle exactly equals prepared/raw_c.json. It wrote no file
and made no new requests.

Gate: **changes requested; 0 P1, 1 P2**. Resolve R7-G-1 in an isolated
commit citing this ID, record offline negative-path confirmation, then freeze.
No second formal review is requested. These checks establish implementation and
provenance contracts, not M accuracy, live service availability or validation
acceptance.

## Implementation disposition — R7-G-1 fixed

The implementation records `value_hash` of the sanitized successful return in
every new M service log before durable cache publication. `audit_target()` now
requires that log digest to equal the validated cache-value digest; saved stage
refs additionally require the same value digest. Historical logs are unchanged.

Offline confirmation:38 network-disabled synthetic tests pass, including the
reviewer's exact negative cases for chat and a different valid3072-vector:
edit only cache value plus its self-checksum, leave counter/success log intact,
and both audits now reject with `M_success_log_return_value_changed`.
Two-dataset paired execution and completed no-Provider/no-credential/no-write
replay still pass. R7-D/F are fixed; no unresolved P1/P2 remains. The review was
performed once; this disposition is implementation-side offline confirmation,
not a second formal review or an accuracy/validation claim.
