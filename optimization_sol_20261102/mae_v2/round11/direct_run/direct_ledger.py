"""Thread-shared exact-byte admission cache around the existing P ledger.

The legacy JSON schema, persistence, UUIDs, budgets, response validation and
parser-repair proofs remain inherited. Task admission checks the frozen slot,
route/model contract and image rather than reconstructing the scientific Gate.
"""
from contextlib import contextmanager
from collections import Counter
from copy import deepcopy
import hashlib
from pathlib import Path
import sys
import threading

BASE = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(BASE), *(str(BASE/p) for p in
    ('src', 'round7/src', 'round8/src', 'round10', 'round11'))]
from service_p import Ledger, route, load, _hash
from opt_provider import fingerprint
from runtime_m import durable_json


class _FrozenDict(dict):
    def _refuse(self, *args, **kwargs):
        raise TypeError('P_direct_frozen_slots_are_read_only')
    __setitem__ = __delitem__ = clear = pop = popitem = setdefault = update = __ior__ = _refuse

    def __deepcopy__(self, memo):
        return self


class FastLedger(Ledger):
    """One threaded writer, durable dynamic WAL, original-format final flush."""
    def __init__(self, directory, binding, slots):
        super().__init__(directory, binding, slots)
        self.slots = _FrozenDict({sid:_FrozenDict(meta) for sid, meta in self.slots.items()})
        self._state_lock = threading.RLock()
        self._local = threading.local()
        self._cached_digest = None
        self._cached_state = None
        self._original_state = None

    def _wal_path(self):
        return self.path('direct_admission_dynamic.json')

    @staticmethod
    def _dynamic(state):
        return {key:deepcopy(value) for key, value in state.items() if key != 'allowed_slots'}

    def _validate_dynamic(self, state):
        if (type(state) is not dict or set(state) != {
                'namespace', 'binding', 'bindings', 'repairs', 'reservations', 'outcomes'}
                or state['namespace'] != self._original_state['namespace']
                or state['binding'] != self.binding or not set(state['bindings']) <= self.slots.keys()
                or len(state['reservations']) > self.cap):
            raise ValueError('P_direct_WAL_binding_changed')
        counts, ids = Counter(), set()
        for index, entry in enumerate(state['reservations'], 1):
            sid, h, rid = entry['slot'], entry['payload_hash'], entry['id']
            counts[h] += 1
            if (entry['sequence'] != index or rid in ids or type(rid) is not str or len(rid) != 32
                    or any(c not in '0123456789abcdef' for c in rid)
                    or sid not in self.slots or state['bindings'].get(sid) != h
                    or entry.get('role') != self.slots[sid]['role']
                    or counts[h] > 3 or entry['attempt'] != counts[h]):
                raise ValueError('P_direct_WAL_reservation_changed')
            ids.add(rid)
        if not set(state['outcomes']) <= ids or not all(_hash(v) for v in state['outcomes'].values()):
            raise ValueError('P_direct_WAL_outcome_anchor_changed')
        if not all(_hash(h) for h in state['bindings'].values()):
            raise ValueError('P_direct_WAL_payload_hash_changed')
        for sid, proof in state['repairs'].items():
            meta = self.slots.get(sid)
            if (not meta or meta['ordinal'] != 0 or meta['role'] != 'chat'
                    or set(proof) != {'raw_hash', 'error', 'parser_sha256'}
                    or type(proof['error']) is not str or not _hash(proof['raw_hash'])
                    or proof['parser_sha256'] != self.parser_sha256):
                raise ValueError('P_direct_WAL_repair_proof_changed')

    def _require_extension(self, state, previous):
        if (state['namespace'] != previous['namespace'] or state['binding'] != previous['binding']
                or state['reservations'][:len(previous['reservations'])] != previous['reservations']
                or any(any(state[key].get(k) != v for k, v in previous[key].items())
                       for key in ('bindings', 'repairs', 'outcomes'))):
            raise ValueError('P_direct_WAL_must_extend_original_state')

    def _load_original_once(self):
        if self._original_state is not None:
            return
        original = super().read()  # Original complete validator, once at startup.
        self._original_state = self._dynamic(original)
        self._cached_state = self._copy_state(original)

    @contextmanager
    def lock(self, name):
        if name != 'admission':
            # Payload locks remain independent; do not serialize HTTP requests.
            with super().lock(name):
                yield
            return
        with self._state_lock:
            depth = getattr(self._local, 'admission_depth', 0)
            if depth:
                self._local.admission_depth = depth+1
                try:
                    yield
                finally:
                    self._local.admission_depth = depth
                return
            with super().lock(name):
                self._local.admission_depth = 1
                self._local.snapshot_checked = False
                try:
                    yield
                finally:
                    self._local.admission_depth = 0
                    self._local.snapshot_checked = False

    def _copy_state(self, state):
        return {key:self.slots if key == 'allowed_slots' else deepcopy(value)
                for key, value in state.items()}

    def read(self):
        with self.lock('admission'):
            self._load_original_once()
            if not self._local.snapshot_checked or self._cached_state is None:
                path = self._wal_path()
                if path.is_file():
                    digest = hashlib.sha256(path.read_bytes()).digest()
                    if digest != self._cached_digest:
                        value = load(path)
                        self._validate_dynamic(value)
                        self._require_extension(value, self._original_state)
                        self._require_extension(value, self._dynamic(self._cached_state))
                        self._cached_state = {**value, 'allowed_slots':self.slots}
                        self._cached_digest = digest
                elif self._cached_digest is not None:
                    raise ValueError('P_direct_WAL_disappeared')
                self._local.snapshot_checked = True
            return self._copy_state(self._cached_state)

    def save(self, state):
        with self.lock('admission'):
            self._load_original_once()
            dynamic = self._dynamic(state)
            self._require_extension(dynamic, self._dynamic(self._cached_state))
            # Original atomic replace + file fsync + directory fsync. reserve()
            # returns only after this durable boundary, before any HTTP call.
            durable_json(self._wal_path(), dynamic)
            self._cached_digest = hashlib.sha256(self._wal_path().read_bytes()).digest()
            self._cached_state = self._copy_state(state)
            self._local.snapshot_checked = True

    def flush_original(self):
        """Call after all worker futures drain, including orderly interruption."""
        with self.lock('admission'):
            state = self.read()
            super().save(state)
            self._original_state = self._dynamic(state)
            return len(state['reservations'])

    def verify_task(self, sid, value):
        route(value)  # The original exact role/model/route/payload contract.
        meta = self.slots.get(sid)
        if meta is None:
            raise ValueError('P_unknown_slot')
        role, body = value['role'], value['payload']
        if meta['role'] != role:
            raise ValueError('P_slot_role_changed')
        urls = [block['image_url']['url'] for message in body.get('messages', [])
                if isinstance(message.get('content'), list) for block in message['content']
                if block.get('type') == 'image_url']
        if ((role == 'chat' and (len(urls) != 1 or fingerprint(urls[0]) != meta['image_payload_sha256']))
                or (role == 'embedding' and urls)):
            raise ValueError('P_slot_image_changed')
        return True
