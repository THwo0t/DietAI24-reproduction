"""E3: the tables of REPORT.md that set a run's metrics (metrics.json of evaluate.py) beside the
paper's: Tables 1-3 and 5, Supplementary Table 2 and Supplementary Fig. 6a.

    python report_tables.py ../runs/test/metrics.json
"""
import argparse
import json

from evaluate import PAPER, SIZES, TARGETS, fmt

# Table 3, GPT-4 Turbo (the model of DietAI24): Exact, Close, Far, Mismatch (%) per portion size
PAPER_MATCH = {'Largest': (29.1, 77.3, 84.5, 14.5), 'Medium': (26.3, 68.3, 78.4, 21.6), 'Smallest': (22.1, 59.3, 71.9, 28.1)}
# Table 5: classification accuracy (%) and prediction error (units) per portion size
PAPER_PORTIONS = {'Largest': (68.4, 0.72), 'Medium': (85, 0.31), 'Smallest': (86.7, 0.16), 'Total': (74.3, 0.55)}
# Supplementary Table 2 (Nutrition5k, %): food code per dish, portion per dish, portion per food item
PAPER_N5K_SR = (98.9, 84.2, 80.5)


def pct(value):
    return fmt(None if value is None else value * 100)


def mae_cell(m):
    return f"{fmt(m['per_dish'])} / {fmt(m['per_unit'])} ({m['n']})"


def mae_tables(metrics):
    a, n = metrics['asa24'], metrics['nutrition5k']
    lines = [f"ASA24（{a['images']} 张），per dish / per unit（n）：", '',
             '| 目标 | 论文协议 option | 论文协议 amount | 端到端 | 论文 Table 1 |', '|---|---|---|---|---|']
    for target in TARGETS:
        lines.append(f"| {target} | {mae_cell(a['mae_protocol']['option']['Total'][target])} | "
                     f"{mae_cell(a['mae_protocol']['amount']['Total'][target])} | {mae_cell(a['mae_end_to_end']['Total'][target])} | "
                     f"{PAPER['asa24'][target][0]} / {PAPER['asa24'][target][1]} |")
    lines += ['', f"Nutrition5k（{n['dishes']} 道菜），per dish / per unit（n）：", '',
              '| 目标 | 完整的菜 | 所有有估计的菜 | 论文 Table 2 |', '|---|---|---|---|']
    for target in TARGETS:
        lines.append(f"| {target} | {mae_cell(n['mae']['complete'][target])} | {mae_cell(n['mae']['any_estimate'][target])} | "
                     f"{PAPER['nutrition5k'][target][0]} / {PAPER['nutrition5k'][target][1]} |")
    return lines


def success_table(metrics):
    a, n = metrics['asa24'], metrics['nutrition5k']
    sr, e2e, nsr = a['success_rates'], a['mae_end_to_end'], n['success_rates']
    total = sr['Total']
    codes_by_size = '、'.join(f"{size} {pct(sr[size]['food_code'])}" for size in SIZES)
    e2e_by_size = '、'.join(f"{size} {pct(e2e[size]['success_rate'])}" for size in SIZES)
    return ['| 指标（%） | 本次 | 论文 |', '|---|---|---|',
            f"| ASA24 编码成功率 | {pct(total['food_code'])}（{codes_by_size}） | 84–93（Supplementary Fig. 6a，GPT-4 Turbo 各档） |",
            f"| ASA24 有共同编码、被问份量的图片 | {total['asked_portion']} / {total['images']} | – |",
            f"| ASA24 份量成功率：option、amount（分母是被问份量的图片） | {pct(total['portion_option'])}、{pct(total['portion_amount'])} | – |",
            f"| ASA24 营养成功率，论文协议 | {pct(total['nutrients'])} | – |",
            f"| ASA24 端到端成功率 | {pct(e2e['Total']['success_rate'])}（{e2e_by_size}） | – |",
            f"| Nutrition5k 编码，按菜 | {pct(nsr['food_code_per_dish'])} | {PAPER_N5K_SR[0]} |",
            f"| Nutrition5k 份量，按菜（分母是有编码的菜） | {pct(nsr['portion_per_dish'])} | {PAPER_N5K_SR[1]} |",
            f"| Nutrition5k 份量，按食物项 | {pct(nsr['portion_per_food_item'])}（{nsr['food_items']} 项） | {PAPER_N5K_SR[2]} |"]


def match_table(metrics):
    levels = metrics['asa24']['match_levels']
    lines = ['| 档 | n | Exact | Close | Far | Mismatch | 论文 Exact | 论文 Close | 论文 Far | 论文 Mismatch |',
             '|---|---|---|---|---|---|---|---|---|---|']
    for size in SIZES + ['Total']:
        any_, first = levels[size]['any'], levels[size]['first']
        cells = [f"{pct(any_[level])}（{pct(first[level])}）" for level in ('Exact', 'Close', 'Far', 'Mismatch')]
        paper = PAPER_MATCH.get(size, ('–',) * 4)
        lines.append(f"| {size} | {any_['n']} | {' | '.join(cells)} | {' | '.join(str(p) for p in paper)} |")
    return lines


def portion_table(metrics):
    portions = metrics['asa24']['portions']
    lines = ['| 档 | 被问份量 | 分类准确率（%） | 论文（%） | 单位误差（n） | 论文（units） | 克数误差 option（n） | 克数误差 amount（n） |',
             '|---|---|---|---|---|---|---|---|']
    for size in SIZES + ['Total']:
        p, paper = portions[size], PAPER_PORTIONS[size]
        lines.append(f"| {size} | {p['n']} | {pct(p['classification_accuracy'])} | {paper[0]} | "
                     f"{fmt(p['unit_error']['per_dish'])}（{p['unit_error']['n']}） | {paper[1]} | "
                     f"{fmt(p['gram_error_option']['per_dish'])}（{p['gram_error_option']['n']}） | "
                     f"{fmt(p['gram_error_amount']['per_dish'])}（{p['gram_error_amount']['n']}） |")
    return lines


def main(args):
    metrics = json.load(open(args.metrics))
    for title, lines in (('MAE', mae_tables(metrics)), ('成功率', success_table(metrics)),
                         ('编码匹配级别，any（first）', match_table(metrics)), ('份量', portion_table(metrics))):
        print(f'### {title}\n\n' + '\n'.join(lines) + '\n')


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Tables of a run's metrics beside the paper's.")
    parser.add_argument('metrics', help='metrics.json of evaluate.py')
    return parser.parse_args(argv)


if __name__ == '__main__':
    main(parse_args())
