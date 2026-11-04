"""Read-only, snapshot-anchored request metadata accounting; never imports service code."""
import hashlib
import json
import os
import re
import stat
from collections import Counter
from pathlib import Path

LIMIT = 64 * 1024 * 1024
TOKEN_FIELDS = ('prompt_tokens', 'completion_tokens', 'total_tokens', 'reasoning_tokens', 'cached_tokens')


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
        allow_nan=False, separators=(',', ':')).encode()).hexdigest()


def _read(path):
    path = Path(path).absolute()
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError('symlink_refused')
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise ValueError('regular_file_required')
        with os.fdopen(fd, 'rb', closefd=False) as stream:
            raw = stream.read(LIMIT + 1)
        if len(raw) > LIMIT:
            raise ValueError('file_size_limit')
        return raw
    finally:
        os.close(fd)


def _json(raw):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('duplicate_json_key')
            result[key] = value
        return result
    return json.loads(raw, object_pairs_hook=unique,
        parse_constant=lambda _: (_ for _ in ()).throw(ValueError('nonfinite_json')))


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _usage(body, role=None):
    usage = body.get('usage') if isinstance(body, dict) else None
    if usage is None:
        return {}, 'missing'
    if not isinstance(usage, dict):
        return {}, 'invalid'
    values, invalid = {}, False
    for field in TOKEN_FIELDS:
        source = usage
        if field in ('reasoning_tokens', 'cached_tokens'):
            source = usage.get('completion_tokens_details' if field == 'reasoning_tokens'
                               else 'prompt_tokens_details', {})
            if source is None:
                source = {}
            if not isinstance(source, dict):
                invalid = True
                continue
        if field in source:
            value = source[field]
            if type(value) is not int or value < 0:
                invalid = True
            else:
                values[field] = value
    if invalid:
        return values, 'invalid'
    required = ('prompt_tokens', 'total_tokens') if role == 'embedding' else TOKEN_FIELDS[:3]
    return values, 'complete' if all(k in values for k in required) else 'partial'


def _aggregate(rows):
    result = {'reservations': len(rows), 'anchored_responses': 0, 'pending': 0,
              'kind_counts': {}, 'role_counts': {}, 'status_counts': {}, 'model_counts': {},
              'usage_state_counts': {}, 'usage': dict.fromkeys(TOKEN_FIELDS, 0),
              'usage_field_observations': dict.fromkeys(TOKEN_FIELDS, 0)}
    for row in rows:
        for target, key in (('role_counts', 'role'), ('kind_counts', 'kind'),
                            ('status_counts', 'status'), ('model_counts', 'model'),
                            ('usage_state_counts', 'usage_state')):
            if key in row:
                label = str(row[key])
                result[target][label] = result[target].get(label, 0) + 1
        result['anchored_responses' if row['anchored'] else 'pending'] += 1
        for key, value in row.get('usage', {}).items():
            result['usage'][key] += value
            result['usage_field_observations'][key] += 1
    return result


def summarize(directory, freeze_path):
    """Capture admission once. Private snapshot bytes must never be published."""
    directory = Path(directory)
    admission_raw, freeze_raw = _read(directory / 'admission.json'), _read(freeze_path)
    admission, freeze = _json(admission_raw), _json(freeze_raw)
    science_sha = fingerprint(freeze)
    if ('namespace' in admission or 'namespace' in freeze) and admission.get('namespace') != freeze.get('namespace'):
        raise ValueError('namespace_mismatch')
    if admission.get('binding') != science_sha:
        raise ValueError('freeze_binding_mismatch')
    slots, bindings = admission['allowed_slots'], admission['bindings']
    if freeze.get('allowed_slots_sha256') != fingerprint(slots):
        raise ValueError('allowed_slots_binding_mismatch')
    reservations, anchors = admission['reservations'], admission['outcomes']
    private, rows, ids, successful_payloads = {}, [], set(), set()
    for sid, info in slots.items():
        private[sid] = {**info, 'h': bindings.get(sid), 'responses': []}
    for reservation in reservations:
        rid, sid, h = (reservation[k] for k in ('id', 'slot', 'payload_hash'))
        if (not isinstance(rid, str) or not re.fullmatch(r'[A-Za-z0-9_-]+', rid)
                or rid in ids or sid not in slots or bindings.get(sid) != h
                or reservation['role'] != slots[sid]['role']):
            raise ValueError('invalid_reservation')
        ids.add(rid)
        row = {'role': reservation['role'], 'anchored': rid in anchors}
        if rid in anchors:
            raw = _read(directory / 'outcomes' / (rid + '.json'))
            if _sha(raw) != anchors[rid]:
                raise ValueError('outcome_anchor_mismatch')
            outcome = _json(raw)
            if outcome.get('reservation') != reservation:
                raise ValueError('outcome_reservation_mismatch')
            kind, status = outcome.get('kind'), outcome.get('status')
            if (kind not in ('success', 'retryable', 'fatal')
                    or not (type(status) is int or status is None)
                    or (kind == 'success' and status != 200)):
                raise ValueError('invalid_outcome_metadata')
            body = outcome.get('body')
            usage, state = _usage(body, reservation['role'])
            row.update(kind=kind, status=status, usage=usage, usage_state=state)
            if kind == 'success':
                successful_payloads.add(h)
            if isinstance(body, dict) and isinstance(body.get('model'), str):
                row['model'] = body['model']
        private[sid]['responses'].append(row)
        rows.append(row)
    if not set(anchors) <= ids or not set(bindings) <= set(slots):
        raise ValueError('orphan_anchor_or_binding')
    for slot in private.values():
        slot['summary'] = _aggregate(slot['responses'])
        slot['successful'] = slot['h'] is not None and slot['h'] in successful_payloads
    by_role = {role: _aggregate([row for row in rows if row['role'] == role])
               for role in sorted({row['role'] for row in rows})}
    return {'public': {**_aggregate(rows), 'by_role': by_role, 'admission_sha256': _sha(admission_raw),
                       'freeze_sha256': _sha(freeze_raw), 'science_sha256': science_sha,
                       'source_hashes_replayed': False},
            'PRIVATE': {'slots': private, 'admission_raw': admission_raw, 'freeze_raw': freeze_raw}}


def compare(a, b):
    """Compare logical completed slots, without authorizing cache import or reuse."""
    old, new = a['PRIVATE']['slots'], b['PRIVATE']['slots']
    counts = Counter(old_successful_slots=0, completed_same_slot=0,
                     same_payload_hash=0, different_payload_hash=0, not_completed=0)
    details = []
    for sid, before in old.items():
        if not before['successful']:
            continue
        counts['old_successful_slots'] += 1
        after = new.get(sid)
        keys = ('sample_id', 'stage', 'ordinal', 'role', 'image_payload_sha256')
        complete = after is not None and after['successful'] and all(before.get(k) == after.get(k) for k in keys)
        same = complete and before['h'] == after['h']
        if complete:
            counts['completed_same_slot'] += 1
            counts['same_payload_hash' if same else 'different_payload_hash'] += 1
        else:
            counts['not_completed'] += 1
        details.append({'sid': sid, 'old_h': before['h'], 'new_h': after['h'] if after else None,
                        'completed_same_slot': complete, 'same_payload_hash': bool(same)})
    return {'public': dict(counts), 'PRIVATE': {'details': details}}
