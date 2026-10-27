"""R-E3-2: the offline causes of the failures in REPORT.md section 2 (code/failure_causes.py)."""
import sys
import unittest
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'code'))

import failure_causes as fc  # noqa: E402

# dish_1561574479 of E2 (runs/test/nutrition5k_nutrition.csv)
DECLINED_DISH = {
    'dish_id': 'dish_1561574479',
    'GPTFoodCode': "I'm unable to identify specific foods in the image. However, based on the context provided, here are "
                   "potential matches:; - Pizza with cheese and extra vegetables: 58106347, 58106325, 58106330, 58106350, "
                   "58106345; If there are other foods in the image, I can't determine them from the context given.",
    'GPTAmount': "I'm unable to determine the exact weight of the foods in the image."}


class TestGramsFailures(unittest.TestCase):

    def test_a_refusal_is_no_renaming(self):
        # no number at all: it fell into "renamed" before R-E3-2
        self.assertEqual(fc.grams_failures(pd.DataFrame([DECLINED_DISH])),
                         [('dish_1561574479', 'pizza with cheese and extra vegetables', fc.DECLINED)])

    def test_each_cause(self):
        df = pd.DataFrame({
            'dish_id': ['split', 'renamed', 'not a number', 'found', 'no code'],
            'GPTFoodCode': ['pork, potatoes, and vegetables: 22222222', 'fruit salad: 63200100',
                            'Egg sandwich with bacon: 32202020; Omelet: 32105000', 'Rice: 56205000', 'Sauce: none'],
            'GPTAmount': ['pork: 100 grams\npotatoes: 150 grams', 'fruit mixture: 50 grams',
                          'Omelet: 150 grams\nEgg sandwich with bacon: Not visible in the image', 'Rice: 120', np.nan]})
        self.assertEqual(fc.grams_failures(df), [('split', 'pork, potatoes, and vegetables', fc.SPLIT),
                                                 ('renamed', 'fruit salad', fc.RENAMED),
                                                 ('not a number', 'egg sandwich with bacon', fc.NOT_A_NUMBER)])

    def test_e2(self):
        # each cause of E2 with its dishes, the failures of a dish its WeightError
        path = ROOT / 'runs' / 'test' / 'nutrition5k_nutrition.csv'
        if not path.exists():
            self.skipTest('needs the E2 tables')
        df = pd.read_csv(path)
        failures = fc.grams_failures(df)
        self.assertEqual(Counter(cause for _, _, cause in failures),
                         {fc.SPLIT: 20, fc.RENAMED: 14, fc.NOT_A_NUMBER: 3, fc.DECLINED: 1})
        self.assertEqual([dish for dish, _, cause in failures if cause == fc.DECLINED], ['dish_1561574479'])
        per_dish = Counter(dish for dish, _, _ in failures)
        weight_errors = df.set_index('dish_id')['WeightError'].fillna(0)
        self.assertEqual(per_dish, Counter({dish: int(n) for dish, n in weight_errors.items() if n > 0}))


if __name__ == '__main__':
    unittest.main()
