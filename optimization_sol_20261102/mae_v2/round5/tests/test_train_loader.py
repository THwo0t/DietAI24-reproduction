"""Synthetic-only seal, source and train-only access tests; no real inputs."""
from contextlib import ExitStack
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import stat
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'src'))
from round4.src.artifacts import ArtifactStore, ArtifactError, canonical
from round5.src import run_train_prior as loader


def write(base, name, value, raw=False):
    path = base / name
    path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    data = value if raw else canonical(value)
    path.write_bytes(data)
    path.chmod(0o600)
    return hashlib.sha256(data).hexdigest()


class Fixture:
    def __init__(self, base, *, missing_label=False, wrong_group=False,
                 wrong_record=False, wrong_stage=False, bad_ref=False,
                 invalid_vector=False, extra_label=False):
        self.base = base
        for name in set(loader.GALLERY_SOURCES + loader.RELEASE_SOURCES + loader.PRIOR_SOURCES):
            write(base, name, ('synthetic source ' + name).encode(), raw=True)
        rows, labels, ingredients = [], {}, []
        for i in range(5):
            sid, group = 'train' + str(i), 'group' + str(i)
            image, pixels, recipe = [hashlib.sha256((kind + str(i)).encode()).hexdigest()
                                      for kind in ('bytes', 'pixels', 'recipe')]
            rows.append({'sample_id': sid, 'group_id': group, 'dataset': 'nutrition5k', 'split': 'train',
                         'original_component_id': group, 'recipe_sha256': recipe,
                         'image_path': loader.TRAIN + '/images/' + image + '.png',
                         'image_sha256': image, 'rgb_sha256': pixels})
            nutrients = {k: 2.0 + i for k in ('energy', 'fat', 'carbs', 'protein')}
            labels[sid] = {'truth': {'weight': float(8 + i if i == 0 else 10 + i), **nutrients}}
            ingredients.append({'sample_id': sid, 'group_id': group, 'dish_id': 'dish' + str(i), 'split': 'train',
                                'ingredients': [{'ingredient_id': 'food' + str(i % 2), 'grams': float(10 + i),
                                    'nutrients': nutrients, 'name': 'synthetic food',
                                    'density_per_100g': {k: 100 * v / (10 + i) for k, v in nutrients.items()}}]})
        if missing_label:
            labels.pop('train0')
        if extra_label:
            labels['protected-extra'] = deepcopy(labels['train1'])
        if wrong_group:
            ingredients[0]['group_id'] = 'wrong'
        source_hashes = {name: loader.digest((base / name).read_bytes()) for name in loader.RELEASE_SOURCES}
        artifacts = {'manifest.jsonl': write(base, loader.TRAIN + '/manifest.jsonl',
                     b''.join(canonical(r) for r in rows), raw=True)}
        objects = {'labels.json': labels,
                   'ingredients.json': {'schema_version': 1, 'scope': 'accepted_external_training_only_private',
                                        'source_sha256': {}, 'records': ingredients},
                   'catalog.json': {'ingredients': [{'global_only': 'must never enter fitting'}]},
                   'fallback.json': {'prediction': labels['train1']['truth']}, 'audit.json': {'fixture': True}}
        for name, value in objects.items():
            artifacts[name] = write(base, loader.TRAIN + '/' + name, value)
        artifacts.update({'images/' + r['image_sha256'] + '.png': r['image_sha256'] for r in rows})
        freeze = {'schema_version': 1, 'status': 'accepted_external_training_frozen', 'accepted_images': 5,
                  'accepted_groups': 5, 'data_quality_exception_count': 1, 'artifacts': artifacts,
                  'binding': {'source_sha256': source_hashes,
                              'inputs_sha256': {'data/freeze/validation_freeze.json': '0' * 64}}}
        self.freeze_hash = write(base, loader.TRAIN + '/freeze.json', freeze)
        input_hashes = {name: loader.digest((base / name).read_bytes()) for name in loader.GALLERY_SOURCES}
        input_hashes.update({loader.TRAIN + '/' + name: loader.digest((base / loader.TRAIN / name).read_bytes())
                            for name in ('freeze.json', 'manifest.jsonl', 'ingredients.json', 'catalog.json', 'fallback.json')})
        # Deliberately nonexistent protected paths: consuming this inventory
        # wholesale would immediately fail or violate the access boundary.
        input_hashes.update({'data/cohorts/dev.jsonl': '1' * 64, 'data/freeze/source_snapshot.json': '2' * 64})
        binding = {'schema_version': 1, 'phase': 'gallery', 'training_freeze_sha256': self.freeze_hash,
                   'training_exclusion_binding': freeze['binding'], 'input_sha256': input_hashes}
        store = ArtifactStore(base / loader.GALLERY, binding, [r['sample_id'] for r in rows],
                              verify_sources=lambda: True, root=base / 'round4')
        records = {}
        for i, row in enumerate(rows):
            raw = json.dumps({'scene': 'white plate', 'foods': [{'appearance': 'brown pieces', 'placement': 'center'}],
                              'scale_cues': [], 'uncertainties': []})
            parsed, text = loader.vision_stages._parse_description(raw)
            descriptor = {'raw_outputs': [raw], 'parsed': parsed, 'embedding_text': text,
                          'repair_used': False, 'failure': None}
            vector = [0.0] * 3072
            vector[i] = 1.0
            if invalid_vector and i == 0:
                vector = [0.0] * 3072
            embedding = {'vector': vector}
            proof = {k: row[k] for k in ('image_sha256', 'rgb_sha256')}
            prefix = 'image-' + loader.pipeline.fingerprint(proof)[:24]
            for suffix, result, inputs, role, values in (
                    ('description', descriptor, {'method': loader.vision_stages.METHOD_VERSION, 'image': proof}, 'chat', [raw]),
                    ('embedding', embedding, {'embedding_model': 'text-embedding-3-large', 'dimensions': 3072,
                                             'embedding_text': text}, 'embedding', [vector])):
                if wrong_stage and i == 0 and suffix == 'embedding':
                    inputs['embedding_text'] = 'different appearance'
                refs = [{'role': role, 'request_hash': 'a' * 64, 'value_hash': loader.pipeline.fingerprint(value),
                         'status': 'returned', 'cache_present_before': False} for value in values]
                if bad_ref and i == 0 and suffix == 'embedding':
                    refs[0]['value_hash'] = 'b' * 64
                envelope = {'result': result, 'request_refs': refs}
                store.stage_runner(prefix + ':' + suffix, inputs, lambda e=envelope: e, lambda value: value)
            metadata = {'train_id': row['sample_id'], 'screening_group_id': row['group_id'], **proof}
            if wrong_record and i == 0:
                metadata['screening_group_id'] = 'wrong'
            records[row['sample_id']] = {'metadata': metadata,
                'result': {'description': descriptor, 'embedding': embedding, 'repair_used': False, 'failure': None}}
        store.finalize(records)
        self.completion_hash = loader.digest((base / loader.GALLERY / 'completion.json').read_bytes())
        self.protocol_hash = loader.digest((base / loader.PROTOCOL).read_bytes())

    def patches(self):
        stack = ExitStack()
        for name, value in {'EXPECTED_N': 5, 'EXPECTED_GROUPS': 5,
                            'TRAIN_FREEZE_SHA256': self.freeze_hash,
                            'GALLERY_COMPLETION_SHA256': self.completion_hash,
                            'PROTOCOL_SHA256': self.protocol_hash}.items():
            stack.enter_context(patch.object(loader, name, value))
        return stack


class TrainLoaderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)

    def fixture(self, **kwargs):
        fixture = Fixture(self.base, **kwargs)
        self.addCleanup(fixture.patches().close)
        return fixture

    def test_projection_has_no_global_catalog_and_preserves_source_mass(self):
        self.fixture()
        data = loader.load_training(self.base)
        self.assertEqual(set(data), {'rows', 'vectors_by_id', 'ingredient_records', 'official_targets', 'binding', 'reader'})
        self.assertEqual(set(data['rows'][0]), {'sample_id', 'group_id'})
        self.assertEqual(set(data['ingredient_records']['train0'][0]), {'ingredient_id', 'grams', 'nutrients'})
        self.assertEqual(data['ingredient_records']['train0'][0]['grams'], 10.0)
        self.assertEqual(data['official_targets']['train0']['weight'], 8.0)
        self.assertEqual(len(data['vectors_by_id']), 5)

    def test_preflight_never_fits_or_reads_images_protected_data_or_keys(self):
        self.fixture()
        original = Path.read_bytes
        opened = []
        def guarded(path):
            name = path.relative_to(self.base).as_posix()
            self.assertFalse(name.startswith(('data/', 'round4/data/incoming/', 'round4/provider/')))
            self.assertNotIn('/images/', name)
            self.assertNotIn('.env', name)
            opened.append(name)
            return original(path)
        with patch.object(Path, 'read_bytes', guarded), patch.object(loader.gram_prior, 'evaluate_oof', side_effect=AssertionError('fit prohibited')):
            result = loader.run(base=self.base)
        self.assertEqual(result['status'], 'training_prior_inputs_verified')
        self.assertTrue(opened)
        self.assertFalse((self.base / loader.OUTPUT).exists())

    def test_reader_rejects_unlisted_path_before_open(self):
        self.fixture()
        with patch.object(Path, 'read_bytes', side_effect=AssertionError('opened')):
            with self.assertRaisesRegex(loader.LoaderError, 'input_path_not_allowlisted'):
                loader.Inputs(self.base).read('data/cohorts/dev_labels.json')

    def test_missing_and_extra_training_labels_rejected(self):
        self.fixture(missing_label=True)
        with self.assertRaisesRegex(loader.LoaderError, 'training_label_population_changed'):
            loader.load_training(self.base)

    def test_extra_label_rejected(self):
        self.fixture(extra_label=True)
        with self.assertRaisesRegex(loader.LoaderError, 'training_label_population_changed'):
            loader.load_training(self.base)

    def test_ingredient_group_mismatch_rejected(self):
        self.fixture(wrong_group=True)
        with self.assertRaisesRegex(loader.LoaderError, 'ingredient_training_association_changed'):
            loader.load_training(self.base)

    def test_gallery_image_group_association_rejected(self):
        self.fixture(wrong_record=True)
        with self.assertRaisesRegex(loader.LoaderError, 'gallery_training_association_changed'):
            loader.load_training(self.base)

    def test_sealed_wrong_embedding_caption_rejected(self):
        self.fixture(wrong_stage=True)
        with self.assertRaisesRegex(ArtifactError, 'stage_input_or_source_changed'):
            loader.load_training(self.base)

    def test_response_reference_value_hash_rejected(self):
        self.fixture(bad_ref=True)
        with self.assertRaisesRegex(loader.LoaderError, 'gallery_response_reference_changed'):
            loader.load_training(self.base)

    def test_invalid_vector_rejected(self):
        self.fixture(invalid_vector=True)
        with self.assertRaisesRegex(ValueError, 'zero_embedding'):
            loader.load_training(self.base)

    def test_source_change_rejected(self):
        self.fixture()
        write(self.base, 'round4/src/vision_stages.py', b'changed source', raw=True)
        with self.assertRaisesRegex(loader.LoaderError, 'pinned_input_changed'):
            loader.load_training(self.base)

    def test_incomplete_seal_stops_before_label_decode(self):
        self.fixture()
        (self.base / loader.GALLERY / 'seal.json').unlink()
        with patch.object(loader.gram_prior, '_targets', side_effect=AssertionError('labels decoded')):
            with self.assertRaises(ArtifactError):
                loader.load_training(self.base)

    def test_gallery_extra_file_rejected(self):
        self.fixture()
        write(self.base, loader.GALLERY + '/unexpected.json', {})
        with self.assertRaisesRegex(ArtifactError, 'completed_inventory_or_hash_changed'):
            loader.load_training(self.base)

    def test_metadata_hash_change_and_symlink_rejected(self):
        self.fixture()
        path = self.base / loader.TRAIN / 'labels.json'
        path.unlink()
        path.symlink_to(self.base / loader.TRAIN / 'catalog.json')
        with self.assertRaisesRegex(loader.LoaderError, 'unsafe_or_missing_input'):
            loader.load_training(self.base)

    def test_population_must_match_registration(self):
        self.fixture()
        with patch.object(loader, 'EXPECTED_N', 6):
            with self.assertRaisesRegex(loader.LoaderError, 'registered_training_population_changed'):
                loader.load_training(self.base)

    def test_explicit_run_reuses_math_and_completed_rerun_is_readonly(self):
        self.fixture()
        evaluate = loader.gram_prior.evaluate_oof
        def fit_after_binding(*args, **kwargs):
            intent = json.loads((self.base / loader.OUTPUT / 'intent.json').read_bytes())
            self.assertTrue(set(loader.PRIOR_SOURCES) <= set(intent['binding']['input_sha256']))
            self.assertIn(loader.TRAIN + '/labels.json', intent['binding']['input_sha256'])
            self.assertFalse((self.base / loader.OUTPUT / 'completion.json').exists())
            return evaluate(*args, **kwargs)
        with patch.object(loader.gram_prior, 'evaluate_oof', side_effect=fit_after_binding) as fit:
            first = loader.run(execute=True, base=self.base)
        self.assertEqual(fit.call_count, 1)
        output = self.base / loader.OUTPUT
        before = {p.relative_to(output).as_posix(): (p.read_bytes(), p.stat().st_mtime_ns)
                  for p in output.rglob('*') if p.is_file()}
        with patch.object(loader.gram_prior, 'evaluate_oof', side_effect=AssertionError('refit')):
            second = loader.run(execute=True, base=self.base)
        after = {p.relative_to(output).as_posix(): (p.read_bytes(), p.stat().st_mtime_ns)
                 for p in output.rglob('*') if p.is_file()}
        self.assertEqual(first, second)
        self.assertEqual(before, after)
        self.assertTrue(all(stat.S_IMODE(p.stat().st_mode) == 0o600 for p in output.rglob('*') if p.is_file()))


if __name__ == '__main__':
    unittest.main()
