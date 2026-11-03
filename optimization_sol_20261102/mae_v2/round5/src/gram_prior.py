"""Pure external-training linear ingredient-gram prior; no I/O or API.

Fixed lambda=1 squared-loss fit, judged by the separately fixed OOF MAE gate.
This is provisional quantitative supervision for a possible future Sol stage,
not a replacement for Sol or an assertion of visible ingredient presence.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import math
from numbers import Real

import numpy as np

VERSION = 'external-gram-prior-r5.1'
DIMENSIONS = 3072
RIDGE_LAMBDA = 1.0
FOLDS = 5
TARGETS = ('weight', 'energy', 'fat', 'carbs', 'protein')
NUTRIENTS = TARGETS[1:]


class PriorError(ValueError):
    pass


def require(condition, code):
    if not condition:
        raise PriorError(code)


def _number(value, *, positive=False):
    require(isinstance(value, Real) and not isinstance(value, (bool, np.bool_))
            and math.isfinite(value) and (value > 0 if positive else value >= 0),
            'invalid_nonnegative_number')
    return float(value)


def _identifier(value):
    require(isinstance(value, str) and bool(value.strip()), 'invalid_identifier')
    return value


def _vector(value):
    require(isinstance(value, (list, tuple, np.ndarray)) and len(value) == DIMENSIONS,
            'embedding_dimension_changed')
    require(all(isinstance(x, Real) and not isinstance(x, (bool, np.bool_)) and math.isfinite(x)
                for x in value), 'invalid_embedding')
    vector = np.asarray(value, dtype=np.float64)
    require(vector.shape == (DIMENSIONS,), 'embedding_dimension_changed')
    norm = np.linalg.norm(vector)
    require(np.isfinite(norm) and norm > 0, 'zero_or_nonfinite_embedding_norm')
    return vector / norm


def _targets(value):
    require(isinstance(value, dict) and set(value) == set(TARGETS), 'official_target_fields_changed')
    return {k: _number(value[k], positive=k == 'weight') for k in TARGETS}


def _ingredients(value):
    require(isinstance(value, list) and bool(value), 'ingredient_records_required')
    out = {}
    for item in value:
        require(isinstance(item, dict) and set(item) == {'ingredient_id', 'grams', 'nutrients'},
                'ingredient_fields_changed')
        ingredient = _identifier(item['ingredient_id'])
        grams = _number(item['grams'])
        amounts = item['nutrients']
        require(isinstance(amounts, dict) and set(amounts) == set(NUTRIENTS), 'nutrient_fields_changed')
        amounts = {k: _number(amounts[k]) for k in NUTRIENTS}
        if grams == 0:
            require(not any(amounts.values()), 'zero_mass_nonzero_nutrients')
            continue
        if ingredient not in out:
            out[ingredient] = {'grams': 0.0, 'nutrients': {k: 0.0 for k in NUTRIENTS}}
        out[ingredient]['grams'] += grams
        for k in NUTRIENTS:
            out[ingredient]['nutrients'][k] += amounts[k]
    require(bool(out), 'positive_ingredient_required')
    require(all(math.isfinite(row['grams']) and all(math.isfinite(x) for x in row['nutrients'].values())
                for row in out.values()), 'ingredient_sum_nonfinite')
    return out


def assign_folds(group_ids):
    groups = {_identifier(g) for g in group_ids}
    require(len(groups) >= FOLDS, 'at_least_five_groups_required')
    ordered = sorted(groups, key=lambda g: (hashlib.sha256((VERSION + '\0' + g).encode('utf-8')).hexdigest(), g))
    return {group: index % FOLDS for index, group in enumerate(ordered)}


@dataclass(frozen=True)
class GramPriorModel:
    train_ids: tuple
    ingredient_ids: tuple
    embedding_mean: np.ndarray
    gram_mean: np.ndarray
    coefficients: np.ndarray
    density_per_100g: dict
    fallback: dict


def fit(vectors_by_id, ingredient_records, official_targets, train_ids):
    """Access numeric training values only for the explicit train_ids subset."""
    ids = sorted(_identifier(x) for x in train_ids)
    require(bool(ids) and len(ids) == len(set(ids)), 'unique_training_ids_required')
    require(all(sid in vectors_by_id and sid in ingredient_records and sid in official_targets for sid in ids),
            'missing_training_input')
    parsed = {sid: _ingredients(ingredient_records[sid]) for sid in ids}
    ingredients = tuple(sorted({ingredient for row in parsed.values() for ingredient in row}))
    x = np.stack([_vector(vectors_by_id[sid]) for sid in ids])
    y = np.array([[parsed[sid].get(ingredient, {}).get('grams', 0.0) for ingredient in ingredients]
                  for sid in ids], dtype=np.float64)
    means_x, means_y = x.mean(axis=0), y.mean(axis=0)
    xc, yc = x - means_x, y - means_y
    kernel = xc @ xc.T
    alpha = np.linalg.solve(kernel + RIDGE_LAMBDA * np.eye(len(ids), dtype=np.float64), yc)
    coefficients = xc.T @ alpha
    require(np.isfinite(coefficients).all() and np.isfinite(means_y).all(), 'nonfinite_ridge_solution')
    density = {}
    for ingredient in ingredients:
        grams = math.fsum(parsed[sid][ingredient]['grams'] for sid in ids if ingredient in parsed[sid])
        density[ingredient] = {k: 100.0 * math.fsum(parsed[sid][ingredient]['nutrients'][k]
            for sid in ids if ingredient in parsed[sid]) / grams for k in NUTRIENTS}
        require(all(math.isfinite(v) for v in density[ingredient].values()), 'nonfinite_fold_density')
    targets = [_targets(official_targets[sid]) for sid in ids]
    fallback = {k: float(np.median([row[k] for row in targets])) for k in TARGETS}
    return GramPriorModel(tuple(ids), ingredients, means_x, means_y, coefficients, density, fallback)


def predict(model, query_vector):
    require(isinstance(model, GramPriorModel), 'gram_prior_model_required')
    signed = model.gram_mean + (_vector(query_vector) - model.embedding_mean) @ model.coefficients
    require(np.isfinite(signed).all(), 'nonfinite_predicted_grams')
    grams = np.maximum(signed, 0.0)
    audit = {'negative_gram_count_clipped': int(np.sum(signed < 0)),
             'negative_gram_magnitude_clipped': float(-np.sum(signed[signed < 0]))}
    if not np.any(grams > 0):
        return {'ingredient_grams': {}, 'prediction': dict(model.fallback), 'fallback': True, 'audit': audit}
    masses = {ingredient: float(value) for ingredient, value in zip(model.ingredient_ids, grams)}
    prediction = {'weight': math.fsum(masses.values())}
    prediction.update({k: math.fsum(masses[ingredient] * model.density_per_100g[ingredient][k] / 100.0
                                  for ingredient in model.ingredient_ids) for k in NUTRIENTS})
    require(all(math.isfinite(v) for v in prediction.values()), 'nonfinite_predicted_total')
    return {'ingredient_grams': masses, 'prediction': prediction, 'fallback': False, 'audit': audit}


def advance_gate(candidate_mae, baseline_mae):
    require(set(candidate_mae) == set(TARGETS) and set(baseline_mae) == set(TARGETS), 'gate_target_fields_changed')
    for mapping in (candidate_mae, baseline_mae):
        require(all(isinstance(v, Real) and not isinstance(v, (bool, np.bool_))
                    and (not math.isfinite(v) or v >= 0)
                    for v in mapping.values()), 'invalid_gate_error')
    if (any(not math.isfinite(v) or v <= 0 for v in baseline_mae.values())
            or any(not math.isfinite(v) for v in candidate_mae.values())):
        return {'valid': False, 'advance': False, 'reason': ['zero_or_nonfinite_mae'],
                'ratios': None, 'mean_ratio': None, 'improved_targets': None}
    ratios = {k: float(candidate_mae[k] / baseline_mae[k]) for k in TARGETS}
    if not all(math.isfinite(v) for v in ratios.values()):
        return {'valid': False, 'advance': False, 'reason': ['nonfinite_mae_ratio'],
                'ratios': None, 'mean_ratio': None, 'improved_targets': None}
    mean = math.fsum(ratios.values()) / len(TARGETS)
    improved = sum(candidate_mae[k] < baseline_mae[k] for k in TARGETS)
    reasons = []
    if improved < 3:
        reasons.append('fewer_than_three_mae_improvements')
    if mean >= 1:
        reasons.append('mean_mae_ratio_not_below_one')
    if any(value > 1.10 for value in ratios.values()):
        reasons.append('individual_mae_degradation_over_ten_percent')
    return {'valid': True, 'advance': not reasons, 'reason': reasons, 'ratios': ratios,
            'mean_ratio': mean, 'improved_targets': improved}


def _composition(records, ingredient_records):
    counts, counts_one, extra, omitted, l1, totals, negative_counts, negative_mass = [], [], [], [], [], [], [], []
    excluded = 0
    for sid, record in records.items():
        if record['fallback']:
            excluded += 1
            continue
        truth = {key: row['grams'] for key, row in _ingredients(ingredient_records[sid]).items()}
        masses = record['ingredient_grams']
        counts.append(sum(v > 0 for v in masses.values()))
        counts_one.append(sum(v >= 1 for v in masses.values()))
        extra.append(math.fsum(v for k, v in masses.items() if k not in truth))
        omitted.append(math.fsum(v for k, v in truth.items() if masses.get(k, 0) == 0))
        l1.append(math.fsum(abs(masses.get(k, 0) - truth.get(k, 0)) for k in set(masses) | set(truth)))
        totals.append(math.fsum(masses.values()))
        negative_counts.append(record['audit']['negative_gram_count_clipped'])
        negative_mass.append(record['audit']['negative_gram_magnitude_clipped'])
    def mean(values):
        return math.fsum(values) / len(values) if values else None
    total = math.fsum(totals)
    return {'evaluated_nonfallback_n': len(counts), 'excluded_whole_fallback_n': excluded,
            'positive_id_count_mean': mean(counts), 'at_least_one_gram_id_count_mean': mean(counts_one),
            'absent_id_mass_grams_mean': mean(extra),
            'absent_id_mass_fraction_pooled': math.fsum(extra) / total if total > 0 else None,
            'omitted_true_id_mass_grams_mean': mean(omitted), 'ingredient_l1_grams_mean': mean(l1),
            'negative_gram_count_clipped_mean': mean(negative_counts),
            'negative_gram_magnitude_clipped_mean': mean(negative_mass)}


def evaluate_oof(rows, vectors_by_id, ingredient_records, official_targets, *, expected_n=230, expected_groups=230):
    """Full grouped OOF; alternate expected counts are for invented test fixtures.

    Production uses the registered defaults. No label access occurs in predict;
    fold-specific fit explicitly scopes every ingredient/official-label lookup.
    """
    require(isinstance(rows, list) and all(isinstance(row, dict) and set(row) == {'sample_id', 'group_id'}
                                        for row in rows), 'row_metadata_fields_changed')
    ids = [_identifier(row['sample_id']) for row in rows]
    groups = {_identifier(row['group_id']) for row in rows}
    require(len(ids) == expected_n and len(set(ids)) == expected_n and len(groups) == expected_groups,
            'registered_population_changed')
    require(set(vectors_by_id) == set(ids) and set(ingredient_records) == set(ids)
            and set(official_targets) == set(ids), 'input_population_changed')
    folds = assign_folds(groups)
    by_id = {row['sample_id']: row for row in rows}
    records, baselines, fold_audit = {}, {}, []
    for fold in range(FOLDS):
        heldout = sorted(sid for sid in ids if folds[by_id[sid]['group_id']] == fold)
        training = sorted(set(ids) - set(heldout))
        model = fit(vectors_by_id, ingredient_records, official_targets, training)
        train_groups = sorted({by_id[sid]['group_id'] for sid in training})
        heldout_groups = sorted({by_id[sid]['group_id'] for sid in heldout})
        require(not set(train_groups) & set(heldout_groups), 'heldout_group_in_training')
        for sid in heldout:
            records[sid] = {**predict(model, vectors_by_id[sid]), 'fold': fold}
            baselines[sid] = dict(model.fallback)
        fold_audit.append({'fold': fold, 'train_ids': training, 'heldout_ids': heldout,
            'train_groups': train_groups, 'heldout_groups': heldout_groups,
            'catalogue_ingredient_count': len(model.ingredient_ids), 'fallback': model.fallback})
    require(set(records) == set(ids), 'incomplete_oof_population')
    truths = {sid: _targets(official_targets[sid]) for sid in ids}
    candidate_mae = {k: math.fsum(abs(records[sid]['prediction'][k] - truths[sid][k]) for sid in ids) / len(ids)
                     for k in TARGETS}
    baseline_mae = {k: math.fsum(abs(baselines[sid][k] - truths[sid][k]) for sid in ids) / len(ids)
                    for k in TARGETS}
    discrepancies = {k: [] for k in TARGETS}
    for sid in ids:
        ingredients = _ingredients(ingredient_records[sid])
        total = {'weight': math.fsum(item['grams'] for item in ingredients.values())}
        total.update({k: math.fsum(item['nutrients'][k] for item in ingredients.values()) for k in NUTRIENTS})
        for k in TARGETS:
            discrepancies[k].append(truths[sid][k] - total[k])
    source_audit = {k: {'nonzero_at_0_001_n': sum(abs(v) > 0.001 for v in values),
                        'signed_sum': math.fsum(values), 'min': min(values), 'max': max(values)}
                    for k, values in discrepancies.items()}
    aggregate = {'version': VERSION, 'scope': 'external_training_group_oof_prior_utility_not_paper_acceptance',
        'api_calls': 0, 'lambda': RIDGE_LAMBDA, 'kernel': 'linear', 'fit_loss': 'unaveraged_squared_error',
        'n': len(ids), 'groups': len(groups), 'fold_count': FOLDS,
        'whole_fallback_n': sum(record['fallback'] for record in records.values()),
        'candidate_mae': candidate_mae, 'fold_median_baseline_mae': baseline_mae,
        'advance_gate': advance_gate(candidate_mae, baseline_mae),
        'composition': _composition(records, ingredient_records),
        'official_minus_ingredient_totals': source_audit}
    return {'aggregate': aggregate, 'oof_predictions': records, 'fold_audit': fold_audit,
            'group_folds': folds}
