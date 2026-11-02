"""Synthetic loader isolation; no credentials, real images, or research labels."""
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image

V2 = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(V2), str(V2 / 'src')]
from round4.src import context as c


class ContextTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        def put(name, value):
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            raw = value if isinstance(value, bytes) else json.dumps(value).encode()
            path.write_bytes(raw)
            return c.digest(raw)
        self.put = put
        for name in c.SOURCE_NAMES:
            put(name, b'synthetic immutable source')
        self.train, ingredients = [], []
        for i in range(12):
            raw = self.picture(i)
            image = 'round4/data/train/images/' + c.digest(raw) + '.png'
            put(image, raw)
            self.train.append({'sample_id': f'train-{i}', 'dataset': 'nutrition5k', 'split': 'train',
                'group_id': f'train-group-{i}', 'image_path': image, 'image_sha256': c.digest(raw),
                'rgb_sha256': c.rgb_hash(raw)})
            ingredients.append({'sample_id': f'train-{i}', 'ingredients': [
                {'ingredient_id': 'ingr_0000000001', 'grams': 100, 'name': 'unforwarded', 'nutrients': {}}]})
        put(c.TRAIN + '/manifest.jsonl', b''.join(json.dumps(r).encode() + b'\n' for r in self.train))
        put(c.TRAIN + '/ingredients.json', {'records': ingredients})
        put(c.TRAIN + '/catalog.json', {'ingredients': [{'ingredient_id': 'ingr_0000000001',
            'name': 'synthetic food', 'density_per_100g': {k: 1 for k in ('energy', 'fat', 'carbs', 'protein')},
            'supporting_dish_count': 12, 'supporting_group_count': 12}]})
        put(c.TRAIN + '/fallback.json', {'prediction': {k: 1 for k in ('weight', 'energy', 'fat', 'carbs', 'protein')}})
        artifacts = {name: c.digest((self.root / c.TRAIN / name).read_bytes()) for name in
                     ('manifest.jsonl', 'ingredients.json', 'catalog.json', 'fallback.json')}
        freeze_sha = put(c.TRAIN + '/freeze.json', {'binding': {'synthetic_exclusion_proof': True}, 'artifacts': artifacts})
        self.proof = {'status': 'accepted_external_training_verified', 'freeze_sha256': freeze_sha, 'accepted_images': 12}
        capability_sha = put('round4/runs/capability/completion.json', {'synthetic_capability': True})
        self.capability = {'status': 'capability_passed', 'training_freeze_sha256': freeze_sha,
                           'completion_sha256': capability_sha}
        # Real artifact parents are created privately by the capability store.
        (self.root / 'round4/runs').chmod(0o700)
        self.rows = []
        for i in range(84):
            raw = self.picture(i + 20)
            image = f'fake_query_images/{i}.png'
            put(image, raw)
            self.rows.append({'sample_id': f'query-{i}', 'dataset': 'nutrition5k', 'split': 'dev',
                'group_id': f'query-group-{i % 78}', 'fold': (i % 78) % 5,
                'image_path': image, 'image_sha256': c.digest(raw)})
        self.pin_manifest()
        # Reading either label sentinel as JSON would fail, even though the
        # legitimate manifest/image-only loader must still complete.
        put('data/cohorts/dev_labels.json', b'NOT JSON: SECRET QUERY TARGETS')
        put('data/cohorts/validation_labels.json', b'NEVER OPEN VALIDATION')

    def pin_manifest(self):
        value = self.put(c.DEV_MANIFEST, b''.join(json.dumps(r).encode() + b'\n' for r in self.rows))
        if hasattr(self, 'pin'):
            self.pin.stop()
        self.pin = patch.object(c, 'DEV_MANIFEST_SHA256', value)
        self.pin.start()
        self.addCleanup(self.pin.stop)

    @staticmethod
    def picture(i):
        out = io.BytesIO()
        Image.new('RGB', (3, 2), (i, i // 2, 255 - i)).save(out, 'PNG')
        return out.getvalue()

    def load(self):
        return c.load_context(self.root, verify_train=lambda _: self.proof,
                              verify_capability=lambda _: self.capability)

    def test_full_population_narrow_adapters_and_no_query_labels(self):
        reads = []
        original = Path.read_bytes
        def read(path):
            reads.append(str(path.relative_to(self.root)))
            return original(path)
        with patch.object(Path, 'read_bytes', read):
            result = self.load()
        self.assertEqual(len(result['queries']), 84)
        self.assertEqual(len(result['entries']), 12)
        self.assertFalse(any('labels' in name or 'validation' in name for name in reads))
        self.assertEqual(set(result['assets']['catalog'][0]), {'ingredient_id', 'name', 'density_per_100g'})
        self.assertEqual(set(result['assets']['supports']['train-0']), {'image_path', 'ingredients'})
        before = json.dumps(result['binding'], sort_keys=True)
        self.put('data/cohorts/dev_labels.json', b'ALL LABELS CHANGED')
        self.assertEqual(before, json.dumps(self.load()['binding'], sort_keys=True))

    def test_manifest_change_rejected_before_queries(self):
        with (self.root / c.DEV_MANIFEST).open('ab') as handle:
            handle.write(b' ')
        with self.assertRaisesRegex(c.ContextError, 'pinned_input_changed'):
            self.load()

    def test_pixel_overlap_rejected_even_if_bytes_differ(self):
        raw = (self.root / self.train[0]['image_path']).read_bytes()
        path = self.rows[0]['image_path']
        # Different PNG serialization, same pixels.
        out = io.BytesIO()
        with Image.open(io.BytesIO(raw)) as image:
            image.save(out, 'PNG', compress_level=0)
        changed = out.getvalue()
        self.assertNotEqual(c.digest(raw), c.digest(changed))
        self.put(path, changed)
        self.rows[0]['image_sha256'] = c.digest(changed)
        self.pin_manifest()
        with self.assertRaisesRegex(c.ContextError, 'train_query_pixel_overlap'):
            self.load()

    def test_missing_query_and_group_change_fail_population(self):
        self.rows.pop()
        self.pin_manifest()
        with self.assertRaisesRegex(c.ContextError, 'development_population_changed'):
            self.load()

    def test_image_hash_and_source_changes_cannot_be_silent(self):
        result = self.load()
        self.put(c.SOURCE_NAMES[0], b'changed source')
        with self.assertRaisesRegex(c.ContextError, 'bound_input_changed'):
            result['reader'].unchanged()
        self.put(self.rows[0]['image_path'], self.picture(200))
        with self.assertRaisesRegex(c.ContextError, 'pinned_input_changed'):
            self.load()

    def test_symlink_and_traversal_paths_fail(self):
        path = self.root / 'linked'
        path.symlink_to(self.root / c.DEV_MANIFEST)
        for name in ('linked', '../elsewhere', str(self.root / c.DEV_MANIFEST)):
            with self.assertRaises(c.ContextError):
                c.safe_path(self.root, name)

    def test_unreleased_train_and_ingredient_id_mismatch_fail(self):
        self.proof['status'] = 'pending'
        with self.assertRaisesRegex(c.ContextError, 'training_not_released'):
            self.load()
        self.proof['status'] = 'accepted_external_training_verified'
        self.put(c.TRAIN + '/ingredients.json', {'records': []})
        with self.assertRaisesRegex(c.ContextError, 'pinned_input_changed'):
            self.load()

    def test_training_changed_between_verification_and_load_is_rejected(self):
        def verify(_):
            self.put(c.TRAIN + '/catalog.json', {'ingredients': []})
            return self.proof
        with self.assertRaisesRegex(c.ContextError, 'pinned_input_changed'):
            c.load_context(self.root, verify_train=verify, verify_capability=lambda _: self.capability)

    def test_capability_must_pass_on_the_same_training_freeze(self):
        self.capability['training_freeze_sha256'] = 'a' * 64
        with self.assertRaisesRegex(c.ContextError, 'training_capability_not_verified'):
            self.load()


if __name__ == '__main__':
    unittest.main()
