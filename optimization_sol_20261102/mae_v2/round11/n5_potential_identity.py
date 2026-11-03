"""Pure, private potential-input overlay after provisional reconcile_lineage.

No I/O, target payload, eligibility, proposal selection or completeness grant.
The generic local RGB algorithm equals cohorts_v2.image_fingerprint's legacy
N5 size-tuple/NUL/RGB algorithm; ASA's separate digest is never substituted.
Unassigned rows must later participate in blind post-download collision checks.
"""
from collections import defaultdict
from copy import deepcopy
import re

from n5_identity import require, fingerprints, identities, screening_closure, HEX
from cohorts_v2 import build_components
from local_input_inventory import dependency_gif_path

RGB_ALGORITHM = 'pillow-convert-RGB-size-tuple-nul-v1'
LOCAL_FIELDS = frozenset(('path','classification','bytes_sha256','rgb_sha256','rgb_algorithm',
    'width','height','mode','format','nontrivial_render_semantics','asa_compatible',
    'asa_rgb_sha256','asa_algorithm'))
TOKEN = re.compile(r'(?<![A-Za-z0-9_])dish_[0-9]{10}(?![A-Za-z0-9_])')


def _status():
    return dict(status='provisional_potential_input_overlay', source_completeness_proven=False,
        latest_exposure_completeness_proven=False, eligibility_established=False,
        download_authorized=False, inference_authorized=False, freeze_authorized=False, frozen=False)


def _pixels(rows, universe):
    require(isinstance(rows,(list,tuple)) and all(isinstance(r,dict) and
        set(r)=={'dish_id','bytes_sha256','rgb_sha256'} for r in rows),
        'identity_only_fingerprints_required')
    return fingerprints(rows,universe)


