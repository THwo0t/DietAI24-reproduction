#!/usr/bin/env python3
"""P-C1 mechanical identity capture only; no candidate target/eligibility use.

The first reviewed path census precedes this source capture. Exact historical
API exposure and full source-association closure remain unresolved; this entry
therefore cannot select, download, freeze cohorts or construct a predictor.
"""
import json
from pathlib import Path
import sys

import PIL
import openpyxl

sys.dont_write_bytecode = True
import asa_archive
from asa_workbook import capture_workbook
import n5_sources
from n5_preparation import raw_scans, COUNTS
from n5_identity import reconcile
from source_census import (BASE, REPO, PREFIX, CONTROL_PINS, require, bounded_read,
                           control_evidence, decode, encoded, sha, isolated_network,
                           _write_at)

CENSUS = PREFIX + 'round11/preparation/inventory/source_census.json'
CENSUS_SHA = '46a40f27b9da663b93611523677ed3ddf038f8bc91111c80c250489284b5db04'
OUTPUT = PREFIX + 'round11/preparation/capture/source_capture.json'
V1_PROTOCOL = 'optimization_sol_20261102/data/cohorts/protocol.json'
ASA_SOURCES = (
    'ASA24/Asa24PortionImages.zip', 'ASA24/ASA24_ImageMetadata.xlsx',
    'NHANES/top_1000_frequent_select_foods.csv',
    'FNDDS/2019-2020 FNDDS - Foods and Beverages.csv', 'FoodWeights.csv',
)
IMPLEMENTATION_FILES = tuple('round11/' + name + '.py' for name in (
    'source_capture', 'source_census', 'n5_sources', 'n5_preparation', 'n5_identity',
    'n5_pool', 'asa_archive', 'asa_workbook', 'asa_content_identity', 'asa_identity',
    'qualification')) + ('src/cohorts_v2.py',)


def implementation_pins(base):
    return {relative: sha(bounded_read(base, relative)) for relative in IMPLEMENTATION_FILES}


def pin_for(mapping, repo, relative):
    """Choose a fixed source only; never follow arbitrary inventory paths."""
    values = {mapping[key] for key in (relative, str(repo / relative)) if key in mapping}
    require(len(values) == 1, 'unambiguous_registered_capture_pin_required')
    value = values.pop()
    require(isinstance(value, str) and n5_sources.HEX.fullmatch(value), 'valid_capture_pin_required')
    return value


def plain(value):
    if isinstance(value, dict):
        return {key: plain(child) for key, child in value.items()}
    if isinstance(value, (set, tuple, list)):
        values = sorted(value) if isinstance(value, set) else value
        return [plain(child) for child in values]
    return value


