"""Offline, no requests: 95% bootstrap intervals of the per-dish MAE of E2's main readings,
from the run's tables with the pairs evaluate.py uses. Not part of the paper's metrics (the
paper reports no interval); for reading the small n.

The resampled unit follows the sampling design (R-E2-2):
- ASA24: 50 codes drawn from the 284 eligible ones (B4), each with its three portion sizes.
  A replicate draws 50 codes with replacement and keeps all three rows of each, failures
  included; its MAE is the errors' sum over the rows with an estimate divided by their number,
  so the interval is one of the MAE on the conditional subset with an estimate, whose size
  varies. An image shared by several codes is not treated as one, so the interval may be
  narrow. It covers drawing codes from the 284-code frame under this run's answers, not the
  randomness of the model, nor the paper's 1,000 codes.
- Nutrition5k: one row per dish (150 drawn from 1,906); the complete dishes are resampled.

Percentile intervals of 10,000 replicates; each reading draws from its own generator with the
same seed.

    .venv/bin/python runs/test/diagnostics/bootstrap.py > runs/test/diagnostics/bootstrap.txt
"""
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
RUN = ROOT / 'runs' / 'test'
sys.path.insert(0, str(ROOT / 'code'))
os.chdir(ROOT / 'code')

import evaluate  # noqa: E402
from run_experiment import NUTRITION_XLSX  # noqa: E402

REPLICATES, SEED = 10000, 20261027
nutrition = pd.read_excel(NUTRITION_XLSX, sheet_name='FNDDS Nutrient Values', skiprows=1)
asa24 = pd.read_csv(RUN / 'asa24_nutrition.csv').reset_index(drop=True)
n5k = pd.read_csv(RUN / 'nutrition5k_nutrition.csv').reset_index(drop=True)

reference = evaluate.nutrients_of(nutrition, asa24['FoodCode'], asa24['Weight'])
option = asa24[['TotalWeight'] + evaluate.NUTRIENTS].rename(columns={'TotalWeight': 'Weight (g)'})
end_to_end = evaluate.nutrients_of(nutrition, asa24['GPTFoodCodeE2E'], asa24['WeightE2E'])
complete = (n5k['IngredientNum'] > 0) & (n5k['WeightError'] == 0) & (n5k['FoodCodeError'] == 0)
n5k_predicted = n5k[['GPTWeight'] + evaluate.NUTRIENTS].rename(columns={'GPTWeight': 'Weight (g)'})[complete]
n5k_reference = pd.DataFrame({t: n5k.loc[complete, label] for t, label in evaluate.NUTRITION5K_LABELS.items()})

print('| reading | unit resampled | target | n (rows; codes or dishes) | MAE per dish | 95% interval | replicates without an estimate |')
print('|---|---|---|---|---|---|---|')
for reading, predicted in (('ASA24 paper protocol, option', option), ('ASA24 end to end', end_to_end)):
    errors = (predicted[evaluate.TARGETS] - reference[evaluate.TARGETS]).abs()
    sums = errors.groupby(asa24['FoodCode']).sum()  # NaN, no estimate, adds nothing
    counts = errors.notna().groupby(asa24['FoodCode']).sum()
    draws = np.random.default_rng(SEED).integers(0, len(sums), size=(REPLICATES, len(sums)))
    for target in evaluate.TARGETS:
        total, rows = sums[target].to_numpy()[draws].sum(axis=1), counts[target].to_numpy()[draws].sum(axis=1)
        mae = total[rows > 0] / rows[rows > 0]
        low, high = np.percentile(mae, [2.5, 97.5])
        n, codes = int(counts[target].sum()), int((counts[target] > 0).sum())
        print(f'| {reading} | code, its three sizes | {target} | {n}; {codes} codes | {sums[target].sum() / n:.3g} | '
              f'{low:.3g}–{high:.3g} | {int((rows == 0).sum())} |')
draws = np.random.default_rng(SEED).integers(0, int(complete.sum()), size=(REPLICATES, int(complete.sum())))
for target in evaluate.TARGETS:
    error = (n5k_predicted[target] - n5k_reference[target]).abs().to_numpy()
    low, high = np.percentile(error[draws].mean(axis=1), [2.5, 97.5])
    print(f'| Nutrition5k complete dishes | dish | {target} | {len(error)}; {len(error)} dishes | {error.mean():.3g} | '
          f'{low:.3g}–{high:.3g} | 0 |')
