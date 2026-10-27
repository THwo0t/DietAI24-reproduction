# DietAI24 reproduction and model comparison

An auditable reproduction of **DietAI24**, Communications Medicine 5, 458 (2025), [doi:10.1038/s43856-025-01159-0](https://doi.org/10.1038/s43856-025-01159-0), starting from the [authors' released code](https://github.com/Runz96/DietAI24), local baseline `5946365`.

GPT-4 Turbo was unavailable on 27 October 2026. The primary experiment used `gpt-4o-2024-08-06`; the supplementary comparison used `gpt-6.1-sol` with its necessary supported settings. Each configuration was formally tested once on the same 150 ASA24 records and 150 Nutrition5k dishes. This is a reconstruction with documented departures.

| Main finding | GPT-4o | Sol |
|---|---:|---:|
| ASA24 Exact coverage, out of 150 | 21 | 11 |
| Nutrition5k complete dishes, out of 150 | 86 | 118 |
| Shared Nutrition5k weight MAE, 79 dishes | 96.01 g | 62.24 g |
| Shared Nutrition5k energy MAE, same 79 dishes | 126.86 kcal | 131.83 kcal |

Weight underestimation improved on the shared subset; nutrient accuracy and exact identification did not consistently improve. Read the English [report](REPORT.md), [PDF](output/report/REPORT.pdf) or [Word](output/report/REPORT.docx) for denominators, paired intervals and limitations.

## Demonstrate on Mac

**给 Mac 上的 Codex：先读 [START_HERE_MAC.md](START_HERE_MAC.md)，按步骤安装、验证并打开演示。**

```sh
git clone https://github.com/THwo0t/DietAI24-reproduction.git
cd DietAI24-reproduction
./setup.sh offline
.venv-demo/bin/python tools/demo.py --open
```

Open `http://127.0.0.1:8765`. The page displays archived measurements and four saved examples, supports dataset/subset switching, and links to the three report formats. It makes **zero API requests** and needs no key, raw datasets or index. After the initial dependency installation, presentation works without internet access.

Setup installs checksum-pinned uv 0.9.6 and Python 3.10.13 locally, and synchronizes `env/pip-freeze.txt` into `.venv-demo`. No Homebrew, sudo or shell-profile changes are required. Apple Silicon and Intel Mac are supported by the installer; consult actual CI results for tested architectures.

## Optional new inference on two development images

```sh
./setup.sh live
# If absent, copy .env.example to .env and fill OPENAI_API_KEY locally.
.venv-demo/bin/python tools/live_demo.py --dry-run
.venv-demo/bin/python tools/live_demo.py --allow-paid --max-usd 0.50
```

Live setup fetches the pinned ~59 MiB [runtime release](https://github.com/THwo0t/DietAI24-reproduction/releases/tag/mac-demo-v1), validates all hashes, and builds a native Chroma index from the **same 5,624 saved embeddings**, without a paid embedding rebuild. The bundle includes required FNDDS tables, mappings and the existing 10 + 10 development images. It excludes credentials, virtual environments, full raw datasets and the Linux binary index. Native approximate-neighbor layouts can differ across platforms.

The wrapper calls the original inference, portion, nutrient and evaluation code on the first development image of each dataset. Results go to a new `demo-runs/<timestamp>-<id>/`; formal results are never overwritten or resumed. Recognition/portion failures remain failures. This small demo is not a new estimate of the paper's MAE.

The default live model is the historical GPT-4o configuration; use `--model gpt-6.1-sol` for Sol. Account availability is required; there is no silent fallback. Demo SDK retries are reduced to one, request timeout is 45 seconds, and at most 80 HTTP requests are allowed. `--max-usd` stops between requests using returned token usage and historical prices: **one in-flight request can exceed this threshold; it is not a billing hard cap**. No live request is made without `--allow-paid`.

## Verify

```sh
.venv-demo/bin/python tools/demo.py --check
.venv-demo/bin/python -m unittest discover -s tests -v
# After live setup:
.venv-demo/bin/python tools/runtime_bundle.py verify
.venv-demo/bin/python tools/live_demo.py --dry-run
```

The offline check verifies evidence hashes and independently recomputes own/shared weight MAEs from saved CSVs. Tests needing complete original raw data explicitly skip when absent; the historical full-data record remains in `REVIEW.md`. CI validates clean checkouts on Linux and macOS, without keys or paid calls. Check [Actions](https://github.com/THwo0t/DietAI24-reproduction/actions) for actual architecture and outcomes.

## Records and attribution

- `code/`: original and reconstructed pipeline. ViT and commercial baselines are outside this reproduction's setup.
- `runs/test/`, `runs/test-gpt-6.1-sol/`: immutable formal outputs, metrics, usage and diagnostics.
- `runs/comparison-gpt-4o-vs-sol/`: all own/shared estimates and paired intervals.
- [CHECKLIST.md](CHECKLIST.md), [REVIEW.md](REVIEW.md): decisions, paper references and independent reviews.
- [MAC_DEMO.md](MAC_DEMO.md): operation and recovery; [THIRD_PARTY.md](THIRD_PARTY.md): sources and data terms.

`HANDOFF_CODEX.md` is historical: its proposed comparison is complete. Do not rerun the formal tests. `code/place_inputs.py` is the original local-copy helper with historical absolute paths; Mac setup uses the new clone-relative entry points.

The upstream README states MIT but its repository has no standalone LICENSE file. [UPSTREAM_README.md](UPSTREAM_README.md) preserves that notice. Third-party datasets retain separate terms; this repository does not invent license grants for them.

