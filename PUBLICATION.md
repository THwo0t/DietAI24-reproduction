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
