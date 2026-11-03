"""Label-free complete-population N record assembly with physical mass checks."""
from copy import deepcopy
from opt_provider import fingerprint
from opt_pipeline import ContractError, TARGETS
from pipeline_v2 import _positive
from records_m import vector
from uncertain_portions import aggregate


def coding_snapshot(identity):
    if identity['status'] != 'ok':
        expected = {'ordered_codes':[], 'final_codes':[], 'primary_code':None}
    else:
        areas = {p['parent_id']: (p['bbox'][2]-p['bbox'][0])*(p['bbox'][3]-p['bbox'][1])
                 for p in identity['parents']}
        leaves = sorted(identity['leaves'], key=lambda l:(-areas[l['parent_id']],l['parent_id'],l['component_id']))
        codes = list(dict.fromkeys(leaf['codes'][rank] for rank in range(3) for leaf in leaves
                                   if len(leaf['codes']) > rank))
        expected = {'ordered_codes':codes, 'final_codes':codes[:3], 'primary_code':codes[0] if codes else None}
    if identity['coding'] != expected: raise ValueError('N_coding_changed')
    return deepcopy(expected)


def validate_leaves(identity, portion):
    leaves = portion['raw_leaves']
    expected = {leaf['component_id']:leaf for leaf in identity['leaves']}
    if (identity['status'] != 'ok' or len(expected) != len(identity['leaves']) or len(leaves) != len(expected)
            or {p['component_id'] for p in leaves} != set(expected)):
        raise ValueError('N_incomplete_or_duplicate_mass_join')
    masses = {leaf['component_id']:_positive(leaf['grams']) for leaf in leaves}
    recomputed = aggregate(identity, masses, [])
    if recomputed['raw_leaves'] != leaves or recomputed['prediction'] != portion['prediction']:
        raise ValueError('N_mass_density_join_or_total_changed')
    return leaves


def core_record(row, identity, portion, fallback, coding):
    if coding_snapshot(identity) != coding: raise ValueError('N_pre_quantity_coding_changed')
    valid = portion.get('status') == 'ok'
    leaves = deepcopy(validate_leaves(identity,portion)) if valid else []
    if not valid and (portion.get('prediction') is not None or portion.get('raw_leaves')):
        raise ValueError('N_failed_quantity_contains_partial_success')
    prediction = vector(portion['prediction'] if valid else fallback)
    codes = coding['final_codes'] if row['dataset'] == 'asa24' else coding['ordered_codes']
    retrieved = deepcopy(identity.get('retrieved_codes',[]))
    if not set(codes) <= set(retrieved): raise ValueError('N_code_outside_candidates')
    imported_quantity_repaired = bool(portion.get('imported_quantity_repaired'))
    upstream_identity_repaired = bool(identity.get('upstream_identity_repaired'))
    inherited = imported_quantity_repaired or upstream_identity_repaired
    new_repair = bool(identity.get('repaired') or portion.get('repaired'))
    return {**{k:row[k] for k in ('sample_id','dataset','group_id','fold')},
        'identity_sha256':fingerprint(identity), 'coding':deepcopy(coding), 'final_codes':list(codes),
        'primary_code':codes[0] if codes else None, 'retrieved_codes':retrieved,
        'parents':deepcopy(identity.get('parents',[])), 'items':deepcopy(identity.get('leaves',[])),
        'identity_status':identity['status'], 'portion_status':portion['status'],
        'raw_prediction':deepcopy(prediction) if valid else None, 'prediction':prediction, 'raw_leaves':leaves,
        'fallback':not valid, 'fallback_reason':portion.get('failure') if not valid else None,
        'native_complete':valid and not (new_repair or inherited), 'repair_used':new_repair or inherited,
        'new_repair_used':new_repair, 'imported_quantity_repaired':imported_quantity_repaired,
        'upstream_identity_repaired':upstream_identity_repaired,
        'conditional':None, 'e2e':{'prediction':deepcopy(prediction),'fallback':not valid}}
