"""Offline blind duplicate quarantine and immutable external-training release.

No network/client imports. Nothing runs on import. Protected images/labels are
never opened: only their already frozen byte/RGB fingerprints are consulted.
Metadata is first-column allowlisted as bytes before decoding accepted rows.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
from decimal import Decimal
import fcntl
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import shutil
import stat
import statistics
import sys
import tempfile

from PIL import Image

sys.dont_write_bytecode = True
V2 = Path(__file__).resolve().parents[2]
PROPOSAL = 'round4/proposal/private_train_pool_proposal.json'
PROPOSAL_SHA256 = 'eddf9a644114f5b4aecc4d906dbdec6ee0eaecd80b97e23743d9edf663e03eb0'
PROPOSAL_SUMMARY = 'round4/proposal/raw_rgb_summary.json'
SUMMARY_SHA256 = '3e3d3dc8f66faf1176971480ad988925c5b63d5dc92f8673a3b75dd54c70f810'
AUDIT_INDEX = 'round4/proposal/private_audit_index.json'
INDEX_SHA256 = 'e0a57d390fced7b3d811900e3cfd634bfaced7b4f7c1b897c59b495aac4fc5f2'
DOWNLOADER_SHA256 = 'e4547e9c20d6b09d7510332ad40570cd6d95a9b1745f830a364c48c98ee19dfb'
SEED = 'dietai24-mae-v2-round4-train600-20261103'
FILE_COUNT = 230
CACHED_BYTES = 104830902
MIN_GROUPS = 12
MAX_IMAGE_BYTES = 5000000
MAX_TRANSFER_BYTES = 350000000
MAX_ATTEMPTS = 3
TOTAL_TOLERANCE = Decimal('0.001')
EXPECTED_EXCEPTION_COUNT = 1
TRAINING_DATA_EXCEPTION = {
    'version': 'official-single-record-mass-discrepancy-r4.1',
    'raw_source_relative_path': 'Nutrition5k/metadata/dish_metadata_cafe1.csv',
    'raw_source_sha256': '881df31f27c2343d0ce219964527e0796f6ddadd60701ce6840fa801e8c2a960',
    'raw_record_sha256': '6924b964d0da3b5dbed4bfe055f1f9c0cac0f072fac732c46393b418ad9e5201',
    'target': 'weight',
    'signed_residual_definition': 'ingredient_sum_minus_official_target',
    'signed_residual': '2.000000',
    'strict_default_abs_tolerance': '0.001',
    'preserve_original_targets_and_ingredient_masses': True,
    'pre_exception_train_data_sha256': '7a5c450dc5cc3918bb283e9a042e16db95e69ef5ee887b2f79763d525e4600a3',
}
TARGETS = ('weight', 'energy', 'fat', 'carbs', 'protein')
BASE_URL = 'https://storage.googleapis.com/nutrition5k_dataset/nutrition5k_dataset/imagery/realsense_overhead'
TRAIN = 'round4/data/train'
DOWNLOADS = 'round4/downloads'
RAW_NAMES = ('Nutrition5k/metadata/dish_metadata_cafe1.csv', 'Nutrition5k/metadata/dish_metadata_cafe2.csv')
SOURCE_NAMES = ('round4/src/train_data.py', 'round3/src/dev_ingredients.py', 'round4/tools/download_train.py',
                'round4/TRAINING_DATA_EXCEPTION.md')
FREEZE_NAMES = {'data/freeze/source_snapshot.json', 'data/freeze/final_source_snapshot.json',
                'data/freeze/validation_freeze.json', 'data/cohorts/dev_freeze.json'}
HEX = re.compile(r'[0-9a-f]{64}\Z')
DISH = re.compile(r'dish_[0-9]{10}\Z')


class TrainDataError(RuntimeError):
    """Only fixed, non-sensitive codes reach the terminal."""


def require(condition, code):
    if not condition:
        raise TrainDataError(code)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def encoded(value):
    return (json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + '\n').encode()


def decode(raw):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, 'duplicate_json_key')
            result[key] = value
        return result
    try:
        return json.loads(raw, object_pairs_hook=unique,
                          parse_constant=lambda _: require(False, 'nonfinite_json'))
    except TrainDataError:
        raise
    except Exception:
        raise TrainDataError('invalid_json') from None


def child(base, relative):
    base, relative = Path(base), Path(relative)
    require(base.resolve() == base and base.is_dir(), 'unsafe_root')
    require(not relative.is_absolute() and '..' not in relative.parts and relative.parts,
            'unsafe_relative_path')
    path = base
    for part in relative.parts:
        path = path / part
        require(not path.is_symlink(), 'symlink_rejected')
    require(path.resolve() == path and path.is_relative_to(base), 'unsafe_relative_path')
    return path


def read_bytes(path, *, private=False):
    path = Path(path)
    require(not path.is_symlink() and path.is_file() and stat.S_ISREG(path.stat().st_mode),
            'regular_file_required')
    require(not private or stat.S_IMODE(path.stat().st_mode) == 0o600,
            'private_permissions_required')
    return path.read_bytes()


def bound_read(base, relative, expected, guards, *, private=False):
    path = child(base, relative)
    raw = read_bytes(path, private=private)
    require(digest(raw) == expected, 'input_hash_mismatch')
    require(path not in guards or guards[path] == expected, 'conflicting_input_binding')
    guards[path] = expected
    return raw


def verify_guards(guards):
    for path, expected in guards.items():
        require(digest(read_bytes(path)) == expected, 'input_changed_during_preparation')


def load_ingredient_helpers(base):
    path = child(base, 'round3/src/dev_ingredients.py')
    spec = importlib.util.spec_from_file_location('_round4_training_ingredient_helpers', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def replay_ledger(raw, entries):
    """Independent read-only replay of the downloader's durable receipt states."""
    require(not raw or raw.endswith(b'\n'), 'truncated_download_ledger')
    expected = {entry['dish_id']: entry['cached_object_bytes'] for entry in entries}
    states = {dish: {'attempt': 0, 'status': 'new', 'received': 0} for dish in expected}
    reserved = received = 0
    for line in raw.splitlines():
        event = decode(line)
        require(isinstance(event, dict), 'invalid_download_event')
        dish, attempt, kind = event.get('dish_id'), event.get('attempt'), event.get('event')
        require(dish in expected and type(attempt) is int and 1 <= attempt <= MAX_ATTEMPTS,
                'invalid_download_event')
        state = states[dish]
        if kind == 'start':
            require(set(event) == {'event', 'dish_id', 'attempt', 'reserved_bytes'}
                    and state['status'] in ('new', 'retryable_failure')
                    and attempt == state['attempt'] + 1
                    and event['reserved_bytes'] == expected[dish] + 1,
                    'invalid_attempt_or_reservation')
            state.update(attempt=attempt, status='started', received=0)
            reserved += event['reserved_bytes']
            continue
        require(attempt == state['attempt'], 'invalid_attempt_sequence')
        if kind == 'received':
            require(set(event) == {'event', 'dish_id', 'attempt', 'bytes'}
                    and state['status'] == 'started' and type(event['bytes']) is int
                    and event['bytes'] > 0, 'invalid_received_event')
            state['received'] += event['bytes']
            received += event['bytes']
            require(state['received'] <= expected[dish] + 1, 'received_exceeds_reservation')
        elif kind == 'ready':
            require(set(event) == {'event', 'dish_id', 'attempt', 'bytes_sha256', 'bytes'}
                    and state['status'] == 'started' and state['received'] == expected[dish]
                    and event['bytes'] == expected[dish] and isinstance(event['bytes_sha256'], str)
                    and HEX.fullmatch(event['bytes_sha256']), 'invalid_ready_event')
            state.update(status='ready', bytes_sha256=event['bytes_sha256'])
        elif kind == 'complete':
            require(set(event) == {'event', 'dish_id', 'attempt'} and state['status'] == 'ready',
                    'invalid_complete_event')
            state['status'] = 'complete'
        elif kind == 'failed':
            require(set(event) == {'event', 'dish_id', 'attempt', 'category', 'retryable'}
                    and state['status'] == 'started' and type(event['retryable']) is bool
                    and isinstance(event['category'], str) and re.fullmatch('[a-z_]+', event['category']),
                    'invalid_failure_event')
            state['status'] = 'retryable_failure' if event['retryable'] else 'terminal_failure'
        else:
            require(False, 'unknown_download_event')
    require(received <= reserved <= MAX_TRANSFER_BYTES, 'download_budget_invalid')
    require(all(state['status'] == 'complete' for state in states.values()), 'all_downloads_must_complete')
    return states, reserved, received


