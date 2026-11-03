# L training-only pilot checklist

Old development methods and sources remain immutable. This pilot is not a
formal report or validation run. Use `PROTOCOL.md` for the registered method.

| Item | Work | State |
|---|---|---|
| R6A | Fixed paired question, 25/230 grouped pilot, gate and publication scope | implemented |
| R6B | Pure region annotation, deterministic crops, J-compatible candidate | implemented; synthetic tested |
| R6C | Scoped transport, ordered image receipts, durable budgets and replay proof | implemented; synthetic tested |
| R6D | Training-only fold assets and label-free query context | implemented; synthetic tested |
| R6E | Resumable paired runner and full-seal-only offline scorer | implemented; synthetic tested |
| R6F | Independent formal review | deferred after user scope correction |
| R6G | Real preflight and paid pilot | not started; N5-only CLI shelved |
| R6H | Real score | not run; no L accuracy claim |

The completed 95-test engineering suite passed in 58.096 seconds with networking
disabled. A subsequent CLI guard prevents accidental paid execution of this
N5-only design. User steering requires a common method newly tested on both
datasets, full project retrospectives after failures, and a separately defined
relaxed MAE acceptance rule. These override this unexecuted pilot's advance path.

No paid request until R6B–E tests pass, R6F is handled and R6G sources are frozen.
At review, supply exact source/commit scope, tests and known concerns in
`REVIEW.md`; the reviewer edits only that file and makes no paid request.
Required fixes receive isolated English commits citing their review IDs; offline
evidence confirms them without a second review. User authorization for existing
data and paid development persists. No new download is part of this pilot.

If the advance gate fails, stop this candidate, back up safe source/aggregates,
and register the next mechanism separately. Do not rerun, alter the sample or
open validation. Final reports and actual Mac verification remain deferred.
