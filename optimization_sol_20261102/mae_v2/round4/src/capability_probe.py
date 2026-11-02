"""Fixed training-only 13-image rerank capability check; default is offline.

The accepted train manifest's first 13 sample IDs (lexical order) are immutable
probe inputs. No target/ingredient/catalog is consumed. The training verifier may
hash private training artifacts, but their label values never enter this module.
Format failure after the one allowed repair is sealed and remains a blocker.
ProviderStop propagates with durable stage intent/provider attempt state intact.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import io
import json
import os
from pathlib import Path
import re
import sys

from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'src'))
from opt_pipeline import ContractError, encode_image
from opt_provider import Provider, ProviderStop, fingerprint as request_value_hash
from round4.src.artifacts import ArtifactStore, decode, fingerprint
from round4.src.trace_provider import TraceProvider, NAMESPACE
from round4.src.image_guard import ImageGuard, payload_hash
from round4.src import train_data, vision_stages as vision

TRAIN = 'round4/data/train'
RUN = 'round4/runs/capability'
PROVIDER_LOGS = 'round4/provider/capability'
RECORD = 'thirteen_image_rerank'
STAGE = 'fixed_training_thirteen_image_rerank'
SOURCE_NAMES = ('src/opt_provider.py', 'src/opt_pipeline.py',
    'round3/src/dev_ingredients.py', 'round4/src/train_data.py',
    'round4/src/vision_stages.py', 'round4/src/trace_provider.py',
    'round4/src/artifacts.py', 'round4/src/image_guard.py',
    'round4/src/capability_probe.py')
POLICY = {'version': 'external-gallery-capability-r4.1',
    'selection': 'first13_accepted_train_sample_ids_in_lexical_order',
    'query_images': 1, 'candidate_images': 12, 'namespace': NAMESPACE,
    'completion_tokens': 4096, 'format_repairs': 1,
    'contract_failure': 'seal_failed_completion_and_stop_without_reselection',
    'provider_exception': 'propagate_preserving_exact_payload_attempt_budget',
    'labels_consumed': False, 'validation_opened': False}


class CapabilityError(RuntimeError):
    """Fixed safe error code; no provider body or image identifiers."""


def require(condition, code):
    if not condition:
        raise CapabilityError(code)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _state(base, verify_train=None):
    base = Path(base).resolve()
    proof = (verify_train or train_data.verify_train_only)(base)
    require(proof.get('status') == 'accepted_external_training_verified', 'training_release_required')
    hashes = {}

    def read(name, expected=None, private=False):
        raw = train_data.read_bytes(train_data.child(base, name), private=private)
        value = sha(raw)
        require(expected is None or value == expected, 'capability_input_hash_changed')
        require(name not in hashes or hashes[name] == value, 'capability_input_changed_during_load')
        hashes[name] = value
        return raw

    freeze_raw = read(TRAIN + '/freeze.json', proof['freeze_sha256'], private=True)
    freeze = decode(freeze_raw)
    manifest_raw = read(TRAIN + '/manifest.jsonl', freeze['artifacts']['manifest.jsonl'], private=True)
    rows = [decode(line) for line in manifest_raw.splitlines()]
    require(len(rows) == proof['accepted_images'] and len(rows) >= 13,
            'at_least_13_accepted_training_images_required')
    require(len({row['sample_id'] for row in rows}) == len(rows), 'duplicate_training_sample_id')
    selected = sorted(rows, key=lambda row: row['sample_id'])[:13]
    require(len({row['group_id'] for row in selected}) == 13
            and len({row['image_sha256'] for row in selected}) == 13
            and len({row['rgb_sha256'] for row in selected}) == 13,
            'probe_requires_13_distinct_training_groups_and_images')
    images, payloads = [], {}
    for row in selected:
        expected_path = TRAIN + '/images/' + row['image_sha256'] + '.png'
        require(row.get('dataset') == 'nutrition5k' and row.get('split') == 'train'
                and row['image_path'] == expected_path
                and freeze['artifacts'].get('images/' + row['image_sha256'] + '.png') == row['image_sha256'],
                'nontraining_or_unsealed_probe_image')
        raw = read(expected_path, row['image_sha256'], private=True)
        with Image.open(io.BytesIO(raw)) as image:
            image.load()
            rgb = image.convert('RGB')
            pixels = sha(str(rgb.size).encode() + b'\0' + rgb.tobytes())
        require(pixels == row['rgb_sha256'], 'probe_rgb_hash_changed')
        # Derive the sent-payload proof from the same verified bytes. The
        # estimator may reopen paths, but the final provider boundary rejects
        # any different image or ordering before a request can be made.
        payloads[row['image_sha256']] = payload_hash(encode_image(io.BytesIO(raw), 'native'))
        images.append({key: row[key] for key in ('sample_id', 'group_id', 'image_path', 'image_sha256', 'rgb_sha256')})
    for name in SOURCE_NAMES:
        read(name)

    def unchanged():
        for name, expected in hashes.items():
            require(sha(train_data.read_bytes(train_data.child(base, name))) == expected,
                    'capability_bound_source_or_input_changed')

    binding = {'schema_version': 1, 'policy': deepcopy(POLICY),
        'training_freeze_sha256': sha(freeze_raw), 'training_images': len(rows),
        'fixed_probe_images': images, 'image_payload_sha256': payloads,
        'source_and_input_sha256': dict(hashes)}
    inputs = {'training_freeze_sha256': sha(freeze_raw), 'fixed_probe_images': images,
              'image_payload_sha256': payloads, 'policy': deepcopy(POLICY)}
    unchanged()
    store = ArtifactStore(base / RUN, binding, [RECORD], verify_sources=unchanged, root=base / 'round4')
    query = str(train_data.child(base, images[0]['image_path']))
    candidates = [{'candidate_id': f'c{index}',
                   'image_path': str(train_data.child(base, row['image_path']))}
                  for index, row in enumerate(images[1:], start=1)]
    return {'base': base, 'store': store, 'binding': binding, 'inputs': inputs,
            'query': query, 'candidates': candidates, 'unchanged': unchanged,
            'ordered_payload_hashes': [payloads[row['image_sha256']] for row in images]}


def validate_envelope(envelope):
    require(isinstance(envelope, dict) and set(envelope) == {'result', 'request_refs'},
            'invalid_capability_envelope')
    result, refs = envelope['result'], envelope['request_refs']
    require(isinstance(result, dict) and set(result) == {'raw_outputs', 'selected_ids', 'repair_used', 'failure'},
            'invalid_capability_result')
    raw = result['raw_outputs']
    require(isinstance(raw, list) and 1 <= len(raw) <= 2 and all(isinstance(value, str) for value in raw)
            and type(result['repair_used']) is bool, 'invalid_capability_response_count')
    expected = None
    for index, value in enumerate(raw):
        try:
            selected = vision._parse_rerank(value)
        except ContractError as error:
            expected = {'raw_outputs': raw, 'selected_ids': None, 'repair_used': True, 'failure': str(error)}
        else:
            require(index == len(raw) - 1, 'response_after_successful_capability_result')
            expected = {'raw_outputs': raw, 'selected_ids': selected, 'repair_used': bool(index), 'failure': None}
    require(result == expected and (result['failure'] is None or len(raw) == 2),
            'capability_result_reparse_changed')
    require(isinstance(refs, list) and len(refs) == len(raw), 'capability_request_count_changed')
    for ref, value in zip(refs, raw):
        require(isinstance(ref, dict) and set(ref) == {'role', 'request_hash', 'value_hash', 'status', 'cache_present_before'}
                and ref['role'] == 'chat' and ref['status'] == 'returned'
                and isinstance(ref['request_hash'], str) and re.fullmatch('[0-9a-f]{64}', ref['request_hash'])
                and ref['value_hash'] == request_value_hash(value)
                and type(ref['cache_present_before']) is bool,
                'invalid_capability_request_reference')
    return deepcopy(envelope)


def _record(state, envelope):
    result = envelope['result']
    return {'schema_version': 1, 'passed': result['failure'] is None,
        'training_freeze_sha256': state['binding']['training_freeze_sha256'],
        'binding_sha256': fingerprint(state['binding']),
        'stage_envelope_sha256': fingerprint(envelope),
        'probe_images': 13, 'candidate_images': 12,
        'repair_used': result['repair_used'], 'failure': result['failure'],
        'selected_ids': result['selected_ids'], 'request_ref_count': len(envelope['request_refs'])}


def _verify_state(state):
    store = state['store']
    records = store.verify_completed()
    def never_call():
        raise CapabilityError('completed_probe_must_not_call_provider')
    envelope = store.stage_runner(STAGE, state['inputs'], never_call, validate_envelope)
    require(records == {RECORD: _record(state, envelope)}, 'capability_completed_record_changed')
    require(records[RECORD]['passed'] is True, 'sealed_capability_contract_failure')
    state['unchanged']()
    completion = train_data.read_bytes(train_data.child(state['base'], RUN + '/completion.json'), private=True)
    return {'status': 'capability_passed', 'passed': True,
        'completion_sha256': sha(completion),
        'training_freeze_sha256': state['binding']['training_freeze_sha256'],
        'probe_images': 13, 'candidate_images': 12,
        'request_ref_count': records[RECORD]['request_ref_count'],
        'provider_constructed': False, 'api_calls_this_verification': 0}


def verify_capability(base=None, *, verify_train=None):
    """Read-only success gate; a sealed negative probe remains a hard blocker."""
    return _verify_state(_state(Path(base or ROOT), verify_train))


def probe(base=None, *, allow_paid=False, provider_factory=None, verify_train=None):
    require(type(allow_paid) is bool, 'paid_flag_must_be_boolean')
    state = _state(Path(base or ROOT), verify_train)
    if (state['base'] / RUN / 'completion.json').exists():
        return _verify_state(state)
    if not allow_paid:
        return {'status': 'offline_capability_preflight_pass', 'training_images': state['binding']['training_images'],
            'probe_images': 13, 'candidate_images': 12, 'maximum_chat_logical_requests': 2,
            'training_freeze_sha256': state['binding']['training_freeze_sha256'],
            'binding_sha256': fingerprint(state['binding']), 'provider_constructed': False, 'api_calls': 0}
    store = state['store']
    store.initialize()
    factory = provider_factory or Provider
    provider = factory(state['base'] / PROVIDER_LOGS, allow_paid=True, namespace=NAMESPACE)
    try:
        guarded = ImageGuard(TraceProvider(provider))
        def invoke():
            marker = guarded.mark()
            with guarded.expect(state['ordered_payload_hashes']):
                result = vision.rerank(guarded, state['query'], state['candidates'])
            return {'result': result, 'request_refs': guarded.refs_since(marker)}
        envelope = store.stage_runner(STAGE, state['inputs'], invoke, validate_envelope)
        state['unchanged']()
        record = _record(state, envelope)
        store.finalize({RECORD: record})
    finally:
        provider.close()
    result = _verify_state(state)  # Sealed contract failure raises here.
    result['provider_constructed'] = True
    result.pop('api_calls_this_verification')
    return result


def main(argv=None):
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--allow-paid', action='store_true')
    mode.add_argument('--verify-only', action='store_true')
    args = parser.parse_args(argv)
    try:
        result = verify_capability() if args.verify_only else probe(allow_paid=args.allow_paid)
    except (Exception, ProviderStop) as error:
        print(json.dumps({'status': 'stopped', 'error_type': type(error).__name__}, sort_keys=True))
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