def load_inputs(base):
    guards = {}
    proposal = decode(bound_read(base, PROPOSAL, PROPOSAL_SHA256, guards, private=True))
    summary = decode(bound_read(base, PROPOSAL_SUMMARY, SUMMARY_SHA256, guards))
    index = decode(bound_read(base, AUDIT_INDEX, INDEX_SHA256, guards, private=True))
    require(proposal.get('schema_version') == 1 and proposal.get('seed') == SEED
            and proposal.get('status') == 'awaiting_new_download_authorization'
            and proposal.get('actual_images_and_screening_groups') == FILE_COUNT
            and proposal.get('private_audit_index_sha256') == INDEX_SHA256,
            'invalid_pinned_proposal')
    require(summary.get('proposal_sha256') == PROPOSAL_SHA256
            and summary.get('selected_images') == FILE_COUNT
            and summary.get('selected_groups') == FILE_COUNT
            and summary.get('cached_download_byte_estimate') == CACHED_BYTES,
            'proposal_summary_mismatch')
    freezes = proposal.get('original_frozen_hashes')
    require(isinstance(freezes, dict) and set(freezes) == FREEZE_NAMES, 'invalid_source_freezes')
    for relative, expected in freezes.items():
        bound_read(base, relative, expected, guards)
    source_hashes = {}
    for relative in SOURCE_NAMES:
        source = child(base, relative)
        raw = read_bytes(source)
        source_hashes[relative] = digest(raw)
        guards[source] = digest(raw)
    require(source_hashes[SOURCE_NAMES[2]] == DOWNLOADER_SHA256, 'downloader_source_changed')
    require(index.get('schema_version') == 1 and index.get('seed') == SEED, 'invalid_audit_index')
    entries = proposal.get('entries')
    require(isinstance(entries, list) and len(entries) == FILE_COUNT, 'proposal_count_changed')
    ids, groups, recipes, destinations = set(), set(), set(), set()
    blocked = set(index['blocked_screening_components'])
    for entry in entries:
        dish, group = entry.get('dish_id'), entry.get('screening_component_id')
        require(isinstance(dish, str) and DISH.fullmatch(dish) and dish not in ids,
                'invalid_proposal_identifier')
        require(group not in blocked and group not in groups
                and index['screening_components'].get(dish) == group
                and index['original_components'].get(dish) == entry.get('original_component_id')
                and index['recipe_sha256'].get(dish) == entry.get('recipe_sha256')
                and entry['recipe_sha256'] not in recipes, 'proposal_exclusion_or_group_changed')
        destination = 'round4/data/incoming/' + digest((SEED + '|incoming|' + dish).encode()) + '/rgb.png'
        require(entry.get('planned_destination') == destination and destination not in destinations
                and entry.get('source_url') == f'{BASE_URL}/{dish}/rgb.png'
                and type(entry.get('cached_object_bytes')) is int
                and 0 < entry['cached_object_bytes'] < MAX_IMAGE_BYTES
                and entry.get('max_image_bytes') == MAX_IMAGE_BYTES, 'proposal_payload_contract_changed')
        child(base, destination)
        ids.add(dish); groups.add(group); recipes.add(entry['recipe_sha256']); destinations.add(destination)
    require(sum(entry['cached_object_bytes'] for entry in entries) == CACHED_BYTES,
            'cached_size_total_changed')
    done_path = child(base, DOWNLOADS + '/download_summary.json')
    done_raw = read_bytes(done_path, private=True)
    guards[done_path] = digest(done_raw)
    done = decode(done_raw)
    require(done.get('status') == 'incoming_bytes_complete_pending_blind_dedup'
            and done.get('completed_files') == FILE_COUNT
            and done.get('proposal_sha256') == PROPOSAL_SHA256
            and done.get('raw_rgb_summary_sha256') == SUMMARY_SHA256
            and done.get('training_release') is False
            and done.get('pixel_verification_performed') is False,
            'download_completion_required')
    receipt_raw = bound_read(base, DOWNLOADS + '/receipts.json', done.get('receipts_sha256'), guards, private=True)
    auth_raw = bound_read(base, DOWNLOADS + '/authorization.json', done.get('authorization_sha256'), guards, private=True)
    ledger_raw = bound_read(base, DOWNLOADS + '/attempts.jsonl', done.get('ledger_sha256'), guards, private=True)
    receipts, auth = decode(receipt_raw), decode(auth_raw)
    require(auth.get('operator_asserted_current_user_authorization') is True
            and auth.get('status') == 'operator_asserted_authorization'
            and auth.get('proposal_sha256') == PROPOSAL_SHA256
            and auth.get('raw_rgb_summary_sha256') == SUMMARY_SHA256
            and auth.get('downloader_sha256') == DOWNLOADER_SHA256
            and auth.get('maximum_total_response_body_transfer_bytes') == MAX_TRANSFER_BYTES
            and auth.get('maximum_attempts_per_file') == MAX_ATTEMPTS
            and auth.get('maximum_image_bytes') == MAX_IMAGE_BYTES,
            'download_authorization_binding_changed')
    require(set(receipts) == {'schema_version', 'proposal_sha256', 'raw_rgb_summary_sha256',
                              'training_release', 'pixel_verification_performed', 'entries'}
            and receipts.get('schema_version') == 1
            and receipts.get('proposal_sha256') == PROPOSAL_SHA256
            and receipts.get('raw_rgb_summary_sha256') == SUMMARY_SHA256
            and receipts.get('training_release') is False
            and receipts.get('pixel_verification_performed') is False
            and isinstance(receipts.get('entries'), list) and len(receipts['entries']) == FILE_COUNT,
            'invalid_download_receipts')
    states, reserved, received = replay_ledger(ledger_raw, entries)
    require(done.get('reserved_response_body_bytes') == reserved
            and done.get('received_body_bytes_recorded') == received
            and done.get('attempts_consumed') == sum(state['attempt'] for state in states.values())
            and done.get('cached_expected_payload_bytes') == CACHED_BYTES
            and done.get('maximum_total_response_body_transfer_bytes') == MAX_TRANSFER_BYTES
            and done.get('maximum_attempts_per_file') == MAX_ATTEMPTS
            and done.get('maximum_image_bytes') == MAX_IMAGE_BYTES,
            'download_summary_totals_changed')
    for entry, receipt in zip(entries, receipts['entries']):
        state = states[entry['dish_id']]
        expected = {'dish_id': entry['dish_id'], 'destination': entry['planned_destination'],
                    'source_url': entry['source_url'], 'bytes': entry['cached_object_bytes'],
                    'bytes_sha256': state['bytes_sha256'], 'attempts_consumed': state['attempt']}
        require(receipt == expected, 'receipt_order_or_payload_mismatch')
    protected = {'bytes_sha256': set(), 'rgb_sha256': set()}
    for fingerprint in index['known_image_fingerprints']:
        for key in protected:
            value = fingerprint.get(key)
            require(isinstance(value, str) and HEX.fullmatch(value), 'invalid_protected_fingerprint')
            protected[key].add(value)
    require(all(protected.values()), 'empty_protected_fingerprint_index')
    return entries, receipts['entries'], protected, index, guards, source_hashes


