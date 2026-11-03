# Independent bounded delta review: model-input identity v3 and inventory storage

Date: 2026-11-04. Reviewer: independent Codex `gpt-6.1-sol` agent.
Reviewed commit: `bddc1adaf0e4003bb9d2141be73f2cca00875e90`.
The eight scoped implementation/test files are unchanged between that commit and current HEAD. This is one new delta review; unchanged previous inventory behavior and unrelated later prototypes were not re-reviewed.

## Decision

**approved** for the bounded implementation delta. No P1, P2, or P3 findings.

1. V3 binds the registered algorithm prefix, NUL, unsigned big-endian width/height, and exact loaded Pillow `convert('RGB')` bytes, while retaining independent source-byte SHA-256 (`asa_content_identity.py:22`, `:45–64`). This matches the actual pre-resize conversion in `../../src/opt_pipeline.py:99–114`, with no claim of universal rendered appearance. The generic entry point accepts content-detected PNG/JPEG; the compatibility wrapper remains PNG-only (`asa_content_identity.py:67–74`). Graph validation requires the exact v3 algorithm and rejects v1/v2 (`:100–105`). PNG/JPEG validation, full decoding, pixel/byte bounds and single-frame rejection remain fail-closed.
2. Archive selection remains the existing finite `.png`-named member scope with preserved ZIP/source checks; selected bytes now use the generic fingerprint (`asa_archive.py:87–104`). JPEG-content `.png` members therefore receive v3 rather than failing solely on encoding. Local PNG/JPEG inventory retains its independent RGB convention and semantics flag while obtaining the same v3 compatible digest (`local_content_inventory.py:54–85`).
3. Compaction preserves image rows, all symlink/exclusion/special rows, link metadata, census pins, counts and other projection fields; only duplicate ordinary nonimage entry storage is omitted. It hashes the full original projection without mutating it (`source_inventory_capture.py:74–84`). The full projection remains reconstructible through the pinned census and pinned projection implementation, rather than being silently discarded. Serialized output is checked against imported 64 MiB `MAX_FILE` before `_collect_at` returns and before `main` can write (`:150–169`; `source_census.py:21`). Existing false completeness/eligibility/action flags remain false.

## Offline verification

Executed from repository root using network isolation and the absolute interpreter, without production entry points:

```text
unshare -Urn /home/lelouch/Data/Projects/DietAI24_original/.venv/bin/python -B -m unittest discover -s optimization_sol_20261102/mae_v2/round11 -p '<file>'
```

- `test_asa_content_identity.py`: 15 passed.
- `test_asa_archive.py`: 12 passed.
- `test_local_content_inventory.py`: 18 passed.
- `test_source_inventory_capture.py`: 12 passed.

Total: 57 passed. Included negative paths cover old algorithm rejection, GIF/APNG, invalid/truncated bytes, PNG CRC/byte/pixel bounds, wrong source pin before decode, source drift, and oversized output refusal before any private write. The synthetic JPEG/decoded-PNG pair also compares actual `encode_image` output in both modes.

An additional independent `unshare -Urn` synthetic check recomputed the exact JPEG v3 payload and byte digest, refused empty/garbage/two truncated inputs, and verified compaction retains every image/link/exclusion/special disposition, the full-projection hash, census pins, link metadata and input immutability.

Only source and synthetic/ID-free test evidence were read. No actual dataset, census artifact, source images, labels, credentials, network API, production capture, cohort selection or inference was accessed or run. Supplied header-only corpus evidence was treated as coordinator evidence, not independently verified full-decode success. This review grants no capture, source-completeness, cohort-eligibility, download or inference permission.

## Root disposition

Approved within the v3 encoding/storage delta with zero findings. Root confirms
57 scoped executions and the then-complete307 distinct unittest IDs passed
offline. A later metadata preflight identified175 static Tk/IDLE GIF assets
in the finite census; the next inventory attempt was interrupted before output.
Their narrow local-only dependency rule is a distinct prospective delta, not
a v3 ASA encoding or source-eligibility change. No second v3 review occurred.
