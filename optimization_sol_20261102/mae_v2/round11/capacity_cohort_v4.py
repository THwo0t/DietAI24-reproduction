"""Pure capacity-amended identity bindings; no I/O, targets or action grants."""
from collections import defaultdict
from copy import deepcopy
import hashlib
import re

from cohort_lineage_v3 import SEED as BASE_SEED
from development_identity import FIELDS
from training_identity import FIELDS as TRAIN_FIELDS
from qualification import new_group_order
from source_census import require

SEED=BASE_SEED+'|capacity-v4'
DISH=re.compile(r'dish_[0-9]{10}\Z')
HEX=re.compile(r'[0-9a-f]{64}\Z')


def _dish(row,split):
    require(isinstance(row,dict) and set(row)==FIELDS,'identity_only_capacity_row_required')
    sample=row['sample_id']
    require(isinstance(sample,str) and sample.startswith('nutrition5k-')
            and DISH.fullmatch(sample.removeprefix('nutrition5k-'))
            and row['dataset']=='nutrition5k' and row['split']==split
            and isinstance(row['group_id'],str) and row['group_id']
            and isinstance(row['image_path'],str) and row['image_path']
            and HEX.fullmatch(row['image_sha256'])
            and (type(row['fold']) is int and row['fold'] in range(5)
                 if split=='dev' else row['fold'] is None),'capacity_original_identity_binding_required')
    return sample.removeprefix('nutrition5k-')


def _flags():
    return {'pending_boundary_confirmation':True,'original_global_guard_remains_stopped':True,
        'new_acceptance_designated':False,'actual_api_exposure_complete':False,
        'candidate_eligibility_evaluated':False,'grants_sampling_download_or_inference':False,
        'new_samples_selected':0,'new_downloads':0,'api_calls':0}


def _developer(core_n5_rows,trainingidentity,state,*,core_count,training_count):
    require(len(core_n5_rows)==core_count,'capacity_core_population_required')
    mapping=state['mapping']; rows={};strata={};old_folds={}
    for row in core_n5_rows:
        dish=_dish(row,'dev')
        require(dish not in rows and state['core_rows'][dish]==row,'immutable_capacity_core_binding_required')
        group=row['group_id']
        require(group not in old_folds or old_folds[group]==row['fold'],'old_core_fold_binding_changed')
        old_folds[group]=row['fold'];rows[dish]=deepcopy(row);strata[dish]='core84'
    accepted=trainingidentity['accepted_manifest_private']
    require(len(accepted)==training_count,'all_historical_support_observations_required')
    proposals=trainingidentity['protected_proposals_private']
    require(all(isinstance(r,dict) and set(r)<={'dish_id','sample_id','screening_component_id',
        'original_component_id','recipe_sha256','bytes_sha256','rgb_sha256',
        'quarantine_reasons','protected_training_proposal'} for r in proposals),
        'identity_only_support_proof_required')
    proposal_ids={r['dish_id'] for r in proposals}
    proposal_by_id={r['dish_id']:r for r in proposals}
    require(len(proposals)==len(proposal_ids),'unique_historical_support_proposals_required')
    require(len(proposal_ids)==training_count,'complete_historical_support_proposal_required')
    support=set()
    for row in accepted:
        require(isinstance(row,dict) and set(row)==TRAIN_FIELDS,'identity_only_historical_support_required')
        sample=row['sample_id']
        require(isinstance(sample,str) and sample.startswith('nutrition5k-'),'support_sample_identity_required')
        dish=sample.removeprefix('nutrition5k-')
        require(DISH.fullmatch(dish) and dish in proposal_ids and dish not in rows and dish not in support
            and row['dataset']=='nutrition5k' and row['split']=='train'
            and all(HEX.fullmatch(row[k]) for k in ('recipe_sha256','image_sha256','rgb_sha256'))
            and row['image_path']=='round4/data/train/images/'+row['image_sha256']+'.png'
            and all(isinstance(row[k],str) and row[k] for k in ('group_id','original_component_id')),
            'immutable_support_source_binding_required')
        proof=proposal_by_id[dish]
        require(row['image_sha256']==proof['bytes_sha256'] and row['rgb_sha256']==proof['rgb_sha256']
                and row['recipe_sha256']==proof['recipe_sha256']
                and row['group_id']==proof['screening_component_id']
                and row['original_component_id']==proof['original_component_id'],
                'support_identity_projection_binding_changed')
        support.add(dish);rows[dish]=deepcopy(row);strata[dish]='historical_support230_reused_not_fresh'
    require(support==proposal_ids and len(rows)==core_count+training_count,'complete_capacity_development_union_required')
    groups={mapping[d] for d in rows};uncertain=groups&set(state['quarantine'])
    uncertainty='capacity-v4-uncertainty-'+hashlib.sha256('\n'.join(sorted(uncertain)).encode()).hexdigest()
    units={g:uncertainty if g in uncertain else g for g in groups}
    order=new_group_order(units.values(),seed=SEED+'|folds',count=len(set(units.values())))
    require(len(order)>=5,'five_capacity_fold_units_required')
    folds={u:i%5 for i,u in enumerate(order)}
    bindings={d:{'sample_id':rows[d]['sample_id'],'association_group_id':mapping[d],
        'fold_unit':units[mapping[d]],'prospective_fold':folds[units[mapping[d]]],
        'stratum':strata[d],'historical_source_binding_private':deepcopy(rows[d])} for d in sorted(rows)}
    return {'development_bindings_private':bindings,'original_core_rows_private':deepcopy(core_n5_rows),
        'original_training_manifest_private':deepcopy(accepted),'counts':{'development_rows':len(rows),
            'core_rows':core_count,'reused_historical_support_rows':training_count,
            'association_groups':len(groups),'fold_units':len(order),'uncertainty_components':len(uncertain)},
        'old_folds_overwritten':False,'historical_support_is_fresh_or_independent':False,
        'physical_plate_identity_certified':False,'seed':SEED,**_flags()}


