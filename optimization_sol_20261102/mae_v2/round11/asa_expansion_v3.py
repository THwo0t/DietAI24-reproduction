"""Pure deterministic ASA development/replacement proposal, never a designation.

Caller authenticates identity/eligibility/scope projections. No I/O or protected
label parsing occurs. Existing rows/folds are copied unchanged; new group/fold
bindings are prospective and require a later full preparation review.
"""
from collections import defaultdict
from copy import deepcopy
from decimal import Decimal
import hashlib
import json
import re

from asa_eligibility import number, integer
from asa_phase_graph import _bindings
from asa_identity import require, sha_value, image_name
from cohort_lineage_v3 import SEED
from qualification import code8, new_group_order

LEGAL_FIELDS = {'FoodCode','Image','Portion','PortionCode','Multiplier','PortionWeight','Weight'}


def _legal(legal, image_hashes, mapping):
    require(isinstance(legal, dict) and set(legal) == {'rows','ambiguous_code_images'},
            'legal_rows_projection_required')
    result=[];seen=set()
    for row in legal['rows']:
        require(isinstance(row,dict) and set(row)==LEGAL_FIELDS,'exact_legal_portion_fields_required')
        code=code8(row['FoodCode']);image=image_name(row['Image'])
        require(row['FoodCode']==code and isinstance(row['Portion'],str) and row['Portion'].strip(),
                'exact_legal_portion_identity_required')
        require(integer(row['PortionCode'])==row['PortionCode'], 'legal_portion_code_required')
        multiplier,unit,grams=(number(row[k]) for k in ('Multiplier','PortionWeight','Weight'))
        require(multiplier>0 and unit>0 and grams>0 and multiplier*unit==grams,
                'positive_exact_legal_weight_required')
        digest=sha_value(image_hashes[image]); group=mapping['c:'+code]
        require(mapping['i:'+image]==group,'legal_source_component_binding_required')
        require((code,image) not in legal['ambiguous_code_images'],'ambiguous_legal_source_photo')
        canonical={**row,'Multiplier':multiplier,'PortionWeight':unit,'Weight':grams}
        signature=json.dumps({k:str(v) for k,v in canonical.items()},sort_keys=True,separators=(',',':'))
        if signature in seen: continue
        seen.add(signature)
        result.append((canonical,digest,group,hashlib.sha256(signature.encode()).hexdigest()))
    return sorted(result,key=lambda item:(item[0]['FoodCode'],item[0]['Image'],item[3]))


