#!/usr/bin/env python3
"""Offline scoring of all 25 sealed L pairs; no fitting or paid requests.

The complete zero-Provider driver verification precedes construction of the
reference reader. Only fixed training-release references can then be opened.
The paired gate is a training utility filter, never independent acceptance.
"""
from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
import hashlib
import json
import math
import os
from pathlib import Path
import sys

import numpy as np

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / 'src')]
import opt_metrics as metrics
from round4.src.artifacts import ArtifactStore, canonical, decode, fingerprint
from round6.src import train_context as context

OUTPUT = 'round6/scoring/L_pilot'
BASE = 'round6/runs/L_pilot'
SOURCE_NAMES = ('round6/src/score_pilot.py', 'round6/tests/test_score_pilot.py',
                'src/opt_metrics.py', 'round4/src/artifacts.py')
BOOTSTRAP, SEED = 10000, 20261102
SCOPE = 'external_training_paired_pilot_not_independent_acceptance'


def require(condition, code):
    if not condition:
        raise ValueError(code)


def _number(value):
    require(type(value) in (int, float) and math.isfinite(value) and value >= 0, 'finite_nonnegative_value_required')
    return float(value)


def _vector(value):
    require(isinstance(value, dict) and set(value) == set(metrics.KEYS), 'all_five_targets_required')
    return {k: _number(value[k]) for k in metrics.KEYS}


def _checks(summary):
    checks = []
    for target in metrics.KEYS:
        for statistic in ('mae', 'per_unit'):
            value = summary['primary']['metrics'][target][statistic]
            cap = metrics.THRESHOLDS['nutrition5k'][target][statistic == 'per_unit']
            passed = type(value) in (int, float) and math.isfinite(value) and 0 <= value <= cap
            checks.append({'dataset': 'nutrition5k', 'target': target, 'statistic': statistic,
                           'value': value, 'threshold': cap, 'pass': bool(passed)})
    return checks


def advance_gate(baseline, candidate):
    """Fixed, full-precision whole-profile gate; zero baseline rejects safely."""
    old = [baseline['primary']['metrics'][k]['mae'] for k in metrics.KEYS]
    new = [candidate['primary']['metrics'][k]['mae'] for k in metrics.KEYS]
    valid = all(type(x) in (int, float) and math.isfinite(x) and x > 0 for x in old)
    valid &= all(type(x) in (int, float) and math.isfinite(x) and x >= 0 for x in new)
    ratios = [b / a for a, b in zip(old, new)] if valid else None
    old_checks, new_checks = _checks(baseline), _checks(candidate)
    check_values = old_checks + new_checks
    valid &= all(type(c['value']) in (int, float) and math.isfinite(c['value']) and c['value'] >= 0
                 for c in check_values)
    improved = sum(b < a for a, b in zip(old, new)) if valid else 0
    old_worst = max(c['value'] / c['threshold'] for c in old_checks) if valid else None
    new_worst = max(c['value'] / c['threshold'] for c in new_checks) if valid else None
    regressions = [{'target': a['target'], 'statistic': a['statistic']} for a, b in zip(old_checks, new_checks)
                   if a['pass'] and not b['pass']]
    conditions = {'at_least_three_mae_improvements': valid and improved >= 3,
                  'mean_five_mae_ratios_at_most_0_90': valid and math.fsum(ratios) / 5 <= .90,
                  'no_mae_ratio_above_1_05': valid and max(ratios) <= 1.05,
                  'strictly_lower_worst_ten_cap_ratio': valid and new_worst < old_worst,
                  'no_previously_passed_check_regression': valid and not regressions}
    return {'valid': bool(valid), 'advance': bool(valid and all(conditions.values())),
            'conditions': {k: bool(v) for k, v in conditions.items()},
            'improved_mae_count': improved, 'five_mae_ratios': ratios if valid else None,
            'mean_mae_ratio': math.fsum(ratios) / 5 if valid else None,
            'baseline_worst_ten_cap_ratio': old_worst, 'candidate_worst_ten_cap_ratio': new_worst,
            'regressed_checks': regressions,
            'decision_scope': 'permits_registration_of_one_84_image_development_candidate_only',
            'invalid_reason': None if valid else 'zero_or_nonfinite_baseline_or_metric'}


