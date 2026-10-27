"""Offline, no requests: what the failures of E2 were, and where the end-to-end errors come
from, for REPORT.md section 2. The causes are those of code/failure_causes.py (R-E3-2), each
listed with its dishes (ASA24: code and portion size).

    .venv/bin/python runs/test/diagnostics/failures.py > runs/test/diagnostics/failures.txt
"""
import os
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
RUN = ROOT / 'runs' / 'test'
sys.path.insert(0, str(ROOT / 'code'))
os.chdir(ROOT / 'code')

import evaluate  # noqa: E402
import failure_causes  # noqa: E402
from run_experiment import NUTRITION_XLSX  # noqa: E402

asa24 = pd.read_csv(RUN / 'asa24_nutrition.csv').reset_index(drop=True)
n5k = pd.read_csv(RUN / 'nutrition5k_nutrition.csv').reset_index(drop=True)


def show(failures):
    """Each cause with its count and its dishes (a dish twice when two of its foods failed)."""
    by_cause = defaultdict(list)
    for key, *_, cause in failures:
        by_cause[cause].append(key)
    for cause, keys in sorted(by_cause.items(), key=lambda item: -len(item[1])):
        print(f'  {cause}: {len(keys)}: {", ".join(keys)}')


print('# Food codes: rows without a code after 5 passes')
failures = failure_causes.food_code_failures(asa24, 'asa24')
print('ASA24', len(failures), dict(Counter(key.split()[1] for key, _ in failures)))
show(failures)
failures = failure_causes.food_code_failures(n5k, 'nutrition5k')
print('Nutrition5k', len(failures))
show(failures)

print('\n# Nutrition5k grams: the recognized foods without grams (WeightError)')
coded = n5k['GPTFoodCode'].map(lambda answer: any(codes for _, codes in failure_causes.food_items(answer)))
disclaimers = sum(isinstance(a, str) and '\n\n' in a.strip() for a in n5k.loc[coded, 'GPTAmount'])
failures = failure_causes.grams_failures(n5k)
print(f'dishes asked {int(coded.sum())}, answers with a disclaimer paragraph {disclaimers}')
print(f'foods without grams {len(failures)} in {len({dish for dish, _, _ in failures})} dishes')
show(failures)
print('foods with grams but no code (FoodCodeError):', int(n5k['FoodCodeError'].fillna(0).sum()))

print('\n# ASA24 end to end')
has_code = asa24['GPTFoodCodeE2E'].notna()
not_option = has_code & asa24['GPTPortionDescriptionE2E'].notna() & asa24['PortionUnitE2E'].isna()
print('with a code', int(has_code.sum()), '| not asked (no FNDDS portion)', int((has_code & asa24['PortionShotE2E'].isna()).sum()),
      '| portion answer not an option', int(not_option.sum()), '| estimates', int(asa24['WeightE2E'].notna().sum()))
print('  answers not an option:', dict(Counter(asa24.loc[not_option, 'GPTPortionDescriptionE2E'])))
nutrition = pd.read_excel(NUTRITION_XLSX, sheet_name='FNDDS Nutrient Values', skiprows=1)
reference = evaluate.nutrients_of(nutrition, asa24['FoodCode'], asa24['Weight'])
predicted = evaluate.nutrients_of(nutrition, asa24['GPTFoodCodeE2E'], asa24['WeightE2E'])
errors = (predicted - reference).abs().dropna()
largest = errors['Energy (kcal)'].sort_values(ascending=False).index[:5]
for i in largest:
    row = asa24.loc[i]
    print(f"  {row['Size']} code {int(row['FoodCode'])} -> {int(row['GPTFoodCodeE2E'])}, {row['GPTPortionDescriptionE2E']!r} x "
          f"{row['GPTPortionAmountE2E']:g} = {row['WeightE2E']:.0f} g (reference {row['Weight']:.0f} g), "
          f"energy error {errors.loc[i, 'Energy (kcal)']:.0f} kcal")
same_unit = asa24.index[asa24['GPTPortionDescriptionE2E'] == '1 cup, bite size.']
print('without the two "1 cup, bite size." images:', {t: round(errors.drop(same_unit)[t].mean(), 1) for t in ('Weight (g)', 'Energy (kcal)')},
      'n', len(errors.drop(same_unit)))
print('median absolute errors:', {t: round(errors[t].median(), 1) for t in ('Weight (g)', 'Energy (kcal)')}, 'n', len(errors))

print('\n# Candidates: codes in every candidate list (the empty query, C3)')
for name in ('asa24_food_codes.csv', 'nutrition5k_food_codes.csv'):
    lists = pd.read_csv(RUN / name)['GPTCandidateCodes'].dropna()
    counts = Counter(code for value in lists for code in re.findall(r'\d{8}', value))
    print(name, len(lists), 'lists:', [code for code, count in counts.items() if count == len(lists)])
