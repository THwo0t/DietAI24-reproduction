"""Posthoc development diagnostic of sealed H; never an inference/selection input."""
from __future__ import annotations

from collections import defaultdict
import hashlib
import json
import math
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
TARGETS = ('weight', 'energy', 'fat', 'carbs', 'protein')


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                    allow_nan=False, separators=(',', ':')).encode()).hexdigest()


def mass_comparison(items, reference):
    """Exact-ID descriptive mass accounting; unknown never assumed matched."""
    p, t = defaultdict(float), defaultdict(float)
    unknown = 0.0
    for item in items:
        value = float(item['grams'])
        if not math.isfinite(value) or value <= 0:
            raise ValueError('Prediction item must have positive finite mass')
        if item['ingredient_id'] is None:
            unknown += value
        else:
            p[item['ingredient_id']] += value
    for item in reference:
        value = float(item['grams'])
        if not math.isfinite(value) or value < 0:
            raise ValueError('Reference item must have nonnegative finite mass')
        if value:
            t[item['ingredient_id']] += value
    predicted, truth = math.fsum(p.values()) + unknown, math.fsum(t.values())
    if predicted <= 0 or truth <= 0:
        raise ValueError('Positive total masses required')
    common = p.keys() & t.keys()
    overlap = math.fsum(min(p[k], t[k]) for k in common)
    missing = math.fsum(t[k] for k in t.keys() - p.keys())
    extra = math.fsum(p[k] for k in p.keys() - t.keys())
    under = math.fsum(max(t[k] - p[k], 0) for k in common)
    over = math.fsum(max(p[k] - t[k], 0) for k in common)
    out = {
        'reference_mass_g': truth, 'predicted_mass_g': predicted,
        'known_predicted_mass_g': math.fsum(p.values()), 'unknown_predicted_mass_g': unknown,
        'reference_mass_with_present_id_g': truth - missing,
        'prediction_mass_with_reference_id_g': math.fsum(p[k] for k in common),
        'exact_id_mass_overlap_g': overlap,
        'omitted_reference_id_mass_g': missing, 'extra_known_id_mass_g': extra,
        'matched_id_under_mass_g': under, 'matched_id_over_mass_g': over,
        'unpaired_mass_l1_g': missing + extra + under + over + unknown,
        'signed_total_mass_error_g': predicted - truth,
        'absolute_total_mass_error_g': abs(predicted - truth),
        'reference_id_count': len(t), 'predicted_known_id_count': len(p),
        'matched_id_count': len(common),
    }
    assert math.isclose(out['unpaired_mass_l1_g'], truth + predicted - 2 * overlap,
                        rel_tol=1e-10, abs_tol=1e-7)
    return out


def summarize(rows):
    if not rows:
        raise ValueError('No rows')
    totals = {key: math.fsum(r[key] for r in rows) for key in rows[0]}
    pred, truth = totals['predicted_mass_g'], totals['reference_mass_g']
    return {
        'n': len(rows), 'totals': totals,
        'micro_rates': {
            'known_predicted_mass_fraction': totals['known_predicted_mass_g'] / pred,
            'unknown_predicted_mass_fraction': totals['unknown_predicted_mass_g'] / pred,
            'reference_mass_with_present_id_fraction': totals['reference_mass_with_present_id_g'] / truth,
            'prediction_mass_with_reference_id_fraction': totals['prediction_mass_with_reference_id_g'] / pred,
            'exact_id_mass_overlap_reference_fraction': totals['exact_id_mass_overlap_g'] / truth,
            'exact_id_mass_overlap_prediction_fraction': totals['exact_id_mass_overlap_g'] / pred,
        },
        'mean_image_rates': {
            'unknown_predicted_mass_fraction': math.fsum(r['unknown_predicted_mass_g'] / r['predicted_mass_g'] for r in rows) / len(rows),
            'reference_mass_with_present_id_fraction': math.fsum(r['reference_mass_with_present_id_g'] / r['reference_mass_g'] for r in rows) / len(rows),
            'exact_id_mass_overlap_reference_fraction': math.fsum(r['exact_id_mass_overlap_g'] / r['reference_mass_g'] for r in rows) / len(rows),
        },
        'mean_image_mass_g': {key: value / len(rows) for key, value in totals.items() if key.endswith('_g')},
        'images_with_unknown': sum(r['unknown_predicted_mass_g'] > 0 for r in rows),
    }


