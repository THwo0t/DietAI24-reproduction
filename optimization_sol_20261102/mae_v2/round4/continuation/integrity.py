"""Private, hash-only registration checks for the one-time service continuation.

No labels, images, provider construction, or mutation of the original run.
Registration is prepared by the coordinator after all original workers stop.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
import stat

from round4.src.artifacts import ArtifactError, decode

REGISTRATION = 'round4/continuation/private_registration.json'
PROTOCOL = 'round4/continuation/SERVICE_CONTINUATION_PROTOCOL.md'
SNAPSHOT = 'round4/continuation/private_old_stage_snapshot.json'
OLD_RUN = 'round4/runs/J'
NEW_RUN = 'round4/runs/J_service_continuation'
PROVIDER_RUN = 'round4/provider/J_service_continuation'
AUDIT = PROVIDER_RUN + '/reservations.jsonl'
NAMESPACE = 'external-gallery-r4.1'
NEW_SOURCES = tuple('round4/continuation/' + p for p in (
    'provider.py', 'runner.py', 'integrity.py', 'evaluate.py',
    'tests/test_provider.py', 'tests/test_runner.py', 'tests/test_evaluate.py'))
HEX = re.compile(r'[0-9a-f]{64}\Z')


def require(condition, code):
    if not condition:
        raise ArtifactError(code)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def counter_bytes(value):
    return (json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False) + '\n').encode()


def original_counter_bytes(value):
    """Reconstruct the frozen Provider's exact four-key, unsorted encoding.

    A registration writer may sort the nested state keys. Reintroduce the
    insertion order in opt_provider._reserve_attempt before its atomic_json
    encoding. This binds the semantic baseline to its original byte hash even
    after the live counter has advanced; new sorted counter_bytes is different.
    """
    ordered = {key: value[key] for key in ('request_hash', 'attempts', 'last_reserved', 'namespace')}
    return (json.dumps(ordered, indent=2, ensure_ascii=False, allow_nan=False) + '\n').encode()


def path(root, name, *, exists=True):
    root, relative = Path(root), Path(name)
    require(root.resolve() == root and root.is_dir() and not root.is_symlink(), 'unsafe_root')
    require(not relative.is_absolute() and '..' not in relative.parts and str(relative) != '.',
            'unsafe_registration_path')
    result = root / relative
    current = root
    for part in relative.parts:
        current /= part
        require(not current.is_symlink(), 'registration_symlink_rejected')
    require(result.resolve() == result, 'noncanonical_registration_path')
    if exists:
        require(result.is_file() and stat.S_ISREG(result.stat().st_mode), 'registered_file_missing')
    return result


def read(root, name):
    return path(root, name).read_bytes()


def _hashes(value):
    require(isinstance(value, dict) and all(isinstance(k, str) and isinstance(v, str)
            and HEX.fullmatch(v) for k, v in value.items()), 'invalid_registered_hash_map')


def policy(exception_hash):
    return {'namespace': NAMESPACE, 'default_max_total_attempts': 3,
            'exception': {'role': 'chat', 'request_hash': exception_hash, 'max_total_attempts': 4},
            'timeout_seconds': {'read': 600, 'connect': 30, 'write': 120, 'pool': 120},
            'max_workers': 2}


class Registration:
    def __init__(self, root):
        self.root = Path(root)
        raw = read(self.root, REGISTRATION)
        self.sha256 = digest(raw)
        self.data = decode(raw)
        r = self.data
        required = {'schema_version', 'namespace', 'original_base_dir', 'continuation_base_dir',
                    'protocol', 'readiness', 'original_source_sha256', 'continuation_source_sha256',
                    'original_base_intent_sha256', 'gallery_completion_sha256', 'training_freeze_sha256',
                    'query_manifest_sha256', 'old_stage_snapshot', 'original_log_sha256',
                    'successful_cache_sha256', 'attempt_snapshots', 'policy'}
        require(isinstance(r, dict) and set(r) == required, 'registration_fields_changed')
        require(r['schema_version'] == 1 and r['namespace'] == NAMESPACE
                and r['original_base_dir'] == OLD_RUN and r['continuation_base_dir'] == NEW_RUN,
                'registration_scope_changed')
        for name, expected in (('protocol', PROTOCOL), ('readiness', 'round4/execution_readiness.json'),
                               ('old_stage_snapshot', SNAPSHOT)):
            item = r[name]
            require(isinstance(item, dict) and set(item) == {'path', 'sha256'}
                    and item['path'] == expected and isinstance(item['sha256'], str)
                    and HEX.fullmatch(item['sha256']), 'registration_document_changed')
        for name in ('original_base_intent_sha256', 'gallery_completion_sha256',
                     'training_freeze_sha256', 'query_manifest_sha256'):
            require(isinstance(r[name], str) and HEX.fullmatch(r[name]), 'invalid_registered_digest')
        for name in ('original_source_sha256', 'continuation_source_sha256',
                     'original_log_sha256', 'successful_cache_sha256'):
            _hashes(r[name])
        require(set(r['continuation_source_sha256']) == set(NEW_SOURCES), 'continuation_source_inventory_changed')
        require(set(r['original_log_sha256']) == {'round4/provider/J/requests.jsonl'}, 'original_log_scope_changed')
        exception = r['policy'].get('exception', {}) if isinstance(r['policy'], dict) else {}
        h = exception.get('request_hash')
        require(isinstance(h, str) and HEX.fullmatch(h) and r['policy'] == policy(h), 'service_policy_changed')
        self.exception_hash = h
        self._validate_snapshots()
        self.verify_static()
        self.verify_snapshot()
        self._verify_exception_history()

    def _validate_snapshots(self):
        r = self.data
        require(isinstance(r['attempt_snapshots'], dict), 'invalid_attempt_snapshots')
        for name, item in r['attempt_snapshots'].items():
            match = re.fullmatch(r'runtime_cache/attempts/(chat|embedding)/([0-9a-f]{64})\.json', name)
            require(match is not None and isinstance(item, dict) and set(item) == {'sha256', 'state'},
                    'attempt_snapshot_scope_changed')
            state = item['state']
            require(isinstance(item['sha256'], str) and HEX.fullmatch(item['sha256'])
                    and isinstance(state, dict)
                    and set(state) == {'request_hash', 'attempts', 'last_reserved', 'namespace'}
                    and state['request_hash'] == match[2]
                    and type(state['attempts']) is int and 1 <= state['attempts'] <= 3
                    and state['namespace'] == NAMESPACE
                    and isinstance(state['last_reserved'], str) and bool(state['last_reserved']),
                    'invalid_original_attempt_snapshot')
            require(digest(original_counter_bytes(state)) == item['sha256'],
                    'original_attempt_state_hash_mismatch')
        for name in r['successful_cache_sha256']:
            require(re.fullmatch(r'runtime_cache/responses/(chat|embedding)/[0-9a-f]{64}\.json', name),
                    'successful_cache_scope_changed')
        name = f'runtime_cache/attempts/chat/{self.exception_hash}.json'
        require(name in r['attempt_snapshots'] and r['attempt_snapshots'][name]['state']['attempts'] == 3,
                'exception_original_attempts_not_three')
        require(f'runtime_cache/responses/chat/{self.exception_hash}.json'
                not in r['successful_cache_sha256'], 'exception_had_original_success_cache')

    def verify_static(self):
        r = self.data
        require(digest(read(self.root, REGISTRATION)) == self.sha256, 'registration_changed')
        for name in ('protocol', 'readiness', 'old_stage_snapshot'):
            item = r[name]
            require(digest(read(self.root, item['path'])) == item['sha256'], 'registered_document_changed')
        for name in ('original_source_sha256', 'continuation_source_sha256',
                     'original_log_sha256', 'successful_cache_sha256'):
            for file, expected in r[name].items():
                require(digest(read(self.root, file)) == expected, 'registered_file_changed')
        ready = decode(read(self.root, r['readiness']['path']))
        require(ready.get('source_sha256') == r['original_source_sha256'], 'original_source_inventory_changed')
        fixed = {OLD_RUN + '/intent.json': r['original_base_intent_sha256'],
                 'round4/runs/J_gallery/completion.json': r['gallery_completion_sha256'],
                 'round4/data/train/freeze.json': r['training_freeze_sha256'],
                 'data/cohorts/dev.jsonl': r['query_manifest_sha256']}
        for name, expected in fixed.items():
            require(digest(read(self.root, name)) == expected, 'original_binding_file_changed')

    def verify_snapshot(self):
        snapshot = decode(read(self.root, SNAPSHOT))
        require(isinstance(snapshot, dict) and set(snapshot) == {'schema_version', 'root', 'files'}
                and snapshot['schema_version'] == 1 and snapshot['root'] == OLD_RUN,
                'old_snapshot_schema_changed')
        _hashes(snapshot['files'])
        actual = {}
        directory = self.root / OLD_RUN
        require(directory.is_dir() and not directory.is_symlink(), 'old_run_missing')
        for file in sorted(directory.rglob('*')):
            require(not file.is_symlink(), 'old_run_symlink_rejected')
            if file.is_dir():
                continue
            require(file.is_file() and stat.S_ISREG(file.stat().st_mode), 'old_run_nonregular_file')
            if file.name == '.lock' or file.name.endswith('.lock'):
                continue
            actual[file.relative_to(self.root).as_posix()] = digest(file.read_bytes())
        require(actual == snapshot['files'], 'old_stage_snapshot_changed')
        self.snapshot = snapshot

    def _verify_exception_history(self):
        rows = []
        self.original_requests = []
        for name in self.data['original_log_sha256']:
            for line in read(self.root, name).splitlines():
                row = decode(line)
                require(isinstance(row, dict), 'invalid_original_log_record')
                self.original_requests.append(row)
                if row.get('request_hash') == self.exception_hash:
                    rows.append(row)
        require(len(rows) == 3 and [r.get('attempt') for r in rows] == [1, 2, 3]
                and all(r.get('role') == 'chat' and r.get('status') is None
                        and r.get('error_type') == 'ReadTimeout' for r in rows),
                'exception_not_three_read_timeouts')

    def cap(self, role, request_hash):
        return 4 if role == 'chat' and request_hash == self.exception_hash else 3

    def audit_rows(self):
        p = path(self.root, AUDIT, exists=False)
        if not p.exists():
            return []
        raw = read(self.root, AUDIT)
        require(not raw or raw.endswith(b'\n'), 'truncated_reservation_audit')
        rows = [decode(line) for line in raw.splitlines()]
        return rows

    def attempt_states(self, *, allow_pending=False):
        """Validate monotonic budgets, including a reserved-before-counter crash.

        The fsynced audit is authoritative for consumed reservations. A final
        interrupted ledger replacement can only be reconciled by the provider,
        never by a read-only completed-run verification.
        """
        states = {name: {'state': deepcopy(item['state']), 'sha256': item['sha256'], 'pending': False}
                  for name, item in self.data['attempt_snapshots'].items()}
        rows = self.audit_rows()
        for row in rows:
            require(isinstance(row, dict) and set(row) == {'schema_version', 'registration_sha256', 'role',
                    'request_hash', 'previous_attempts', 'attempt', 'previous_state_sha256', 'next_state'},
                    'invalid_reservation_audit')
            role, h = row['role'], row['request_hash']
            require(role in ('chat', 'embedding') and isinstance(h, str) and HEX.fullmatch(h)
                    and row['schema_version'] == 1 and row['registration_sha256'] == self.sha256,
                    'reservation_binding_changed')
            name = f'runtime_cache/attempts/{role}/{h}.json'
            previous = states.get(name, {'state': None, 'sha256': None})
            count = previous['state']['attempts'] if previous['state'] else 0
            nxt = row['next_state']
            require(type(row['previous_attempts']) is int and row['previous_attempts'] == count
                    and type(row['attempt']) is int and row['attempt'] == count + 1
                    and row['attempt'] <= self.cap(role, h)
                    and row['previous_state_sha256'] == previous['sha256']
                    and isinstance(nxt, dict) and set(nxt) == {'request_hash', 'attempts', 'last_reserved', 'namespace'}
                    and nxt['request_hash'] == h and nxt['attempts'] == count + 1
                    and nxt['namespace'] == NAMESPACE and isinstance(nxt['last_reserved'], str)
                    and bool(nxt['last_reserved']), 'reservation_count_not_contiguous')
            states[name] = {'state': deepcopy(nxt), 'sha256': digest(counter_bytes(nxt)),
                            'prior_sha256': previous['sha256'], 'pending': False}
        for name, expected in states.items():
            p = path(self.root, name, exists=False)
            raw = p.read_bytes() if p.exists() else None
            actual = digest(raw) if raw is not None else None
            if name in self.data['attempt_snapshots'] and actual == self.data['attempt_snapshots'][name]['sha256']:
                require(decode(raw) == self.data['attempt_snapshots'][name]['state'],
                        'original_attempt_counter_semantics_changed')
            if actual != expected['sha256']:
                require(allow_pending and 'prior_sha256' in expected and actual == expected['prior_sha256'],
                        'attempt_ledger_differs_from_reservations')
                expected['pending'] = True
        exception_cache = path(self.root, f'runtime_cache/responses/chat/{self.exception_hash}.json', exists=False)
        exception_name = f'runtime_cache/attempts/chat/{self.exception_hash}.json'
        require(not exception_cache.exists() or states[exception_name]['state']['attempts'] == 4,
                'exception_cache_without_registered_fourth_attempt')
        return states

    def service_binding(self):
        r = self.data
        return {'registration_sha256': self.sha256, 'protocol_sha256': r['protocol']['sha256'],
                'old_stage_snapshot_sha256': r['old_stage_snapshot']['sha256'],
                'original_base_intent_sha256': r['original_base_intent_sha256'],
                'source_sha256': deepcopy(r['continuation_source_sha256']), 'policy': deepcopy(r['policy'])}
