#!/usr/bin/env python3
"""Post-selection development diagnostics; never an inference or selection arm."""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
import random

import opt_metrics as scoring

ROOT = Path(__file__).resolve().parents[1]
KEYS = scoring.KEYS


def _digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load(path):
    if path.is_symlink():
        raise ValueError("Diagnostic inputs cannot be symbolic links")
    return json.loads(path.read_text())


def _quantile(values, fraction):
    values = sorted(values)
    position = (len(values) - 1) * fraction
    lo, hi = math.floor(position), math.ceil(position)
    return values[lo] + (values[hi] - values[lo]) * (position - lo)


def paired_n5(manifest, labels, baseline, selected, draws=10000, seed=20261102):
    """Resample the same association groups in both arms; negative favors selected."""
    scoring._training(manifest, labels)
    _, bp = scoring._validate(manifest, labels, baseline)
    _, sp = scoring._validate(manifest, labels, selected)
    rows = [r for r in manifest if r['dataset'] == 'nutrition5k']
    groups = {}
    for row in rows:
        groups.setdefault(row['group_id'], []).append(row['sample_id'])
    names = sorted(groups)
    if len(names) < 2:
        return {'n': len(rows), 'groups': len(names), 'intervals': None, 'reason': 'fewer_than_two_groups'}
    if not isinstance(draws, int) or draws <= 0:
        raise ValueError('Positive bootstrap draws required')
    # Each group retains its original image multiplicity in every resample.
    values = {}
    for group, ids in groups.items():
        values[group] = (len(ids), {
            k: (sum(abs(sp[s]['prediction'][k] - labels[s]['truth'][k]) -
                    abs(bp[s]['prediction'][k] - labels[s]['truth'][k]) for s in ids),
                sum(labels[s]['truth'][k] for s in ids)) for k in KEYS})
    rng = random.Random(seed)
    samples = {k + '.' + stat: [] for k in KEYS for stat in ('mae', 'per_unit')}
    for _ in range(draws):
        chosen = [values[g] for g in rng.choices(names, k=len(names))]
        n = sum(v[0] for v in chosen)
        for k in KEYS:
            delta = sum(v[1][k][0] for v in chosen)
            truth = sum(v[1][k][1] for v in chosen)
            samples[k + '.mae'].append(delta / n)
            if truth > 0:
                samples[k + '.per_unit'].append(delta / truth)
    return {'n': len(rows), 'groups': len(names), 'replicates': draws, 'seed': seed,
            'confidence': .95, 'direction': 'selected_minus_original_baseline_negative_is_lower_error',
            'scope': 'selected_development_not_unbiased_validation',
            'intervals': {k: {'low': _quantile(v, .025) if v else None,
                              'high': _quantile(v, .975) if v else None,
                              'valid_replicates': len(v)} for k, v in samples.items()}}


def asa24_exact_intersection(manifest, labels, baseline, selected, draws=10000, seed=20261102):
    """Exploratory option comparison on identical, independently Exact rows.

    Membership depends only on each arm's original recognition codes. Missing
    conditional predictions stay in the intersection and invalidate that arm's
    score instead of silently creating an easier successful-only denominator.
    """
    scoring._training(manifest, labels)
    _, bp = scoring._validate(manifest, labels, baseline)
    _, sp = scoring._validate(manifest, labels, selected)
    if type(draws) is not int or draws <= 0:
        raise ValueError('Positive bootstrap draws required')
    population = [r for r in manifest if r['dataset'] == 'asa24']
    rows, baseline_n, selected_n = [], 0, 0
    for row in population:
        sid = row['sample_id']
        code = labels[sid]['food_code']
        # Explicit independent flags; do not manufacture Exact membership by
        # replacing codes, using retrieval hits, or testing portion availability.
        baseline_exact = code in bp[sid].get('final_codes', [])
        selected_exact = code in sp[sid].get('final_codes', [])
        baseline_n += baseline_exact
        selected_n += selected_exact
        if baseline_exact and selected_exact:
            rows.append(row)
    scores = {}
    for name, index in (('baseline', bp), ('selected', sp)):
        evaluated = scoring.evaluate(rows, labels, [index[r['sample_id']] for r in rows])['datasets']['asa24']
        if evaluated['exact_n'] != len(rows) or evaluated['primary']['n'] != len(rows):
            raise ValueError('ASA24 diagnostic intersection denominator changed during evaluation')
        scores[name] = evaluated['primary']
    groups = {}
    for row in rows:
        groups.setdefault(row['group_id'], []).append(row['sample_id'])
    boot = {'n': len(rows), 'groups': len(groups), 'replicates': draws, 'seed': seed,
            'confidence': .95, 'direction': 'selected_minus_baseline_negative_is_lower_error',
            'intervals': None}
    if len(groups) < 2:
        boot['reason'] = 'fewer_than_two_groups'
    elif any(not score['complete_population'] for score in scores.values()):
        boot['reason'] = 'missing_conditional_prediction_on_fixed_intersection'
    else:
        values = [(len(ids), {k: (
            sum(abs(sp[s]['conditional']['prediction'][k] - labels[s]['truth'][k]) -
                abs(bp[s]['conditional']['prediction'][k] - labels[s]['truth'][k]) for s in ids),
            sum(labels[s]['truth'][k] for s in ids)) for k in KEYS}) for _, ids in sorted(groups.items())]
        rng = random.Random(seed)
        samples = {k + '.' + stat: [] for k in KEYS for stat in ('mae', 'per_unit')}
        for _ in range(draws):
            chosen = rng.choices(values, k=len(values))
            n = sum(v[0] for v in chosen)
            for key in KEYS:
                delta = sum(v[1][key][0] for v in chosen)
                truth = sum(v[1][key][1] for v in chosen)
                samples[key + '.mae'].append(delta / n)
                if truth > 0:
                    samples[key + '.per_unit'].append(delta / truth)
        boot['intervals'] = {k: {'low': _quantile(v, .025) if v else None,
                                 'high': _quantile(v, .975) if v else None,
                                 'valid_replicates': len(v)} for k, v in samples.items()}
    return {'diagnostic_only': True, 'population_n': len(population), 'n': len(rows), 'groups': len(groups),
            'baseline_exact_n': baseline_n, 'selected_exact_n': selected_n,
            'baseline_only_exact_n': baseline_n - len(rows), 'selected_only_exact_n': selected_n - len(rows),
            'membership': 'reference_code_in_original_final_codes_of_both_arms',
            'interpretation': 'post_selection_common_exact_option_diagnostic_not_a_replacement_for_registered_scores',
            **scores, 'paired_bootstrap': boot}


