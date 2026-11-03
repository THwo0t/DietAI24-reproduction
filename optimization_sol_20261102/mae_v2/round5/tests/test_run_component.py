import io
from contextlib import redirect_stdout
from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from PIL import Image
import httpx

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / 'src')]
from opt_provider import ProviderStop
from round4.src.artifacts import ArtifactStore
from round5.src import run_component as run
from round5.src.component_runtime import BoundTrace, NAMESPACE
from round5.src import component_runtime as runtime
from opt_provider import fingerprint as response_fingerprint

URL = 'data:image/png;base64,QUFB'


class FakeProvider:
    namespace = NAMESPACE

    def __init__(self, cache):
        self.cache, self.calls = cache, 0

    def chat(self, messages, max_completion_tokens=4096):
        self.calls += 1
        return '{"fixture":true}'


class SequenceProvider(FakeProvider):
    def __init__(self, cache, outputs):
        super().__init__(cache)
        self.outputs = list(outputs)

    def chat(self, messages, max_completion_tokens=4096):
        self.calls += 1
        if not self.outputs:
            raise AssertionError('unexpected new inference')
        value = self.outputs.pop(0)
        if isinstance(value, BaseException):
            raise value
        return value


class RunTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'round5').mkdir(mode=0o700)
        self.provider = FakeProvider(self.root / 'cache')
        self.traced = BoundTrace(self.provider)
        # These small tests isolate orchestration/format behavior. The separate
        # actual-transport integration below reenables all evidence checks.
        self.ref_patch = patch.object(run, 'verify_refs', return_value=None)
        self.proof_patch = patch.object(run, 'completion_proof', return_value={'synthetic': True})
        self.ref_patch.start()
        self.proof_patch.start()
        self.addCleanup(self.ref_patch.stop)
        self.addCleanup(self.proof_patch.stop)

    def stage_store(self):
        return ArtifactStore(self.root / 'runs/K', {'scope': 'invented'}, ['s'],
                             verify_sources=lambda: None, root=self.root)

    def test_saved_stage_is_reused_without_call_and_receipt_matches_value(self):
        store = self.stage_store()
        payload = [{'role': 'user', 'content': [{'type': 'image_url', 'image_url': {'url': URL}}]}]
        def call():
            return {'raw_outputs': [self.traced.chat(payload)], 'repair_used': False}
        result = run._stage(store, self.traced, 's:hypotheses', {'image': 'fixture'}, [URL], call, deepcopy)
        self.assertEqual(self.provider.calls, 1)
        again = run._stage(store, self.traced, 's:hypotheses', {'image': 'fixture'}, [URL],
                           lambda: self.fail('cached stage invoked provider'), deepcopy)
        self.assertEqual(result, again)
        self.assertEqual(self.provider.calls, 1)

    def test_wrong_value_receipt_is_rejected(self):
        store = self.stage_store()
        def call():
            self.traced.chat([{'role': 'user', 'content': [
                {'type': 'image_url', 'image_url': {'url': URL}}]}])
            return {'raw_outputs': ['different returned content']}
        with self.assertRaisesRegex(ValueError, 'component_request_value_binding_changed'):
            run._stage(store, self.traced, 's:mass', {}, [URL], call, deepcopy)
        self.assertFalse((self.root / 'runs/K/completion.json').exists())

    def test_service_exception_propagates_without_record_fallback(self):
        store = self.stage_store()
        def call():
            raise ProviderStop('fixture service failure')
        with self.assertRaises(ProviderStop):
            run._stage(store, self.traced, 's:hypotheses', {}, [URL], call, deepcopy)
        self.assertFalse((self.root / 'runs/K/completion.json').exists())

    def test_lazy_does_not_create_provider_without_real_call(self):
        with patch.object(run, 'ComponentProvider', side_effect=AssertionError('constructed')):
            lazy = run.LazyProvider(False)
            self.assertIsNone(lazy.instance)
            lazy.close()
            with self.assertRaisesRegex(ValueError, 'registered_paid_execution_required'):
                lazy.chat([])
        self.assertIsNone(lazy.instance)

    def test_completed_base_replay_has_no_provider_and_no_file_mutation(self):
        row = {'sample_id': 'invented', 'dataset': 'nutrition5k', 'group_id': 'group', 'fold': 0}
        query = {'query_id': 'invented'}
        ctx = {'binding': {'phase': 'synthetic'}, 'rows': [row], 'queries': [query],
               'verify_quick': lambda: None, 'verify_gallery': lambda: None}
        class Reader:
            def unchanged(self):
                pass
        ctx['reader'] = Reader()
        answer = {'prediction': {'weight': 1, 'energy': 2, 'fat': 0, 'carbs': 0, 'protein': 0},
                  'stages': {'hypotheses': {'raw_outputs': ['fixture']}},
                  'request_refs': {'hypotheses': [{'role': 'chat', 'request_hash': 'a' * 64,
                    'value_hash': response_fingerprint('fixture'), 'status': 'returned', 'cache_present_before': False}]}}
        with patch.object(run, 'ROOT', self.root), patch.object(run, 'load_inputs', return_value=ctx), \
             patch.object(run, 'infer_one', return_value=answer), \
             patch.object(run, 'ComponentProvider', side_effect=AssertionError('provider constructed')), \
             redirect_stdout(io.StringIO()):
            first = run.base(allow_paid=True)
            self.assertEqual(first['status'], 'base_complete_unscored')
            before = {str(p.relative_to(self.root)): (p.read_bytes(), p.stat().st_mtime_ns)
                      for p in self.root.rglob('*') if p.is_file()}
            second = run.base(verify_only=True)
        after = {str(p.relative_to(self.root)): (p.read_bytes(), p.stat().st_mtime_ns)
                 for p in self.root.rglob('*') if p.is_file()}
        self.assertEqual(before, after)
        self.assertEqual(second['records'], first['records'])
        self.assertFalse(second['provider_constructed'])

    def test_new_base_requires_paid_flag_and_one_or_two_workers(self):
        for invalid in (0, 3, True):
            with self.assertRaisesRegex(ValueError, 'component_workers_must_be_one_or_two'):
                run.base(workers=invalid)
        ctx = {'binding': {}, 'rows': [{'sample_id': 's'}], 'verify_quick': lambda: None}
        with patch.object(run, 'ROOT', self.root), patch.object(run, 'load_inputs', return_value=ctx):
            with self.assertRaisesRegex(ValueError, 'registered_paid_execution_required'):
                run.base()
        self.assertFalse((self.root / run.OUTPUT).exists())

    def fixture_context(self):
        a, b = 'ingr_0000000001', 'ingr_0000000002'
        catalog = [{'ingredient_id': code, 'name': name, 'density_per_100g': density}
                   for code, name, density in [
                       (a, 'synthetic grain', {'energy': 120, 'fat': 1, 'carbs': 25, 'protein': 3}),
                       (b, 'synthetic protein', {'energy': 200, 'fat': 10, 'carbs': 0, 'protein': 25})]]
        query_path = self.root / 'query_private_filename.png'
        Image.new('RGB', (90, 60), (80, 120, 60)).save(query_path)
        query = {'query_id': 's', 'image_path': str(query_path), 'screening_group_id': 'query-group',
                 'image_sha256': 'e' * 64, 'rgb_sha256': 'f' * 64}
        entries, supports, vectors = [], {}, {}
        for index in range(12):
            sid = 'train' + str(index).zfill(2)
            path = self.root / (sid + '.png')
            Image.new('RGB', (30, 20), (index, 20, 50)).save(path)
            entries.append({'train_id': sid, 'screening_group_id': 'group' + str(index),
                            'image_sha256': format(index + 1, '064x'), 'rgb_sha256': format(index + 101, '064x')})
            supports[sid] = {'image_path': str(path), 'ingredients': [
                {'ingredient_id': a if index < 6 else b, 'grams': 100}]}
            vectors[sid] = [1.] + [0.] * 3071
        retrieval = [{**row, 'rank': i + 1, 'cosine': 1.} for i, row in enumerate(entries)]
        fallback = {'weight': 90, 'energy': 100, 'fat': 2, 'carbs': 10, 'protein': 5}
        prefix = {'provenance': {'stage_sha256': {}}, 'method_fallback': False,
                  'method_fallback_reason': None, 'repair_used': False,
                  'selected_train_ids': [row['train_id'] for row in entries[:4]],
                  'stages': {'embedding': {'vector': [1.] + [0.] * 3071}, 'retrieval': retrieval}}
        ctx = {'prefixes': {'s': prefix}, 'entries': entries, 'vectors': vectors,
               'assets': {'catalog': catalog, 'supports': supports, 'fallback': fallback,
                          'training_sha256': 'a' * 64}}
        group = {'group_id': 'g1', 'description': 'visible food', 'bbox': [.1, .1, .9, .9],
                 'preparation': 'single', 'hypotheses': [a, b], 'evidence': 'visible texture',
                 'uncertainty': 'identity uncertain'}
        hypotheses = json.dumps({'groups': [group]})
        mass = json.dumps({'total_grams': 100, 'parents': [{'group_id': 'g1', 'grams': 100,
            'leaves': [{'item_id': 'i1', 'description': 'visible grain', 'grams': 100,
                        'ingredient_id': a, 'estimated_density': None}]}], 'uncertainty': 'none'})
        return ctx, query, hypotheses, mass

    def test_actual_two_stage_contract_selection_images_and_completed_replay(self):
        ctx, query, hypotheses, mass = self.fixture_context()
        provider = SequenceProvider(self.root / 'cache', [hypotheses, mass])
        store = self.stage_store()
        result = run.infer_one(ctx, query, store, BoundTrace(provider))
        self.assertEqual(provider.calls, 2)
        self.assertEqual(result['prediction'], {'weight': 100., 'energy': 120., 'fat': 1., 'carbs': 25., 'protein': 3.})
        self.assertTrue(result['native_complete'])
        self.assertEqual(len(result['audit']['selected_train_ids']), 8)
        store.finalize({'s': result})
        before = {str(p): (p.read_bytes(), p.stat().st_mtime_ns) for p in store.directory.rglob('*') if p.is_file()}
        no_calls = SequenceProvider(self.root / 'cache', [])
        repeated = run.infer_one(ctx, query, store, BoundTrace(no_calls))
        after = {str(p): (p.read_bytes(), p.stat().st_mtime_ns) for p in store.directory.rglob('*') if p.is_file()}
        self.assertEqual(repeated, result)
        self.assertEqual(before, after)
        self.assertEqual(no_calls.calls, 0)

    def test_structural_failure_keeps_whole_training_fallback(self):
        ctx, query, _, _ = self.fixture_context()
        provider = SequenceProvider(self.root / 'cache', ['bad json', 'bad json'])
        result = run.infer_one(ctx, query, self.stage_store(), BoundTrace(provider))
        self.assertTrue(result['fallback'])
        self.assertTrue(result['repair_used'])
        self.assertFalse(result['native_complete'])
        self.assertEqual(result['prediction'], ctx['assets']['fallback'])
        self.assertEqual(set(result['stages']), {'hypotheses'})
        self.assertEqual(result['raw_leaves'], [])

    def test_actual_service_proof_rejects_tampering_before_scoring_labels(self):
        self.ref_patch.stop()
        self.proof_patch.stop()
        ctx, query, hypotheses, mass = self.fixture_context()
        row = {'sample_id': 's', 'dataset': 'nutrition5k', 'group_id': 'query-group', 'fold': 0}
        class Reader:
            def unchanged(self):
                pass
        ctx.update(binding={'phase': 'invented-component-integration'}, rows=[row], queries=[query],
                   reader=Reader(), verify_quick=lambda: None, verify_gallery=lambda: None)
        outputs, transmissions = [hypotheses, mass], []
        def transport(request):
            transmissions.append(1)
            if not outputs:
                raise AssertionError('unexpected new HTTP transmission')
            return httpx.Response(200, json={'model': 'gpt-6.1-sol', 'choices': [
                {'message': {'content': outputs.pop(0)}, 'finish_reason': 'stop'}], 'usage': {}})
        real_provider = runtime.ComponentProvider
        def factory(directory, allow_paid=False):
            return real_provider(directory, allow_paid=allow_paid,
                                 keys=('invented-chat-credential', 'invented-embedding-credential'),
                                 transport=httpx.MockTransport(transport), sleep=lambda _: None)
        from round5.src import score_component as scoring
        with patch.object(run, 'ROOT', self.root), patch.object(runtime.original, 'ROOT', self.root), \
             patch.object(run.LazyProvider, 'cache', self.root / 'runtime_cache/responses'), \
             patch.object(run, 'load_inputs', return_value=ctx), \
             patch.object(run, 'ComponentProvider', side_effect=factory), redirect_stdout(io.StringIO()):
            first = run.base(allow_paid=True, workers=1)
            self.assertEqual(len(transmissions), 2)
            all_paths = lambda: {str(p.relative_to(self.root)): (p.read_bytes(), p.stat().st_mtime_ns)
                                 for p in self.root.rglob('*') if p.is_file()}
            before = all_paths()
            with patch.object(run, 'ComponentProvider', side_effect=AssertionError('Provider on completed replay')):
                replay = run.base(verify_only=True, workers=1)
            self.assertEqual(replay['records'], first['records'])
            self.assertFalse(replay['provider_constructed'])
            self.assertEqual(before, all_paths())
            caches = sorted((self.root / 'runtime_cache/responses/chat').glob('*.json'))
            counter = self.root / 'runtime_cache/attempts/chat' / caches[0].name
            log = self.root / 'round5/provider/K/requests.jsonl'
            def changed(path, edit):
                original = path.read_bytes()
                try:
                    edit(path)
                    with self.assertRaises(Exception):
                        run.base(verify_only=True, workers=1)
                    with patch.object(scoring, 'verified_base', side_effect=lambda: run.base(verify_only=True, workers=1)), \
                         patch.object(scoring, 'Inputs', side_effect=AssertionError('labels/readers reached')) as inputs:
                        with self.assertRaises(Exception) as caught:
                            scoring.score()
                        self.assertNotIsInstance(caught.exception, AssertionError)
                        inputs.assert_not_called()
                finally:
                    path.write_bytes(original)
            def mutate_json(path, key, value):
                data = json.loads(path.read_text())
                data[key] = value
                path.write_text(json.dumps(data))
            for target, key, value in ((caches[0], 'model', 'wrong-model'),
                                       (caches[0], 'value', 'changed content'),
                                       (caches[0], 'request_hash', '0' * 64),
                                       (counter, 'attempts', 4),
                                       (counter, 'namespace', 'other-namespace')):
                changed(target, lambda path, key=key, value=value: mutate_json(path, key, value))
            for target in (caches[0], counter, log):
                changed(target, lambda path: path.unlink())
            changed(log, lambda path: path.write_bytes(path.read_bytes() + b'\n'))
            self.assertEqual(len(transmissions), 2)

    def test_service_ref_coverage_cannot_omit_a_stage(self):
        for record in ({'stages': {'hypotheses': {'raw_outputs': ['fixture']}}, 'request_refs': {}},
                       {'stages': {}, 'request_refs': {}}):
            with self.assertRaisesRegex(ValueError, 'component_service_stage_coverage_changed'):
                run.collect_service_refs({'s': record})


if __name__ == '__main__':
    unittest.main()
