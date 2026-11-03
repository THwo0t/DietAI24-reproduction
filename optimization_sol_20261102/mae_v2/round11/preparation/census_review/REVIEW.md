# P-C0 — first source path census review

## Ready for review

Scope: `round11/source_census.py`, `round11/test_source_census.py` and
`round11/preparation/CENSUS.md` only. Previously reviewed components and frozen
O remain reference-only. Root implementation is the sole code writer.

Eight synthetic unittest cases pass under `unshare -Urn`; no real census,
source audit, new download or API request has been run. Review fixed control
pins, previous-recovery consumption versus fresh-proof claims, body-open and
traversal boundaries, output privacy, refusal/race behavior, and whether any
claim could accidentally permit eligibility, sampling or inference.

Reviewer: independent context; only this REVIEW.md may be modified. Source and
synthetic fixtures only, no actual research data/artifacts, credentials,
network, APIs or production census invocation. Record all findings once, with
priority, stable ID and file:line evidence. Root fixes P1/P2 in isolated English
commits and confirms offline; no second formal review of this scope.

## Independent P-C0 review — 2026-11-04

Decision: **changes requested** for checkpoint `e2f80e3`. This is the single
bounded review by independent `gpt-6.1-sol` context. Two P2 findings and one P3
suggestion; no P1 finding. Root must fix P1/P2 and confirm offline without a
second formal review. Only this review file was changed.

Scope included the source, synthetic tests, CENSUS.md and CHECKLIST.md delta.
Reference-only reading covered AGENTS.md, DESIGN.md, the previous preparation
review, and source contracts in n5_sources.py and o_completion.py. No actual
research datasets, results, control receipts, credentials or production census
were opened or invoked. All execution used synthetic fixtures in a network
namespace, with bytecode disabled. Eight existing tests pass.

### R-PC0-1 — P2 — bind every control path component before opening a body

Evidence: `round11/source_census.py:69-83`. The pre-open `path.resolve()` check
at line73 and post-read check at lines81-82 do not bind ancestor directories.
`os.open(path, O_NOFOLLOW)` at line74 protects only the final component. If an
ancestor is replaced by a symlink after line73, the code opens and reads the
foreign regular file at lines78-79 before refusing at line81. A hash mismatch
or post-read refusal cannot undo opening a protected research/credential body.
This violates `preparation/CENSUS.md:4-5` and CHECKLIST.md's explicit no-body
contract, independently of whether any result is published.

Synthetic reproduction: a temporary `base/controls/control` is an ordinary
anchor, with a separate `foreign/control` containing a synthetic protected
marker. Immediately before the real os.open, rename `controls` and replace it
with a symlink to `foreign`. The returned descriptor resolves to the foreign
regular file; bounded_read subsequently raises `control_path_changed`, after
its read. The reproduction printed only booleans and the fixed refusal code.
The existing test at `test_source_census.py:90-102` covers a symlink already
present before the check, so does not exercise this race.

Required: open ancestors through pinned no-follow directory descriptors and
open the leaf relative to the verified parent; ensure the base/root ancestry
also cannot be substituted during acquisition. Reject before opening a foreign
body. Add synthetic ancestor-substitution regressions with an observed body
open/read guard, alongside the static symlink/FIFO checks.

### R-PC0-2 — P2 — create the output relative to a pinned private directory

Evidence: `round11/source_census.py:251-262`. The initial fresh-output check,
mkdir, parent resolve/mode check and final absolute-path open are separate
operations. Replacing the output parent after line257 with a symlink redirects
line258 into another directory; the leaf's O_NOFOLLOW does not stop this. The
code can report successful completion with the census outside its required
0700 parent. This contradicts `preparation/CENSUS.md:24-29` and can place private
path metadata outside the intended access boundary. An unrelated ordinary
directory replacement can likewise invalidate the checked parent mode.

