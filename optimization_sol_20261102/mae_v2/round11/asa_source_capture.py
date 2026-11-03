"""Separate mechanical ASA supplement after the original N5 guard stopped.

No original capture replay, graph repair, eligibility, targets or writes.
Only authenticated fixed protocol paths supply pins; inventories are not followed.
"""
from pathlib import Path
import sys
import PIL
import openpyxl
import asa_archive
from asa_workbook import capture_workbook
import n5_sources
from source_capture import ASA_SOURCES, CENSUS, CENSUS_SHA, pin_for, plain
from source_census import (BASE, REPO, PREFIX, CONTROL_PINS, bounded_read,
                           control_evidence, decode, sha, require)

PROTOCOLS = ('optimization_sol_20261102/data/cohorts/protocol.json',
             'optimization_sol_20261102/data/freeze/protocol.json')
REFUSAL = 'round11/evidence/source_capture_refusal.json'
REFUSAL_SHA = 'ce223cf5e756a9b7c6840d044f6cca017c3cd31348d78a0f3dde2a3185be5f9a'
DIAGNOSTIC = 'round11/evidence/proposal_overlap.json'
DIAGNOSTIC_SHA = '45f1f30b0b1286f891f93b28b1c99d7d0ffd522255b5c2f731c6efdf62ad6203'
IMPLEMENTATION_FILES = tuple('round11/' + name + '.py' for name in (
    'asa_source_capture', 'source_capture', 'source_census', 'n5_sources',
    'asa_archive', 'asa_workbook', 'asa_content_identity', 'asa_identity', 'qualification'))


def implementation_pins(base):
    return {name: sha(bounded_read(base, name)) for name in IMPLEMENTATION_FILES}


