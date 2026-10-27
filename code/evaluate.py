"""Evaluation of the ASA24 and Nutrition5k results (CHECKLIST.md D2-D7).

The release has no evaluation code; the metrics follow the paper's "Evaluation metric"
section (paper.txt:242-259 and the right column of 198-228) and the notes of Tables 1-5.
"""
import argparse
import json
import numpy as np
import pandas as pd
from nutrient_estimate import parse_portion_amount
from rag_portion_size import food_items, normalize_portion, parse_food_codes

SIZES = ['Largest', 'Medium', 'Smallest']
LEVELS = ['Exact', 'Close', 'Far', 'Mismatch']
# Tables 1-2: food weight and four nutrients (FNDDS column names)
NUTRIENTS = ['Energy (kcal)', 'Total Fat (g)', 'Carbohydrate (g)', 'Protein (g)']
TARGETS = ['Weight (g)'] + NUTRIENTS
# Nutrition5k labels of each target (dish_metadata)
NUTRITION5K_LABELS = {'Weight (g)': 'total_mass', 'Energy (kcal)': 'total_calories', 'Total Fat (g)': 'total_fat',
                      'Carbohydrate (g)': 'total_carbs', 'Protein (g)': 'total_protein'}
# DietAI24 in Tables 1 and 2 (per dish, per unit), for the comparison
PAPER = {
    'asa24': {'Weight (g)': (49.4, 0.348), 'Energy (kcal)': (47.7, 0.196), 'Total Fat (g)': (1.8, 0.174),
              'Carbohydrate (g)': (6.95, 0.208), 'Protein (g)': (1.38, 0.233)},
    'nutrition5k': {'Weight (g)': (45.1, 0.156), 'Energy (kcal)': (68.2, 0.197), 'Total Fat (g)': (4.01, 0.226),
                    'Carbohydrate (g)': (5.98, 0.212), 'Protein (g)': (3.88, 0.188)},
}


def mae(predicted, reference):
    """MAE per dish, and per unit = MAE / mean reference (notes of Tables 1-2), over the rows
    that have both values."""
    predicted, reference = pd.Series(predicted, dtype=float), pd.Series(reference, dtype=float)
    ok = predicted.notna().values & reference.notna().values
    if not ok.any():
        return {'n': 0, 'per_dish': np.nan, 'per_unit': np.nan}
    error = np.abs(predicted.values[ok] - reference.values[ok])
    return {'n': int(ok.sum()), 'per_dish': float(error.mean()), 'per_unit': float(error.mean() / reference.values[ok].mean())}


def nutrients_of(df_nutrition, codes, grams):
    """The four nutrients of `grams` of each code: per-100 g value x grams / 100 (paper.txt:151-160)."""
    per_100g = df_nutrition.set_index('Food code')[NUTRIENTS].reindex(pd.Series(codes, dtype=float).values)
    values = per_100g.mul(np.asarray(grams, dtype=float) / 100, axis=0).reset_index(drop=True)
    values.insert(0, 'Weight (g)', np.asarray(grams, dtype=float))
    return values


def by_size(df, function):
    """function(rows) for each portion size and for all rows."""
    return {size: function(df[df['Size'] == size] if size != 'Total' else df) for size in SIZES + ['Total']}


def asa24_mae(df, df_nutrition):
    """D2, the paper protocol: rows whose answer includes the labeled code (FoodCodeCommon, D1)
    and whose portion gives grams; nutrients of FoodCodeCommon, so only the portion is
    estimated. Two readings of the weight: the chosen option (TotalWeight, C6; nutrients as
    nutrient_estimate.py computed them) and the amount answer (AmountWeight)."""
    reference = nutrients_of(df_nutrition, df['FoodCode'], df['Weight'])
    option = df[['TotalWeight'] + NUTRIENTS].rename(columns={'TotalWeight': 'Weight (g)'}).reset_index(drop=True)
    amount = nutrients_of(df_nutrition, df['FoodCodeCommon'], df['AmountWeight'])
    result = {}
    for reading, predicted in (('option', option), ('amount', amount)):
        def table(rows):
            return {t: mae(predicted.loc[rows.index, t], reference.loc[rows.index, t]) for t in TARGETS}
        result[reading] = by_size(df.reset_index(drop=True), table)
    return result


