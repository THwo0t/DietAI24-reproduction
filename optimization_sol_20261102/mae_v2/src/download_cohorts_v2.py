"""Authorized exact-proposal downloader; private durable attempt/budget ledger.

Importing this module performs no I/O. Network access requires authorized=True.
Retries and byte reservations survive process death. CLI stdout is aggregates
only; no URLs, dish IDs, image contents, response text, headers or credentials.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import time
import urllib.error
import urllib.request

from PIL import Image

import cohorts_v2 as c


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def append_event(path, event):
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    if path.is_symlink():
        c.fail('unsafe_download_ledger')
    fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    try:
        if os.fstat(fd).st_mode & 0o077:
            c.fail('unsafe_download_ledger_permissions')
        with os.fdopen(fd, 'a', encoding='utf-8', closefd=False) as handle:
            handle.write(json.dumps(event, sort_keys=True, allow_nan=False) + '\n')
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        os.close(fd)


def validate_image(path, dish):
    if not 0 < Path(path).stat().st_size <= c.MAX_IMAGE_BYTES:
        c.fail('download_image_byte_limit')
    try:
        with Image.open(path) as image:
            if image.format != 'PNG' or image.mode != 'RGB' or image.size != (640, 480):
                c.fail('download_image_format_mismatch')
            image.verify()
    except c.AuditError:
        raise
    except Exception:
        c.fail('download_image_decode_failed')
    return c.image_fingerprint(path, dish)


def read_ledger(path, proposal_ids):
    attempts, completed = {}, {}
    reserved = actual = 0
    if not path.exists():
        return attempts, completed, reserved, actual
    if path.is_symlink() or path.stat().st_mode & 0o077:
        c.fail('unsafe_download_ledger_permissions')
    try:
        records = [json.loads(line) for line in path.read_text().splitlines()]
        for event in records:
            dish = event['dish_id']
            attempt = event['attempt']
            if dish not in proposal_ids or type(attempt) is not int or attempt not in range(1, 4):
                c.fail('invalid_download_ledger_record')
            if event['event'] == 'start':
                if attempt != attempts.get(dish, 0) + 1:
                    c.fail('invalid_download_attempt_sequence')
                attempts[dish] = attempt
            elif attempts.get(dish) != attempt:
                c.fail('invalid_download_ledger_record')
            if event['event'] in ('reserve', 'received'):
                amount = event['bytes']
                if type(amount) is not int or amount < 0:
                    c.fail('invalid_download_ledger_record')
                if event['event'] == 'reserve':
                    reserved += amount
                else:
                    actual += amount
            elif event['event'] == 'complete':
                completed[dish] = event['bytes_sha256']
            elif event['event'] not in ('start', 'failed'):
                c.fail('invalid_download_ledger_record')
    except c.AuditError:
        raise
    except Exception:
        c.fail('unreadable_download_ledger')
    if actual > reserved:
        c.fail('download_ledger_budget_inconsistency')
    return attempts, completed, reserved, actual


def download(*, v2_root=None, authorized=False, max_total_bytes=None,
             opener=None, sleep_fn=time.sleep, finalize=True):
    if not authorized:
        c.fail('explicit_download_authorization_required')
    base = Path(v2_root or c.V2).resolve()
    proposal_path = c.child(base, 'data/freeze/cohort_proposal.json')
    summary = json.loads(c.child(base, 'evidence/audit_summary.json').read_text())
    if c.sha256(proposal_path) != summary['proposal_sha256']:
        c.fail('download_proposal_hash_mismatch')
    proposal = json.loads(proposal_path.read_text())
    entries = proposal['downloads']
    if len(entries) != summary['downloads']['exact_file_count']:
        c.fail('download_proposal_count_mismatch')
    ceiling = len(entries) * c.MAX_IMAGE_BYTES
    if type(max_total_bytes) is not int or not 0 < max_total_bytes <= ceiling:
        c.fail('explicit_valid_download_byte_budget_required')
    ids, destinations = set(), set()
    for entry in entries:
        dish = entry['dish_id']
        if not c.DISH.fullmatch(dish) or dish in ids:
            c.fail('invalid_download_proposal')
        expected_destination = f'data/incoming/{c.rank("incoming", dish)}/rgb.png'
        if (entry['source_url'] != f'{c.BASE_URL}/{dish}/rgb.png'
                or entry['destination'] != expected_destination
                or entry['max_bytes'] != c.MAX_IMAGE_BYTES):
            c.fail('invalid_download_proposal')
        if entry['destination'] in destinations:
            c.fail('duplicate_download_destination')
        ids.add(dish)
        destinations.add(entry['destination'])
    authorization = {'proposal_sha256': c.sha256(proposal_path),
        'file_count': len(entries), 'maximum_total_transfer_bytes': max_total_bytes,
        'maximum_image_bytes': c.MAX_IMAGE_BYTES, 'maximum_attempts_per_url': 3,
        'policy': 'explicit current-user authorization; official fixed URLs only; no redirects or substitutions'}
    c.frozen_write(base, 'data/freeze/download_authorization.json', c.json_bytes(authorization), private=True)
    ledger_path = c.child(base, 'data/downloads/attempts.jsonl')
    attempts, completed, reserved, actual = read_ledger(ledger_path, ids)
    if reserved > max_total_bytes:
        c.fail('persisted_download_budget_exceeded')
    if opener is None:
        opener = urllib.request.build_opener(NoRedirect()).open
    for entry in entries:
        dish, url = entry['dish_id'], entry['source_url']
        destination = c.child(base, entry['destination'])
        if destination.exists():
            fingerprint = validate_image(destination, dish)
            if dish not in attempts:
                c.fail('unreceipted_incoming_image')
            if dish in completed and fingerprint['bytes_sha256'] != completed[dish]:
                c.fail('completed_incoming_image_changed')
            if dish not in completed:
                append_event(ledger_path, {'event': 'complete', 'dish_id': dish,
                    'attempt': attempts[dish], 'bytes_sha256': fingerprint['bytes_sha256'],
                    'rgb_sha256': fingerprint['rgb_sha256'], 'recovered_after_rename': True})
            continue
        if dish in completed:
            c.fail('completed_incoming_image_missing')
        if attempts.get(dish, 0) >= 3:
            c.fail('download_attempts_exhausted')
        destination.parent.mkdir(parents=True, exist_ok=True)
        os.chmod(destination.parent, 0o700)
        partial = destination.with_suffix('.png.part')
        if partial.is_symlink():
            c.fail('unsafe_download_partial_path')
        for attempt in range(attempts.get(dish, 0) + 1, 4):
            if reserved >= max_total_bytes:
                c.fail('download_byte_budget_exhausted')
            append_event(ledger_path, {'event': 'start', 'dish_id': dish, 'attempt': attempt})
            attempts[dish] = attempt
            transferred = 0
            try:
                request = urllib.request.Request(url, headers={'User-Agent': 'DietAI24-MAE-v2-data-preparation/1.0'})
                with opener(request, timeout=45) as response:
                    if response.geturl() != url:
                        c.fail('download_redirect_rejected')
                    if response.status != 200:
                        if response.status == 429 or response.status >= 500:
                            raise OSError('retryable_status')
                        c.fail('download_nonretryable_http_status')
                    declared_header = response.headers.get('Content-Length')
                    try:
                        declared = int(declared_header) if declared_header is not None else None
                    except (ValueError, TypeError):
                        c.fail('invalid_download_content_length')
                    if declared is not None and (declared < 0 or declared > c.MAX_IMAGE_BYTES):
                        c.fail('download_image_byte_limit')
                    fd = os.open(partial, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
                    with os.fdopen(fd, 'wb') as handle:
                        while declared is None or transferred < declared:
                            allowance = min(65536, c.MAX_IMAGE_BYTES - transferred,
                                            max_total_bytes - reserved)
                            if declared is not None:
                                allowance = min(allowance, declared - transferred)
                            if allowance <= 0:
                                c.fail('download_byte_budget_or_image_limit')
                            # Reserving before each read makes a kill/restart
                            # conservative: unrecorded received bytes stay charged.
                            append_event(ledger_path, {'event': 'reserve', 'dish_id': dish,
                                'attempt': attempt, 'bytes': allowance})
                            reserved += allowance
                            block = response.read(allowance)
                            if len(block) > allowance:
                                c.fail('download_reader_exceeded_reserved_bytes')
                            if not block:
                                break
                            handle.write(block)
                            transferred += len(block)
                            actual += len(block)
                            append_event(ledger_path, {'event': 'received', 'dish_id': dish,
                                'attempt': attempt, 'bytes': len(block)})
                        handle.flush()
                        os.fsync(handle.fileno())
                    if declared is not None and transferred != declared:
                        raise OSError('incomplete_body')
                fingerprint = validate_image(partial, dish)
                os.link(partial, destination)  # never replace an existing image
                partial.unlink()
                append_event(ledger_path, {'event': 'complete', 'dish_id': dish, 'attempt': attempt,
                    'bytes_sha256': fingerprint['bytes_sha256'], 'rgb_sha256': fingerprint['rgb_sha256']})
                completed[dish] = fingerprint['bytes_sha256']
                break
            except c.AuditError:
                append_event(ledger_path, {'event': 'failed', 'dish_id': dish,
                    'attempt': attempt, 'category': 'integrity_or_budget'})
                partial.unlink(missing_ok=True)
                raise
            except Exception as error:
                retryable = not isinstance(error, urllib.error.HTTPError) or (
                    error.code in (408, 429) or 500 <= error.code < 600)
                append_event(ledger_path, {'event': 'failed', 'dish_id': dish,
                    'attempt': attempt, 'category': 'transport' if retryable else 'nonretryable_http'})
                partial.unlink(missing_ok=True)
                if not retryable:
                    c.fail('download_nonretryable_http_status')
                if attempt == 3:
                    c.fail('download_attempts_exhausted')
                sleep_fn(2 if attempt == 1 else 8)
    result = {'status': 'downloads_verified', 'completed_files': len(entries),
        'received_bytes_recorded': actual, 'reserved_transfer_bytes': reserved,
        'maximum_total_transfer_bytes': max_total_bytes, 'proposal_sha256': c.sha256(proposal_path),
        'ledger_sha256': c.sha256(ledger_path)}
    c.frozen_write(base, 'evidence/download_summary.json', c.json_bytes(result))
    if finalize:
        result['cohorts'] = c.prepare(v2_root=base)
        result['status'] = 'validation_frozen'
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--authorized', action='store_true')
    parser.add_argument('--max-total-bytes', type=int)
    parser.add_argument('--no-finalize', action='store_true')
    args = parser.parse_args()
    try:
        result = download(authorized=args.authorized, max_total_bytes=args.max_total_bytes,
                          finalize=not args.no_finalize)
    except c.AuditError as error:
        print(json.dumps({'status': 'blocked', 'error_code': str(error)}, sort_keys=True))
        return 2
    except Exception as error:
        print(json.dumps({'status': 'blocked', 'error_code': 'unexpected_' + type(error).__name__}, sort_keys=True))
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
