# Public delivery scope

The public repository is a clean source snapshot of this reproduction. It does **not** publish the original local Git history, raw API response ledgers, process logs, console transcripts, old development-run outputs, credentials, virtual environments, full raw datasets or machine-specific binary indices.

Included content is explicitly listed with SHA256 hashes in `PUBLICATION_MANIFEST.json` when the public snapshot is exported:

- Current experiment source, frozen dependency specifications, offline tests and Mac setup/demo tools.
- The English report in Markdown, Word and PDF; implementation/review decisions and source attribution.
- Formal-run prediction/nutrition CSVs, metric/configuration/cost JSON and offline analysis outputs needed to explain the saved results. Response-level API logs and process/console logs are excluded.
- Four clearly identified image previews from public ASA24 and Nutrition5k datasets, with attribution.
- A separate fixed release asset containing 20 public development images, prepared FNDDS/portion mappings and the original saved numeric embeddings: approximately 59 MiB, exact member/asset checksums recorded.

The original local research archive remains intact. Historical commit identifiers in the report and reviews refer to that archive; those historical Git objects are not part of the new public repository. The paper's original upstream code remains linked in README and THIRD_PARTY.

Full raw-download regeneration and response-level ledger reconciliation require the original archive and source datasets. Public offline presentation and the optional two-development-image demo are the supported clean-clone acceptance targets.

## Authorized C/Sol backup, 2026-11-04

The user explicitly authorized backing up the completed C-derived Sol source and results on branch `codex/c-repro-sol-backup-20261104`. The scoped archive is `research_backups/c_repro_sol_20261104/`; its own `BACKUP_MANIFEST.json` lists file hashes, original hashes and export transformations. This adds 28 exact Python source files, experiment configuration and aggregate results, plus parsed predictions for all 843 development images and their corrections. Raw model-response subtrees are omitted from the prediction exports. No images, reference-label files, response ledgers, process logs, credentials, vector/index caches or independent acceptance data are added. This is a source/results backup, not a complete runnable data package or an independently accepted result. Historical manifests and run-time no-upload flags remain unchanged as provenance.
