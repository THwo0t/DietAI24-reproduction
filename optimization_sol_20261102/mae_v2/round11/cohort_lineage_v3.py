"""Pure provisional identity/fold proposals; no I/O, targets, or action grants.

Supplied projections cannot prove source/exposure completeness. The original
n5_identity.reconcile and its failed validation guard are deliberately unchanged.
"""
from collections import defaultdict
from copy import deepcopy
import hashlib

from n5_identity import require, identities, fingerprints, screening_closure, HEX
from cohorts_v2 import build_components
from qualification import new_group_order

SEED = 'DietAI24-Sol-expanded-dev-20261104-O-completed-v1'
FOLD_SEED = SEED + '|cohort-lineage-v3|folds'
COUNTS = {'core':84, 'legacy_reserved':200, 'original_development':100, 'training':230}


def _status():
    return {'status':'provisional', 'source_completeness_proven':False,
            'latest_exposure_completeness_proven':False, 'download_authorized':False,
            'inference_authorized':False, 'freeze_authorized':False, 'frozen':False}


def _core_rows(projection, core, pixels):
    require(set(projection)=={'rows','labels_sha256'}, 'identity_only_core_projection_required')
    require(isinstance(projection['labels_sha256'],str) and HEX.fullmatch(projection['labels_sha256']),
            'core_labels_hash_required')
    rows=projection['rows']; by_dish={}
    pixel_hashes=defaultdict(set)
    for pixel in pixels:pixel_hashes[pixel['dish_id']].add(pixel['bytes_sha256'])
    for row in rows:
        require(set(row)=={'sample_id','dataset','split','group_id','fold','image_path','image_sha256'},
                'identity_only_core_row_required')
        dish=row['sample_id'].removeprefix('nutrition5k-')
        require(row['sample_id']=='nutrition5k-'+dish and dish in core and dish not in by_dish,
                'exact_unique_core_manifest_required')
        require(row['dataset']=='nutrition5k' and row['split']=='dev'
                and type(row['fold']) is int and row['fold'] in range(5), 'old_core_binding_required')
        require(isinstance(row['image_path'],str) and bool(row['image_path'])
                and row['image_sha256'] in pixel_hashes[dish], 'core_image_binding_changed')
        by_dish[dish]=deepcopy(row)
    require(set(by_dish)==core,'complete_core_manifest_required')
    return by_dish


def reconcile_lineage(scans,index,snapshot,cohort_proposal,registry,train_entries,train_pixels,
                      core_manifest,*,expected_counts=None):
    """Reconstruct supplied closure with explicit legacy reservation, never old candidate_pool.

    core_manifest is {rows: identity-only N5 dev rows, labels_sha256: hash}; no
    labels are accepted. Registered counts may be overridden for private tests.
    """
    counts=COUNTS if expected_counts is None else expected_counts
    require(set(counts)==set(COUNTS) and all(type(v) is int and v>0 for v in counts.values()),
            'registered_identity_counts_required')
    universe=set(scans); original=index['original_components'];recipes=index['recipe_sha256']
    require(set(original)==set(recipes)==set(index['screening_components'])==universe,
            'complete_index_raw_universe_required')
    require(all(recipes[d]==scans[d].recipe_hash for d in universe),'raw_recipe_identity_changed')
    members=snapshot['component_members']
    require(sum(map(len,members.values()))==len(universe)
            and {d:g for g,ds in members.items() for d in ds}==original,'snapshot_partition_changed')
    old=fingerprints(index['known_image_fingerprints'],universe)
    baseline,quarantine,_,_=build_components(scans,old)
    require(baseline==original and quarantine==set(snapshot['ambiguous_component_ids']),
            'old_raw_snapshot_changed')
    require(screening_closure(original,recipes,old)==index['screening_components'],
            'old_screening_closure_changed')
    core=identities(snapshot['active_development_ids'])
    original_dev=identities(cohort_proposal['original_development_exposure_ids'])
    roles={'core':core,'legacy_reserved':identities(cohort_proposal['selected_dish_ids']),
           'retired':identities(cohort_proposal['retired_validation_dish_ids'])|(original_dev-core),
           'history':identities(snapshot['historical_exposure_ids'])|identities(registry['exposed_dish_ids'])
                     |identities(registry['local_dish_ids']),
           'training':identities([r['dish_id'] for r in train_entries])}
    require(core<=original_dev,'active_core_not_original_development')
    require(all(ds<=universe for ds in roles.values()),'exposure_identity_outside_raw_universe')
    require(len(original_dev)==counts['original_development']
            and all(len(roles[r])==counts[r] for r in ('core','legacy_reserved','training')),
            'registered_identity_population_changed')
    incoming=fingerprints(train_pixels,universe)
    require(identities([r['dish_id'] for r in incoming])==roles['training'],
            'complete_selected_training_pixels_required')
    pixels=old+incoming
    mapping,raw_ambiguous,_,_=build_components(scans,pixels)
    screening=screening_closure(mapping,recipes,pixels)
    ambiguous={screening[d] for d in universe if mapping[d] in raw_ambiguous}
    old_blocked=set(index['blocked_screening_components'])
    require(old_blocked<=set(index['screening_components'].values()),'unknown_old_blocked_component')
    blocked=ambiguous|{screening[d] for d in universe if index['screening_components'][d] in old_blocked}
    grouped={r:{screening[d] for d in ds} for r,ds in roles.items()}
    blocked|=set().union(*grouped.values())
    recipes_blocked=set(registry['exposed_ingredient_group_sha256'])
    require(all(isinstance(v,str) and HEX.fullmatch(v) for v in recipes_blocked),'valid_exposed_recipe_hash_required')
    recipes_blocked|={recipes[d] for ds in roles.values() for d in ds}
    core_rows=_core_rows(core_manifest,core,pixels)
    require(all(core_rows[d]['group_id']==original[d] for d in core),'old_core_group_binding_changed')
    state={'mapping':screening,'raw_mapping':mapping,'quarantine':ambiguous,
           'blocked_screening_components':blocked,'protected':{r:{'dish_ids':sorted(ds),
            'recipe_hashes':sorted(recipes_blocked) if r=='history' else []} for r,ds in roles.items()},
           'allowed_ids':{d for d in universe if screening[d] not in blocked and recipes[d] not in recipes_blocked},
           'core_rows':core_rows,'labels_sha256':core_manifest['labels_sha256'],
           'fingerprints':deepcopy(pixels),**_status()}
    summary={'role_counts':{r:len(ds) for r,ds in roles.items()},
             'screening_components':len(set(screening.values())),
             'legacy_reserved_intersections':{r:len(grouped['legacy_reserved']&gs)
                 for r,gs in grouped.items() if r!='legacy_reserved'},**_status()}
    return state,summary


