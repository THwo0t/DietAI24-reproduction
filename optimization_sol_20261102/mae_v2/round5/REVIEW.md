# K independent offline review

## Ready for review

Scope: R5-K1 through R5-K5, fixed protocol, pure prefix/support selection,
component estimator, runtime/runner and independent complete-population scorer.
Commits start at 056577d; the score/checklist submission completes the range.
The existing 108 synthetic tests passed together with networking disabled;
the new scorer has 17 passing synthetic tests. A real offline preflight is
running in a separate network namespace, without Provider construction.
No K inference, K scoring or validation access has occurred.

Review label isolation, identity/recipe boundaries, mass conservation,
ordered image payloads, durable budgets, service failure propagation,
complete-population scoring, strict selection and secret exposure.
The review agent modifies only this file and invokes no paid API.

## Independent review — 2026-11-03

Reviewed `056577d^..945b5a2` once, restricted to the new K files and the K
checklist entries. The reviewed source/test files still matched `945b5a2` at
the end of inspection. No frozen earlier scientific source was edited. This
review ran synthetic offline tests only; it did not run real K inference,
scoring, a parent preflight, downloads or API calls, and did not open development
reference labels or validation inputs. The separately running real preflight is
outside this review's execution evidence.

**Decision: changes requested.** One P2 finding must be fixed before K6. K1,
K2, K3 and K5 are approved within their submitted scope; K4 requires the
service-provenance fix below. Approval of the scorer's local logic does not
waive its dependency on a trustworthy completed-K verifier. After the fix,
perform offline confirmation and source freeze; this is not a request for a
second review.

### Per-item decisions and evidence

Paths in this section are relative to `optimization_sol_20261102/mae_v2/`
unless explicitly qualified. `paper.txt` means the paper path in the root
`CHECKLIST.md:31`.

| Item | Decision | Evidence |
|---|---|---|
| R5-K1 | approved | `round5/K_PROTOCOL.md:23-37,119-144` registers the independent training inputs, label boundary, new namespace, fixed service settings, all-84 scoring, ten-ratio Nutrition5k selection and unchanged joint gate. `round5/src/score_component.py:163-209` implements strict full-precision lexicographic comparison and cap-regression rejection. `src/opt_metrics.py:24-28,139-158,277-307` retains the registered caps, reference-mean normalization and 20-check joint acceptance. Paper basis: `paper.txt:309-350`, especially the normalization notes at 324 and 348. K is a new registered development method, with its Sol/native-image/training-comparison departures explicit; it is not the paper's original zero-shot procedure (`paper.txt:303-306`). |
| R5-K2 | approved | `round5/src/run_component.py:56-95` first verifies the pinned complete J continuation, training context and gallery; `round5/src/verified_j_prefix.py:151-194,205-225` projects upstream fields and provenance without J estimate/prediction/labels/folds. `round5/src/component_supports.py:125-174` expands ID/byte/RGB exclusions to association groups, applies the registered ranking, limits selected groups to eight, and preserves the supplied J fill order. The production adapter passes only the four largest groups (`round5/src/run_component.py:169-178`). Protocol basis: `round5/K_PROTOCOL.md:23-37,57-77`; root `CHECKLIST.md:9-10`. The existing training-only release verifier remains the independent-training authority; this review did not reopen its private inputs. |
| R5-K3 | approved | `round5/src/component_estimator.py:160-231` enforces the group/box contract, stable area ordering and clipped native-aspect RGB crops. `242-315` checks every parent, globally unique leaves, finite positive masses, catalog/null-density rules and the two mass-conservation constraints, then computes predictions only from leaf contributions. `336-393` allows one structural repair, reparses cached raw replies and propagates provider exceptions. `396-452` whitelists model-visible fields and sends query/crops/supports in the registered order; file metadata is removed by `src/opt_pipeline.py:99-114`. The composite/hidden-oil/whole-support-recipe boundaries are explicit in the prompts (`component_estimator.py:43-46,49-76`); visual correctness remains an empirical question, not something schema validation proves. Protocol basis: `round5/K_PROTOCOL.md:39-115,128-132`; the programmatic density-times-mass and item-sum principle follows `paper.txt:151-176`. |
| R5-K4 | changes requested | Fresh requests have the required ordered image scope, distinct namespace, timeout and no-embedding guard (`round5/src/component_runtime.py:18-26,48-102`); the inherited HTTP adapter enforces three persistent reservations and propagates authentication/model/service stops (`src/opt_provider.py:163-242`). Structural terminal failures use the fixed external-training vector (`round5/src/run_component.py:153-167,197-210`), and no row is dropped. However, completed K verification does not validate the K response caches/counters/logs against its request references: **R5-K4-1 below**. Protocol basis: `round5/K_PROTOCOL.md:35-37,119-132`; root `CHECKLIST.md:11`. |
| R5-K5 | approved | `round5/src/score_component.py:77-141,212-244` requires complete zero-Provider K verification before constructing its reader, checks external seals/source/training bindings, pins unmodified raw J and preserved ASA, and only then reads the pinned development labels. `round4/src/score_dev.py:91-142` requires exactly 84 N5 and 99 ASA records with manifest metadata; `_summary` at 145-163 retains fallbacks in the primary population. `score_component.py:163-209` rejects missing/altered checks, ties, ASA changes and formerly passing-cap regressions. `245-251` verifies repeated scoring without writes. Protocol basis: `round5/K_PROTOCOL.md:128-144`; paper MAE/normalization basis: `paper.txt:181-184,324-350`. No calibration, target splicing or validation reader is added. |

### R5-K4-1 — P2 — Verify K service provenance during resume and completed replay

