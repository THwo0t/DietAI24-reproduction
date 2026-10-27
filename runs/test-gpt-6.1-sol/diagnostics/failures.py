"""Offline failure counts using the same frozen rules as the gpt-4o report."""
import json
import sys
from collections import Counter
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
RUN = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'code'))
import failure_causes

asa = pd.read_csv(RUN / 'asa24_nutrition.csv')
n5k = pd.read_csv(RUN / 'nutrition5k_nutrition.csv')
grams = failure_causes.grams_failures(n5k)
assert len(grams) == int(n5k.WeightError.fillna(0).sum())
result = {
    'asa24_code_failures': failure_causes.food_code_failures(asa, 'asa24'),
    'nutrition5k_code_failures': failure_causes.food_code_failures(n5k, 'nutrition5k'),
    'grams_failure_counts': dict(Counter(cause for _, _, cause in grams)),
    'grams_failure_items': grams,
    'grams_failure_dishes': len({dish for dish, _, _ in grams}),
    'food_code_error_items': int(n5k.FoodCodeError.fillna(0).sum()),
    'attempts': {name: {'total': int(df.GPTAttempts.sum()), 'more_than_one': int((df.GPTAttempts > 1).sum())}
                 for name, df in (('asa24', asa), ('nutrition5k', n5k))},
}
(Path(__file__).parent / 'failures.json').write_text(json.dumps(result, ensure_ascii=False, indent=2))
print(json.dumps(result, ensure_ascii=False, indent=2))
