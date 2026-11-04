# P continuation and request accounting

These are operating rules for the already frozen P method. They do not amend
its sources, transport retry policy, import policy, task population or scoring.
Do not modify this method's frozen files while its process is active.

1. Check the PID recorded in the latest private launch receipt using the host
   process view. An isolated tool may not see that PID. Never launch a second
   batch while the original process is alive; do not interrupt an in-flight call
   just to inspect its accounting.
2. For a stopped process, preserve the entire matching freeze/environment,
   `provider/P` admission/outcomes/responses/imports and all three `runs` stores.
   Use those same paths and the same frozen source bytes. Do not replace them
   with empty directories, delete failed/unknown attempts or rewrite bindings.
3. Persisted successes are recovered locally before any new transport. A valid
   cached success under the same complete binding and payload hash is not sent
   again. The per-payload execution lock also shares such a cache between valid
   slots. Missing or corrupt evidence must fail closed, not trigger a blank run.
4. An unanchored but fully persisted outcome can be recovered without a request.
   A reservation with no recoverable outcome is different: the service may have
   executed it, and no server-side exactly-once guarantee is implemented. Preserve
   it as potentially billed. Before a manual restart, reconcile that uncertainty;
   do not describe retrying it as free or as guaranteed not to repeat. The frozen
   running method's bounded transport retries remain unchanged.
5. An incomplete same-freeze continuation uses the existing `run_p.py
   --allow-paid` entry only after the single-writer and evidence checks above.
   It can issue unfinished requests and therefore is not an offline check. When
   all three completion seals exist, the entry without `--allow-paid` performs
   full cache replay and must not construct a provider. Do not run a replay or
   recovery writer concurrently with the active batch.
6. A new source freeze is not ordinary crash recovery. Equal sample/stage names
   do not prove equal requests; compare complete request hashes and image/slot
   identity. Even exact request equality alone does not authorize cross-freeze
   imports. Such reuse requires a separately registered, reviewed provenance and
   import contract before the new freeze. The active P import manifest is
   fresh-P-only; do not inject archived answers or select between old/new answers.
7. Count every recorded transmission across both engineering phases. Report
   duplicate-stage counts separately from identical-request counts. Sum actual
   usage over transmissions, without deduplicating successful repeats. Reasoning
   tokens are a detail of completion tokens and are not added to total tokens.
   Embedding usage normally has prompt and total tokens, without completion
   tokens. Missing usage and unknown outcomes remain explicit. No monetary cost
   is inferred without verifiable billing or prices.

The first engineering phase has four preserved successful requests. Its
replacement phase deliberately starts a fresh ledger under a distinct science
binding, as registered in `INTEGRITY_CACHE_PROTOCOL.md` and the fixed review.
Metadata reconciliation is kept separately under private `accounting/`; the
corresponding ID-free evidence contains cumulative request/token totals and
states its exact cutoff. These totals establish usage, not an MAE improvement.

Offline source confirmation: 53 targeted service/runtime/runner/Gate tests and
one additional synthetic cross-slot-cache probe passed. They demonstrate the
exercised local cache/recovery contracts, not server-side billing idempotency.
