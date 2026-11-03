"""Pure blind expanded-development eligibility; no files, images or inference.

Caller supplies complete raw scans and full-universe byte/RGB/scan components
from cohorts_v2, plus the verified current exposure registry. This cannot prove
the completeness of those external inputs or authorize a real sample freeze.
"""
from collections import Counter
import math

from qualification import new_group_order

TARGETS=('weight','energy','fat','carbs','protein')
REQUIRED_ROLES={'history','core','validation','training','retired'}


def candidate_pool(scans,available,mapping,quarantine,protected):
    if set(mapping)!=set(scans) or set(protected)!=REQUIRED_ROLES:
        raise ValueError('complete_raw_universe_and_exposure_roles_required')
    if not set(quarantine)<=set(mapping.values()):raise ValueError('unknown_quarantined_component')
    if any(not isinstance(group,str) or not group for group in mapping.values()):
        raise ValueError('complete_named_raw_components_required')
    blocked_recipes=set();groups={}
    for role,entry in protected.items():
        if set(entry)!={'dish_ids','recipe_hashes'} or not set(entry['dish_ids'])<=set(scans):
            raise ValueError('complete_known_exposure_anchors_required')
        groups[role]={mapping[dish] for dish in entry['dish_ids']}
        blocked_recipes.update(entry['recipe_hashes'])
        blocked_recipes.update(scans[dish].recipe_hash for dish in entry['dish_ids'])
    for role in ('history','core','training','retired'):
        if groups['validation']&groups[role]:raise ValueError('protected_validation_linkage_requires_separate_resolution')
    if groups['validation']&set(quarantine):raise ValueError('protected_validation_linkage_requires_separate_resolution')
    blocked=set(quarantine)|set().union(*groups.values());seen=set();candidates={};excluded=Counter()
    for row in available:
        if set(row)!={'dish_id','truth'} or row['dish_id'] in seen or row['dish_id'] not in scans:
            raise ValueError('unique_available_raw_dish_required')
        dish=row['dish_id'];seen.add(dish)
        # Exclusion is an identity-only operation. Never inspect target values
        # for validation, history, training, retired or related records.
        if mapping[dish] in blocked:excluded['protected_or_quarantined_component']+=1;continue
        if scans[dish].recipe_hash in blocked_recipes:excluded['protected_recipe']+=1;continue
        truth=row['truth']
        if (set(truth)!=set(TARGETS) or any(type(v) not in (int,float) or not math.isfinite(v) or v<0
                                           for v in truth.values()) or truth['weight']<=0):
            raise ValueError('finite_complete_positive_weight_reference_required')
        if not any(truth[k] for k in TARGETS[1:]):excluded['missing_nutrition']+=1;continue
        if not scans[dish].masses:excluded['no_positive_ingredient_anchor']+=1;continue
        candidates[dish]={'group_id':mapping[dish],'recipe_hash':scans[dish].recipe_hash}
    if len({r['recipe_hash'] for r in candidates.values()})!=len(candidates):
        raise ValueError('original_available_recipe_deduplication_required')
    return candidates,{'available_n':len(seen),'eligible_n':len(candidates),
        'eligible_groups':len({r['group_id'] for r in candidates.values()}),'excluded':dict(excluded),
        'protected_validation_intersections':0,
        'limitation':'Counts concern supplied complete inputs; registry/source completeness remains a preparer obligation.'}


def choose_new_dishes(candidates,*,seed,count):
    """One fixed representative per full component, no outcome/target ranking."""
    groups={}
    for dish,row in candidates.items():
        if set(row)!={'group_id','recipe_hash'}:raise ValueError('label_free_candidate_shape_required')
        groups.setdefault(row['group_id'],[]).append(dish)
    ordered=new_group_order(groups,seed=seed+'|groups',count=count)
    # The caller's available frame already applies the original recipe rule;
    # the component representative is selected independently of target size.
    selected=[new_group_order(groups[group],seed=seed+'|dish',count=1)[0] for group in ordered]
    return selected,{'requested':count,'selected':len(selected),'independent_linkage_groups':len(ordered),
                     'shortfall':max(0,count-len(selected)),'replacement_policy':'none'}
