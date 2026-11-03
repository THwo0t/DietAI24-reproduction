#!/usr/bin/env python3
"""Train-only adapter for the registered offline gram-prior experiment.

Read the pinned released training metadata and sealed training gallery only.
Never follow the gallery's arbitrary input inventory: it also contains protected
development inputs. Images, mixed source CSVs, provider caches and credentials
are unnecessary. The original release exclusion proof is inherited by hash,
not recomputed here. Default CLI is read-only preflight; --run is explicit.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'src'))
from round4.src.artifacts import ArtifactStore, decode, key_path
from round4.src import pipeline, vision_stages
from round5.src import gram_prior

TRAIN = 'round4/data/train'
GALLERY = 'round4/runs/J_gallery'
OUTPUT = 'round5/runs/train_prior'
PROTOCOL = 'round5/PRIOR_PROTOCOL.md'
PROTOCOL_SHA256 = 'b265e11f2c2878e81036e8699046ed174fe41afb496644ea55b8679167fc558e'
TRAIN_FREEZE_SHA256 = '885f8d1a0573313e9e09771f3c38ec938b807e9ffcc9525d706867d3d0d081cb'
GALLERY_COMPLETION_SHA256 = '57d97d46b9e62a3933af23a1773bf91590b0532a8a99d60ab977ec7908805458'
EXPECTED_N = EXPECTED_GROUPS = 230
TRAIN_FILES = ('manifest.jsonl', 'labels.json', 'ingredients.json', 'catalog.json', 'fallback.json', 'audit.json')
GALLERY_SOURCES = (
    'round4/PROTOCOL.md', 'src/opt_provider.py', 'src/opt_pipeline.py',
    'round4/src/vision_stages.py', 'round4/src/retrieval.py',
    'round4/src/catalog_estimator.py', 'round4/src/pipeline.py',
    'round4/src/artifacts.py', 'round4/src/train_data.py',
    'round4/src/context.py', 'round4/src/run_base.py', 'round4/src/trace_provider.py',
    'round4/src/capability_probe.py', 'round4/src/image_guard.py',
)
RELEASE_SOURCES = ('round4/src/train_data.py', 'round3/src/dev_ingredients.py',
                   'round4/tools/download_train.py', 'round4/TRAINING_DATA_EXCEPTION.md')
PRIOR_SOURCES = (PROTOCOL, 'round5/src/run_train_prior.py', 'round5/src/gram_prior.py')
SHA = re.compile(r'[0-9a-f]{64}\Z')
MANIFEST_KEYS = {'sample_id', 'dataset', 'split', 'group_id', 'original_component_id',
                 'recipe_sha256', 'image_path', 'image_sha256', 'rgb_sha256'}


class LoaderError(ValueError):
    """Fixed safe code, never include training values or paths in errors."""


def require(condition, code):
    if not condition:
        raise LoaderError(code)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


class Inputs:
    """Exact metadata/source allowlist; recorded paths never grant read access."""
    def __init__(self, base):
        self.base = Path(base)
        require(self.base.is_dir() and self.base.resolve() == self.base, 'unsafe_input_root')
        self.allowed = {*GALLERY_SOURCES, *RELEASE_SOURCES, *PRIOR_SOURCES,
                        *(TRAIN + '/' + name for name in (*TRAIN_FILES, 'freeze.json')),
                        GALLERY + '/intent.json', GALLERY + '/completion.json'}
        self.hashes = {}

    def read(self, name, expected=None):
        require(name in self.allowed, 'input_path_not_allowlisted')
        path = self.base / name
        require(path.resolve() == path and not path.is_symlink() and path.is_file()
                and stat.S_ISREG(path.stat().st_mode), 'unsafe_or_missing_input')
        if name.startswith((TRAIN + '/', GALLERY + '/')):
            require(stat.S_IMODE(path.stat().st_mode) == 0o600, 'private_input_required')
        raw = path.read_bytes()
        actual = digest(raw)
        require(expected is None or actual == expected, 'pinned_input_changed')
        require(name not in self.hashes or self.hashes[name] == actual, 'input_changed_during_load')
        self.hashes[name] = actual
        return raw

    def json(self, name, expected=None):
        return decode(self.read(name, expected))

    def unchanged(self):
        for name, expected in list(self.hashes.items()):
            self.read(name, expected)


def _reference_envelope(envelope, validator, role):
    require(isinstance(envelope, dict) and set(envelope) == {'result', 'request_refs'},
            'gallery_stage_envelope_changed')
    result = validator(envelope['result'])
    values = result['raw_outputs'] if role == 'chat' else [result['vector']]
    refs = envelope['request_refs']
    require(isinstance(refs, list) and len(refs) == len(values), 'gallery_reference_count_changed')
    for ref, value in zip(refs, values):
        require(isinstance(ref, dict) and set(ref) == {
            'role', 'request_hash', 'value_hash', 'status', 'cache_present_before'}, 'gallery_reference_fields_changed')
        require(ref['role'] == role and ref['status'] == 'returned'
                and type(ref['cache_present_before']) is bool
                and isinstance(ref['request_hash'], str) and SHA.fullmatch(ref['request_hash'])
                and ref['value_hash'] == pipeline.fingerprint(value), 'gallery_response_reference_changed')
    return {'result': result, 'request_refs': deepcopy(refs)}


def _gallery_vectors(store, manifest, records):
    """Replay existing sealed stages without call closures or image readers."""
    vectors = {}
    expected_stages = set()
    for row in manifest:
        sid = row['sample_id']
        metadata = {'train_id': sid, 'screening_group_id': row['group_id'],
                    'image_sha256': row['image_sha256'], 'rgb_sha256': row['rgb_sha256']}
        require(set(records[sid]) == {'metadata', 'result'} and records[sid]['metadata'] == metadata,
                'gallery_training_association_changed')
        proof = {key: row[key] for key in ('image_sha256', 'rgb_sha256')}
        prefix = 'image-' + pipeline.fingerprint(proof)[:24]
        name = prefix + ':description'
        expected_stages.add(key_path(name))
        intent = store._stage_intent(name, {'method': vision_stages.METHOD_VERSION, 'image': proof})
        description = store._cached('stages/' + key_path(name), intent,
            lambda value: _reference_envelope(value, pipeline.validate_description_result, 'chat'))['result']
        require(description['failure'] is None, 'failed_gallery_description')
        name = prefix + ':embedding'
        expected_stages.add(key_path(name))
        intent = store._stage_intent(name, {'embedding_model': 'text-embedding-3-large',
            'dimensions': 3072, 'embedding_text': description['embedding_text']})
        embedding = store._cached('stages/' + key_path(name), intent,
            lambda value: _reference_envelope(value, pipeline.validate_embedding_result, 'embedding'))['result']
        require(records[sid]['result'] == {'description': description, 'embedding': embedding,
            'repair_used': description['repair_used'], 'failure': None}, 'gallery_final_record_replay_changed')
        vectors[sid] = embedding['vector']
    require({path.name for path in store._path('stages').iterdir()} == expected_stages,
            'gallery_stage_inventory_changed')
    return vectors


def load_training(base=ROOT):
    """Return only explicit pure-model inputs plus their reproducibility binding.

    This checks the pinned metadata projection and original gallery seal, not a
    fresh image/download/recipe audit. No global catalogue is passed to fitting.
    """
    reader = Inputs(base)
    reader.read(PROTOCOL, PROTOCOL_SHA256)
    freeze = reader.json(TRAIN + '/freeze.json', TRAIN_FREEZE_SHA256)
    require(freeze.get('schema_version') == 1 and freeze.get('status') == 'accepted_external_training_frozen'
            and freeze.get('accepted_images') == EXPECTED_N
            and freeze.get('accepted_groups') == EXPECTED_GROUPS, 'registered_training_population_changed')
    release_binding = freeze['binding']
    require(set(release_binding['source_sha256']) == set(RELEASE_SOURCES), 'release_source_inventory_changed')
    for name in RELEASE_SOURCES:
        reader.read(name, release_binding['source_sha256'][name])
    artifacts = freeze['artifacts']
    require(set(TRAIN_FILES).issubset(artifacts) and all(
        name in TRAIN_FILES or re.fullmatch(r'images/[0-9a-f]{64}\.png', name) for name in artifacts),
        'training_artifact_inventory_changed')
    payloads = {name: reader.read(TRAIN + '/' + name, artifacts[name]) for name in TRAIN_FILES}
    manifest = [decode(line) for line in payloads['manifest.jsonl'].splitlines()]
    require(len(manifest) == EXPECTED_N and all(set(row) == MANIFEST_KEYS for row in manifest),
            'training_manifest_fields_changed')
    ids = {row['sample_id'] for row in manifest}
    require(len(ids) == EXPECTED_N and len({row['group_id'] for row in manifest}) == EXPECTED_GROUPS,
            'training_id_or_group_population_changed')
    for row in manifest:
        require(row['dataset'] == 'nutrition5k' and row['split'] == 'train'
                and row['image_path'] == TRAIN + '/images/' + row['image_sha256'] + '.png'
                and all(isinstance(row[k], str) and SHA.fullmatch(row[k])
                        for k in ('image_sha256', 'rgb_sha256', 'recipe_sha256'))
                and artifacts.get('images/' + row['image_sha256'] + '.png') == row['image_sha256'],
                'training_image_association_changed')
    require(len({r['image_sha256'] for r in manifest}) == EXPECTED_N
            and len({r['rgb_sha256'] for r in manifest}) == EXPECTED_N, 'duplicate_training_image_proof')
    require(set(artifacts) == set(TRAIN_FILES) | {'images/' + r['image_sha256'] + '.png' for r in manifest},
            'training_artifact_population_changed')

    reader.read(GALLERY + '/completion.json', GALLERY_COMPLETION_SHA256)
    intent = reader.json(GALLERY + '/intent.json')
    binding = intent['binding']
    require(binding.get('schema_version') == 1 and binding.get('phase') == 'gallery'
            and binding.get('training_freeze_sha256') == TRAIN_FREEZE_SHA256
            and binding.get('training_exclusion_binding') == release_binding, 'gallery_training_binding_changed')
    gallery_inputs = binding['input_sha256']
    for name in GALLERY_SOURCES:
        reader.read(name, gallery_inputs[name])
    for name in ('freeze.json', 'manifest.jsonl', 'ingredients.json', 'catalog.json', 'fallback.json'):
        require(gallery_inputs.get(TRAIN + '/' + name) == reader.hashes[TRAIN + '/' + name],
                'gallery_training_input_changed')
    for name in PRIOR_SOURCES:
        reader.read(name)
    store = ArtifactStore(Path(base) / GALLERY, binding, ids,
                          verify_sources=reader.unchanged, root=Path(base) / 'round4')
    records = store.verify_completed()
    vectors = _gallery_vectors(store, manifest, records)
    require(store.verify_completed() == records, 'gallery_changed_during_replay')

    # Release hashes bind the original values, including the registered 2 g
    # source discrepancy. Projection drops names/global densities, not masses.
    label_rows = decode(payloads['labels.json'])
    ingredient_file = decode(payloads['ingredients.json'])
    ingredient_rows = ingredient_file['records']
    require(ingredient_file['schema_version'] == 1
            and ingredient_file['scope'] == 'accepted_external_training_only_private'
            and len(ingredient_rows) == EXPECTED_N
            and set(label_rows) == ids and {r['sample_id'] for r in ingredient_rows} == ids,
            'training_label_population_changed')
    groups = {row['sample_id']: row['group_id'] for row in manifest}
    ingredients, targets = {}, {}
    for row in ingredient_rows:
        sid = row['sample_id']
        require(row['split'] == 'train' and row['group_id'] == groups[sid], 'ingredient_training_association_changed')
        ingredients[sid] = [{k: item[k] for k in ('ingredient_id', 'grams', 'nutrients')}
                            for item in row['ingredients']]
        require(set(label_rows[sid]) == {'truth'}, 'training_target_fields_changed')
        targets[sid] = deepcopy(label_rows[sid]['truth'])
        gram_prior._ingredients(ingredients[sid])
        gram_prior._targets(targets[sid])
    reader.unchanged()
    return {'rows': [{'sample_id': sid, 'group_id': groups[sid]} for sid in sorted(ids)],
            'vectors_by_id': vectors, 'ingredient_records': ingredients, 'official_targets': targets,
            'binding': {'schema_version': 1, 'scope': 'external_training_only',
                        'training_freeze_sha256': TRAIN_FREEZE_SHA256,
                        'gallery_completion_sha256': GALLERY_COMPLETION_SHA256,
                        'input_sha256': dict(reader.hashes),
                        'data_quality_exception_count': freeze['data_quality_exception_count'],
                        'image_bytes_opened': False, 'development_opened': False,
                        'validation_opened': False, 'provider_constructed': False},
            'reader': reader}


def run(*, execute=False, base=ROOT):
    data = load_training(base)
    summary = {'status': 'training_prior_inputs_verified', 'n': len(data['rows']),
               'groups': len({r['group_id'] for r in data['rows']}), 'api_calls': 0,
               'image_bytes_opened': False, 'development_opened': False, 'validation_opened': False,
               'training_freeze_sha256': TRAIN_FREEZE_SHA256,
               'gallery_completion_sha256': GALLERY_COMPLETION_SHA256}
    if not execute:
        return summary
    store = ArtifactStore(Path(base) / OUTPUT, data['binding'],
        ['aggregate', 'oof_predictions', 'fold_audit', 'group_folds'],
        verify_sources=data['reader'].unchanged, root=Path(base) / 'round5')
    if store._path('completion.json').exists():
        results = store.verify_completed()
    else:
        # Publish exact protocol/source/input binding before any real fit. A
        # failed experiment retains this intent; a resume cannot replace it.
        store.initialize()
        results = gram_prior.evaluate_oof(*(data[key] for key in (
            'rows', 'vectors_by_id', 'ingredient_records', 'official_targets')),
            expected_n=EXPECTED_N, expected_groups=EXPECTED_GROUPS)
        data['reader'].unchanged()
        store.finalize(results)
    return {**summary, 'status': 'training_prior_oof_complete', 'aggregate': results['aggregate']}


def main(argv=None):
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', action='store_true', help='Execute the fixed train-only OOF; default is preflight.')
    args = parser.parse_args(argv)
    print(json.dumps(run(execute=args.run), sort_keys=True, allow_nan=False))


if __name__ == '__main__':
    main()
