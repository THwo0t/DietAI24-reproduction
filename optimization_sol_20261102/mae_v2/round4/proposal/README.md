# Round 4 training-pool proposal only

The actionable private manifest is `private_train_pool_proposal.json`:
**230 RGB images from 230 conservative screening components**, SHA256
`eddf9a644114f5b4aecc4d906dbdec6ee0eaecd80b97e23743d9edf663e03eb0`.
All 230 need download. The cached official object sizes sum to **104,830,902
bytes**. The 5,000,000-byte per-image ceiling gives a 1,150,000,000-byte maximum
successful payload; this is not download authorization or a retry budget.
No image has been downloaded by this proposal.

The requested 600 different groups are unavailable under the required exclusions.
The frozen graph contains 5,006 scans / 2,606 components. Additional proposal-only
closure over identical archived recipe fingerprints and exact local image hashes
produces 823 screening components. Historical exposure, all original dev100,
active dev84, original validation200 including retired rows, current validation200,
and ambiguity anchors exclude 255 whole screening components after closure.
Even before RGB/label eligibility, at most 568 unblocked groups remain. There are
1,191 cached RGB objects in 287 unblocked groups; excluding 188 all-zero-nutrient
records leaves 1,003 eligible images in 230 groups.

The archived available-frame CSV yields only 353 eligible images / 213 groups.
The separately authorized proposal expands the **new training frame** to raw
official RGB records. It requires finite positive total mass, finite nonnegative
four nutrients with at least one positive, and positive ingredient mass. Individual
zero nutrients are valid. The same all-zero nutrient safeguard is preserved.
Original dev/validation eligibility, manifests, folds and hashes are unchanged.

One representative per group is selected using the fixed seed
`dietai24-mae-v2-round4-train600-20261103`; nutrition magnitudes, errors and image
appearance do not rank candidates. The seed retains its original requested target
name; it does not imply 600 selected images. Of the fixed 230 representatives,
56 are outside the archived available-frame CSV.

`summary.json` and the empty `private_train600_proposal.json` document the initial
600-group infeasibility. They are not the actionable download request.
`raw_rgb_summary.json` describes the final 230-image request. `capacity.json`
contains unqualified raw-RGB upper bounds and is not a download manifest.

## Blind integrity boundary

- `audit_pool.py` reuses the frozen component partition. It checks exact original
  snapshot, final snapshot, validation freeze and dev freeze hashes before and
  after auditing. It never calls `prepare()` or imports a cohort loader.
- Raw metadata ingredient names are consumed only to reproduce the original
  sorted-name SHA256. Names and label values are not persisted. The formula is
  cross-checked against all 300 archived recipe hashes.
- Validation target files are never opened. Validation numeric fields in mixed
  raw CSVs are never converted. Numeric qualification occurs only after complete
  excluded-component closure. Synthetic poison tests cover these boundaries.
- Existing image files are decoded only into exact bytes/RGB digests. No display,
  thumbnails, descriptions or learned features are created. The blind audit
  checks 855 image locations representing 543 unique file/RGB digests.
- The scripts run under `unshare -rn`, without network access. The raw proposal
  and coverage scripts also install a Python accidental-read guard for label and
  credential files. This guard is not claimed to be an OS filesystem sandbox.

Private index/manifest files are mode 0600 and locally git-ignored. Only safe
aggregate counts, provenance hashes and source/tests are intended for review.

## Before any training release

Download requires separate current-user authorization for the exact 230-URL
manifest and a total transfer budget. The cached object inventory supplies sizes,
not remote content hashes, and was not revalidated over the network.

After authorized download, a blind integrity step must compare exact bytes/RGB
against all excluded historical/development/validation images and all candidates.
Any duplicate or newly linked candidate must quarantine its affected screening
component before training. Do not automatically replace it with a new URL outside
the authorized manifest. The final training count can be below 230.

Different screening components do not prove different physical plates. Original
time/anchor rules can miss related scans, exact recipe hashes can miss naming
variants, and common recipes can conservatively merge independent plates.

## Post-selection coverage diagnostic

`coverage_diagnostic.json` uses existing dev labels only after the manifest is
fixed and rechecks its exact SHA. It never changes selected images. The proposed
230 images expose 164 positive ingredient IDs. They cover 832/864 dev ingredient
occurrences (96.296%) and 93.931% of dev reference mass, compared with 93.174%
for the original H outer-fold training catalogs. All positive IDs are available
for 60/84 dev dishes. Ingredient availability is not an inference accuracy result.

A separately labeled exploratory union with each query's other dev folds/groups
would cover 857/864 occurrences (99.190%) and 98.919% of reference mass, with
77/84 fully covered dishes. Such a gallery/catalog would require a new protocol;
query fold/group labels must stay outside all catalog densities, examples and
fitted priors. This does not authorize ordinary second-stage calibration using
OOF outputs whose training sources contain an outer holdout.

## Offline reproduction

From the repository root, with the original private sources present:

```sh
unshare -rn .venv/bin/python -B -m unittest discover -s optimization_sol_20261102/mae_v2/round4/proposal -p 'test_*.py' -v
unshare -rn .venv/bin/python -B optimization_sol_20261102/mae_v2/round4/proposal/audit_pool.py
unshare -rn .venv/bin/python -B optimization_sol_20261102/mae_v2/round4/proposal/propose_raw_rgb.py
unshare -rn .venv/bin/python -B optimization_sol_20261102/mae_v2/round4/proposal/diagnose_coverage.py
```

The output writers reject changed existing artifacts. These commands neither
download nor call an API. They cannot reconstruct missing private inputs from
the public source alone.
