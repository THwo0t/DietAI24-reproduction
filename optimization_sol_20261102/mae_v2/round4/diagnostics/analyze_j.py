#!/usr/bin/env python3
"""Posthoc J continuation diagnostics, never predictions or a selection input.

Require the full base and completed scoring seal before reference labels. The
base verifier can reread bound images for integrity; this module does not open
images. True-weight scaling directly uses each query's truth and is not an
achievable bound, OOF calibration, or a new candidate. Only aggregates are saved.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import json
import math
import os
from pathlib import Path
import sys

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / 'src')]
from round4.continuation import evaluate as continuation
from round4.src.artifacts import ArtifactStore, canonical, decode, fingerprint

scorer = continuation.scorer
KEYS = tuple(scorer.metrics.KEYS)
NUTRIENTS = tuple(key for key in KEYS if key != 'weight')
INGREDIENTS = 'round3/data/dev_ingredients.json'
INGREDIENTS_SHA256 = '8e4607fd58372e5bf8489cbcdeabe23399230d4dfdc70592642f778f0aef5753'
CATALOG = 'round4/data/train/catalog.json'
CATALOG_SIZE = 164
OUTPUT = 'round4/diagnostics/results/J_service_continuation'
SOURCES = ('round4/diagnostics/analyze_j.py', 'src/opt_metrics.py')
COMPONENTS = ('omitted_reference', 'extra_known_id', 'unknown', 'shared_id_mass',
              'shared_id_density', 'reference_reconciliation', 'prediction_reconciliation',
              'whole_fallback_error')
verified_base = continuation._verified_base
external_binding = continuation._external_binding
Inputs = scorer.Inputs


class DiagnosticError(ValueError):
    """Fixed safe codes only; no sample ID, target or model text."""


def require(condition, code):
    if not condition:
        raise DiagnosticError(code)


def number(value):
    require(not isinstance(value, bool) and isinstance(value, (int, float))
            and math.isfinite(value) and value >= 0, 'finite_nonnegative_value_required')
    return float(value)


def vector(value, *, positive_weight=True):
    require(isinstance(value, dict) and set(value) == set(KEYS), 'five_target_vector_required')
    out = {key: number(value[key]) for key in KEYS}
    require(not positive_weight or out['weight'] > 0, 'nonpositive_weight_invalid_full_population')
    return out


def true_weight_oracle(records, labels):
    """All rows or an explicit error; no row filtering or mutation of raw data."""
    require(isinstance(records, dict) and bool(records) and set(records) == set(labels),
            'oracle_population_mismatch')
    checked = {}
    for sid, record in records.items():
        pred, truth = vector(record['prediction']), vector(labels[sid]['truth'])
        factor = truth['weight'] / pred['weight']
        scaled = {key: pred[key] * factor for key in KEYS}
        scaled['weight'] = truth['weight']  # Exact oracle identity, avoiding floating roundoff.
        checked[sid] = vector(scaled)
    result = deepcopy(records)
    for sid, prediction in checked.items():
        result[sid]['prediction'] = prediction
    return result


def _reference(items):
    grouped = {}
    for item in items:
        identifier, grams = item['ingredient_id'], number(item['grams'])
        require(isinstance(identifier, str) and bool(identifier), 'reference_id_required')
        nutrients = {key: number(item['nutrients'][key]) for key in NUTRIENTS}
        require(grams > 0 or not any(nutrients.values()), 'zero_reference_mass_nonzero_nutrients')
        if not grams:
            continue
        row = grouped.setdefault(identifier, {key: [] for key in KEYS})
        row['weight'].append(grams)
        for key in NUTRIENTS:
            row[key].append(nutrients[key])
    require(bool(grouped), 'positive_reference_ingredients_required')
    return {identifier: {key: math.fsum(values) for key, values in row.items()}
            for identifier, row in grouped.items()}


def _predicted(leaves):
    grouped, unknown = {}, {key: [] for key in KEYS}
    require(isinstance(leaves, list) and bool(leaves), 'nonfallback_leaves_required')
    for leaf in leaves:
        grams = number(leaf['grams'])
        require(grams > 0 and isinstance(leaf['density'], dict)
                and set(leaf['density']) == set(NUTRIENTS), 'positive_leaf_and_four_densities_required')
        amounts = {'weight': grams, **{key: grams * number(leaf['density'][key]) / 100 for key in NUTRIENTS}}
        identifier = leaf['ingredient_id']
        require(identifier is None or isinstance(identifier, str) and bool(identifier), 'invalid_predicted_id')
        row = unknown if identifier is None else grouped.setdefault(identifier, {key: [] for key in KEYS})
        for key in KEYS:
            row[key].append(amounts[key])
    return ({identifier: {key: math.fsum(values) for key, values in row.items()}
             for identifier, row in grouped.items()},
            {key: math.fsum(values) for key, values in unknown.items()})


def decompose(record, reference, truth, catalog_ids):
    """Signed accounting identity, not causal attribution or additive MAE."""
    require(isinstance(catalog_ids, (set, frozenset)) and bool(catalog_ids)
            and all(isinstance(value, str) and value for value in catalog_ids), 'bound_catalog_ids_required')
    pred, truth = vector(record['prediction']), vector(truth)
    require(type(record.get('fallback')) is bool, 'fallback_flag_required')
    components = {key: dict.fromkeys(COMPONENTS, 0.0) for key in KEYS}
    if record['fallback']:
        require(not record.get('raw_leaves'), 'whole_fallback_must_not_have_estimated_leaves')
        for key in KEYS:
            components[key]['whole_fallback_error'] = pred[key] - truth[key]
        return {'decomposable': False, 'mass': None, 'omission_catalog_split': None, 'components': components,
                'signed_error': {key: pred[key] - truth[key] for key in KEYS}, 'max_identity_residual': 0.0}
    p, unknown = _predicted(record['raw_leaves'])
    t = _reference(reference)
    require(p.keys() <= catalog_ids, 'predicted_known_id_absent_from_bound_catalog')
    shared, missing, extra = p.keys() & t.keys(), t.keys() - p.keys(), p.keys() - t.keys()
    unavailable, available = missing - catalog_ids, missing & catalog_ids
    omission_split = {
        'catalog_absent_reference_id_g': math.fsum(t[i]['weight'] for i in unavailable),
        'catalog_present_unselected_reference_id_g': math.fsum(t[i]['weight'] for i in available),
        'catalog_absent_reference_id_dish_occurrences': len(unavailable),
        'catalog_present_unselected_reference_id_dish_occurrences': len(available)}
    pred_total = {key: math.fsum([unknown[key], *(row[key] for row in p.values())]) for key in KEYS}
    true_total = {key: math.fsum(row[key] for row in t.values()) for key in KEYS}
    require(all(math.isclose(pred_total[key], pred[key], rel_tol=1e-10, abs_tol=1e-7) for key in KEYS),
            'leaf_prediction_accounting_changed')
    require(all(abs(true_total[key] - truth[key]) <= .001 for key in KEYS),
            'reference_ingredient_totals_changed')
    for key in KEYS:
        c = components[key]
        c['omitted_reference'] = -math.fsum(t[identifier][key] for identifier in missing)
        c['extra_known_id'] = math.fsum(p[identifier][key] for identifier in extra)
        c['unknown'] = unknown[key]
        c['shared_id_mass'] = math.fsum(
            (p[identifier]['weight'] - t[identifier]['weight']) * t[identifier][key] / t[identifier]['weight']
            for identifier in shared)
        c['shared_id_density'] = math.fsum(
            p[identifier][key] - p[identifier]['weight'] * t[identifier][key] / t[identifier]['weight']
            for identifier in shared)
        c['reference_reconciliation'] = true_total[key] - truth[key]
        c['prediction_reconciliation'] = pred[key] - pred_total[key]
    overlap = math.fsum(min(p[i]['weight'], t[i]['weight']) for i in shared)
    mass = {'predicted_g': pred_total['weight'], 'reference_g': true_total['weight'],
        'unknown_g': unknown['weight'], 'omitted_reference_id_g': math.fsum(t[i]['weight'] for i in missing),
        'extra_known_id_g': math.fsum(p[i]['weight'] for i in extra),
        'shared_id_under_g': math.fsum(max(t[i]['weight'] - p[i]['weight'], 0) for i in shared),
        'shared_id_over_g': math.fsum(max(p[i]['weight'] - t[i]['weight'], 0) for i in shared),
        'exact_id_overlap_g': overlap,
        'reference_mass_with_present_id_g': math.fsum(t[i]['weight'] for i in shared)}
    mass['unpaired_mass_l1_g'] = math.fsum(mass[key] for key in
        ('unknown_g', 'omitted_reference_id_g', 'extra_known_id_g', 'shared_id_under_g', 'shared_id_over_g'))
    require(math.isclose(mass['unpaired_mass_l1_g'], mass['predicted_g'] + mass['reference_g'] - 2 * overlap,
                         rel_tol=1e-10, abs_tol=1e-7), 'mass_identity_failed')
    errors = {key: pred[key] - truth[key] for key in KEYS}
    residual = max(abs(math.fsum(components[key].values()) - errors[key]) for key in KEYS)
    require(residual <= 1e-7, 'nutrient_decomposition_identity_failed')
    require(math.isclose(omission_split['catalog_absent_reference_id_g']
                        + omission_split['catalog_present_unselected_reference_id_g'],
                        mass['omitted_reference_id_g'], rel_tol=1e-10, abs_tol=1e-7),
            'omission_catalog_split_identity_failed')
    return {'decomposable': True, 'mass': mass, 'omission_catalog_split': omission_split, 'components': components,
            'signed_error': errors, 'max_identity_residual': residual}


def aggregate_decomposition(values):
    require(bool(values), 'nonempty_diagnostic_population_required')
    masses = [value['mass'] for value in values if value['decomposable']]
    total = {key: math.fsum(m[key] for m in masses) for key in masses[0]} if masses else {}
    ratios = None
    if masses:
        ratios = {'unknown_fraction_of_predicted_mass': total['unknown_g'] / total['predicted_g'],
            'present_id_reference_mass_fraction': total['reference_mass_with_present_id_g'] / total['reference_g'],
            'exact_id_overlap_reference_fraction': total['exact_id_overlap_g'] / total['reference_g'],
            'exact_id_overlap_predicted_fraction': total['exact_id_overlap_g'] / total['predicted_g']}
    splits = [value['omission_catalog_split'] for value in values if value['decomposable']]
    split_totals = {key: math.fsum(row[key] for row in splits) if key.endswith('_g')
                    else sum(row[key] for row in splits) for key in splits[0]} if splits else {}
    split = {'population_n': len(values), 'decomposable_n': len(splits),
        'excluded_whole_fallback_n': len(values) - len(splits),
        'totals_on_decomposable_rows': split_totals,
        'measured_mass_sums_divided_by_population_n': {
            key: value / len(values) for key, value in split_totals.items() if key.endswith('_g')},
        'mean_mass_on_decomposable_rows': {
            key: value / len(splits) for key, value in split_totals.items() if key.endswith('_g')} if splits else None,
        'definition': 'Exact-ID dish occurrences after merging duplicate ID entries. Whole fallbacks have no ingredient decomposition; full-population denominators do not impute their omitted mass.'}
    return {'population_n': len(values), 'decomposable_n': len(masses), 'whole_fallback_n': len(values) - len(masses),
        'mass_totals_on_decomposable_rows': total, 'mass_micro_rates_on_decomposable_rows': ratios,
        'omitted_reference_catalog_availability': split,
        'components_all_rows': {key: {name: {
            'mean_signed': math.fsum(v['components'][key][name] for v in values) / len(values),
            'mean_absolute': math.fsum(abs(v['components'][key][name]) for v in values) / len(values)}
            for name in COMPONENTS} for key in KEYS},
        'mean_signed_error_all_rows': {key: math.fsum(v['signed_error'][key] for v in values) / len(values) for key in KEYS},
        'maximum_accounting_identity_residual': max(v['max_identity_residual'] for v in values)}


def _completed_scoring(reader, verified):
    directory = continuation.SCORE_OUTPUT
    intent = decode(reader.read(directory + '/intent.json'))
    binding = intent.get('binding', {})
    require(binding.get('candidate') == continuation.CANDIDATE
            and binding.get('phase') == 'service_continuation_calibration_scoring'
            and binding.get('service_continuation') is True
            and binding.get('base_completion_sha256') == verified['completion_sha256']
            and binding.get('base_records_sha256') == fingerprint(verified['records']),
            'matching_completed_scoring_required_before_labels')
    store = ArtifactStore(ROOT / directory, binding, ['metrics'], verify_sources=reader.unchanged,
                          root=ROOT / 'round4')
    saved = store.verify_completed()['metrics']
    reader.read(directory + '/completion.json')
    for relative, key in ((continuation.RAW_OUTPUT + '/completion.json', 'raw_scoring_completion_sha256'),
                          (continuation.CAL_OUTPUT + '/completion.json', 'calibration_completion_sha256')):
        reader.read(relative)
        require(reader.hashes[relative] == binding.get(key), 'scoring_dependency_completion_changed')
    return saved


def run():
    verified = verified_base()
    records = verified['records']
    require(len(records) == 84, 'all_84_base_records_required')
    reader = Inputs(ROOT)
    reader.read(continuation.SERVICE_PROTOCOL)
    proof = external_binding(reader, verified)
    saved_score = _completed_scoring(reader, verified)
    # Read this exact training file only, never traverse recorded input paths.
    expected_catalog = verified['binding'].get('input_sha256', {}).get(CATALOG)
    require(isinstance(expected_catalog, str) and len(expected_catalog) == 64,
            'base_bound_training_catalog_hash_required')
    catalog_raw = reader.read(CATALOG)
    require(reader.hashes[CATALOG] == expected_catalog, 'base_bound_training_catalog_changed')
    catalog = decode(catalog_raw)
    catalog_ids = {item['ingredient_id'] for item in catalog['ingredients']}
    require(catalog.get('schema_version') == 1
            and catalog.get('scope') == 'accepted_external_training_only_domain_catalog'
            and len(catalog['ingredients']) == len(catalog_ids) == CATALOG_SIZE,
            'bound_training_catalog_population_changed')
    for name in SOURCES:
        reader.read(name)
    rows = scorer._manifest(reader.read(scorer.MANIFEST))
    n5 = [row for row in rows if row['dataset'] == 'nutrition5k']
    indexed = continuation.calibration._rows(n5)
    continuation.calibration._records(indexed, records)
    labels = decode(reader.read(scorer.LABELS))
    require(isinstance(labels, dict) and set(labels) == {row['sample_id'] for row in rows},
            'pinned_development_label_population_changed')
    labels = {sid: labels[sid] for sid in indexed}
    scorer.metrics._training(n5, labels)
    metadata = decode(reader.read(INGREDIENTS))
    require(reader.hashes[INGREDIENTS] == INGREDIENTS_SHA256, 'pinned_development_ingredients_changed')
    reference = {row['sample_id']: row for row in metadata['records']}
    require(len(metadata['records']) == len(reference) == 84 and set(reference) == set(indexed)
            and all(reference[sid].get('split') == 'dev' and all(reference[sid].get(key) == row[key]
                    for key in ('group_id', 'fold')) for sid, row in indexed.items()),
            'development_ingredient_population_changed')
    oracle = true_weight_oracle(records, labels)
    score = lambda values: scorer.metrics.evaluate(n5, labels, list(values.values()),
        bootstrap=0, seed=scorer.SEED)['datasets']['nutrition5k']
    raw, oracle_score = score(records), score(oracle)
    require(raw['primary']['metrics'] == saved_score['raw']['nutrition5k']['primary']['metrics'],
            'raw_point_metrics_differ_from_completed_scoring')
    decomposition = aggregate_decomposition([decompose(records[sid], reference[sid]['ingredients'],
        labels[sid]['truth'], catalog_ids) for sid in indexed])
    result = {'schema_version': 1, 'scope': 'posthoc_development_diagnostic_not_candidate_selection_or_acceptance',
        'candidate_source': continuation.CANDIDATE, 'n': 84, 'groups': 78,
        'training_catalog_size': len(catalog_ids), 'training_catalog_sha256': expected_catalog,
        'raw_point_metrics': raw['primary']['metrics'],
        'true_weight_oracle_point_metrics': oracle_score['primary']['metrics'],
        'already_sealed_calibrated_point_metrics': saved_score['calibrated']['nutrition5k']['primary']['metrics'],
        'definitions': {
            'raw': 'Unchanged external-training base totals, including every whole fallback.',
            'registered_calibration': 'Already sealed five target-wise OOF multipliers fitted on other folds; not refitted here.',
            'true_weight_oracle': 'Each of all 84 query truths sets its own factor true_weight/raw_predicted_weight; multiply all five totals, including fallback. This is not OOF and is not deployable.',
            'zero_predicted_weight': 'Invalidates the whole diagnostic; never removes an observation.',
            'extra_known_id': 'Positive predicted mass whose exact catalog ID is absent from reference; not proof of a visually false food.',
            'omitted_reference': 'Reference exact ID absent from predicted known IDs. Its mass is split by presence in the bound training catalog; neither subset proves a visual detection failure.',
            'catalog_absent_reference_id': 'Omitted exact reference ID unavailable among the bound training catalog IDs; an unknown item may still represent this food.',
            'catalog_present_unselected_reference_id': 'Omitted exact reference ID available in the bound training catalog but not selected; this is not proof of visual omission or semantic mismatch.',
            'unknown': 'Never remapped to a reference ID; it may represent real omitted food.',
            'shared_density': 'Predictive mass times predicted-minus-reference nutrient density for each shared exact ID.',
            'signed_accounting': 'Omitted + extra-known + unknown + shared-mass + shared-density + reference/prediction reconciliation + whole-fallback error equals signed error. Absolute component means do not sum to MAE.'},
        'decomposition': decomposition,
        'limitations': ['Exact-ID agreement does not establish semantic or region-level correctness.',
            'The mass/density split is ordered using reference density for the mass term; it is descriptive, not causal.',
            'True-weight scaling can worsen nutrient errors and does not guarantee attainable performance.',
            'Repeatedly used development data are not independent validation.'],
        'bootstrap_replicates': 0, 'calibration_refitted': False, 'new_profile_selected': False,
        'row_predictions_or_reference_rows_exported': False, 'provider_constructed': False,
        'validation_opened': False, 'api_calls': 0}
    require(fingerprint(verified_base()) == fingerprint(verified), 'base_changed_during_diagnostic')
    reader.unchanged()
    binding = {'phase': 'posthoc_service_continuation_diagnostic', 'scope': result['scope'],
        'external_training_proof': proof, 'base_completion_sha256': verified['completion_sha256'],
        'base_records_sha256': fingerprint(records), 'input_sha256': dict(reader.hashes),
        'ingredient_source_sha256': INGREDIENTS_SHA256}
    store = ArtifactStore(ROOT / OUTPUT, binding, ['aggregate'], verify_sources=reader.unchanged,
                          root=ROOT / 'round4/diagnostics')
    complete = (ROOT / OUTPUT / 'completion.json').exists()
    if complete:
        require(store.verify_completed() == {'aggregate': result}, 'diagnostic_recomputation_changed')
    else:
        store.finalize({'aggregate': result})
    return {'status': 'diagnostic_verified' if complete else 'diagnostic_complete', 'output': OUTPUT, 'aggregate': result}


def main(argv=None):
    os.umask(0o077)
    argparse.ArgumentParser(description=__doc__).parse_args(argv)
    try:
        result = run()
        print(json.dumps({'status': result['status'], 'output': result['output'], 'n': 84,
                          'scope': result['aggregate']['scope'], 'api_calls': 0}, sort_keys=True))
        return 0
    except Exception as error:
        print(json.dumps({'status': 'invalid_diagnostic', 'error_code': str(error)
            if isinstance(error, DiagnosticError) else type(error).__name__,
            'required_population_n': 84, 'dropped_rows': 0}, sort_keys=True))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