def rebuild_core_folds(state):
    """New fold bindings alongside untouched old rows; ambiguity is containment."""
    rows=state['core_rows']; mapping=state['mapping']; ambiguous=state['quarantine']
    groups=defaultdict(list)
    for dish,row in rows.items():groups[mapping[dish]].append(dish)
    uncertain=set(groups)&set(ambiguous)
    uncertainty_unit='uncertainty-containment-'+hashlib.sha256('\n'.join(sorted(uncertain)).encode()).hexdigest()
    units={g:uncertainty_unit if g in uncertain else g for g in groups}
    ordered=new_group_order(units.values(),seed=FOLD_SEED,count=len(set(units.values())))
    require(len(ordered)>=5,'at_least_five_independent_fold_units_required')
    folds={g:i%5 for i,g in enumerate(ordered)}
    bindings={dish:{'screening_component_id':mapping[dish], 'fold_unit_id':units[mapping[dish]],
              'fold':folds[units[mapping[dish]]]} for dish in rows}
    bridges=[g for g,ds in groups.items() if len({rows[d]['fold'] for d in ds})>1]
    return {'original_core_rows':deepcopy(rows),'labels_sha256':state['labels_sha256'],
            'bindings':bindings,'seed':FOLD_SEED,'old_fold_bridge_components':sorted(bridges),
            'screening_component_count':len(groups),'fold_unit_count':len(ordered),
            'ambiguous_core_components':len(uncertain),'uncertainty_containment_units':int(bool(uncertain)),
            'fold_row_counts':{fold:sum(b['fold']==fold for b in bindings.values()) for fold in range(5)},
            **_status()}


def ordered_proposal_split(candidates,*,development_count=216,acceptance_count=200):
    """Already-safe identity candidates only; no target interpretation or authorization."""
    require(all(type(n) is int and n>=0 for n in (development_count,acceptance_count)),
            'nonnegative_proposal_counts_required')
    groups=defaultdict(list)
    for dish,row in candidates.items():
        identities([dish])
        require(set(row)=={'group_id','recipe_hash'} and isinstance(row['group_id'],str)
                and bool(row['group_id']) and isinstance(row['recipe_hash'],str)
                and HEX.fullmatch(row['recipe_hash']),'label_free_safe_candidate_required')
        groups[row['group_id']].append(dish)
    ordered=new_group_order(groups,seed=SEED+'|groups',count=len(groups))
    representatives=[new_group_order(groups[g],seed=SEED+'|dish',count=1)[0] for g in ordered]
    dev=representatives[:development_count]
    acceptance=representatives[development_count:development_count+acceptance_count]
    return {'development_dish_ids':dev,'acceptance_dish_ids':acceptance,
            'development_shortfall':max(0,development_count-len(dev)),
            'acceptance_shortfall':max(0,acceptance_count-len(acceptance)),
            'acceptance_status':'pending_boundary_confirmation','replacement_policy':'none',
            'seed':SEED,**_status()}
