#!/usr/bin/env python3
"""Pinned training-download action; default is entirely offline and read only.

--authorized is an operator assertion of current user approval, not a substitute
for obtaining it. Only exact proposal URLs are requested. Incoming bytes remain
quarantined and are never released to training by this tool. The transfer cap
covers application response-body reads, not TCP/TLS/HTTP framing overhead.
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
import tempfile
import time
import urllib.error
import urllib.request

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
PROPOSAL = 'round4/proposal/private_train_pool_proposal.json'
SUMMARY = 'round4/proposal/raw_rgb_summary.json'
PROPOSAL_SHA256 = 'eddf9a644114f5b4aecc4d906dbdec6ee0eaecd80b97e23743d9edf663e03eb0'
SUMMARY_SHA256 = '3e3d3dc8f66faf1176971480ad988925c5b63d5dc92f8673a3b75dd54c70f810'
FILE_COUNT = 230
CACHED_TOTAL_BYTES = 104830902
MAX_TOTAL_BYTES = 350000000
MAX_IMAGE_BYTES = 5000000
MAX_ATTEMPTS = 3
BASE_URL = 'https://storage.googleapis.com/nutrition5k_dataset/nutrition5k_dataset/imagery/realsense_overhead'
SEED = 'dietai24-mae-v2-round4-train600-20261103'
DOWNLOADS = 'round4/downloads'
FROZEN_PATHS = frozenset({
    'data/cohorts/dev_freeze.json',
    'data/freeze/source_snapshot.json',
    'data/freeze/final_source_snapshot.json',
    'data/freeze/validation_freeze.json',
})
ENTRY_KEYS = {'cached_object_bytes', 'dish_id', 'in_archived_available_frame', 'max_image_bytes',
              'original_component_id', 'pixel_verification', 'planned_destination', 'recipe_sha256',
              'screening_component_id', 'source_url'}


class DownloadError(Exception):
    """Only fixed non-sensitive error codes cross the CLI boundary."""


def fail(code):
    raise DownloadError(code)


def decode(raw):
    def pairs(values):
        out = {}
        for key, value in values:
            if key in out:
                fail('duplicate_json_key')
            out[key] = value
        return out
    try:
        return json.loads(raw, object_pairs_hook=pairs,
                          parse_constant=lambda _: fail('nonfinite_json'))
    except DownloadError:
        raise
    except Exception:
        fail('unreadable_json')


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def child(base, relative):
    base, relative = Path(base), Path(relative)
    if base.is_symlink() or base.resolve() != base or not base.is_dir():
        fail('unsafe_root')
    if relative.is_absolute() or '..' in relative.parts or not relative.parts:
        fail('unsafe_relative_path')
    path = base
    for part in relative.parts:
        path = path / part
        if path.is_symlink():
            fail('symlink_rejected')
    if path.resolve() != path or not path.is_relative_to(base):
        fail('path_escape_rejected')
    return path


def regular(path, private=False):
    if path.is_symlink() or not path.is_file() or not stat.S_ISREG(path.stat().st_mode):
        fail('regular_file_required')
    if private and stat.S_IMODE(path.stat().st_mode) != 0o600:
        fail('private_file_permissions_required')
    return path


def private_dir(base, relative):
    path = child(base, relative)
    parts = Path(relative).parts
    for index in range(1, len(parts) + 1):
        current = child(base, Path(*parts[:index]))
        if current.exists():
            if not current.is_dir():
                fail('directory_required')
            # Existing shared round4/proposal/tool directories are untouched.
            if index >= 2 and stat.S_IMODE(current.stat().st_mode) != 0o700:
                fail('private_directory_permissions_required')
        else:
            current.mkdir(mode=0o700)
    return path


def fsync_dir(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def immutable_json(base, relative, value):
    path = child(base, relative)
    if path.exists():
        if decode(regular(path, private=True).read_bytes()) != value:
            fail('immutable_download_binding_changed')
        return
    private_dir(base, Path(relative).parent)
    raw = (json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False) + '\n').encode()
    fd, temporary = tempfile.mkstemp(prefix='.train-download-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o600)
        os.link(temporary, path)
        fsync_dir(path.parent)
    finally:
        Path(temporary).unlink(missing_ok=True)


def load_plan(base):
    proposal_raw = regular(child(base, PROPOSAL)).read_bytes()
    summary_raw = regular(child(base, SUMMARY)).read_bytes()
    if digest(proposal_raw) != PROPOSAL_SHA256:
        fail('proposal_hash_mismatch')
    if digest(summary_raw) != SUMMARY_SHA256:
        fail('summary_hash_mismatch')
    proposal, summary = decode(proposal_raw), decode(summary_raw)
    entries = proposal.get('entries')
    if (proposal.get('schema_version') != 1 or proposal.get('seed') != SEED
            or proposal.get('status') != 'awaiting_new_download_authorization'
            or proposal.get('actual_images_and_screening_groups') != FILE_COUNT
            or not isinstance(entries, list) or len(entries) != FILE_COUNT
            or summary.get('proposal_relative_path') != PROPOSAL
            or summary.get('proposal_sha256') != PROPOSAL_SHA256
            or summary.get('status') != 'awaiting_new_download_authorization'
            or summary.get('seed') != SEED
            or any(summary.get(k) != FILE_COUNT for k in ('new_download_file_count', 'selected_groups', 'selected_images'))
            or summary.get('cached_download_byte_estimate') != CACHED_TOTAL_BYTES
            or summary.get('maximum_per_image_bytes') != MAX_IMAGE_BYTES
            or summary.get('selected_already_local') != 0 or summary.get('downloaded_images') != 0
            or summary.get('new_download_authorization_received') is not False
            or summary.get('automatic_replacement_permitted') is not False
            or summary.get('postdownload_blind_dedup_and_quarantine_required') is not True
            or summary.get('source_freezes_unchanged') is not True
            or proposal.get('original_frozen_hashes') != summary.get('original_frozen_hashes')):
        fail('proposal_summary_contract_mismatch')
    # The proposal auditor resolves these four keys against mae_v2, not the
    # repository or round4 directory. Hash only the freeze metadata bytes;
    # never follow their contents to images, manifests or label files.
    frozen = proposal.get('original_frozen_hashes')
    if not isinstance(frozen, dict) or set(frozen) != FROZEN_PATHS:
        fail('source_freeze_inventory_mismatch')
    for relative, expected in frozen.items():
        if (not isinstance(expected, str) or re.fullmatch(r'[0-9a-f]{64}', expected) is None
                or digest(regular(child(base, relative)).read_bytes()) != expected):
            fail('source_freeze_changed')
    ids, destinations, groups = set(), set(), set()
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != ENTRY_KEYS:
            fail('invalid_proposal_entry')
        dish, size = entry['dish_id'], entry['cached_object_bytes']
        if (not isinstance(dish, str) or re.fullmatch(r'dish_[0-9]{10}', dish) is None
                or dish in ids or type(size) is not int or not 0 < size < MAX_IMAGE_BYTES
                or entry['max_image_bytes'] != MAX_IMAGE_BYTES
                or entry['pixel_verification'] != 'pending_authorized_download'
                or type(entry['in_archived_available_frame']) is not bool
                or entry['source_url'] != f'{BASE_URL}/{dish}/rgb.png'):
            fail('invalid_proposal_entry')
        destination = 'round4/data/incoming/' + digest((SEED + '|incoming|' + dish).encode()) + '/rgb.png'
        if entry['planned_destination'] != destination or destination in destinations:
            fail('invalid_proposal_destination')
        child(base, destination)
        group = entry['screening_component_id']
        if not isinstance(group, str) or not group or group in groups:
            fail('duplicate_or_invalid_screening_group')
        ids.add(dish)
        destinations.add(destination)
        groups.add(group)
    if sum(e['cached_object_bytes'] for e in entries) != CACHED_TOTAL_BYTES:
        fail('cached_byte_total_mismatch')
    return entries


def dry_summary():
    return {'status': 'offline_dry_run', 'network_requests': 0, 'files_written': 0,
            'file_count': FILE_COUNT, 'cached_expected_payload_bytes': CACHED_TOTAL_BYTES,
            'maximum_total_response_body_transfer_bytes': MAX_TOTAL_BYTES,
            'maximum_attempts_per_file': MAX_ATTEMPTS, 'maximum_image_bytes': MAX_IMAGE_BYTES,
            'all_three_attempt_reservations_bytes': MAX_ATTEMPTS * (CACHED_TOTAL_BYTES + FILE_COUNT),
            'proposal_sha256': PROPOSAL_SHA256, 'raw_rgb_summary_sha256': SUMMARY_SHA256,
            'training_release': False, 'requires_new_user_download_authorization': True,
            'next_gate': 'blind_rgb_dedup_and_component_quarantine'}


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def append_event(base, event):
    path = child(base, DOWNLOADS + '/attempts.jsonl')
    fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        if stat.S_IMODE(os.fstat(fd).st_mode) != 0o600:
            fail('private_ledger_permissions_required')
        raw = (json.dumps(event, sort_keys=True, allow_nan=False) + '\n').encode()
        with os.fdopen(fd, 'ab', closefd=False) as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
    finally:
        os.close(fd)
    fsync_dir(path.parent)


def read_ledger(base, entries):
    expected = {e['dish_id']: e['cached_object_bytes'] for e in entries}
    states = {dish: {'attempt': 0, 'status': 'new', 'received': 0} for dish in expected}
    reserved = received = 0
    path = child(base, DOWNLOADS + '/attempts.jsonl')
    if not path.exists():
        return states, reserved, received
    raw = regular(path, private=True).read_bytes()
    if raw and not raw.endswith(b'\n'):
        fail('truncated_download_ledger')
    for line in raw.splitlines():
        event = decode(line)
        if not isinstance(event, dict):
            fail('invalid_download_ledger')
        dish, attempt, kind = event.get('dish_id'), event.get('attempt'), event.get('event')
        if dish not in expected or type(attempt) is not int or attempt not in range(1, MAX_ATTEMPTS + 1):
            fail('invalid_download_ledger')
        state = states[dish]
        if kind == 'start':
            if (set(event) != {'event', 'dish_id', 'attempt', 'reserved_bytes'}
                    or state['status'] not in ('new', 'retryable_failure')
                    or attempt != state['attempt'] + 1
                    or event['reserved_bytes'] != expected[dish] + 1):
                fail('invalid_attempt_sequence_or_reservation')
            reserved += event['reserved_bytes']
            state.update(attempt=attempt, status='started', received=0)
        elif attempt != state['attempt']:
            fail('invalid_attempt_sequence')
        elif kind == 'received':
            if (set(event) != {'event', 'dish_id', 'attempt', 'bytes'} or state['status'] != 'started'
                    or type(event['bytes']) is not int or event['bytes'] <= 0):
                fail('invalid_received_event')
            state['received'] += event['bytes']
            received += event['bytes']
            if state['received'] > expected[dish] + 1:
                fail('received_exceeds_attempt_reservation')
        elif kind == 'ready':
            if (set(event) != {'event', 'dish_id', 'attempt', 'bytes_sha256', 'bytes'}
                    or state['status'] != 'started' or state['received'] != expected[dish]
                    or event['bytes'] != expected[dish]
                    or not isinstance(event['bytes_sha256'], str)
                    or re.fullmatch(r'[0-9a-f]{64}', event['bytes_sha256']) is None):
                fail('invalid_ready_receipt')
            state.update(status='ready', bytes_sha256=event['bytes_sha256'])
        elif kind == 'complete':
            if (set(event) != {'event', 'dish_id', 'attempt'} or state['status'] != 'ready'):
                fail('invalid_complete_receipt')
            state['status'] = 'complete'
        elif kind == 'failed':
            if (set(event) != {'event', 'dish_id', 'attempt', 'category', 'retryable'}
                    or state['status'] != 'started' or type(event['retryable']) is not bool
                    or not isinstance(event['category'], str)
                    or re.fullmatch(r'[a-z_]+', event['category']) is None):
                fail('invalid_failure_receipt')
            state.update(status='retryable_failure' if event['retryable'] else 'terminal_failure',
                         category=event['category'])
        else:
            fail('invalid_download_ledger_event')
    if received > reserved or reserved > MAX_TOTAL_BYTES:
        fail('persisted_budget_exceeded')
    return states, reserved, received


def verify_payload(path, expected, digest_expected):
    raw = regular(path, private=True).read_bytes()
    if len(raw) != expected or digest(raw) != digest_expected:
        fail('incoming_payload_changed')


def discard_partial(path):
    if path.exists():
        regular(path, private=True)
        path.unlink()
        fsync_dir(path.parent)


def finish_ready(base, entry, state):
    destination = child(base, entry['planned_destination'])
    partial = child(base, entry['planned_destination'] + '.part')
    if destination.exists():
        verify_payload(destination, entry['cached_object_bytes'], state['bytes_sha256'])
        if partial.exists():
            verify_payload(partial, entry['cached_object_bytes'], state['bytes_sha256'])
            discard_partial(partial)
    elif state['status'] == 'complete':
        fail('completed_incoming_payload_missing')
    elif partial.exists():
        verify_payload(partial, entry['cached_object_bytes'], state['bytes_sha256'])
        os.link(partial, destination)
        fsync_dir(destination.parent)
        discard_partial(partial)
    else:
        fail('ready_incoming_payload_missing')
    if state['status'] == 'ready':
        append_event(base, {'event': 'complete', 'dish_id': entry['dish_id'], 'attempt': state['attempt']})


def receive(base, entry, attempt, opener):
    """A whole-attempt reservation has already been fsynced before entry."""
    expected, url = entry['cached_object_bytes'], entry['source_url']
    partial = child(base, entry['planned_destination'] + '.part')
    request = urllib.request.Request(url, method='GET', headers={
        'User-Agent': 'DietAI24-round4-quarantined-training-download/1.0', 'Accept-Encoding': 'identity'})
    with opener(request, timeout=45) as response:
        if response.geturl() != url:
            fail('redirect_rejected')
        if response.status != 200:
            if response.status in (408, 429) or 500 <= response.status < 600:
                raise OSError('retryable_http')
            fail('nonretryable_http_status')
        length = response.headers.get('Content-Length')
        if not isinstance(length, str) or re.fullmatch(r'[0-9]+', length) is None or int(length) != expected:
            fail('cached_content_length_changed')
        if response.headers.get('Content-Encoding', 'identity').lower() != 'identity':
            fail('content_encoding_rejected')
        transferred = 0
        fd = os.open(partial, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'wb') as stream:
            while True:
                allowance = min(65536, expected + 1 - transferred)
                if allowance <= 0:
                    fail('body_exceeds_cached_size')
                block = response.read(allowance)
                if not isinstance(block, bytes) or len(block) > allowance:
                    fail('reader_exceeded_reserved_bytes')
                if not block:
                    break
                transferred += len(block)
                stream.write(block)
                append_event(base, {'event': 'received', 'dish_id': entry['dish_id'], 'attempt': attempt, 'bytes': len(block)})
                if transferred > expected:
                    fail('body_exceeds_cached_size')
            stream.flush()
            os.fsync(stream.fileno())
        if transferred != expected:
            fail('body_differs_from_cached_size')
    bytes_hash = digest(regular(partial, private=True).read_bytes())
    append_event(base, {'event': 'ready', 'dish_id': entry['dish_id'], 'attempt': attempt,
                        'bytes': expected, 'bytes_sha256': bytes_hash})


def download(*, root=None, authorized=False, opener=None, sleep_fn=time.sleep):
    base = Path(root) if root is not None else ROOT
    if type(authorized) is not bool:
        fail('authorization_must_be_boolean')
    entries = load_plan(base)
    if not authorized:
        return dry_summary()
    private_dir(base, DOWNLOADS)
    lock = child(base, DOWNLOADS + '/.lock')
    fd = os.open(lock, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'a+') as handle:
        if stat.S_IMODE(os.fstat(handle.fileno()).st_mode) != 0o600:
            fail('private_lock_permissions_required')
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            fail('download_already_running')
        authorization = {'schema_version': 1, 'status': 'operator_asserted_authorization',
                         'operator_asserted_current_user_authorization': True,
                         'proposal_sha256': PROPOSAL_SHA256, 'raw_rgb_summary_sha256': SUMMARY_SHA256,
                         'file_count': FILE_COUNT, 'cached_expected_payload_bytes': CACHED_TOTAL_BYTES,
                         'maximum_total_response_body_transfer_bytes': MAX_TOTAL_BYTES,
                         'maximum_attempts_per_file': MAX_ATTEMPTS, 'maximum_image_bytes': MAX_IMAGE_BYTES,
                         'training_release': False, 'pixel_verification_performed': False,
                         'next_gate': 'blind_rgb_dedup_and_component_quarantine',
                         'downloader_sha256': digest(Path(__file__).read_bytes())}
        immutable_json(base, DOWNLOADS + '/authorization.json', authorization)
        states, reserved, actual = read_ledger(base, entries)
        completed_summary = child(base, DOWNLOADS + '/download_summary.json')
        if completed_summary.exists():
            saved = decode(regular(completed_summary, private=True).read_bytes())
            ledger = regular(child(base, DOWNLOADS + '/attempts.jsonl'), private=True)
            if saved.get('ledger_sha256') != digest(ledger.read_bytes()):
                fail('completed_download_ledger_changed')
            for field, name in (('receipts_sha256', 'receipts.json'), ('authorization_sha256', 'authorization.json')):
                if saved.get(field) != digest(regular(child(base, DOWNLOADS + '/' + name), private=True).read_bytes()):
                    fail('completed_download_receipt_binding_changed')
        for entry in entries:
            dish = entry['dish_id']
            state = states[dish]
            destination = child(base, entry['planned_destination'])
            partial = child(base, entry['planned_destination'] + '.part')
            if state['status'] in ('ready', 'complete'):
                finish_ready(base, entry, state)
                continue
            if destination.exists():
                fail('unreceipted_incoming_payload')
            if state['status'] == 'terminal_failure':
                fail('persisted_terminal_download_failure')
            if state['status'] == 'started':
                append_event(base, {'event': 'failed', 'dish_id': dish, 'attempt': state['attempt'],
                                    'category': 'interrupted', 'retryable': True})
            private_dir(base, Path(entry['planned_destination']).parent)
            discard_partial(partial)
            if state['attempt'] >= MAX_ATTEMPTS:
                fail('download_attempts_exhausted')
            for attempt in range(state['attempt'] + 1, MAX_ATTEMPTS + 1):
                reservation = entry['cached_object_bytes'] + 1
                if reserved + reservation > MAX_TOTAL_BYTES:
                    fail('download_transfer_budget_exhausted')
                append_event(base, {'event': 'start', 'dish_id': dish, 'attempt': attempt,
                                    'reserved_bytes': reservation})
                reserved += reservation
                try:
                    if opener is None:
                        # Do not inherit proxy URLs, credentials or redirect behavior.
                        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect()).open
                    receive(base, entry, attempt, opener)
                except DownloadError as error:
                    append_event(base, {'event': 'failed', 'dish_id': dish, 'attempt': attempt,
                                        'category': str(error), 'retryable': False})
                    discard_partial(partial)
                    raise
                except Exception as error:
                    retryable = not isinstance(error, urllib.error.HTTPError) or error.code in (408, 429) or 500 <= error.code < 600
                    if isinstance(error, urllib.error.HTTPError):
                        error.close()
                    append_event(base, {'event': 'failed', 'dish_id': dish, 'attempt': attempt,
                                        'category': 'transport' if retryable else 'nonretryable_http',
                                        'retryable': retryable})
                    discard_partial(partial)
                    if not retryable:
                        fail('nonretryable_http_status')
                    if attempt == MAX_ATTEMPTS:
                        fail('download_attempts_exhausted')
                    sleep_fn(2 if attempt == 1 else 8)
                    continue
                latest, _, _ = read_ledger(base, entries)
                finish_ready(base, entry, latest[dish])
                break
        states, reserved, actual = read_ledger(base, entries)
        if any(state['status'] != 'complete' for state in states.values()):
            fail('download_completion_incomplete')
        load_plan(base)
        receipts = {'schema_version': 1, 'proposal_sha256': PROPOSAL_SHA256,
                    'raw_rgb_summary_sha256': SUMMARY_SHA256, 'training_release': False,
                    'pixel_verification_performed': False,
                    'entries': [{'dish_id': e['dish_id'], 'destination': e['planned_destination'],
                                 'source_url': e['source_url'], 'bytes': e['cached_object_bytes'],
                                 'bytes_sha256': states[e['dish_id']]['bytes_sha256'],
                                 'attempts_consumed': states[e['dish_id']]['attempt']}
                                for e in entries]}
        immutable_json(base, DOWNLOADS + '/receipts.json', receipts)
        result = {'status': 'incoming_bytes_complete_pending_blind_dedup', 'completed_files': FILE_COUNT,
                  'proposal_sha256': PROPOSAL_SHA256, 'raw_rgb_summary_sha256': SUMMARY_SHA256,
                  'cached_expected_payload_bytes': CACHED_TOTAL_BYTES,
                  'received_body_bytes_recorded': actual, 'reserved_response_body_bytes': reserved,
                  'maximum_total_response_body_transfer_bytes': MAX_TOTAL_BYTES,
                  'attempts_consumed': sum(s['attempt'] for s in states.values()),
                  'maximum_attempts_per_file': MAX_ATTEMPTS, 'maximum_image_bytes': MAX_IMAGE_BYTES,
                  'ledger_sha256': digest(regular(child(base, DOWNLOADS + '/attempts.jsonl'), private=True).read_bytes()),
                  'receipts_sha256': digest(regular(child(base, DOWNLOADS + '/receipts.json'), private=True).read_bytes()),
                  'authorization_sha256': digest(regular(child(base, DOWNLOADS + '/authorization.json'), private=True).read_bytes()),
                  'training_release': False, 'pixel_verification_performed': False,
                  'next_gate': 'blind_rgb_dedup_and_component_quarantine'}
        immutable_json(base, DOWNLOADS + '/download_summary.json', result)
        return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--authorized', action='store_true', help='Only after current user approval of this exact action')
    args = parser.parse_args(argv)
    try:
        result = download(authorized=args.authorized)
    except DownloadError as error:
        print(json.dumps({'status': 'blocked', 'error_code': str(error)}, sort_keys=True))
        return 2
    except Exception as error:
        print(json.dumps({'status': 'blocked', 'error_code': 'unexpected_' + type(error).__name__}, sort_keys=True))
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
