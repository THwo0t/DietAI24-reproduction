"""Synthetic adapter tests; never open research metadata, images or validation."""
from copy import deepcopy
import csv
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import dev_ingredients as adapter


def manifest_row(i, fold, group=None):
    return {'dataset': 'nutrition5k', 'sample_id': f'nutrition5k-dish_{i:010d}',
            'group_id': group or f'synthetic_group_{i}', 'fold': fold, 'split': 'dev',
            'image_path': 'must_never_open_this.png'}


def csv_line(i, ingredients=None, declared=False):
    if ingredients is None:
        ingredients = [['ingr_0000000001', 'Synthetic food', 10, 20, 1, 2, 3]]
    # Intentionally nonnumeric dish totals: no aggregate dish labels are needed.
    values = [f'dish_{i:010d}', 'unused', 'unused', 'unused', 'unused', 'unused']
    if declared:
        values.append(len(ingredients))
    for item in ingredients:
        values.extend(item)
    stream = io.StringIO(newline='')
    csv.writer(stream, lineterminator='\n').writerow(values)
    return stream.getvalue().encode()


def extract(rows, lines):
    return adapter.extract_streams([('synthetic.csv', io.BytesIO(b''.join(lines)))],
                                   adapter.active_development(rows))


class AdapterTests(unittest.TestCase):
    def test_unmatched_tail_never_decoded_or_csv_parsed(self):
        rows = [manifest_row(1, 0)]
        poison = b'dish_9999999999,\xff\xfe,NaN,"unclosed\n'
        good = csv_line(1, [['ingr_0000000001', 'Food, with comma', 10, 20, 1, 2, 3]])
        real_reader = adapter.csv.reader
        with patch.object(adapter.csv, 'reader', wraps=real_reader) as reader:
            result = extract(rows, [poison, good])
        self.assertEqual(reader.call_count, 1)
        self.assertEqual(result['source_sha256']['synthetic.csv'], hashlib.sha256(poison + good).hexdigest())
        ingredient = result['records'][0]['ingredients'][0]
        self.assertEqual(ingredient['name'], 'Food, with comma')
        self.assertEqual(ingredient['density_per_100g'], {'energy': 200., 'fat': 10., 'carbs': 20., 'protein': 30.})

    def test_bom_and_declared_count_variant(self):
        result = extract([manifest_row(1, 0)], [b'\xef\xbb\xbf' + csv_line(1, declared=True)])
        self.assertEqual(len(result['records'][0]['ingredients']), 1)

    def test_missing_name_count_and_ingredient_schema_fail(self):
        cases = [csv_line(1, [['ingr_0000000001', '', 10, 20, 1, 2, 3]]),
                 csv_line(1, declared=True).replace(b',1,ingr_', b',2,ingr_'),
                 csv_line(1).replace(b'ingr_0000000001', b'bad_id'),
                 csv_line(1).replace(b',20,1,2,3', b',NaN,1,2,3')]
        for raw in cases:
            with self.subTest(raw_kind=cases.index(raw)):
                with self.assertRaises(adapter.IngredientError) as error:
                    extract([manifest_row(1, 0)], [raw])
                self.assertNotIn('dish_', str(error.exception))
                self.assertNotIn('Synthetic food', str(error.exception))

    def test_duplicate_and_missing_active_rows_fail(self):
        with self.assertRaisesRegex(adapter.IngredientError, 'duplicate_matched'):
            extract([manifest_row(1, 0)], [csv_line(1), csv_line(1)])
        with self.assertRaisesRegex(adapter.IngredientError, 'missing_from_sources'):
            extract([manifest_row(1, 0), manifest_row(2, 1)], [csv_line(1)])

    def test_explicit_nondev_and_group_fold_leak_fail(self):
        bad = manifest_row(1, 0)
        bad['split'] = 'validation'
        with self.assertRaisesRegex(adapter.IngredientError, 'development_only'):
            adapter.active_development([bad])
        bad = manifest_row(1, 0)
        bad['sealed'] = True
        with self.assertRaisesRegex(adapter.IngredientError, 'development_only'):
            adapter.active_development([bad])
        with self.assertRaisesRegex(adapter.IngredientError, 'group_spans_folds'):
            adapter.active_development([manifest_row(1, 0, 'same'), manifest_row(2, 1, 'same')])

    def test_exclude_all_heldout_group_rows_before_inspecting_ingredients(self):
        rows = [manifest_row(1, 0, 'held_group'), manifest_row(2, 0, 'held_group'),
                manifest_row(3, 1), manifest_row(4, 2)]
        private = extract(rows, [csv_line(i) for i in range(1, 5)])
        original = adapter.build_fold_catalog(private, rows, 0)
        changed = deepcopy(private)
        # Even malformed held-out contents are never inspected by training fit.
        changed['records'][0]['ingredients'] = [{'name': None, 'grams': float('nan')}]
        changed['records'][1]['ingredients'] = None
        self.assertEqual(adapter.build_fold_catalog(changed, rows, 0), original)
        self.assertEqual(original['training_dish_count'], 2)
        self.assertEqual(original['training_group_count'], 2)
        self.assertEqual(original['excluded_group_count'], 1)
        self.assertEqual(original['ingredients'][0]['supporting_dish_count'], 2)

    def test_heldout_only_food_absent_and_no_image_food_mapping(self):
        rows = [manifest_row(1, 0), manifest_row(2, 1)]
        unique = [['ingr_0000000099', 'Held-out secret food', 10, 20, 1, 2, 3]]
        private = extract(rows, [csv_line(1, unique), csv_line(2)])
        catalog = adapter.build_fold_catalog(private, rows, 0)
        text = json.dumps(catalog)
        for forbidden in ['Held-out secret food', 'ingr_0000000099', 'nutrition5k-dish_',
                          'synthetic_group_', 'sample_id', 'dish_id', 'group_id',
                          'image_path', 'records', '"grams"', '"nutrients"']:
            self.assertNotIn(forbidden, text)

    def test_training_density_conflict_fails_but_heldout_conflict_does_not(self):
        rows = [manifest_row(1, 0), manifest_row(2, 1), manifest_row(3, 2)]
        private = extract(rows, [csv_line(i) for i in range(1, 4)])
        private['records'][0]['ingredients'][0]['nutrients']['protein'] = 20
        adapter.build_fold_catalog(private, rows, 0)
        with self.assertRaisesRegex(adapter.IngredientError, 'density_conflict'):
            adapter.build_fold_catalog(private, rows, 1)

    def test_training_name_conflict_fails(self):
        rows = [manifest_row(1, 0), manifest_row(2, 1), manifest_row(3, 2)]
        private = extract(rows, [csv_line(i) for i in range(1, 4)])
        private['records'][2]['ingredients'][0]['name'] = 'Different recipe'
        with self.assertRaisesRegex(adapter.IngredientError, 'name_conflict'):
            adapter.build_fold_catalog(private, rows, 0)

    def test_density_rederived_and_zero_mass_kept_private_only(self):
        rows = [manifest_row(1, 0), manifest_row(2, 1)]
        items = [['ingr_0000000001', 'Synthetic food', 10, 20, 1, 2, 3],
                 ['ingr_0000000002', 'Zero amount', 0, 0, 0, 0, 0]]
        private = extract(rows, [csv_line(1), csv_line(2, items)])
        self.assertEqual(len(private['records'][1]['ingredients']), 2)
        private['records'][1]['ingredients'][0]['density_per_100g'] = {'protein': 99999}
        catalog = adapter.build_fold_catalog(private, rows, 0)
        self.assertEqual(len(catalog['ingredients']), 1)
        self.assertEqual(catalog['zero_mass_training_ingredient_count'], 1)
        self.assertEqual(catalog['ingredients'][0]['density_per_100g']['protein'], 30)
        invalid = [['ingr_0000000002', 'Zero amount', 0, 1, 0, 0, 0]]
        with self.assertRaisesRegex(adapter.IngredientError, 'zero_mass'):
            extract([rows[0]], [csv_line(1, invalid)])

    def test_manifest_identity_binding_cannot_be_reassigned(self):
        rows = [manifest_row(1, 0), manifest_row(2, 1)]
        private = extract(rows, [csv_line(1), csv_line(2)])
        private['records'][0]['fold'] = 1
        with self.assertRaisesRegex(adapter.IngredientError, 'binding_mismatch'):
            adapter.build_fold_catalog(private, rows, 0)

    def test_no_extract_flag_opens_no_data(self):
        with patch.object(adapter, 'prepare_registered', side_effect=AssertionError('must not execute')):
            with patch('sys.stdout', new_callable=io.StringIO) as output:
                self.assertEqual(adapter.main([]), 0)
        self.assertFalse(json.loads(output.getvalue())['source_data_opened'])

    def test_private_writes_are_immutable_restricted_and_reject_symlink(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'private' / 'one.json'
            adapter.private_write(path, b'{}')
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(path.parent.stat().st_mode & 0o777, 0o700)
            adapter.private_write(path, b'{}')
            with self.assertRaisesRegex(adapter.IngredientError, 'conflict'):
                adapter.private_write(path, b'[]')
            other = path.parent / 'link.json'
            other.symlink_to(path)
            with self.assertRaisesRegex(adapter.IngredientError, 'unsafe_output'):
                adapter.private_write(other, b'{}')

    def test_fixed_operational_route_with_only_synthetic_84_rows(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            # Six repeated groups plus 72 singleton groups = 78 groups / 84 rows.
            rows = [manifest_row(i + 1, (i if i < 78 else i - 78) % 5,
                                 f'synthetic_group_{i if i < 78 else i - 78}') for i in range(84)]
            manifest = base / 'dev.jsonl'
            raw = b''.join(adapter.encoded(row).replace(b'\n', b'') + b'\n' for row in rows)
            manifest.write_bytes(raw)
            freeze = base / 'dev_freeze.json'
            freeze.write_bytes(adapter.encoded({'artifacts': {'data/cohorts/dev.jsonl': adapter.sha(raw)}}))
            sources = (base / 'cafe1.csv', base / 'cafe2.csv')
            sources[0].write_bytes(b''.join(csv_line(i) for i in range(1, 43)))
            sources[1].write_bytes(b''.join(csv_line(i) for i in range(43, 85)))
            output = base / 'private/dev_ingredients.json'
            catalog_dir = base / 'private/train_catalogs'
            summary_path = base / 'private/summary.json'
            with patch.multiple(adapter, MANIFEST=manifest, FREEZE=freeze, SOURCES=sources,
                                OUTPUT=output, CATALOG_DIR=catalog_dir, SUMMARY=summary_path):
                result = adapter.prepare_registered()
                self.assertEqual(adapter.prepare_registered(), result)
            self.assertEqual(result['development_dish_count'], 84)
            self.assertEqual(result['development_group_count'], 78)
            self.assertEqual(len(list(catalog_dir.glob('fold_*.json'))), 5)
            safe = json.dumps(result)
            for forbidden in ['dish_000', 'ingr_000', 'Synthetic food', 'synthetic_group_', 'density_per_100g']:
                self.assertNotIn(forbidden, safe)
            self.assertEqual(json.loads(summary_path.read_text()), result)
            self.assertEqual(output.stat().st_mode & 0o777, 0o600)


if __name__ == '__main__':
    unittest.main()
