"""One registered service retry; frozen scientific payloads and old cache keys.

The parent Provider supplies credential validation, sanitization, chat/embed
contracts and model/vector checks. This independent transport loop replaces its
hard-coded three-attempt backoff. Reservations use the SAME persistent counters;
a fsynced write-ahead audit consumes an attempt even if the process then crashes.
"""
from __future__ import annotations

import fcntl
import json
import os
from pathlib import Path
import threading
import time

import httpx
import opt_provider as original
from round4.continuation.integrity import (AUDIT, NAMESPACE, PROVIDER_RUN, Registration,
    counter_bytes, digest, path, require)
from round4.src.artifacts import canonical, sync_dir

ProviderStop = original.ProviderStop


def _durable_counter(root, name, state):
    target = path(root, name, exists=False)
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    pending = target.with_name(target.name + '.continuation-pending')
    fd = os.open(pending, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'wb') as stream:
        stream.write(counter_bytes(state))
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(pending, target)
    sync_dir(target.parent)


class ContinuationProvider(original.Provider):
    def __init__(self, run_dir, registration, *, allow_paid=False, keys=None,
                 transport=None, sleep=time.sleep):
        require(isinstance(registration, Registration), 'verified_registration_required')
        self.registration = registration
        self.root = registration.root
        require(self.root == original.ROOT and Path(run_dir) == self.root / PROVIDER_RUN,
                'continuation_provider_scope_changed')
        registration.verify_static()
        registration.attempt_states(allow_pending=True)
        super().__init__(run_dir, allow_paid=allow_paid, namespace=NAMESPACE, keys=keys,
                         transport=transport, timeout=600, sleep=sleep)
        # Explicitly record all four timeout phases; none enters the payload hash.
        self.client.timeout = httpx.Timeout(read=600, connect=30, write=120, pool=120)
        self.reservation_lock = threading.Lock()

    def _reserve_attempt(self, cache_id, role):
        require(role in ('chat', 'embedding'), 'unknown_provider_role')
        directory = path(self.root, PROVIDER_RUN, exists=False)
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        lock_path = directory / 'reservations.lock'
        with self.reservation_lock:
            fd = os.open(lock_path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX)
                states = self.registration.attempt_states(allow_pending=True)
                name = f'runtime_cache/attempts/{role}/{cache_id}.json'
                target = path(self.root, name, exists=False)
                target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                # Interoperate with the original provider's per-payload lock.
                with target.with_suffix('.lock').open('a') as ledger_lock:
                    fcntl.flock(ledger_lock, fcntl.LOCK_EX)
                    expected = states.get(name)
                    if expected is None:
                        require(not target.exists(), 'unregistered_existing_attempt_counter')
                        count, previous_sha = 0, None
                    else:
                        if expected['pending']:
                            # The audit already spent this attempt, so restoring
                            # its counter does not authorize retransmission.
                            _durable_counter(self.root, name, expected['state'])
                        require(digest(target.read_bytes()) == expected['sha256'], 'attempt_counter_changed')
                        count, previous_sha = expected['state']['attempts'], expected['sha256']
                    cap = self.registration.cap(role, cache_id)
                    if count >= cap:
                        raise ProviderStop('Payload has exhausted its registered cumulative HTTP attempts')
                    next_state = {'request_hash': cache_id, 'attempts': count + 1,
                                  'last_reserved': original.stamp(), 'namespace': NAMESPACE}
                    row = {'schema_version': 1, 'registration_sha256': self.registration.sha256,
                           'role': role, 'request_hash': cache_id, 'previous_attempts': count,
                           'attempt': count + 1, 'previous_state_sha256': previous_sha,
                           'next_state': next_state}
                    audit = path(self.root, AUDIT, exists=False)
                    out = os.open(audit, os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW, 0o600)
                    with os.fdopen(out, 'ab') as stream:
                        stream.write(canonical(row))
                        stream.flush()
                        os.fsync(stream.fileno())
                    sync_dir(audit.parent)
                    _durable_counter(self.root, name, next_state)
                    return count + 1
            finally:
                os.close(fd)

    def _request(self, role, payload):
        if role not in ('chat', 'embedding'):
            raise ProviderStop('Unknown provider route')
        url, key = ((original.CHAT_URL, self.keys[0]) if role == 'chat'
                    else (original.EMBED_URL, self.keys[1]))
        model = original.CHAT_MODEL if role == 'chat' else original.EMBED_MODEL
        if payload.get('model') != model:
            raise ProviderStop('Requested model violates the provider route')
        cache_id = original.fingerprint({'url': url, 'payload': payload,
                    'namespace': self.namespace if role == 'chat' else 'official-query-v1'})
        cache_path = self.cache / role / (cache_id + '.json')
        with self.lock:
            key_lock = self.key_locks.setdefault(cache_id, threading.Lock())
        with key_lock:
            inherited = self.root.parent / 'runtime_cache/responses/embedding' / (cache_id + '.json')
            if role == 'embedding' and not cache_path.exists() and inherited.is_file():
                saved = json.loads(inherited.read_text())
                self._cache_value(saved, cache_id, role, model)
                original.atomic_json(cache_path, saved)
            if cache_path.exists():
                return self._cache_value(json.loads(cache_path.read_text()), cache_id, role, model)
            cap = self.registration.cap(role, cache_id)
            while True:
                attempt = self._reserve_attempt(cache_id, role)
                record = {'started': original.stamp(), 'role': role, 'endpoint': url,
                          'model_requested': model, 'request_hash': cache_id, 'attempt': attempt,
                          'service_registration_sha256': self.registration.sha256}
                try:
                    response = self.client.post(url, json=payload, headers={'Authorization': 'Bearer ' + key})
                except httpx.HTTPError as exc:
                    record.update(status=None, error_type=type(exc).__name__)
                    self._log(record)
                    if attempt >= cap:
                        raise ProviderStop('Provider connection failed at registered cumulative attempt cap') from None
                    self.sleep(2 if attempt == 1 else 8)
                    continue
                record['status'] = response.status_code
                try:
                    body = response.json()
                except ValueError:
                    body = {}
                if not isinstance(body, dict):
                    body = {}
                record.update(model_served=body.get('model'), usage=body.get('usage'))
                if response.status_code != 200:
                    error = body.get('error')
                    record['error_type'] = error.get('type') if isinstance(error, dict) else None
                    self._log(record)
                    if (response.status_code == 429 or response.status_code >= 500) and attempt < cap:
                        self.sleep(2 if attempt == 1 else 8)
                        continue
                    raise ProviderStop('Provider HTTP ' + str(response.status_code) + '; batch stopped')
                if body.get('model') != model:
                    self._log(record)
                    raise ProviderStop('Provider-reported model differs from the requested model')
                if role == 'chat':
                    choices = body.get('choices') or []
                    if not isinstance(choices, list) or any(not isinstance(c, dict) for c in choices):
                        self._log(record)
                        raise ProviderStop('Malformed chat response envelope')
                    if any(not isinstance(c.get('message'), dict) for c in choices):
                        self._log(record)
                        raise ProviderStop('Malformed chat message envelope')
                    record['finish_reason'] = choices[0].get('finish_reason') if len(choices) == 1 else None
                    content = (choices[0].get('message') or {}).get('content') if len(choices) == 1 else None
                    value = content if isinstance(content, str) and record['finish_reason'] == 'stop' else ''
                    value = original.sanitize(value, self.keys)
                else:
                    data = body.get('data') or []
                    if not isinstance(data, list) or any(not isinstance(d, dict) for d in data):
                        self._log(record)
                        raise ProviderStop('Malformed embedding response envelope')
                    value = data[0].get('embedding') if len(data) == 1 else None
                    if not self._valid_vector(value):
                        self._log(record)
                        raise ProviderStop('Official query embedding is incompatible with the frozen index')
                self._log(record)
                original.atomic_json(cache_path, {'request_hash': cache_id, 'model': model,
                    'value': value, 'value_hash': original.fingerprint(value)})
                return value

    def _cache_value(self, saved, cache_id, role, model):
        if saved.get('request_hash') != cache_id or saved.get('model') != model:
            raise ProviderStop('Response cache provenance mismatch')
        value = saved.get('value')
        if saved.get('value_hash') != original.fingerprint(value):
            raise ProviderStop('Response cache content checksum mismatch')
        if role == 'chat' and not isinstance(value, str):
            raise ProviderStop('Invalid cached chat value')
        if role == 'embedding' and not self._valid_vector(value):
            raise ProviderStop('Invalid cached embedding value')
        return value
