# First bounded integrity-cache amendment review

Decision: **changes requested**. Findings: **0 P1, 1 P2, 0 P3**. This is the first and single bounded review of the integrity-check performance amendment against `20c748572d50cc2149f509e95c1a5691c6c10c24`; it does not reopen the complete P review or its fixed R-P-1/R-P-2 findings. The coordinator must fix the finding and confirm it offline before registering replacement receipts or freezing/starting the replacement batch. No second formal review is requested.

## R-PI-1 — P2: bind the image root throughout the cache lifetime

`round11/gate_p.py:85,88` builds the cache using the constructor root, but `verify_context` at `:112-124` never checks that `self.root` still denotes that root. Machine reconstruction reads the mutable root at `:59,64`. The context verifier authenticates files beneath its separately captured context root (`context_p.py:172-183`), so changing only `gate.root` disconnects the cached image proof from the images used in later task reconstruction. The removed per-check conversion reconstructed slots from the current `self.root` and rejected this change. This violates the same-frozen-input premise of `INTEGRITY_CACHE_PROTOCOL.md:29-36` and the preserved exact task/payload contract at `:38-40`.

Independent, network-isolated synthetic reproduction: construct the normal test fixture with a generated red image; create a second temporary directory containing a blue image at the same relative path; assign only `gate.root` to the second directory. The amended `verify_context()` succeeds, and `engine_p.identify(..., root=second_directory)` completes all four synthetic identify/embedding/select requests through Gate validation. Loading the baseline Gate directly from `git show 20c7485:.../gate_p.py` and applying the same single-attribute mutation rejects with `P_frozen_rows_or_slots_changed`. No production image, source file, provider, ledger, or process was changed. All 176 existing P tests pass despite this regression.

`service_p.py:219-231` independently rejects an altered chat image when the real ledger binds a request; this reproduction does **not** demonstrate a paid-admission bypass, label leakage, or changed scientific results. P2 reflects the lost fail-closed Gate invariant and incomplete equivalence proof. Preserve the initialization root as a validation anchor, reject a changed/noncanonical root before using the conversion cache, and keep the fixed production ROOT binding. Add synthetic regressions for single-attribute root mutation and a mismatched initialization/context root, without reintroducing cohort-wide conversions. As in the protocol's stated trusted-process model, this need not defend against an attacker replacing both values and their validation anchors.

## Other reviewed contracts and evidence

The constructor verifies all context sources before conversions and again after the full allowed-slot equality check; the production context verifier checks complete source bytes, frozen environment and live context, with no mtime shortcut. Subsequent checks retain tuple-cache digest, frozen-slot digest, row digest and row-map equality, catalog/import/manifest checks. `allowed_slots` rejects duplicate sample IDs before constructing its map. Existing task reconstruction and cached-parser-failure repair paths remain unchanged, and the exact current-query payload is rebuilt. Parser code remains in the actual production required inventory through PARSER_SOURCES. Full immutable byte/code/environment premises support reuse of deterministic RGB/bicubic/PNG/base64 fingerprints, subject to R-PI-1 and the explicitly inherited package/trusted-process/path-race assumptions.

Both new documents, `round11/INTEGRITY_CACHE_PROTOCOL.md` and this review, are mandatory in context REQUIRED and freezer EXTRA; `_freeze_at` uses the production inventory union. The protocol retains `paired-portions-r11-p.1` for unchanged science and makes only operation-count claims: N conversions once per Gate, zero cohort conversions or slot reconstruction per subsequent context check, while full source hashing and individual query conversion remain. No measured percentage/time saving is claimed.

Read only the permitted ID-free `round11/evidence/P_integrity_performance_transition.json`: it reports four reservations/four outcomes, zero pending/inflight, preserved old freeze and checkpoint, and no response/accuracy inspection. Independently checked that active `prepared/freeze.json`, `provider/P`, `runs/P`, runtime review gate and postscore review gate are absent. No replacement receipts were fabricated by this review. The archive body was not opened; preservation contents and cohort/preparation byte equality are coordinator transition evidence, not independently reread here. Existing write-once freeze/ledger binding and fresh production roots remain unchanged, and the new source hashes require a distinct replacement science binding. No authorization to pool old partial results, resume against the old binding, or overwrite old artifacts is granted.

## Independent verification and scope

Ran `unshare -Urn .venv/bin/python -B -m unittest discover -s optimization_sol_20261102/mae_v2/round11 -p 'test_*p.py'`: **176 tests passed in 17.375 seconds**. Also ran the two isolated root-mutation probes above against amended and baseline Gate implementations. Tests used generated images and synthetic answers only. No API/network, actual replay, credentials, development/validation targets, research images, historical responses, accuracy values, process control, staging or commits were used. Actual provider access, accuracy, full scientific replay, independent acceptance and Mac hardware remain outside scope.

## Reviewed amendment content inventory

SHA-256 of reviewed files (paths relative to MAE-v2):

| Source | SHA-256 |
|---|---|
| `round11/gate_p.py` | `fde71491c4f3530052afc0bc65d8a7774a112957e8106ccd967346959379fa01` |
| `round11/test_gate_p.py` | `5cf6bdcc01850d0f864b759bc8792ef58c7b98098e84cc037c7a75f04c43201d` |
| `round11/context_p.py` | `ef028d6f5f0f0ccaf115406cd7be9c965e0b665ce256cb47bc9ff0d8848becd3` |
| `round11/freeze_p.py` | `34ac7f96d4ef8f8a2ed27052b67139416fd94f38e957168d7812aac09860bd5a` |
| `round11/INTEGRITY_CACHE_PROTOCOL.md` | `f5cb185c8ba9cd5dc151551d275e54bf5c490a99c16473dd7231b035faeea8e1` |

## Coordinator disposition — R-PI-1 fixed

The Gate now preserves its canonical construction root as a string anchor and
checks it on every validation. A changed/noncanonical root is rejected before
cached conversion proofs are used. If a context supplies a root field, its
presence and canonical value must remain consistent with that anchor. The actual
production context has no root field: its verifier closes over the fixed root,
and `frozen_gate` still uses the fixed production ROOT and ledger directory.

New generated-image regressions cover the single-attribute Gate root mutation,
mismatched construction/context roots, removal of a supplied context root, and
symlink roots. These failures and repeated valid checks perform no cohort image
conversions. The coordinator's complete network-isolated suite passed **523
distinct tests in 51.904 seconds**, including all six new cache/root regressions.
The implementer's separate P-scoped pass passed 178 tests. This is offline fix
confirmation, not a second formal review or an actual scientific replay.

R-PI-1 is **fixed; unresolved P1/P2 = 0**. The previous four paid requests remain
archived with their original freeze and ledger; their answers and accuracy were
not inspected for this amendment. Replacement gates and a distinct scientific
source binding may now be registered for the unchanged, already authorized
development method. No previous partial results may be pooled into its fresh
ledger. The preparation/cohort bytes and pending independent-acceptance boundary
remain unchanged. No MAE, acceptance, cost amount or Mac hardware pass is implied.
