#!/usr/bin/env python3
"""Bounded mechanical source role audit; no eligibility or exposure closure."""
from copy import deepcopy
import json
from pathlib import Path
import sys

import asa_phase_graph
import asa_role_sources
import development_identity
import n5_sources
import source_inventory_capture as inventory
from source_census import (BASE, REPO, PREFIX, CONTROL_PINS, bounded_read,
    control_evidence, decode, encoded, sha, require, isolated_network, _write_at)

# Registered only after the separate mechanical inventory has a reviewed receipt.
INVENTORY_SHA256 = '203bbb7c9f26f2bf6a4bf3846151fe068c3399f61efbb3f1a0b41c830dc9892d'
INPUT = inventory.OUTPUT
OUTPUT = PREFIX + 'round11/preparation/source_role_audit/source_role_audit.json'
IMPLEMENTATION_FILES = tuple(dict.fromkeys(inventory.IMPLEMENTATION_FILES + tuple(
    'round11/' + name + '.py' for name in (
        'source_role_audit', 'asa_role_sources', 'asa_phase_graph'))))
FALSE_FLAGS = ('source_association_complete', 'actual_api_exposure_complete',
    'candidate_eligibility_evaluated', 'grants_sampling_download_or_inference',
    'fresh_O_store_replay', 'food_visual_analysis_performed')
ZERO_FLAGS = ('new_samples_selected', 'new_downloads', 'api_calls',
    'protected_dish_targets_interpreted', 'candidate_targets_interpreted',
    'sealed_label_files_opened')


def implementation_pins(base):
    return {p: sha(bounded_read(base, p)) for p in IMPLEMENTATION_FILES}


def _non_grants(value, *, complete=False):
    for key in FALSE_FLAGS:
        require((key in value or not complete) and value.get(key, False) is False,
                'audit_false_grant_required')
    for key in ZERO_FLAGS:
        require((key in value or not complete) and type(value.get(key, 0)) is int
                and value.get(key, 0) == 0, 'audit_zero_action_required')


def _audit_at(repo, base, *, expected_sha, controls=CONTROL_PINS):
    """Private synthetic fixture hook. Production supplies only fixed constants."""
    repo, base = Path(repo), Path(base)
    require(repo.is_absolute() and repo.resolve() == repo
            and base == repo / PREFIX.rstrip('/'), 'canonical_role_audit_roots_required')
    require(isinstance(expected_sha, str) and n5_sources.HEX.fullmatch(expected_sha),
            'registered_inventory_receipt_required')
    raw = bounded_read(repo, INPUT)
    require(sha(raw) == expected_sha, 'inventory_receipt_hash_changed')
    held = decode(raw)
    require(held['schema_version'] == 1 and held['status'] ==
            'mechanical_source_inventory_captured_role_closure_pending',
            'completed_mechanical_inventory_required')
    _non_grants(held, complete=True)
    require(held['potential_input_coverage_complete'] is False
            and held['original_linkage_guard_remains_stopped'] is True,
            'inventory_unresolved_guards_required')
    code = implementation_pins(base)
    capture_code = inventory.implementation_pins(base)
    require(held['implementation_sha256'] == capture_code, 'inventory_implementation_changed')
    control = control_evidence(base, controls)
    require(held['control_sha256'] == control, 'inventory_controls_changed')
    n5, n5_reader = n5_sources.load_identity_sources(repo)
    dev, dev_reader = development_identity._load_development_identity(
        repo, n5_sources.ANCHORS['development_seal'])
    require(held['n5_source_sha256'] == n5['source_hashes'], 'inventory_n5_sources_changed')
    require(held['development_identity'] == dev, 'inventory_development_identity_changed')
    asa = held['asa_mechanical_sources']; legacy = held['legacy_inputs_private']
    def revalidate():
        require(bounded_read(repo, INPUT) == raw, 'held_inventory_changed')
        n5_reader.revalidate(); dev_reader.revalidate()
        inventory.verify_asa_bindings(repo, asa)
        inventory.verify_legacy_bindings(repo.parent, legacy)
        require(control_evidence(base, controls) == control
                and implementation_pins(base) == code, 'role_audit_bindings_changed')
    revalidate()
    roles = asa_role_sources._load_at(repo, asa, dev, legacy)
    _non_grants(roles)
    require(roles['role_inventory_complete'] is False
            and roles['source_association_complete'] is False,
            'unresolved_role_inventory_required')
    revalidate()
    graph, aggregate = asa_phase_graph.build_phase_graph(
        deepcopy(asa), deepcopy(roles), deepcopy(held['local_content_private']))
    _non_grants(graph); _non_grants(aggregate)
    revalidate()
    require(asa_role_sources._load_at(repo, asa, dev, legacy) == roles,
            'asa_role_sources_changed')
    revalidate()
    flags = {**{k: False for k in FALSE_FLAGS}, **{k: 0 for k in ZERO_FLAGS},
        'role_inventory_complete': False, 'potential_input_coverage_complete': False,
        'original_linkage_guard_remains_stopped': True}
    # Whitelist ID-free counters; never print source rows, paths, IDs or stop payloads.
    counters = ('old_core_fold_bridge_components', 'core_validation_intersection_components',
        'merged_old_group_components', 'unverified_original_image_bindings',
        'local_attachment_count', 'unmatched_local_potential_input_count')
    counts = {}
    for key in counters:
        require(type(aggregate[key]) is int and aggregate[key] >= 0, 'aggregate_count_required')
        counts[key] = aggregate[key]
    summary = {'status': 'mechanical_source_role_audit_requires_disposition',
        'asa': counts, 'unresolved_source_pin_count': len(roles['unresolved_sources']),
        'caller_registration_complete': False, 'training_retired_roles_proven': False,
        **flags}
    value = {'schema_version': 1, **summary, 'inventory_sha256': expected_sha,
        'implementation_sha256': code, 'control_sha256': control,
        'asa_role_sources_private': roles, 'asa_phase_graph_private': graph,
        'asa_summary_private': aggregate,
        'pending': ['F_to_O_caller_registration', 'source_backed_training_retired_roles',
                    'full_source_association_and_exposure_disposition']}
    # Role projections contain sets; reuse the capture's deterministic conversion.
    return inventory.plain(value), summary


def main():
    require(len(sys.argv) == 1, 'role_audit_cli_overrides_refused')
    require(isolated_network(Path('/proc/self/net/dev').read_bytes()),
            'isolated_network_namespace_required')
    output = REPO / OUTPUT
    require(output.resolve() == output and not output.exists(), 'fresh_role_audit_output_required')
    value, summary = _audit_at(REPO, BASE, expected_sha=INVENTORY_SHA256)
    _write_at(REPO, OUTPUT, value)
    print(json.dumps({**summary, 'private_role_audit_sha256': sha(encoded(value))}, sort_keys=True))


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print(json.dumps({'status': 'source_role_audit_refused', 'error_type': type(exc).__name__}))
        raise SystemExit(1)
