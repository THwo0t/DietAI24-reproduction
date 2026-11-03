import sys
from pathlib import Path
import tempfile
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import patch
import json
import httpx
from copy import deepcopy

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / 'src')]
from opt_provider import ProviderStop
from round6.src.runtime import BoundTrace, PilotProvider, NAMESPACE
from round6.src import runtime
from round6.src import service_evidence as evidence
from round4.src.artifacts import ArtifactStore

URL_A = 'data:image/png;base64,QUFB'
URL_B = 'data:image/png;base64,QkJC'


class Fake:
    namespace = NAMESPACE

    def __init__(self, cache):
        self.cache, self.calls, self.error = cache, 0, None

    def chat(self, messages, max_completion_tokens=4096):
        self.calls += 1
        if self.error:
            raise self.error
        return '{"ok":true}'


def messages(*urls):
    return [{'role': 'user', 'content': [
        {'type': 'image_url', 'image_url': {'url': url}} for url in urls]}]


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.fake = Fake(Path(self.temp.name))
        self.trace = BoundTrace(self.fake)

    def test_ordered_binding_and_repair_receipts(self):
        with self.trace.expect([URL_A, URL_B]):
            mark = self.trace.mark()
            self.trace.chat(messages(URL_A, URL_B))
            self.trace.chat(messages(URL_A, URL_B) + [{'role': 'user', 'content': 'format repair'}])
        refs = self.trace.refs_since(mark)
        self.assertEqual(len(refs), 2)
        self.assertTrue(all(row['status'] == 'returned' for row in refs))
        self.assertNotEqual(refs[0]['request_hash'], refs[1]['request_hash'])
        self.assertNotIn('messages', refs[0])
        refs[0]['status'] = 'changed'
        self.assertEqual(self.trace.refs_since(0)[0]['status'], 'returned')

    def test_swapped_or_added_image_fails_before_provider(self):
        with self.trace.expect([URL_A, URL_B]):
            for urls in ((URL_B, URL_A), (URL_A,), (URL_A, URL_B, URL_A)):
                with self.assertRaises(ValueError):
                    self.trace.chat(messages(*urls))
        self.assertEqual(self.fake.calls, 0)

    def test_scope_and_namespace_are_mandatory(self):
        with self.assertRaises(ValueError):
            self.trace.chat(messages(URL_A))
        self.fake.namespace = 'old-run'
        with self.trace.expect([URL_A]):
            with self.assertRaises(ValueError):
                self.trace.chat(messages(URL_A))
        self.assertEqual(self.fake.calls, 0)

    def test_exception_propagates_and_never_becomes_success(self):
        error = ProviderStop('invented service fault')
        self.fake.error = error
        with self.trace.expect([URL_A]):
            with self.assertRaises(ProviderStop) as caught:
                self.trace.chat(messages(URL_A))
        self.assertIs(caught.exception, error)
        self.assertEqual(self.trace.refs_since(0)[0]['status'], 'raised')
        self.assertIsNone(self.trace.refs_since(0)[0]['value_hash'])

    def test_scope_restored_after_exception_and_no_embeddings(self):
        with self.assertRaises(RuntimeError):
            with self.trace.expect([URL_A]):
                raise RuntimeError('fixture')
        with self.trace.expect([URL_A]):
            self.trace.chat(messages(URL_A))
        with self.assertRaises(ProviderStop):
            self.trace.embed(['not sent'])

    def test_local_image_bound_and_maximum(self):
        for urls in ([], [URL_A] * 14, ['https://example.invalid/image.png']):
            with self.assertRaises(ValueError):
                with self.trace.expect(urls):
                    self.fail('invalid image scope entered')
        with self.trace.expect([URL_A] * 13):
            self.trace.chat(messages(*([URL_A] * 13)))
        self.assertEqual(self.fake.calls, 1)

    def test_thread_local_images_and_receipts(self):
        barrier, counts, errors = threading.Barrier(2), [], []
        def worker(url):
            try:
                with self.trace.expect([url]):
                    barrier.wait()
                    self.trace.chat(messages(url))
                counts.append(len(self.trace.refs_since(0)))
            except BaseException as exc:
                errors.append(type(exc).__name__)
        threads = [threading.Thread(target=worker, args=(u,)) for u in (URL_A, URL_B)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(errors, [])
        self.assertEqual(counts, [1, 1])
        self.assertEqual(self.trace.refs_since(0), [])

    def test_transport_settings_extend_only_registered_timeout(self):
        seen = {}
        def parent_init(instance, run_dir, **kwargs):
            seen.update(kwargs)
            instance.client = SimpleNamespace(timeout=None)
        with patch('round6.src.runtime.Provider.__init__', parent_init), \
             patch('round6.src.runtime.audit_state', return_value={}):
            provider = PilotProvider(runtime.original.ROOT / runtime.PROVIDER_DIRECTORY, allow_paid=True)
        self.assertEqual(seen['namespace'], NAMESPACE)
        self.assertEqual(seen['timeout'], 600)
        timeout = provider.client.timeout
        self.assertEqual((timeout.read, timeout.connect, timeout.write, timeout.pool), (600, 30, 120, 120))

    def test_interrupted_reserved_attempt_is_preserved_across_provider_restart(self):
        root = Path(self.temp.name)
        keys = ('invented-chat-credential', 'invented-embedding-credential')
        transmissions = []
        def interrupted(request):
            transmissions.append(1)
            raise KeyboardInterrupt()
        def success(request):
            transmissions.append(1)
            return httpx.Response(200, json={'model': 'gpt-6.1-sol', 'choices': [
                {'message': {'content': '{"ok":true}'}, 'finish_reason': 'stop'}], 'usage': {}})
        with patch.object(runtime.original, 'ROOT', root):
            first = PilotProvider(root / 'round6/provider/L', allow_paid=True, keys=keys,
                                      transport=httpx.MockTransport(interrupted))
            try:
                with self.assertRaises(KeyboardInterrupt):
                    first.chat(messages(URL_A))
            finally:
                first.close()
            second = PilotProvider(root / 'round6/provider/L', allow_paid=True, keys=keys,
                                       transport=httpx.MockTransport(success))
            try:
                self.assertEqual(second.chat(messages(URL_A)), '{"ok":true}')
            finally:
                second.close()
        counter = next((root / 'runtime_cache/attempts/chat').glob('*.json'))
        self.assertEqual(json.loads(counter.read_text())['attempts'], 2)
        rows = (root / 'round6/provider/L/requests.jsonl').read_text().splitlines()
        self.assertEqual(len(rows), 1)
        self.assertEqual(json.loads(rows[0])['attempt'], 2)
        self.assertEqual(len(transmissions), 2)

    def test_exhausted_unlogged_reservations_block_next_provider_before_http(self):
        root = Path(self.temp.name)
        keys = ('invented-chat-credential', 'invented-embedding-credential')
        transmissions = []
        def interrupted(request):
            transmissions.append(1)
            raise KeyboardInterrupt()
        with patch.object(runtime.original, 'ROOT', root):
            for _ in range(3):
                provider = PilotProvider(root / 'round6/provider/L', allow_paid=True, keys=keys,
                                             transport=httpx.MockTransport(interrupted))
                try:
                    with self.assertRaises(KeyboardInterrupt):
                        provider.chat(messages(URL_A))
                finally:
                    provider.close()
            with self.assertRaises(Exception):
                PilotProvider(root / 'round6/provider/L', allow_paid=True, keys=keys,
                                  transport=httpx.MockTransport(interrupted))
        self.assertEqual(len(transmissions), 3)


class RealTransportEvidenceTests(unittest.TestCase):
    """Real Provider-shaped output generated by MockTransport, never HTTP."""
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='synthetic-l-transport-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.patch_root = patch.object(runtime.original, 'ROOT', self.root)
        self.patch_root.start()
        self.addCleanup(self.patch_root.stop)
        self.sent = []
        self.provider = self.new_provider(self.success)
        self.trace = BoundTrace(self.provider)

    def success(self, request):
        self.sent.append(json.loads(request.content))
        return httpx.Response(200, json={'model': 'gpt-6.1-sol', 'choices': [
            {'message': {'content': '{"synthetic":true}'}, 'finish_reason': 'stop'}],
            'usage': {'prompt_tokens': 1, 'completion_tokens': 1, 'total_tokens': 2}})

    def new_provider(self, transport):
        provider = PilotProvider(self.root / runtime.PROVIDER_DIRECTORY, allow_paid=True,
            keys=('invented-chat-credential', 'invented-embedding-credential'),
            transport=httpx.MockTransport(transport), sleep=lambda _: None)
        self.addCleanup(provider.close)
        return provider

    def returned(self, *, repair=False):
        cursor = self.trace.mark()
        with self.trace.expect([URL_A]):
            values = [self.trace.chat(messages(URL_A), max_completion_tokens=8192)]
            if repair:
                values.append(self.trace.chat(messages(URL_A) + [
                    {'role': 'user', 'content': 'format repair only'}], max_completion_tokens=8192))
        return {'refs': self.trace.refs_since(cursor), 'values': values}

    def snapshot(self):
        return {str(p.relative_to(self.root)): (p.read_bytes(), p.stat().st_mtime_ns)
                for p in self.root.rglob('*') if p.is_file()}

    def test_real_receipts_repair_and_cache_reuse(self):
        stage = self.returned(repair=True)
        proof = evidence.completion_proof(self.root, {'annotation': stage})
        self.assertEqual(proof['counts']['transmissions'], 2)
        self.assertEqual(len(self.sent), 2)
        again = self.returned(repair=True)
        self.assertTrue(all(ref['cache_present_before'] for ref in again['refs']))
        self.assertEqual(evidence.completion_proof(self.root, {'annotation': stage}), proof)
        self.assertEqual(len(self.sent), 2)
        self.assertTrue(all(payload['max_completion_tokens'] == 8192 for payload in self.sent))

    def test_real_cache_counter_and_log_tampering_rejected(self):
        stage = self.returned()
        h = stage['refs'][0]['request_hash']
        cache = self.root / f'runtime_cache/responses/chat/{h}.json'
        counter = self.root / f'runtime_cache/attempts/chat/{h}.json'
        log = self.root / evidence.LOG
        changes = [(cache, 'model', 'wrong'), (cache, 'request_hash', 'f' * 64),
                   (cache, 'value', 'tampered'), (cache, 'value_hash', 'f' * 64),
                   (counter, 'namespace', 'old-namespace'), (counter, 'request_hash', 'f' * 64),
                   (counter, 'attempts', 2), (counter, 'attempts', 4),
                   (log, 'model_requested', 'wrong'), (log, 'model_served', 'wrong'),
                   (log, 'endpoint', 'https://wrong.invalid'), (log, 'attempt', 2),
                   (log, 'request_hash', 'f' * 64)]
        for path, field, value in changes:
            with self.subTest(file=path.parent.name, field=field):
                raw = path.read_bytes()
                obj = json.loads(raw); obj[field] = value
                path.write_text(json.dumps(obj) + '\n')
                try:
                    with self.assertRaises(evidence.ServiceEvidenceError):
                        evidence.completion_proof(self.root, {'stage': stage})
                finally:
                    path.write_bytes(raw)
        self.assertEqual(len(self.sent), 1)

    def test_rehashed_forgery_and_saved_completion_proof_detect_changes(self):
        stage = self.returned()
        proof = evidence.completion_proof(self.root, {'stage': stage})
        h = stage['refs'][0]['request_hash']
        cache = self.root / f'runtime_cache/responses/chat/{h}.json'
        original = cache.read_bytes()
        obj = json.loads(original); obj['value'] = 'forged'
        obj['value_hash'] = runtime.fingerprint(obj['value'])
        cache.write_text(json.dumps(obj) + '\n')
        with self.assertRaises(evidence.ServiceEvidenceError):
            evidence.verify_refs(self.root, stage['refs'], stage['values'])
        cache.write_bytes(original + b' ')
        self.assertNotEqual(evidence.completion_proof(self.root, {'stage': stage}), proof)
        cache.unlink()
        with self.assertRaises(evidence.ServiceEvidenceError):
            evidence.completion_proof(self.root, {'stage': stage})

    def test_fsync_failure_consumes_attempt_without_sending_or_rollback(self):
        with patch.object(runtime.os, 'fsync', side_effect=OSError('synthetic fsync failure')):
            with self.assertRaises(OSError):
                self.provider.chat(messages(URL_A))
        self.assertEqual(self.sent, [])
        counter = next((self.root / 'runtime_cache/attempts/chat').glob('*.json'))
        self.assertEqual(json.loads(counter.read_text())['attempts'], 1)
        proof = evidence.audit_state(self.root)
        self.assertEqual(proof['counts']['unlogged_attempts'], 1)
        self.new_provider(self.success).chat(messages(URL_A))
        self.assertEqual(json.loads(counter.read_text())['attempts'], 2)
        self.assertEqual(len(self.sent), 1)

    def test_counter_file_and_directory_are_synced_before_http(self):
        calls = []
        original_fsync = runtime.os.fsync
        def fsync(fd):
            calls.append('fsync')
            original_fsync(fd)
        def response(request):
            self.assertEqual(calls, ['fsync', 'fsync'])
            return self.success(request)
        provider = self.new_provider(response)
        with patch.object(runtime.os, 'fsync', side_effect=fsync):
            provider.chat(messages(URL_A))
        self.assertEqual(len(self.sent), 1)

    def test_directory_fsync_failure_also_stops_before_http(self):
        real_fsync, calls = runtime.os.fsync, []
        def fsync(fd):
            calls.append(1)
            if len(calls) == 2:
                raise OSError('synthetic directory fsync failure')
            return real_fsync(fd)
        with patch.object(runtime.os, 'fsync', side_effect=fsync):
            with self.assertRaises(OSError):
                self.provider.chat(messages(URL_A))
        self.assertEqual(len(calls), 2)
        self.assertEqual(self.sent, [])
        counter = next((self.root / 'runtime_cache/attempts/chat').glob('*.json'))
        self.assertEqual(json.loads(counter.read_text())['attempts'], 1)

    def test_two_unlogged_reservations_resume_at_three_then_success(self):
        def interrupted(request):
            raise KeyboardInterrupt()
        for _ in range(2):
            provider = self.new_provider(interrupted)
            with self.assertRaises(KeyboardInterrupt):
                provider.chat(messages(URL_A))
        self.assertEqual(evidence.audit_state(self.root)['counts']['unlogged_attempts'], 2)
        provider = self.new_provider(self.success)
        trace = BoundTrace(provider)
        with trace.expect([URL_A]):
            value = trace.chat(messages(URL_A))
        proof = evidence.completion_proof(self.root, {'recovered': {
            'refs': trace.refs_since(0), 'values': [value]}})
        self.assertEqual(proof['counts']['reserved_attempts'], 3)
        self.assertEqual(proof['counts']['unlogged_attempts'], 2)
        self.assertEqual(proof['counts']['transmissions'], 1)

    def test_three_timeouts_stop_and_restart_cannot_send_fourth(self):
        attempts = []
        def timeout(request):
            attempts.append(1)
            raise httpx.ReadTimeout('synthetic timeout', request=request)
        provider = self.new_provider(timeout)
        with self.assertRaises(ProviderStop):
            provider.chat(messages(URL_A))
        self.assertEqual(len(attempts), 3)
        with self.assertRaises(evidence.ServiceEvidenceError):
            self.new_provider(timeout)
        self.assertEqual(len(attempts), 3)

    def test_auth_and_model_faults_propagate_without_fallback(self):
        for code, model in ((401, 'gpt-6.1-sol'), (200, 'wrong-model')):
            with self.subTest(code=code):
                seen = []
                def response(request):
                    seen.append(1)
                    return httpx.Response(code, json={'model': model, 'choices': []})
                provider = self.new_provider(response)
                with self.assertRaises(ProviderStop):
                    provider.chat(messages(URL_A) + [{'role': 'user', 'content': str(code)}])
                self.assertEqual(seen, [1])

    def test_completed_stage_replay_has_zero_provider_and_no_writes(self):
        store = ArtifactStore(self.root / 'sealed', {'fixture': 'L'}, ['q1'],
                              verify_sources=lambda: None, root=self.root)
        store.initialize()
        def call():
            return {'raw_outputs': [self.trace.chat(messages(URL_A))], 'failure': None}
        refs = []
        result = runtime.run_stage(self.root, store, self.trace, 'q1:rerank', {}, [URL_A],
                                   call, deepcopy, refs_sink=refs.extend)
        stage = {'refs': refs, 'values': result['raw_outputs']}
        proof = evidence.completion_proof(self.root, {'q1:rerank': stage})
        store.finalize({'q1': result})
        before = self.snapshot()
        with (patch.object(runtime, 'PilotProvider', side_effect=AssertionError('provider created')),
              patch.object(runtime.original, 'read_credentials', side_effect=AssertionError('credential read')),
              patch('socket.socket', side_effect=AssertionError('network'))):
            self.assertEqual(store.verify_completed(), {'q1': result})
            replay = runtime.run_stage(self.root, store, None, 'q1:rerank', {}, [],
                lambda: self.fail('completed call re-executed'), deepcopy)
            self.assertEqual(replay, result)
            self.assertEqual(evidence.completion_proof(self.root, {'q1:rerank': stage}), proof)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(len(self.sent), 1)

    def test_terminal_two_response_failure_is_verifiable_and_envelope_is_strict(self):
        stage = self.returned(repair=True)
        envelope = {'result': {'raw_outputs': stage['values'], 'failure': 'format_invalid'},
                    'request_refs': stage['refs']}
        self.assertEqual(runtime.validate_envelope(self.root, envelope, deepcopy), envelope)
        for bad in ({}, {**envelope, 'extra': 1},
                    {'result': {'raw_outputs': []}, 'request_refs': []},
                    {'result': {'raw_outputs': stage['values']}, 'request_refs': stage['refs'][:1]}):
            with self.subTest(fields=tuple(bad)):
                with self.assertRaises(ValueError):
                    runtime.validate_envelope(self.root, bad, deepcopy)

    def test_provider_log_scope_and_embedding_route_are_fixed(self):
        with self.assertRaises(ValueError):
            PilotProvider(self.root / 'arbitrary', allow_paid=True)
        with self.assertRaises(ProviderStop):
            self.provider.embed(['synthetic'])
        with self.assertRaises(ProviderStop):
            self.provider._reserve_attempt('a' * 64, 'embedding')
        self.assertEqual(self.sent, [])


if __name__ == '__main__':
    unittest.main()
