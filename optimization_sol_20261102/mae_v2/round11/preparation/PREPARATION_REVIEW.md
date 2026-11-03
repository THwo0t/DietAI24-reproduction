# First complete capacity-v4 preparation review

Scope: `P_capacity_v4_preparation`. Decision: **changes requested**.
Findings: **0 P1 / 1 P2 / 0 P3**. This is the single complete preparer review,
not a repeat of an earlier bounded component review or the future integrated
cohort/runtime review. No approval gate is created by this review.

Reviewed independently with `gpt-6.1-sol` on 2026-11-04 at source HEAD
`08954450a64561b7f65a51d8b4f080ad83adf846`, including the then-untracked stable
preparer and protocol. Relevant content SHA-256:

| File under round11 | SHA-256 |
|---|---|
| prepare_p.py | 6ad207d35a37423dc82b4e3f179c1ee516457a2459b9284aef15b822484b85e8 |
| test_prepare_p.py | 320410dac5c0a3f13dfdfcf499d802154ec7ab347a7b28d9db26afe51a23f995 |
| PREPARATION_PROTOCOL.md | 410c566dc9010262f044635e6bdee0125826127841f273aaa8d6e8aa828695ca |
| source_scope_v3.py | a1b78f07836e36cc0334b0a251baedcc3e669821cd5e97e9fb76b0466bb47d74 |
| asa_expansion_v3.py | 1189749fac10f3dcc240304ebc851381002b8dd738346601a8eef16182c661de |
| capacity_cohort_v4.py | 41f9191a59189629a10e85fff73354e0c93c9636718c3b40fde3893f6b2364d4 |
| training_identity.py | 4dce7c1cb1212b8e1b3f257e8640a9bd2eb5b104d21613e6067e5e5e13597903 |
| caller_registration.py | be9750058e0c72354ab094f200d53bb065df05a7847ea871578b415f06150b11 |

During review the coordinator recorded the same preparer/protocol/test bytes in
commit `0ca1fe1`; the content hashes above identify the reviewed snapshot across
that bookkeeping change. The coordinator's separate full-suite report is not
counted as this reviewer's independent executions below.

Paths below are relative to `optimization_sol_20261102/mae_v2/round11/`
unless another prefix is explicit. Governing prospective requirements are
DESIGN.md, CAPACITY_AMENDMENT.md, COHORT_REPAIR_DESIGN.md,
preparation/SOURCE_DISPOSITION_DESIGN.md and PREPARATION_PROTOCOL.md. These
changes register a new preparation protocol; they do not establish a new paper
result or relax any paper metric.

## R-PC6-1 — P2 — include the active preparation dependencies in the review pins

`prepare_p.py:41-48` omits local modules whose current contents affect this
entry. In particular, `service_p.py` supplies `NAMESPACE` and `ROW_FIELDS`
through `prepare_p.py:26`; these determine accepted identity schemas and the
published common/embedding namespace (`prepare_p.py:274-281,341-345`). It is
absent from both `PREPARATION_SOURCES` and the fixed caller registration's
`SOURCE_FILES` (`caller_registration.py:37-62`). Changing that module therefore
does not invalidate the preparation review gate.

There is also an unbound active source-verification dependency:
`prepare_p.py:371,397` calls `source_inventory_capture.verify_asa_bindings` and
`verify_legacy_bindings`. Those helpers obtain their archive source/open/digest
operations from `asa_source_capture` and their allowed legacy manifest set from
`legacy_input_identity` (`source_inventory_capture.py:15-18,42-58`). Neither
module is in the preparation pin inventory or the caller-registration source
inventory. The existing mechanical receipt records implementation hashes, but
the new preparer never compares those implementation hashes to the active
modules: it authenticates the receipt body and source bodies instead
(`prepare_p.py:378-407`). A historical digest inside an authenticated receipt
does not itself authenticate the current helper implementation.

The exact-set gate at `prepare_p.py:115,127` prevents a coordinator from simply
adding these files to the gate without correcting the required inventory.
Consequently a correctly formed gate can pass and reach numeric eligibility or
development labels with these preparation dependencies changed since review.
This violates PREPARATION_PROTOCOL.md:9-14,20-21's exact source inventory and
before/after source-pin contract. The present code is not alleged to leak a
label or make a network call; the issue is that its reviewed behavior is not
fully bound by the claimed gate.

Required correction: enumerate and authenticate the local modules that actually
supply preparation behavior, including these three, and retain their digests
through final revalidation. Alternatively remove unnecessary dependencies by
moving the small preparation constants/contracts into an explicitly pinned
module. Check the reached dependency graph rather than only adding the examples
above. Add synthetic negative checks in which each newly required dependency
changes or disappears after review, proving refusal before the source loader
and refusal on final source drift. Preserve historical receipt implementation
pins as history rather than rewriting old receipts. Root should confirm the
fix offline in an isolated English commit citing R-PC6-1; no second formal
review is requested.

## Requirement-by-requirement conclusions

