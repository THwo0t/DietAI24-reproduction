"""N-only lazy chat transport; each returned answer binds a durable reservation."""
from contextlib import contextmanager
from copy import deepcopy
import hashlib
import threading
import time

import httpx
from opt_provider import CHAT_MODEL, CHAT_URL, ProviderStop, read_credentials, sanitize, fingerprint, sha
from service_n import Ledger, payload, request_hash, slot_id


class NProvider:
    def __init__(self, ledger, *, allow_paid=False, keys=None, transport=None, sleep=time.sleep):
        if not allow_paid: raise ProviderStop('N explicit paid authorization required')
        self.ledger = ledger
        self.keys = tuple(keys) if keys is not None else read_credentials()
        if len(self.keys) != 2 or not all(self.keys) or self.keys[0] == self.keys[1]:
            raise ProviderStop('N distinct dual-route credentials required')
        self.sleep = sleep
        self.client = httpx.Client(transport=transport, trust_env=False, follow_redirects=False,
            timeout=httpx.Timeout(read=600, connect=30, write=120, pool=120))

    def request(self, sid, value):
        h = request_hash(value)
        with self.ledger.lock('payload-' + h):
            self.ledger.bind(sid, value)
            old = self.ledger.target(h, recover=True)
            before = old['cache'] is not None
            if old['fatal']: raise ProviderStop('N permanent provider failure; preserve state')
            while old['cache'] is None:
                self.ledger.verify_task(sid,value)
                reservation = self.ledger.reserve(sid, h)
                try:
                    response = self.client.post(CHAT_URL, json=value,
                                                headers={'Authorization': 'Bearer ' + self.keys[0]})
                except httpx.HTTPError as exc:
                    outcome = {'kind': 'retryable', 'status': None, 'error_type': type(exc).__name__, 'body': None}
                else:
                    try: body = response.json()
                    except ValueError: body = None
                    body = sanitize(body, self.keys)
                    outcome = {'kind': 'fatal', 'status': response.status_code, 'body': body,
                               'error_type': None}
                    if response.status_code == 429 or response.status_code >= 500:
                        outcome['kind'] = 'retryable'
                    elif response.status_code == 200 and isinstance(body, dict) and body.get('model') == CHAT_MODEL:
                        try:
                            choice = body['choices'][0]
                            content = choice['message']['content']
                            valid = len(body['choices']) == 1 and isinstance(content, str)
                        except (KeyError, IndexError, TypeError): valid = False
                        if valid:
                            answer = content if choice.get('finish_reason') == 'stop' else ''
                            outcome.update(kind='success', value=answer, value_hash=fingerprint(answer))
                self.ledger.persist(reservation, outcome)
                old = self.ledger.target(h)
                if old['fatal']: raise ProviderStop('N authentication/model/envelope/permanent HTTP failure')
                if old['cache'] is None:
                    if old['reserved'] >= 3: raise ProviderStop('N payload transport budget exhausted')
                    self.sleep((2, 8)[old['reserved']-1])
            result = old['cache']
            return result['value'], {'slot': sid, 'payload_hash': h, 'value_hash': result['value_hash'],
                'reservation_id': result['reservation_id'], 'cache_present_before': before}

    def close(self): self.client.close()


class Trace:
    def __init__(self, ledger, parser_sha256, allow_paid=False):
        self.ledger, self.parser_sha256, self.allow_paid = ledger, parser_sha256, allow_paid
        self.local, self.guard, self.provider = threading.local(), threading.Lock(), None

    @contextmanager
    def expect(self, sample, stage, image_url):
        if getattr(self.local, 'scope', None) is not None: raise ValueError('N_nested_stage_scope')
        self.local.scope = {'sample': sample, 'stage': stage, 'image': fingerprint(image_url), 'refs': []}
        try: yield self.local.scope['refs']
        finally: self.local.scope = None

    def chat(self, messages):
        scope = self.local.scope
        urls = [b['image_url']['url'] for m in messages if isinstance(m.get('content'), list)
                for b in m['content'] if b.get('type') == 'image_url']
        if scope is None or len(urls) != 1 or fingerprint(urls[0]) != scope['image']:
            raise ValueError('N_exact_query_image_changed')
        ordinal = len(scope['refs'])
        sid = slot_id(scope['sample'], scope['stage'], ordinal)
        with self.guard:
            if self.provider is None: self.provider = NProvider(self.ledger, allow_paid=self.allow_paid)
        answer, ref = self.provider.request(sid, payload(messages))
        scope['refs'].append(ref)
        return answer

    def format_failure(self, stage, raw, error):
        scope = self.local.scope
        if scope['stage'] != stage or len(scope['refs']) != 1: raise ValueError('N_invalid_repair_callback')
        sid = slot_id(scope['sample'], stage, 0)
        self.ledger.format_failure(sid, raw, error, self.parser_sha256)

    def close(self):
        if self.provider is not None: self.provider.close()


class Replay:
    def __init__(self, ledger, sample, stage, refs, parser_sha256):
        self.ledger, self.sample, self.stage = ledger, sample, stage
        self.refs, self.index, self.parser_sha256 = refs, 0, parser_sha256
        self.failure = None

    def chat(self, messages):
        if self.index >= len(self.refs): raise ValueError('N_replay_missing_request')
        ref = self.refs[self.index]; h = request_hash(payload(messages))
        sid = slot_id(self.sample, self.stage, self.index)
        if (set(ref) != {'slot', 'payload_hash', 'value_hash', 'reservation_id', 'cache_present_before'}
                or type(ref['cache_present_before']) is not bool or ref['slot'] != sid
                or ref['payload_hash'] != h): raise ValueError('N_replay_exact_request_changed')
        state = self.ledger.read()
        if state['bindings'].get(sid) != h: raise ValueError('N_replay_slot_binding_changed')
        if self.index == 1:
            initial = slot_id(self.sample, self.stage, 0)
            if self.failure is None or state['repairs'].get(initial) != self.failure:
                raise ValueError('N_replay_format_proof_changed')
        cached = self.ledger.target(h)['cache']
        if (cached is None or cached['value_hash'] != ref['value_hash']
                or cached['reservation_id'] != ref['reservation_id']):
            raise ValueError('N_replay_value_provenance_changed')
        self.index += 1
        return cached['value']

    def format_failure(self, stage, raw, error):
        if stage != self.stage or self.index != 1: raise ValueError('N_replay_parser_scope_changed')
        self.failure = {'raw_hash': fingerprint(raw), 'error': str(error), 'parser_sha256': self.parser_sha256}
        state = self.ledger.read()
        initial = slot_id(self.sample, stage, 0)
        if state['repairs'].get(initial) != self.failure: raise ValueError('N_replay_parser_failure_changed')

    def finish(self):
        if self.index != len(self.refs): raise ValueError('N_replay_extra_request')
