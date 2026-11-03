"""Pure provisional N5 eligibility for explicit legacy-reserved lineage.

This does not bypass n5_pool's original validation guard. The caller must gate
and authenticate complete raw scans, source/exposure closure and both lineage
states before numeric eligibility. No I/O, targets for blocked rows, or grants.
"""
from collections import Counter
import math

from cohorts_v2 import build_components
from n5_identity import identities,fingerprints,screening_closure,HEX,require
from cohort_lineage_v3 import ordered_proposal_split

TARGETS=('weight','energy','fat','carbs','protein')
PRIOR_ROLES={'core','history','legacy_reserved','training','retired'}
REQUIRED_ROLES=PRIOR_ROLES|{'potential_extra'}
BASE_FIELDS={'mapping','raw_mapping','quarantine','blocked_screening_components','protected','allowed_ids',
    'core_rows','labels_sha256','fingerprints','status','source_completeness_proven',
    'latest_exposure_completeness_proven','download_authorized','inference_authorized','freeze_authorized','frozen'}
OVERLAY_FIELDS={'potential_local_rows_private','potential_path_aliases_private','unassigned_potential_digests_private',
    'postdownload_blind_collision_check_required','eligibility_established'}
FLAGS=('source_completeness_proven','latest_exposure_completeness_proven','download_authorized',
       'inference_authorized','freeze_authorized','frozen')


def _identity_state(scans,state,roles,overlay):
    universe=set(scans)
    require(type(state) is dict and set(state)==BASE_FIELDS|(OVERLAY_FIELDS if overlay else set()),
            'complete_identity_only_lineage_state_required')
    require(state['status']==('provisional_potential_input_overlay' if overlay else 'provisional') and
            all(state[k] is False for k in FLAGS),'provisional_no_grant_state_required')
    if overlay:require(state['eligibility_established'] is False and
                       state['postdownload_blind_collision_check_required'] is True,'overlay_safety_flags_changed')
    require(type(state['mapping']) is dict and type(state['raw_mapping']) is dict and
            set(state['mapping'])==set(state['raw_mapping'])==universe,'complete_raw_mapping_required')
    require(all(type(v) is str and v for m in (state['mapping'],state['raw_mapping']) for v in m.values()),
            'named_raw_components_required')
    require(type(state['fingerprints']) is list and all(type(r) is dict and
            set(r)=={'dish_id','bytes_sha256','rgb_sha256'} for r in state['fingerprints']),
            'identity_only_fingerprints_required')
    pixels=fingerprints(state['fingerprints'],universe)
    raw,ambiguity,_,_=build_components(scans,pixels)
    recipes={d:s.recipe_hash for d,s in scans.items()}
    mapping=screening_closure(raw,recipes,pixels)
    quarantine={mapping[d] for d in universe if raw[d] in ambiguity}
    require(raw==state['raw_mapping'] and mapping==state['mapping'],'complete_raw_recipe_pixel_closure_required')
    require(isinstance(state['quarantine'],(set,list,tuple)) and set(state['quarantine'])==quarantine,
            'complete_quarantine_required')
    require(type(state['protected']) is dict and set(state['protected'])==roles,'all_explicit_protected_roles_required')
    core_fields={'sample_id','dataset','split','group_id','fold','image_path','image_sha256'}
    require(type(state['core_rows']) is dict and all(type(r) is dict and set(r)==core_fields
            for r in state['core_rows'].values()) and type(state['labels_sha256']) is str and
            HEX.fullmatch(state['labels_sha256']),'identity_only_core_projection_required')
    blocked_recipes=set();anchors={}
    for role,entry in state['protected'].items():
        require(type(entry) is dict and set(entry)=={'dish_ids','recipe_hashes'},'identity_only_role_required')
        ds=identities(entry['dish_ids']);require(ds<=universe,'known_protected_dish_required')
        require(isinstance(entry['recipe_hashes'],(list,tuple,set)) and
                all(type(v) is str and HEX.fullmatch(v) for v in entry['recipe_hashes']),
                'protected_recipe_hashes_required')
        require(role=='potential_extra' or bool(ds),'nonempty_prior_protected_roles_required')
        anchors[role]=ds
        blocked_recipes.update(entry['recipe_hashes']);blocked_recipes.update(recipes[d] for d in ds)
    require(isinstance(state['blocked_screening_components'],(set,list,tuple)), 'explicit_blocked_components_required')
    blocked=set(state['blocked_screening_components'])
    required=quarantine|{mapping[d] for ds in anchors.values() for d in ds}
    require(required<=blocked<=set(mapping.values()),'protected_or_quarantine_block_lost')
    allowed={d for d in universe if mapping[d] not in blocked and recipes[d] not in blocked_recipes}
    require(isinstance(state['allowed_ids'],(set,list,tuple)) and identities(state['allowed_ids'])==allowed,
            'fabricated_allowed_ids_rejected')
    return mapping,blocked,blocked_recipes,allowed,anchors