def _mass_diagnostic(branch, truth_ingredients):
    true = {}
    for item in truth_ingredients:
        grams = _number(item['grams'])
        identifier = item['ingredient_id']
        true[identifier] = true.get(identifier, 0.0) + grams
    predicted, unknown = {}, 0.0
    if branch['fallback']:
        require(not branch['raw_leaves'], 'fallback_must_not_have_fabricated_ingredient_leaves')
        unknown = _number(branch['prediction']['weight'])
    else:
        for leaf in branch['raw_leaves']:
            grams = _number(leaf['grams'])
            identifier = leaf['ingredient_id']
            if identifier is None:
                unknown += grams
            else:
                predicted[identifier] = predicted.get(identifier, 0.0) + grams
        require(abs(math.fsum(predicted.values()) + unknown - branch['prediction']['weight']) <= .001,
                'leaf_mass_must_equal_prediction_weight')
    omitted = math.fsum(grams for identifier, grams in true.items() if identifier not in predicted)
    extra = math.fsum(grams for identifier, grams in predicted.items() if identifier not in true)
    shared = math.fsum(abs(true[k] - predicted[k]) for k in true.keys() & predicted.keys())
    overlap = math.fsum(min(true[k], predicted.get(k, 0.0)) for k in true)
    denominator = math.fsum(true.values()) + math.fsum(predicted.values()) + unknown
    require(denominator > 0, 'positive_mass_diagnostic_denominator_required')
    return {'exact_id_gram_l1': omitted + extra + shared + unknown,
            'omitted_grams': omitted, 'extra_id_grams': extra, 'shared_id_gram_l1': shared,
            'unknown_grams': unknown, 'mass_overlap_dice': 2 * overlap / denominator}


def paired_bootstrap(rows, truths, predictions, *, count=BOOTSTRAP, seed=SEED):
    """Same sampled groups for both branches; CI does not drive the gate."""
    require(type(count) is int and count >= 0, 'invalid_bootstrap_count')
    names = sorted({r['group_id'] for r in rows})
    require(len(names) == len(rows), 'registered_pilot_requires_one_query_per_group')
    if count == 0:
        return {'replicates': 0, 'seed': seed, 'unit': 'training_group_id', 'intervals': {}}
    by_group = {r['group_id']: r['sample_id'] for r in rows}
    order = [by_group[g] for g in names]
    y = np.array([[truths[sid][k] for k in metrics.KEYS] for sid in order])
    errors = {role: np.abs(np.array([[predictions[role][sid][k] for k in metrics.KEYS] for sid in order]) - y)
              for role in ('baseline', 'candidate')}
    picks = np.random.default_rng(seed).integers(0, len(rows), size=(count, len(rows)))
    reference = y[picks].mean(axis=1)
    maes = {role: value[picks].mean(axis=1) for role, value in errors.items()}
    intervals = {}
    for i, key in enumerate(metrics.KEYS):
        for statistic in ('mae', 'per_unit'):
            values = {role: array[:, i] if statistic == 'mae' else
                      np.divide(array[:, i], reference[:, i], out=np.full(count, np.nan), where=reference[:, i] > 0)
                      for role, array in maes.items()}
            values['candidate_minus_baseline'] = values['candidate'] - values['baseline']
            intervals[key + '.' + statistic] = {}
            for role, array in values.items():
                finite = array[np.isfinite(array)]
                bounds = np.quantile(finite, [.025, .975]).tolist() if len(finite) else [None, None]
                intervals[key + '.' + statistic][role] = {'low': bounds[0], 'high': bounds[1],
                                                         'valid_replicates': len(finite)}
    return {'replicates': count, 'seed': seed, 'unit': 'training_group_id', 'group_count': len(names),
            'confidence': .95, 'paired': True, 'gate_uses_intervals': False,
            'scope': 'descriptive_fixed_predictions_no_refitting', 'intervals': intervals}


