"""F5: offline comparison of frozen runs, with paired cluster bootstrap.

No inference, prompts, parsing, or evaluation definitions are changed. Difference is
always comparison minus baseline; negative MAE differences favor the comparison.
ASA24 resamples the sampled codes and keeps all sizes and failures. Nutrition5k
resamples dishes. Intervals condition on the observed answers, not model randomness.
"""
import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

import evaluate
from rag_portion_size import parse_food_codes, normalize_portion

ROOT = Path(__file__).resolve().parents[1]
SEED, REPLICATES = 20261027, 10000


def align(left, right, keys, labels):
    """Reject duplicates, differing samples, and changed ground truth before pairing."""
    for frame in (left, right):
        if frame.duplicated(keys).any():
            raise ValueError('duplicate sample keys')
    a, b = (frame.set_index(keys).sort_index() for frame in (left, right))
    if not a.index.equals(b.index):
        raise ValueError('sample keys differ')
    pd.testing.assert_frame_equal(a[labels], b[labels], check_dtype=False, check_exact=True)
    return a.reset_index(), b.reset_index()


def bootstrap_difference(left, right, groups, replicates=REPLICATES, seed=SEED):
    """Paired draws, allowing distinct conditional subsets (NaN = failure).

    The same sampled groups feed both error means. The common-subset caller masks
    both sides identically. No-estimate replicates are counted and excluded explicitly.
    """
    frame = pd.DataFrame({'left': np.asarray(left, float), 'right': np.asarray(right, float),
                          'group': np.asarray(groups)})
    grouped = frame.groupby('group')[['left', 'right']]
    sums, counts = grouped.sum(), grouped.count()
    if len(sums) == 0:
        raise ValueError('empty sampling frame')
    draws = np.random.default_rng(seed).integers(0, len(sums), size=(replicates, len(sums)))
    total = sums.to_numpy()[draws].sum(axis=1)
    n = counts.to_numpy()[draws].sum(axis=1)
    valid = (n > 0).all(axis=1)
    diff = total[valid, 1] / n[valid, 1] - total[valid, 0] / n[valid, 0]
    interval = np.percentile(diff, [2.5, 97.5]).tolist() if len(diff) else [None, None]
    means = [float(frame[col].mean()) if frame[col].notna().any() else None for col in ('left', 'right')]
    return {'baseline': means[0], 'comparison': means[1],
            'difference': means[1] - means[0] if None not in means else None,
            'ci95': interval, 'n': counts.sum().astype(int).tolist(),
            'groups_with_estimate': (counts > 0).sum().astype(int).tolist(),
            'replicates_without_estimate': int((~valid).sum())}


def mae_comparison(left, right, reference, groups, left_ok, right_ok, common=False):
    result = {}
    if common:
        left_ok = right_ok = left_ok & right_ok
    for target in evaluate.TARGETS:
        le = (left[target] - reference[target]).abs().where(left_ok)
        re = (right[target] - reference[target]).abs().where(right_ok)
        if common:
            valid = le.notna() & re.notna()
            le, re = le.where(valid), re.where(valid)
        item = bootstrap_difference(le, re, groups)
        # per unit uses each model's own valid reference mean, matching evaluate.mae.
        item['per_unit'] = [evaluate.mae(pred[target].where(ok), reference[target])['per_unit']
                            for pred, ok in ((left, le.notna()), (right, re.notna()))]
        result[target] = item
    return result


def exact_mask(frame):
    return pd.Series([int(code) in {int(c) for c in parse_food_codes(answer)}
                      for code, answer in zip(frame.FoodCode, frame.GPTFoodCode)], index=frame.index)


def complete_mask(frame):
    return (frame.IngredientNum > 0) & (frame.WeightError == 0) & (frame.FoodCodeError == 0)


def weight_bias(frame, selected):
    selected = selected & frame.GPTWeight.notna() & frame.total_mass.notna()
    pred, ref = frame.loc[selected, 'GPTWeight'], frame.loc[selected, 'total_mass']
    positive = ref > 0
    return {'n': int(selected.sum()), 'mean_signed_error_g': float((pred - ref).mean()),
            'ratio_n': int(positive.sum()), 'median_predicted_reference_ratio': float((pred[positive] / ref[positive]).median())}


