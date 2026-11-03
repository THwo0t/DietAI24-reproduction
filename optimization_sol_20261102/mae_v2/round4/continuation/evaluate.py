#!/usr/bin/env python3
"""Separate, immutable development evaluation of the registered J continuation.

The new base must be completely sealed and externally trained before this
entry point opens pinned development labels. Reuse the reviewed score helpers
and calibration math verbatim; never create an old J completion or modify old
modules. Seal raw scores, then all calibrated records/audits, then selection.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import json
import os
from pathlib import Path
import re
import sys

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / 'src')]
from round4.src import score_dev as scorer, calibrate_j as calibration
from round4.src.artifacts import ArtifactStore, canonical, decode, fingerprint
from round4.continuation.integrity import policy as service_policy

SERVICE_PROTOCOL = 'round4/continuation/SERVICE_CONTINUATION_PROTOCOL.md'
REGISTRATION = 'round4/continuation/private_registration.json'
OLD_SNAPSHOT = 'round4/continuation/private_old_stage_snapshot.json'
OLD_INTENT = 'round4/runs/J/intent.json'
GALLERY_COMPLETION = 'round4/runs/J_gallery/completion.json'
BASE_OUTPUT = 'round4/runs/J_service_continuation'
BASE_INTENT = BASE_OUTPUT + '/intent.json'
BASE_COMPLETION = BASE_OUTPUT + '/completion.json'
RAW_OUTPUT = 'round4/scoring/J_service_continuation'
CAL_OUTPUT = 'round4/calibration/J_service_continuation'
SCORE_OUTPUT = 'round4/scoring/J_service_continuation_calibration'
SOURCES = ('round4/continuation/evaluate.py', 'round4/src/calibrate_j.py', *scorer.SOURCE_NAMES)
CONTINUATION_SOURCES = (
    'round4/continuation/provider.py', 'round4/continuation/runner.py',
    'round4/continuation/integrity.py', 'round4/continuation/tests/test_provider.py',
    'round4/continuation/tests/test_runner.py', 'round4/continuation/evaluate.py',
    'round4/continuation/tests/test_evaluate.py')
CANDIDATE = 'J_service_continuation'
SCOPE = 'development_not_independent_validation'

# Explicit aliases allow isolated synthetic fixtures without changing any
# original module. Production uses these original implementations directly.
Inputs = scorer.Inputs
PINNED_INPUTS = scorer.PINNED_INPUTS
summarize = scorer._summary
build_oof = calibration.build_oof
select_profile = calibration.select_profile


class EvaluationError(ValueError):
    """Fixed safe-code exception, without target values or sample identifiers."""


def require(condition, code):
    if not condition:
        raise EvaluationError(code)


def verified_base():
    from round4.continuation import runner
    return runner.base(verify_only=True)


def _verified_base():
    value = verified_base()
    require(isinstance(value, dict) and value.get('status') == 'base_verified'
            and type(value.get('n')) is int and value['n'] == 84
            and value.get('provider_constructed') is False
            and value.get('validation_opened') is False,
            'complete_zero_provider_continuation_verification_required')
    records = value.get('records')
    require(isinstance(records, dict) and len(records) == 84, 'continuation_requires_all_84_records')
    require(isinstance(value.get('binding'), dict)
            and isinstance(value.get('completion_sha256'), str)
            and re.fullmatch('[0-9a-f]{64}', value['completion_sha256']),
            'verified_continuation_binding_and_completion_required')
    return decode(canonical({key: value[key] for key in ('records', 'binding', 'completion_sha256')}))


def _external_binding(reader, verified):
    records = verified['records']
    intent = decode(reader.read(BASE_INTENT))
    complete = decode(reader.read(BASE_COMPLETION))
    binding = intent.get('binding', {})
    require(binding == verified['binding']
            and reader.hashes[BASE_COMPLETION] == verified['completion_sha256']
            and intent.get('binding_sha256') == fingerprint(binding)
            and intent.get('expected_records') == sorted(records)
            and intent.get('expected_records_sha256') == fingerprint(sorted(records))
            and complete.get('run_binding_sha256') == fingerprint(intent)
            and complete.get('record_count') == 84,
            'continuation_external_seal_binding_mismatch')
    old_intent = decode(reader.read(OLD_INTENT))
    old_binding = old_intent.get('binding', {})
    service = binding.get('service_continuation', {})
    require(isinstance(service, dict)
            and {key: value for key, value in binding.items() if key != 'service_continuation'} == old_binding
            and old_intent.get('binding_sha256') == fingerprint(old_binding)
            and old_intent.get('expected_records') == sorted(records)
            and old_intent.get('expected_records_sha256') == fingerprint(sorted(records))
            and service.get('original_base_intent_sha256') == reader.hashes[OLD_INTENT],
            'original_scientific_binding_must_be_preserved')
    require(binding.get('phase') == 'development_base'
            and binding.get('method_config') == scorer.run_base.context.METHOD_CONFIG
            and binding.get('query_count') == 84 and binding.get('query_groups') == 78,
            'registered_external_only_base_required')
    bound = binding.get('input_sha256', {})
    require(isinstance(bound, dict) and scorer.LABELS not in bound and scorer.PRESERVED not in bound
            and bound.get(scorer.MANIFEST) == PINNED_INPUTS[scorer.MANIFEST]
            and all(not name.endswith('labels.json') or name.startswith('round4/data/train/') for name in bound),
            'development_labels_must_not_bind_base_inference')
    freeze = decode(reader.read(calibration.TRAIN_FREEZE))
    require(freeze.get('status') == 'accepted_external_training_frozen'
            and binding.get('training_freeze_sha256') == reader.hashes[calibration.TRAIN_FREEZE]
            and bound.get(calibration.TRAIN_FREEZE) == reader.hashes[calibration.TRAIN_FREEZE]
            and binding.get('training_exclusion_binding') == freeze.get('binding')
            and bool(freeze.get('binding')), 'independent_training_freeze_mismatch')
    reader.read(GALLERY_COMPLETION)
    require(binding.get('gallery_completion_sha256') == reader.hashes[GALLERY_COMPLETION],
            'original_gallery_completion_changed')
    registration = decode(reader.read(REGISTRATION))
    reader.read(OLD_SNAPSHOT)
    require(service.get('registration_sha256') == reader.hashes[REGISTRATION]
            and service.get('protocol_sha256') == reader.hashes[SERVICE_PROTOCOL]
            and service.get('old_stage_snapshot_sha256') == reader.hashes[OLD_SNAPSHOT],
            'registered_service_departure_required')
    sources = service.get('source_sha256', {})
    require(isinstance(sources, dict) and set(sources) == set(CONTINUATION_SOURCES)
            and sources == registration.get('continuation_source_sha256'),
            'registered_continuation_source_inventory_required')
    for name, expected in sources.items():
        reader.read(name)
        require(reader.hashes[name] == expected, 'registered_continuation_source_changed')
    policy = service.get('policy', {})
    exception = policy.get('exception', {}) if isinstance(policy, dict) else {}
    require(isinstance(exception, dict) and set(exception) == {'role', 'request_hash', 'max_total_attempts'}
            and exception.get('role') == 'chat' and exception.get('max_total_attempts') == 4
            and isinstance(exception.get('request_hash'), str)
            and re.fullmatch('[0-9a-f]{64}', exception['request_hash'])
            and policy == service_policy(exception['request_hash']),
            'single_registered_service_policy_required')
    return {'base_binding_sha256': fingerprint(binding),
        'training_freeze_sha256': reader.hashes[calibration.TRAIN_FREEZE],
        'training_exclusion_binding_sha256': fingerprint(freeze['binding']),
        'gallery_completion_sha256': reader.hashes[GALLERY_COMPLETION],
        'original_base_intent_sha256': reader.hashes[OLD_INTENT],
        'service_continuation': deepcopy(service)}


def _seal(directory, binding, records, reader):
    require(directory in {RAW_OUTPUT, CAL_OUTPUT, SCORE_OUTPUT}, 'new_continuation_output_required')
    store = ArtifactStore(ROOT / directory, binding, list(records),
                          verify_sources=reader.unchanged, root=ROOT / 'round4')
    complete = (ROOT / directory / 'completion.json').exists()
    if complete:
        require(fingerprint(store.verify_completed()) == fingerprint(records),
                'completed_continuation_recomputation_changed')
    else:
        store.finalize(records)
    # A published marker is not sufficient: verify the actual independent seal.
    require(fingerprint(store.verify_completed()) == fingerprint(records),
            'continuation_output_seal_mismatch')
    return complete


def _summary(rows, labels, n5, predictions, asa, *, calibrated=False):
    value = summarize(rows, labels, n5, predictions, asa)
    value.update(candidate=CANDIDATE + ('_aggregate_calibration' if calibrated else ''),
                 service_continuation=True, scope=SCOPE, calibration_applied=calibrated)
    return value


def run():
    verified = _verified_base()  # No label reader exists before the full base gate.
    records = verified['records']
    reader = Inputs(ROOT)
    reader.read(calibration.PROTOCOL)
    require(reader.hashes[calibration.PROTOCOL] == calibration.PROTOCOL_SHA256,
            'registered_calibration_protocol_changed')
    reader.read(SERVICE_PROTOCOL)
    for name in SOURCES:
        reader.read(name)
    external = _external_binding(reader, verified)
    rows = scorer._manifest(reader.read(scorer.MANIFEST))
    n5, raw_predictions, asa = scorer._predictions(
        rows, records, decode(reader.read(scorer.PRESERVED)))
    indexed = calibration._rows(n5)
    calibration._records(indexed, records)
    labels = decode(reader.read(scorer.LABELS))
    require(isinstance(labels, dict) and set(labels) == {row['sample_id'] for row in rows},
            'registered_development_label_population_required')
    scorer.metrics._training(rows, labels)
    reader.unchanged()

    raw = _summary(rows, labels, n5, raw_predictions, asa)
    require(fingerprint(_verified_base()) == fingerprint(verified), 'continuation_changed_during_raw_scoring')
    reader.unchanged()
    binding = {'schema_version': 1, 'candidate': CANDIDATE, 'service_continuation': True,
        'phase': 'service_continuation_raw_scoring', 'scope': SCOPE, 'validation_opened': False,
        'calibration_applied': False, 'bootstrap': scorer.BOOTSTRAP, 'seed': scorer.SEED,
        'base_completion_sha256': reader.hashes[BASE_COMPLETION],
        'base_records_sha256': fingerprint(records), 'external_training_proof': external,
        'source_sha256': {name: reader.hashes[name] for name in SOURCES},
        'input_sha256': dict(reader.hashes)}
    was_raw = _seal(RAW_OUTPUT, binding, {'metrics': raw}, reader)
    reader.read(RAW_OUTPUT + '/completion.json')

    derived = build_oof(n5, {sid: labels[sid] for sid in indexed}, records)
    require(fingerprint(_verified_base()) == fingerprint(verified), 'continuation_changed_during_calibration')
    reader.unchanged()
    cal_binding = {**binding, 'phase': 'service_continuation_calibration_oof',
        'calibration_applied': True, 'method': deepcopy(calibration.METHOD),
        'raw_scoring_completion_sha256': reader.hashes[RAW_OUTPUT + '/completion.json'],
        'input_sha256': dict(reader.hashes)}
    was_cal = _seal(CAL_OUTPUT, cal_binding,
                    {**derived['records'], 'fit_audit': derived['fit_audit']}, reader)
    reader.read(CAL_OUTPUT + '/completion.json')

    calibrated = _summary(rows, labels, n5,
        [derived['records'][row['sample_id']] for row in n5], asa, calibrated=True)
    selection = select_profile(raw['joint_metrics_with_preserved_asa'],
                               calibrated['joint_metrics_with_preserved_asa'])
    summary = {'candidate': CANDIDATE + '_aggregate_calibration', 'service_continuation': True,
        'scope': SCOPE, 'validation_opened': False, 'calibration_applied': True,
        'raw': raw, 'calibrated': calibrated, 'selection': selection,
        'bootstrap_scope': 'conditional_on_fixed_oof_predictions_no_refitting_or_selection_uncertainty',
        'selected_profile_calibration_applied': selection['selected_profile'] == 'calibrated',
        'future_selected_profile_factors': (derived['fit_audit']['final_training_fit']['applied_factors']
            if selection['selected_profile'] == 'calibrated' else dict.fromkeys(calibration.KEYS, 1.0)),
        'future_factor_usage': 'unseen_inputs_only_never_reported_oof_predictions',
        'service_continuation_proof': external}
    require(fingerprint(_verified_base()) == fingerprint(verified),
            'continuation_changed_during_calibrated_scoring')
    reader.unchanged()
    score_binding = {**cal_binding, 'phase': 'service_continuation_calibration_scoring',
        'calibration_completion_sha256': reader.hashes[CAL_OUTPUT + '/completion.json'],
        'input_sha256': dict(reader.hashes)}
    was_scored = _seal(SCORE_OUTPUT, score_binding, {'metrics': summary}, reader)
    return {'status': 'continuation_evaluation_verified' if was_raw and was_cal and was_scored
            else 'continuation_evaluation_complete', 'metrics': summary,
        'provider_constructed': False, 'validation_opened': False,
        'raw_scoring_output': RAW_OUTPUT, 'calibrated_output': CAL_OUTPUT, 'scoring_output': SCORE_OUTPUT}


def main(argv=None):
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args(argv)
    try:
        result = run()
        print(json.dumps({key: value for key, value in result.items() if key != 'metrics'} |
            {'scope': SCOPE, 'service_continuation': True,
             'selected_profile': result['metrics']['selection']['selected_profile']}, sort_keys=True))
        return 0
    except Exception as error:
        print(json.dumps({'status': 'stopped', 'error_type': type(error).__name__}, sort_keys=True))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