def summarize(records, rows, labels, ingredient_records, *, bootstrap=BOOTSTRAP):
    ids = {row['sample_id'] for row in rows}
    require(len(records) == len(rows) == len(ids) == 25 and set(records) == ids
            and set(labels) == set(ingredient_records) == ids, 'all_25_paired_records_required')
    require(len({r['group_id'] for r in rows}) == 25 and {r['fold'] for r in rows} == set(range(5)),
            'registered_25_group_five_fold_population_required')
    truths, predictions, summaries, diagnostics = {}, {'baseline': {}, 'candidate': {}}, {}, {}
    for row in rows:
        sid, record = row['sample_id'], records[row['sample_id']]
        require(all(record[k] == row[k] for k in ('sample_id', 'group_id', 'fold', 'dataset'))
                and record['query_id'] == sid, 'paired_record_metadata_changed')
        truths[sid] = _vector(labels[sid]['truth'])
        for role in predictions:
            branch = record[role]
            require(all(type(branch[k]) is bool for k in ('fallback', 'method_fallback', 'repair_used', 'native_complete')),
                    'branch_state_must_be_boolean')
            predictions[role][sid] = _vector(branch['prediction'])
    for role in predictions:
        internal = [{'manifest': row, 'label': {'truth': truths[row['sample_id']]},
                     'pred': records[row['sample_id']][role]} for row in rows]
        summaries[role] = metrics._dataset_stats(internal, 'nutrition5k')
        summaries[role]['checks'] = _checks(summaries[role])
        summaries[role]['passed_checks'] = sum(c['pass'] for c in summaries[role]['checks'])
        mass = [_mass_diagnostic(records[sid][role], ingredient_records[sid]) for sid in sorted(ids)]
        diagnostics[role] = {key: math.fsum(r[key] for r in mass) / 25 for key in mass[0]}
        diagnostics[role]['population_n'] = 25
    atlases = {}
    usages, usage_statuses = 0, Counter()
    for record in records.values():
        for tid, item in record.get('stages', {}).get('atlas', {}).items():
            result = item['result']
            require(tid not in atlases or atlases[tid] == result, 'shared_atlas_results_changed')
            atlases[tid] = result
            usages += 1
            usage_statuses.update(a['status'] for a in result['annotations'])
    unique_statuses = Counter(a['status'] for result in atlases.values() for a in result['annotations'])
    crop_counts = Counter(len(record.get('crop_provenance', [])) for record in records.values())
    actual_crops = sum(count * queries for count, queries in crop_counts.items())
    return {'scope': SCOPE, 'n': 25, 'groups': 25, 'folds': 5, 'development_opened': False,
        'validation_opened': False, 'calibration_applied': False, **summaries,
        'advance_gate': advance_gate(summaries['baseline'], summaries['candidate']),
        'paired_bootstrap': paired_bootstrap(rows, truths, predictions, count=bootstrap),
        'exact_id_mass_diagnostic': diagnostics,
        'atlas_availability': {'unique_supports': len(atlases), 'support_usages': usages,
            'unique_available': sum(r['failure'] is None for r in atlases.values()),
            'unique_unavailable': sum(r['failure'] is not None for r in atlases.values()),
            'unique_repaired': sum(r['repair_used'] for r in atlases.values()),
            'unique_annotation_status_counts': dict(sorted(unique_statuses.items())),
            'usage_annotation_status_counts': dict(sorted(usage_statuses.items())),
            'actual_crop_cards': actual_crops, 'mean_crop_cards_per_query': actual_crops / 25,
            'queries_with_zero_crop_cards': crop_counts[0],
            'queries_by_crop_card_count': {str(k): v for k, v in sorted(crop_counts.items())}},
        'mechanism_limitations': ['automatic_regions_are_not_human_ground_truth',
            'whole_support_id_mass_is_not_measured_crop_mass',
            'shared_id_metrics_have_changing_populations',
            'intervention_combines_region_hints_crops_and_attention',
            'pilot_gate_is_not_independent_acceptance']}


def verified_base(root=ROOT):
    from round6.src.run_pilot import base
    value = base(verify_only=True, root=root)
    require(value.get('status') == 'base_verified' and value.get('n') == 25
            and value.get('provider_constructed') is False and value.get('validation_opened') is False
            and value.get('development_opened') is False and len(value.get('records', {})) == 25,
            'complete_zero_provider_paired_verification_required')
    return decode(canonical({k: value[k] for k in ('records', 'binding', 'completion_sha256')}))


class ReferenceReader:
    """Constructed only after full base verification; exact training allowlist."""
    def __init__(self, root, verified):
        self.root, self.hashes = Path(root), {}
        self.allowed = {*SOURCE_NAMES, *context.SOURCES, BASE + '/intent.json', BASE + '/completion.json',
                        context.TRAIN + '/freeze.json', context.TRAIN + '/labels.json',
                        context.TRAIN + '/ingredients.json'}
        self.pins = dict(verified['binding']['input_sha256'])
        self.pins.update({context.PROTOCOL: context.PROTOCOL_SHA256,
            context.TRAIN + '/freeze.json': context.TRAIN_FREEZE_SHA256,
            BASE + '/completion.json': verified['completion_sha256'],
            'src/opt_metrics.py': '15d71fd2c2379f7f723707cddfeb2e2868c0dd84b027edd12ef9185303a1e63e'})

    def read(self, name):
        require(name in self.allowed, 'scoring_input_not_allowlisted')
        path = self.root / name
        require(path.resolve() == path and path.is_file(), 'unsafe_or_missing_scoring_input')
        raw = path.read_bytes()
        value = hashlib.sha256(raw).hexdigest()
        require(name not in self.pins or value == self.pins[name], 'pinned_scoring_input_changed')
        require(name not in self.hashes or value == self.hashes[name], 'scoring_input_changed')
        self.hashes[name] = value
        return raw

    def unchanged(self):
        for name in tuple(self.hashes):
            self.read(name)


