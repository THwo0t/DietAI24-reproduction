# P-C1 mechanical source capture — ready for review

One first bounded independent review is requested for `source_capture.py`, its
test, the `n5_sources.py`/`asa_archive.py` ancestor-binding changes and their
tests, plus SOURCE_CAPTURE.md and the checklist delta. Referenced source-only
dependencies include the already reviewed fixed-source/hash/identity modules
and the pure workbook/content prototypes. Frozen O is reference-only.

Eight new capture tests, eight N5 source tests and ten ZIP tests pass using
synthetic fixtures under unshare with bytecode disabled. Full protected and
candidate dish target fields are poisoned, as are deferred workbook portions;
the capture succeeds without interpreting/exporting them. Source drift, pin
aliases, validation bridges, protected inventory paths, output privacy and
second-capture refusal have negative evidence. No actual source capture, new
download or API request has been invoked.

All129 unique round11 tests pass offline. The pre-hardening N5 and ZIP readers
atdb59d62 each fail their new parent-swap regression (two failures, zero errors).
Implementation-source drift is also rejected by the capture fixture.

Reviewer may modify only this REVIEW.md. Independent context; no actual
research artifacts/receipts/data, credentials, network, APIs or production
capture. Inspect sources and run synthetic offline tests. Give all findings
once with stable R-PC1-n IDs, P1/P2/P3 and file:line evidence. Root fixes and
confirms offline without re-review. Pay special attention to mechanical source
pixels versus sealed validation files, source-pin authentication, parser and
output boundaries, and all false completeness/action grants. This cannot
approve final cohorts or expanded paid inference.

## Independent bounded review — 2026-11-04

Decision: **approved for the P-C1 mechanical source-capture implementation at
55f5fec only**. No P1, P2 or P3 findings were identified; no R-PC1 finding IDs
are assigned. This is the first and only review of this bounded stage.

Evidence (paths relative to round11):

- Original source authentication is retained: `n5_sources.py:112-137` binds
  fixed anchors, seal-derived proposal/audit pins, the fixed raw-source slots
  and original/final snapshot continuity. `source_capture.py:87-95` derives
  the fixed original protocol pin from that authenticated original snapshot,
  then authenticates the named workbook and ZIP. Recorded pins for the three
  unopened ASA tables are explicitly registrations, not fresh body checks
  (`preparation/SOURCE_CAPTURE.md:29-36`). Arbitrary inventory paths are not
  followed.
- Mechanical source pixels and sealed validation files are distinguished:
  `source_capture.py:80-95` invokes only the fixed identity reader, raw linkage,
  workbook identity projection and source ZIP fingerprinting. It does not call
  numerical eligibility. `source_capture.py:103-132` removes provisional
  allowed IDs, exports identity projections only, and separately states that
  source ZIP pixels were fingerprinted while sealed validation files were not
  opened. No dish target or legal portion is interpreted or exported by this
  path. Ingredient masses remain confined to blind graph construction.
- `n5_sources.py:70-102` opens bodies relative to held no-follow ancestor
  descriptors, bounds reads, verifies identity/hash and revalidates sources.
  `asa_archive.py:23-43,79-124` holds the fixed archive descriptor, checks the
  expected hash before parsing, checks it again afterwards and reopens the
  fixed path for a final hash check. `source_capture.py:96-102` additionally
  rechecks controls, census, protocol, workbook and implementation provenance.
  These checks establish captured-byte consistency; they are not a lock or a
  claim that external sources can never change after capture.
- `source_capture.py:128-144` leaves source association, latest exposure,
  candidate eligibility and all action grants false. `source_capture.py:149-164`
  refuses CLI overrides, requires the isolated namespace, exclusively writes
  through the existing private writer and reports only aggregates/hash or a
  generic exception class. `source_census.py:284-323` is reference-only evidence
  for exclusive0600 output beneath0700 and preserved partial failures.

Reviewer verification: independently ran the8 source-capture,8 N5-reader and10
ZIP-reader synthetic tests using `unshare -Urn .venv/bin/python -B -m unittest
discover`; all26 passed. This includes poisoned target/deferred values,
protected inventory-path exclusion, protocol/census/implementation drift,
validation-bridge rejection, parent substitution, archive drift, private CLI
output and repeat-capture refusal. The submitted129-test total and old-version
regression result are implementation evidence, not independently rerun claims
in this review. No actual research artifacts, receipts, data, images or
credentials were opened; no production capture, network or API was invoked.

This decision does not approve full source/exposure closure, candidate
eligibility, cohort construction, sampling, downloads, paid inference, or a
future runner. Those remain pending. It does not replace user authorization
for any later action; root may perform the already-authorized mechanical
capture only within the existing task boundary.
