# MAE v2 portable demonstration

The offline page displays the saved `reports/DietAI24_MAE_v2_Report.{md,json,pdf,docx}` and two previously authorized historical images. It opens neither development nor sealed validation cohorts, reads no credential file, and submits zero model requests. Final reports and `reports/demo_profile.json` must be present: an unfinished research checkout returns `INCOMPLETE` instead of inventing results.

The complete candidate includes the saved food catalog and 5,624 × 3,072 embedding vectors. The source candidate has an accompanying local runtime archive and a fixed checksum descriptor. There is no v2 public download URL yet. The runtime installer accepts a local ZIP only, verifies the archive and per-file checksums, and refuses unexpected members, symlinks, changed existing files, or a profile mismatch. It does not rebuild a native index or embed the corpus.

## Environment and offline display

```bash
bash setup.sh offline
.venv-demo/bin/python tools/demo.py --check
.venv-demo/bin/python tools/demo.py --serve --open
```

Setup pins uv 0.9.6, Python 3.10.13 and every package in `requirements-demo.txt`. First installation downloads environment dependencies. All installations and caches stay under this directory. Reuse of a local parent uv binary is optional; the distributed package does not depend on the original workspace. Supported installation targets are Apple Silicon Mac, Intel Mac and Linux x86_64. Actual execution on Mac is **not verified** for this v2 delivery.

The local HTTP server binds only `127.0.0.1`, serves an explicit report/image allowlist, and exposes no directory listing. `--check --require-runtime` also validates saved vector and catalog hashes. Neither mode reads `.env`.

## Explicitly authorized two-image live demo

This is a new paid demonstration, not a replay of either experiment or its accuracy. It uses only `tools/demo_images/asa24.png` and `nutrition5k.png`, whose fixed hashes are validated. No new development/validation images, labels or example bank are distributed.

After current authorization, create a local credential file yourself:

```bash
cp tools/env.example .env
chmod 600 .env
# Fill the two distinct credentials locally; never paste them into logs or chat.
.venv-demo/bin/python tools/demo.py --live
.venv-demo/bin/python tools/demo.py --live --allow-paid
```

The first command performs readiness checks with zero API requests and no credential reads. The second requires distinct chat and embedding keys in **this directory's** `.env`, mode 0600. It never searches the parent workspace for credentials. Chat/vision use `gpt-6.1-sol` through `https://api.zicc.cc/v1`; query embeddings use the official `https://api.openai.com/v1`. These routes and model names must match the template. Credentials must never be committed or put in an archive.

The final public profile binds the chosen per-dataset configuration, fitted mass factor/fallback, inference source hashes and runtime hashes. Nutrition5k A/B/C executes the chosen component method and inherited crop/portion configuration. D adds semantic code review to its selected A/B/C base; E adds standard-unit portions to its selected base. D and E are not composed. The fitted Nutrition5k mass factor is applied once to leaves, preserving nutrient densities and reaggregating the dish.

ASA24 live inference is **image-only E2E**: it supplies no true food code and no reference label. The report's primary ASA24 result is Exact-conditioned and uses its explicitly registered legal-option condition. Its conditional calibration and accuracy are therefore not reproduced by this live demo. If the selected legacy Nutrition5k winner used two development examples, the compact demo disables those examples because the private bank is omitted. Output explicitly records that method deviation; it makes no claim to reproduce the winner's reported accuracy.

Live output stays in a new local `runs/demo/` folder with sanitized provider usage. API costs depend on responses and any bounded retries. There is no automatic formal validation, publishing, upload, or image substitution. Inspect sanitized local usage after a stopped attempt; do not casually rerun paid commands.

## Candidate packaging and research sources

Maintainers use the finalization helper after development completes. Its default is read-only. It requires a complete registered candidate inventory, idle research jobs, the exact recorded selection, unchanged source/configuration/runtime bindings, and sealed development records. It loads the selected saved calibration parameters and verifies them with a deterministic development-only refit; a winner without calibration uses the existing development-only fallback fit. It makes no API calls, reads no credentials or validation targets, and never changes research records.

```bash
python -B tools/finalize_demo_profile.py
# Only after the readiness check passes and final report status is settled:
python -B tools/finalize_demo_profile.py --write
```

The writer calls `tools/demo.py:make_demo_profile` to project only dataset, mass factor, enabled flag, and the five-target fallback, omitting training IDs and binding all portable inference/runtime hashes. Optional validation status comes only from bound frozen-method and batch/completion metadata; it does not read validation scores, rows, labels or images. The fixed output is `reports/demo_profile.json`: identical content is verified, and different existing content is never replaced. Finalize it when the intended validation status is settled, since a later status change would require a different artifact. Keep the safe command summary with the local evidence: it records completion, selection and source input hashes without row identities.

```bash
python tools/package_demo.py --check --kind complete
python tools/package_demo.py --build /absolute/new/candidate-directory --kind complete
```

The builder requires final report files, the public profile, aggregate diagnostics and the explicit source inventory. It scans allowlisted content for credential patterns and row-level research fields/identities. PDF inspection uses a local `pdftotext` executable; DOCX XML is inspected internally. The scanner does not open `.env` or compare live credential values; it is a conservative generic check, not a proof that arbitrary prose cannot contain a secret. The manifest records every member's SHA-256 and length plus the final archive hash. Reusing output archive names fails rather than replacing an earlier candidate.