def diagnostic_aggregates(manifest, labels, baseline, selected, draws=10000):
    scoring._training(manifest, labels)
    _, index = scoring._validate(manifest, labels, selected)
    scoring._validate(manifest, labels, baseline)
    n5 = [r for r in manifest if r['dataset'] == 'nutrition5k']
    if not n5:
        raise ValueError('Nutrition5k development rows required')
    median_predictions = []
    for row in n5:
        vector = scoring.fold_medians(manifest, labels, row['fold'], 'nutrition5k')
        median_predictions.append({'sample_id': row['sample_id'], 'dataset': 'nutrition5k',
            'prediction': vector, 'final_codes': [], 'primary_code': None,
            'native_complete': False, 'fallback': True})
    median_score = scoring.evaluate(n5, labels, median_predictions)['datasets']['nutrition5k']['primary']
    # This uses reference weight by design, only after selection. It must never
    # be reported as a prediction, feasible model, selected arm or acceptance.
    corrected = []
    eligible_rows = []
    for row in n5:
        sid = row['sample_id']
        pred, truth = index[sid]['prediction'], labels[sid]['truth']
        if pred['weight'] <= 0 or truth['weight'] <= 0:
            continue
        copy = deepcopy(index[sid])
        copy['prediction'] = {k: pred[k] * truth['weight'] / pred['weight'] for k in KEYS}
        corrected.append(copy)
        eligible_rows.append(row)
    oracle = (scoring.evaluate(eligible_rows, labels, corrected)['datasets']['nutrition5k']['primary']
              if eligible_rows else None)
    complete = [index[r['sample_id']] for r in n5]
    signed = {k: sum(p['prediction'][k] - labels[p['sample_id']]['truth'][k] for p in complete) / len(n5)
              for k in KEYS}
    baseline_score = scoring.evaluate(manifest, labels, baseline)['datasets']['nutrition5k']['primary']
    selected_score = scoring.evaluate(manifest, labels, selected)['datasets']['nutrition5k']['primary']
    return {'schema_version': 2,
            'scope': 'post_selection_development_diagnostics_no_candidate_or_acceptance_effect',
            'asa24_common_exact_comparison': asa24_exact_intersection(manifest, labels, baseline, selected, draws),
            'median_baseline': {'method': 'five_componentwise_medians_from_other_folds_only',
                'dataset': 'nutrition5k', 'score': median_score},
            'same_population_comparison': {'n': len(n5), 'baseline': baseline_score,
                'selected': selected_score, 'selected_mean_signed_error': signed,
                'paired_bootstrap': paired_n5(manifest, labels, baseline, selected, draws)},
            'oracle_weight_diagnostic': {'uses_reference_weight': True,
                'not_a_model_or_acceptance_result': True,
                'method': 'multiply_all_selected_targets_by_reference_weight_over_predicted_weight',
                'interpretation': 'residual nutrient error under perfect total mass; does not identify its causal source',
                'population_n': len(n5), 'scored_n': len(eligible_rows),
                'excluded_nonpositive_weight_n': len(n5) - len(eligible_rows), 'score': oracle}}


def write_diagnostics(root=ROOT, draws=10000):
    root = Path(root).resolve()
    if root != ROOT:
        raise ValueError('The operational diagnostic uses only this study development loader')
    from cohorts_v2 import verify_dev_only, load_dev
    verify_dev_only()
    paths = [root / p for p in ('runs/development/completion.json', 'runs/development/selection.json',
             'runs/development/baseline/oof_predictions.json', 'runs/development/selected_oof_predictions.json',
             'data/cohorts/dev_freeze.json')]
    completion, selection, baseline, selected = [_load(p) for p in paths[:4]]
    if completion.get('status') not in ('ready_for_review', 'development_targets_not_met'):
        raise ValueError('Diagnostics require completed registered development')
    if selection.get('scope') != 'development_not_independent_validation':
        raise ValueError('Selected development scope required')
    rows, labels = load_dev()
    recalculated = scoring.evaluate(rows, labels, selected)
    for ds in scoring.DATASETS:
        if recalculated['datasets'][ds]['primary'] != selection['metrics']['datasets'][ds]['primary']:
            raise ValueError('Selected metric aggregate differs from selected predictions')
    result = diagnostic_aggregates(rows, labels, baseline, selected, draws)
    result['source_sha256'] = {str(p.relative_to(root)): _digest(p) for p in paths}
    result['source_sha256']['src/diagnostics_v2.py'] = _digest(Path(__file__))
    destination = root / 'analysis/diagnostics_v2.json'
    if destination.is_symlink():
        raise ValueError('Diagnostic destination cannot be a symbolic link')
    destination.write_text(json.dumps(result, indent=2, allow_nan=False) + '\n')
    return {'output': str(destination), 'n': result['same_population_comparison']['n'], 'paid_api_calls': 0}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    print(json.dumps(write_diagnostics(), indent=2))