def fingerprint_candidate(raw, expected):
    require(len(raw) == expected['bytes'] and digest(raw) == expected['bytes_sha256'],
            'candidate_bytes_mismatch')
    try:
        with Image.open(io.BytesIO(raw)) as image:
            require(image.format == 'PNG' and image.mode == 'RGB' and image.size == (640, 480),
                    'candidate_image_contract_failed')
            image.load()
            rgb_hash = digest(str(image.size).encode() + b'\0' + image.tobytes())
    except TrainDataError:
        raise
    except Exception:
        raise TrainDataError('candidate_image_decode_failed') from None
    return {'bytes_sha256': expected['bytes_sha256'], 'rgb_sha256': rgb_hash, 'bytes': len(raw)}


def quarantine(entries, fingerprints, protected):
    require(len(entries) == len(fingerprints), 'fingerprint_population_mismatch')
    reasons = defaultdict(set)
    for key in ('bytes_sha256', 'rgb_sha256'):
        by_value = defaultdict(list)
        for entry, fingerprint in zip(entries, fingerprints):
            dish = entry['dish_id']
            by_value[fingerprint[key]].append(dish)
            if fingerprint[key] in protected[key]:
                reasons[dish].add('protected_' + key)
        for dishes in by_value.values():
            if len(dishes) > 1:
                for dish in dishes:
                    reasons[dish].add('candidate_collision_' + key)
    bad_groups = {entry['screening_component_id'] for entry in entries if reasons[entry['dish_id']]}
    for entry in entries:
        if entry['screening_component_id'] in bad_groups:
            reasons[entry['dish_id']].add('quarantined_screening_component')
    return {entry['dish_id']: sorted(reasons[entry['dish_id']]) for entry in entries}


