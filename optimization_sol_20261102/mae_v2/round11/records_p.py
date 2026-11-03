"""Pure P records: revalidate actual stage envelopes, then compose four profiles.

Hashes are bindings, never evidence authentication. The runner must verify the
coding seal, request references and training-fold provenance before calling.
No labels, files, providers, fitting or old prediction imports are used here.
"""
from copy import deepcopy
import json
import re

from opt_provider import fingerprint
from opt_pipeline import ContractError,validate_options
from opt_metrics import nearest_option,median_option,option_prediction
from source_portions import SourcePortionPipeline, CONFIG
from paired_stage_pipeline import PairedStagePipeline,VERSION,IMAGE_MODE
from paired_failure import compose_profiles
import paired_accounting as p
from service_p import ROW_FIELDS,slot_id,allowed_slots
from engine_p import STAGES


def require(ok,code):p.require(ok,'P_record_'+code)
def _hash(v):return type(v) is str and re.fullmatch('[0-9a-f]{64}',v) is not None

def _finite(value):
    try:json.dumps(value,allow_nan=False)
    except (ValueError,TypeError,OverflowError,RecursionError):raise p.PairContractError('P_record_finite_json_required') from None


def _envelope(row,envelope,allowed):
    p.obj(envelope,('result','request_refs'));_finite(envelope)
    refs=envelope['request_refs']
    require(type(refs) is dict and set(refs)==set(STAGES),'reference_groups_changed')
    for stage,group in refs.items():
        require(type(group) is list and (stage in allowed or not group),'reference_stage_changed')
        require(len(group)<=(40 if stage=='retrieval' else 2),'reference_count_changed')
        for i,ref in enumerate(group):
            p.obj(ref,('slot','payload_hash','value_hash','reservation_id','cache_present_before','origin'))
            expected=slot_id(row['sample_id'],f'embed_{i:02d}',0) if stage=='retrieval' else slot_id(row['sample_id'],stage,i)
            require(ref['slot']==expected and ref['origin']=='new_P' and
                    all(_hash(ref[k]) for k in ('slot','payload_hash','value_hash')) and
                    type(ref['reservation_id']) is str and re.fullmatch('[0-9a-f]{32}',ref['reservation_id']) and
                    type(ref['cache_present_before']) is bool,'reference_binding_changed')
    return envelope['result']


def _parsed(stage,parser,refs):
    require(type(stage) is dict and set(stage) in ({'stage','attempts'},{'stage','attempts','parsed'}),
            'stage_log_schema_changed')
    attempts=stage['attempts'];require(type(attempts) is list and 1<=len(attempts)<=2 and len(refs)==len(attempts),
                                      'one_repair_contract_changed')
    parsed=None
    for i,entry in enumerate(attempts):
        require(type(entry) is dict and type(entry.get('valid')) is bool and
                type(entry.get('raw')) is str and ref_hash(refs[i],entry['raw']),'attempt_reference_changed')
        try:value=parser(entry['raw'])
        except (ContractError,p.PairContractError) as exc:
            require(set(entry)=={'raw','valid','error'} and entry['valid'] is False and entry['error']==str(exc),
                    'declared_parser_failure_changed')
        else:
            require(set(entry)=={'raw','valid'} and entry['valid'] is True and i==len(attempts)-1,
                    'declared_parser_success_changed')
            parsed=value
    if parsed is None:
        require(len(attempts)==2 and 'parsed' not in stage,'exhausted_failure_required')
    else:require(stage.get('parsed')==parsed,'parsed_stage_changed')
    return parsed,('failed' if parsed is None else 'repaired' if len(attempts)==2 else 'native')


def ref_hash(ref,raw):return ref['value_hash']==fingerprint(raw)


def _identity(row,envelope,pipeline):
    result=_envelope(row,envelope,{'identify','retrieval','select'})
    require(type(result) is dict and result.get('status') in ('ok','failed') and
            type(result.get('repaired')) is bool,'identity_status_changed')
    stages=result.get('stages');require(type(stages) is list and stages and stages[0].get('stage')=='identify',
                                      'identity_stage_sequence_changed')
    refs=envelope['request_refs']
    identified,istatus=_parsed(stages[0],lambda raw:pipeline._identity_items(raw,row['dataset']),refs['identify'])
    status=istatus
    if identified is None:
        require(len(stages)==1 and not refs['retrieval'] and not refs['select'],'failed_identity_downstream_stage')
    else:
        require(len(stages)==3 and stages[1].get('stage')=='retrieval' and stages[2].get('stage')=='select',
                'identity_retrieval_selection_required')
        banks=result.get('candidates')
        require(type(banks) is dict and stages[1].get('codes_by_item')==banks and
                len(refs['retrieval'])==len(identified)*2,'identity_retrieval_join_changed')
        queries=[q for item in identified for q in (item['description'],item['broad_query'])]
        require(stages[1].get('queries')==queries and stages[1].get('attempts')==[],'retrieval_queries_changed')
        selected,sstatus=_parsed(stages[2],lambda raw:pipeline._selection(raw,identified,banks,row['dataset']),refs['select'])
        if selected is None:status='failed'
        else:
            require(selected==result.get('items'),'identity_selection_join_changed')
            status='repaired' if 'repaired' in (istatus,sstatus) else 'native'
        retrieved=list(dict.fromkeys(code for bank in banks.values() for code in bank))
        require(result.get('retrieved_codes')==retrieved,'retrieved_code_order_changed')
    if status=='failed':
        require(result['status']=='failed' and result.get('items')==[] and result.get('final_codes')==[] and
                result.get('selected_codes')==[] and isinstance(result.get('failure'),str),'failed_identity_contains_success')
        return result,None,status
    require(result['status']=='ok' and not result.get('failure') and
            result['repaired']==(status=='repaired'),'identity_success_status_changed')
    items=p.checked_items(pipeline.checked_items(result,row['dataset']))
    require(result.get('selected_codes')==result['final_codes'],'selected_final_codes_changed')
    return result,items,status