def save(name, value):
    target = OUT / name
    raw = json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + '\n'
    with target.open('w') as stream:
        os.chmod(target, 0o600)
        stream.write(raw)


def main():
    hashes = {}

    def read(relative, decode=True):
        path = ROOT / relative
        assert not path.is_symlink() and path.resolve() == path and path.is_file()
        data = path.read_bytes()
        hashes[relative] = hashlib.sha256(data).hexdigest()
        return json.loads(data) if decode else data

    complete = read('round3/runs/H/completion.json')
    assert complete['candidate'] == 'H' and complete['n'] == 84 and complete['groups'] == 78
    assert complete['validation_opened'] is False
    expected_files = {'records_sealed.json', 'predictions.json', 'metrics.json', 'usage.json',
                      'binding.json', 'example_assignments.json'}
    assert set(complete['artifact_sha256']) == expected_files
    artifacts = {}
    for name, expected in complete['artifact_sha256'].items():
        rel = 'round3/runs/H/' + name
        data = read(rel, decode=False)
        assert hashes[rel] == expected
        if name in ('predictions.json', 'records_sealed.json', 'binding.json'):
            artifacts[name] = json.loads(data)
    h = artifacts['predictions.json']
    binding = artifacts['binding.json']
    assert fingerprint(binding) == complete['binding_sha256']
    assert binding['validation_access'] is False
    assert len(h) == 84 and len({r['sample_id'] for r in h}) == 84
    assert len({r['group_id'] for r in h}) == 78
    seal = artifacts['records_sealed.json']
    assert set(seal) == {r['sample_id'] for r in h}
    for record in h:
        rel = 'round3/runs/H/records/' + fingerprint(record['sample_id'])[:24] + '.json'
        envelope = read(rel)
        assert hashes[rel] == seal[record['sample_id']]
        assert envelope['record'] == record
        assert envelope['binding_sha256'] == complete['binding_sha256']
        assert envelope['record_sha256'] == fingerprint(record)
        assert not record['fallback'], 'Fallback needs separate mass-accounting policy'
        assert record['dataset'] == 'nutrition5k'

    metadata_rel = 'round3/data/dev_ingredients.json'
    label_rel = 'data/cohorts/dev_labels.json'
    metadata = read(metadata_rel)
    labels = read(label_rel)
    for rel in (metadata_rel, label_rel):
        assert hashes[rel] == binding['input_sha256'][rel]
    true = {r['sample_id']: r for r in metadata['records']}
    assert len(true) == 84 and set(true) == set(seal)
    assert all(r['split'] == 'dev' for r in true.values())
    groups = defaultdict(set)
    for r in true.values():
        groups[r['group_id']].add(r['fold'])
    assert all(len(v) == 1 for v in groups.values())
    prior = read('analysis/next_round_visual/private_checklist.json')
    fixed = {c['private_manifest']['sample_id']: c for c in prior['cases']}
    assert len(fixed) == 6
    stats, private, case_aggregates = [], [], []
    target_errors = {target: [] for target in TARGETS}
    catalog_unavailable, catalog_total = 0.0, 0.0
    main_present = 0
    for record in h:
        sid = record['sample_id']
        reference = true[sid]
        assert all(reference[k] == record[k] for k in ('group_id', 'fold'))
        truth = labels[sid]['truth']
        result = mass_comparison(record['items'], reference['ingredients'])
        assert math.isclose(result['predicted_mass_g'], record['prediction']['weight'], abs_tol=1e-6)
        assert math.isclose(result['reference_mass_g'], truth['weight'], abs_tol=1e-3)
        assert math.isclose(result['unknown_predicted_mass_g'] / result['predicted_mass_g'],
                            record['audit']['unknown_mass_fraction'], abs_tol=1e-10)
        for target in TARGETS:
            target_errors[target].append(abs(record['prediction'][target] - truth[target]))
        available = {i['ingredient_id'] for r in true.values()
                     if r['fold'] != reference['fold'] and r['group_id'] != reference['group_id']
                     for i in r['ingredients'] if i['grams'] > 0}
        assert all(i['ingredient_id'] is None or i['ingredient_id'] in available for i in record['items'])
        absent = math.fsum(i['grams'] for i in reference['ingredients'] if i['ingredient_id'] not in available)
        catalog_unavailable += absent
        catalog_total += result['reference_mass_g']
        result['catalog_unavailable_reference_mass_g'] = absent
        pred_mass = defaultdict(float)
        for item in record['items']:
            if item['ingredient_id'] is not None:
                pred_mass[item['ingredient_id']] += item['grams']
        major = max(reference['ingredients'], key=lambda i: i['grams'])
        present = major['ingredient_id'] in pred_mass
        main_present += present
        stats.append(result)
        if sid in fixed:
            case = fixed[sid]
            summary = {'case_alias': case['case_alias'], 'association_group_alias': case['association_group_alias'],
                       'mass_comparison': result, 'main_reference_id_predicted': present,
                       'main_reference_id_available_in_catalog': major['ingredient_id'] in available,
                       'main_reference_mass_g': major['grams'],
                       'predicted_main_reference_id_mass_g': pred_mass.get(major['ingredient_id'], 0),
                       'H_prediction': record['prediction'], 'truth': truth,
                       'signed_errors': {t: record['prediction'][t] - truth[t] for t in TARGETS}}
            case_aggregates.append(summary)
            private.append({**summary, 'sample_id': sid, 'group_id': reference['group_id'],
                            'fold': reference['fold'], 'items': record['items'],
                            'reference_ingredients': reference['ingredients']})
    case_aggregates.sort(key=lambda r: r['case_alias'])
    private.sort(key=lambda r: r['case_alias'])
    aggregate = {
        'scope': 'posthoc_development_diagnostic_not_selection_or_acceptance',
        'privacy': 'private_development_diagnostic_not_for_public_demo',
        'candidate': 'H', 'n': 84, 'groups': 78, 'api_calls': 0, 'validation_read': False,
        'definitions': {
            'known': 'Any nonnull training-catalog ID; this does not mean a correct food.',
            'presence_coverage': 'Reference grams whose exact ID occurs at positive predicted mass; quantities need not agree.',
            'overlap': 'Per-image same-ID sum(min(reference grams, predicted grams)), after merging duplicate IDs.',
            'unpaired_mass_l1': 'Reference-only mass + prediction-only known mass + unknown mass + absolute matched-ID mass residual; unknown never assumed matched.',
            'micro': 'Ratio of masses summed over all 84 images; mean-image rates are separately provided.',
        },
        'all_rows': summarize(stats),
        'catalog_reference_mass_unavailable_fraction': catalog_unavailable / catalog_total,
        'largest_reference_ingredient_present_images': main_present,
        'mae_recomputed': {t: math.fsum(values) / len(values) for t, values in target_errors.items()},
        'fixed_six_cases': case_aggregates,
        'limitations': [
            'All 84 development rows retained; six visual cases were selected using raw C errors and represent four groups.',
            'Exact-ID agreement is stricter than semantic similarity or recipe equivalence, and does not establish image-region correspondence.',
            'Chicken versus chicken breast is an observed exact-ID mismatch; do not label every such mismatch a wholly different visual food.',
            'Unknown predictions may refer to true foods, but cannot be assigned an exact match without unsupported manual remapping.',
            'Small total-mass error can conceal canceling omitted and extra food masses.',
            'No causal claim about example retrieval versus mass estimation follows from this descriptive decomposition.',
            'No current H or future candidate receives query labels, modified examples or replacement predictions.',
        ],
        'input_sha256': hashes,
    }
    for rel, expected in hashes.items():
        assert hashlib.sha256((ROOT / rel).read_bytes()).hexdigest() == expected
    save('h_mass_diagnostic.json', aggregate)
    save('h_private_case_diagnostic.json', {'scope': aggregate['scope'], 'cases': private})
    print(json.dumps({'n': 84, 'groups': 78, 'fixed_cases': len(private),
                      'source_hashes_unchanged': len(hashes), 'api_calls': 0,
                      'validation_read': False, 'mae_recomputed': aggregate['mae_recomputed']}))


if __name__ == '__main__':
    main()
