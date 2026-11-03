# Round 7 implementation checklist

The implementation and development results are frozen; M failed the target.
All new subagents for
this project are explicitly gpt-6.1-sol; unrelated projects inherit their parent.

| Item | Scope | State | Evidence |
|---|---|---|---|
| R7-A | Whole-project review and common dual-dataset protocol | approved and frozen | PROJECT_REVIEW.md; PROTOCOL.md |
| R7-B | Shared accounting core with one-text whole RRF, exclusive paths and conserved C quantity | approved | src/shared_accounting.py; 18 synthetic core tests |
| R7-C | Read-only exact raw-C historical importer | approved | all84 real image/payload/parser/aggregation replays independently passed;3159 explicit old embedding imports |
| R7-D | New dual-role service provenance and runtime | fixed | R7-G-1; independent M ledger/cache, fsync budgets and exact response binding |
| R7-E | Dataset adapters, label-isolated preparation and 10-check tolerance scorer | approved | post-seal ASA adapter; fixed other-fold fallbacks; per-dataset tolerance and common-Exact |
| R7-F | Resumable paired M0/M runner and full offline preflight | fixed and frozen preflight passed |38 offline tests; real guarded preflight forbids labels/credentials/Provider and confirms no writes |
| R7-G | One independent implementation review, fixes, immutable freeze | complete | REVIEW.md,review_gate.json,readiness.json;20 source/input pins |
| R7-H | Both-dataset development inference and complete scoring | completed; targets not met |183 pairs; zero-Provider verification; M0 fails4/10 ASA,10/10 N5; M fails9/10 ASA,10/10 N5; both9/99 Exact |
| R7-I | Full retrospective and explicit public backup | retrospective complete; backup pending | PROJECT_REVIEW.md; sealed post-score diagnostics; no per-iteration formal report |
| R7-J | Dot's original 4o/Sol prediction-chain diagnostic, isolated from method selection | completed offline | original_comparison_diagnostic.json; all300 archived rows replayed, no query labels or API |

The R7-B tests verify synthetic mass conservation, candidate membership, mutual
exclusion, original ownership, distinct whole identity, fixed pre-portion coding,
format-repair limits, service-stop propagation and changed-input rejection.
They establish contracts only, not an MAE improvement. The first test invocation
used an incorrect test import root and failed before loading the target module;
the corrected source path passed. A mutation test then exposed an unchecked
unused child bank; a bound accounting-input hash now rejects that change before
quantity inference. No research row, reference label or external call was used.
The existing 32-test ComponentPipeline suite also passes with networking disabled;
the historical C source was not modified by this implementation.

R7-C's real preparation read development labels only in its isolated fallback
step. The C importer itself loaded none; it reconstructed all84 actual images,
original chat payloads, raw repairs, 384 child banks,530 exact query texts and
all leaf nutrition. It wrote only separate private prepared outputs. Its initial
embedding inventory missed314 later-development provider logs; their source
locations were found without new inference, and the initial manifest is preserved
in ignored preflight_archives. The corrected3159-entry manifest has zero rejected
old successes and explicitly records whether an old persistent counter exists.

The38 synthetic tests are network-disabled. They cover authorization/route keys,
payload identity, model mismatch, invalid vectors, redaction, orphan caches,
unlogged reservations, three-attempt exhaustion, ASA option fallbacks, per-dataset
tolerance, two-arm execution and immutable completed replay. They do not establish
M accuracy, real-provider availability today, or independent validation success.