Included research source and tests document the full method. Private data, v1 archives, provider caches and row-level results are excluded, so the research preparation/development/validation commands cannot run from this package alone. The research README/protocol remain authoritative for those inputs. Document authoring tests additionally require the author's Codex document runtime (`python-docx`, PDF tools and fonts), outside the fixed inference environment. Run the portable demo checks independently; full test discovery is not a Mac setup requirement.

Candidate creation does not mean independent review or publication has passed. The package manifest uses `review_status: see_review_ledger`; the builder does not infer approval from the current ledger. It also records `publication_status: not_published_by_this_tool`. Linux clean-directory tests, synthetic/mock provider tests, and actual Mac or paid runs are distinct evidence and must be reported separately. No v2 actual Mac execution or paid demo execution is claimed by these files.

## Offline implementation evidence

On 2026-11-02, 19 focused tests passed in an isolated network namespace with the existing fixed Python 3.10.13 environment. They cover private-file read guards, no-key dry-run, local-only credentials and permissions, report/path allowlists, in-memory HTTP handling, tampering, A–E dispatch, ASA `label=None`, disabled examples, source inventory, credential scanning, ZIP manifests, runtime import, and clean extraction. A real loopback socket was unavailable in the sandbox; the HTTP handler used an in-memory transport.

The original clean-directory rehearsal used real saved catalog/vectors and the then-current 13 source files/13 test files, with **synthetic reports/profile**. The current explicit inventory contains 14 source files and 16 test files, plus the standalone tools; the packager rejects any unlisted new source or test file. The rehearsal verifies the actual 5,624 × 3,072 NumPy shape, pinned dependencies, offline display checks and no-key live readiness. A Python read guard rejects any credential/cohort/sealed reads, including a synthetic parent `.env`. By default, setup runs with uv installation operations mocked and the already installed fixed interpreter reused. No dependencies are downloaded in that mode, no formal candidate is retained, and no final report/selection is fabricated.

```bash
# Run from this root using the existing fixed environment, not a new installation:
python -B -m unittest discover -s tests -p 'test_demo_v2.py' -v
python -B tools/check_clean_demo.py
```

The development-host executions also used `unshare -rn` to disable external networking. macOS does not provide this Linux command; it is test isolation evidence, not part of Mac setup.

Separate **real installation acceptance on Linux** passed on 2026-11-02. The following mode actually downloaded uv 0.9.6 and managed Python 3.10.13, then resolved and installed all 19 pinned packages into a new virtual environment. It reused neither the original interpreter nor its venv. The installed interpreter's prefix and base prefix were checked inside the temporary demo root. Subsequent runtime checks, no-key live readiness, and ten presentation tests ran in a disabled network namespace. The separate combined portable/presentation suite then had 29 passing tests.

```bash
# Authorized environment downloads; no model calls or .env reads:
python -B tools/check_clean_demo.py --real-install
# A repeat must use a new evidence name; previous evidence is immutable:
python -B tools/check_clean_demo.py --real-install --evidence evidence/M2-9_real_install_repeat.json
```

All installer work, caches and the new environment stay under this v2 directory. On completion, only this invocation's temporary directory is deleted. The development worktree retains `evidence/M2-9_real_install.json` with exact installed versions, input hashes and checks, plus the scanned setup log. These local installation evidence files are outside the public package allowlist. Dependency installation is real; reports/profile remain test fixtures. This result does not establish actual Mac execution, final report QA, or acceptance of the eventual exact publication archive.

## Checking the eventual exact complete archive

After reports, profile and review records are final, build the complete candidate and use its independently recorded `archive_sha256` from the builder summary or sidecar manifest. Run this command from the v2 research checkout with the existing fixed Python 3.10.13 environment:

```bash
unshare -rn python -B tools/check_clean_demo.py \
  --candidate /absolute/candidate-directory/mae-v2-complete.zip \
  --expected-sha256 REPLACE_WITH_THE_RECORDED_64_HEX_DIGEST \
  --evidence evidence/M2-9_exact_candidate_check.json
```

This Linux-only mode checks the actual ZIP, not a fixture reconstruction. It binds the supplied archive digest, exact complete-member allowlist, manifest schema, per-file sizes and hashes; rejects unexpected members, duplicates, symlinks, nonregular files and excessive expansion; and scans the same payload bytes that it extracts. Reports and profile are copied byte-for-byte from the archive, with no replacement. The dependency list must match the trusted runner's 19 fixed pins, and the existing interpreter and NumPy vector shape are checked directly. It does not run setup or install dependencies.

The command above isolates the entire checker, including the PDF content scanner. Every Python check process additionally runs under `unshare -rn`; failure stops the check with no unisolated fallback. A sanitized environment and Python audit/read guards reject credential/cohort access, sockets and child subprocesses. Guard probes verify those checks before the package's `--check --require-runtime` and no-key `--live` commands. These are regression safeguards, not an OS filesystem sandbox for untrusted programs. The checker verifies that the extracted tree gained no files, directories or symlinks and that all original member hashes and the input archive digest remain unchanged. Only its own temporary directory is deleted.

The safe JSON evidence records the exact archive/manifest hashes, counts, checks and installed versions. It is immutable; a repeat requires a new evidence filename. This mode establishes an offline check of that particular artifact with an existing environment. It does not establish a fresh installation, report-content correctness, independent-review approval, publication or actual Mac execution. The checker itself is tested using clearly synthetic archive fixtures; those unit tests do not constitute acceptance of the final research report archive.
