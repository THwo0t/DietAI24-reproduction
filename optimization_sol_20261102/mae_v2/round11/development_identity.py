"""Fixed development identity projection, without labels, images or action grants.

Authenticates the existing seal and manifest only. Image and label hashes are
recorded bindings, not verification of current protected file contents. This
reader proves neither source completeness nor exposure isolation. No CLI exists.
"""
from copy import deepcopy
import hashlib
from pathlib import Path

from n5_sources import PREFIX, PATHS, ANCHORS, decode, require, HEX
from source_census import bounded_read

REPO = Path(__file__).resolve().parents[3]
MANIFEST = PREFIX + 'data/cohorts/dev.jsonl'
SEAL = PATHS['development_seal']
FIELDS = {'sample_id','dataset','split','group_id','fold','image_path','image_sha256'}
SEED = 'dietai24-mae-v2-20261102'


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


class _BoundDevelopment:
    def __init__(self, repo, anchor):
        self.repo = Path(repo)
        require(self.repo.is_absolute() and self.repo.resolve() == self.repo,
                'canonical_development_root_required')
        require(isinstance(anchor, str) and HEX.fullmatch(anchor), 'development_anchor_required')
        self.hashes = {SEAL: anchor}

    def read(self, relative):
        require(relative in (SEAL, MANIFEST), 'fixed_development_identity_path_required')
        raw = bounded_read(self.repo, relative)
        require(_sha(raw) == self.hashes[relative], 'development_identity_hash_changed')
        return raw

    def revalidate(self):
        require(set(self.hashes) == {SEAL, MANIFEST}, 'complete_development_binding_required')
        for relative in self.hashes:
            self.read(relative)


def load_development_identity():
    """Return (projection, bound reader) at the fixed repository and seal anchor.

    Projection keys are n5_core (the exact _core_rows input contract), asa_rows
    (the seven original identity fields), and source_hashes (seal/manifest only).
    Call reader.revalidate() again immediately before consuming a held projection.
    """
    return _load_development_identity(REPO, ANCHORS['development_seal'])


def _load_development_identity(repo, anchor):
    """Private synthetic-fixture hook; never exposed as a production option."""
    reader = _BoundDevelopment(repo, anchor)
    seal = decode(reader.read(SEAL))
    require(isinstance(seal, dict) and isinstance(seal.get('artifacts'), dict),
            'development_artifacts_required')
    artifacts = seal['artifacts']
    manifest_hash = artifacts.get('data/cohorts/dev.jsonl')
    labels_hash = artifacts.get('data/cohorts/dev_labels.json')
    require(all(isinstance(v, str) and HEX.fullmatch(v) for v in (manifest_hash, labels_hash)),
            'development_manifest_and_labels_hash_required')
    reader.hashes[MANIFEST] = manifest_hash
    lines = reader.read(MANIFEST).splitlines()
    require(len(lines) == 183 and all(lines), 'exact_development_population_required')
    rows = [decode(line) for line in lines]
    seen = set(); images = set(); parts = {'asa24': [], 'nutrition5k': []}
    for row in rows:
        require(isinstance(row, dict) and set(row) == FIELDS, 'identity_only_development_row_required')
        dataset = row['dataset']; sample = row['sample_id']
        require(isinstance(dataset, str) and dataset in parts and isinstance(sample, str)
                and sample.startswith(dataset + '-') and len(sample) > len(dataset) + 1
                and sample not in seen, 'unique_development_sample_required')
        require(row['split'] == 'dev' and type(row['fold']) is int and row['fold'] in range(5)
                and isinstance(row['group_id'], str) and bool(row['group_id']),
                'original_development_binding_required')
        name = _sha((SEED + '|sample|' + sample).encode()) + '.png'
        expected = 'data/' + dataset + '/dev/images/' + name
        require(row['image_path'] == expected and expected not in images,
                'fixed_development_image_path_required')
        image_hash = row['image_sha256']
        require(isinstance(image_hash, str) and HEX.fullmatch(image_hash)
                and artifacts.get(expected) == image_hash, 'development_image_binding_changed')
        seen.add(sample); images.add(expected); parts[dataset].append(deepcopy(row))
    require(len(parts['asa24']) == 99 and len(parts['nutrition5k']) == 84,
            'exact_development_dataset_counts_required')
    reader.revalidate()
    return {'n5_core': {'rows': parts['nutrition5k'], 'labels_sha256': labels_hash},
            'asa_rows': parts['asa24'], 'source_hashes': deepcopy(reader.hashes)}, reader
