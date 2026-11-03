"""Atomic O records; preserve main/E2E separately from the allowed ASA task."""
from copy import deepcopy

from opt_pipeline import TARGETS, _number
from opt_metrics import median_option, option_prediction
from opt_provider import fingerprint


def vector(value):
    if not isinstance(value,dict) or set(value) != set(TARGETS):
        raise ValueError('O_complete_five_vector_required')
    return {k:_number(value[k]) for k in TARGETS}


def coding_snapshot(identity):
    codes = list(identity.get('final_codes',[]))
    if (identity.get('status') != 'ok' and codes or len(codes) != len(set(codes))
            or not set(codes) <= set(identity.get('retrieved_codes',[]))):
        raise ValueError('O_coding_not_fixed_legal_candidates')
    return {'codes':codes,'primary_code':codes[0] if codes else None,
            'identity_sha256':fingerprint(identity)}


def main_record(row, identity, portion, fallback, pipeline, coding):
    if coding_snapshot(identity) != coding:
        raise ValueError('O_identity_changed_after_coding')
    valid = portion.get('status') == 'ok'
    if valid:
        checked = pipeline.aggregate_quantities(identity,row['dataset'],portion['portions'])
        if any(checked[k] != portion[k] for k in ('prediction','raw_prediction','raw_leaves','portions')):
            raise ValueError('O_physical_mass_or_density_join_changed')
    elif portion.get('prediction') is not None or portion.get('raw_leaves'):
        raise ValueError('O_failed_quantity_contains_partial_success')
    prediction = vector(portion['prediction'] if valid else fallback)
    repaired = bool(identity.get('repaired') or portion.get('repaired'))
    return {**{k:row[k] for k in ('sample_id','dataset','group_id','fold')},
        'coding':deepcopy(coding),'final_codes':list(coding['codes']),
        'primary_code':coding['primary_code'],'retrieved_codes':deepcopy(identity.get('retrieved_codes',[])),
        'items':deepcopy(identity.get('items',[])),'identity_status':identity.get('status'),
        'portion_status':portion.get('status'),'raw_prediction':deepcopy(prediction) if valid else None,
        'prediction':prediction,'raw_leaves':deepcopy(portion.get('raw_leaves',[])) if valid else [],
        'portion_result':deepcopy(portion),'fallback':not valid,
        'fallback_reason':portion.get('failure') if not valid else None,
        'native_complete':valid and not repaired,'main_repair_used':repaired,
        'conditional_repair_used':False,'repair_used':repaired,
        'e2e':{'prediction':deepcopy(prediction),'fallback':not valid},'conditional':None}


def attach_conditional(record, result, context, catalog):
    if (record['dataset'] != 'asa24' or set(context) != {'code','options'}
            or context['code'] not in record['final_codes']):
        raise ValueError('O_Exact_ASA_context_required')
    code,options = context['code'],context['options']
    if options != catalog['asa_options'][code]:
        raise ValueError('O_complete_conditional_catalogue_required')
    density = catalog['foods'][code]['density']
    valid = result.get('status') == 'ok'
    if valid:
        option = next((o for o in options if o['option_id']==result.get('option_id')),None)
        if (option is None or result.get('code') != code
                or result.get('prediction') != option_prediction(option,density)):
            raise ValueError('O_conditional_option_prediction_changed')
        grams = _number(result.get('continuous_grams'))
    else:
        option = median_option(options); grams = None
    out = deepcopy(record)
    out['conditional'] = {'code':code,'options':deepcopy(options),'option_id':option['option_id'],
        'continuous_grams':grams,'prediction':option_prediction(option,density),'fallback':not valid,
        'native_complete':valid and not result.get('repaired',False),
        'fallback_reason':result.get('failure') if not valid else None,'raw_result':deepcopy(result)}
    out['conditional_repair_used'] = bool(result.get('repaired'))
    # Main fields, E2E vector and its success provenance remain unchanged.
    return out
