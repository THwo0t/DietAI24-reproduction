"""R5-K4-1: synthetic read-only K service evidence and tampering cases.

Files use the existing Provider's exact cache/counter/metadata-log schemas.
No Provider, credentials, images, real artifacts or HTTP client are used here;
the production runner's MockTransport integration is tested separately.
"""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / 'src')]
from opt_provider import CHAT_MODEL, CHAT_URL, fingerprint
from round5.src import service_evidence as evidence

NAMESPACE = 'component-comparison-r5-k.1'
LOG = 'round5/provider/K/requests.jsonl'
VALUE = '{"synthetic":"success"}'
STAMP = '2026-11-03T00:00:00+00:00'


def encoded(value):
    return (json.dumps(value, sort_keys=True, allow_nan=False) + '\n').encode()


class ServiceEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='synthetic-k-service-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.request_hash = self.request('primary')
        self.cache = self.root / self.cache_path(self.request_hash)
        self.counter = self.root / self.counter_path(self.request_hash)
        self.log = self.root / LOG
        self.refs = [self.ref(self.request_hash)]
        self.stage_refs = {'synthetic-stage': {'refs': self.refs, 'values': [VALUE]}}

    @staticmethod
    def cache_path(request_hash):
        return 'runtime_cache/responses/chat/' + request_hash + '.json'

    @staticmethod
    def counter_path(request_hash):
        return 'runtime_cache/attempts/chat/' + request_hash + '.json'

    @staticmethod
    def ref(request_hash, value=VALUE, cache_present_before=False):
        return {'role': 'chat', 'request_hash': request_hash, 'value_hash': fingerprint(value),
                'status': 'returned', 'cache_present_before': cache_present_before}

    def put(self, relative, raw):
        path = self.root / relative
        current = self.root
        for part in path.parent.relative_to(self.root).parts:
            current /= part
            current.mkdir(mode=0o700, exist_ok=True)
        path.write_bytes(raw)
        path.chmod(0o600)

    def json_put(self, path, value):
        self.put(path.relative_to(self.root).as_posix(), encoded(value))

    def append_log(self, record):
        old = self.log.read_bytes() if hasattr(self, 'log') and self.log.exists() else (
            (self.root / LOG).read_bytes() if (self.root / LOG).exists() else b'')
        self.put(LOG, old + encoded(record))

    @staticmethod
    def log_record(request_hash, attempt=1, *, success=True):
        common = {'started': STAMP, 'role': 'chat', 'endpoint': CHAT_URL,
                  'model_requested': CHAT_MODEL, 'request_hash': request_hash, 'attempt': attempt}
        if success:
            return {**common, 'status': 200, 'model_served': CHAT_MODEL,
                    'usage': {'prompt_tokens': 2, 'completion_tokens': 1, 'total_tokens': 3},
                    'finish_reason': 'stop'}
        return {**common, 'status': None, 'error_type': 'ReadTimeout'}

    def request(self, name, *, attempts=1, success=True, namespace=NAMESPACE,
                logged_attempts=None, value=VALUE):
        payload = {'model': CHAT_MODEL, 'temperature': 1, 'max_completion_tokens': 4096,
                   'messages': [{'role': 'user', 'content': 'invented-' + name}]}
        request_hash = fingerprint({'url': CHAT_URL, 'payload': payload, 'namespace': namespace})
        self.put(self.counter_path(request_hash), encoded({'request_hash': request_hash,
            'attempts': attempts, 'last_reserved': STAMP, 'namespace': namespace}))
        self.put('runtime_cache/attempts/chat/' + request_hash + '.lock', b'')
        if success:
            self.put(self.cache_path(request_hash), encoded({'request_hash': request_hash,
                'model': CHAT_MODEL, 'value': value, 'value_hash': fingerprint(value)}))
        # Non-K logs belong to another run, not to this fixed K log path.
        if namespace == NAMESPACE:
            count = attempts if logged_attempts is None else logged_attempts
            for attempt in range(1, count + 1):
                self.append_log(self.log_record(request_hash, attempt,
                                               success=success and attempt == attempts))
        return request_hash

    def snapshot(self):
        return {p.relative_to(self.root).as_posix(): (p.read_bytes(), p.stat().st_mtime_ns)
                for p in self.root.rglob('*') if p.is_file() and not p.is_symlink()}

    def assert_rejected(self, invoke=None):
        with self.assertRaises(evidence.ServiceEvidenceError):
            (invoke or (lambda: evidence.completion_proof(self.root, self.stage_refs)))()

    def test_complete_success_proof_binds_exact_bytes_and_is_readonly(self):
        before = self.snapshot()
        proof = evidence.completion_proof(self.root, self.stage_refs)
        self.assertEqual(proof['schema_version'], 1)
        self.assertEqual(proof['namespace'], NAMESPACE)
        self.assertEqual(proof['counter_sha256'], {self.request_hash: hashlib.sha256(self.counter.read_bytes()).hexdigest()})
        self.assertEqual(proof['cache_sha256'], {self.request_hash: hashlib.sha256(self.cache.read_bytes()).hexdigest()})
        self.assertEqual(proof['log_sha256'], hashlib.sha256(self.log.read_bytes()).hexdigest())
        self.assertEqual(proof['stage_count'], 1)
        self.assertEqual(proof['ref_count'], 1)
        self.assertEqual(proof['counts']['success_count'], 1)
        self.assertEqual(proof['counts']['reserved_attempts'], 1)
        self.assertEqual(proof['counts']['logged_attempts'], 1)
        self.assertEqual(proof['counts']['transmissions'], 1)
        self.assertEqual(proof['counts']['unlogged_attempts'], 0)
        self.assertIsNone(evidence.verify_refs(self.root, self.refs, [VALUE]))
        self.assertEqual(evidence.completion_proof(self.root, self.stage_refs), proof)
        self.assertEqual(before, self.snapshot())
        serialized = json.dumps(proof)
        self.assertNotIn(VALUE, serialized)
        self.assertNotIn('messages', serialized)

    def test_no_key_provider_or_socket_access(self):
        original = Path.read_bytes
        original_open = os.open
        opened = []
        def check_path(path):
            path = Path(path)
            relative = path.relative_to(self.root).as_posix()
            self.assertTrue(relative.startswith(('runtime_cache/', 'round5/provider/K/')))
            self.assertNotIn('.env', relative)
            opened.append(relative)
        def guarded(path):
            check_path(path)
            return original(path)
        def guarded_open(path, flags, *args, **kwargs):
            check_path(path)
            self.assertEqual(flags & os.O_ACCMODE, os.O_RDONLY)
            return original_open(path, flags, *args, **kwargs)
        with (patch.object(Path, 'read_bytes', guarded),
              patch('os.open', side_effect=guarded_open),
              patch('opt_provider.read_credentials', side_effect=AssertionError('key')),
              patch('socket.socket', side_effect=AssertionError('network'))):
            evidence.completion_proof(self.root, self.stage_refs)
        self.assertTrue(opened)

    def test_cache_deleted_rejected(self):
        self.cache.unlink()
        self.assert_rejected()

    def test_cache_model_value_request_hash_and_value_hash_mutations_rejected(self):
        raw = self.cache.read_bytes()
        for key, value in (('model', 'wrong-model'), ('value', 'changed'),
                           ('request_hash', 'f' * 64), ('value_hash', 'f' * 64)):
            with self.subTest(field=key):
                changed = json.loads(raw); changed[key] = value
                self.json_put(self.cache, changed)
                self.assert_rejected()
                self.cache.write_bytes(raw)

    def test_consistently_rehashed_forged_cache_value_fails_sealed_ref(self):
        cache = json.loads(self.cache.read_bytes()); cache['value'] = 'different valid cached text'
        cache['value_hash'] = fingerprint(cache['value']); self.json_put(self.cache, cache)
        self.assert_rejected(lambda: evidence.verify_refs(self.root, self.refs, [VALUE]))

    def test_counter_deleted_rejected(self):
        self.counter.unlink()
        self.assert_rejected()

    def test_counter_namespace_hash_four_noninteger_and_negative_rejected(self):
        raw = self.counter.read_bytes()
        mutations = [('namespace', 'old-namespace'), ('request_hash', 'f' * 64),
                     ('attempts', 4), ('attempts', 1.0), ('attempts', True), ('attempts', '1'), ('attempts', -1)]
        for key, value in mutations:
            with self.subTest(field=key, value=value):
                changed = json.loads(raw); changed[key] = value
                self.json_put(self.counter, changed)
                self.assert_rejected()
                self.counter.write_bytes(raw)

    def test_success_on_third_reserved_transmission_is_valid(self):
        self.cache.unlink(); self.counter.unlink(); self.log.unlink()
        request_hash = self.request('third-success', attempts=3)
        proof = evidence.completion_proof(self.root, {'stage': {
            'refs': [self.ref(request_hash)], 'values': [VALUE]}})
        self.assertEqual(proof['counts']['reserved_attempts'], 3)
        self.assertEqual(proof['counts']['logged_attempts'], 3)
        self.assertEqual(proof['counts']['transmissions'], 3)
        self.assertEqual(proof['counts']['pending_count'], 0)

    def test_log_deleted_or_truncated_rejected(self):
        raw = self.log.read_bytes()
        self.log.unlink(); self.assert_rejected()
        self.put(LOG, raw[:-9]); self.assert_rejected()

    def test_log_request_route_requested_served_model_and_attempt_tampering_rejected(self):
        raw = self.log.read_bytes()
        for key, value in (('request_hash', 'f' * 64), ('endpoint', 'https://wrong.invalid/v1/chat/completions'),
                           ('model_requested', 'wrong-model'), ('model_served', 'wrong-model'),
                           ('role', 'embedding'), ('attempt', 2), ('attempt', True), ('attempt', 1.0)):
            with self.subTest(field=key):
                changed = json.loads(raw); changed[key] = value
                self.put(LOG, encoded(changed)); self.assert_rejected(); self.put(LOG, raw)

    def test_duplicate_transmission_log_entry_rejected(self):
        self.put(LOG, self.log.read_bytes() * 2)
        self.assert_rejected()

    def test_cache_without_successful_transmission_evidence_rejected(self):
        self.put(LOG, encoded(self.log_record(self.request_hash, success=False)))
        self.assert_rejected()

    def test_success_counter_must_cover_the_logged_attempt(self):
        counter = json.loads(self.counter.read_bytes()); counter['attempts'] = 0
        self.json_put(self.counter, counter)
        self.assert_rejected()

    def test_pending_crash_reservations_without_logs_are_explicit(self):
        self.request('pending', attempts=2, success=False, logged_attempts=0)
        proof = evidence.audit_state(self.root, allow_incomplete=True)
        self.assertEqual(proof['counts']['request_count'], 2)
        self.assertEqual(proof['counts']['success_count'], 1)
        self.assertEqual(proof['counts']['pending_count'], 1)
        self.assertEqual(proof['counts']['reserved_attempts'], 3)
        self.assertEqual(proof['counts']['unlogged_attempts'], 2)
        self.assertEqual(proof['counts']['logged_attempts'], 1)
        self.assertEqual(proof['counts']['transmissions'], 1)
        self.assert_rejected(lambda: evidence.audit_state(self.root, allow_incomplete=False))
        self.assert_rejected()

    def test_reserved_gap_before_later_success_is_counted_not_invented_as_log(self):
        counter = json.loads(self.counter.read_bytes()); counter['attempts'] = 2
        self.json_put(self.counter, counter)
        log = json.loads(self.log.read_bytes()); log['attempt'] = 2; self.put(LOG, encoded(log))
        proof = evidence.completion_proof(self.root, self.stage_refs)
        self.assertEqual(proof['counts']['reserved_attempts'], 2)
        self.assertEqual(proof['counts']['logged_attempts'], 1)
        self.assertEqual(proof['counts']['unlogged_attempts'], 1)
        self.assertEqual(proof['counts']['transmissions'], 1)

    def test_pending_three_rejected_globally_but_other_success_target_unaffected(self):
        pending = self.request('pending-three', attempts=3, success=False, logged_attempts=0)
        for allow in (False, True):
            self.assert_rejected(lambda: evidence.audit_state(self.root, allow_incomplete=allow))
        self.assert_rejected(lambda: evidence.audit_request(self.root, pending, allow_incomplete=True))
        proof = evidence.audit_request(self.root, self.request_hash, allow_incomplete=False)
        self.assertEqual(proof['counts']['request_count'], 1)
        self.assertIsNone(evidence.verify_refs(self.root, self.refs, [VALUE]))

    def test_new_target_can_be_audited_during_an_unrelated_exhausted_request(self):
        self.request('other-pending', attempts=3, success=False, logged_attempts=0)
        new_hash = fingerprint({'invented': 'new-request'})
        proof = evidence.audit_request(self.root, new_hash, allow_incomplete=True)
        self.assertEqual(proof['counter_sha256'], {})
        self.assertEqual(proof['cache_sha256'], {})
        self.assertTrue(all(value == 0 for value in proof['counts'].values()))

    def test_cache_reused_ref_does_not_claim_another_transmission(self):
        refs = self.refs + [self.ref(self.request_hash, cache_present_before=True)]
        proof = evidence.completion_proof(self.root, {'first': self.stage_refs['synthetic-stage'],
            'reused': {'refs': refs[1:], 'values': [VALUE]}})
        self.assertEqual(proof['stage_count'], 2)
        self.assertEqual(proof['ref_count'], 2)
        self.assertEqual(proof['counts']['success_count'], 1)
        self.assertEqual(proof['counts']['transmissions'], 1)
        self.assertIsNone(evidence.verify_refs(self.root, refs, [VALUE, VALUE]))

    def test_require_success_refs_and_ref_value_hash_cannot_be_forged(self):
        self.assertEqual(evidence.audit_state(self.root, require_success_refs=self.refs)['counts']['success_count'], 1)
        for key, value in (('value_hash', 'f' * 64), ('request_hash', 'f' * 64), ('role', 'embedding'),
                           ('status', 'raised'), ('cache_present_before', 'false')):
            refs = deepcopy(self.refs); refs[0][key] = value
            with self.subTest(field=key):
                self.assert_rejected(lambda: evidence.verify_refs(self.root, refs, [VALUE]))
        self.assert_rejected(lambda: evidence.verify_refs(self.root, self.refs, ['different']))
        self.assert_rejected(lambda: evidence.verify_refs(self.root, self.refs, []))
        refs = deepcopy(self.refs); refs[0]['value_hash'] = 'f' * 64
        self.assert_rejected(lambda: evidence.audit_state(self.root, require_success_refs=refs))

    def test_nonstop_empty_chat_value_remains_valid_terminal_service_evidence(self):
        cache = json.loads(self.cache.read_bytes()); cache.update(value='', value_hash=fingerprint(''))
        self.json_put(self.cache, cache)
        log = json.loads(self.log.read_bytes()); log['finish_reason'] = 'length'; self.put(LOG, encoded(log))
        refs = [self.ref(self.request_hash, value='')]
        self.assertIsNone(evidence.verify_refs(self.root, refs, ['']))
        self.assertEqual(evidence.completion_proof(self.root, {'stage': {'refs': refs, 'values': ['']}})['counts']['success_count'], 1)

    def test_other_namespace_counter_and_cache_do_not_pollute_proof(self):
        before = evidence.completion_proof(self.root, self.stage_refs)
        other = self.request('old-method', namespace='external-gallery-r4.1')
        self.put(self.cache_path(other), b'not even a K cache JSON')
        self.assertEqual(evidence.completion_proof(self.root, self.stage_refs), before)
        counter = json.loads((self.root / self.counter_path(other)).read_bytes()); counter['attempts'] = 2
        self.put(self.counter_path(other), encoded(counter))
        self.assertEqual(evidence.completion_proof(self.root, self.stage_refs), before)
        self.assert_rejected(lambda: evidence.audit_request(self.root, other, allow_incomplete=True))

    def test_every_bound_file_byte_change_changes_proof_or_rejects(self):
        before = evidence.completion_proof(self.root, self.stage_refs)
        for path in (self.cache, self.counter, self.log):
            raw = path.read_bytes()
            with self.subTest(file_kind=path.parent.name):
                path.write_bytes(raw + b' ')
                try:
                    after = evidence.completion_proof(self.root, self.stage_refs)
                except evidence.ServiceEvidenceError:
                    pass
                else:
                    self.assertNotEqual(after, before)
                path.write_bytes(raw)

    def test_symlink_cache_counter_log_and_parent_rejected(self):
        for path in (self.cache, self.counter, self.log):
            raw = path.read_bytes(); target = path.with_suffix('.fixture-target')
            target.write_bytes(raw); target.chmod(0o600); path.unlink(); path.symlink_to(target)
            with self.subTest(kind=path.parent.name): self.assert_rejected()
            path.unlink(); target.unlink(); path.write_bytes(raw); path.chmod(0o600)
        directory = self.cache.parent; target = directory.with_name('chat-target')
        directory.rename(target); directory.symlink_to(target, target_is_directory=True)
        self.assert_rejected()

    def test_request_hash_path_traversal_rejected(self):
        for bad in ('../../outside', '/absolute', 'a' * 63, 'a' * 65, 'G' * 64):
            refs = deepcopy(self.refs); refs[0]['request_hash'] = bad
            with self.subTest(kind=bad):
                self.assert_rejected(lambda: evidence.verify_refs(self.root, refs, [VALUE]))
                self.assert_rejected(lambda: evidence.audit_request(self.root, bad, allow_incomplete=True))

    def test_duplicate_json_keys_rejected(self):
        raw = self.counter.read_bytes()
        self.counter.write_bytes(raw.rstrip()[:-1] + b',"attempts":1}\n')
        self.assert_rejected()


if __name__ == '__main__':
    unittest.main()
