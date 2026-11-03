#!/usr/bin/env python3
"""Blind diagnosis of a stopped linkage guard; never resolve it automatically."""
from collections import Counter
import json
from pathlib import Path
import sys

sys.dont_write_bytecode = True
import n5_sources
from n5_preparation import raw_scans, COUNTS
from n5_identity import identities, fingerprints, screening_closure
from cohorts_v2 import build_components
from source_capture import implementation_pins, plain
from source_census import (BASE, REPO, PREFIX, CONTROL_PINS, require, bounded_read,
                           control_evidence, decode, encoded, sha, isolated_network, _write_at)

REFUSAL = 'round11/evidence/source_capture_refusal.json'
REFUSAL_SHA = 'ce223cf5e756a9b7c6840d044f6cca017c3cd31348d78a0f3dde2a3185be5f9a'
MANIFEST = 'round4/data/train/manifest.jsonl'
OUTPUT = PREFIX + 'round11/preparation/overlap/proposal_overlap.json'
REASONS = {'protected_bytes_sha256', 'protected_rgb_sha256',
    'candidate_collision_bytes_sha256', 'candidate_collision_rgb_sha256', 'quarantined_screening_component'}
MANIFEST_KEYS = {'sample_id', 'dataset', 'split', 'group_id', 'original_component_id',
                 'recipe_sha256', 'image_path', 'image_sha256', 'rgb_sha256'}


