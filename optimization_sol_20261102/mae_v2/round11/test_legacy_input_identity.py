"""Synthetic-only legacy projection regressions; never loads actual sources."""
import csv
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import legacy_input_identity as legacy

HEAD = ['dataset', 'sample_id', 'dish_id', 'image_path', 'reference_food_code',
        'truth', 'weight', 'nutrients', 'portion', 'size', 'ingredients']


def csv_bytes(rows, headers=HEAD):
    stream = io.StringIO(newline='')
    writer = csv.writer(stream)
    writer.writerow(headers)
    writer.writerows(rows)
    return stream.getvalue().encode()


class LegacyInputsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.asa = ['asa24', 'asa-1', '', '/DO_NOT_OPEN/a.png', '12345678'] + ['POISON_TARGET'] * 6
        self.n5 = ['nutrition5k', 'nutrition5k-dish_0000000001', '',
                   '/NEVER_OPEN/dish_0000000001/rgb.png', ''] + ['POISON_TARGET'] * 6
        for path in legacy.LEGACY_MANIFESTS:
            self.write(path, [self.asa, self.n5])

    def write(self, path, rows, headers=HEAD):
        dest = self.root / path
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(csv_bytes(rows, headers))

    def load(self):
        return legacy._load_at(self.root)

    def test_mixed_projection_ignores_targets_and_never_follows_images(self):
        real_read = legacy.secure_bounded_read
        opened = []
        def guarded(root, relative):
            self.assertEqual(root, self.root)
            self.assertIn(relative, legacy.LEGACY_MANIFESTS)
            opened.append(relative)
            return real_read(root, relative)
        with patch.object(legacy, 'secure_bounded_read', guarded):
            result = self.load()
        self.assertEqual(len(opened), 12)
        self.assertEqual(set(opened), set(legacy.LEGACY_MANIFESTS))
        self.assertEqual(result['summary']['dataset_identity_counts'], {'asa24': 4, 'nutrition5k': 4})
        self.assertNotIn('POISON', json.dumps(result))
        self.assertNotIn('DO_NOT_OPEN', json.dumps(result))
        self.assertEqual(result['private_identities'][1]['dish_id'], 'dish_0000000001')
        for key in ('exposure_complete', 'source_association_complete', 'historical_exposure_proven',
                    'may_remove_historical_snapshot_blocks', 'grants_sampling_download_or_inference'):
            self.assertIs(result[key], False)

    def test_unexpected_path_refused_before_open(self):
        with patch.object(legacy, 'secure_bounded_read', side_effect=AssertionError('opened')):
            with self.assertRaisesRegex(ValueError, 'unregistered'):
                legacy._read(self.root, '../sealed/labels.csv')

    def test_missing_is_explicit_and_not_complete(self):
        (self.root / legacy.LEGACY_MANIFESTS[0]).unlink()
        result = self.load()
        self.assertEqual(result['sources'][0]['status'], 'missing_unresolved')
        self.assertEqual(result['summary']['missing_unresolved_count'], 1)
        self.assertFalse(result['exposure_complete'])

    def test_empty_is_unresolved(self):
        self.write(legacy.LEGACY_MANIFESTS[0], [])
        self.assertEqual(self.load()['sources'][0]['status'], 'empty_unresolved')

    def test_duplicate_headers_and_duplicate_identities_refused(self):
        for rows, headers in (([self.asa], HEAD[:-1] + ['dataset']),
                              ([self.asa, self.asa], HEAD),
                              ([self.n5, self.n5], HEAD)):
            with self.subTest(headers=headers, rows=len(rows)):
                self.write(legacy.LEGACY_MANIFESTS[0], rows, headers)
                with self.assertRaises(ValueError):
                    self.load()

    def test_ambiguous_dish_and_unknown_dataset_refused(self):
        variants = []
        row = self.n5.copy(); row[3] = 'dish_0000000002/rgb.png'; variants.append(row)
        row = self.n5.copy(); row[1] = ''; row[3] = 'plain.png'; variants.append(row)
        row = self.asa.copy(); row[0] = ''; variants.append(row)
        row = self.asa.copy(); row[0] = 'unknown'; variants.append(row)
        row = self.n5.copy(); row[2] = 'dish_0000000009'; variants.append(row)
        for row in variants:
            self.write(legacy.LEGACY_MANIFESTS[0], [row])
            with self.assertRaises(ValueError):
                self.load()

    def test_food_code_requires_exact_eight_ascii_digits(self):
        for code in ('12345678.0', '12345678.5', ' 12345678', '1234567', '１２３４５６７８'):
            row = self.asa.copy(); row[4] = code
            self.write(legacy.LEGACY_MANIFESTS[0], [row])
            with self.assertRaisesRegex(ValueError, 'exact_legacy_food_code'):
                self.load()
        for code in ('01234567', ''):
            row = self.asa.copy(); row[4] = code
            self.write(legacy.LEGACY_MANIFESTS[0], [row])
            self.load()

    def test_linked_parent_and_special_file_refused(self):
        path = self.root / legacy.LEGACY_MANIFESTS[0]
        parent = path.parent
        moved = parent.with_name('moved')
        parent.rename(moved)
        parent.symlink_to(moved, target_is_directory=True)
        with self.assertRaises((ValueError, OSError)):
            self.load()
        parent.unlink(); moved.rename(parent)
        path.unlink()
        import os
        os.mkfifo(path)
        with self.assertRaisesRegex(ValueError, 'bounded_regular'):
            self.load()

    def test_source_changed_before_and_after_parse_refused(self):
        real_read = legacy.secure_bounded_read
        for change_at in (5, 9):
            count = 0
            def changed(root, relative):
                nonlocal count
                count += 1
                raw = real_read(root, relative)
                return raw + b'\n' if count == change_at else raw
            with patch.object(legacy, 'secure_bounded_read', changed):
                with self.assertRaisesRegex(ValueError, 'legacy_source_changed'):
                    self.load()

    def test_public_entry_has_no_path_override(self):
        with patch.object(legacy, '_load_at', return_value={}) as load:
            self.assertEqual(legacy.load_legacy_inputs(), {})
            load.assert_called_once_with(legacy.REPO.parent)
        with self.assertRaises(TypeError):
            legacy.load_legacy_inputs(self.root)


if __name__ == '__main__':
    unittest.main()
