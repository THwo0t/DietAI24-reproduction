"""Pure prospective failure completion; grants no run or cohort authorization.

Stages are exact {'status': native|repaired|failed, 'value': parsed value|None}.
Retries and fitting the supplied training-fold median belong to the caller.
"""
from copy import deepcopy
import json
import re

import paired_accounting as p

PROFILES = ('O', 'Q', 'D', 'Q+D')


def _stage(stage):
    p.obj(stage, ('status', 'value'))
    p.require(type(stage['status']) is str and stage['status'] in ('native', 'repaired', 'failed'),
              'explicit_stage_status_required')
    p.require(stage['status'] != 'failed' or stage['value'] is None, 'failed_stage_value_must_be_none')
    return deepcopy(stage)


def _json(value):
    try:
        return json.dumps(value, allow_nan=False)
    except (TypeError, ValueError, OverflowError, RecursionError):
        raise p.PairContractError('valid_parsed_structure_required') from None


def _catalogue(items, foods):
    p.require(type(foods) is dict, 'catalogue_required')
    clean = {}
    for item in items:
        for code in [item['primary_code']] + item['alternative_codes']:
            p.require(code in foods and type(foods[code]) is dict, 'fixed_catalogue_codes_required')
            food = foods[code]
            p.require(isinstance(food.get('description'), str) and food['description'].strip(),
                      'fixed_catalogue_description_required')
            p.obj(food.get('density'), p.NUTRIENTS)
            clean[code] = {'description': food['description'],
                           'density': {key: p.number(food['density'][key]) for key in p.NUTRIENTS}}
    return clean


def compose_profiles(items, foods, original_stage, quantity_stage, density_stage,
                     fallback, fallback_binding_sha256, identity_status='native'):
    """Complete all four five-vectors, with deterministic dependency failures.

    Failed identity requires items=None and foods=None; successful identity is a
    shared fixed snapshot. Catalogue metadata outside description/density is
    projected away. Successful parsed stages are validated even if a different
    failed dependency will prevent their profile from being used. Failed identity
    requires every downstream stage failed (there is no identity to validate).
    The binding is an opaque SHA256 of caller-owned training-fold provenance;
    this function validates its form, not the truth of the caller's fold claim.
    """
    p.require(type(identity_status) is str and identity_status in ('native', 'repaired', 'failed'),
              'explicit_identity_status_required')
    stages = {name: _stage(stage) for name, stage in (
        ('original', original_stage), ('quantity', quantity_stage), ('density', density_stage))}
    p.obj(fallback, p.TARGETS)
    median = {key: p.number(fallback[key], positive=key == 'weight') for key in p.TARGETS}
    p.require(type(fallback_binding_sha256) is str and re.fullmatch(r'[0-9a-f]{64}', fallback_binding_sha256),
              'training_fold_binding_sha256_required')
    masses, qmass, dcodes = None, None, None
    hashes = {'fixed_items_sha256': None, 'catalogue_sha256': None,
              'original_sha256': None, 'quantity_sha256': None, 'density_sha256': None,
              'fallback_sha256': p.fingerprint(median),
              'fallback_binding_sha256': fallback_binding_sha256}
    if identity_status == 'failed':
        p.require(items is None and foods is None and all(s['status'] == 'failed' for s in stages.values()),
                  'failed_identity_requires_absent_snapshot_and_failed_stages')
    else:
        items = p.checked_items(items)
        foods = _catalogue(items, foods)
        hashes.update(fixed_items_sha256=p.fingerprint(items), catalogue_sha256=p.fingerprint(foods))
        if stages['original']['status'] != 'failed':
            value = stages['original']['value']
            rows = p.rows_by_id(value, items, ('item_id', 'grams'))
            masses = {key: p.number(row['grams'], positive=True) for key, row in rows.items()}
            hashes['original_sha256'] = p.fingerprint(value)
        if stages['quantity']['status'] != 'failed':
            value = stages['quantity']['value']
            p.obj(value, ('total_grams', 'items'))
            rows = p.rows_by_id(value['items'], items, ('item_id', 'ratio', 'share', 'grams'))
            for row in rows.values():
                for key in ('ratio', 'share', 'grams'):
                    p.number(row[key], positive=True)
            raw = {'total_grams': value['total_grams'], 'items': [
                {'item_id': row['item_id'], 'ratio': row['ratio']} for row in value['items']]}
            checked = p.parse_quantity(_json(raw), items)
            p.require(checked == value, 'quantity_result_changed')
            qmass = {row['item_id']: row['grams'] for row in checked['items']}
            hashes['quantity_sha256'] = p.fingerprint(checked)
        if stages['density']['status'] != 'failed':
            value = stages['density']['value']
            checked = p.parse_density(_json(value), items)
            p.require(checked == value, 'density_result_changed')
            dcodes = {row['item_id']: row['density_code'] for row in checked['items']}
            hashes['density_sha256'] = p.fingerprint(checked)
    dependencies = {'O': ('original',), 'Q': ('quantity',),
                    'D': ('original', 'density'), 'Q+D': ('quantity', 'density')}
    profiles = {}
    for name in PROFILES:
        deps = dependencies[name]
        # Identity dominates; otherwise preserve every failed dependency in fixed
        # dependency order, so cross-failures have a stable and specific reason.
        failed = (['identity'] if identity_status == 'failed' else
                  [dep for dep in deps if stages[dep]['status'] == 'failed'])
        used_statuses = [identity_status] + [stages[dep]['status'] for dep in deps]
        state = 'fallback' if failed else ('repaired' if 'repaired' in used_statuses else 'native')
        if failed:
            computed = {'prediction': deepcopy(median), 'leaves': []}
        else:
            computed = p.aggregate(items, foods, masses if name in ('O', 'D') else qmass,
                                   dcodes if name in ('D', 'Q+D') else None)
        provenance = {'identity_status': identity_status,
                      'stage_statuses': {dep: stages[dep]['status'] for dep in deps}, **hashes}
        profiles[name] = {**computed, 'status': state, 'native': state == 'native',
                          'repaired': state == 'repaired', 'fallback': bool(failed),
                          'fallback_reason': '+'.join(failed) + '_failed' if failed else None,
                          'original_status': stages['original']['status'],
                          'provenance': provenance,
                          'prediction_sha256': p.fingerprint(computed['prediction']),
                          'leaves_sha256': p.fingerprint(computed['leaves']),
                          'provenance_sha256': p.fingerprint(provenance)}
    checks = {}
    for left, right in (('O', 'D'), ('Q', 'Q+D')):
        a, b = profiles[left], profiles[right]
        if a['fallback'] or b['fallback']:
            checks[left + ':' + right] = 'unavailable_due_to_fallback'
        else:
            p.require(a['prediction']['weight'] == b['prediction']['weight'] and
                      [r['grams'] for r in a['leaves']] == [r['grams'] for r in b['leaves']],
                      'paired_mass_manipulation_changed')
            checks[left + ':' + right] = 'passed'
    return {'profiles': profiles, 'weight_manipulation': checks,
            'stage_statuses': {'identity': identity_status, **{k: v['status'] for k, v in stages.items()}},
            'repair_count': int(identity_status == 'repaired') +
                            sum(s['status'] == 'repaired' for s in stages.values()),
            'fallback_count': sum(row['fallback'] for row in profiles.values())}