def exception_record():
    """Safe evidence for the sole source-pinned exception, never a row ID."""
    return {key: TRAINING_DATA_EXCEPTION[key] for key in (
        'version', 'raw_source_relative_path', 'raw_source_sha256',
        'raw_record_sha256', 'target', 'signed_residual_definition', 'signed_residual')}


def extract_accepted(streams, accepted, helpers, *, exception_audit=None):
    """Unmatched physical tails are never UTF-8/CSV decoded or numerically parsed."""
    allowed = {dish.encode('ascii'): dish for dish in accepted}
    records, labels, hashes = {}, {}, {}
    max_residual = {key: Decimal(0) for key in TARGETS}
    applied = []
    for name, stream in streams:
        require(name not in hashes, 'duplicate_metadata_source')
        h = hashlib.sha256()
        source_exception_count = 0
        for position, raw in enumerate(stream):
            require(isinstance(raw, bytes), 'binary_metadata_required')
            h.update(raw)
            first = raw.split(b',', 1)[0]
            if position == 0:
                first = first.removeprefix(b'\xef\xbb\xbf')
            if first not in allowed:
                continue
            dish = allowed[first]
            require(dish not in records, 'duplicate_accepted_metadata')
            try:
                ingredients = helpers.parse_matched_row(raw, dish)
                parsed = list(csv.reader(io.StringIO(raw.decode('utf-8-sig'), newline=''), strict=True))
                require(len(parsed) == 1 and parsed[0][0] == dish, 'matched_record_invalid')
                row = parsed[0]
                energy, weight, fat, carbs, protein = [helpers.number(value) for value in row[1:6]]
                truth = dict(zip(TARGETS, (weight, energy, fat, carbs, protein)))
                require(weight > 0 and any(truth[key] > 0 for key in TARGETS[1:]),
                        'accepted_target_eligibility_changed')
                start = 6 if row[6].startswith('ingr_') else 7
                recipe = digest(', '.join(sorted(row[offset + 1] for offset in range(start, len(row), 7))).encode())
                require(recipe == accepted[dish]['recipe_sha256'], 'accepted_recipe_changed')
                totals = {key: Decimal(0) for key in TARGETS}
                for offset in range(start, len(row), 7):
                    for key, value in zip(TARGETS, row[offset + 2:offset + 7]):
                        totals[key] += helpers.number(value)
                for key in TARGETS:
                    signed_residual = totals[key] - truth[key]
                    residual = abs(signed_residual)
                    if residual > TOTAL_TOLERANCE:
                        require(key == TRAINING_DATA_EXCEPTION['target'] == 'weight'
                                and name == TRAINING_DATA_EXCEPTION['raw_source_relative_path']
                                and digest(raw) == TRAINING_DATA_EXCEPTION['raw_record_sha256']
                                and signed_residual == Decimal(TRAINING_DATA_EXCEPTION['signed_residual']),
                                'ingredient_target_total_mismatch')
                        applied.append(exception_record())
                        source_exception_count += 1
                    max_residual[key] = max(max_residual[key], residual)
            except TrainDataError:
                raise
            except Exception:
                raise TrainDataError('accepted_metadata_invalid') from None
            meta = {'dish_id': dish, 'sample_id': 'nutrition5k-' + dish,
                    'group_id': accepted[dish]['screening_component_id'], 'split': 'train'}
            records[dish] = {**meta, 'ingredients': ingredients}
            labels[meta['sample_id']] = {'truth': {key: float(truth[key]) for key in TARGETS}}
        hashes[name] = h.hexdigest()
        # Source SHA is checked after consuming the complete byte stream and
        # before any records can leave this function. A matching row in a
        # changed source file is never sufficient to authorize the exception.
        if source_exception_count:
            require(hashes[name] == TRAINING_DATA_EXCEPTION['raw_source_sha256'],
                    'registered_exception_source_hash_mismatch')
    require(set(records) == set(accepted), 'accepted_metadata_missing')
    require(len(applied) <= 1, 'registered_exception_count_exceeded')
    if exception_audit is not None:
        exception_audit.extend(applied)
    return [records[dish] for dish in sorted(records)], labels, hashes, {key: str(value) for key, value in max_residual.items()}


