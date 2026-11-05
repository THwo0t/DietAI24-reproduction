"""Offline route, provenance, privacy and restart tests; no credentials are read."""
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import httpx

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
# Load the experiment's config explicitly even in a larger test discovery session.
spec = importlib.util.spec_from_file_location('config', HERE / 'config.py')
config = importlib.util.module_from_spec(spec)
spec.loader.exec_module(config)
sys.modules['config'] = config
spec = importlib.util.spec_from_file_location('gemini_experiment_provider', HERE / 'provider.py')
provider = importlib.util.module_from_spec(spec)
spec.loader.exec_module(provider)

KEYS = ('dummy-sol-secret-10001', 'dummy-embed-secret-20002', 'dummy-vision-secret-30003')
TEXT = [{'role': 'user', 'content': 'Describe the meal.'}]
IMAGE = [{'role': 'user', 'content': [
    {'type': 'text', 'text': 'Describe the meal.'},
    {'type': 'image_url', 'image_url': {'url': 'data:image/png;base64,AA=='}}]}]


class ProviderTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / 'isolated'
        self.root.mkdir()
        self.patches = [patch.object(provider, 'ROOT', self.root),
                        patch.object(provider, 'HERE', self.root),
                        patch.object(provider, 'read_credentials', side_effect=AssertionError('Credential read forbidden'))]
        for p in self.patches:
            p.start()
        self.clients = []
        self.sent = []

    def tearDown(self):
        for client in self.clients:
            client.close()
        for p in reversed(self.patches):
            p.stop()
        self.tmp.cleanup()

    def client(self, handler=None):
        def success(req):
            body = json.loads(req.content)
            if req.url.path.endswith('/embeddings'):
                return httpx.Response(200, json={'model': body['model'], 'data': [{'embedding': [1.0] * 3072}]})
            return httpx.Response(200, json={'model': body['model'], 'choices': [
                {'message': {'content': 'ok'}, 'finish_reason': 'stop'}]})
        def record(req):
            self.sent.append(req)
            return (handler or success)(req)
        result = provider.Provider(self.root / 'run', allow_paid=True, keys=KEYS,
                                   transport=httpx.MockTransport(record), sleep=lambda _: None)
        self.clients.append(result)
        return result

    def test_image_text_repair_and_embedding_route_credentials(self):
        p = self.client()
        self.assertEqual(p.chat(IMAGE), 'ok')
        self.assertEqual(p.chat(TEXT), 'ok')
        repair = IMAGE + [{'role': 'assistant', 'content': 'bad JSON'},
                          {'role': 'user', 'content': 'Repair the JSON.'}]
        self.assertEqual(p.chat(repair), 'ok')
        self.assertEqual(len(p.embed(['rice'])[0]), 3072)
        expected = [(provider.VISION_MODEL, 2), (provider.CHAT_MODEL, 0),
                    (provider.VISION_MODEL, 2), (provider.EMBED_MODEL, 1)]
        for request, (model, key_index) in zip(self.sent, expected):
            self.assertEqual(json.loads(request.content)['model'], model)
            self.assertEqual(request.headers['Authorization'], 'Bearer ' + KEYS[key_index])
        self.assertEqual(len(self.sent), 4)
        self.assertEqual(str(self.sent[-1].url), provider.EMBED_URL)

    def test_wrong_served_model_stops_without_caching(self):
        p = self.client(lambda _: httpx.Response(200, json={
            'model': 'wrong-model', 'choices': [{'message': {'content': 'must never be accepted'}, 'finish_reason': 'stop'}]}))
        with self.assertRaises(provider.ProviderStop):
            p.chat(IMAGE)
        self.assertEqual(len(self.sent), 1)
        self.assertEqual(list((self.root / 'runtime_cache/responses').rglob('*.json')), [])

    def test_cache_keeps_models_separate_and_reuses_across_instances(self):
        p = self.client()
        p.chat(TEXT)
        with patch.object(provider, 'CHAT_MODEL', provider.VISION_MODEL):
            p.chat(TEXT)
        self.assertEqual(len(self.sent), 2)
        saved = [json.loads(f.read_text()) for f in (self.root / 'runtime_cache/responses/chat').glob('*.json')]
        self.assertEqual({r['model'] for r in saved}, {config.MODELS['llm'], config.MODELS['llm_vision']})
        p2 = self.client(lambda _: self.fail('A cached response must not send HTTP'))
        self.assertEqual(p2.chat(TEXT), 'ok')
        self.assertEqual(len(self.sent), 2)

    def test_response_credentials_redacted_in_logs_and_cache(self):
        leaked = ' '.join(KEYS)
        p = self.client(lambda req: httpx.Response(200, json={
            'model': json.loads(req.content)['model'],
            'usage': {'unexpected_metadata': leaked},
            'choices': [{'message': {'content': leaked}, 'finish_reason': 'stop'}]}))
        value = p.chat(IMAGE)
        for key in KEYS:
            self.assertNotIn(key, value)
        for path in self.root.rglob('*'):
            if path.is_file():
                for key in KEYS:
                    self.assertNotIn(key, path.read_text(), str(path))
        self.assertIn('[REDACTED]', value)

    def test_http_error_credentials_do_not_enter_log(self):
        p = self.client(lambda _: httpx.Response(401, json={'error': {'type': ' '.join(KEYS), 'message': ' '.join(KEYS)}}))
        with self.assertRaises(provider.ProviderStop):
            p.chat(TEXT)
        saved = (self.root / 'run/requests.jsonl').read_text()
        for key in KEYS:
            self.assertNotIn(key, saved)

    def test_three_attempts_survive_restarts(self):
        def fail(_):
            return httpx.Response(401, json={'error': {'type': 'denied'}})
        # A terminal HTTP error stops each process after one transmission.
        for _ in range(3):
            with self.assertRaises(provider.ProviderStop):
                self.client(fail).chat(TEXT)
        self.assertEqual(len(self.sent), 3)
        with self.assertRaisesRegex(provider.ProviderStop, 'exhausted'):
            self.client(fail).chat(TEXT)
        self.assertEqual(len(self.sent), 3)
        ledgers = list((self.root / 'runtime_cache/attempts/chat').glob('*.json'))
        self.assertEqual(len(ledgers), 1)
        self.assertEqual(json.loads(ledgers[0].read_text())['attempts'], 3)

    def test_retryable_error_also_stops_at_three_after_restart(self):
        p = self.client(lambda _: httpx.Response(503, json={'error': {'type': 'unavailable'}}))
        with self.assertRaises(provider.ProviderStop):
            p.chat(TEXT)
        with self.assertRaises(provider.ProviderStop):
            self.client().chat(TEXT)
        self.assertEqual(len(self.sent), 3)

    def test_gemini_format_wrapper_only_extracts_one_complete_object(self):
        cases = [
            ('Explanation\n```json\n{"grams":"001.20","item":"rice"}\n```',
             '{"grams":"001.20","item":"rice"}'),
            ('Explanation: {"grams":12}', '{"grams":12}'),
            ('{"grams":12} then {"grams":13}', '{"grams":12} then {"grams":13}'),
            ('Explanation: {"grams":12', 'Explanation: {"grams":12'),
            ('[{"grams":12}]', '[{"grams":12}]'),
            ('Explanation: [{"grams":12}', 'Explanation: [{"grams":12}'),
            ('[{"grams":12},{"grams":13}]', '[{"grams":12},{"grams":13}]'),
        ]
        for position, (raw, expected) in enumerate(cases):
            with self.subTest(case=position):
                self.assertEqual(provider.extract_unique_json(raw), expected)
                def response(request):
                    return httpx.Response(200, json={
                        'model': json.loads(request.content)['model'],
                        'choices': [{'message': {'content': raw}, 'finish_reason': 'stop'}]})
                p = self.client(response)
                # Distinct namespaces avoid accidental cache reuse between cases.
                p.namespace = 'format-case-' + str(position)
                self.assertEqual(p.chat(IMAGE), expected)
                self.assertEqual(p.chat(TEXT), raw)

    def test_remote_image_rejected_before_any_http(self):
        p = self.client()
        with self.assertRaises(provider.ProviderStop):
            p.chat([{'role': 'user', 'content': [{'type': 'image_url', 'image_url': {'url': 'https://example.invalid/a.png'}}]}])
        self.assertEqual(self.sent, [])


if __name__ == '__main__':
    unittest.main(verbosity=2)