def compare(baseline_dir, comparison_dir, nutrition_path):
    base, other = Path(baseline_dir), Path(comparison_dir)
    configs = [json.loads((p / 'config.json').read_text()) for p in (base, other)]
    for key in ('split', 'inputs_sha256', 'image_size'):
        if configs[0][key] != configs[1][key]:
            raise ValueError(f'run configurations differ in {key}')
    if configs[0]['models']['embedding'] != configs[1]['models']['embedding']:
        raise ValueError('embedding models differ')
    if configs[0]['code_sha256']['rag_portion_size.py'] != configs[1]['code_sha256']['rag_portion_size.py']:
        raise ValueError('portion prompts or parsers differ')
    for saved in configs:
        if not saved['invocations'] or saved['invocations'][-1]['status'] != 'completed':
            raise ValueError('run is not completed')
    nutrition = pd.read_excel(nutrition_path, sheet_name='FNDDS Nutrient Values', skiprows=1)
    asa = align(*[pd.read_csv(p / 'asa24_nutrition.csv') for p in (base, other)],
                ['FoodCode', 'Image', 'Size'], ['Weight', 'Portion', 'LabelAmount'])
    n5k = align(*[pd.read_csv(p / 'nutrition5k_nutrition.csv') for p in (base, other)],
                ['dish_id'], list(evaluate.NUTRITION5K_LABELS.values()))
    a, b = asa
    reference = evaluate.nutrients_of(nutrition, a.FoodCode, a.Weight)
    predictions = [f[['TotalWeight'] + evaluate.NUTRIENTS].rename(columns={'TotalWeight': 'Weight (g)'}) for f in asa]
    exact = [exact_mask(f) for f in asa]
    common_exact = exact[0] & exact[1]
    accuracy = []
    for f in asa:
        accuracy.append(pd.Series([normalize_portion(answer) == normalize_portion(label) if pd.notna(answer) else False
                                   for answer, label in zip(f.GPTPortionDescription, f.Portion)], index=f.index))
    portion_delta = bootstrap_difference(accuracy[0].astype(float).where(common_exact),
                                         accuracy[1].astype(float).where(common_exact), a.FoodCode)
    asa_result = {
        'exact_n': [int(mask.sum()) for mask in exact], 'common_exact_n': int(common_exact.sum()),
        'common_exact_keys': a.loc[common_exact, ['FoodCode', 'Image', 'Size']].to_dict('records'),
        'own_subset_mae': mae_comparison(*predictions, reference, a.FoodCode, *exact),
        'common_subset_mae': mae_comparison(*predictions, reference, a.FoodCode, *exact, common=True),
        'common_portion_accuracy': portion_delta,
    }
    a, b = n5k
    complete = [complete_mask(f) for f in n5k]
    common_complete = complete[0] & complete[1]
    predictions = [f[['GPTWeight'] + evaluate.NUTRIENTS].rename(columns={'GPTWeight': 'Weight (g)'}) for f in n5k]
    reference = pd.DataFrame({target: a[label] for target, label in evaluate.NUTRITION5K_LABELS.items()})
    n5k_result = {
        'complete_n': [int(mask.sum()) for mask in complete], 'common_complete_n': int(common_complete.sum()),
        'common_complete_dishes': a.loc[common_complete, 'dish_id'].tolist(),
        'own_subset_mae': mae_comparison(*predictions, reference, a.dish_id, *complete),
        'common_subset_mae': mae_comparison(*predictions, reference, a.dish_id, *complete, common=True),
        'own_subset_weight_bias': [weight_bias(f, mask) for f, mask in zip(n5k, complete)],
        'common_subset_weight_bias': [weight_bias(f, common_complete) for f in n5k],
    }
    return {'baseline': str(base), 'comparison': str(other),
            'models': [c['models']['llm'] for c in configs], 'temperatures': [c['temperature'] for c in configs],
            'bootstrap': {'seed': SEED, 'replicates': REPLICATES, 'direction': 'comparison minus baseline',
                          'asa24_unit': 'sampled code, all sizes and failures', 'nutrition5k_unit': 'dish',
                          'scope': 'conditional on observed answers; excludes model randomness and paper uncertainty'},
            'asa24': asa_result, 'nutrition5k': n5k_result,
            'metrics': [json.loads((p / 'metrics.json').read_text()) for p in (base, other)]}


def number(value):
    return '—' if value is None or not np.isfinite(value) else f'{value:.4g}'


def percent(value):
    return number(None if value is None else value * 100)


