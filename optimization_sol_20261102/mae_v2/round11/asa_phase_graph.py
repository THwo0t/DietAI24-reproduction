"""Pure ASA phase topology audit. Supplied identities confer no action permission.

No files, targets, selection, fold repair or source authentication occur here.
The caller must hold and revalidate the source projections around this function.
"""
from collections import defaultdict
from copy import deepcopy
import re

from asa_content_identity import ALGORITHM, build_asa_content_inventory
from asa_identity import ROLES, require, sha_value, image_name
from development_identity import FIELDS

COUNTS = {'core': (99, 23), 'validation': (78, 23)}


def _bindings(projection, expected):
    old = projection['originalmanifestbinding']
    current = projection['currentmanifestbinding']
    result = {}
    for role, (population, groups) in expected.items():
        def indexed(rows):
            require(len(rows) == population, 'exact_asa_role_population_required')
            out = {}
            for row in rows:
                require(isinstance(row, dict) and set(row) == FIELDS,
                        'identity_only_manifest_required')
                sample = row['sample_id']
                require(isinstance(sample, str) and re.fullmatch(r'asa24-[0-9]{8}-.+', sample)
                        and sample not in out and row['dataset'] == 'asa24',
                        'unique_asa_sample_binding_required')
                require(row['split'] == ('dev' if role == 'core' else 'validation')
                        and isinstance(row['group_id'], str) and row['group_id']
                        and (type(row['fold']) is int and row['fold'] in range(5)
                             if role == 'core' else row['fold'] is None),
                        'preserved_asa_manifest_binding_required')
                require(isinstance(row['image_path'], str) and row['image_path'],
                        'image_path_required')
                sha_value(row['image_sha256']); out[sample] = row
            require(len({r['group_id'] for r in rows}) == groups,
                    'exact_asa_role_group_population_required')
            return out
        before, after = indexed(old[role]), indexed(current[role])
        require(set(before) == set(after) and all(
            {k:v for k,v in before[s].items() if k != 'image_path'} ==
            {k:v for k,v in after[s].items() if k != 'image_path'} for s in before),
            'preserved_asa_identity_changed')
        result[role] = (before, after)
    return result