def candidate_pool(scans,available,state,*,prior_state):
    """Return label-free safe candidates and ID-free provisional counts.

    prior_state is mandatory: a post-overlay state alone cannot prove that an
    old blocked component or role was not erased together with allowed_ids.
    Both states remain supplied evidence, not authenticated source closure.
    """
    require(type(scans) is dict and scans,'complete_raw_scans_required')
    universe=identities(list(scans))
    require(all(getattr(s,'dish_id',None)==d and isinstance(getattr(s,'recipe_hash',None),str) and
                HEX.fullmatch(s.recipe_hash) for d,s in scans.items()),'complete_raw_recipe_universe_required')
    old_mapping,old_blocked,old_recipes,_,old_anchors=_identity_state(scans,prior_state,PRIOR_ROLES,False)
    mapping,blocked,blocked_recipes,allowed,anchors=_identity_state(scans,state,REQUIRED_ROLES,True)
    require(all(old_anchors[r]<=anchors[r] and
                set(prior_state['protected'][r]['recipe_hashes'])<=set(state['protected'][r]['recipe_hashes'])
                for r in PRIOR_ROLES),'old_protected_role_or_recipe_exclusion_lost')
    require(all(row in state['fingerprints'] for row in prior_state['fingerprints']),
            'old_pixel_closure_evidence_lost')
    retained={mapping[d] for d in universe if old_mapping[d] in old_blocked}
    require(retained<=blocked and old_recipes<=blocked_recipes,'old_blocked_component_or_recipe_lost')
    # Legacy reservation is always blocked even where it intersects core or
    # another role. This is containment, never independent validation evidence.
    require({mapping[d] for d in anchors['legacy_reserved']}<=blocked,'legacy_reservation_block_lost')
    require(isinstance(available,(list,tuple)),'available_identity_rows_required')
    seen=set();candidates={};excluded=Counter()
    for row in available:
        require(type(row) is dict and set(row)=={'dish_id','truth'},'exact_available_row_required')
        dish=row['dish_id'];require(dish in universe and dish not in seen,'unique_known_available_dish_required');seen.add(dish)
        if mapping[dish] in blocked:
            excluded['protected_or_quarantined_component']+=1;continue
        if scans[dish].recipe_hash in blocked_recipes:
            excluded['protected_recipe']+=1;continue
        require(dish in allowed,'recomputed_allowed_identity_required')
        truth=row['truth']
        require(type(truth) is dict and set(truth)==set(TARGETS),'finite_complete_positive_weight_reference_required')
        try:finite=all(type(v) in (int,float) and math.isfinite(v) and v>=0 for v in truth.values())
        except (ValueError,OverflowError):finite=False
        require(finite and truth['weight']>0,'finite_complete_positive_weight_reference_required')
        if not any(truth[k] for k in TARGETS[1:]):excluded['missing_nutrition']+=1;continue
        if not scans[dish].masses:excluded['no_positive_ingredient_anchor']+=1;continue
        candidates[dish]={'group_id':mapping[dish],'recipe_hash':scans[dish].recipe_hash}
    require(len({r['recipe_hash'] for r in candidates.values()})==len(candidates),
            'original_available_recipe_deduplication_required')
    summary={'available_n':len(seen),'eligible_n':len(candidates),
        'eligible_groups':len({r['group_id'] for r in candidates.values()}),'excluded':dict(excluded),
        'legacy_independent_validation_claimed':False,'source_completeness_proven':False,
        'latest_exposure_completeness_proven':False,'eligibility_established':False,
        'download_authorized':False,'inference_authorized':False,'freeze_authorized':False,'frozen':False,
        'limitation':'Supplied-state consistency only; the actual preparer must authenticate source and exposure closure before eligibility.'}
    return candidates,summary


def propose(scans,available,state,*,prior_state):
    """Fixed 216 development + 200 pending-acceptance proposal, no overrides."""
    candidates,summary=candidate_pool(scans,available,state,prior_state=prior_state)
    proposal=ordered_proposal_split(candidates,development_count=216,acceptance_count=200)
    return proposal,summary
