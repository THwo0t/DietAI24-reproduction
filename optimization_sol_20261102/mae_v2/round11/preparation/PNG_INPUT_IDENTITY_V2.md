# Prospective PNG model-input identity v2

This rule is registered before any new actual source capture. The prior capture
stopped without a new artifact at `unsupported_png_rendering_semantics`. The
reported metadata-only cause was a single-frame RGBA PNG, 160 × 160, alpha extrema
0–182, no ICC profile, normal EXIF orientation. This records a decoder coverage
failure, not an inference result or MAE observation. No source photograph or
label is inspected by this change.

## Source evidence and rule

`../../src/opt_pipeline.py:99–114` implements `encode_image`: open with Pillow,
`source.convert("RGB")`, then resize/thumbnail, copy pixels into a clean RGB
image, and encode PNG. It performs no alpha compositing, ICC color management,
or EXIF rotation. The exact prospective pre-resize identity follows that
conversion, including Pillow-supported RGBA, LA and palette transparency.

The registered algorithm is `png-model-input-rgb-u32be-v2`. Its SHA-256 payload is
ASCII algorithm name, one NUL byte, width and height as two unsigned 32-bit
big-endian integers, then row-major bytes from `image.convert('RGB')`. Retain the
independent original-byte SHA-256. No resizing is performed by this identity.
Existing v1 digests are not accepted as v2 evidence and must not be relabelled.
The prior pinned DESIGN remains unchanged.

Only bounded PNG byte streams (at most 8 MiB and 16 × 1024 × 1024 pixels) are
accepted. Pillow verifies the PNG container/CRC before a fresh open converts and
loads pixels. Corrupt/non-PNG input and multiple frames fail closed; animation is
outside scope. Local inventory retains its existing stricter 16,000,000-pixel
bound and also rejects animation. Its generic RGB digest remains distinct; PNG
ASA compatibility now uses v2 even when its retained semantics flag is true.
JPEG remains outside ASA compatibility.

## Interpretation and verification

This is conservative exact equality of pre-resize model-input RGB and dimensions.
It is neither universal rendered-appearance equivalence nor physical-plate
identity. Alpha, profile, and orientation differences can intentionally join
because the model encoder ignores them. Different dimensions or pixel ordering
do not join even when downstream resizing could obscure those differences.

Synthetic temporary PNG fixtures compare v2 equality against actual
`opt_pipeline.encode_image` output in both supported modes for differing alpha,
LA alpha, ICC, EXIF orientation, and palette transparency. They assert differing
source-byte hashes, equal RGB hashes, and the exact versioned digest payload.
Additional offline tests cover dimensions, permutations, CRC/corruption, bounds,
non-PNG rejection, animation rejection, and old-version graph refusal. These
checks open no actual source images or labels and make no API calls.

Validation (network namespace disabled): 14 `test_asa_content_identity` tests and
17 `test_local_content_inventory` tests passed using `unshare -Urn .venv/bin/python
-B -m unittest discover -s optimization_sol_20261102/mae_v2/round11 -p '<test file>'`.
The decoder delta requires one root review before any new actual capture; this
registration grants no capture, inference, sampling, or source-completeness claim.