def analyse(projection, audit, freeze, manifest, *, expected_counts):
    """Supplied authenticated identities only. Never read a target/portion/image."""
    scans = raw_scans(projection['raw_tables'])
    universe = set(scans)
    index, snapshot = projection['index'], projection['snapshot']
    require(set(index['original_components']) == set(index['recipe_sha256']) == universe,
            'complete_overlap_raw_universe_required')
    require(all(index['recipe_sha256'][dish] == scans[dish].recipe_hash for dish in universe),
            'overlap_raw_recipe_identity_changed')
    old_pixels = fingerprints(index['known_image_fingerprints'], universe)
    old_mapping, old_quarantine, _, _ = build_components(scans, old_pixels)
    require(old_mapping == index['original_components']
            and old_quarantine == set(snapshot['ambiguous_component_ids']), 'overlap_old_graph_changed')
    proposal = identities([row['dish_id'] for row in projection['train_entries']])
    pixels = fingerprints(projection['train_pixels'], universe)
    require(identities([row['dish_id'] for row in pixels]) == proposal,
            'complete_overlap_proposal_pixels_required')
    validation = identities(projection['cohort_proposal']['selected_dish_ids'])
    core = identities(snapshot['active_development_ids'])
    original_dev = identities(projection['cohort_proposal']['original_development_exposure_ids'])
    retired = identities(projection['cohort_proposal']['retired_validation_dish_ids']) | (original_dev - core)
    history = (identities(snapshot['historical_exposure_ids'])
        | identities(projection['registry']['exposed_dish_ids']) | identities(projection['registry']['local_dish_ids']))
    require(set(expected_counts) == set(COUNTS)
            and {key: len(value) for key, value in (('core', core), ('validation', validation),
                ('original_development', original_dev), ('training', proposal))} == expected_counts,
            'registered_overlap_populations_required')
    require(all(value <= universe for value in (validation, core, original_dev, retired, history, proposal)),
            'overlap_role_outside_universe')
    require(freeze.get('schema_version') == 1 and freeze.get('status') == 'accepted_external_training_frozen',
            'authenticated_accepted_training_freeze_required')
    source = projection['source_hashes']
    for field, slot in (('proposal_sha256', 'training_proposal'), ('private_audit_index_sha256', 'index')):
        require(audit.get(field) == freeze['binding'].get(field) == source[slot],
                'overlap_training_identity_binding_changed')
    require(audit.get('schema_version') == 1 and isinstance(audit.get('candidate_audit'), list),
            'complete_prior_quarantine_audit_required')
    fp = {row['dish_id']: row for row in pixels}
    candidates = {}
    for row in audit['candidate_audit']:
        dish = row['dish_id']
        require(dish in proposal and dish not in candidates, 'unique_complete_audit_candidates_required')
        require(all(row[key] == fp[dish][key] for key in ('bytes_sha256', 'rgb_sha256')),
                'prior_quarantine_pixels_changed')
        reasons = row['quarantine_reasons']
        require(isinstance(reasons, list) and all(isinstance(reason, str) and reason in REASONS for reason in reasons)
                and len(reasons) == len(set(reasons)), 'registered_prior_quarantine_reasons_required')
        candidates[dish] = {key: row[key] for key in ('dish_id', 'screening_component_id',
            'bytes_sha256', 'rgb_sha256', 'quarantine_reasons')}
    require(set(candidates) == proposal and audit.get('complete_candidate_count') == len(proposal),
            'complete_prior_quarantine_candidates_required')
    rows = [decode(line) for line in manifest.splitlines() if line]
    accepted = {}
    for row in rows:
        require(isinstance(row, dict) and set(row) == MANIFEST_KEYS
                and isinstance(row['sample_id'], str) and row['sample_id'].startswith('nutrition5k-')
                and row['dataset'] == 'nutrition5k' and row['split'] == 'train',
                'exact_training_identity_manifest_required')
        dish = row['sample_id'].removeprefix('nutrition5k-')
        require(dish in candidates and dish not in accepted, 'unique_accepted_proposal_identity_required')
        old = candidates[dish]
        require(not old['quarantine_reasons'] and row['group_id'] == old['screening_component_id']
                and row['image_sha256'] == old['bytes_sha256'] and row['rgb_sha256'] == old['rgb_sha256']
                and row['recipe_sha256'] == index['recipe_sha256'][dish]
                and row['original_component_id'] == index['original_components'][dish]
                and row['image_path'] == 'round4/data/train/images/' + old['bytes_sha256'] + '.png',
                'accepted_manifest_prior_audit_disagrees')
        accepted[dish] = row
    require(set(accepted) == {dish for dish, row in candidates.items() if not row['quarantine_reasons']},
            'accepted_manifest_not_exact_audit_acceptance')
    accepted_bytes = {row['image_sha256'] for row in accepted.values()}
    accepted_rgb = {row['rgb_sha256'] for row in accepted.values()}
    require(len(accepted) == len(accepted_bytes) == len(accepted_rgb), 'accepted_pixel_identity_collision')
    counts = {'accepted_images': len(accepted), 'accepted_groups': len({row['group_id'] for row in accepted.values()}),
              'quarantined_images': len(proposal) - len(accepted)}
    require(all(audit.get(key) == value == freeze.get(key) for key, value in counts.items()),
            'prior_acceptance_counts_changed')
    require(dict(Counter(reason for row in candidates.values() for reason in row['quarantine_reasons']))
            == audit.get('quarantine_reason_counts_overlapping'), 'prior_quarantine_reason_counts_changed')
    mapping, quarantine, _, _ = build_components(scans, old_pixels + pixels)
    screening = screening_closure(mapping, index['recipe_sha256'], old_pixels + pixels)
    val_groups = {screening[dish] for dish in validation}
    ambiguous_screening = {screening[dish] for dish in universe if mapping[dish] in quarantine}
    roles = {'history': history, 'core': core, 'retired': retired,
             'proposed_training': proposal, 'accepted_training': set(accepted)}
    intersections = {role: len(val_groups & {screening[dish] for dish in values}) for role, values in roles.items()}
    overlaps = []
    for dish in sorted(proposal):
        if screening[dish] not in val_groups:
            continue
        row = candidates[dish]
        admitted = (dish in accepted or row['bytes_sha256'] in accepted_bytes or row['rgb_sha256'] in accepted_rgb)
        classification = ('accepted_training_overlap_requires_resolution' if admitted else
            'preexisting_rejected_proposal_overlap' if row['quarantine_reasons'] else 'unresolved')
        overlaps.append({**row, 'new_screening_component_id': screening[dish], 'classification': classification})
    summary = {'scope': 'blind_prior_proposal_overlap_diagnostic_not_eligibility_or_API_exposure',
        'registered_training_proposals': len(proposal), **counts,
        'validation_component_intersections': intersections,
        'validation_ambiguous_raw_components': len({mapping[dish] for dish in validation} & quarantine),
        'validation_ambiguous_screening_components': len(val_groups & ambiguous_screening),
        'overlap_class_counts': dict(Counter(row['classification'] for row in overlaps)),
        'overlap_prior_reason_counts': dict(Counter(reason for row in overlaps for reason in row['quarantine_reasons'])),
        'original_linkage_guard_remains_stopped': True, 'actual_API_exposure_proven': False,
        'protected_dish_targets_interpreted': 0, 'candidate_targets_interpreted': 0,
        'sealed_validation_label_or_image_files_opened': 0,
        'validation_unchanged': True, 'grants_eligibility_download_or_inference': False,
        'new_samples_selected': 0, 'new_downloads': 0, 'api_calls': 0}
    return {'overlaps': overlaps, 'summary': summary}


