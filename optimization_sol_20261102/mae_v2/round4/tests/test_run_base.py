"""Production composition exercised using invented images and a fake provider."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

V2 = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(V2), str(V2 / 'src'), str(Path(__file__).resolve().parent)]
from round4.src import run_base as r
import test_context


class FakeProvider:
    namespace = r.NAMESPACE
    def __init__(self, root):
        self.cache = root / 'fake_cache'
        self.chats = self.embeddings = 0
        self.closed = False

    def chat(self, messages, max_completion_tokens=4096):
        self.chats += 1
        content = messages[1]['content']
        text = ' '.join(b.get('text', '') for b in content)
        if 'Training-only ingredient catalogue:' in text:
            return json.dumps({'items': [{'item_id': 'i1', 'description': 'synthetic visible food',
                'grams': 100, 'ingredient_id': 'ingr_0000000001', 'estimated_density': None}]})
        if 'following twelve images' in text:
            return json.dumps({'selected_ids': ['c1', 'c2', 'c3', 'c4']})
        return json.dumps({'scene': 'one serving', 'foods': [{'appearance': 'rough clustered pieces',
            'placement': 'centre'}], 'scale_cues': [], 'uncertainties': []})

    def embed(self, texts):
        self.embeddings += len(texts)
        return [[1.0] + [0.0] * 3071 for _ in texts]

    def close(self):
        self.closed = True


class DriverTests(unittest.TestCase):
    def setUp(self):
        self.fixture = test_context.ContextTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root = self.fixture.root
        self.providers = []
        def provider(directory, authorized):
            self.assertTrue(authorized)
            value = FakeProvider(self.root)
            self.providers.append(value)
            return value
        for target, value in ((r, 'ROOT'),):
            patcher = patch.object(target, value, self.root)
            patcher.start()
            self.addCleanup(patcher.stop)
        # fixture.load calls context.load_context, so retain the original to
        # avoid recursively reentering this production-loader injection.
        original = r.context.load_context
        patcher = patch.object(r.context, 'load_context', lambda _: original(
            self.root, verify_train=lambda base: self.fixture.proof,
            verify_capability=lambda base: self.fixture.capability))
        patcher.start()
        self.addCleanup(patcher.stop)
        patcher = patch.object(r, '_provider', provider)
        patcher.start()
        self.addCleanup(patcher.stop)
        patcher = patch.object(r, 'event', lambda **kwargs: None)
        patcher.start()
        self.addCleanup(patcher.stop)

    def files(self):
        return {str(p.relative_to(self.root)): (p.stat().st_mtime_ns, p.read_bytes())
                for p in (self.root / 'round4/runs').rglob('*') if p.is_file()}

    def test_full_gallery_base_then_completed_zero_provider_and_no_rewrites(self):
        self.assertEqual(r.gallery(allow_paid=True, workers=2)['n'], 12)
        self.assertEqual(sum(p.chats for p in self.providers), 12)
        self.assertEqual(sum(p.embeddings for p in self.providers), 12)
        result = r.base(allow_paid=True, workers=2)
        self.assertEqual(result['status'], 'base_complete_unscored')
        self.assertEqual(result['n'], 84)
        self.assertTrue(all(p.closed for p in self.providers))
        before = self.files()
        count = len(self.providers)
        self.assertEqual(r.gallery()['status'], 'gallery_verified')
        completed = r.base(verify_only=True)
        self.assertEqual(len(self.providers), count)
        self.assertEqual(before, self.files())
        self.assertEqual(len(completed['records']), 84)
        self.assertTrue(all(x['native_complete'] and not x['fallback'] for x in completed['records'].values()))
        self.assertTrue(all(x['prediction']['weight'] == 100 for x in completed['records'].values()))

    def test_no_paid_flag_no_provider_or_run_directory(self):
        with self.assertRaisesRegex(r.context.ContextError, 'explicit_paid_flag_required'):
            r.gallery()
        self.assertEqual(self.providers, [])
        self.assertFalse((self.root / 'round4/runs/J_gallery').exists())

    def test_verify_missing_base_no_provider(self):
        r.gallery(allow_paid=True, workers=1)
        count = len(self.providers)
        with self.assertRaises(Exception):
            r.base(verify_only=True)
        self.assertEqual(len(self.providers), count)

    def test_changed_source_completed_gallery_rejected_before_provider(self):
        r.gallery(allow_paid=True, workers=1)
        count = len(self.providers)
        self.fixture.put(r.context.SOURCE_NAMES[0], b'changed protocol')
        with self.assertRaises(Exception):
            r.gallery(allow_paid=True)
        self.assertEqual(len(self.providers), count)

    def test_request_reference_envelope_rejects_unknown_or_failed_fields(self):
        good = {'role': 'chat', 'request_hash': 'a' * 64, 'value_hash': 'b' * 64,
                'status': 'returned', 'cache_present_before': False}
        self.assertEqual(r._validate_refs([good]), [good])
        for changed in ({**good, 'status': 'raised'}, {**good, 'prompt': 'should never be persisted'},
                        {**good, 'cache_present_before': 'true'}):
            with self.assertRaises(r.context.ContextError):
                r._validate_refs([changed])

    def test_query_modified_after_context_verification_stops_before_chat(self):
        r.gallery(allow_paid=True, workers=1)
        original = r.context.load_context
        def changed(base):
            ctx = original(base)
            self.fixture.put(ctx['rows'][0]['image_path'], self.fixture.picture(201))
            return ctx
        with patch.object(r.context, 'load_context', changed), patch.object(r, '_execute',
                lambda rows, worker, workers: dict([worker(rows[0])])):
            with self.assertRaisesRegex(ValueError, 'sent_images_differ_from_frozen_stage'):
                r.base(allow_paid=True, workers=1)
        self.assertEqual(self.providers[-1].chats, 0)
        self.assertFalse((self.root / 'round4/runs/J/completion.json').exists())

    def test_failure_stops_queued_work_without_nutritional_fallback(self):
        calls = []
        def fail(row):
            calls.append(row)
            raise r.ProviderStop('synthetic service failure')
        with self.assertRaises(BaseException):
            r._execute(list(range(84)), fail, 1)
        self.assertEqual(calls, [0])

    def test_gallery_changed_during_base_blocks_final_seal(self):
        r.gallery(allow_paid=True, workers=1)
        def corrupt(rows, worker, workers):
            path = next((self.root / 'round4/runs/J_gallery/records').glob('*.json'))
            path.write_text('{}')
            return {row['query_id']: {} for row in rows}
        with patch.object(r, '_execute', corrupt):
            with self.assertRaisesRegex(Exception, 'completed_inventory_or_hash_changed'):
                r.base(allow_paid=True, workers=1)
        self.assertFalse((self.root / 'round4/runs/J/completion.json').exists())


if __name__ == '__main__':
    unittest.main()
