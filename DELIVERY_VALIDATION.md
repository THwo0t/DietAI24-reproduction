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
- Actual Linux x86_64 and macOS 26 Apple Silicon (Darwin arm64) execution passed in [GitHub Actions run 40498743097](https://github.com/THwo0t/DietAI24-reproduction/actions/runs/40498743097): fresh bootstrap, 130 tests with 29 explicit full-data skips, release download/hash checks, native index restore and two-image no-key readiness all succeeded.
- Initial push/release checks hit HTTP 404 while the runtime asset was still uploading. The completed-release run above passed. CI now triggers on main-branch pushes and explicit dispatch, avoiding tag/release events during incomplete uploads.
- All three platforms passed in [GitHub Actions run 40499158187](https://github.com/THwo0t/DietAI24-reproduction/actions/runs/40499158187), on functional source commit `c8663c2168a59904153b2b557c335514f219e5c3`: Linux x86_64, macOS 26 Apple Silicon and macOS 15 Intel. Each started from checkout, installed the frozen environment, ran 130 tests (101 passes and 29 explicit full-data skips), downloaded/verified the public runtime, restored 5,624 native vectors and passed the two-development-image no-key check. No paid API request was made.

## Published delivery

- Public repository: [THwo0t/DietAI24-reproduction](https://github.com/THwo0t/DietAI24-reproduction).
- Fixed runtime: [mac-demo-v1](https://github.com/THwo0t/DietAI24-reproduction/releases/tag/mac-demo-v1), 61,363,315 bytes; GitHub's asset digest matches the pinned SHA256 `fe9948149c4bea168481daa09f02cb8a826d70ae682082fba6e0c2d7dc643393`.
- An additional clone downloaded directly from the public GitHub URL passed the offline evidence check and restored its index using the public release URL.
- Documentation-only completion records follow the successful functional CI commit; they do not change source behavior, saved measurements, runtime bytes or scientific report contents.

## Interpretation

No new paid inference was run for packaging. The live path reuses the original, previously exercised API pipeline, with explicit demo guards and separate outputs. Successful dry-run proves imports, files and index readiness; account/model access and an actual new response require the optional user-authorized live demonstration.

The original model availability and prices are historical experiment records. Current availability depends on the receiving account. Native ANN layouts can differ after reconstruction; the demo is not claimed to reproduce historical responses bit for bit. Full-data tests skip explicitly when their raw files are not present in a clean clone.