def build_catalog(records, helpers):
    catalog, zero = {}, 0
    for row in records:
        require(row['split'] == 'train', 'training_records_only')
        for item in row['ingredients']:
            identifier, name = item['ingredient_id'], helpers.name_value(item['name'])
            require(helpers.INGREDIENT.fullmatch(identifier), 'invalid_training_ingredient_id')
            grams = helpers.number(item['grams'])
            require(set(item['nutrients']) == set(TARGETS[1:]), 'invalid_training_nutrients')
            nutrients = {key: helpers.number(item['nutrients'][key]) for key in TARGETS[1:]}
            if not grams:
                require(not any(nutrients.values()), 'zero_mass_nonzero_nutrients')
                zero += 1
                continue
            density = {key: 100 * value / grams for key, value in nutrients.items()}
            if identifier not in catalog:
                catalog[identifier] = {'name': name, 'reference': density, 'grams': Decimal(0),
                    'nutrients': dict.fromkeys(TARGETS[1:], Decimal(0)), 'dishes': set(), 'groups': set()}
            entry = catalog[identifier]
            require(entry['name'].casefold() == name.casefold(), 'training_ingredient_name_conflict')
            require(all(helpers.close_density(entry['reference'][key], density[key]) for key in TARGETS[1:]),
                    'training_ingredient_density_conflict')
            entry['grams'] += grams
            for key in TARGETS[1:]:
                entry['nutrients'][key] += nutrients[key]
            entry['dishes'].add(row['dish_id']); entry['groups'].add(row['group_id'])
    require(catalog, 'empty_training_catalog')
    return {'schema_version': 1, 'scope': 'accepted_external_training_only_domain_catalog',
        'training_dish_count': len(records), 'training_group_count': len({row['group_id'] for row in records}),
        'zero_mass_ingredient_count': zero,
        'density_consistency': {'absolute_tolerance': str(helpers.DENSITY_ABS_TOL),
            'relative_tolerance': str(helpers.DENSITY_REL_TOL),
            'method': 'per_training_ID_consistency_then_mass_weighted_pooling'},
        'ingredients': [{'ingredient_id': identifier, 'name': entry['name'],
            'density_per_100g': {key: float(100 * entry['nutrients'][key] / entry['grams']) for key in TARGETS[1:]},
            'supporting_dish_count': len(entry['dishes']), 'supporting_group_count': len(entry['groups'])}
            for identifier, entry in sorted(catalog.items())]}


