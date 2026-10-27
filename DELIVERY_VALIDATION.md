# Demonstration delivery validation

This records delivery checks separately from the formal scientific results. The formal inference source, prompts, parsing, evaluation and archived runs were not changed for this delivery.

## Local checks on 27 October 2026

- Original experiment environment: **130 offline tests passed** (121 existing plus nine delivery checks).
- Archived evidence: 20 hashes verified; own weight MAEs recomputed from CSV; shared Nutrition5k weight MAEs recomputed on 79 identical complete dishes. No API calls.
- Browser: Nutrition5k shared-subset table, ASA24 own-subset switching, saved prediction disclosure, four images and three report routes checked.
- HTTP: explicitly whitelisted routes; `.env`, source code and traversal requests return 404.
- Runtime: 28 files, 20 original development images, 5,624 saved 3,072-dimensional vectors. Export rejects any lossy float32 conversion. Every bundle member and the installed manifest is checksum-verified.
- Native index restoration and live dry-run: PASS, two development rows, 5,624 vectors, zero API calls, no key required.
- A second project-local environment created by `setup.sh offline`: all 130 offline tests passed.
- A genuinely fresh local Git clone, without `.env`, raw data or a virtual environment: bootstrap succeeded; 130 tests completed successfully, with 29 explicit full-data skips and 101 passes. The same clone restored the native index and passed live dry-run without a key or API calls.
- Both Apple Silicon (`aarch64-apple-darwin`) and Intel (`x86_64-apple-darwin`) dependency resolution succeeded for Python 3.10.13, with binary wheels required for chroma-hnswlib and onnxruntime. This is a cross-platform resolution check on Linux, not an actual Mac execution.
- The public snapshot contains no prior local Git objects or raw API/process logs. Its 123 files occupy approximately 3 MB; publication scope and file hashes are explicit.
- Actual macOS GitHub Actions execution remains pending publication authorization. No Mac runtime success is claimed yet.

## Interpretation

No new paid inference was run for packaging. The live path reuses the original, previously exercised API pipeline, with explicit demo guards and separate outputs. Successful dry-run proves imports, files and index readiness; account/model access and an actual new response require the optional user-authorized live demonstration.

The original model availability and prices are historical experiment records. Current availability depends on the receiving account. Native ANN layouts can differ after reconstruction; the demo is not claimed to reproduce historical responses bit for bit. Full-data tests skip explicitly when their raw files are not present in a clean clone.
