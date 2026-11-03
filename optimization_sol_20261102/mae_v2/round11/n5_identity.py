"""Pure reconciliation of seal-bound N5 identities; no I/O or target access.

The isolated caller must first authenticate the original snapshots/index,
complete training proposal and candidate audit by their registered hashes.
This module neither authenticates those files nor proves a latest exposure
inventory complete. It never selects samples or changes an existing cohort.
"""
from collections import defaultdict
import hashlib
from pathlib import Path
import re
import sys

BASE=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(BASE/'src'))
from cohorts_v2 import build_components

DISH=re.compile(r'dish_[0-9]{10}\Z')
HEX=re.compile(r'[0-9a-f]{64}\Z')
ROLES=('history','core','validation','training','retired')


def require(value,code):
    if not value:raise ValueError(code)


def identities(values):
    require(isinstance(values,(list,tuple,set)), 'identity_collection_required')
    require(all(isinstance(v,str) and DISH.fullmatch(v) for v in values),'valid_dish_identity_required')
    require(len(set(values))==len(values),'duplicate_dish_identity')
    return set(values)


def fingerprints(values,universe):
    result=[]
    for row in values:
        require(row['dish_id'] in universe,'fingerprint_outside_full_raw_universe')
        require(all(isinstance(row[k],str) and HEX.fullmatch(row[k])
                    for k in ('bytes_sha256','rgb_sha256')),'complete_pixel_fingerprints_required')
        result.append({k:row[k] for k in ('dish_id','bytes_sha256','rgb_sha256')})
    return result


def screening_closure(mapping,recipes,pixels):
    """Same conservative recipe/byte/RGB closure as R4; no target weights."""
    require(set(mapping)==set(recipes),'complete_recipe_universe_required')
    parent={group:group for group in mapping.values()}
    def find(group):
        while parent[group]!=group:
            parent[group]=parent[parent[group]];group=parent[group]
        return group
    def join(a,b):
        a,b=find(a),find(b)
        if a!=b:parent[max(a,b)]=min(a,b)
    seen={}
    for dish in sorted(mapping):
        key=('recipe',recipes[dish])
        if key in seen:join(mapping[dish],mapping[seen[key]])
        seen[key]=dish
    for row in pixels:
        for field in ('bytes_sha256','rgb_sha256'):
            key=(field,row[field])
            if key in seen:join(mapping[row['dish_id']],mapping[seen[key]])
            seen[key]=row['dish_id']
    members=defaultdict(list)
    for group in sorted(parent):members[find(group)].append(group)
    names={root:'round4-screening-'+hashlib.sha256('\n'.join(groups).encode()).hexdigest()
           for root,groups in members.items()}
    return {dish:names[find(group)] for dish,group in mapping.items()}


def reconcile(scans,index,snapshot,cohort_proposal,registry,train_entries,train_pixels,
              *,expected_counts):
    """Return PRIVATE identity state and an ID-free aggregate only.

    expected_counts must come from the preregistered caller, never discovered
    from the input itself. Production expectations are core84, validation200,
    original_development100 and training230. Tests use explicit small fixtures.
    """
    require(set(expected_counts)=={'core','validation','original_development','training'},
            'registered_identity_counts_required')
    require(all(type(v) is int and v>0 for v in expected_counts.values()),
            'positive_registered_identity_counts_required')
    universe=set(scans);original=index['original_components'];recipes=index['recipe_sha256']
    require(set(original)==set(recipes)==set(index['screening_components'])==universe,
            'complete_index_raw_universe_required')
    require(all(recipes[dish]==scans[dish].recipe_hash for dish in universe),
            'raw_recipe_identity_changed')
    members=snapshot['component_members']
    require(sum(len(rows) for rows in members.values())==len(universe),
            'snapshot_partition_population_changed')
    snapshot_mapping={dish:group for group,rows in members.items() for dish in rows}
    require(snapshot_mapping==original,'snapshot_partition_changed')
    old_pixels=fingerprints(index['known_image_fingerprints'],universe)
    baseline,old_quarantine,_,_=build_components(scans,old_pixels)
    require(baseline==original,'raw_graph_does_not_reproduce_original_snapshot')
    require(old_quarantine==set(snapshot['ambiguous_component_ids']),
            'raw_ambiguity_does_not_reproduce_original_snapshot')
    require(screening_closure(original,recipes,old_pixels)==index['screening_components'],
            'old_screening_closure_changed')

    core=identities(snapshot['active_development_ids'])
    validation=identities(cohort_proposal['selected_dish_ids'])
    original_dev=identities(cohort_proposal['original_development_exposure_ids'])
    retired=identities(cohort_proposal['retired_validation_dish_ids'])|(original_dev-core)
    history=identities(snapshot['historical_exposure_ids'])
    history|=identities(registry['exposed_dish_ids'])|identities(registry['local_dish_ids'])
    training=identities([row['dish_id'] for row in train_entries])
    roles=dict(zip(ROLES,(history,core,validation,training,retired)))
    for role,values in roles.items():require(values<=universe,'exposure_identity_outside_raw_universe')
    require(core<=original_dev,'active_core_not_original_development')
    for role in ('core','validation','training'):
        require(len(roles[role])==expected_counts[role],'registered_identity_population_changed')
    require(len(original_dev)==expected_counts['original_development'],
            'registered_identity_population_changed')
    incoming=fingerprints(train_pixels,universe)
    require(identities([row['dish_id'] for row in incoming])==training,
            'complete_selected_training_pixels_required')
    pixels=old_pixels+incoming
    new_mapping,new_quarantine,_,_=build_components(scans,pixels)
    screening=screening_closure(new_mapping,recipes,pixels)
    grouped={role:{screening[dish] for dish in values} for role,values in roles.items()}
    ambiguous={screening[dish] for dish in universe if new_mapping[dish] in new_quarantine}
    require(not grouped['validation']&ambiguous,'validation_linkage_requires_separate_resolution')
    for role in ('history','core','training','retired'):
        require(not grouped['validation']&grouped[role],
                'validation_linkage_requires_separate_resolution')
    old_blocked=set(index['blocked_screening_components'])
    require(old_blocked<=set(index['screening_components'].values()),'unknown_old_blocked_component')
    # Preserve every historical screening exclusion, even if its original
    # reason was not separately materialized in the five role lists.
    projected_old={screening[dish] for dish in universe
                   if index['screening_components'][dish] in old_blocked}
    blocked=ambiguous|projected_old|set().union(*grouped.values())
    exposed_recipes=set(registry['exposed_ingredient_group_sha256'])
    require(all(isinstance(v,str) and HEX.fullmatch(v) for v in exposed_recipes),
            'valid_exposed_recipe_hash_required')
    exposed_recipes|={recipes[dish] for values in roles.values() for dish in values}
    allowed={dish for dish in universe
             if screening[dish] not in blocked and recipes[dish] not in exposed_recipes}
    private={'mapping':screening,'raw_mapping':new_mapping,'quarantine':ambiguous,
        'protected':{role:{'dish_ids':sorted(values),'recipe_hashes':
            sorted(exposed_recipes) if role=='history' else []} for role,values in roles.items()},
        'allowed_ids':allowed,'fingerprints':pixels}
    aggregate={'raw_dishes':len(universe),'raw_components':len(set(new_mapping.values())),
        'screening_components':len(set(screening.values())),
        'role_counts':{role:len(values) for role,values in roles.items()},
        'allowed_identity_count_before_eligibility':len(allowed),
        'blocked_screening_components':len(blocked),'validation_intersections':0}
    return private,aggregate
