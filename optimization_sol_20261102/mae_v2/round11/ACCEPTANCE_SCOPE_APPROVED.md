# Approved independent acceptance population

On 2026-11-04 the user approved Nutrition5k **102 observations / 92 complete
association groups** and ASA24 **75 observations / 22 complete association
groups**. The identity-only approval and write-once seal were registered at
11:40:59 Singapore time. This supersedes the pending status of
`ACCEPTANCE_SCOPE_PROPOSAL.md`; that original proposal and its evidence remain
unchanged as historical records.

Both retained identity lists were recomputed using canonical JSON SHA-256 and
match the exact previously proposed fingerprints. Their sample IDs, recorded
image hashes and complete association groups do not intersect the current
843-row development population under the held source metadata. No replacement
was sampled and no data was downloaded. Nutrition5k retains its original row
group IDs (97 distinct values) alongside the authoritative 92-group association
map; uncertainty must use the latter. ASA24 uses its authenticated current
manifest-to-component bindings, while the original manifest rows remain intact.

Private `acceptance_scope/approval.json`, `identities.json` and `seal.json` bind
the human approval, retained rows, complete group maps, source/proposal hashes,
all twenty unchanged MAE thresholds and scoring populations. The public-safe
receipt is `evidence/acceptance_scope_approved_20261104.json`. Files are private
and were created exclusively; the original development freeze was not changed.

This is population designation only. No acceptance image or target was opened,
no method was selected, and no formal validation was started. Qualification,
method freezing and the single formal acceptance batch remain later steps.
Nutrition5k scores all 102 observations including frozen fallbacks; ASA24 MAE
uses every Exact conditional-option observation including option fallbacks,
with end-to-end results reported separately. Per-unit means MAE divided by the
reference mean of the same population; thresholds use unrounded point estimates.
Bootstrap intervals use complete association groups. The original 18% ASA
recognition reference remains separately reported over all 75 records.

Historical reserved-source reuse and the smaller population limit the scope of
the conclusion. Existing limits on global source/API-exposure completeness are
preserved. Future development must keep the sealed identities and their known
associations excluded; this approval does not authorize tuning on acceptance.
