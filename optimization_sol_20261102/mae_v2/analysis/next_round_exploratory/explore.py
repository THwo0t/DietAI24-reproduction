#!/usr/bin/env python3
"""Posthoc exploratory development analysis, not a registered candidate.

Run with ../../.venv/bin/python -B analysis/next_round_exploratory/explore.py
from mae_v2. Reads the seven exact development JSON inputs below, no images,
validation, provider, source run writes, or registered selection changes.
"""
from __future__ import annotations

from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import platform
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'src'))
import opt_metrics as metrics

KEYS = metrics.KEYS
INPUTS = (
    'data/cohorts/dev_freeze.json', 'data/cohorts/dev.jsonl',
    'data/cohorts/dev_labels.json', 'runs/development/C/predictions.json',
    'runs/development/C/calibration-round1.json',
    'runs/development/C/calibration-summary.json',
    'runs/development/selection.json',
)
FAMILIES = ('median', 'scale', 'scale_half', 'offset', 'median_mix',
            'affine', 'density_nn', 'density_nn_half')
COMPLEXITY = dict(zip(FAMILIES, (5, 5, 5, 5, 10, 10, 9, 9)))
DESCRIPTIONS = {
    'median': 'Five training-only target medians; ignores C inputs.',
    'scale': 'Five independent nonnegative L1-optimal multipliers.',
    'scale_half': 'Five independent multipliers, shrunk halfway toward one.',
    'offset': 'Add five training median residuals; clip output at zero.',
    'median_mix': 'Five L1-optimal convex mixtures of raw prediction and training target median.',
    'affine': 'Five nonnegative-slope, free-intercept L1 affine fits; clip output at zero.',
    'density_nn': 'Weight multiplier; each nutrient = a * raw nutrient + b * raw weight, a,b >= 0 (nine coefficients).',
    'density_nn_half': 'Halfway mixture of density_nn and the unmodified raw vector.',
}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_inputs():
    loaded, hashes = {}, {}
    for name in INPUTS:
        path = ROOT / name
        if path.is_symlink() or path.resolve() != path:
            raise ValueError('Only exact nonsymlink development input paths are allowed')
        raw = path.read_bytes()
        hashes[name] = hashlib.sha256(raw).hexdigest()
        loaded[name] = ([json.loads(line) for line in raw.splitlines() if line]
                        if name.endswith('.jsonl') else json.loads(raw))
    freeze = loaded[INPUTS[0]]
    # Do not open/hash any of the image entries in dev_freeze.
    for name in INPUTS[1:3]:
        if freeze['artifacts'].get(name) != hashes[name]:
            raise ValueError('Development text input no longer matches freeze')
    manifest = [r for r in loaded[INPUTS[1]] if r['dataset'] == 'nutrition5k']
    labels = {r['sample_id']: loaded[INPUTS[2]][r['sample_id']] for r in manifest}
    metrics._training(manifest, labels)
    metrics._validate(manifest, labels, loaded[INPUTS[3]])
    metrics._validate(manifest, labels, loaded[INPUTS[4]]['predictions'])
    if len(manifest) != 84 or len({r['group_id'] for r in manifest}) != 78:
        raise ValueError('This exploratory analysis is restricted to the fixed 84 / 78 development cohort')
    raw_index = {r['sample_id']: r for r in loaded[INPUTS[3]]}
    cal_index = {r['sample_id']: r for r in loaded[INPUTS[4]]['predictions']}
    if any(raw_index[r['sample_id']]['fallback'] for r in manifest):
        raise ValueError('Current C has no whole fallback; any future fallback needs explicit train-only rebuilding')
    if any(p['prediction'] != p['raw_prediction'] for p in raw_index.values()):
        raise ValueError('Regression features must be raw label-blind vectors')
    x = np.array([[raw_index[r['sample_id']]['raw_prediction'][k] for k in KEYS] for r in manifest])
    y = np.array([[labels[r['sample_id']]['truth'][k] for k in KEYS] for r in manifest])
    calibrated = np.array([[cal_index[r['sample_id']]['prediction'][k] for k in KEYS] for r in manifest])
    folds = np.array([r['fold'] for r in manifest])
    groups = np.array([r['group_id'] for r in manifest])
    validate_arrays(x, y, folds, groups)
    saved = loaded[INPUTS[6]]['metrics']['datasets']['nutrition5k']['primary']
    check = score(calibrated, y)
    if any(not math.isclose(check['metrics'][k]['mae'], saved['metrics'][k]['mae'], abs_tol=1e-10) for k in KEYS):
        raise ValueError('Saved calibrated C no longer matches current selected metrics')
    return x, y, calibrated, folds, groups, hashes


