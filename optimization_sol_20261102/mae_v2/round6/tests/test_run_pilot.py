from copy import deepcopy
from io import BytesIO
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

import httpx
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / 'src')]
from opt_provider import ProviderStop
from round4.src.artifacts import ArtifactStore
from round6.src import run_pilot as run
from round6.src import runtime, train_context


def synthetic_context(root):
    """30 invented image groups, 25 pilot queries, 24 fold-local supports."""
    folder = root / 'images'
    folder.mkdir(mode=0o700)
    rows, ingredients, targets, vectors = [], {}, {}, {}
    for i in range(30):
        sid = 's%02d' % i
        out = BytesIO()
        Image.new('RGB', (15 + i, 20), (i * 7, 22, 77)).save(out, format='PNG')
        raw = out.getvalue()
        path = folder / (sid + '.png')
        path.write_bytes(raw)
        rows.append({'sample_id': sid, 'group_id': 'g%02d' % i, 'image_path': str(path),
                     'image_sha256': train_context.digest(raw), 'rgb_sha256': train_context.rgb_hash(raw)})
        ingredients[sid] = [{'ingredient_id': 'ingr_0000000001', 'name': 'Rice' if i % 2 else 'rice', 'grams': 100 + i,
                             'nutrients': {k: (j + 1) * (100 + i) / 10
                                           for j, k in enumerate(train_context.TARGETS[1:])}}]
        targets[sid] = {k: float(100 + i + j) for j, k in enumerate(train_context.TARGETS)}
        vectors[sid] = [1.0] + [0.0] * 3071
    ctx = train_context.build_views(rows, ingredients, targets, vectors, expected_n=30)
    ctx['binding'] = {'scope': 'synthetic_only', 'method_config': deepcopy(run.METHOD_CONFIG)}
    class Reader:
        def unchanged(self):
            return None
    ctx.update(reader=Reader(), verify_quick=lambda: None, verify_gallery=lambda: None)
    return ctx, (rows, ingredients, targets, vectors)


class CoordinatorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='synthetic-l-pilot-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        (self.root / 'round6').mkdir(mode=0o700)
        self.ctx, self.raw = synthetic_context(self.root)
        self.sent = []
        self.patch_root = patch.object(runtime.original, 'ROOT', self.root)
        self.patch_root.start()
        self.addCleanup(self.patch_root.stop)

    def answer(self, request):
        payload = json.loads(request.content)
        self.sent.append(payload)
        texts = '\n'.join(block.get('text', '') for msg in payload['messages']
            for block in (msg['content'] if isinstance(msg['content'], list) else []))
        if payload['max_completion_tokens'] == 8192:
            answer = {'items': [{'item_id': 'i1', 'description': 'invented visible rice', 'grams': 100,
                                 'ingredient_id': 'ingr_0000000001', 'estimated_density': None}]}
        elif '"selected_ids"' in texts:
            answer = {'selected_ids': ['c1', 'c2', 'c3', 'c4']}
        elif '"annotations"' in texts:
            answer = {'annotations': [{'ingredient_id': 'ingr_0000000001', 'status': 'separable',
                'boxes': [[.1, .1, .9, .9]], 'evidence': 'invented visible rice',
                'uncertainty': 'automatic fixture', 'shared_region_group': None}]}
        else:
            answer = {'items': [{'item_id': 'i1', 'description': 'invented visible rice', 'grams': 100,
                                 'ingredient_id': 'ingr_0000000001', 'estimated_density': None}]}
        return httpx.Response(200, json={'model': 'gpt-6.1-sol', 'choices': [
            {'message': {'content': json.dumps(answer)}, 'finish_reason': 'stop'}],
            'usage': {'prompt_tokens': 1, 'completion_tokens': 1, 'total_tokens': 2}})

    def provider(self, path, **kwargs):
        return runtime.PilotProvider(path, **kwargs,
            keys=('invented-chat-credential', 'invented-embedding-credential'),
            transport=httpx.MockTransport(self.answer), sleep=lambda _: None)

    def snapshot(self):
        return {str(p.relative_to(self.root)): (p.read_bytes(), p.stat().st_mtime_ns)
                for p in self.root.rglob('*') if p.is_file()}

    def test_full_25_pair_transport_seal_and_zero_provider_replay(self):
        with patch.object(run, 'PilotProvider', self.provider):
            result = run.base(root=self.root, context_loader=lambda root: self.ctx, allow_paid=True, workers=2)
        self.assertEqual(result['n'], 25)
        self.assertTrue(result['provider_constructed'])
        self.assertTrue(all(not row['baseline']['fallback'] and not row['candidate']['fallback']
                            for row in result['records'].values()))
        self.assertLessEqual(len(self.sent), 175)
        self.assertEqual(sum(p['max_completion_tokens'] == 4096 and '"selected_ids"' not in
                             '\n'.join(block.get('text', '') for msg in p['messages']
                                 for block in (msg['content'] if isinstance(msg['content'], list) else []))
                             for p in self.sent),
                         len({sid for record in result['records'].values() for sid in record['selected_train_ids']}))
        self.assertTrue(all(p['model'] == 'gpt-6.1-sol' for p in self.sent))
        for record in result['records'].values():
            self.assertEqual(len(record['crop_provenance']), 4)
            for crop in record['crop_provenance']:
                self.assertIn('crop_bytes_sha256', crop['proof'])
                self.assertIn('pixel_bounds', crop['proof'])
                self.assertIn('source_image_sha256', crop['proof'])
        before = self.snapshot()
        with patch.object(run, 'PilotProvider', side_effect=AssertionError('Provider constructed')):
            replay = run.base(root=self.root, context_loader=lambda root: self.ctx, verify_only=True, workers=2)
        self.assertFalse(replay['provider_constructed'])
        self.assertEqual(replay['records'], result['records'])
        self.assertEqual(self.snapshot(), before)
        for payload in self.sent:
            text = json.dumps(payload['messages'])
            for forbidden in ('\\"sample_id\\"', '\\"query_id\\"', '\\"fold\\"', '\\"image_path\\"'):
                self.assertNotIn(forbidden, text)
        counter = next((self.root / 'runtime_cache/attempts/chat').glob('*.json'))
        value = json.loads(counter.read_text())
        value['attempts'] = 4
        counter.write_text(json.dumps(value))
        with patch.object(run, 'PilotProvider', side_effect=AssertionError('Provider constructed')) as factory:
            with self.assertRaises(Exception):
                run.base(root=self.root, context_loader=lambda root: self.fail('context read after bad audit'), verify_only=True)
            factory.assert_not_called()

    def test_not_paid_and_missing_completion_verify_do_not_construct_provider(self):
        with patch.object(run, 'PilotProvider', side_effect=AssertionError('Provider constructed')) as factory:
            with self.assertRaises(Exception):
                run.base(root=self.root, context_loader=lambda root: self.ctx, allow_paid=False)
            with self.assertRaises(Exception):
                run.base(root=self.root, context_loader=lambda root: self.ctx, verify_only=True)
            factory.assert_not_called()

    def test_worker_limit_and_changed_image_fail_before_provider(self):
        with patch.object(run, 'PilotProvider', side_effect=AssertionError('Provider constructed')) as factory:
            for workers in (0, 3, True):
                with self.assertRaises(ValueError):
                    run.base(root=self.root, context_loader=lambda root: self.ctx, workers=workers)
            query = self.ctx['queries'][0]
            Path(query['image_path']).write_bytes(b'changed')
            with self.assertRaises(ValueError):
                run._snapshot(query)
            factory.assert_not_called()

    def test_service_fault_preserves_no_whole_prediction_and_resume_stage(self):
        calls = []
        real_answer = self.answer
        def fail_second(request):
            calls.append(1)
            if len(calls) == 2:
                raise KeyboardInterrupt()
            return real_answer(request)
        def interrupted_provider(path, **kwargs):
            return runtime.PilotProvider(path, **kwargs,
                keys=('invented-chat-credential', 'invented-embedding-credential'),
                transport=httpx.MockTransport(fail_second), sleep=lambda _: None)
        with patch.object(run, 'PilotProvider', interrupted_provider):
            with self.assertRaises(KeyboardInterrupt):
                run.base(root=self.root, context_loader=lambda root: self.ctx, allow_paid=True, workers=1)
        self.assertFalse((self.root / run.OUTPUT / 'completion.json').exists())
        saved_reranks = [p for p in self.sent if 'selected_ids' in json.dumps(p['messages'])]
        self.assertEqual(len(saved_reranks), 1)
        with patch.object(run, 'PilotProvider', self.provider):
            finished = run.base(root=self.root, context_loader=lambda root: self.ctx, allow_paid=True, workers=1)
        self.assertEqual(finished['n'], 25)
        first_payload = saved_reranks[0]
        self.assertEqual(sum(p == first_payload for p in self.sent), 1)

    def test_heldout_supervision_poison_leaves_fold_request_bytes_identical(self):
        query = next(q for q in self.ctx['queries'] if self.ctx['group_folds'][q['screening_group_id']] == 0)
        rows, ingredients, targets, vectors = deepcopy(self.raw)
        for row in rows:
            if self.ctx['group_folds'][row['group_id']] == 0:
                ingredients[row['sample_id']][0].update(grams=9000, name='poisoned query-fold name',
                    ingredient_id='ingr_%010d' % (1000 + int(row['sample_id'][1:])))
                ingredients[row['sample_id']][0]['nutrients'] = {k: 8000 for k in train_context.TARGETS[1:]}
                targets[row['sample_id']] = {k: 7000 for k in train_context.TARGETS}
        poisoned = train_context.build_views(rows, ingredients, targets, vectors, expected_n=30)
        provider = self.provider(self.root / 'round6/provider/L', allow_paid=True)
        self.addCleanup(provider.close)
        trace = runtime.BoundTrace(provider)
        locks = {sid: threading.Lock() for assets in self.ctx['fold_assets'].values() for sid in assets['supports']}
        records = []
        for i, ctx in enumerate((self.ctx, poisoned)):
            store = ArtifactStore(self.root / 'round6' / ('comparison%d' % i), {'synthetic': i}, ['pair'],
                                  verify_sources=lambda: None, root=self.root / 'round6')
            store.initialize()
            records.append(run.infer_one(ctx, query, store, trace, locks, base=self.root))
            if i == 0:
                before_count = len(self.sent)
        self.assertEqual(len(self.sent), before_count)  # all second-view exact payloads hit real caches
        self.assertEqual(records[0]['baseline'], records[1]['baseline'])
        self.assertEqual(records[0]['candidate'], records[1]['candidate'])


if __name__ == '__main__':
    unittest.main()