def match_level(predicted, label):
    """paper.txt:200-211: Exact, all eight digits; Close, the first two (the subgroup); Far,
    the first (the major group); otherwise Mismatch."""
    predicted, label = str(int(predicted)), str(int(label))
    if predicted == label:
        return 'Exact'
    if predicted[:2] == label[:2]:
        return 'Close'
    if predicted[0] == label[0]:
        return 'Far'
    return 'Mismatch'


def asa24_match_levels(df):
    """D4 (Table 3): over the images with a predicted code ("images where food was successfully
    detected", paper.txt:385-388), cumulative as in Table 3: Close includes Exact, Far includes
    Close, Mismatch = 1 - Far. Two readings: the best level among all predicted codes ('any',
    the reading of FoodCodeCommon) and the first code ('first')."""
    def table(rows):
        out = {}
        for reading in ('any', 'first'):
            found = []
            for answer, label in zip(rows['GPTFoodCode'], rows['FoodCode']):
                codes = parse_food_codes(answer)
                if codes:
                    codes = codes if reading == 'any' else codes[:1]
                    found.append(min(LEVELS.index(match_level(code, label)) for code in codes))
            found = np.array(found)
            out[reading] = {'n': len(found)}
            out[reading].update({level: float((found <= i).mean()) if len(found) else np.nan
                                 for i, level in enumerate(LEVELS[:3])})
            out[reading]['Mismatch'] = float((found == 3).mean()) if len(found) else np.nan
        return out
    return by_size(df, table)


def asa24_portions(df):
    """D5 (Table 5, paper.txt:212-220, 413-433), over the images asked about their portion
    (FoodCodeCommon present). Classification accuracy: the chosen option is the labeled
    portion; an answer that is no option counts as wrong. Prediction error: |amount answer -
    labeled amount| in units, as Table 5 reports it, and in grams (paper.txt:218-220), for
    the chosen option and for the amount answer."""
    def table(rows):
        asked = rows[rows['FoodCodeCommon'].notna()]
        correct = [normalize_portion(a) == normalize_portion(p) if not pd.isna(a) else False
                   for a, p in zip(asked['GPTPortionDescription'], asked['Portion'])]
        amount = asked['GPTPortionAmount'].map(parse_portion_amount)
        return {
            'n': len(asked),
            'classification_accuracy': float(np.mean(correct)) if len(asked) else np.nan,
            'unit_error': mae(amount, asked['LabelAmount']),
            'gram_error_option': mae(asked['TotalWeight'], asked['Weight']),
            'gram_error_amount': mae(asked['AmountWeight'], asked['Weight']),
        }
    return by_size(df, table)


def share(numerator, denominator):
    return float(numerator / denominator) if denominator else np.nan


def asa24_success_rates(df):
    """D6 (paper.txt:224-228 right column, 546-550): an image succeeds when the system gives
    a food code, or a portion, whether right or not. food_code: images with a predicted code,
    over all images (Supplementary Fig. 6a). portion_option / portion_amount: among the images
    asked about their portion, those whose option maps to grams / whose answer has a number.
    nutrients: images with a protocol estimate (D2, option reading), over all images."""
    def table(rows):
        has_code = rows['GPTFoodCode'].map(lambda answer: len(parse_food_codes(answer)) > 0)
        asked = rows[rows['FoodCodeCommon'].notna()]
        return {
            'images': len(rows),
            'food_code': share(has_code.sum(), len(rows)),
            'asked_portion': len(asked),
            'portion_option': share(asked['TotalWeight'].notna().sum(), len(asked)),
            'portion_amount': share(asked['GPTPortionAmount'].map(parse_portion_amount).notna().sum(), len(asked)),
            'nutrients': share(rows['TotalWeight'].notna().sum(), len(rows)),
        }
    return by_size(df, table)


