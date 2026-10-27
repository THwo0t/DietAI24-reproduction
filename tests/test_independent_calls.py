"""A5: each image is sent in its own request, without earlier images or answers (offline)."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'code'))

import api_log  # noqa: E402
import chagApp_openai  # noqa: E402
import config  # noqa: E402
import rag_food_code  # noqa: E402

IMAGE_1 = 'data:image/png;base64,FIRSTIMAGE='
IMAGE_2 = 'data:image/png;base64,SECONDIMAGE='


class TestIndependentCalls(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        env_path = os.path.join(self.tmp.name, '.env')
        with open(env_path, 'w') as f:
            f.write('OPENAI_API_KEY=sk-test\n')
        for patch in [mock.patch.object(config, 'ENV_PATH', env_path),
                      mock.patch.object(config, 'API_LOG_PATH', os.path.join(self.tmp.name, 'log.jsonl'))]:
            patch.start()
            self.addCleanup(patch.stop)
        self.sent = []

    def tearDown(self):
        self.tmp.cleanup()

    def fake_openai(self, request):
        self.sent.append(json.loads(request.content)['messages'])
        return httpx.Response(200, json={
            'id': 'chatcmpl-1', 'object': 'chat.completion', 'created': 0, 'model': 'gpt-4o-2024-08-06',
            'choices': [{'index': 0, 'finish_reason': 'stop',
                         'message': {'role': 'assistant', 'content': f'answer {len(self.sent)}'}}],
            'usage': {'prompt_tokens': 10, 'completion_tokens': 2, 'total_tokens': 12}})

    def client(self):
        return api_log.openai_client(transport=httpx.MockTransport(self.fake_openai))

    def test_vision_chat_sends_only_system_and_current_image(self):
        # rag_portion_size.py asks one Vision instance about every image, in two passes
        with mock.patch.object(chagApp_openai, 'openai_client', self.client):
            vision = chagApp_openai.Vision(config.MODELS['llm_vision'])
            vision.chat('Portion of image 1?', IMAGE_1)
            vision.chat('Portion of image 2?', IMAGE_2)
        first, second = self.sent
        self.assertEqual(len(first), len(second))
        self.assertEqual([m['role'] for m in second], ['system', 'user'])
        self.assertEqual(second[0], first[0])
        self.assertEqual(second[1]['content'][1]['image_url']['url'], IMAGE_2)
        self.assertNotIn('FIRSTIMAGE', json.dumps(second))
        self.assertNotIn('answer 1', json.dumps(second))
        self.assertEqual(len(vision.messages), 1)

    def test_image_description_step_is_independent(self):
        with mock.patch.object(rag_food_code, 'openai_client', self.client):
            _, llm_vision, _ = rag_food_code.initialize_clients(config.MODELS)
            llm_vision.invoke(rag_food_code.get_messages_from_url(IMAGE_1))
            llm_vision.invoke(rag_food_code.get_messages_from_url(IMAGE_2))
        first, second = self.sent
        self.assertEqual(len(first), len(second))
        self.assertEqual([m['role'] for m in second], ['system', 'user'])
        self.assertNotIn('FIRSTIMAGE', json.dumps(second))
        self.assertNotIn('answer 1', json.dumps(second))


if __name__ == '__main__':
    unittest.main()