def validate_arrays(x, y, folds, groups):
    if x.shape != y.shape or x.shape != (len(folds), 5) or len(groups) != len(folds):
        raise ValueError('Full aligned five-target population is required')
    if not np.all(np.isfinite(x)) or not np.all(np.isfinite(y)) or np.any(x < 0) or np.any(y < 0):
        raise ValueError('No missing, negative, or nonfinite values can be dropped')
    if set(folds) != {0, 1, 2, 3, 4}:
        raise ValueError('All five existing folds are required')
    for g in set(groups):
        if len(set(folds[groups == g])) != 1:
            raise ValueError('An association group spans folds')


def weighted_median(values, weights, prefer=1.0):
    active = weights > 1e-12
    if not np.any(active):
        return float(prefer)
    v, w = values[active], weights[active]
    order = np.argsort(v, kind='stable')
    v, w = v[order], w[order]
    cum, half = np.cumsum(w), np.sum(w) / 2
    index = int(np.searchsorted(cum, half, side='left'))
    low = v[index]
    high = v[index + 1] if index + 1 < len(v) and abs(cum[index] - half) < 1e-10 else low
    return float(np.clip(prefer, low, high))


def scalar_fit(x, y, lower=0.0, upper=math.inf, prefer=1.0):
    nz = np.abs(x) > 1e-12
    value = weighted_median(y[nz] / x[nz], np.abs(x[nz]), prefer)
    return float(np.clip(value, lower, upper))


def lad_two(features, target, *, second_nonnegative):
    """Exact two-parameter LAD vertices plus boundary optima; no numerical solver.

    A convex piecewise-linear loss has an optimum at a residual-line intersection
    or constraint boundary; the boundary fits use exact weighted medians.
    """
    a, b = features[:, 0], features[:, 1]
    i, j = np.triu_indices(len(target), k=1)
    det = a[i] * b[j] - a[j] * b[i]
    stable = np.abs(det) > 1e-12 * np.maximum(1.0, np.abs(a[i] * b[j]) + np.abs(a[j] * b[i]))
    i, j, det = i[stable], j[stable], det[stable]
    slopes = (target[i] * b[j] - target[j] * b[i]) / det
    second = (a[i] * target[j] - a[j] * target[i]) / det
    eligible = slopes >= -1e-10
    if second_nonnegative:
        eligible &= second >= -1e-10
    candidates = np.column_stack((np.maximum(0, slopes[eligible]), second[eligible]))
    boundaries = [[scalar_fit(a, target), 0.0],
                  [0.0, scalar_fit(b, target, lower=0.0 if second_nonnegative else -math.inf, prefer=0.0)]]
    candidates = np.vstack((candidates, boundaries))
    if second_nonnegative:
        candidates[:, 1] = np.maximum(0, candidates[:, 1])
    # Broadcast avoids a BLAS thread pool for these very small matrices.
    losses = np.mean(np.abs(a[:, None] * candidates[:, 0] + b[:, None] * candidates[:, 1] - target[:, None]), axis=0)
    best = np.flatnonzero(losses <= losses.min() + 1e-10)
    # A deterministic tie break toward unchanged raw values, scaled by features.
    scale = np.maximum(1e-12, np.mean(np.abs(features), axis=0))
    distances = np.sum(((candidates[best] - [1.0, 0.0]) * scale) ** 2, axis=1)
    return candidates[best[np.argmin(distances)]]


