import csv
from pathlib import Path
import tempfile
import unittest

import audit_pool as a
import diagnose_coverage as d


class CoverageTests(unittest.TestCase):
    def test_positive_only_count_and_quantity_coverage(self):
        rows = [{'ingredients': [
            {'ingredient_id': 'a', 'grams': 30, 'nutrients': dict(energy=60, fat=1, carbs=2, protein=3)},
            {'ingredient_id': 'b', 'grams': 70, 'nutrients': dict(energy=140, fat=3, carbs=2, protein=7)},
            {'ingredient_id': 'c', 'grams': 0, 'nutrients': dict(energy=0, fat=0, carbs=0, protein=0)}]}]
        result = d.coverage(rows, lambda row: {'a'})
        self.assertEqual(result['positive_ingredient_occurrences'], 2)
        self.assertEqual(result['positive_ingredient_occurrence_coverage'], 0.5)
        self.assertEqual(result['quantity_coverage']['weight'], 0.3)
        self.assertEqual(result['quantity_coverage']['fat'], 0.25)
        self.assertEqual(result['all_positive_ingredients_covered_dishes'], 0)

    def test_selected_catalog_skips_unselected_numeric_poison(self):
        selected, excluded = 'dish_1000000000', 'dish_1000000001'
        with tempfile.TemporaryDirectory(dir=a.HERE) as folder:
            path = Path(folder) / 'raw.csv'
            with path.open('w', newline='') as stream:
                writer = csv.writer(stream)
                writer.writerow([excluded] + ['POISON'] * 5 + ['ingr_0000000001', 'private', 'POISON'] + ['POISON'] * 4)
                writer.writerow([selected] + ['POISON'] * 5 + ['ingr_0000000002', 'synthetic', '10'] + ['POISON'] * 4)
            ids, count = d.selected_catalog([path], {selected})
            self.assertEqual(ids, {'ingr_0000000002'})
            self.assertEqual(count, 1)


if __name__ == '__main__':
    unittest.main()
