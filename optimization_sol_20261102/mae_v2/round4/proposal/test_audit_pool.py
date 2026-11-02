"""Synthetic integrity tests; no real cohorts/images or credentials are read."""
from pathlib import Path
import csv
import io
import tempfile
import unittest

from PIL import Image

import audit_pool as a


def raw(dish, names, numeric='POISON_MUST_NOT_PARSE'):
    row = [dish] + [numeric] * 5
    for index, name in enumerate(names):
        row += [f'ingr_{index:010d}', name] + [numeric] * 5
    return row


class BlindProposalTests(unittest.TestCase):
    def test_recipe_parses_no_numeric_fields_and_exact_legacy_formula(self):
        row = raw('dish_1000000000', ['rice', 'oil', 'oil'])
        self.assertEqual(a.recipe_fingerprint(row), a.digest(b'oil, oil, rice'))

    def test_poisoned_labels_do_not_change_recipe(self):
        self.assertEqual(a.recipe_fingerprint(raw('dish_1000000000', ['apple'], 'NaN')),
                         a.recipe_fingerprint(raw('dish_1000000000', ['apple'], 'secret')))

    def test_declared_count_and_structure_fail_closed(self):
        row = raw('dish_1000000000', ['rice'])
        self.assertEqual(a.recipe_fingerprint(row), a.recipe_fingerprint(row[:6] + ['1'] + row[6:]))
        with self.assertRaises(a.AuditError):
            a.recipe_fingerprint(row[:6] + ['2'] + row[6:])
        with self.assertRaises(a.AuditError):
            a.recipe_fingerprint(row[:-1])

    def test_recipe_closure_transitive_through_an_unselected_member(self):
        mapping = {'a': 'g1', 'b': 'g1', 'c': 'g2', 'd': 'g2', 'e': 'g3', 'f': 'g4'}
        recipes = {'a': 'r1', 'b': 'r2', 'c': 'r2', 'd': 'r3', 'e': 'r3', 'f': 'r4'}
        result, members = a.proposal_closure(mapping, recipes, [])
        self.assertEqual(len(members), 2)
        self.assertEqual(result['a'], result['e'])
        self.assertNotEqual(result['a'], result['f'])
        self.assertEqual(mapping['e'], 'g3')  # Original graph remains unchanged.

    def test_byte_and_rgb_equalities_extend_only_proposal_closure(self):
        mapping = {'a': 'g1', 'b': 'g2', 'c': 'g3'}
        recipes = {x: x for x in mapping}
        fps = [{'dish_id': 'a', 'bytes_sha256': '1', 'rgb_sha256': 'x'},
               {'dish_id': 'b', 'bytes_sha256': '2', 'rgb_sha256': 'x'},
               {'dish_id': 'c', 'bytes_sha256': '2', 'rgb_sha256': 'y'}]
        result, members = a.proposal_closure(mapping, recipes, fps)
        self.assertEqual(len(members), 1)
        self.assertEqual(result['a'], result['c'])

    def test_unknown_image_id_fails(self):
        with self.assertRaises(a.AuditError):
            a.proposal_closure({'a': 'g'}, {'a': 'r'},
                              [{'dish_id': 'z', 'bytes_sha256': '1', 'rgb_sha256': '2'}])

    def test_validation_numeric_poison_is_never_parsed(self):
        with tempfile.TemporaryDirectory(dir=a.HERE) as folder:
            path = Path(folder) / 'available.csv'
            with path.open('w', newline='') as stream:
                writer = csv.writer(stream)
                writer.writerow(['dish_id', 'total_mass', 'total_calories', 'total_fat', 'total_carbs', 'total_protein'])
                writer.writerow(['dish_1000000000'] + ['POISON'] * 5)
                writer.writerow(['dish_1000000001', '100', '10', '1', '1', '1'])
                writer.writerow(['dish_1000000002', '100', '0', '0', '0', '0'])
            accepted, frame, count = a.candidate_eligibility(path, {'dish_1000000001', 'dish_1000000002'})
            self.assertEqual(accepted, {'dish_1000000001'})
            self.assertEqual((len(frame), count), (3, 1))
            with self.assertRaises(a.AuditError):
                a.candidate_eligibility(path, {'dish_1000000000'})

    def test_raw_mass_poison_for_excluded_rows_is_never_parsed(self):
        with tempfile.TemporaryDirectory(dir=a.HERE) as folder:
            path = Path(folder) / 'raw.csv'
            with path.open('w', newline='') as stream:
                writer = csv.writer(stream)
                writer.writerow(raw('dish_1000000000', ['private'], 'POISON'))
                writer.writerow(raw('dish_1000000001', ['food'], '1'))
            self.assertEqual(a.positive_mass_ids([path], {'dish_1000000001'}), {'dish_1000000001'})

    def test_selection_is_deterministic_unique_and_does_not_relax(self):
        mapping = {'a': '1', 'b': '1', 'c': '2', 'd': '3'}
        first = a.fixed_selection(list(mapping), mapping, target=3)
        self.assertEqual(first, a.fixed_selection(list(reversed(mapping)), mapping, target=3))
        self.assertEqual(len({mapping[x] for x in first}), 3)
        self.assertEqual(a.fixed_selection(list(mapping), mapping, target=4), [])

    def test_rgb_hash_matches_frozen_preparer_formula(self):
        with tempfile.TemporaryDirectory(dir=a.HERE) as folder:
            path = Path(folder) / 'image.png'
            image = Image.new('RGB', (2, 3), (20, 30, 40))
            image.save(path)
            result = a.rgb_fingerprint(path, a.file_hash(path))
            self.assertEqual(result['rgb_sha256'], a.digest(str(image.size).encode() + b'\0' + image.tobytes()))
            with self.assertRaises(a.AuditError):
                a.rgb_fingerprint(path, '0' * 64)

    def test_duplicate_json_and_unsafe_paths_rejected(self):
        with self.assertRaises(a.AuditError):
            a.unique_object([('a', 1), ('a', 2)])
        with self.assertRaises(a.AuditError):
            a.safe_child(a.HERE, '../outside')


if __name__ == '__main__':
    unittest.main()