def _whole(row,envelope,identity,pipeline):
    result=_envelope(row,envelope,{'whole'})
    require(type(result) is dict and result.get('status') in ('ok','failed'),'whole_status_changed')
    stages=result.get('stages');require(type(stages) is list and len(stages)==1 and
            stages[0].get('stage')=='source_standard_first','whole_stage_changed')
    context=pipeline.portion_context(identity,row['dataset'])
    parsed,status=_parsed(stages[0],lambda raw:pipeline.parse_quantities(raw,identity,row['dataset'],context),
                          envelope['request_refs']['whole'])
    require(result.get('repaired')==(status=='repaired'),'whole_repair_status_changed')
    if parsed is None:
        require(result.get('status')=='failed' and result.get('prediction') is None and result.get('raw_prediction') is None and
                result.get('raw_leaves')==[] and result.get('portions')==[] and result.get('failure')=='O_quantity_contract',
                'failed_whole_contains_success')
        return {'status':'failed','value':None}
    require(all(result.get(k)==v for k,v in parsed.items()),'physical_mass_or_density_join_changed')
    # The physical grams are copied from validated O leaves, never recalculated
    # using a D-selected code's standard option or density.
    return {'status':status,'value':[{'item_id':leaf['item_id'],'grams':leaf['grams']} for leaf in parsed['raw_leaves']]}


def _intervention(row,envelope,identity,pipeline,kind):
    result=_envelope(row,envelope,{kind})
    require(type(result) is dict and result.get('status') in ('native','repaired','failed'),'intervention_status_changed')
    fixed=pipeline._fixed(identity,row['dataset']);prompt=getattr(p,kind+'_prompt')(fixed['items'],fixed['foods'])
    require(result.get('source_binding')==fixed and result.get('fixed_source_sha256')==p.fingerprint(fixed) and
            result.get('prompt')==prompt and result.get('prompt_sha256')==p.fingerprint(prompt) and
            result.get('method_version')==VERSION and result.get('dataset')==row['dataset'] and
            result.get('image_mode')==IMAGE_MODE,'intervention_fixed_source_changed')
    stages=result.get('stages');require(type(stages) is list and len(stages)==1 and
            stages[0].get('stage')=='paired_'+kind,'intervention_stage_changed')
    # Match the production parser's prefixed ContractError exactly.
    def parser(raw):
        try:return getattr(p,'parse_'+kind)(raw,fixed['items'])
        except p.PairContractError as exc:raise ContractError('paired_'+str(exc)) from None
    parsed,status=_parsed(stages[0],parser,envelope['request_refs'][kind])
    require(result.get('status')==status and result.get('value')==parsed and
            result.get('repaired')==(status=='repaired') and
            result.get('parsed_sha256')==(None if parsed is None else p.fingerprint(parsed)) and
            result.get('failure')==('paired_'+kind+'_contract' if parsed is None else None),
            'intervention_parsed_status_changed')
    return {'status':status,'value':parsed}


