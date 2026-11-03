# PNG model-input identity v2 — independent bounded review

Reviewed commit: `93b5bc3aabfbfe63a9b188152a715975f7442b7b`.

Decision: **approved for this decoder delta**. No P1/P2/P3 findings. This is not approval of full source closure, cohorts, actual capture, eligibility, sampling, download, or inference. The prior v1 refusal and its absence of a completed inventory are not rewritten by this review.

## Evidence and scope

The scope was the new-version changes to `round11/asa_content_identity.py`, `round11/local_content_inventory.py`, and their two tests, against `PNG_INPUT_IDENTITY_V2.md` and `SOURCE_INVENTORY_DESIGN.md`. Paths below are relative to `optimization_sol_20261102/mae_v2/`.

- Actual encoder evidence: `src/opt_pipeline.py:99–114` opens with Pillow, converts directly to RGB before resizing, copies into a clean RGB image and writes PNG. It does not composite alpha, apply ICC transforms or transpose EXIF orientation. `round11/asa_content_identity.py:22,35–64` matches that pre-resize operation, binds algorithm/dimensions/row-major bytes, retains the independent source-byte SHA, and performs container verification plus a fresh decode. The v2 name is intentional, not a v1 relabelling or a universal appearance/physical-plate claim.
- `round11/local_content_inventory.py:55–86` retains its separate generic digest and semantics flag, now supplies v2 ASA compatibility for PNG, still excludes JPEG from ASA compatibility, and rejects multiple frames. The delta adds no file-reader/root override or target access. Its closed-list reader, fresh source rehashes and census checks at `:29–52,90–115` are unchanged. The implementation-pin list still includes both decoder files (`round11/source_inventory_capture.py:29–39`); no source-pin aliases or historical hashes were rewritten by this delta.
- Offline tests: the two modules passed **14 + 17 tests**, each using `unshare -Urn /home/lelouch/Data/Projects/DietAI24_original/.venv/bin/python -B -m unittest discover -s optimization_sol_20261102/mae_v2/round11 -p '<module>.py'`. Coverage includes explicitly refusing v1 graph fingerprints (`round11/test_asa_content_identity.py:102–110`), non-PNG/corrupt/oversized inputs, animation, CRC damage, pixel permutations, preserved generic semantics, fixed paths, changed-source refusal, and synthetic label-path exclusion.
- Supplemental network-isolated synthetic checks passed for spatially varying RGBA, LA and 16-bit grayscale PNGs: independently constructed v2 payload matched both decoders and actual native encoder RGB bytes. Corrupting an IDAT CRC was refused by both decoders (five supplemental cases total). These checks created temporary fixtures only. No actual dataset/photo, census/private artifact, credential or network/API was read or invoked.

## Findings (all findings reported once)

None. The existing 3 × 2 EXIF-orientation fixture exercises changed dimensions in native mode, while source inspection confirms the exact untransposed RGB operation. The bounded decoder delta needs no corrective finding.

## Root disposition

Approved for the new decoder delta with no findings; no re-review requested.
Root full-suite execution found one stale archive fixture still expecting RGBA
to fail. It now uses a JPEG-labelled-as-PNG as the unsupported-format case and
adds a successful transparent PNG archive path. All23 archive/ASA-role tests
pass offline. This is fixture alignment with the reviewed versioned contract,
not a decoder change. Full source/role and paid-run gates remain pending.
