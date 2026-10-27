"""A3: one model for all steps, and every response logs the model that served it (offline)."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import httpx
import openai

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'code'))

import api_log  # noqa: E402
import chagApp_openai  # noqa: E402
import config  # noqa: E402
import rag_food_code  # noqa: E402

KEY = 'test-key-0123456789abcdefghijklmnopqrstuvwxyz'  # not sk-..., so the A2 key scan stays clean
SERVED = 'gpt-4o-2024-08-06-served-by-mock'


def fake_openai(request):
    """Answer like the OpenAI API, naming a served model that differs from the request."""
    if request.url.path.endswith('/embeddings'):
        return httpx.Response(200, headers={'x-request-id': 'req_emb'}, json={
            'object': 'list', 'model': SERVED,
            'data': [{'object': 'embedding', 'index': 0, 'embedding': [0.1, 0.2]}],
            'usage': {'prompt_tokens': 1, 'total_tokens': 1}})
    return httpx.Response(200, headers={'x-request-id': 'req_chat'}, json={
        'id': 'chatcmpl-1', 'object': 'chat.completion', 'created': 0, 'model': SERVED,
        'choices': [{'index': 0, 'finish_reason': 'stop',
                     'message': {'role': 'assistant', 'content': 'an apple'}}],
        'usage': {'prompt_tokens': 10, 'completion_tokens': 2, 'total_tokens': 12}})


class TestApiLog(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        env_path = os.path.join(self.tmp.name, '.env')
        with open(env_path, 'w') as f:
            f.write(f'OPENAI_API_KEY={KEY}\n')
        self.log_path = os.path.join(self.tmp.name, 'logs', 'openai_api.jsonl')
        for patch in [mock.patch.object(config, 'ENV_PATH', env_path),
                      mock.patch.object(config, 'API_LOG_PATH', self.log_path)]:
            patch.start()
            self.addCleanup(patch.stop)

    def tearDown(self):
        self.tmp.cleanup()

    def mock_client(self, handler=fake_openai):
        return lambda: api_log.openai_client(transport=httpx.MockTransport(handler))

    def records(self):
        with open(self.log_path) as f:
            return [json.loads(line) for line in f]

    def test_one_model_for_vision_and_text(self):
        self.assertEqual(config.MODELS, {'llm': 'gpt-4o-2024-08-06',
                                         'llm_vision': 'gpt-4o-2024-08-06',
                                         'embedding': 'text-embedding-3-large'})

    def test_every_client_logs_requested_and_served_model(self):
        with mock.patch.object(chagApp_openai, 'openai_client', self.mock_client()), \
                mock.patch.object(rag_food_code, 'openai_client', self.mock_client()):
            vision = chagApp_openai.Vision(config.MODELS['llm_vision'])
            vision.chat('Which food is this?', 'data:image/png;base64,iVBORw0KGgo=')
            llm, llm_vision, embedding = rag_food_code.initialize_clients(config.MODELS)
            llm.invoke('Which food code?')
            llm_vision.invoke('Which food?')
            embedding.client.create(input=['apple'], model=embedding.model)
        records = self.records()
        self.assertEqual([r['endpoint'] for r in records],
                         ['/v1/chat/completions'] * 3 + ['/v1/embeddings'])
        self.assertEqual([r['model_requested'] for r in records],
                         ['gpt-4o-2024-08-06'] * 3 + ['text-embedding-3-large'])
        for r in records:
            self.assertEqual(r['model_served'], SERVED)
            self.assertEqual(r['status'], 200)
            self.assertIsNotNone(r['usage'])
            self.assertIsNotNone(r['request_id'])

    def test_log_has_no_key_and_no_message_content(self):
        def reject(request):
            return httpx.Response(401, json={'error': {
                'code': 'invalid_api_key', 'type': 'invalid_request_error',
                'message': f'Incorrect API key provided: {KEY[:8]}****{KEY[-4:]}.'}})
        with mock.patch.object(chagApp_openai, 'openai_client', self.mock_client()):
            chagApp_openai.Vision(config.MODELS['llm_vision']).chat(
                'Which food is this?', 'data:image/png;base64,iVBORw0KGgo=')
        with mock.patch.object(chagApp_openai, 'openai_client', self.mock_client(reject)):
            with self.assertRaises(openai.AuthenticationError):
                chagApp_openai.Vision(config.MODELS['llm_vision']).chat(
                    'Which food is this?', 'data:image/png;base64,iVBORw0KGgo=')
        text = Path(self.log_path).read_text()
        for secret in [KEY, KEY[:8], KEY[-4:], 'Bearer', 'Which food', 'iVBORw0KGgo', 'an apple']:
            self.assertNotIn(secret, text)
        self.assertEqual(self.records()[-1]['status'], 401)
        self.assertEqual(self.records()[-1]['error_code'], 'invalid_api_key')


if __name__ == '__main__':
    unittest.main()
