"""O dual-role freeze-bound admission ledger and offline service evidence.

Lock order is payload execution lock, then short ledger lock. Reservations are
never refunded; a response persisted before cache publication is recoverable.
No Provider, credentials or HTTP client is constructed by this module.
"""
from contextlib import contextmanager
from copy import deepcopy
from collections import Counter
import fcntl
import os
from pathlib import Path
import uuid

from opt_provider import ROOT, CHAT_MODEL, CHAT_URL, EMBED_MODEL, EMBED_URL, ProviderStop, fingerprint, sha, stamp
from historical_m import checked_path
from round4.src.artifacts import decode
from runtime_m import durable_json
REPAIR = ('Correct the output FORMAT only to satisfy the original contract. Preserve your visual '
          'interpretation; do not reconsider for accuracy. Return only the requested output. Contract error: ')

NAMESPACE = 'source-portions-r10-o.1'


def slot_id(sample, stage, ordinal):
    chat = stage in ('identify','select','whole','conditional')
    embedding = isinstance(stage,str) and stage in {f'embed_{i:02d}' for i in range(40)}
    if not (chat or embedding) or type(ordinal) is not int or ordinal not in ((0,1) if chat else (0,)):
        raise ValueError('O_unregistered_stage')
    return fingerprint([sample, stage, ordinal])


def load(path): return decode(Path(path).read_bytes())


def allowed_slots(rows, *, image_hashes=None):
    from opt_pipeline import encode_image
    if image_hashes is None:
        image_hashes = {r['sample_id']:fingerprint(encode_image(ROOT/r['image_path'],'square256')) for r in rows}
    slots = {}
    for row in rows:
        stages = ['identify','select','whole']+(['conditional'] if row['dataset']=='asa24' else [])
        for stage in stages:
            for ordinal in (0,1):
                slots[slot_id(row['sample_id'],stage,ordinal)] = {'sample_id':row['sample_id'],
                    'stage':stage,'ordinal':ordinal,'role':'chat',
                    'image_payload_sha256':image_hashes[row['sample_id']]}
        for i in range(40):
            stage = f'embed_{i:02d}'
            slots[slot_id(row['sample_id'],stage,0)] = {'sample_id':row['sample_id'],
                'stage':stage,'ordinal':0,'role':'embedding','image_payload_sha256':None}
    return slots


def payload(messages):
    return {'role':'chat','payload':{'model': CHAT_MODEL, 'temperature': 1,
            'max_completion_tokens': 8192, 'messages': messages}}


def embedding_payload(text):
    return {'role':'embedding','payload':{'model':EMBED_MODEL,'input':[text],'encoding_format':'float'}}


def route(value):
    if set(value) != {'role','payload'}: raise ValueError('O_role_payload_wrapper_required')
    role,body = value['role'],value['payload']
    if role == 'chat':
        if (set(body) != {'model','temperature','max_completion_tokens','messages'}
                or body['model'] != CHAT_MODEL or type(body['temperature']) is not int
                or body['temperature'] != 1 or body['max_completion_tokens'] != 8192
                or not isinstance(body['messages'],list)):
            raise ValueError('O_chat_contract_changed')
        return CHAT_URL,CHAT_MODEL,NAMESPACE
    if role == 'embedding':
        if (set(body) != {'model','input','encoding_format'} or body['model'] != EMBED_MODEL
                or body['encoding_format'] != 'float' or not isinstance(body['input'],list)
                or len(body['input']) != 1 or not isinstance(body['input'][0],str)
                or not body['input'][0].strip() or len(body['input'][0])>12000):
            raise ValueError('O_embedding_contract_changed')
        return EMBED_URL,EMBED_MODEL,'official-query-v1'
    raise ValueError('O_unknown_service_role')


def request_hash(value):
    url,_,namespace = route(value)
    return fingerprint({'url':url,'namespace':namespace,'payload':value['payload']})