def _capture_at(repo, base, *, controls=CONTROL_PINS, census_sha=CENSUS_SHA,
                n5_anchors=None, expected_counts=None):
    """Private fixture hooks. Production calls with fixed defaults only."""
    repo, base = Path(repo), Path(base)
    require(repo.is_absolute() and repo.resolve() == repo and base == repo / PREFIX.rstrip('/'),
            'canonical_capture_roots_required')
    implementations = implementation_pins(base)
    controls_seen = control_evidence(base, controls)
    census_raw = bounded_read(repo, CENSUS)
    require(sha(census_raw) == census_sha, 'registered_path_census_required')
    census = decode(census_raw)
    require(census.get('status') == 'path_census_complete_not_exposure_closure'
            and census.get('grants_sampling_download_or_inference') is False
            and census.get('research_file_bodies_opened') == 0
            and census.get('control_sha256') == controls_seen,
            'correct_path_only_census_required')
    # No complete-exposure claim is inferred from a path census. These fixed
    # sources are opened only for mechanical identity/duplicate associations.
    n5, reader = n5_sources.load_identity_sources(repo, anchors=n5_anchors)
    scans = raw_scans(n5['raw_tables'])
    identities, n5_summary = reconcile(scans, n5['index'], n5['snapshot'],
        n5['cohort_proposal'], n5['registry'], n5['train_entries'], n5['train_pixels'],
        expected_counts=COUNTS if expected_counts is None else expected_counts)
    # Available numerical dish targets are intentionally not interpreted.
    # Ingredient masses are used mechanically only by the full linkage graph.
    snapshot = n5_sources.decode(reader.bound['original_snapshot'])
    protocol_pin = pin_for(snapshot['source_sha256'], repo, V1_PROTOCOL)
    protocol_raw = bounded_read(repo, V1_PROTOCOL)
    require(sha(protocol_raw) == protocol_pin, 'registered_v1_protocol_changed')
    protocol = decode(protocol_raw)
    asa_pins = {relative: pin_for(protocol['source_sha256'], repo, relative) for relative in ASA_SOURCES}
    workbook_raw = bounded_read(repo, ASA_SOURCES[1])
    _, asa, asa_summary = capture_workbook(workbook_raw, asa_pins[ASA_SOURCES[1]])
    archive, archive_summary = asa_archive.capture_archive(repo, asa_pins[ASA_SOURCES[0]])
    reader.revalidate()
    require(bounded_read(repo, V1_PROTOCOL) == protocol_raw
            and bounded_read(repo, ASA_SOURCES[1]) == workbook_raw
            and bounded_read(repo, CENSUS) == census_raw
            and control_evidence(base, controls) == controls_seen
            and implementation_pins(base) == implementations,
            'capture_sources_changed')
    # Retain identity-only results. No raw source tables, food nutrient data,
    # dish targets, legal portion values or deferred workbook fields are saved.
    identities.pop('allowed_ids')
    value = plain({
        'schema_version': 1,
        'status': 'mechanical_identity_sources_captured_not_eligibility',
        'source_sha256': {**{n5_sources.PATHS[slot]: value for slot, value in reader.hashes.items()},
            V1_PROTOCOL: protocol_pin, ASA_SOURCES[0]: asa_pins[ASA_SOURCES[0]],
            ASA_SOURCES[1]: asa_pins[ASA_SOURCES[1]]},
        'control_sha256': controls_seen,
        'implementation_sha256': implementations,
        'decoder_runtime': {'python': sys.version.split()[0], 'implementation': sys.implementation.name,
            'Pillow': PIL.__version__, 'openpyxl': openpyxl.__version__,
            'asa_exact_rgb_rule': asa_archive.ALGORITHM,
            'n5_exact_rgb_rule': 'dimension_string_nul_decoded_RGB_cohorts_v2_source_pinned'},
        'census_sha256': census_sha,
        'registered_asa_sources_sha256': asa_pins,
        'n5_identity_state': identities,
        'asa_workbook_identity': asa,
        'asa_archive_identity': archive,
        'candidate_targets_interpreted': 0,
        'protected_dish_targets_interpreted': 0,
        'ingredient_masses_used_only_for_blind_linkage': True,
        'sealed_validation_label_or_image_files_opened': 0,
        'asa_source_archive_pixels_mechanically_fingerprinted': True,
        'source_association_complete': False,
        'latest_exposure_completeness_proven': False,
        'candidate_eligibility_evaluated': False,
        'new_samples_selected': 0, 'new_downloads': 0, 'api_calls': 0,
        'grants_sampling_download_or_inference': False,
    })
    summary = {
        'status': value['status'],
        'sources_captured': len(value['source_sha256']),
        'implementation_files_bound': len(implementations),
        'decoder_runtime': value['decoder_runtime'],
        'n5_supplied_identity_summary': n5_summary,
        'asa_workbook': asa_summary, 'asa_archive': archive_summary,
        **{key: value[key] for key in ('candidate_targets_interpreted', 'protected_dish_targets_interpreted',
            'sealed_validation_label_or_image_files_opened', 'source_association_complete',
            'latest_exposure_completeness_proven', 'candidate_eligibility_evaluated',
            'new_samples_selected', 'new_downloads', 'api_calls', 'grants_sampling_download_or_inference')},
    }
    return value, summary


def main():
    require(len(sys.argv) == 1, 'capture_cli_overrides_refused')
    require(isolated_network(Path('/proc/self/net/dev').read_bytes()), 'isolated_network_namespace_required')
    output = REPO / OUTPUT
    require(output.resolve() == output and not output.exists(), 'fresh_capture_output_required')
    value, summary = _capture_at(REPO, BASE)
    _write_at(REPO, OUTPUT, value)
    print(json.dumps({**summary, 'capture_sha256': sha(encoded(value))}, sort_keys=True))


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print(json.dumps({'status': 'source_capture_refused', 'error_type': type(exc).__name__}))
        raise SystemExit(1)
