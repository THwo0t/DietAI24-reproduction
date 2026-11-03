#!/usr/bin/env python3
"""Separate private mechanical inventory; never selects a cohort or calls a model.

This consumes the completed census and stopped-capture evidence. It does not
repeat O or the original failed capture. All image decoding is blind exact
fingerprinting, including sealed image copies; numerical labels stay unopened.
"""
from copy import deepcopy
import json
from pathlib import Path
import sys

import PIL
import openpyxl
import asa_source_capture
import development_identity
import legacy_input_identity
import local_content_inventory
import local_input_inventory
import n5_sources
from cohort_lineage_v3 import reconcile_lineage, rebuild_core_folds
from n5_potential_identity import overlay_potential_identity
from n5_preparation import raw_scans
from source_capture import plain
from source_census import (BASE, REPO, PREFIX, CONTROL_PINS, bounded_read,
    control_evidence, decode, encoded, sha, require, isolated_network, _write_at)

OUTPUT = PREFIX + 'round11/preparation/source_inventory/source_inventory.json'
IMPLEMENTATION_FILES = tuple('round11/' + name + '.py' for name in (
    'source_inventory_capture', 'source_census', 'source_capture', 'n5_sources',
    'n5_preparation', 'n5_identity', 'n5_pool', 'cohort_lineage_v3',
    'n5_potential_identity', 'development_identity', 'legacy_input_identity',
    'local_input_inventory', 'local_content_inventory', 'asa_source_capture',
    'asa_archive', 'asa_workbook', 'asa_content_identity', 'asa_identity',
    'qualification')) + ('src/cohorts_v2.py',)


def implementation_pins(base):
    return {name: sha(bounded_read(base, name)) for name in IMPLEMENTATION_FILES}


def verify_asa_bindings(repo, asa):
    archive_path = asa_source_capture.ASA_SOURCES[0]
    hashes = {**asa['source_sha256'], **asa['registered_asa_sources_sha256']}
    for name, expected in hashes.items():
        if name == archive_path:
            with asa_source_capture.asa_archive._open(repo) as stream:
                require(asa_source_capture.asa_archive._digest(stream)[0] == expected,
                        'asa_inventory_source_changed')
        else:
            require(sha(bounded_read(repo, name)) == expected, 'asa_inventory_source_changed')


def verify_legacy_bindings(root, legacy):
    for source in legacy['sources']:
        require(source['path'] in legacy_input_identity.LEGACY_MANIFESTS,
                'registered_legacy_source_required')
        status = source['status']
        require(status in ('captured_prospective', 'empty_unresolved', 'missing_unresolved'),
                'registered_legacy_source_status_required')
        if status == 'missing_unresolved':
            try:
                bounded_read(root, source['path'])
            except FileNotFoundError:
                continue
            raise ValueError('legacy_inventory_source_changed')
        try:
            raw = bounded_read(root, source['path'])
        except FileNotFoundError:
            raise ValueError('legacy_inventory_source_changed') from None
        require(sha(raw) == source['sha256'], 'legacy_inventory_source_changed')