def developer_identity_bindings(core_n5_rows,trainingidentity,state):
    return _developer(core_n5_rows,trainingidentity,state,core_count=84,training_count=230)


def _acceptance(old_validation_rows,state,eligible_new_ids,*,old_count,retained_expected,new_count,max_candidates):
    require(len(old_validation_rows)==old_count,'capacity_old_validation_population_required')
    old={}
    for row in old_validation_rows:
        dish=_dish(row,'validation')
        require(dish not in old,'unique_old_capacity_validation_required');old[dish]=row
    mapping=state['mapping'];protected=state['protected'];old_ids=set(old)
    require({'core','history','training','retired','legacy_reserved','potential_extra'}<=set(protected),
            'complete_capacity_protected_roles_required')
    require(set(protected['legacy_reserved']['dish_ids'])==old_ids,'complete_legacy_reserved_binding_required')
    dangerous=set()
    for role,projection in protected.items():
        if role=='legacy_reserved':continue
        ids=set(projection['dish_ids'])
        if role=='potential_extra':ids-=old_ids
        dangerous|={mapping[d] for d in ids}
    dangerous|=set(state['quarantine'])
    retained=[deepcopy(old[d]) for d in sorted(old) if mapping[d] not in dangerous]
    replaced=[deepcopy(old[d]) for d in sorted(old) if mapping[d] in dangerous]
    allowed=set(state['allowed_ids']);old_groups={mapping[d] for d in old}
    require(not old_ids&allowed and not {mapping[d] for d in allowed}&old_groups,
            'all_old_validation_associations_must_stay_blocked')
    require(isinstance(eligible_new_ids,(set,list,tuple)) and len(eligible_new_ids)<=max_candidates
            and all(isinstance(d,str) and DISH.fullmatch(d) for d in eligible_new_ids)
            and len(set(eligible_new_ids))==len(eligible_new_ids),'identity_only_external_eligible_ids_required')
    eligible=set(eligible_new_ids)
    require(eligible<=allowed and not {mapping[d] for d in eligible}&dangerous,
            'capacity_candidate_outside_allowed_scope')
    by_group=defaultdict(list)
    for dish in eligible:by_group[mapping[dish]].append(dish)
    group_order=new_group_order(by_group,seed=SEED+'|acceptance-groups',count=len(by_group))
    queues={g:new_group_order(by_group[g],seed=SEED+'|acceptance-dishes',count=len(by_group[g])) for g in group_order}
    chosen=[];position=0
    while len(chosen)<new_count:
        batch=[queues[g][position] for g in group_order if len(queues[g])>position]
        if not batch:break
        chosen.extend(batch[:new_count-len(chosen)]);position+=1
    short=[]
    if len(retained)!=retained_expected:short.append('retained_old_population_differs')
    if len(chosen)<new_count:short.append('new_acceptance_fixed_order_shortfall')
    retained_groups={mapping[_dish(r,'validation')] for r in retained}
    require(not retained_groups&{mapping[d] for d in chosen},'acceptance_retained_new_group_collision')
    return {'old_validation_legacy_reserved_private':deepcopy(old_validation_rows),
        'retained_old_rows_private':retained,'linked_old_rows_to_replace_private':replaced,
        'new_acceptance_dish_ids_private':chosen,'component_order_private':group_order,
        'prospective_component_bindings_private':{d:mapping[d] for d in chosen}|{
            _dish(r,'validation'):mapping[_dish(r,'validation')] for r in retained},
        'counts':{'retained_old_rows':len(retained),'new_rows':len(chosen),
            'proposed_rows':len(retained)+len(chosen),
            'retained_old_components':len(retained_groups),
            'full_association_groups':len(retained_groups|{mapping[d] for d in chosen})},
        'shortfall_reasons':short,'within_set_observations_independent':False,
        'external_label_validity_not_nutrient_magnitude_selection':True,'seed':SEED,**_flags()}


def acceptance_identity_proposal(old_validation_rows,state,eligible_new_ids):
    return _acceptance(old_validation_rows,state,eligible_new_ids,old_count=200,
        retained_expected=102,new_count=98,max_candidates=137)