def markdown(result):
    lines = ['# 模型对照（离线生成）', '',
             f"模型：{result['models'][0]} → {result['models'][1]}；temperature：{result['temperatures']}。",
             '差值 = 新模型 − 基线；MAE 负差值表示改善。各自子集有选择差异，解释模型差别优先看共同子集。', '',
             '| 数据集 | 子集 | 目标 | n 基线／新模型 | MAE per dish／per unit 基线 | MAE per dish／per unit 新模型 | MAE 差值 | 配对 95% 区间 | 论文 per dish／per unit |',
             '|---|---|---|---|---|---|---|---|---|']
    for dataset in ('asa24', 'nutrition5k'):
        for subset in ('own_subset_mae', 'common_subset_mae'):
            for target, cell in result[dataset][subset].items():
                ci = '～'.join(number(v) for v in cell['ci95'])
                subset_name = '各自成功子集' if subset == 'own_subset_mae' else '共同成功子集'
                paper = evaluate.PAPER[dataset][target]
                lines.append(f"| {dataset} | {subset_name} | {target} | {cell['n'][0]}／{cell['n'][1]} | "
                             f"{number(cell['baseline'])}／{number(cell['per_unit'][0])} | "
                             f"{number(cell['comparison'])}／{number(cell['per_unit'][1])} | {number(cell['difference'])} | {ci} | "
                             f"{number(paper[0])}／{number(paper[1])} |")
    lines += ['', '| 模型 | ASA24 编码成功率 | Nutrition5k 编码成功率 | Nutrition5k 份量成功率（菜／食物项） |',
              '|---|---|---|---|']
    for model, metrics in zip(result['models'], result['metrics']):
        sr = metrics['nutrition5k']['success_rates']
        lines.append(f"| {model} | {percent(metrics['asa24']['success_rates']['Total']['food_code'])}% | "
                     f"{percent(sr['food_code_per_dish'])}% | {percent(sr['portion_per_dish'])}%／"
                     f"{percent(sr['portion_per_food_item'])}% |")
    lines += ['', '| 模型 | 读法 | 有编码 n | Exact n（%） | Close % | Far % | Mismatch % |',
              '|---|---|---|---|---|---|---|']
    for model, metrics in zip(result['models'], result['metrics']):
        for reading in ('any', 'first'):
            cell = metrics['asa24']['match_levels']['Total'][reading]
            n = cell['n']
            exact_n = round(cell['Exact'] * n) if n else 0
            lines.append(f"| {model} | {reading} | {n} | {exact_n}（{percent(cell['Exact'])}） | "
                         f"{percent(cell['Close'])} | {percent(cell['Far'])} | {percent(cell['Mismatch'])} |")
    cell = result['asa24']['common_portion_accuracy']
    lines += ['', f"共同 Exact {result['asa24']['common_exact_n']} 行的份量分类准确率："
              f"{percent(cell['baseline'])}% → {percent(cell['comparison'])}%；"
              f"差值 {percent(cell['difference'])} 个百分点，95% 区间 "
              + '～'.join(percent(value) for value in cell['ci95']) + '。', '',
              '| Nutrition5k 子集 | 模型 | n | 平均符号误差 g（预测−参考） | 预测／参考中位数 |',
              '|---|---|---|---|---|']
    for subset in ('own_subset_weight_bias', 'common_subset_weight_bias'):
        for model, cell in zip(result['models'], result['nutrition5k'][subset]):
            subset_name = '各自完整菜' if subset == 'own_subset_weight_bias' else '共同完整菜'
            lines.append(f"| {subset_name} | {model} | {cell['n']} | {number(cell['mean_signed_error_g'])} | "
                         f"{number(cell['median_predicted_reference_ratio'])} |")
    lines += ['', 'ASA24 按抽到的全部编码成组配对重抽，保留三档和失败；Nutrition5k 按菜配对重抽。',
              '10,000 次，种子 20261027；没有估计的重抽次数记录在 JSON。区间不含模型随机性，重复图片跨编码的相关未建模。',
              '完整识别指标和无估计的重抽次数保存在 comparison.json。']
    return '\n'.join(lines) + '\n'


def clean(value):
    if isinstance(value, dict):
        return {k: clean(v) for k, v in value.items()}
    if isinstance(value, list):
        return [clean(v) for v in value]
    if isinstance(value, float) and not np.isfinite(value):
        return None
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', type=Path, default=ROOT / 'runs/test')
    parser.add_argument('--comparison', type=Path, required=True)
    parser.add_argument('--nutrition', type=Path, default=ROOT / 'FNDDS/2019-2020 FNDDS At A Glance - FNDDS Nutrient Values.xlsx')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = clean(compare(args.baseline, args.comparison, args.nutrition))
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / 'comparison.json').write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
    (args.output / 'comparison.md').write_text(markdown(result))


if __name__ == '__main__':
    main()