def fit_model(name, x, y):
    if name not in FAMILIES:
        raise ValueError('Unknown fixed exploratory family')
    if not len(x) or x.shape != y.shape:
        raise ValueError('Nonempty aligned training data required')
    coefficients = []
    for k in range(5):
        if name == 'median':
            coef = [0.0, float(np.median(y[:, k]))]
        elif name in {'scale', 'scale_half'}:
            scale = scalar_fit(x[:, k], y[:, k])
            coef = [1 + (scale - 1) * (.5 if name.endswith('_half') else 1), 0.0]
        elif name == 'offset':
            coef = [1.0, float(np.median(y[:, k] - x[:, k]))]
        elif name == 'median_mix':
            med = float(np.median(y[:, k]))
            alpha = scalar_fit(x[:, k] - med, y[:, k] - med, upper=1.0)
            coef = [alpha, (1 - alpha) * med]
        elif name == 'affine':
            coef = lad_two(np.column_stack((x[:, k], np.ones(len(x)))), y[:, k], second_nonnegative=False)
        elif k == 0:
            scale = scalar_fit(x[:, k], y[:, k])
            coef = [1 + (scale - 1) * (.5 if name.endswith('_half') else 1), 0.0]
        else:
            coef = lad_two(x[:, [k, 0]], y[:, k], second_nonnegative=True)
            if name.endswith('_half'):
                coef = (coef + [1.0, 0.0]) / 2
        coefficients.append(list(map(float, coef)))
    return {'family': name, 'coefficients': coefficients}


def predict(model, x):
    coef = np.array(model['coefficients'])
    second = np.repeat(x[:, [0]], 5, axis=1) if model['family'].startswith('density_nn') else np.ones_like(x)
    second[:, 0] = 1.0
    return np.maximum(0.0, x * coef[:, 0] + second * coef[:, 1])


def score(pred, truth):
    if pred.shape != truth.shape or not len(pred) or not np.all(np.isfinite(pred)):
        raise ValueError('Cannot silently score only successful rows')
    mae = np.mean(np.abs(pred - truth), axis=0)
    mean = np.mean(truth, axis=0)
    values, ratios, passed = {}, [], 0
    for k, a, m in zip(KEYS, mae, mean):
        cap, ucap = metrics.THRESHOLDS['nutrition5k'][k]
        unit = float(a / m) if m > 0 else None
        ratio = max(float(a / cap), unit / ucap if unit is not None else math.inf)
        pa, pu = bool(a <= cap), bool(unit is not None and unit <= ucap)
        values[k] = {'mae': float(a), 'per_unit': unit, 'reference_mean': float(m),
                     'threshold_mae': cap, 'threshold_per_unit': ucap,
                     'effective_absolute_cap': min(cap, float(m * ucap)),
                     'pass_mae': pa, 'pass_per_unit': pu, 'worst_ratio': ratio}
        passed += pa + pu
        ratios.extend((float(a / cap), unit / ucap if unit is not None else math.inf))
    worst = max(values, key=lambda key: values[key]['worst_ratio'])
    return {'n': len(pred), 'passed_checks': passed, 'total_checks': 10,
            'worst_target': worst, 'worst_ratio': max(ratios), 'mean_ratio': sum(ratios) / 10,
            'metrics': values}


def oof(name, x, y, folds, groups):
    validate_arrays(x, y, folds, groups)
    out = np.full_like(x, np.nan)
    parameters = []
    for fold in sorted(set(folds)):
        train, heldout = folds != fold, folds == fold
        if set(groups[train]) & set(groups[heldout]):
            raise ValueError('Group leak')
        model = fit_model(name, x[train], y[train])
        out[heldout] = predict(model, x[heldout])
        parameters.append({'outer_fold': int(fold), 'training_n': int(train.sum()),
                           'training_groups': len(set(groups[train])),
                           'heldout_n': int(heldout.sum()), 'heldout_groups': len(set(groups[heldout])), **model})
    return out, parameters