def overlay_potential_identity(scans, state, known_fingerprints, training_fingerprints, local_rows):
    """Return (PRIVATE extended lineage state, ID-free aggregate).

    All local rows, including charts and dependencies, remain private verbatim.
    Paths identify possible N5 dishes, never actual exposure or dataset membership.
    Full raw scans are required; state must be reconcile_lineage's provisional
    result. The supplied full index/training fingerprints must reproduce it.
    """
    universe=set(scans)
    required={'mapping','raw_mapping','quarantine','blocked_screening_components','protected',
        'allowed_ids','core_rows','labels_sha256','fingerprints','status',
        'source_completeness_proven','latest_exposure_completeness_proven',
        'download_authorized','inference_authorized','freeze_authorized','frozen'}
    require(isinstance(state,dict) and set(state)==required,'identity_only_lineage_state_required')
    require(state['status']=='provisional' and all(state[k] is False for k in
        ('source_completeness_proven','latest_exposure_completeness_proven','download_authorized',
         'inference_authorized','freeze_authorized','frozen')),'provisional_lineage_required')
    core_fields={'sample_id','dataset','split','group_id','fold','image_path','image_sha256'}
    require(isinstance(state['core_rows'],dict) and all(isinstance(r,dict) and set(r)==core_fields
            for r in state['core_rows'].values()),'identity_only_core_rows_required')
    require(isinstance(state['protected'],dict) and set(state['protected'])==
            {'core','legacy_reserved','retired','history','training'}
            and all(isinstance(r,dict) and set(r)=={'dish_ids','recipe_hashes'}
                    for r in state['protected'].values()),'identity_only_protected_roles_required')
    recipes={d:s.recipe_hash for d,s in scans.items()}
    old=_pixels(known_fingerprints,universe)+_pixels(training_fingerprints,universe)
    require(old==_pixels(state['fingerprints'],universe),'complete_old_training_fingerprints_required')
    raw,ambiguity,_,_=build_components(scans,old)
    require(raw==state['raw_mapping'] and screening_closure(raw,recipes,old)==state['mapping'],
            'complete_raw_lineage_required')
    require(set(state['mapping'])==universe,'complete_raw_universe_required')
    require(isinstance(local_rows,(list,tuple)), 'local_identity_rows_required')
    rows=[]; paths=set(); resolved=[]
    for row in local_rows:
        require(isinstance(row,dict) and set(row)==LOCAL_FIELDS,'identity_only_local_row_required')
        require(all(isinstance(row[k],str) and row[k] for k in ('path','classification','mode'))
                and row['path'] not in paths,'unique_local_path_required')
        require(row['rgb_algorithm']==RGB_ALGORITHM and (row['format'] in ('PNG','JPEG') or
                    (row['format']=='GIF' and row['classification']=='dependency'
                     and dependency_gif_path(row['path']) and not row['asa_compatible']))
                and all(type(row[k]) is int and row[k]>0 for k in ('width','height'))
                and all(type(row[k]) is bool for k in ('nontrivial_render_semantics','asa_compatible')),
                'registered_local_rgb_contract_required')
        require(all(isinstance(row[k],str) and HEX.fullmatch(row[k]) for k in
                    ('bytes_sha256','rgb_sha256')),'valid_local_digest_required')
        require((row['asa_compatible'] and isinstance(row['asa_rgb_sha256'],str)
                 and HEX.fullmatch(row['asa_rgb_sha256']) and isinstance(row['asa_algorithm'],str))
                or (not row['asa_compatible'] and row['asa_rgb_sha256'] is None
                    and row['asa_algorithm'] is None),'valid_asa_identity_projection_required')
        ds=set(TOKEN.findall(row['path']))
        require(ds<=universe,'path_dish_outside_full_raw_universe')
        paths.add(row['path']);rows.append(deepcopy(row));resolved.append(ds)
    lookup=defaultdict(set)
    for p in old:
        for field in ('bytes_sha256','rgb_sha256'):lookup[field,p[field]].add(p['dish_id'])
    # Fixed point retains every hash/path bridge and every alias, independent of row order.
    changed=True
    while changed:
        changed=False
        for row,ds in zip(rows,resolved):
            before=set(ds)
            for field in ('bytes_sha256','rgb_sha256'):ds.update(lookup[field,row[field]])
            if ds!=before:changed=True
            for field in ('bytes_sha256','rgb_sha256'):
                key=(field,row[field]); previous=len(lookup[key]);lookup[key].update(ds)
                if len(lookup[key])!=previous:changed=True
    additions=[]; aliases=defaultdict(list);unassigned=[]
    for row,ds in zip(rows,resolved):
        if not ds:unassigned.append(deepcopy(row))
        for d in sorted(ds):
            aliases[d].append(row['path'])
            additions.append({'dish_id':d,**{k:row[k] for k in ('bytes_sha256','rgb_sha256')}})
    pixels=old+additions
    raw,raw_ambiguous,_,_=build_components(scans,pixels)
    mapping=screening_closure(raw,recipes,pixels)
    ambiguous={mapping[d] for d in universe if raw[d] in raw_ambiguous}
    blocked_old=set(state['blocked_screening_components'])
    require(blocked_old<=set(state['mapping'].values()),'unknown_old_blocked_component')
    blocked=ambiguous|{mapping[d] for d in universe if state['mapping'][d] in blocked_old}
    protected=deepcopy(state['protected']); potential=set(aliases)
    protected['potential_extra']={'dish_ids':sorted(potential),'recipe_hashes':sorted({recipes[d] for d in potential})}
    blocked_recipes=set()
    for role in protected.values():
        require(set(role)=={'dish_ids','recipe_hashes'},'identity_only_protected_role_required')
        ds=identities(role['dish_ids']);require(ds<=universe,'protected_identity_outside_raw_universe')
        require(all(isinstance(v,str) and HEX.fullmatch(v) for v in role['recipe_hashes']), 'valid_protected_recipe_required')
        blocked.update(mapping[d] for d in ds)
        blocked_recipes.update(role['recipe_hashes']);blocked_recipes.update(recipes[d] for d in ds)
    result=deepcopy(state)
    result.update(mapping=mapping,raw_mapping=raw,quarantine=ambiguous,
        blocked_screening_components=blocked,protected=protected,fingerprints=pixels,
        allowed_ids={d for d in universe if mapping[d] not in blocked and recipes[d] not in blocked_recipes},
        potential_local_rows_private=rows,potential_path_aliases_private={d:sorted(ps) for d,ps in sorted(aliases.items())},
        unassigned_potential_digests_private=unassigned,
        postdownload_blind_collision_check_required=True,**_status())
    summary={'local_image_rows':len(rows),'resolved_local_rows':sum(bool(ds) for ds in resolved),
        'unassigned_local_rows':len(unassigned),'potential_extra_identity_count':len(potential),
        'new_potential_identity_count':len(potential-{p['dish_id'] for p in old}),
        'raw_components':len(set(raw.values())),'screening_components':len(set(mapping.values())),
        'blocked_screening_components':len(blocked),
        'classification_counts':{c:sum(r['classification']==c for r in rows) for c in sorted({r['classification'] for r in rows})},
        'postdownload_blind_collision_check_required':True,**_status()}
    return result,summary