def write_private(path, raw):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'wb') as stream:
        stream.write(raw); stream.flush(); os.fsync(stream.fileno())


def prepare(base=None):
    base = Path(base or V2).resolve()
    release = child(base, TRAIN)
    if release.exists():
        return verify_train_only(base)
    entries, receipts, protected, index, guards, source_hashes = load_inputs(base)
    fingerprints = []
    for entry, receipt in zip(entries, receipts):
        path = child(base, entry['planned_destination'])
        raw = read_bytes(path, private=True)
        fingerprints.append(fingerprint_candidate(raw, receipt))
        guards[path] = receipt['bytes_sha256']
    reasons = quarantine(entries, fingerprints, protected)
    accepted = {entry['dish_id']: entry for entry in entries if not reasons[entry['dish_id']]}
    require(len({entry['screening_component_id'] for entry in accepted.values()}) >= MIN_GROUPS,
            'fewer_than_12_accepted_training_groups')
    helpers = load_ingredient_helpers(base)
    # The only mixed-source metadata read is a binary stream with ID-first gating.
    repo = base.parents[1]
    raw_paths = {}
    for name in RAW_NAMES:
        path = child(repo, name)
        value = digest(read_bytes(path))
        require(index['source_sha256'].get(name) == value, 'frozen_raw_metadata_changed')
        guards[path] = value
        raw_paths[name] = path
    from contextlib import ExitStack
    with ExitStack() as stack:
        streams = [(name, stack.enter_context(raw_paths[name].open('rb'))) for name in RAW_NAMES]
        applied_exceptions = []
        records, labels, raw_hashes, residuals = extract_accepted(
            streams, accepted, helpers, exception_audit=applied_exceptions)
    require(len(applied_exceptions) == EXPECTED_EXCEPTION_COUNT,
            'registered_exception_expected_count_mismatch')
    for name, value in raw_hashes.items():
        require(index['source_sha256'].get(name) == value, 'frozen_raw_metadata_changed')
        guards[repo / name] = value
    catalog = build_catalog(records, helpers)
    fallback = {'schema_version': 1, 'method': 'median_of_accepted_external_training_official_targets',
        'training_dish_count': len(records),
        'prediction': {key: statistics.median(row['truth'][key] for row in labels.values()) for key in TARGETS}}
    fp_by_dish = {entry['dish_id']: fp for entry, fp in zip(entries, fingerprints)}
    manifest = []
    for dish in sorted(accepted):
        entry, fp = accepted[dish], fp_by_dish[dish]
        manifest.append({'sample_id': 'nutrition5k-' + dish, 'dataset': 'nutrition5k', 'split': 'train',
            'group_id': entry['screening_component_id'], 'original_component_id': entry['original_component_id'],
            'recipe_sha256': entry['recipe_sha256'], 'image_path': TRAIN + '/images/' + fp['bytes_sha256'] + '.png',
            'image_sha256': fp['bytes_sha256'], 'rgb_sha256': fp['rgb_sha256']})
    audit = {'schema_version': 1, 'proposal_sha256': PROPOSAL_SHA256, 'private_audit_index_sha256': INDEX_SHA256,
        'complete_candidate_count': len(entries), 'accepted_images': len(accepted),
        'accepted_groups': len({entry['screening_component_id'] for entry in accepted.values()}),
        'quarantined_images': len(entries) - len(accepted),
        'quarantine_reason_counts_overlapping': dict(Counter(reason for values in reasons.values() for reason in values)),
        'candidate_audit': [{'dish_id': entry['dish_id'], 'screening_component_id': entry['screening_component_id'],
                            **fp, 'quarantine_reasons': reasons[entry['dish_id']]} for entry, fp in zip(entries, fingerprints)],
        'target_sum_max_abs_residual': residuals, 'target_sum_abs_tolerance': str(TOTAL_TOLERANCE),
        'data_quality_exception_policy': TRAINING_DATA_EXCEPTION,
        'expected_data_quality_exception_count': EXPECTED_EXCEPTION_COUNT,
        'data_quality_exception_count': len(applied_exceptions),
        'data_quality_exceptions': applied_exceptions,
        'protected_images_or_labels_opened': False, 'automatic_replacements': 0,
        'physical_plate_independence_proved': False}
    payloads = {'manifest.jsonl': b''.join((json.dumps(row, sort_keys=True) + '\n').encode() for row in manifest),
        'labels.json': encoded(labels), 'ingredients.json': encoded({'schema_version': 1,
            'scope': 'accepted_external_training_only_private', 'source_sha256': raw_hashes, 'records': records}),
        'catalog.json': encoded(catalog), 'fallback.json': encoded(fallback), 'audit.json': encoded(audit)}
    binding = {'schema_version': 1, 'proposal_sha256': PROPOSAL_SHA256, 'private_audit_index_sha256': INDEX_SHA256,
        'source_sha256': source_hashes,
        'inputs_sha256': {str(path.relative_to(base)): value for path, value in guards.items() if path.is_relative_to(base)},
        'raw_metadata_sha256': raw_hashes,
        'data_quality_exception_count': len(applied_exceptions),
        'policy': {'candidate_collisions': 'quarantine_all_endpoints_and_their_screening_components',
            'protected_collisions': 'quarantine_entire_screening_component', 'minimum_groups': MIN_GROUPS,
            'target_sum_abs_tolerance': str(TOTAL_TOLERANCE), 'no_replacements': True,
            'expected_data_quality_exception_count': EXPECTED_EXCEPTION_COUNT,
            'data_quality_exception': TRAINING_DATA_EXCEPTION}}
    verify_guards(guards)
    data_dir = child(base, 'round4/data')
    data_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    lock_path = child(base, 'round4/data/.train_prepare.lock')
    fd = os.open(lock_path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'a+') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise TrainDataError('training_preparation_already_running') from None
        if release.exists():
            return verify_train_only(base)
        staging = Path(tempfile.mkdtemp(prefix='.train-stage-', dir=data_dir))
        try:
            artifacts = {}
            for name, raw in payloads.items():
                write_private(staging / name, raw)
                artifacts[name] = digest(raw)
            for row in manifest:
                dish = row['sample_id'].removeprefix('nutrition5k-')
                raw = read_bytes(child(base, accepted[dish]['planned_destination']), private=True)
                require(digest(raw) == row['image_sha256'], 'candidate_changed_before_copy')
                name = 'images/' + row['image_sha256'] + '.png'
                write_private(staging / name, raw)
                artifacts[name] = row['image_sha256']
            freeze = {'schema_version': 1, 'status': 'accepted_external_training_frozen',
                'binding': binding, 'artifacts': artifacts,
                'accepted_images': len(manifest), 'accepted_groups': audit['accepted_groups'],
                'quarantined_images': audit['quarantined_images'], 'training_catalog_size': len(catalog['ingredients']),
                'data_quality_exception_count': len(applied_exceptions)}
            write_private(staging / 'freeze.json', encoded(freeze))
            verify_guards(guards)
            os.rename(staging, release)
            dirfd = os.open(data_dir, os.O_DIRECTORY)
            try:
                os.fsync(dirfd)
            finally:
                os.close(dirfd)
        finally:
            if staging.exists():
                shutil.rmtree(staging)
    return verify_train_only(base)


