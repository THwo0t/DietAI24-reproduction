"""Synthetic HTTP/ledger fixtures only; no credentials, dataset, or network."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

V2 = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(V2), str(V2 / 'src')]
import httpx
import opt_provider as old
from round4.continuation import provider as p
from round4.continuation import integrity as i
from round4.src.artifacts import canonical


MESSAGES = [{'role': 'user', 'content': 'synthetic unchanged request'}]


def request_hash(messages=MESSAGES):
    return old.fingerprint({'url': old.CHAT_URL, 'payload': {'model': old.CHAT_MODEL,
        'temperature': 1, 'max_completion_tokens': 4096, 'messages': messages}, 'namespace': i.NAMESPACE})


class Fixture:
    """Small registration authoring fixture; never reads the workspace data."""
    def __init__(self, root):
        self.root = root
        self.exception = request_hash()
        for name in i.NEW_SOURCES:
            self.put(name, b'synthetic source\n')
        self.put(i.PROTOCOL, b'synthetic registered service policy\n')
        self.put('src/opt_provider.py', b'synthetic old source\n')
        self.put('round4/execution_readiness.json', {'source_sha256': {
            'src/opt_provider.py': self.sha('src/opt_provider.py')}})
        self.put(i.OLD_RUN + '/intent.json', {'synthetic': 'old intent'})
        self.put('round4/runs/J_gallery/completion.json', {'synthetic': 'gallery seal'})
        self.put('round4/data/train/freeze.json', {'synthetic': 'train freeze'})
        self.put('data/cohorts/dev.jsonl', b'synthetic fixed manifest\n')
        self.counter('chat', self.exception, 3)
        self.logs = [{'role': 'chat', 'request_hash': self.exception, 'attempt': n,
                      'status': None, 'error_type': 'ReadTimeout'} for n in (1, 2, 3)]

    def put(self, name, value):
        target = self.root / name
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        for directory in target.parents:
            if directory == self.root:
                break
            directory.chmod(0o700)
        target.write_bytes(value if isinstance(value, bytes) else canonical(value))
        target.chmod(0o600)
        return target

    def sha(self, name):
        return i.digest((self.root / name).read_bytes())

    def counter(self, role, h, count):
        # Actual frozen opt_provider.atomic_json encoding/order, independently
        # expressed here rather than using continuation's reconstruction helper.
        state = {'request_hash': h, 'attempts': count,
                 'last_reserved': 'original-time', 'namespace': i.NAMESPACE}
        self.put(f'runtime_cache/attempts/{role}/{h}.json',
            (json.dumps(state, indent=2, ensure_ascii=False, allow_nan=False) + '\n').encode())

    def cache(self, value, h=None, role='chat'):
        h = h or old.fingerprint({'synthetic_response': value, 'role': role})
        self.put(f'runtime_cache/responses/{role}/{h}.json', {'request_hash': h,
            'model': old.CHAT_MODEL if role == 'chat' else old.EMBED_MODEL,
            'value': value, 'value_hash': old.fingerprint(value)})
        self.counter(role, h, 1)
        self.logs.append({'role': role, 'request_hash': h, 'attempt': 1, 'status': 200,
                          'model_served': old.CHAT_MODEL if role == 'chat' else old.EMBED_MODEL})
        return {'role': role, 'request_hash': h, 'value_hash': old.fingerprint(value),
                'status': 'returned', 'cache_present_before': False}

    def register(self):
        self.put('round4/provider/J/requests.jsonl', b''.join(canonical(r) for r in self.logs))
        files = {f.relative_to(self.root).as_posix(): i.digest(f.read_bytes())
                 for f in sorted((self.root / i.OLD_RUN).rglob('*'))
                 if f.is_file() and f.name != '.lock' and not f.name.endswith('.lock')}
        self.put(i.SNAPSHOT, {'schema_version': 1, 'root': i.OLD_RUN, 'files': files})
        caches = {f.relative_to(self.root).as_posix(): i.digest(f.read_bytes())
                  for f in (self.root / 'runtime_cache/responses').rglob('*.json')} if (
                      self.root / 'runtime_cache/responses').exists() else {}
        counters = {f.relative_to(self.root).as_posix(): {'sha256': i.digest(f.read_bytes()),
                    'state': json.loads(f.read_bytes())}
                    for f in (self.root / 'runtime_cache/attempts').rglob('*.json')}
        registration = {'schema_version': 1, 'namespace': i.NAMESPACE, 'original_base_dir': i.OLD_RUN,
            'continuation_base_dir': i.NEW_RUN,
            'protocol': {'path': i.PROTOCOL, 'sha256': self.sha(i.PROTOCOL)},
            'readiness': {'path': 'round4/execution_readiness.json',
                          'sha256': self.sha('round4/execution_readiness.json')},
            'original_source_sha256': {'src/opt_provider.py': self.sha('src/opt_provider.py')},
            'continuation_source_sha256': {name: self.sha(name) for name in i.NEW_SOURCES},
            'original_base_intent_sha256': self.sha(i.OLD_RUN + '/intent.json'),
            'gallery_completion_sha256': self.sha('round4/runs/J_gallery/completion.json'),
            'training_freeze_sha256': self.sha('round4/data/train/freeze.json'),
            'query_manifest_sha256': self.sha('data/cohorts/dev.jsonl'),
            'old_stage_snapshot': {'path': i.SNAPSHOT, 'sha256': self.sha(i.SNAPSHOT)},
            'original_log_sha256': {'round4/provider/J/requests.jsonl': self.sha('round4/provider/J/requests.jsonl')},
            'successful_cache_sha256': caches, 'attempt_snapshots': counters,
            'policy': i.policy(self.exception)}
        self.put(i.REGISTRATION, registration)
        return i.Registration(self.root)


class ProviderTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.fixture = Fixture(self.root)
        patcher = patch.object(old, 'ROOT', self.root)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.calls, self.sleeps = [], []

    def provider(self, responder, registration=None):
        def handle(request):
            self.calls.append(request)
            return responder(request)
        result = p.ContinuationProvider(self.root / i.PROVIDER_RUN,
            registration or self.fixture.register(), allow_paid=True,
            keys=('synthetic-chat-credential', 'synthetic-embedding-credential'),
            transport=httpx.MockTransport(handle), sleep=self.sleeps.append)
        self.addCleanup(result.close)
        return result

    def success(self, request, value='synthetic response', finish='stop', model=old.CHAT_MODEL):
        return httpx.Response(200, json={'model': model, 'choices': [
            {'finish_reason': finish, 'message': {'content': value}}]})

    def timeout(self, request):
        raise httpx.ReadTimeout('synthetic timeout', request=request)

    def test_exception_fourth_only_and_exact_payload_namespace_timeouts(self):
        reg = self.fixture.register()
        original_counter = deepcopy(reg.data['attempt_snapshots'])
        provider = self.provider(self.success, reg)
        self.assertEqual(provider.chat(MESSAGES), 'synthetic response')
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.calls[0].extensions['timeout'], {'connect': 30, 'read': 600, 'write': 120, 'pool': 120})
        self.assertEqual(provider.namespace, i.NAMESPACE)
        self.assertEqual(provider.chat(MESSAGES), 'synthetic response')
        self.assertEqual(len(self.calls), 1)
        row = reg.audit_rows()[0]
        self.assertEqual((row['previous_attempts'], row['attempt']), (3, 4))
        self.assertEqual(reg.data['attempt_snapshots'], original_counter)
        self.assertEqual(reg.attempt_states()[f'runtime_cache/attempts/chat/{self.fixture.exception}.json']['state']['attempts'], 4)

    def test_fourth_timeout_stops_no_backoff_index_error_and_no_fifth_on_resume(self):
        reg = self.fixture.register()
        provider = self.provider(self.timeout, reg)
        with self.assertRaises(old.ProviderStop):
            provider.chat(MESSAGES)
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.sleeps, [])
        resumed = self.provider(self.success, reg)
        with self.assertRaises(old.ProviderStop):
            resumed.chat(MESSAGES)
        self.assertEqual(len(self.calls), 1)
        self.assertEqual([r['attempt'] for r in reg.audit_rows()], [4])

    def test_other_payload_default_three_and_restart_cannot_reset(self):
        reg = self.fixture.register()
        messages = [{'role': 'user', 'content': 'different synthetic request'}]
        provider = self.provider(self.timeout, reg)
        with self.assertRaises(old.ProviderStop):
            provider.chat(messages)
        self.assertEqual(len(self.calls), 3)
        self.assertEqual(self.sleeps, [2, 8])
        with self.assertRaises(old.ProviderStop):
            self.provider(self.success, reg).chat(messages)
        self.assertEqual(len(self.calls), 3)
        self.assertEqual([r['attempt'] for r in reg.audit_rows()], [1, 2, 3])

    def test_existing_other_count_two_gets_only_third(self):
        messages = [{'role': 'user', 'content': 'partially attempted synthetic request'}]
        h = request_hash(messages)
        self.fixture.counter('chat', h, 2)
        reg = self.fixture.register()
        self.provider(self.success, reg).chat(messages)
        self.assertEqual([r['attempt'] for r in reg.audit_rows()], [3])
        self.assertEqual(len(self.calls), 1)

    def test_write_ahead_reservation_crash_consumes_fourth_before_http(self):
        reg = self.fixture.register()
        provider = self.provider(self.success, reg)
        with patch.object(p, '_durable_counter', side_effect=RuntimeError('synthetic disk interruption')):
            with self.assertRaises(RuntimeError):
                provider.chat(MESSAGES)
        self.assertEqual(self.calls, [])
        with self.assertRaises(Exception):
            reg.attempt_states()
        resumed = self.provider(self.success, reg)
        with self.assertRaises(old.ProviderStop):
            resumed.chat(MESSAGES)
        self.assertEqual(self.calls, [])
        self.assertEqual(len(reg.audit_rows()), 1)
        reg.attempt_states()

    def test_original_counter_rewind_and_unregistered_counter_rejected(self):
        reg = self.fixture.register()
        self.fixture.counter('chat', self.fixture.exception, 2)
        with self.assertRaisesRegex(Exception, 'attempt_ledger_differs'):
            self.provider(self.success, reg)
        self.fixture.counter('chat', self.fixture.exception, 3)
        other = [{'role': 'user', 'content': 'unregistered existing counter'}]
        self.fixture.counter('chat', request_hash(other), 1)
        with self.assertRaisesRegex(Exception, 'unregistered_existing'):
            self.provider(self.success, reg).chat(other)
        self.assertEqual(self.calls, [])

    def test_actual_count_three_with_registered_state_two_and_correct_hash_sends_zero_http(self):
        messages = [{'role': 'user', 'content': 'already exhausted ordinary payload'}]
        h = request_hash(messages)
        self.fixture.counter('chat', h, 3)
        reg = self.fixture.register()
        value = deepcopy(reg.data)
        counter = f'runtime_cache/attempts/chat/{h}.json'
        original_hash = value['attempt_snapshots'][counter]['sha256']
        value['attempt_snapshots'][counter]['state']['attempts'] = 2
        self.fixture.put(i.REGISTRATION, value)
        with patch.object(old.httpx, 'Client') as client:
            with self.assertRaisesRegex(Exception, 'original_attempt_state_hash_mismatch'):
                self.provider(self.success, i.Registration(self.root)).chat(messages)
            client.assert_not_called()
        self.assertEqual(self.calls, [])
        self.assertEqual(self.fixture.sha(counter), original_hash)
        self.assertEqual(json.loads((self.root / counter).read_bytes())['attempts'], 3)

    def test_sorted_registration_preserves_old_hash_and_advanced_restart_still_checks_baseline(self):
        reg = self.fixture.register()  # Fixture canonical registration sorts nested state keys.
        self.provider(self.success, reg).chat(MESSAGES)
        resumed = i.Registration(self.root)
        resumed.attempt_states()
        self.assertEqual(self.provider(self.success, resumed).chat(MESSAGES), 'synthetic response')
        self.assertEqual(len(self.calls), 1)
        # Current counter is now four, but the original byte-equivalent state
        # remains independently verifiable from its registered original SHA.
        value = deepcopy(resumed.data)
        name = f'runtime_cache/attempts/chat/{self.fixture.exception}.json'
        value['attempt_snapshots'][name]['state']['last_reserved'] = 'changed-original-time'
        self.fixture.put(i.REGISTRATION, value)
        with self.assertRaisesRegex(Exception, 'original_attempt_state_hash_mismatch'):
            i.Registration(self.root)

    def test_exception_requires_exact_three_readtimeouts_and_no_prior_cache(self):
        self.fixture.logs[-1]['error_type'] = 'ConnectTimeout'
        with self.assertRaisesRegex(Exception, 'exception_not_three_read_timeouts'):
            self.fixture.register()
        self.fixture.logs[-1]['error_type'] = 'ReadTimeout'
        self.fixture.cache('already returned', h=self.fixture.exception)
        self.fixture.counter('chat', self.fixture.exception, 3)
        with self.assertRaisesRegex(Exception, 'original_success_cache'):
            self.fixture.register()

    def test_model_stop_contract_and_model_mismatch_unchanged(self):
        reg = self.fixture.register()
        provider = self.provider(lambda req: self.success(req, finish='length'), reg)
        self.assertEqual(provider.chat(MESSAGES), '')
        messages = [{'role': 'user', 'content': 'different model response'}]
        with self.assertRaises(old.ProviderStop):
            self.provider(lambda req: self.success(req, model='different-model'), reg).chat(messages)

    def test_original_log_cache_or_source_mutation_rejected(self):
        self.fixture.cache('synthetic prior response')
        reg = self.fixture.register()
        for name in ['src/opt_provider.py', 'round4/provider/J/requests.jsonl',
                     next(iter(reg.data['successful_cache_sha256']))]:
            target = self.root / name
            before = target.read_bytes()
            target.write_bytes(before + b' ')
            with self.assertRaisesRegex(Exception, 'registered_file_changed'):
                reg.verify_static()
            target.write_bytes(before)

    def test_no_paid_flag_and_offscope_path_do_not_construct_http_client(self):
        reg = self.fixture.register()
        with patch.object(old.httpx, 'Client') as client:
            with self.assertRaises(old.ProviderStop):
                p.ContinuationProvider(self.root / i.PROVIDER_RUN, reg, allow_paid=False,
                    keys=('synthetic-chat', 'synthetic-embedding'))
            client.assert_not_called()


if __name__ == '__main__':
    unittest.main()