The following approvals describe the inspected behavior subject to R-PC6-1;
they do not grant actual preparation, download, acceptance or inference.

| Acceptance requirement | Conclusion and evidence |
|---|---|
| First review before eligibility or old development/support targets | **Changes requested** for the source inventory in R-PC6-1. Ordering itself is correct: `_prepare_at` calls `_review` before `_production_inputs` (`prepare_p.py:547-551`); the gate checks scope, status, zero unresolved P1/P2, review text and all five receipt bindings (`:105-131`). The network-isolated public entry has no argument overrides (`:554-564`). |
| Honest finite source disposition, missing-source quarantine and no global-completeness claim | **Approved.** `source_scope_v3.py:105-120` reconstructs the full supplied ASA graph before quarantine, compares it to the held audit and refuses unmatched protected anchors. Lines125-131 retain missing names and derive their complete components; lines203-237 return the blocked/permitted partition and false global byte/pixel/exposure/action flags. This implements the explicit available-source amendment in SOURCE_DISPOSITION_DESIGN.md rather than pretending the original global guard succeeded. |
| Full-source allowed set, protected roles and caller evidence, not caller-selected safe inputs | **Approved for the fixed authenticated assembly.** `source_scope_v3.py:45-100` verifies all sixteen registered conservative caller envelopes, role counts and inherited N5 blocks; `:203-205` computes ASA permitted components/codes from the full reconstructed graph. Production uses the fixed receipt's N5 state, not an externally supplied allowed list, and authenticates its current raw-source hashes and identity projections (`prepare_p.py:378-411`). The saved N5 state was built by `cohort_lineage_v3.py:48-109` plus the potential-input overlay; a supplied hash alone is not treated as authentication. Pure helper fixture seams remain outside the public production contract. Neither caller registration nor these receipts certify actual historical API use. |
| Old sources, cohorts, folds and O remain immutable | **Approved.** Only `round11/prepared/` is writable through the producer (`prepare_p.py:134-166`). Original bindings are retained by `capacity_cohort_v4.py:35-93`, ASA bindings by `asa_expansion_v3.py:49-50,135-153`, and source/control authentication by `prepare_p.py:385-407`. No O run, rescore or old-manifest writer is invoked. |
| All 314 N5 development observations, explicit historical reuse | **Approved.** Fixed counts are84+230 (`capacity_cohort_v4.py:35-75,96-97`), all accepted source bindings must match proposal byte/RGB/recipe/group identities (`:56-73`), and historical support has its own reused-not-fresh stratum (`:74`). Production checks314 (`prepare_p.py:493`) and retains the false freshness claim in closure (`:542`). This follows CAPACITY_AMENDMENT.md, superseding only the impossible fresh216+200 allocation. |
| Complete association folds and ambiguity containment | **Approved.** `capacity_cohort_v4.py:76-87` assigns complete components to units, pools every retained ambiguous component into one uncertainty unit, uses a fixed seed and refuses fewer than five units. `prepare_p.py:282-285` rejects cross-fold group and association bindings; ASA old component folds and new broad-component folds are explicit (`:472-478`). Physical-plate identity is not certified. |
| ASA99 plus admitted legal extras and20 broader components | **Approved.** `prepare_p.py:431-443` defers numeric workbook/weight projection until the bounded permitted code set is known. `asa_expansion_v3.py:71-81` retains core-photo identity, excludes missing/validation extras, and selects the fixed first20 safe components without error-based reroll. Original99 rows/labels are copied through their authenticated bindings (`prepare_p.py:452-476`); new source grams/densities are mechanical (`:481-492`). Shortfalls remain explicit. |
| Complete legal catalogue before selection, immutable old prefix | **Approved.** `_extend_catalog` appends every distinct permitted legal description/gram option deterministically, checks identifiers, and preserves all old food/density/standard fields and old ASA entry order (`prepare_p.py:201-237`). Production calls it before broader-component selection (`:444-449`); every prepared ASA mass must be in that code's resulting legal list (`:313-316`). Synthetic tests include an unselected safe code, reversed rows, duplicate options, changed old IDs/density and an illegal prepared mass (`test_prepare_p.py:162-195`). |
| Independent proposals only: N5102+98 and ASA75+3 | **Approved.** N5 checks all200 legacy-reserved identities and associations, retains unlinked rows, uses the capacity seed's group/dish round-robin order and records fixed-order shortfalls (`capacity_cohort_v4.py:100-157`). Production requires102 retained and the full137 official-RGB frame (`prepare_p.py:414-427`). ASA chooses development20 first, then one fixed remaining top1000 code's registered triplet (`asa_expansion_v3.py:97-133`), preserving the pending old-validation repair binding (`:90-96`). Production removes portion-source targets from its proposal (`prepare_p.py:494-498`). No new validation designation is made. |
| Protected targets/images stay sealed; no hidden nutrient-magnitude selection | **Approved.** `_eligible_raw` skips protected identities before Decimal conversion and uses only finite/nonnegative, positive-mass and present-nutrition checks (`prepare_p.py:179-196`). N5 proposal ordering never uses magnitude; ASA replacement size ordering is the expressly registered legal triplet, not model-error selection. Only fixed development/support labels and authorized blind development image sources are loaded (`:450-492,515-531`); all independent acceptance image hashes remain unknown metadata (`:499-506`). No protected image/label or historical prediction loader is called. |
| Byte/RGB/potential-input collisions and unknown local digests | **Approved for preparation.** `source_scope_v3.py:132-174` considers every local byte and compatible V3 RGB identity and retains all248 unmatched identities; unresolved links remain unfollowed (`:188-192`). N5 uses the held full recipe/byte/RGB screening closure. Future blind post-download exact collision screening remains mandatory (`prepare_p.py:506`); it is not falsely marked completed before a download. |
| Fixed source authentication and before/after revalidation | **Changes requested** only for R-PC6-1's missing implementation pins. The inspected bound sources themselves are revalidated around assembly, before publication and after publication (`prepare_p.py:101-102,395-407,532,346-353`). Development/support label and image pins derive from fixed authenticated seals, not caller-selected paths (`:452-464`). The fixed vector matrix is streamed under a96MiB bound, not sent through the64MiB body reader (`:80-100,508-514`). |
| No-follow paths, partial writes, private publication and resume | **Approved.** `prepare_p.py:134-166` walks directories with `O_NOFOLLOW`, requires private0700 directories, creates exclusive0600 regular files and compares existing immutable bytes. Blind image bodies have a5MiB bound and exact source digest/member binding (`:287-309,515-531`). Common is published last, all outputs are rehashed, and a failed/partial preparation supplies no science freeze (`:346-363`). |
| Fold-local fallback, disabled inference calibration and no implicit imports | **Approved.** `prepare_p.py:240-258` excludes the held-out fold and groups, records train/held-out identities, computes training-only medians and emits disabled identity multipliers. Embedding imports are empty with fresh-P-only policy (`:339-342`). No old prediction import or new gallery is enabled here. |
| Runtime remains closed, future review distinct | **Approved.** `prepare_p.py:325-337` explicitly leaves inference/science freeze and acceptance grants false, with status `prepared_development_pending_integrated_review`. It writes neither a runtime review gate nor `round11/prepared/freeze.json`. PREPARATION_PROTOCOL.md:86-93 retains the separate integrated review/science freeze. No nonexistent runtime approval is demanded as a prerequisite to this preparation review. |