class Ledger:
    def __init__(self, directory, binding, slots):
        self.directory = Path(directory)
        if self.directory.resolve() != self.directory: raise ValueError('O_unsafe_service_directory')
        self.binding, self.slots = fingerprint(binding), deepcopy(slots)
        self.parser_sha256 = fingerprint({p:h for p,h in binding.get('source_files',{}).items()
            if p in ('round10/source_portions.py','src/opt_pipeline.py')})
        if not slots or len(slots) > 8616: raise ValueError('O_invalid_allowed_slots')
        self.cap = len(slots) * 3
        self._gate = None

    def task_gate(self):
        if self._gate is None:
            from gate_o import frozen_gate
            self._gate = frozen_gate(self)
        return self._gate

    def verify_task(self,sid,value): return self.task_gate().validate(sid,value)

    def path(self, name):
        if self.directory.resolve() != self.directory: raise ValueError('O_service_ancestor_changed')
        return checked_path(self.directory, name)

    @contextmanager
    def lock(self, name):
        path = self.path('locks/' + name + '.lock')
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX); yield
        finally: os.close(fd)

    def initialize(self):
        self.path('')
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        with self.lock('admission'):
            if self.path('admission.json').exists(): return self.read()
            extras = [p for p in self.directory.iterdir() if p.name != 'locks']
            if extras: raise ValueError('O_missing_ledger_with_existing_state')
            value = {'namespace': NAMESPACE, 'binding': self.binding, 'allowed_slots': self.slots,
                     'bindings': {}, 'repairs': {}, 'reservations': [], 'outcomes': {}}
            durable_json(self.path('admission.json'), value)
            return value

    def read(self):
        value = load(self.path('admission.json'))
        if (set(value) != {'namespace', 'binding', 'allowed_slots', 'bindings', 'repairs', 'reservations', 'outcomes'}
                or value['namespace'] != NAMESPACE or value['binding'] != self.binding
                or value['allowed_slots'] != self.slots or not set(value['bindings']) <= set(self.slots)
                or len(value['reservations']) > self.cap):
            raise ValueError('O_admission_binding_changed')
        counts, ids = Counter(), set()
        for index, entry in enumerate(value['reservations'], 1):
            sid, h, rid = entry['slot'], entry['payload_hash'], entry['id']
            counts[h] += 1
            if (entry['sequence'] != index or rid in ids or len(rid) != 32
                    or any(c not in '0123456789abcdef' for c in rid)
                    or sid not in self.slots or value['bindings'].get(sid) != h
                    or entry.get('role') != self.slots[sid]['role']
                    or counts[h] > 3 or entry['attempt'] != counts[h]):
                raise ValueError('O_admission_reservation_changed')
            ids.add(rid)
        if not set(value['outcomes']) <= ids: raise ValueError('O_orphan_outcome_anchor')
        for h in value['bindings'].values():
            if not isinstance(h, str) or len(h) != 64 or any(c not in '0123456789abcdef' for c in h):
                raise ValueError('O_invalid_payload_hash')
        for sid, proof in value['repairs'].items():
            meta = self.slots.get(sid)
            if (not meta or meta['ordinal'] != 0 or meta['role']!='chat'
                    or set(proof) != {'raw_hash', 'error', 'parser_sha256'}
                    or not isinstance(proof['error'], str)):
                raise ValueError('O_invalid_repair_proof')
        return value

    def save(self, state): durable_json(self.path('admission.json'), state)

    def bind(self, sid, value):
        h = request_hash(value)
        self.verify_task(sid,value)
        with self.lock('admission'):
            state = self.read()
            if sid not in self.slots: raise ValueError('O_unknown_slot')
            role,body = value['role'],value['payload']
            if self.slots[sid]['role'] != role: raise ValueError('O_slot_role_changed')
            urls = [b['image_url']['url'] for m in body.get('messages',[]) if isinstance(m.get('content'),list)
                    for b in m['content'] if b.get('type') == 'image_url']
            if ((role=='chat' and (len(urls)!=1 or fingerprint(urls[0])!=self.slots[sid]['image_payload_sha256']))
                    or role=='embedding' and urls):
                raise ValueError('O_slot_image_changed')
            if sid in state['bindings'] and state['bindings'][sid] != h:
                raise ValueError('O_slot_payload_changed')
            meta = self.slots[sid]
            if meta['ordinal'] == 1:
                initial = slot_id(meta['sample_id'], meta['stage'], 0)
                proof = state['repairs'].get(initial)
                if proof is None: raise ValueError('O_repair_without_parser_failure')
                initial_h = state['bindings'].get(initial)
                if role != 'chat': raise ValueError('O_embedding_format_repair_forbidden')
                if request_hash({'role':role,'payload':{**body,'messages':body['messages'][:-2]}}) != initial_h:
                    raise ValueError('O_repair_original_request_changed')
                if (len(body['messages']) != 4 or body['messages'][-2].get('role') != 'assistant'
                        or fingerprint(body['messages'][-2].get('content')) != proof['raw_hash']
                        or body['messages'][-1] != {'role':'user','content': REPAIR + proof['error']}):
                    raise ValueError('O_repair_response_or_rule_changed')
            if sid not in state['bindings']:
                state['bindings'][sid] = h; self.save(state)
        return h

    def reserve(self, sid, h):
        with self.lock('admission'):
            state = self.read()
            if state['bindings'].get(sid) != h: raise ValueError('O_unbound_request')
            previous = self.target(h)
            if previous['cache'] is not None or previous['fatal']:
                raise ProviderStop('O_cannot_reserve_after_success_or_fatal')
            count = sum(r['payload_hash'] == h for r in state['reservations'])
            if count >= 3 or len(state['reservations']) >= self.cap:
                raise ProviderStop('O durable transport budget exhausted; preserve state')
            entry = {'id': uuid.uuid4().hex, 'slot': sid, 'payload_hash': h, 'attempt': count+1,
                     'sequence': len(state['reservations'])+1, 'started': stamp(),'role':self.slots[sid]['role']}
            state['reservations'].append(entry); self.save(state)
            return deepcopy(entry)

    def outcome_path(self, rid): return self.path('outcomes/' + rid + '.json')
    def cache_path(self, h): return self.path('responses/' + h + '.json')

    def import_usage(self, sid, value, manifest_sha256, vector_hash, origin):
        self.verify_task(sid,value)
        state=self.read()
        if (sid not in self.slots or self.slots[sid]['role']!='embedding' or value['role']!='embedding'
                or sid in state['bindings'] or origin not in ('legacy','M')):
            raise ValueError('O_invalid_or_conflicting_import_slot')
        record={'slot':sid,'payload_hash':request_hash(value),'manifest_sha256':manifest_sha256,
                'value_hash':vector_hash,'origin':origin}
        path=self.path('imports/'+sid+'.json')
        if path.exists():
            if load(path)!=record: raise ValueError('O_immutable_import_usage_changed')
        else: durable_json(path,record)
        return record

    def validate_outcome(self, row, reservation):
        if row.get('reservation') != reservation: raise ValueError('O_outcome_reservation_changed')
        kind = row.get('kind')
        if kind not in ('success', 'retryable', 'fatal'): raise ValueError('O_invalid_outcome_kind')
        if kind == 'success':
            body = row.get('body')
            role = reservation['role']
            try:
                if role == 'chat':
                    choice = body['choices'][0]
                    content = choice['message']['content']
                    valid = body['model']==CHAT_MODEL and len(body['choices'])==1 and isinstance(content,str)
                    expected = content if choice.get('finish_reason') == 'stop' else ''
                else:
                    import math
                    data = body['data']; expected = data[0]['embedding']
                    valid = (body['model']==EMBED_MODEL and len(data)==1 and data[0].get('index')==0
                        and isinstance(expected,list) and len(expected)==3072 and any(expected)
                        and all(type(v) in (int,float) and math.isfinite(v) for v in expected))
                valid = valid and row['status']==200
            except (KeyError, TypeError, IndexError): valid = False
            if not valid: raise ValueError('O_success_envelope_changed')
            if row.get('value') != expected or row.get('value_hash') != fingerprint(expected):
                raise ValueError('O_outcome_value_changed')
        return row

    def target(self, h, *, recover=False):
        """Read-only by default. Recovery requires the caller's payload lock."""
        state = self.read()
        reservations = [r for r in state['reservations'] if r['payload_hash'] == h]
        outcomes = []
        for reservation in reservations:
            path = self.outcome_path(reservation['id'])
            anchor = state['outcomes'].get(reservation['id'])
            if anchor is not None and not path.is_file(): raise ValueError('O_anchored_outcome_missing')
            if not path.is_file(): continue  # Unknown outcome consumes its reservation.
            raw = self.validate_outcome(load(path), reservation)
            if anchor is None:
                if not recover: raise ValueError('O_unanchored_outcome_needs_recovery')
                with self.lock('admission'):
                    current = self.read()
                    current['outcomes'][reservation['id']] = sha(path); self.save(current)
                state = self.read()
            elif sha(path) != anchor: raise ValueError('O_outcome_anchor_changed')
            outcomes.append(raw)
        successes = [r for r in outcomes if r['kind'] == 'success']
        if len(successes) > 1 or successes and successes[-1]['reservation'] != reservations[-1]:
            raise ValueError('O_request_after_success')
        expected = None
        if successes:
            last = successes[0]
            expected = {'namespace': NAMESPACE, 'payload_hash': h,'role':last['reservation']['role'],
                'model':CHAT_MODEL if last['reservation']['role']=='chat' else EMBED_MODEL,
                'value': last['value'], 'value_hash': last['value_hash'],
                'reservation_id': last['reservation']['id'],
                'outcome_sha256': sha(self.outcome_path(last['reservation']['id']))}
        cache = self.cache_path(h)
        if cache.exists():
            if expected is None or load(cache) != expected: raise ValueError('O_cache_outcome_value_mismatch')
        elif expected is not None:
            if not recover: raise ValueError('O_persisted_success_cache_missing')
            durable_json(cache, expected)
        return {'cache': expected, 'outcomes': outcomes, 'reserved': len(reservations),
                'fatal': any(r['kind'] == 'fatal' for r in outcomes)}

    def persist(self, reservation, outcome):
        row = self.validate_outcome({'reservation': reservation, **outcome}, reservation)
        path = self.outcome_path(reservation['id'])
        if path.exists(): raise ValueError('O_outcome_already_persisted')
        durable_json(path, row)  # Recoverable if the process exits at the next instruction.
        self.target(reservation['payload_hash'], recover=True)

    def recover_pending(self):
        # Startup uses this before its read-only audit. Never sends a request;
        # only publishes complete responses already saved by a reserved call.
        for h in sorted(set(self.read()['bindings'].values())):
            with self.lock('payload-' + h): self.target(h,recover=True)

    def format_failure(self, sid, raw, error, parser_sha256):
        if self.parser_sha256 is not None and self.parser_sha256 != parser_sha256:
            raise ValueError('O_unfrozen_repair_parser')
        state = self.read(); meta = self.slots.get(sid)
        if not meta or meta['ordinal'] != 0 or meta['role']!='chat': raise ValueError('O_format_failure_slot')
        item = self.target(state['bindings'][sid])
        if item['cache'] is None or item['cache']['value_hash'] != fingerprint(raw):
            raise ValueError('O_parser_failure_without_initial_answer')
        gate = self.task_gate()
        actual_error = gate.format_error(sid,raw)
        if actual_error != str(error) or parser_sha256 != gate.parser_sha256:
            raise ValueError('O_declared_parser_failure_not_actual')
        proof = {'raw_hash': fingerprint(raw), 'error': str(error), 'parser_sha256': parser_sha256}
        with self.lock('admission'):
            state = self.read()
            if sid in state['repairs'] and state['repairs'][sid] != proof:
                raise ValueError('O_parser_failure_changed')
            if sid not in state['repairs']: state['repairs'][sid] = proof; self.save(state)

    def audit(self, *, complete=False):
        state = self.read()
        reserved = {r['id'] for r in state['reservations']}
        for path in self.path('outcomes').glob('*.json'):
            if path.stem not in reserved: raise ValueError('O_orphan_outcome')
        hashes = set(state['bindings'].values())
        for path in self.path('responses').glob('*.json'):
            if path.stem not in hashes: raise ValueError('O_orphan_cache')
        for path in self.path('imports').glob('*.json'):
            record=load(path)
            if record.get('slot')!=path.stem or path.stem in state['bindings']:
                raise ValueError('O_import_usage_slot_changed')
            self.task_gate().verify_import(record)
        counts = {'payloads': len(hashes), 'bound_slots': len(state['bindings']),
            'reserved_attempts': len(state['reservations']), 'logged_transmissions': 0,
            'successful_payloads': 0, 'errors': 0}
        for h in sorted(hashes):
            result = self.target(h)
            counts['logged_transmissions'] += len(result['outcomes'])
            counts['successful_payloads'] += result['cache'] is not None
            counts['errors'] += sum(r['kind'] != 'success' for r in result['outcomes'])
            if complete and (result['cache'] is None or result['fatal']):
                raise ValueError('O_incomplete_service_at_completion')
        files = {str(p.relative_to(self.directory)): sha(self.path(p.relative_to(self.directory)))
                 for p in self.directory.rglob('*.json')}
        counts['unknown_outcomes'] = counts['reserved_attempts'] - counts['logged_transmissions']
        return {'namespace': NAMESPACE, 'binding': self.binding, 'files': files, 'counts': counts}