def _build_phase_graph(asa_capture, role_projection, local_content, *, expected_counts):
    bindings = _bindings(role_projection, expected_counts)
    protected = deepcopy(role_projection['roleanchors'])
    require(set(protected) == ROLES, 'complete_protected_role_inventory_required')
    workbook = asa_capture['asa_workbook_identity']
    pairs = list(workbook['pairs']) + list(role_projection['historical_pairs'])
    metadata = set(workbook['metadata_images']) | {name for _, name in pairs}
    fingerprints = list(asa_capture['asa_archive_identity']['image_fingerprints'])
    # Original frozen names are trusted only with their exact recorded byte hash.
    trusted = defaultdict(set)
    for before, _ in bindings.values():
        for row in before.values():
            trusted[row['image_path'].rsplit('/', 1)[-1]].add(row['image_sha256'])
    known = defaultdict(set)
    for row in fingerprints:
        known[row['image']].add(row['bytes_sha256'])
    require(all(len(v) == 1 for v in known.values()), 'conflicting_image_basename_bytes')
    for name, hashes in trusted.items():
        require(len(hashes) == 1 and (name not in known or hashes == known[name]),
                'conflicting_original_binding_bytes')
    by_hash = defaultdict(set)
    for name, hashes in {**trusted, **known}.items():
        for digest in hashes: by_hash[digest].add(name)
    unmatched = []; attachments = []
    for local in local_content['rows_private']:
        digest = sha_value(local['bytes_sha256'])
        require(local.get('asa_algorithm') in (None, ALGORITHM), 'registered_pixel_semantics_required')
        if local.get('asa_compatible'):
            require(local.get('asa_algorithm') == ALGORITHM, 'registered_pixel_semantics_required')
        basename = local['path'].rsplit('/', 1)[-1]
        # Never create a source image name from a neutral local filename.
        if basename in known or basename in trusted:
            require(digest in (known.get(basename) or trusted[basename]),
                    'conflicting_local_original_bytes')
        names = set(by_hash.get(digest, ()))
        if basename in metadata and basename not in known and basename not in trusted:
            # A name alone cannot authenticate bytes for an unknown metadata photo.
            names.discard(basename)
        if not names:
            unmatched.append(deepcopy(local)); continue
        for name in sorted(names):
            row = {'image':name, 'bytes_sha256':digest, 'rgb_sha256':None,
                   'width':None, 'height':None, 'algorithm':None}
            if local.get('asa_compatible'):
                row.update(rgb_sha256=local['asa_rgb_sha256'], width=local['width'],
                           height=local['height'], algorithm=ALGORITHM)
            fingerprints.append(row)
            attachments.append({'local_path':local['path'], 'image':name, 'bytes_sha256':digest})
    universe = metadata | {r['image'] for r in fingerprints}
    known_bytes = {r['image'] for r in fingerprints}
    known_pixels = {r['image'] for r in fingerprints if r['rgb_sha256'] is not None}
    graph, summary = build_asa_content_inventory(pairs, fingerprints, protected,
        metadata_images=metadata, unknown_byte_images=universe-known_bytes,
        unknown_pixel_images=universe-known_pixels)
    mapped = {}; folds = defaultdict(set); old_groups = defaultdict(set)
    for role, (before, after) in bindings.items():
        mapped[role] = []
        for sample, old in before.items():
            code = sample.split('-', 2)[1]; name = old['image_path'].rsplit('/', 1)[-1]
            require('c:'+code in graph['node_groups'], 'original_sample_code_association_required')
            group = graph['node_groups']['c:'+code]
            verified = (name in graph['fingerprints'] and
                        graph['fingerprints'][name]['bytes_sha256'] == old['image_sha256'])
            require(name in protected[role]['images'] and old['image_sha256'] in protected[role]['hashes']
                    and code in protected[role]['codes'], 'old_role_anchor_binding_changed')
            if verified:
                require(graph['node_groups']['i:'+name] == group,
                        'old_sample_code_image_association_changed')
            mapped[role].append({'original':deepcopy(old), 'current':deepcopy(after[sample]),
                'component':group, 'source_image_hash_verified':verified})
            old_groups[group].add((role, old['group_id']))
            if role == 'core': folds[group].add(old['fold'])
    bridges = {g:sorted(v) for g,v in folds.items() if len(v)>1}
    intersections = summary['observed_protected_intersections']['core__validation']
    unverified = sum(not row['source_image_hash_verified'] for rows in mapped.values() for row in rows)
    reasons = []
    if bridges: reasons.append('old_core_fold_bridges')
    if intersections: reasons.append('core_validation_intersections')
    if summary['unresolved_component_count'] or unverified: reasons.append('unknown_content_identity')
    if unmatched: reasons.append('unregistered_local_potential_inputs')
    if any(not any(protected[r].values()) for r in ('training','retired')):
        reasons.append('empty_training_or_retired_inventory_unproven')
    if not role_projection.get('role_inventory_complete', False): reasons.append('role_inventory_incomplete')
    if not role_projection.get('source_association_complete', False): reasons.append('source_association_incomplete')
    flags = {'role_inventory_complete':role_projection.get('role_inventory_complete', False),
        'source_association_complete':role_projection.get('source_association_complete', False),
        'actual_api_exposure_complete':False, 'candidate_eligibility_evaluated':False,
        'grants_sampling_download_or_inference':False, 'new_samples_selected':0,
        'new_downloads':0, 'api_calls':0, 'requires_disposition':bool(reasons),
        'status':'asa_phase_identity_audit_requires_disposition' if reasons else 'asa_phase_identity_audit_only'}
    graph.update(manifest_bindings=mapped, local_attachments=attachments,
        unmatched_local_potential_inputs=unmatched, old_core_fold_bridges=bridges,
        old_groups_by_component={g:sorted(v) for g,v in old_groups.items()},
        stop_reasons=reasons, **flags)
    summary.update(old_core_fold_bridge_components=len(bridges),
        core_validation_intersection_components=intersections,
        merged_old_group_components=sum(len(v)>1 for v in old_groups.values()),
        unverified_original_image_bindings=unverified, local_attachment_count=len(attachments),
        unmatched_local_potential_input_count=len(unmatched),
        empty_unproven_roles=[r for r in ('training','retired') if not any(protected[r].values())],
        stop_reasons=reasons, **flags)
    return graph, summary


def build_phase_graph(asa_capture, role_projection, local_content):
    """Return a private graph and ID-free aggregate, with fixed production counts."""
    return _build_phase_graph(asa_capture, role_projection, local_content, expected_counts=COUNTS)
