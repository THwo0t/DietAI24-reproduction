"""L transport settings and thread-local, image-bound request receipts.

The existing dual-provider adapter owns credentials, redaction, persistent
three-transmission budgets, response-model checks and successful caches. This
module neither resets old counters nor changes a scientific payload.
"""
from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
import hashlib
import os
from pathlib import Path
import threading

import httpx
import opt_provider as original
from opt_provider import Provider, ProviderStop, CHAT_MODEL, CHAT_URL, fingerprint
from round6.src.service_evidence import audit_state, audit_request, verify_refs

NAMESPACE = 'region-atlas-pilot-r6-l.1'
PROVIDER_DIRECTORY = 'round6/provider/L'
MAX_WORKERS = 2


class PilotProvider(Provider):
    def __init__(self, run_dir, *, allow_paid=False, keys=None, transport=None, sleep=None):
        if Path(run_dir) != original.ROOT / PROVIDER_DIRECTORY:
            raise ValueError('pilot_provider_scope_changed')
        # R5-K4-1: refuse corrupt/exhausted previous state before any new client
        # is allowed to transmit. This occurs while LazyProvider holds its lock.
        audit_state(original.ROOT)
        kwargs = {} if sleep is None else {'sleep': sleep}
        super().__init__(run_dir, allow_paid=allow_paid, namespace=NAMESPACE,
                         keys=keys, transport=transport, timeout=600, **kwargs)
        self.client.timeout = httpx.Timeout(read=600, connect=30, write=120, pool=120)

    def _reserve_attempt(self, cache_id, role):
        if role != 'chat':
            raise ProviderStop('New embedding requests are not registered for L')
        # Targeted audit avoids interpreting another worker's in-flight third
        # attempt or log-before-cache publication window as a stale failure.
        audit_request(original.ROOT, cache_id)
        count = super()._reserve_attempt(cache_id, role)
        # The original reservation is never rolled back. Make its file and
        # directory entry durable before _request is allowed to send anything.
        # A failed fsync propagates; restarting observes the consumed attempt.
        path = original.ROOT / 'runtime_cache/attempts/chat' / (cache_id + '.json')
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
        fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
        return count

    def embed(self, texts):
        raise ProviderStop('New embedding requests are not registered for L')


def image_digest(url):
    if not isinstance(url, str) or not url.startswith(('data:image/png;base64,', 'data:image/jpeg;base64,')):
        raise ValueError('only_inline_image_payloads_allowed')
    return hashlib.sha256(url.encode()).hexdigest()


class BoundTrace:
    """No credential inspection; exact ordered image payloads on every repair."""
    def __init__(self, provider):
        if provider.namespace != NAMESPACE:
            raise ValueError('pilot_provider_namespace_mismatch')
        self.provider = provider
        self.local = threading.local()

    def _state(self):
        if not hasattr(self.local, 'refs'):
            self.local.refs, self.local.expected = [], None
        return self.local

    @contextmanager
    def expect(self, image_urls):
        state = self._state()
        if state.expected is not None:
            raise ValueError('nested_image_expectation_forbidden')
        expected = [image_digest(url) for url in image_urls]
        if not 1 <= len(expected) <= 13:
            raise ValueError('pilot_image_budget_violated')
        state.expected = expected
        try:
            yield
        finally:
            state.expected = None

    def mark(self):
        return len(self._state().refs)

    def refs_since(self, cursor):
        refs = self._state().refs
        if type(cursor) is not int or not 0 <= cursor <= len(refs):
            raise ValueError('invalid_pilot_trace_cursor')
        return deepcopy(refs[cursor:])

    def chat(self, messages, max_completion_tokens=4096):
        state = self._state()
        if self.provider.namespace != NAMESPACE or state.expected is None:
            raise ValueError('bound_pilot_image_scope_required')
        actual = []
        for message in messages:
            content = message.get('content')
            if isinstance(content, list):
                for block in content:
                    if block.get('type') == 'image_url':
                        actual.append(image_digest(block.get('image_url', {}).get('url')))
        if actual != state.expected:
            raise ValueError('ordered_pilot_image_payload_changed')
        payload = {'model': CHAT_MODEL, 'temperature': 1,
                   'max_completion_tokens': max_completion_tokens, 'messages': messages}
        request_hash = fingerprint({'url': CHAT_URL, 'payload': payload, 'namespace': NAMESPACE})
        ref = {'role': 'chat', 'request_hash': request_hash, 'value_hash': None,
               'status': 'pending', 'cache_present_before':
               (Path(self.provider.cache) / 'chat' / (request_hash + '.json')).is_file()}
        state.refs.append(ref)
        try:
            value = self.provider.chat(messages, max_completion_tokens=max_completion_tokens)
            if self.provider.namespace != NAMESPACE:
                raise ValueError('pilot_provider_namespace_changed')
            ref.update(status='returned', value_hash=fingerprint(value))
            return value
        except BaseException:
            ref.update(status='raised', value_hash=None)
            raise

    def embed(self, texts):
        raise ProviderStop('New embedding requests are not registered for L')


def validate_envelope(root, envelope, validator):
    """Reparse a fresh or saved result and check its real service receipts.

    This function never constructs a Provider. The scientific parser is supplied
    by the caller, including for terminal format failures with two raw answers.
    """
    if not isinstance(envelope, dict) or set(envelope) != {'result', 'request_refs'}:
        raise ValueError('pilot_stage_envelope_changed')
    result = validator(envelope['result'])
    if (not isinstance(result, dict) or not isinstance(result.get('raw_outputs'), list)
            or not 1 <= len(result['raw_outputs']) <= 2):
        raise ValueError('pilot_stage_response_count_changed')
    refs = envelope['request_refs']
    verify_refs(root, refs, result['raw_outputs'])
    return {'result': result, 'request_refs': deepcopy(refs)}


def run_stage(root, store, traced, name, inputs, images, call, validator, *, refs_sink=None):
    """K-style persisted stage; cache replay never invokes call or the trace.

    The coordinator initializes the shared store before starting <=2 workers,
    owns the lazy Provider, and verifies its source/input binding. Image lists
    must match every fresh request including the one allowed format repair.
    """
    def invoke():
        cursor = traced.mark()
        with traced.expect(images):
            result = call()
        return {'result': result, 'request_refs': traced.refs_since(cursor)}

    envelope = store.stage_runner(name, inputs, invoke,
                                 lambda value: validate_envelope(root, value, validator))
    if refs_sink is not None:
        refs_sink(deepcopy(envelope['request_refs']))
    return envelope['result']
