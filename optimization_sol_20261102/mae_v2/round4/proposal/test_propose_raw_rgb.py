import csv
from pathlib import Path
import tempfile
import unittest

import audit_pool as a
import propose_raw_rgb as p


def row(dish, energy='100', weight='100', fat='0', carbs='0', protein='25', grams='100'):
    return [dish, energy, weight, fat, carbs, protein,
            'ingr_0000000001', 'synthetic food', grams, energy, fat, carbs, protein]


class RawQualificationTests(unittest.TestCase):
    def qualify(self, rows, allowed):
        with tempfile.TemporaryDirectory(dir=a.HERE) as folder:
            path = Path(folder) / 'raw.csv'
            with path.open('w', newline='') as stream:
                csv.writer(stream).writerows(rows)
            return p.qualify_rows([path], allowed)

    def test_individual_zero_nutrients_remain_eligible(self):
        dish = 'dish_1000000000'
        good, reasons = self.qualify([row(dish)], {dish})
        self.assertEqual(good, {dish})
        self.assertEqual(reasons, {})

    def test_all_zero_nutrients_and_nonpositive_weight_are_excluded(self):
        ids = ['dish_1000000000', 'dish_1000000001']
        good, reasons = self.qualify([row(ids[0], energy='0', protein='0'), row(ids[1], weight='0')], set(ids))
        self.assertEqual(good, set())
        self.assertEqual(reasons, {'all_four_nutrients_zero': 1, 'nonpositive_weight': 1})

    def test_excluded_reference_numeric_poison_is_never_interpreted(self):
        excluded, candidate = 'dish_1000000000', 'dish_1000000001'
        good, reasons = self.qualify([row(excluded, energy='POISON', grams='POISON'), row(candidate)], {candidate})
        self.assertEqual(good, {candidate})
        self.assertEqual(reasons, {})

    def test_nonfinite_negative_and_zero_food_mass_fail_qualification(self):
        ids = [f'dish_{1000000000+i}' for i in range(3)]
        good, reasons = self.qualify([row(ids[0], protein='NaN'), row(ids[1], energy='-1'), row(ids[2], grams='0')], set(ids))
        self.assertEqual(good, set())
        self.assertEqual(reasons, {'invalid_numeric_target': 2, 'no_positive_ingredient_mass': 1})

    def test_missing_candidate_fails_closed(self):
        with self.assertRaises(a.AuditError):
            self.qualify([], {'dish_1000000000'})

    def test_group_selection_does_not_use_nutrient_magnitudes(self):
        ids = ['dish_1000000000', 'dish_1000000001']
        eligible1, _ = self.qualify([row(x) for x in ids], set(ids))
        eligible2, _ = self.qualify([row(x, energy='99999', protein='1') for x in ids], set(ids))
        groups = {x: 'same-group' for x in ids}
        self.assertEqual(a.fixed_selection(eligible1, groups, 1), a.fixed_selection(eligible2, groups, 1))


if __name__ == '__main__':
    unittest.main()