def nutrition5k_success_rates(df):
    """D6 for Nutrition5k (Supplementary Table 2): food_code per dish; portion per dish, the
    dishes whose recognized foods all have grams, over the dishes with a food code; portion
    per food item, the recognized foods with grams. A dish has a food code when one of its
    foods (rag_portion_size.food_items, R-C8-1) has one."""
    has_code = df['GPTFoodCode'].map(lambda answer: any(codes for _, codes in food_items(answer)))
    coded = df[has_code & (df['IngredientNum'] > 0)]
    foods = coded['IngredientNum'].sum()
    return {
        'dishes': len(df),
        'food_code_per_dish': share(has_code.sum(), len(df)),
        'portion_per_dish': share((coded['WeightError'] == 0).sum(), len(coded)),
        'portion_per_food_item': share(foods - coded['WeightError'].sum(), foods),
        'food_items': int(foods),
    }


def nutrition5k_mae(df):
    """D7 (Table 2). 'complete': dishes with a food code, grams for every recognized food and
    every food's code in FNDDS (the per-dish success of D6). 'any_estimate': every dish with
    an estimate, partial sums included."""
    predicted = df[['GPTWeight'] + NUTRIENTS].rename(columns={'GPTWeight': 'Weight (g)'})
    complete = (df['IngredientNum'] > 0) & (df['WeightError'] == 0) & (df['FoodCodeError'] == 0)
    return {name: {t: mae(predicted.loc[rows, t], df.loc[rows, NUTRITION5K_LABELS[t]]) for t in TARGETS}
            for name, rows in (('complete', complete), ('any_estimate', df['GPTWeight'].notna()))}


def asa24_end_to_end(df, df_nutrition):
    """D3, our addition: no reference label in the inference. The first predicted FNDDS code
    and its FNDDS portions; MAE over the images with an estimate, the rest counted as failures."""
    df = df.reset_index(drop=True)
    reference = nutrients_of(df_nutrition, df['FoodCode'], df['Weight'])
    predicted = nutrients_of(df_nutrition, df['GPTFoodCodeE2E'], df['WeightE2E'])

    def table(rows):
        out = {t: mae(predicted.loc[rows.index, t], reference.loc[rows.index, t]) for t in TARGETS}
        out['images'] = len(rows)
        out['success_rate'] = float(predicted.loc[rows.index, 'Weight (g)'].notna().mean()) if len(rows) else np.nan
        return out
    return by_size(df, table)


def evaluate_run(asa24_path, nutrition5k_path, nutrition_path):
    df_nutrition = pd.read_excel(nutrition_path, sheet_name='FNDDS Nutrient Values', skiprows=1)
    metrics = {}
    if asa24_path:
        df = pd.read_csv(asa24_path)
        metrics['asa24'] = {'images': len(df), 'mae_protocol': asa24_mae(df, df_nutrition),
                            'match_levels': asa24_match_levels(df), 'portions': asa24_portions(df),
                            'success_rates': asa24_success_rates(df)}
        if 'WeightE2E' in df.columns:
            metrics['asa24']['mae_end_to_end'] = asa24_end_to_end(df, df_nutrition)
    if nutrition5k_path:
        df = pd.read_csv(nutrition5k_path)
        metrics['nutrition5k'] = {'dishes': len(df), 'mae': nutrition5k_mae(df),
                                  'success_rates': nutrition5k_success_rates(df)}
    return metrics


def no_nan(value):
    """JSON without NaN (written as null)."""
    if isinstance(value, dict):
        return {k: no_nan(v) for k, v in value.items()}
    if isinstance(value, float) and np.isnan(value):
        return None
    return value


def fmt(value, digits=3):
    return '–' if value is None or (isinstance(value, float) and np.isnan(value)) else f'{value:.{digits}g}'