def compose_record(row,identity_envelope,whole_envelope,quantity_envelope,density_envelope,catalog,fallback,*,evidence_binding):
    require(type(row) is dict and set(row)==ROW_FIELDS and row['dataset'] in ('asa24','nutrition5k') and
            row['split']=='dev' and type(row['fold']) is int and row['fold'] in range(5),'blind_row_changed')
    allowed_slots([row],image_hashes={row['sample_id']:'0'*64})
    p.obj(evidence_binding,('row_sha256','identity_seal_sha256','request_proof_sha256','fallback_binding_sha256'))
    require(all(_hash(h) for h in evidence_binding.values()) and evidence_binding['row_sha256']==fingerprint(row),
            'caller_binding_changed')
    _finite((row,catalog,fallback,evidence_binding))
    pipeline=PairedStagePipeline(None,None,catalog,None)
    identity,items,istatus=_identity(row,identity_envelope,pipeline)
    if istatus=='failed':
        require(whole_envelope is None and quantity_envelope is None and density_envelope is None,
                'failed_identity_requires_skipped_downstream')
        original=quantity=density={'status':'failed','value':None};foods=None
    else:
        original=_whole(row,whole_envelope,identity,pipeline)
        quantity=_intervention(row,quantity_envelope,identity,pipeline,'quantity')
        density=_intervention(row,density_envelope,identity,pipeline,'density');foods=catalog['foods']
    composed=compose_profiles(items,foods,original,quantity,density,fallback,
                              evidence_binding['fallback_binding_sha256'],identity_status=istatus)
    codes=deepcopy(identity['final_codes']);primary=codes[0] if codes else None
    density_primary=(density['value']['items'][0]['density_code'] if density['status']!='failed' else None)
    snapshot={'items':deepcopy(items or []),'candidates':deepcopy(identity.get('candidates',{})),
              'final_codes':codes,'retrieved_codes':deepcopy(identity.get('retrieved_codes',[])),
              'identity_sha256':fingerprint(identity)}
    for profile,value in composed['profiles'].items():
        value.update(profile=profile,final_codes=deepcopy(codes),primary_code=primary,
            density_primary_code=density_primary if profile in ('D','Q+D') else primary,
            match={'final_code_set':sorted(codes),'original_primary_code':primary,
                   'reported_primary_code':density_primary if profile in ('D','Q+D') else primary},
            raw_prediction=None if value['fallback'] else deepcopy(value['prediction']),
            e2e={'prediction':deepcopy(value['prediction']),'status':value['status'],
                 'fallback':value['fallback'],'fallback_reason':value['fallback_reason']},
            conditional=None)
    envelopes={'identity':identity_envelope,'whole':whole_envelope,'quantity':quantity_envelope,'density':density_envelope}
    return {'schema_version':1,'namespace':'paired-portions-r11-p.1','row':deepcopy(row),
        'coding':snapshot,'coding_sha256':fingerprint(snapshot),'evidence_binding':deepcopy(evidence_binding),
        'evidence_authentication':'caller_responsibility_not_authenticated_here',
        'stage_envelopes':deepcopy(envelopes),'stage_envelopes_sha256':fingerprint(envelopes),
        **composed,'conditional':None}


def attach_conditional(record,envelope,context,catalog,*,adapter_binding):
    """Attach ONE shared private code/full-catalogue result after coding seal.

    The caller authenticates the full coding seal and adapter projection. This
    function checks binding consistency and legal mapping, never their truth.
    """
    row=record['row'];require(row['dataset']=='asa24' and record['conditional'] is None,'conditional_role_changed')
    p.obj(adapter_binding,('identity_seal_sha256','context_sha256','request_proof_sha256'))
    require(all(_hash(h) for h in adapter_binding.values()) and
            adapter_binding['identity_seal_sha256']==record['evidence_binding']['identity_seal_sha256'] and
            adapter_binding['context_sha256']==fingerprint(context),'conditional_caller_binding_changed')
    p.obj(context,('code','options'));code=context['code']
    require(code in record['coding']['final_codes'] and context['options']==catalog['asa_options'][code],
            'complete_Exact_code_catalogue_required')
    options=validate_options(context['options']);density=catalog['foods'][code]['density']
    result=_envelope(row,envelope,{'conditional'})
    require(type(result) is dict and result.get('code')==code and result.get('options')==options and
            result.get('protocol')=='conditional_option','conditional_context_join_changed')
    stages=result.get('stages');require(type(stages) is list and len(stages)==1 and
            stages[0].get('stage')=='portion_conditional_option_continuous_option','conditional_stage_changed')
    def parser(raw):
        from opt_pipeline import _object,_json,_number,nearest_option as choose
        data=_object(_json(raw),{'grams'});grams=_number(data['grams'])
        return {**choose(options,grams),'continuous_grams':grams,'item_id':'i1','code':code}
    parsed,status=_parsed(stages[0],parser,envelope['request_refs']['conditional'])
    if parsed is None:
        require(result.get('status')=='failed' and result.get('prediction') is None and result.get('portions')==[] and
                result.get('failure')=='portion_contract','conditional_failed_contains_success')
        option=median_option(options);grams=None
    else:
        grams=parsed['continuous_grams'];option=nearest_option(grams,options)
        expected={**parsed,'item_id':'i1','code':code}
        require(result.get('status')=='ok' and not result.get('failure') and result.get('portions')==[expected] and
                result.get('continuous_grams')==grams and result.get('option_id')==option['option_id'] and
                result.get('prediction')==option_prediction(option,density),'conditional_prediction_join_changed')
    require(result.get('repaired')==(status=='repaired'),'conditional_repair_status_changed')
    shared={'code':code,'options':deepcopy(options),'option_id':option['option_id'],'continuous_grams':grams,
        'raw_option':option_prediction(option,density),'prediction':option_prediction(option,density),
        'status':'fallback' if status=='failed' else status,'fallback':status=='failed',
        'fallback_reason':'conditional_contract_failed' if status=='failed' else None,
        'adapter_binding':deepcopy(adapter_binding),'context_sha256':fingerprint(context),
        'stage_envelope':deepcopy(envelope),'stage_envelope_sha256':fingerprint(envelope),
        'evidence_authentication':'caller_responsibility_not_authenticated_here'}
    out=deepcopy(record);out['conditional']=shared
    for value in out['profiles'].values():value['conditional']=deepcopy(shared)
    return out