def verify_train_only(base=None):
    """Only training artifacts plus sealed metadata/hash inputs; no protected RGB/labels."""
    base = Path(base or V2).resolve()
    release = child(base, TRAIN)
    freeze_raw = read_bytes(child(base, TRAIN + '/freeze.json'), private=True)
    freeze = decode(freeze_raw)
    require(freeze.get('schema_version') == 1 and freeze.get('status') == 'accepted_external_training_frozen',
            'invalid_training_freeze')
    binding = freeze.get('binding', {})
    require(binding.get('proposal_sha256') == PROPOSAL_SHA256 and binding.get('private_audit_index_sha256') == INDEX_SHA256,
            'training_binding_changed')
    # Validate the exact input inventory before opening any recorded input path.
    # A forged/edited freeze must not turn verification into a protected-label or
    # protected-image reader, even if its invented content hash is correct.
    proposal_raw = read_bytes(child(base, PROPOSAL), private=True)
    require(digest(proposal_raw) == PROPOSAL_SHA256, 'proposal_hash_changed')
    proposal = decode(proposal_raw)
    expected_inputs = {PROPOSAL, PROPOSAL_SUMMARY, AUDIT_INDEX, *FREEZE_NAMES, *SOURCE_NAMES,
        *(DOWNLOADS + '/' + name for name in ('download_summary.json', 'receipts.json', 'authorization.json', 'attempts.jsonl')),
        *(entry['planned_destination'] for entry in proposal['entries'])}
    require(set(binding.get('inputs_sha256', {})) == expected_inputs, 'training_input_inventory_changed')
    require(binding['inputs_sha256'][PROPOSAL] == PROPOSAL_SHA256
            and binding['inputs_sha256'][PROPOSAL_SUMMARY] == SUMMARY_SHA256
            and binding['inputs_sha256'][AUDIT_INDEX] == INDEX_SHA256
            and all(binding['inputs_sha256'][name] == expected for name, expected in proposal['original_frozen_hashes'].items()),
            'training_pinned_inputs_changed')
    require(set(binding.get('source_sha256', {})) == set(SOURCE_NAMES), 'training_source_inventory_changed')
    for name, value in binding['source_sha256'].items():
        require(digest(read_bytes(child(base, name))) == value, 'training_source_changed')
    # Recheck original frozen metadata files and acquisition receipts by hashes.
    # Candidate input hashes are safe; protected images never appear here.
    for name, value in binding.get('inputs_sha256', {}).items():
        require(digest(read_bytes(child(base, name))) == value, 'training_input_changed')
    require(set(binding.get('raw_metadata_sha256', {})) == set(RAW_NAMES), 'training_raw_source_inventory_changed')
    for name, value in binding['raw_metadata_sha256'].items():
        require(digest(read_bytes(child(base.parents[1], name))) == value, 'training_raw_source_changed')
    artifacts = freeze.get('artifacts', {})
    required = {'manifest.jsonl', 'labels.json', 'ingredients.json', 'catalog.json', 'fallback.json', 'audit.json'}
    require(required <= set(artifacts), 'training_artifact_inventory_incomplete')
    for name, value in artifacts.items():
        require(name in required or re.fullmatch(r'images/[0-9a-f]{64}\.png', name), 'unexpected_training_artifact')
        require(digest(read_bytes(child(release, name), private=True)) == value, 'training_artifact_changed')
    inventory = list(release.rglob('*'))
    require(not any(path.is_symlink() for path in inventory), 'training_symlink_rejected')
    require({str(path.relative_to(release)) for path in inventory if path.is_dir()} == {'images'},
            'training_directory_inventory_changed')
    actual = {str(path.relative_to(release)) for path in inventory if path.is_file()}
    require(actual == set(artifacts) | {'freeze.json'}, 'training_inventory_changed')
    audit = decode(read_bytes(release / 'audit.json', private=True))
    exception_count = freeze.get('data_quality_exception_count')
    require(type(exception_count) is int and exception_count == EXPECTED_EXCEPTION_COUNT
            and binding.get('policy', {}).get('data_quality_exception') == TRAINING_DATA_EXCEPTION
            and binding.get('policy', {}).get('expected_data_quality_exception_count') == EXPECTED_EXCEPTION_COUNT
            and binding.get('data_quality_exception_count') == exception_count
            and audit.get('data_quality_exception_policy') == TRAINING_DATA_EXCEPTION
            and audit.get('expected_data_quality_exception_count') == EXPECTED_EXCEPTION_COUNT
            and audit.get('data_quality_exception_count') == exception_count
            and audit.get('data_quality_exceptions') == [exception_record()] * exception_count,
            'training_data_quality_exception_binding_changed')
    if exception_count:
        require(binding['raw_metadata_sha256'].get(TRAINING_DATA_EXCEPTION['raw_source_relative_path'])
                == TRAINING_DATA_EXCEPTION['raw_source_sha256'], 'registered_exception_source_hash_mismatch')
    rows = [decode(line) for line in read_bytes(release / 'manifest.jsonl').splitlines()]
    require(len(rows) == freeze.get('accepted_images') and len(rows) >= MIN_GROUPS
            and len({row['group_id'] for row in rows}) == freeze.get('accepted_groups')
            and freeze['accepted_groups'] >= MIN_GROUPS
            and all(row['split'] == 'train' and row['image_path'] == TRAIN + '/images/' + row['image_sha256'] + '.png'
                    and artifacts.get('images/' + row['image_sha256'] + '.png') == row['image_sha256'] for row in rows),
            'training_manifest_contract_changed')
    return {'status': 'accepted_external_training_verified', 'accepted_images': freeze['accepted_images'],
        'accepted_groups': freeze['accepted_groups'], 'quarantined_images': freeze['quarantined_images'],
        'training_catalog_size': freeze['training_catalog_size'], 'freeze_sha256': digest(freeze_raw),
        'data_quality_exception_count': exception_count,
        'proposal_sha256': PROPOSAL_SHA256, 'protected_images_or_labels_opened': False,
        'api_calls': 0, 'automatic_replacements': 0}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--prepare', action='store_true')
    group.add_argument('--verify-only', action='store_true')
    args = parser.parse_args(argv)
    try:
        result = prepare() if args.prepare else verify_train_only()
    except TrainDataError as error:
        print(json.dumps({'status': 'blocked', 'error_code': str(error)}, sort_keys=True))
        return 2
    except Exception as error:
        print(json.dumps({'status': 'blocked', 'error_code': 'unexpected_' + type(error).__name__}, sort_keys=True))
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