def _capture_at(repo, base, *, controls=CONTROL_PINS, census_sha=CENSUS_SHA,
                snapshot_sha=n5_sources.ANCHORS['original_snapshot'],
                refusal_sha=REFUSAL_SHA, diagnostic_sha=DIAGNOSTIC_SHA):
    """Private synthetic fixture hook. Public capture has no overrides."""
    repo, base = Path(repo), Path(base)
    require(repo.is_absolute() and repo.resolve() == repo
            and base == repo / PREFIX.rstrip('/'), 'canonical_capture_roots_required')
    implementations = implementation_pins(base)
    controls_seen = control_evidence(base, controls)
    bound = {}
    def bind(root, relative, expected):
        require(isinstance(expected, str) and n5_sources.HEX.fullmatch(expected),
                'registered_source_hash_required')
        raw = bounded_read(root, relative)
        require(sha(raw) == expected, 'asa_capture_source_hash_changed')
        bound[(root, relative)] = raw
        return decode(raw)
    census = bind(repo, CENSUS, census_sha)
    require(census.get('status') == 'path_census_complete_not_exposure_closure'
            and census.get('research_file_bodies_opened') == 0
            and census.get('grants_sampling_download_or_inference') is False
            and census.get('control_sha256') == controls_seen,
            'correct_path_only_census_required')
    refusal = bind(base, REFUSAL, refusal_sha)
    require(refusal.get('status') == 'mechanical_identity_capture_stopped_for_blind_linkage_resolution'
            and refusal.get('stop_code') == 'validation_linkage_requires_separate_resolution'
            and refusal.get('eligibility_or_inference_granted') is False
            and refusal.get('completed_capture_artifact') is False
            and refusal.get('asa_source_archive_opened') is False,
            'original_stopped_capture_required')
    diagnostic = bind(base, DIAGNOSTIC, diagnostic_sha)
    require(diagnostic.get('original_linkage_guard_remains_stopped') is True
            and diagnostic.get('grants_eligibility_download_or_inference') is False
            and diagnostic.get('actual_API_exposure_proven') is False
            and diagnostic.get('api_calls') == 0,
            'stopped_diagnostic_aggregate_required')
    snapshot = bind(repo, n5_sources.PATHS['original_snapshot'], snapshot_sha)
    mapping = snapshot['source_sha256']
    merged = {relative: set() for relative in ASA_SOURCES}
    protocol_hashes = {}
    # The cohort protocol is mandatory. The fixed freeze protocol is read only
    # when the authenticated snapshot registers it; no arbitrary path is read.
    for index, relative in enumerate(PROTOCOLS):
        present = any(key in mapping for key in (relative, str(repo / relative)))
        require(index != 0 or present, 'registered_cohort_protocol_required')
        if not present:
            continue
        expected = pin_for(mapping, repo, relative)
        protocol = bind(repo, relative, expected)
        protocol_hashes[relative] = expected
        sources = protocol['source_sha256']
        for name in ASA_SOURCES:
            if any(key in sources for key in (name, str(repo / name))):
                merged[name].add(pin_for(sources, repo, name))
    top1000 = ASA_SOURCES[2]
    require(all(len(values) == 1 for name, values in merged.items() if name != top1000)
            and len(merged[top1000]) <= 1, 'complete_consistent_fixed_asa_pins_required')
    # This source was not necessarily part of either inherited protocol. Bind
    # its fixed-path bytes prospectively without parsing codes or eligibility.
    top1000_raw = bounded_read(repo, top1000)
    top1000_pin = sha(top1000_raw)
    require(not merged[top1000] or merged[top1000] == {top1000_pin},
            'inherited_top1000_source_hash_changed')
    bound[(repo, top1000)] = top1000_raw
    pins = {name: next(iter(values)) for name, values in merged.items() if name != top1000}
    pins[top1000] = top1000_pin
    origins = {name: 'inherited_registered_protocol' for name in pins}
    origins[top1000] = ('inherited_registered_protocol' if merged[top1000]
                       else 'prospective_fixed_source_capture')
    workbook_raw = bounded_read(repo, ASA_SOURCES[1])
    _, workbook, workbook_summary = capture_workbook(workbook_raw, pins[ASA_SOURCES[1]])
    bound[(repo, ASA_SOURCES[1])] = workbook_raw
    archive, archive_summary = asa_archive.capture_archive(repo, pins[ASA_SOURCES[0]])
    require(all(bounded_read(root, name) == raw for (root, name), raw in bound.items())
            and control_evidence(base, controls) == controls_seen
            and implementation_pins(base) == implementations, 'asa_capture_sources_changed')
    flags = {'original_linkage_guard_remains_stopped': True,
        'previous_completed_O_recovery_consumed': True, 'fresh_O_store_replay': False,
        'source_association_complete': False, 'latest_exposure_completeness_proven': False,
        'candidate_eligibility_evaluated': False, 'candidate_targets_interpreted': 0,
        'protected_dish_targets_interpreted': 0, 'sealed_validation_label_or_image_files_opened': 0,
        'new_samples_selected': 0, 'new_downloads': 0, 'api_calls': 0,
        'grants_sampling_download_or_inference': False}
    runtime = {'python': sys.version.split()[0], 'implementation': sys.implementation.name,
        'Pillow': PIL.__version__, 'openpyxl': openpyxl.__version__,
        'asa_exact_rgb_rule': asa_archive.ALGORITHM}
    common = {'status': 'asa_mechanical_identity_supplement_not_eligibility',
        'decoder_runtime': runtime, **flags}
    private = plain({'schema_version': 1, **common,
        'control_sha256': controls_seen, 'implementation_sha256': implementations,
        'census_sha256': census_sha, 'original_capture_refusal_sha256': refusal_sha,
        'diagnostic_aggregate_sha256': diagnostic_sha,
        'source_sha256': {n5_sources.PATHS['original_snapshot']: snapshot_sha,
            **protocol_hashes, ASA_SOURCES[2]: top1000_pin, ASA_SOURCES[0]: pins[ASA_SOURCES[0]], ASA_SOURCES[1]: pins[ASA_SOURCES[1]]},
        'registered_asa_sources_sha256': pins, 'asa_source_pin_origin': origins,
        'asa_workbook_identity': workbook, 'asa_archive_identity': archive})
    return private, {**common, 'asa_workbook': workbook_summary, 'asa_archive': archive_summary,
        'registered_asa_sources': len(pins), 'implementation_files_bound': len(implementations)}


def capture():
    """Fixed-root, fixed-pin production API; returns private data and ID-free counts."""
    return _capture_at(REPO, BASE)