def nested_oof(x, y, folds, groups):
    """Select ONE entire five-target family using only inner-held-out train rows."""
    validate_arrays(x, y, folds, groups)
    out, choices = np.full_like(x, np.nan), []
    for outer in sorted(set(folds)):
        train = folds != outer
        # Inner held-out splits are the remaining four original association folds.
        scores = []
        for index, family in enumerate(FAMILIES):
            inner = np.full_like(x, np.nan)
            for held in sorted(set(folds[train])):
                fit = train & (folds != held)
                test = train & (folds == held)
                model = fit_model(family, x[fit], y[fit])
                inner[test] = predict(model, x[test])
            s = score(inner[train], y[train])
            scores.append(((s['worst_ratio'], s['mean_ratio'], COMPLEXITY[family], index), family, s))
        _, family, best = min(scores, key=lambda row: row[0])
        model = fit_model(family, x[train], y[train])
        out[~train] = predict(model, x[~train])
        choices.append({'outer_fold': int(outer), 'selected_family': family,
                        'inner_worst_ratio': best['worst_ratio'],
                        'inner_family_scores': {f: {'worst_ratio': s['worst_ratio'], 'mean_ratio': s['mean_ratio']}
                                                for _, f, s in scores}, **model})
    return out, choices


def signed_error(pred, truth):
    return dict(zip(KEYS, map(float, np.mean(pred - truth, axis=0))))


def rank_correlations(x, y):
    def ranks(v):
        order = np.argsort(v, kind='stable')
        result = np.empty(len(v), dtype=float)
        for value in np.unique(v):
            ids = order[v[order] == value]
            positions = np.flatnonzero(v[order] == value)
            result[ids] = positions.mean()
        return result
    return {k: {'pearson': float(np.corrcoef(x[:, i], y[:, i])[0, 1]),
                'spearman': float(np.corrcoef(ranks(x[:, i]), ranks(y[:, i]))[0, 1])} for i, k in enumerate(KEYS)}


def bootstrap_delta(pred, reference, truth, groups, draws=10000):
    """Fixed already-fitted OOF errors, descriptive; does not refit all models."""
    rng = np.random.default_rng(20261103)
    group_values = []
    for g in sorted(set(groups)):
        ids = groups == g
        group_values.append((ids.sum(), np.sum(np.abs(pred[ids] - truth[ids]) - np.abs(reference[ids] - truth[ids]), axis=0)))
    counts = np.array([v[0] for v in group_values])
    sums = np.array([v[1] for v in group_values])
    indexes = rng.integers(0, len(group_values), size=(draws, len(group_values)))
    samples = sums[indexes].sum(axis=1) / counts[indexes].sum(axis=1)[:, None]
    intervals = np.quantile(samples, [.025, .975], axis=0)
    return {'replicates': draws, 'groups': len(group_values),
            'scope': 'descriptive_fixed_oof_paired_group_bootstrap_no_refit_no_selection_correction',
            'direction': 'exploratory_minus_registered_calibrated_negative_is_better',
            'mae_delta_95pct': {k: {'low': float(intervals[0, i]), 'high': float(intervals[1, i])} for i, k in enumerate(KEYS)}}