def score(*, root=ROOT):
    verified = verified_base(root)  # MUST precede constructing a target reader.
    root = Path(root)
    reader = ReferenceReader(root, verified)
    binding = verified['binding']
    require(binding.get('phase') == 'external_training_paired_pilot'
            and binding.get('method_config') == context.METHOD_CONFIG and binding.get('query_count') == 25
            and binding.get('query_groups') == 25, 'registered_pilot_binding_required')
    intent = decode(reader.read(BASE + '/intent.json'))
    require(intent.get('binding') == binding and intent.get('expected_records') == sorted(verified['records']),
            'paired_base_external_binding_changed')
    reader.read(BASE + '/completion.json')
    freeze = decode(reader.read(context.TRAIN + '/freeze.json'))
    require(freeze['artifacts']['labels.json'] == reader.pins[context.TRAIN + '/labels.json']
            and freeze['artifacts']['ingredients.json'] == reader.pins[context.TRAIN + '/ingredients.json'],
            'reference_release_binding_changed')
    for name in (*context.SOURCES, *SOURCE_NAMES):
        reader.read(name)
    score_binding = {'schema_version': 1, 'phase': 'external_training_paired_pilot_scoring', 'scope': SCOPE,
        'base_completion_sha256': verified['completion_sha256'], 'base_records_sha256': fingerprint(verified['records']),
        'source_sha256': {name: reader.hashes[name] for name in (*context.SOURCES, *SOURCE_NAMES)},
        'reference_sha256': {name: reader.pins[name] for name in
            (context.TRAIN + '/labels.json', context.TRAIN + '/ingredients.json')},
        'bootstrap': BOOTSTRAP, 'seed': SEED, 'calibration_applied': False,
        'development_opened': False, 'validation_opened': False}
    store = ArtifactStore(root / OUTPUT, score_binding, ['metrics'], verify_sources=reader.unchanged, root=root / 'round6')
    saved = store.verify_completed() if (root / OUTPUT / 'completion.json').exists() else None
    rows = binding['pilot_rows']
    ids = {r['sample_id'] for r in rows}
    all_labels = decode(reader.read(context.TRAIN + '/labels.json'))
    all_ingredients = decode(reader.read(context.TRAIN + '/ingredients.json'))['records']
    by_id = {r['sample_id']: r for r in all_ingredients}
    require(len(all_labels) == len(by_id) == len(all_ingredients) == 230 and ids <= set(all_labels) == set(by_id),
            'training_reference_population_changed')
    labels = {sid: all_labels[sid] for sid in ids}
    ingredients = {sid: by_id[sid]['ingredients'] for sid in ids}
    summary = summarize(verified['records'], rows, labels, ingredients)
    require(fingerprint(verified_base(root)) == fingerprint(verified), 'paired_base_changed_during_scoring')
    reader.unchanged()
    if saved is not None:
        require(saved == {'metrics': summary}, 'recomputed_pilot_metrics_changed')
        status = 'pilot_scoring_verified'
    else:
        store.finalize({'metrics': summary})
        status = 'pilot_scoring_complete'
    require(store.verify_completed() == {'metrics': summary}, 'pilot_score_seal_mismatch')
    return {'status': status, 'metrics': summary, 'provider_constructed': False,
            'development_opened': False, 'validation_opened': False, 'output': OUTPUT}


def main(argv=None):
    argparse.ArgumentParser(description=__doc__).parse_args(argv)
    os.umask(0o077)
    try:
        result = score()
        print(json.dumps({k: v for k, v in result.items() if k != 'metrics'} | {
            'advance': result['metrics']['advance_gate']['advance'],
            'baseline_passed_checks': result['metrics']['baseline']['passed_checks'],
            'candidate_passed_checks': result['metrics']['candidate']['passed_checks']}, sort_keys=True, allow_nan=False))
        return 0
    except BaseException as error:
        if isinstance(error, (KeyboardInterrupt, SystemExit)):
            raise
        print(json.dumps({'status': 'stopped', 'error_type': type(error).__name__}, sort_keys=True))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