def _diagnose_at(repo, base, *, controls=CONTROL_PINS, refusal_sha=REFUSAL_SHA,
                 n5_anchors=None, expected_counts=None):
    """Private fixture hooks only; no production CLI overrides."""
    require(base == repo / PREFIX.rstrip('/') and repo.is_absolute() and repo.resolve() == repo,
            'canonical_overlap_roots_required')
    control_hashes = control_evidence(base, controls)
    refusal_raw = bounded_read(base, REFUSAL)
    require(sha(refusal_raw) == refusal_sha, 'registered_capture_refusal_required')
    refusal = decode(refusal_raw)
    require(refusal.get('status') == 'mechanical_identity_capture_stopped_for_blind_linkage_resolution'
            and refusal.get('stop_code') == 'validation_linkage_requires_separate_resolution'
            and refusal.get('eligibility_or_inference_granted') is False, 'stopped_linkage_guard_required')
    implementations = {**implementation_pins(base), 'round11/proposal_overlap.py': sha(bounded_read(base, 'round11/proposal_overlap.py'))}
    projection, reader = n5_sources.load_identity_sources(repo, anchors=n5_anchors)
    audit = decode(reader.bound['training_audit'])
    freeze = decode(reader.bound['training_freeze'])
    raw = bounded_read(base, MANIFEST)
    require(sha(raw) == freeze['artifacts']['manifest.jsonl'], 'accepted_identity_manifest_hash_changed')
    value = analyse(projection, audit, freeze, raw, expected_counts=COUNTS if expected_counts is None else expected_counts)
    reader.revalidate()
    require(bounded_read(base, MANIFEST) == raw and bounded_read(base, REFUSAL) == refusal_raw
            and control_evidence(base, controls) == control_hashes
            and {**implementation_pins(base), 'round11/proposal_overlap.py': sha(bounded_read(base, 'round11/proposal_overlap.py'))}
                == implementations, 'overlap_diagnostic_sources_changed')
    return plain({**value, 'source_sha256': {**{n5_sources.PATHS[key]: value for key, value in reader.hashes.items()},
        PREFIX + MANIFEST: sha(raw)}, 'implementation_sha256': implementations,
        'control_sha256': control_hashes, 'refusal_sha256': refusal_sha})


def main():
    require(len(sys.argv) == 1, 'overlap_cli_overrides_refused')
    require(isolated_network(Path('/proc/self/net/dev').read_bytes()), 'isolated_network_namespace_required')
    output = REPO / OUTPUT
    require(output.resolve() == output and not output.exists(), 'fresh_overlap_output_required')
    value = _diagnose_at(REPO, BASE)
    _write_at(REPO, OUTPUT, value)
    print(json.dumps({**value['summary'], 'diagnostic_sha256': sha(encoded(value))}, sort_keys=True))


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print(json.dumps({'status': 'proposal_overlap_diagnostic_refused', 'error_type': type(exc).__name__}))
        raise SystemExit(1)