Synthetic reproduction: patch main's roots and build result to temporary
synthetic values only; start with the intended 0700 inventory directory.
Immediately before the final real os.open, rename that directory and replace
it with a symlink to a separate 0755 directory. main returns success and the
foreign directory contains source_census.json. No production build or census
was called. Existing tests contain no successful/failed output-write fixture;
`test_source_census.py:159-161` calls main only to reject CLI arguments.

Required: acquire/check a no-follow output-directory descriptor, create the
0600 leaf with O_EXCL relative to that descriptor, and verify the intended
parent binding before reporting success. Preserve partial exclusive outputs
on write/flush/fsync failure and refuse retries that would overwrite them.
Add synthetic tests for parent substitution, preexisting regular/symlink
outputs, and injected write/fsync failure with preserved partial evidence.

### R-PC0-3 — P3 — enforce the entry cap while consuming scandir

Evidence: `round11/source_census.py:136-140`. `sorted(iterator, ...)` materializes
an entire directory before the MAX_ENTRIES check runs. Thus the stated bound
limits emitted rows but not enumeration/allocation; one very large directory
can consume unbounded memory before refusal. Consider consuming at most the
remaining allowance plus one entry before sorting, then refuse on overflow.
Keep deterministic ordering and add a synthetic counting iterator regression.
This is a bounded-resource improvement, not a source qualification issue.

### Other conclusions within this bounded scope

- Fixed production roots/pins have no CLI override; controls and anchor hashes
  are checked before and after metadata capture. No dynamic research/provider
  reader or scoring/recovery routine is invoked.
- Previous recovery consumption is described accurately: source lines127-129,
  215-216 and227, and CENSUS.md:17-22 distinguish anchor authentication from a
  fresh full O-store/proof replay. Actual receipt authenticity was intentionally
  not independently checked by opening receipts in this source-only review.
- Directory census uses relative no-follow child descriptors with inode/device
  checks; links and special entries stay unresolved. Credential-name exclusions
  omit their names/sizes. Legacy checks use path metadata without body reads.
- Output/status limitations retain exposure and source-association incompleteness
  and explicitly grant no sampling, download or inference. DESIGN.md:89-111 still
  requires complete actual exposure/association closure before selection.
- Exclusive leaf creation and generic CLI exception output are sound in the
  uncontended path, subject to R-PC0-2's parent-binding fix and missing negative
  output-path evidence. This review does not approve full P-C, actual exposure
  integration, new data downloads, or any expanded paid development run.

## Root disposition — R-PC0-1

Fixed: all absolute control-directory components are acquired from `/` through
no-follow directory descriptors; the regular bounded leaf opens relative to
the held parent. Fresh parent device/inode binding and leaf identity are checked
after the read. Both ancestor-acquisition and post-acquisition/pre-leaf swaps
refuse without opening the foreign synthetic body. Static symlink/FIFO and
same-size/restored-mtime checks remain. Nine synthetic tests pass offline.
This is root confirmation, not a second formal review. R-PC0-2 is still pending;
no production census has run.

## Root disposition — R-PC0-2

Fixed: creation walks all parents relative to held no-follow descriptors,
requires the final parent to be0700, exclusively creates the0600 leaf relative
to that descriptor, and verifies the current parent binding/mode before success.
Parent-acquisition and pre-leaf substitutions refuse; no foreign output is
created. A held-parent artifact is preserved if its parent is renamed before
the final binding check. Preexisting ordinary/link outputs remain unchanged;
injected partial write/fsync failures preserve evidence and refuse replacement.
The successful synthetic CLI exports only aggregates. Fourteen tests pass
offline. Root confirmation only; no re-review or production census invocation.

## Root disposition — R-PC0-3 and bounded-scope completion

Suggestion adopted: enforce the remaining entry allowance while consuming
scandir, before sorting. The synthetic250-entry iterator stops on its fourth
entry with a three-entry limit. Fifteen census tests pass offline; both P2
fixes are independently represented by old-source negative regressions (two
R-PC0-1 failures and one R-PC0-2 failure, all with zero test errors).
P-C0 is fixed after its single review. Root may execute the path-only census;
actual exposure/source closure, eligibility, cohort freeze, downloads and paid
inference remain outside this approval and still pending.
