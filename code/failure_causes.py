"""Offline: what the failures of a run were (REPORT.md section 2), read from the run's tables
with the pipeline's own parsing. Not a metric of the paper; each failure keeps its image or dish.
"""
import contextlib
import io
import re

import pandas as pd

from nutrient_estimate_mix import match_food_codes, parse_food_items
from rag_portion_size import food_items, food_name, parse_food_codes

NO_CODES = 'No appropriate food codes found'
CODE_DECLINED = 'declined in the code step'
NOT_A_NUMBER = 'answered without a number of grams'
DECLINED = 'the whole grams answer declined, no number'
SPLIT = 'a combined name answered as its parts'
RENAMED = 'renamed, or split or merged otherwise'
# the parts of a combined FNDDS name ("pork, potatoes, and vegetables", "rice with beans")
PARTS = re.compile(r',\s*(?:and\s+)?|\s+and\s+|\s+with\s+')


def food_code_failures(df, dataset):
    """(dish, or ASA24 code and portion size, cause) for each row without a code after its
    passes: the code step's "no codes" sentence, or another answer without a code (a decline)."""
    if dataset == 'nutrition5k':
        has_code = df['GPTFoodCode'].map(lambda answer: any(codes for _, codes in food_items(answer)))
        key = lambda row: row['dish_id']
    else:
        has_code = df['GPTFoodCode'].map(lambda answer: bool(parse_food_codes(answer)))
        key = lambda row: f"{int(row['FoodCode'])} {row['Size']}"
    return [(key(row), NO_CODES if str(row['GPTFoodDescription']).startswith(NO_CODES) else CODE_DECLINED)
            for _, row in df[~has_code].iterrows()]


def grams_failures(df):
    """(dish, food, cause) for each recognized food of a dish with a code that got no grams
    (its WeightError). An answer without any number declined as a whole (R-E3-2: it was taken
    for a renaming); a food named with a value that is no number was answered without grams;
    otherwise the food's name is not in the answer, as its parts or renamed."""
    failures = []
    for _, row in df.iterrows():
        if not any(codes for _, codes in food_items(row['GPTFoodCode'])):
            continue
        with contextlib.redirect_stdout(io.StringIO()):  # it prints the lines it cannot read
            weights = parse_food_items(row['GPTAmount'])
        weights = weights if isinstance(weights, dict) else {}
        answered = {food_name(key).lower() for key in weights}
        numbers = any(not pd.isna(weight) for weight in weights.values())
        for name, (_, weight) in match_food_codes(row['GPTFoodCode'], weights).items():
            if not pd.isna(weight):
                continue
            parts = [part.strip() for part in PARTS.split(name) if part.strip()]
            if name in answered:
                cause = NOT_A_NUMBER
            elif not numbers:
                cause = DECLINED
            elif len(parts) > 1 and any(part in answered for part in parts):
                cause = SPLIT
            else:
                cause = RENAMED
            failures.append((row['dish_id'], name, cause))
    return failures