## Independent offline verification and limits

Executed only synthetic tests, each using `unshare -Urn .venv/bin/python -B
-m unittest discover -s optimization_sol_20261102/mae_v2/round11` with these
patterns: `test_prepare_p.py` (11 passed), `test_*v[34].py` (48 passed),
`test_training_identity.py` (9 passed), `test_caller_registration.py` (7 passed).
Total: **75 executions passed**. Inherited v3 tests are regression evidence,
not a reopened formal review of their earlier bounded scopes.

One additional synthetic gate probe confirmed that an unregistered dependency
file is outside the gate's checked pin set; a direct check of the production
required set confirmed the three omissions in R-PC6-1. This probe did not invoke
production assembly. Existing producer tests deliberately replace that assembly
with a synthetic loader; their success must not be described as a real-source
preparation run or proof of actual cohort counts.

Read source/design/review files and the registered ID-free
`evidence/identity_capacity.json` only. No completed mechanical scan was rerun;
no private large receipt, research label/image, raw prediction, `.env`, API,
network download or actual source assembly was accessed. No code, gate, stage,
commit or old artifact was changed. Only this new review record was written.

Actual preparation remains stopped until R-PC6-1 is fixed and independently
confirmed offline by the coordinator. This review never authorizes acceptance
designation/download, paid inference or a scientific-success claim.

## Coordinator disposition — R-PC6-1 fixed

Added thirteen active project dependencies to the preparation review inventory:
`service_p`, `asa_source_capture`, `legacy_input_identity`,
`local_content_inventory`, `local_input_inventory`, `n5_potential_identity`,
the artifact store, the three M service/runtime/history modules, and
`cohorts_v2`, `opt_pipeline`, `opt_provider`. These current source hashes are
authenticated before assembly and included in the final source revalidation;
historical receipt implementation hashes remain unchanged.

The coordinator independently ran the thirteen synthetic producer tests under
`unshare -Urn` with the project Python interpreter: all passed in 1.407 seconds.
The new negative coverage checks modification and removal of each of the thirteen
dependencies before source loading (26 subcases) and after common publication
(26 subcases), followed by exact-byte restoration and resume. The pre-gate
failures do not invoke the source loader. This is offline fix confirmation,
not a second formal review or an actual-source preparation run.

Disposition: **fixed; unresolved P1/P2 = 0**. Only the reviewed development
preparation may now be invoked through a source-bound preparation gate. Paid
inference, acceptance designation/download and runtime science freezing still
require their separately recorded gates and boundaries.