def mae_table(rows, dataset):
    """Markdown rows: target, per dish, per unit, n, and the paper's values."""
    lines = ['| 目标 | per dish | per unit | n | 论文 per dish | 论文 per unit |', '|---|---|---|---|---|---|']
    for target in TARGETS:
        m, paper = rows[target], PAPER[dataset][target]
        lines.append(f"| {target} | {fmt(m['per_dish'])} | {fmt(m['per_unit'])} | {m['n']} | {paper[0]} | {paper[1]} |")
    return '\n'.join(lines)


def markdown(metrics):
    out = []
    if 'asa24' in metrics:
        a = metrics['asa24']
        out.append(f"## ASA24（{a['images']} 张）\n")
        out.append('### 营养 MAE，论文协议，option 口径（D2，合计）\n\n' + mae_table(a['mae_protocol']['option']['Total'], 'asa24'))
        out.append('### 营养 MAE，论文协议，amount 口径（D2，合计）\n\n' + mae_table(a['mae_protocol']['amount']['Total'], 'asa24'))
        if 'mae_end_to_end' in a:
            out.append('### 营养 MAE，端到端（D3，合计）\n\n' + mae_table(a['mae_end_to_end']['Total'], 'asa24'))
        lines = ['| 档 | 编码成功率 | 有共同编码 | 份量成功率（option） | 营养成功率 | Exact | Close | Far | Mismatch | 份量分类准确率 | 单位误差 | 端到端成功率 |',
                 '|---|---|---|---|---|---|---|---|---|---|---|---|']
        for size in SIZES + ['Total']:
            sr, ml, po = a['success_rates'][size], a['match_levels'][size]['any'], a['portions'][size]
            e2e = a.get('mae_end_to_end', {}).get(size, {}).get('success_rate')
            lines.append(f"| {size} | {fmt(sr['food_code'])} ({sr['images']}) | {sr['asked_portion']} | {fmt(sr['portion_option'])} | "
                         f"{fmt(sr['nutrients'])} | {fmt(ml['Exact'])} | {fmt(ml['Close'])} | {fmt(ml['Far'])} | {fmt(ml['Mismatch'])} | "
                         f"{fmt(po['classification_accuracy'])} | {fmt(po['unit_error']['per_dish'])} | {fmt(e2e)} |")
        out.append('### 按档（D4 any 口径、D5、D6）\n\n' + '\n'.join(lines))
    if 'nutrition5k' in metrics:
        n = metrics['nutrition5k']
        sr = n['success_rates']
        out.append(f"## Nutrition5k（{n['dishes']} 道菜）\n")
        out.append('### 营养 MAE，完整的菜（D7）\n\n' + mae_table(n['mae']['complete'], 'nutrition5k'))
        out.append('### 营养 MAE，所有有估计的菜（D7）\n\n' + mae_table(n['mae']['any_estimate'], 'nutrition5k'))
        out.append(f"成功率（D6）：编码按菜 {fmt(sr['food_code_per_dish'])}（论文 0.989），份量按菜 {fmt(sr['portion_per_dish'])}（论文 0.842），"
                   f"份量按食物项 {fmt(sr['portion_per_food_item'])}（论文 0.805，{sr['food_items']} 项）。")
    return '\n\n'.join(out) + '\n'


def main(args):
    metrics = evaluate_run(args.asa24, args.nutrition5k, args.nutrition_path)
    with open(args.output_json, 'w') as f:
        json.dump(no_nan(metrics), f, indent=1, ensure_ascii=False)
    with open(args.output_md, 'w') as f:
        f.write(markdown(metrics))


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Metrics of one run (CHECKLIST.md D2-D7).")
    parser.add_argument("--asa24", help="ASA24 output of nutrient_estimate.py")
    parser.add_argument("--nutrition5k", help="Nutrition5k output of nutrient_estimate_mix.py")
    parser.add_argument("--nutrition_path", default='../FNDDS/2019-2020 FNDDS At A Glance - FNDDS Nutrient Values.xlsx')
    parser.add_argument("--output_json", default='metrics.json')
    parser.add_argument("--output_md", default='metrics.md')
    return parser.parse_args(argv)


if __name__ == "__main__":
    main(parse_args())
