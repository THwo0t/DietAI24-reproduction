"""Offline, no requests: why most ASA24 images of E2 have no exact code, for REPORT.md
section 2.2. Exact is the 'any' reading of evaluate.asa24_match_levels (the label is one of
the predicted codes). Two views of the images with a predicted code but no exact one: where
the label was lost (not among the retrieved candidates, or retrieved and not chosen), and
whether the predicted code is one that the ASA24 metadata links to the same photo.

    .venv/bin/python runs/test/diagnostics/exact_misses.py > runs/test/diagnostics/exact_misses.txt
"""
import ast
import argparse
import os
import sys
from collections import Counter
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--run-dir', type=Path, default=ROOT / 'runs' / 'test')
RUN = parser.parse_args().run_dir.resolve()
sys.path.insert(0, str(ROOT / 'code'))
os.chdir(ROOT / 'code')

from evaluate import LEVELS, match_level  # noqa: E402
from rag_portion_size import parse_food_codes  # noqa: E402

df = pd.read_csv(RUN / 'asa24_food_codes.csv')
fndds = pd.read_excel(ROOT / 'FNDDS' / '2019-2020 FNDDS At A Glance - Foods and Beverages.xlsx', skiprows=1)
desc = dict(zip(fndds['Food code'].astype(int), fndds['Main food description']))
assoc = pd.read_excel(ROOT / 'ASA24' / 'ASA24_ImageMetadata.xlsx', sheet_name='AssociatedCodes')
assoc = assoc.dropna(subset=['FoodCode'])
photo_codes = assoc.groupby(assoc['Image'].astype(str))['FoodCode'].apply(
    lambda codes: {int(code) for code in codes} & set(desc))


def codes_of(answer):
    return [int(code) for code in parse_food_codes(answer)] if isinstance(answer, str) else []


print(f'Test rows: {len(df)}; different image files: {df.Image.nunique()}')
labels = df.groupby('Image')['FoodCode'].apply(list)
print('Image files that are the test image of more than one labeled code:')
for image, codes in labels[labels.map(len) > 1].items():
    print(f'  {image} ({len(codes)}): ' + '; '.join(desc[code] for code in codes))

linked = df.Image.map(lambda image: len(photo_codes.get(image, set())))
print(f'\nRows whose photo the ASA24 metadata links to more than one FNDDS 2019-2020 code: '
      f'{(linked > 1).sum()} of {len(df)} ({df[linked > 1].FoodCode.nunique()} of '
      f'{df.FoodCode.nunique()} codes); codes per photo: median {linked.median():g}, max {linked.max()}')

rows = []
for _, row in df.iterrows():
    predicted = codes_of(row.GPTFoodCode)
    if not predicted:
        continue
    candidates = [int(code) for code in ast.literal_eval(row.GPTCandidateCodes)]
    same_photo = set(predicted) & photo_codes.get(row.Image, set())
    rows.append({'exact': row.FoodCode in predicted, 'retrieved': row.FoodCode in candidates,
                 'same_photo': bool(same_photo),
                 'level': LEVELS[min(LEVELS.index(match_level(code, row.FoodCode)) for code in predicted)],
                 'label': desc[row.FoodCode], 'predicted': desc.get(predicted[0], predicted[0]),
                 'size': row.Size})
rows = pd.DataFrame(rows)
missed = rows[~rows.exact]
print(f'\nRows with a predicted code: {len(rows)}; exact: {rows.exact.sum()}; not exact: {len(missed)}')
print(f'  label not among the retrieved candidates: {(~missed.retrieved).sum()}')
print(f'  label retrieved, another code chosen: {missed.retrieved.sum()}')
same = missed[missed.same_photo]
print(f'  predicted code linked by the ASA24 metadata to the same photo: {len(same)} '
      f'({dict(Counter(same.level))})')
for _, row in same.drop_duplicates('label').iterrows():
    print(f'    {row["size"]:8s} label: {row.label} | predicted: {row.predicted}')