def run():
    x, y, calibrated, folds, groups, hashes = load_inputs()
    results, arrays = {}, {}
    for name, prediction in [('raw_C_reference', x), ('registered_calibrated_C_reference', calibrated)]:
        results[name] = {'description': 'Existing frozen C reference; no new fit.', 'score': score(prediction, y),
                         'mean_signed_error': signed_error(prediction, y)}
    for family in FAMILIES:
        prediction, parameters = oof(family, x, y, folds, groups)
        arrays[family] = prediction
        results[family] = {'description': DESCRIPTIONS[family], 'score': score(prediction, y),
                           'mean_signed_error': signed_error(prediction, y), 'fold_parameters': parameters,
                           'fold_scores': {str(f): score(prediction[folds == f], y[folds == f]) for f in range(5)}}
    nested, choices = nested_oof(x, y, folds, groups)
    results['nested_family_selection'] = {
        'description': 'Inner four-fold choice of one complete family; outer held-out labels excluded from fitting and choosing.',
        'score': score(nested, y), 'choices': choices,
        'mean_signed_error': signed_error(nested, y),
        'fold_scores': {str(f): score(nested[folds == f], y[folds == f]) for f in range(5)},
        'paired_bootstrap': bootstrap_delta(nested, calibrated, y, groups)}
    best = min(FAMILIES, key=lambda f: (results[f]['score']['worst_ratio'], results[f]['score']['mean_ratio'], COMPLEXITY[f], FAMILIES.index(f)))
    results[best]['paired_bootstrap'] = bootstrap_delta(arrays[best], calibrated, y, groups)
    if np.any(x[:, 0] <= 0) or np.any(y[:, 0] <= 0):
        raise ValueError('Oracle diagnostic cannot silently drop zero-weight rows')
    oracle_mass = x * (y[:, 0] / x[:, 0])[:, None]
    oracle_density = y * (x[:, 0] / y[:, 0])[:, None]
    snapshot = {
        'schema_version': 1, 'scope': 'posthoc_exploratory_development_only_not_registered_not_acceptance',
        'created_date': '2026-11-03', 'api_calls': 0, 'images_read': 0, 'validation_read': False,
        'population': {'n': len(x), 'association_groups': len(set(groups)), 'fold_counts': dict(sorted(Counter(map(int, folds)).items())),
                       'whole_fallback_n': 0, 'dropped_n': 0, 'not_a_claim_of_physical_independence': True},
        'inputs_sha256': hashes,
        'code_sha256': {'explore.py': digest(Path(__file__)), 'opt_metrics.py': digest(ROOT / 'src/opt_metrics.py')},
        'runtime': {'python': platform.python_version(), 'numpy': np.__version__},
        'fixed_family_order': list(FAMILIES),
        'feature_source': 'C raw_prediction only; saved OOF calibrated vectors used only as scored reference',
        'fitting_loss': 'Image-weighted MAE; all medians, coefficients, preprocessing and inner choices use training folds only',
        'preservation': 'No source runs, selection, protocol, reports, images or validation artifacts written',
        'cautions': [
            'C itself was previously chosen on this development cohort; nested calibration does not remove upstream candidate-selection bias.',
            'All family results are posthoc exploratory; choosing the best displayed OOF family is optimistically biased.',
            'Independent nutrient transformations depart from registered v2 physical mass-only calibration and may violate nutrient energy consistency.',
            'Neither descriptive bootstrap nor nested family selection supplies independent validation or approval to open it.',
            'No hyperparameter or sample exclusion is selected to make a threshold pass.',
        ],
        'results': results, 'best_displayed_family_posthoc': best,
        'raw_correlations': rank_correlations(x, y),
        'oracle_diagnostics': {
            'uses_reference_labels_at_prediction_time': True,
            'not_models_not_acceptance_not_selectable': True,
            'perfect_total_mass_raw_densities': score(oracle_mass, y),
            'perfect_nutrient_densities_raw_total_mass': score(oracle_density, y),
        },
    }
    # Recheck only the same text inputs; never touch image or validation entries.
    if any(digest(ROOT / name) != h for name, h in hashes.items()):
        raise ValueError('An input changed while computing exploration')
    (OUT / 'results.json').write_text(json.dumps(snapshot, indent=2, allow_nan=False) + '\n')
    print(json.dumps({'scope': snapshot['scope'], 'population': snapshot['population'],
                      'scores': {n: {'passed': v['score']['passed_checks'], 'worst': v['score']['worst_ratio'],
                                     'worst_target': v['score']['worst_target'],
                                     'mae': {k: round(v['score']['metrics'][k]['mae'], 5) for k in KEYS}}
                                 for n, v in results.items()},
                      'oracle_diagnostics': snapshot['oracle_diagnostics'],
                      'best_displayed_family_posthoc': best}, indent=2))


if __name__ == '__main__':
    run()
