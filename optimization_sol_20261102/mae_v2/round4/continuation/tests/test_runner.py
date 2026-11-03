"""Offline old-seal imports and complete 84-record replay using invented data."""
from copy import deepcopy
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

V2 = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(V2), str(V2 / 'src')]
from round4.continuation import runner as r
from round4.continuation import integrity as i
from round4.continuation.tests.test_provider import Fixture
from round4.src.artifacts import ArtifactStore, TerminalStageError, key_path
import httpx
import opt_provider
from round4.src.image_guard import ImageGuard, payload_hash
from round4.src.trace_provider import TraceProvider


class NoProvider:
    def __getattr__(self, name):
        raise AssertionError('Provider/tracer must not be used on an imported stage')


class RunnerTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.fixture = Fixture(self.root)
        (self.root / i.OLD_RUN / 'intent.json').unlink()
        self.old_store = ArtifactStore(self.root / i.OLD_RUN, {'phase': 'development_base'}, ['q'],
                                       verify_sources=lambda: True, root=self.root / 'round4')
        self.old_store.initialize()
        self.old_contents = None

    def stage(self, name='query-q:estimate', inputs=None, result=None, refs=None):
        inputs = inputs if inputs is not None else {'synthetic_input': 1}
        result = result if result is not None else {'raw_outputs': ['bad first', 'bad repair'], 'failure': 'format_failure'}
        if refs is None:
            refs = [self.fixture.cache(value) for value in result['raw_outputs']]
        envelope = {'result': deepcopy(result), 'request_refs': deepcopy(refs)}
        self.old_store.stage_runner(name, inputs, lambda: envelope, deepcopy)
        return result

    def runner(self):
        reg = self.fixture.register()
        store = ArtifactStore(self.root / i.NEW_RUN,
            {**self.old_store.binding, 'service_continuation': reg.service_binding()}, ['q'],
            verify_sources=reg.verify_static, root=self.root / 'round4')
        return r.ImportRunner(self.old_store, store, NoProvider(), {}, reg)

    def inventory(self, directory=None):
        directory = directory or self.root / i.OLD_RUN
        return {str(p.relative_to(directory)): (p.stat().st_mtime_ns, p.read_bytes())
                for p in directory.rglob('*') if p.is_file()}

    def test_imported_contract_failure_keeps_both_raw_and_zero_provider(self):
        result = self.stage()
        runner = self.runner()
        before = self.inventory()
        got = runner('query-q:estimate', {'synthetic_input': 1},
                     lambda: self.fail('must not call provider'), deepcopy)
        self.assertEqual(got, result)
        self.assertEqual(got['raw_outputs'], ['bad first', 'bad repair'])
        self.assertEqual(runner.verify_import_coverage(), ['query-q:estimate'])
        self.assertEqual(before, self.inventory())
        old_body = self.old_store._json('stages/' + key_path('query-q:estimate') + '/result.json')
        new_body = runner.store._json('stages/' + key_path('query-q:estimate') + '/result.json')
        self.assertEqual(old_body, new_body)
        self.assertNotEqual(self.old_store.intent, runner.store.intent)

    def test_changed_inputs_and_source_stop_before_call(self):
        self.stage()
        runner = self.runner()
        with self.assertRaisesRegex(Exception, 'old_stage_exact_inputs_changed'):
            runner('query-q:estimate', {'synthetic_input': 2}, lambda: self.fail('called'), deepcopy)
        self.fixture.put('src/opt_provider.py', b'changed frozen source')
        with self.assertRaisesRegex(Exception, 'registered_file_changed'):
            runner('query-q:estimate', {'synthetic_input': 1}, lambda: self.fail('called'), deepcopy)

    def test_raw_output_ref_and_cache_are_linked_not_only_well_formed(self):
        wrong = self.fixture.cache('different response')
        self.stage(result={'raw_outputs': ['saved answer'], 'failure': None}, refs=[wrong])
        runner = self.runner()
        with self.assertRaisesRegex(Exception, 'raw_output_request_hash_changed'):
            runner('query-q:estimate', {'synthetic_input': 1}, lambda: self.fail('called'), deepcopy)

    def test_retrieval_must_have_no_request_refs(self):
        ref = self.fixture.cache('unrelated answer')
        self.stage(name='query-q:retrieval', result={'neighbors': []}, refs=[ref])
        runner = self.runner()
        with self.assertRaisesRegex(Exception, 'raw_output_request_count_changed'):
            runner('query-q:retrieval', {'synthetic_input': 1}, lambda: self.fail('called'), deepcopy)

    def test_embedding_raw_vector_ref_and_cache_link(self):
        vector = [1.0] + [0.0] * 3071
        ref = self.fixture.cache(vector, role='embedding')
        self.stage(name='image-q:embedding', result={'vector': vector}, refs=[ref])
        runner = self.runner()
        self.assertEqual(runner('image-q:embedding', {'synthetic_input': 1},
            lambda: self.fail('called'), deepcopy), {'vector': vector})

    def test_explicit_terminal_imported_once_and_never_provider_retried(self):
        def fail():
            raise TerminalStageError('synthetic_terminal')
        with self.assertRaises(TerminalStageError):
            self.old_store.stage_runner('query-q:estimate', {'synthetic_input': 1}, fail, deepcopy)
        runner = self.runner()
        before = self.inventory()
        for _ in range(2):
            with self.assertRaisesRegex(TerminalStageError, 'synthetic_terminal'):
                runner('query-q:estimate', {'synthetic_input': 1}, lambda: self.fail('called'), deepcopy)
        self.assertEqual(before, self.inventory())
        body = runner.store._json('stages/' + key_path('query-q:estimate') + '/result.json')
        self.assertEqual(body, {'kind': 'terminal', 'error_code': 'synthetic_terminal'})

    def test_receipted_pending_old_result_imports_without_publishing_old_file(self):
        result = self.stage()
        stage = self.root / i.OLD_RUN / 'stages' / key_path('query-q:estimate')
        (stage / 'result.json').rename(stage / 'result.json.pending')
        runner = self.runner()
        before = self.inventory()
        self.assertEqual(runner('query-q:estimate', {'synthetic_input': 1},
                               lambda: self.fail('called'), deepcopy), result)
        self.assertEqual(before, self.inventory())
        self.assertFalse((stage / 'result.json').exists())

    def test_old_seal_tampering_and_extra_snapshot_file_rejected(self):
        self.stage()
        runner = self.runner()
        target = self.old_store._path('stages/' + key_path('query-q:estimate') + '/result.seal.json')
        original = target.read_bytes()
        target.write_bytes(b'{}\n')
        with self.assertRaises(Exception):
            runner('query-q:estimate', {'synthetic_input': 1}, lambda: self.fail('called'), deepcopy)
        target.write_bytes(original)
        self.fixture.put(i.OLD_RUN + '/unexpected.json', {'extra': True})
        with self.assertRaisesRegex(Exception, 'old_stage_snapshot_changed'):
            runner.registration.verify_snapshot()

    def test_unregistered_success_cache_or_missing_success_log_rejected(self):
        self.stage()
        self.fixture.logs = self.fixture.logs[:3]
        runner = self.runner()
        with self.assertRaisesRegex(Exception, 'old_chat_success_log_missing'):
            runner('query-q:estimate', {'synthetic_input': 1}, lambda: self.fail('called'), deepcopy)

    def test_unsealed_stage_uses_original_trace_image_guard_and_new_request(self):
        name = 'image-q:description'
        image = 'data:image/png;base64,c3ludGhldGlj'
        inputs = {'image': {'image_sha256': 'a' * 64}}
        with self.assertRaises(opt_provider.ProviderStop):
            self.old_store.stage_runner(name, inputs,
                lambda: (_ for _ in ()).throw(opt_provider.ProviderStop('synthetic interruption')), deepcopy)
        runner = self.runner()
        calls = []
        def handle(request):
            calls.append(request)
            return httpx.Response(200, json={'model': opt_provider.CHAT_MODEL,
                'choices': [{'finish_reason': 'stop', 'message': {'content': 'new synthetic answer'}}]})
        with patch.object(opt_provider, 'ROOT', self.root):
            provider = r.ContinuationProvider(self.root / i.PROVIDER_RUN, runner.registration,
                allow_paid=True, keys=('synthetic-chat', 'synthetic-embedding'),
                transport=httpx.MockTransport(handle), sleep=lambda _: None)
            self.addCleanup(provider.close)
            traced = ImageGuard(TraceProvider(provider))
            runner.traced, runner.payloads = traced, {'a' * 64: payload_hash(image)}
            messages = [{'role': 'user', 'content': [{'type': 'image_url', 'image_url': {'url': image}}]}]
            before = self.inventory()
            result = runner(name, inputs, lambda: {'raw_outputs': [traced.chat(messages)], 'failure': None}, deepcopy)
            self.assertEqual(result['raw_outputs'], ['new synthetic answer'])
            self.assertEqual(len(calls), 1)
            self.assertEqual(before, self.inventory())
            # Cached new stage does not transmit again, and original unfinished
            # stage remains unfinished (all writes went to the new run).
            runner(name, inputs, lambda: self.fail('must use new seal'), deepcopy)
            self.assertEqual(len(calls), 1)

    def test_full84_import_then_readonly_complete_verify_without_provider(self):
        # Mock only the old context/image loader and the pure inference body.
        # Real ArtifactStore imports, seals, ledger checks and replay are used.
        (self.root / i.OLD_RUN / 'intent.json').unlink()
        ids = [f'q{n:02d}' for n in range(84)]
        rows = [{'sample_id': q, 'dataset': 'nutrition5k', 'group_id': f'g{n % 78:02d}', 'fold': n % 5}
                for n, q in enumerate(ids)]
        binding = {'phase': 'development_base',
                   'training_freeze_sha256': self.fixture.sha('round4/data/train/freeze.json'),
                   'gallery_completion_sha256': self.fixture.sha('round4/runs/J_gallery/completion.json')}
        self.old_store = ArtifactStore(self.root / i.OLD_RUN, binding, ids,
                                       verify_sources=lambda: True, root=self.root / 'round4')
        self.old_store.initialize()
        value = {'raw_outputs': ['synthetic same response'], 'failure': None}
        ref = self.fixture.cache(value['raw_outputs'][0])
        for q in ids:
            self.stage(name=q + ':estimate', inputs={'synthetic_query': q}, result=value, refs=[ref])
        reg = self.fixture.register()
        class Reader:
            hashes = {r.old.context.DEV_MANIFEST: reg.data['query_manifest_sha256']}
            def unchanged(self):
                return None
        ctx = {'binding': binding, 'reader': Reader(), 'rows': rows,
               'queries': [{'query_id': q} for q in ids], 'assets': {}, 'payloads': {},
               'verify_gallery': lambda: {'synthetic': 'verified'}}
        def infer(provider, query, assets, index, *, stage_runner):
            stage_runner(query['query_id'] + ':estimate', {'synthetic_query': query['query_id']},
                         lambda: self.fail('no paid/raw inference needed'), deepcopy)
            return {'prediction': {'weight': 1, 'energy': 1, 'fat': 0, 'carbs': 0, 'protein': 0},
                    'fallback': False, 'native_complete': True}
        execute = r.old._execute
        execute_calls = []
        def assert_initialized_before_workers(queries, worker, workers):
            # R-SC-2: fail deterministically before concurrency if base omitted
            # initialize(), instead of relying on a probabilistic lock race.
            intent = r.decode((self.root / i.NEW_RUN / 'intent.json').read_bytes())
            self.assertEqual(intent['binding'], {**binding, 'service_continuation': reg.service_binding()})
            self.assertEqual(intent['expected_records'], sorted(ids))
            execute_calls.append(workers)
            return execute(queries, worker, workers)
        with patch.object(r, 'ROOT', self.root), patch.object(r.old.context, 'load_context', return_value=ctx), \
             patch.object(r.old, '_base_store', return_value=(self.old_store, {})), \
             patch.object(r.old.pipeline, 'infer', infer), patch.object(r.old, 'event'), \
             patch.object(r.old, '_execute', assert_initialized_before_workers), \
             patch.object(r, 'ContinuationProvider', side_effect=AssertionError('must not construct provider')):
            got = r.base(workers=2)
            self.assertEqual(got['n'], 84)
            self.assertFalse(got['provider_constructed'])
            self.assertEqual(got['binding']['service_continuation'], reg.service_binding())
            before = self.inventory(self.root)
            verified = r.base(verify_only=True)
            self.assertEqual(verified['status'], 'base_verified')
            self.assertFalse(verified['provider_constructed'])
            self.assertFalse(verified['validation_opened'])
            self.assertEqual(verified['records'], got['records'])
            self.assertEqual(before, self.inventory(self.root))
            self.assertEqual(execute_calls, [2, 2])
            self.fixture.put(i.PROVIDER_RUN + '/requests.jsonl', b'{"unexpected":"postcompletion"}\n')
            with self.assertRaisesRegex(Exception, 'service_completion_provenance_changed'):
                r.base(verify_only=True)

    def test_workers_above_two_rejected_before_context_or_provider(self):
        with patch.object(r.old.context, 'load_context') as loader:
            for workers in (0, 3, 4, True):
                with self.assertRaisesRegex(Exception, 'workers_must_be_one_or_two'):
                    r.base(workers=workers)
            loader.assert_not_called()


if __name__ == '__main__':
    unittest.main()
