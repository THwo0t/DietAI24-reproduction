# P admission ledger: first bounded independent review

Reviewed commit: `d265ded`. Scope: `round11/service_p.py` and
`round11/test_service_p.py`, with frozen `round10/service_o.py` and
`round10/test_service_o.py` as source-only controls. Decision: **approved for
this offline component**. No P1, P2 or P3 findings identified. This is not an
integrated runner/gate freeze or paid-run authorization.

The review read AGENTS.md, DESIGN.md, PAIRED_FAILURE_DESIGN.md and
PAIRED_ASA_ADAPTER_DESIGN.md. The relevant requirements are the exact shared
image/model/parameter and provenance contract (DESIGN.md:66-80), persistent
service failures and no prediction-based retry (DESIGN.md:119-120), authenticated
structural repair (PAIRED_FAILURE_DESIGN.md:22-28), and the isolated shared ASA
adapter (PAIRED_ASA_ADAPTER_DESIGN.md:14-29).

Evidence:

- `service_p.py:25-87,124-149`: P namespace, six chat stage names with ordinals
  zero/one, forty embedding stages with ordinal zero, exact seven-field blind
  rows, unique sample IDs, dataset/fold/path/hash validation, and population cap.
  Nutrition5k has no conditional slots. Exact slot fingerprint, transport cap
  and six parser-source pins are required by the constructor.
- `service_p.py:90-121,219-253`: model/parameters/role and image binding remain
  fixed; P chat hashes differ from O while official embedding hashes retain
  `official-query-v1`. Repair binding rechecks the actual cached raw response
  against the gate's parser error, including forged stored proofs; the original
  request and exact appended repair exchange cannot change.
- `service_p.py:174-215,255-268,288-358,360-383`: durable reservations consume
  attempts without refund; success and fatal state prevent another reservation;
  outcome anchors and cache linkage prevent answer substitution; interrupted
  persisted successes can be recovered without a new request. Parser failures
  require the frozen parser identity and actual initial response.
- `service_p.py:273-286,385-411`: embedding imports record exact payload,
  manifest, vector hash and explicit legacy/M/O origin; import provenance audit
  is delegated to the future frozen gate. Bound/import conflicts and orphan
  outcomes/caches are rejected by audit.
- `service_p.py:153-159`: production gate loading fails closed when `gate_p`
  is absent. Tests inject only an exact synthetic task allowlist; this injection
  does not establish production prompt, cohort, import or fold authenticity.
  There is no provider, credentials or HTTP-client construction in this module.

Validation, all within `unshare -Urn`, using the absolute repository
`.venv/bin/python -B`: all 18 synthetic tests passed. Additional synthetic
probes created a 2,000-row mixed-dataset universe (102,000 slots and exact
306,000 transmission cap), confirmed absent production gate rejection, and
confirmed the fourth unknown-outcome reservation is denied after restart
without changing admission bytes. No real datasets, runtime artifacts,
provider logs, credentials, HTTP or paid APIs were opened or used.

Limits: the ledger validates stored transport outcomes; the future runtime must
classify and durably persist wrong-model/provider failures as fatal before
stopping, as the old source-only runtime does. The future gate must authenticate
the frozen slot universe, task payloads, parser implementations and import
provenance; the future runner must establish coding seals, fallback lineage and
full-population completion. Their absence is explicitly declared by this
component and was not treated as a component defect. No code edits, staging,
commits or follow-up review were performed.

## Root disposition

Approved for the source-only P ledger component with no findings. Root
confirmed the then-complete307 distinct offline unittest IDs. Future engine,
Trace, gate, context, adapter and full-run freeze remain outside this approval.
No P provider, credential or paid request was constructed.
