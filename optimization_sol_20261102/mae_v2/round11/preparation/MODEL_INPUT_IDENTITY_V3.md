# Prospective model-input identity v3

Registered before the next actual capture retry. The v2 historical rule and
receipt are preserved. The v2 actual capture stopped at
`supported_bounded_png_required` on one JPEG-content member named `.png`, without
producing a new artifact. This is an encoding/extension mismatch and decoder
coverage issue, not a model error or MAE measurement.

## Header-only source evidence supplied by the coordinator

The complete header-only archive inventory reports archive digest abbreviated
`2c0c68...e1c38`, size 670,269,206 bytes, and 17,135 `.png`-named members:
17,131 PNG:RGBA, 3 PNG:RGB, and 1 JPEG:RGB. It reports 97 ICC-bearing members,
no multiple-frame images or header failures, maximum dimensions 341 × 240,
maximum pixel area 78,430, and maximum member size 189,589 bytes. This is supplied
header evidence, not this change's independently repeated capture or proof of
successful full decoding. No food appearance analysis, label inspection, or
actual corpus decoding was performed to implement this change.

## Rule and source evidence

`../../src/opt_pipeline.py:99–114` uses `Image.open` and `source.convert("RGB")`
regardless of the filename extension, then resizes/thumbnails and copies into a
metadata-free RGB PNG. V3 therefore accepts content-detected PNG or JPEG under
the existing finite member-name scope. It performs no alpha compositing, ICC
color management, EXIF rotation, or identity-stage resizing.

`image-model-input-rgb-u32be-v3` hashes the ASCII algorithm name, one NUL byte,
two unsigned big-endian 32-bit dimensions (width then height), and the exact
row-major bytes of Pillow `convert('RGB')`. Source-byte SHA-256 is independently
retained. RGB equality is independent of source encoding, but depends on the
declared Pillow decoding/conversion behavior and dimensions. Neither v1 nor v2
digests are accepted as v3 graph evidence or relabelled.

The generic `image_fingerprint` accepts single-frame PNG/JPEG. The shared
implementation also backs `png_fingerprint`, whose compatibility interface
continues to reject JPEG. The archive still selects `.png`-named members and
retains basename, member, ZIP CRC, source authentication, and binding checks;
selection by extension does not assert the actual encoding. Local inventory now
registers both PNG and JPEG for ASA using generic v3, with its independent
semantics flag and generic RGB digest retained.

All existing byte/pixel bounds remain: identity at most 8 MiB and 16 × 1024 ×
1024 pixels; local inventory retains its stricter 16,000,000-pixel limit. PNG
verification checks its container/CRC; JPEG uses Pillow verification and full
pixel loading. Corrupt/truncated inputs, GIF, and multiple frames (including
APNG) fail closed. Animation remains outside scope.

## Meaning and offline verification

This identifies exact pre-resize model-input RGB and dimensions, not universal
rendered appearance or physical-plate identity. Alpha/profile/orientation
variants can intentionally join when the model conversion ignores those
properties. A PNG built from decoded JPEG pixels can intentionally join that
JPEG despite different byte hashes; arbitrary JPEG re-encoding is not promised
to preserve pixels.

Synthetic fixtures confirm that JPEG content named `.png` is accepted by the
archive and yields v3. A synthetic decoded-JPEG-to-PNG pair has different byte
hashes, equal v3 hashes, and identical actual `opt_pipeline.encode_image` output
in both modes. Tests retain PNG-only wrapper rejection, v1/v2 graph rejection,
CRC/size/pixel/source checks, truncation, GIF, and APNG failure paths.

Network-disabled validation used `unshare -Urn .venv/bin/python -B -m unittest
discover -s optimization_sol_20261102/mae_v2/round11 -p '<test file>'`: identity
15, archive 12, local inventory 18 tests passed. Synthetic integrations also
passed: ASA phase graph 13, source capture 8, source inventory capture 10 (76
tests total). `git diff --check` passed. These tests do not establish actual
corpus full-decode success. Root review of this JPEG delta precedes any actual
retry; this document grants no additional capture, API, or sampling permission.