def _collect_at(repo, base, *, controls=CONTROL_PINS, n5_anchors=None,
                expected_counts=None):
    """Private synthetic fixture hook. No production CLI overrides exist."""
    repo, base = Path(repo), Path(base)
    require(repo.is_absolute() and repo.resolve() == repo
            and base == repo / PREFIX.rstrip('/'), 'canonical_inventory_roots_required')
    implementations = implementation_pins(base)
    controls_seen = control_evidence(base, controls)
    n5, n5_reader = n5_sources.load_identity_sources(repo, anchors=n5_anchors)
    anchors = n5_sources.ANCHORS if n5_anchors is None else n5_anchors
    development, dev_reader = development_identity._load_development_identity(
        repo, anchors['development_seal'])
    asa, asa_summary = asa_source_capture._capture_at(repo, base, controls=controls,
        snapshot_sha=anchors['original_snapshot'])
    legacy = legacy_input_identity._load_at(repo.parent)
    metadata = local_input_inventory.inventory_metadata(repo)
    content = local_content_inventory._load_at(repo, metadata['projection'])
    scans = raw_scans(n5['raw_tables'])
    provisional, supplied_summary = reconcile_lineage(scans, n5['index'], n5['snapshot'],
        n5['cohort_proposal'], n5['registry'], n5['train_entries'], n5['train_pixels'],
        development['n5_core'], expected_counts=expected_counts)
    identities, local_summary = overlay_potential_identity(scans, provisional,
        n5['index']['known_image_fingerprints'], n5['train_pixels'], content['rows_private'])
    core_folds = rebuild_core_folds(identities)
    # Legacy identities and source corpus/caller distinctions are retained for
    # the subsequent complete role audit, not silently declared resolved here.
    n5_reader.revalidate()
    dev_reader.revalidate()
    image_sizes = {r['path']: r['bytes'] for r in metadata['projection']['entries'] if r['image']}
    require(set(image_sizes) == {r['path'] for r in content['rows_private']},
            'complete_local_image_inventory_required')
    for row in content['rows_private']:
        raw = bounded_read(repo, row['path'])
        require(len(raw) == image_sizes[row['path']] and sha(raw) == row['bytes_sha256'],
                'local_inventory_image_changed')
    # Hash only already opened fixed metadata paths; never chase label/image
    # paths supplied by a source seal or legacy manifest.
    verify_asa_bindings(repo, asa)
    verify_legacy_bindings(repo.parent, legacy)
    require(local_input_inventory.load_projected(repo) == metadata['projection']
            and local_input_inventory.inspect_links(repo, metadata['projection'])
                == metadata['link_metadata_private']
            and control_evidence(base, controls) == controls_seen
            and implementation_pins(base) == implementations, 'inventory_sources_changed')
    flags = {'source_association_complete': False, 'potential_input_coverage_complete': False,
        'actual_api_exposure_complete': False, 'candidate_eligibility_evaluated': False,
        'protected_dish_targets_interpreted': 0, 'candidate_targets_interpreted': 0,
        'sealed_label_files_opened': 0, 'local_images_mechanically_fingerprinted': len(image_sizes),
        'local_images_may_include_sealed_copies': True, 'food_visual_analysis_performed': False,
        'original_linkage_guard_remains_stopped': True, 'fresh_O_store_replay': False,
        'new_samples_selected': 0, 'new_downloads': 0, 'api_calls': 0,
        'grants_sampling_download_or_inference': False}
    summary = {'status': 'mechanical_source_inventory_captured_role_closure_pending',
        'local_content': content['counts'], 'local_metadata': metadata['projection']['counts'],
        'link_status_counts': {s: sum(r['status'] == s for r in metadata['link_metadata_private']['links'])
            for s in sorted({r['status'] for r in metadata['link_metadata_private']['links']})},
        'legacy': legacy['summary'], 'asa': asa_summary,
        'n5_supplied': supplied_summary, 'n5_local_overlay': local_summary,
        'core_fold_proposal': {k: deepcopy(core_folds[k]) for k in (
            'screening_component_count', 'fold_unit_count', 'ambiguous_core_components',
            'uncertainty_containment_units', 'fold_row_counts')},
        'old_core_fold_bridge_components': len(core_folds['old_fold_bridge_components']), **flags}
    value = plain({'schema_version': 1, **summary, 'control_sha256': controls_seen,
        'implementation_sha256': implementations,
        'runtime': {'python': sys.version.split()[0], 'Pillow': PIL.__version__,
            'openpyxl': openpyxl.__version__, 'n5_rgb_algorithm': local_content_inventory.RGB_ALGORITHM},
        'n5_source_sha256': n5['source_hashes'],
        'development_identity': development, 'asa_mechanical_sources': asa,
        'legacy_inputs_private': legacy, 'local_metadata_private': metadata,
        'local_content_private': content, 'n5_identity_state_private': identities,
        'core_fold_proposal_private': core_folds})
    return value, plain(summary)


def main():
    require(len(sys.argv) == 1, 'inventory_cli_overrides_refused')
    require(isolated_network(Path('/proc/self/net/dev').read_bytes()),
            'isolated_network_namespace_required')
    output = REPO / OUTPUT
    require(output.resolve() == output and not output.exists(), 'fresh_inventory_output_required')
    value, summary = _collect_at(REPO, BASE)
    _write_at(REPO, OUTPUT, value)
    print(json.dumps({**summary, 'private_inventory_sha256': sha(encoded(value))}, sort_keys=True))


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print(json.dumps({'status': 'source_inventory_refused', 'error_type': type(exc).__name__}))
        raise SystemExit(1)