def _build(core_rows, validation_rows, original_bindings, legal, graph, scope,
           image_hashes, top_codes, *, counts, broader_count):
    bindings=_bindings({'originalmanifestbinding':original_bindings,
        'currentmanifestbinding':{'core':core_rows,'validation':validation_rows}}, counts)
    mapping=graph['node_groups'];top={code8(c) for c in top_codes}
    core_codes={r['sample_id'].split('-',2)[1] for r in core_rows}
    core_groups={mapping['c:'+c] for c in core_codes}
    val_groups={mapping['c:'+r['sample_id'].split('-',2)[1]] for r in validation_rows}
    missing=set(scope['missing_source_quarantine_components_private'])
    permitted=set(scope['asa_permitted_components_private'])
    blocked=set(scope['asa_blocked_components_private'])
    require(not permitted & blocked and not permitted & (core_groups|val_groups|missing),
            'independent_safe_scope_required')
    safe_codes={code8(c) for c in scope['asa_permitted_codes_private']}
    require(all(mapping['c:'+c] in permitted for c in safe_codes), 'safe_code_scope_binding_required')
    rows=_legal(legal,image_hashes,mapping)
    old_pairs={(r['sample_id'].split('-',2)[1],r['image_sha256']) for r in core_rows}
    extras=[];eligible=defaultdict(list)
    def record(item,stratum):
        row,digest,group,fingerprint=item
        return {'sample_id':'asa-v3-'+fingerprint,'dataset':'asa24','split':'dev_proposal',
            'stratum':stratum,'source_row_sha256':fingerprint,'FoodCode':row['FoodCode'],
            'Image':row['Image'],'image_sha256':digest,'association_group_id':group,
            'portion_source_private':deepcopy(row),'fold':None}
    for item in rows:
        row,digest,group,_=item;code=row['FoodCode']
        # Core exposure is intentional; all old validation and unknown source
        # components remain unavailable to additions, even where core joins one.
        if code in core_codes and group not in missing|val_groups and (code,digest) not in old_pairs:
            extras.append(record(item,'asa_core_all_legal_extra'))
        if code in safe_codes and group in permitted:
            eligible[group].append(item)
    order=new_group_order(eligible,seed=SEED,count=len(eligible))
    chosen=order[:broader_count]
    broad=[record(item,'asa_broader_frame') for g in chosen for item in eligible[g]]
    # Entire old validation remains blocked from new development. Linked old
    # records are proposed replacements only; the original set stays immutable.
    protected=core_groups | set().union(*(set(graph.get('protected_groups',{}).get(role,()))
        for role in ('history','training','retired')))
    protected |= set(scope.get('asa_potential_training_components_private',()))
    linked=[deepcopy(r) for r in validation_rows
            if mapping['c:'+r['sample_id'].split('-',2)[1]] in protected]
    retained=[deepcopy(r) for r in validation_rows if r not in linked]
    if 'ASA_pending_repair_private' in scope:
        pending=scope['ASA_pending_repair_private']
        require(set(pending['affected_old_validation_sample_ids'])=={r['sample_id'] for r in linked}
                and set(pending['retained_unlinked_old_validation_sample_ids'])==
                    {r['sample_id'] for r in retained}
                and pending['new_acceptance_designated'] is False,
                'scope_pending_validation_repair_binding_changed')
    replacement=[];replacement_group=None;replacement_code=None
    candidates=[]
    for g in order[broader_count:]:
        codes={item[0]['FoodCode'] for item in eligible[g] if item[0]['FoodCode'] in top}
        if codes:candidates.append((g,codes))
    if candidates:
        replacement_group,codes=candidates[0]
        replacement_code=new_group_order(codes,seed=SEED+'|code',count=1)[0]
        source=[item for item in eligible[replacement_group] if item[0]['FoodCode']==replacement_code]
        weights=sorted({item[0]['Weight'] for item in source},reverse=True)
        # Fixed first component/code, no reroll if a supplied legal projection
        # unexpectedly cannot support the preregistered triplet.
        if len(weights)>=3:
            for size,weight in zip(('largest','medium','smallest'),
                                   (weights[0],weights[len(weights)//2],weights[-1])):
                item=min((x for x in source if x[0]['Weight']==weight),key=lambda x:x[0]['Image'])
                entry=record(item,'asa_validation_replacement_proposal')
                entry.update(split='validation_proposal',size=size)
                replacement.append(entry)
    expected_rows=counts['validation'][0];expected_groups=counts['validation'][1]
    resulting_groups={mapping['c:'+r['sample_id'].split('-',2)[1]] for r in retained}
    if replacement:resulting_groups.add(replacement_group)
    reasons=[]
    if len(chosen)<broader_count:reasons.append('broader_component_shortfall')
    if len(linked)!=3 or len({mapping['c:'+r['sample_id'].split('-',2)[1]] for r in linked})!=1:
        reasons.append('linked_validation_disposition_population_differs')
    if len(retained)+len(replacement)!=expected_rows:reasons.append('validation_record_shortfall_or_population_mismatch')
    if len(resulting_groups)!=expected_groups:reasons.append('validation_group_population_mismatch')
    require(not ({r['association_group_id'] for r in broad+extras}&val_groups),
            'old_validation_component_in_development_additions')
    return {'original_core_private':deepcopy(core_rows),
        'original_validation_legacy_reserved_private':deepcopy(validation_rows),
        'core_extra_proposals_private':extras,'broader_development_proposals_private':broad,
        'broader_component_order_private':order,'chosen_broader_components_private':chosen,
        'validation_proposal_private':{'retained_old_rows':retained,'linked_old_rows_to_replace':linked,
            'new_triplet_rows':replacement,'replacement_component':replacement_group,
            'replacement_code':replacement_code,'resulting_rows':len(retained)+len(replacement),
            'resulting_association_groups':len(resulting_groups)},
        'prospective_development_group_bindings_private':{
            r['sample_id']:mapping['c:'+r['sample_id'].split('-',2)[1]] for r in core_rows}
            | {r['sample_id']:r['association_group_id'] for r in extras+broad},
        'seed':SEED,'shortfall_reasons':reasons,'pending_boundary_confirmation':True,
        'original_global_guard_remains_stopped':True,'old_folds_overwritten':False,
        'prospective_grouped_folds_required':True,'actual_api_exposure_complete':False,
        'source_association_complete':False,'candidate_eligibility_evaluated':False,
        'grants_sampling_download_or_inference':False,'new_samples_selected':0,
        'new_downloads':0,'api_calls':0}


def build_asa_expansion(core_rows,validation_rows,original_bindings,legal,graph,scope,
                        image_hashes,top_codes):
    """Pure PRIVATE proposal; Decimal portion grams remain caller-serialized.

    Graph is the held V3 ASA phase graph. Scope is source_scope_v3.disposition's
    authenticated projection; optional potential-training components may enlarge
    the linked-validation proposal only. Never accepts labels or model outcomes.
    """
    return _build(core_rows,validation_rows,original_bindings,legal,graph,scope,
        image_hashes,top_codes,counts={'core':(99,23),'validation':(78,23)},broader_count=20)