**Evidence:** `round5/src/run_component.py:124-132` checks the reference shape,
response count and `value_hash`, but never reads the successful response cache,
request ledger or service log named by `request_hash`. `base()` at 214-247 seals
and replays the ArtifactStore records without a separate K service-provenance
stage. The trace captures the exact ordered images and request digest on fresh
calls (`round5/src/component_runtime.py:71-99`), but that alone does not audit
the external K cache/counter evidence when a cached stage is replayed. This is
weaker than the reused J verifier's cache checks
(`round4/continuation/runner.py:62-100`) and completion-provenance binding
(211-219,249-260).

**Reproduced negative path:** In a `/tmp` synthetic context, run the actual K
`base()`/`infer_one()`/ArtifactStore/BoundTrace/ComponentProvider chain using
`httpx.MockTransport` and the synthetic fixture from
`round5/tests/test_run_component.py:135-171`. Two valid replies create a complete
K seal, two successful chat caches and two attempt ledgers. Without changing
any sealed K stage or record, change one corresponding successful-cache
`model` to `wrong-model` and its attempt ledger's `attempts` to `4`. Calling
`base(verify_only=True, workers=1)` still returns:

```json
{"replay":"base_verified","same_records":true,"provider_constructed_on_replay":false,"mock_transmissions":2,"real_api_calls":0}
```

This does not show that a fourth transmission occurred or that the model was
wrong on the original request. It shows that the advertised completed-K
verification accepts missing consistency between its sealed receipts and the
service evidence, including a counter state outside the registered bound. A
scorer using this verifier would also pass its pre-label service-integrity gate.

**Required change:** Add a K-only, read-only service-evidence verifier and bind
its completion provenance independently into the K run. For every request
reference, require a matching cache request hash, fixed served model, exact
value/value hash and K namespace/payload provenance; validate the associated
persistent counter and successful transmission evidence, accounting explicitly
for cache reuse and interrupted reserved attempts. Reject missing, changed,
wrong-route/model and over-budget evidence before accepting replay or allowing
scoring. Also audit existing K service state before a resumed uncached request
can spend another attempt. Keep completed replay free of Provider construction,
credential reads, new requests and writes. Do this in new K adapters without
editing frozen earlier scientific sources or resetting any existing state.

**Offline confirmation expected:** Preserve the positive interrupted-resume and
completed zero-Provider/read-only tests. Add negative cases for cache removal,
changed cache model/value/request hash, ledger removal/change/over-budget state,
and altered service logs; the corresponding verifier must fail before the
scorer opens labels. Include a fresh-versus-cache-reused case so no false
transmission claim is inferred from `cache_present_before` alone.

Protocol basis: `round5/K_PROTOCOL.md:35-37` requires independent K response
namespace, counters and complete seal; `119-126` fixes model and durable
three-transmission budgets and forbids disguising service faults as successful
fallbacks. Root `CHECKLIST.md:11` requires request accounting. This is a
provenance/verification defect, not a measured MAE failure.

### Offline validation performed

- `unshare -rn ../../.venv/bin/python -B -m unittest discover -s round5/tests`:
  **125 tests passed**, 40.385 s. This includes the submitted 108 pre-scorer
  synthetic tests and 17 scorer tests; all fixtures are synthetic.
- Independent MockTransport negative checks, with provider storage redirected
  to `/tmp`: the same failed payload across two Provider lifetimes reserved and
  transmitted **three** times total, with the second lifetime stopped before a
  fourth transmission. Authentication and reported-model mismatch each stopped
  at one transmission and propagated through the actual estimator/BoundTrace;
  neither became a structural fallback. A scan of the resulting synthetic
  JSON/JSONL files found no synthetic credential values.
- The independently constructed completed-run mutation case above reproduced
  **R5-K4-1**. It used no real images, labels, credentials, API or research output.
- A parallel read-only subreview checked the prefix/support implementation and
  its 32 synthetic tests with sockets disabled; it found no additional required
  change in that scope. The final decisions above are the reviewer's synthesis.

No P1 issue or confirmed credential/filename/image-metadata leakage was found
in the reviewed K paths. These results establish offline contract behavior,
not K accuracy, real-service capability, completed development execution or
validation acceptance.


## R5-K4-1 resolution — fixed with offline confirmation

The implementation adds K-only `service_evidence.py` and its synthetic tests.
Startup audits K counters/logs/caches before creating a client; each new
reservation audits its own payload, and cached-stage validation checks the exact
returned value against its cache, namespace counter and successful service row.
Target-scoped checks preserve the two-worker request window. After every worker
has joined, `service:completion_provenance` separately seals cache/counter byte
hashes, the full service-log hash, stage refs and reserved/logged/unlogged counts.
Completed replay recomputes and compares that proof without constructing a
Provider, reading credentials or mutating files. Existing scientific prompts,
selection rules and the frozen 35+7 sources are unchanged.

Offline confirmation on 2026-11-03: all 154 round-five synthetic tests passed
with networking disabled (33.855 s). The actual ComponentProvider/MockTransport
two-stage integration seals a K run, verifies identical records and file bytes/
mtimes with zero new calls, then independently deletes or corrupts caches,
counters and logs. Each corruption rejects base replay and reaches neither a
scoring reader nor labels. Positive restart retains an unlogged reservation and
uses attempt two; three consumed reservations reject the next Provider before
HTTP. Twenty-five service-evidence tests cover route/model/value/hash/counter/
log tampering, cache reuse, crash gaps, exhausted requests, concurrent target
isolation, path safety and the read-only boundary. No real API or research
labels were used by these tests.

The earlier real preflight remains an immutable as-of receipt for the submitted
source. New-source preflight and final source freeze are required before K6.
The independent review is not repeated, as required by the repository workflow.
