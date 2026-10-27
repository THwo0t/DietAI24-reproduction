"""A4: every API call is sent with temperature 0 (offline)."""
import ast
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import httpx

ROOT = Path(__file__).resolve().parents[1]
CODE = ROOT / 'code'
sys.path.insert(0, str(CODE))

import api_log  # noqa: E402
import chagApp_openai  # noqa: E402
import config  # noqa: E402
import rag_food_code  # noqa: E402


class TestTemperature(unittest.TestCase):

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
        self.sent.append(json.loads(request.content))
        return httpx.Response(200, json={
            'id': 'chatcmpl-1', 'object': 'chat.completion', 'created': 0, 'model': 'gpt-4o-2024-08-06',
            'choices': [{'index': 0, 'finish_reason': 'stop',
                         'message': {'role': 'assistant', 'content': 'an apple'}}],
            'usage': {'prompt_tokens': 10, 'completion_tokens': 2, 'total_tokens': 12}})

    def test_config_temperature_is_zero(self):
        self.assertEqual(config.TEMPERATURE, 0)

    def test_requests_carry_temperature_zero(self):
        client = lambda: api_log.openai_client(transport=httpx.MockTransport(self.fake_openai))
        with mock.patch.object(chagApp_openai, 'openai_client', client), \
                mock.patch.object(rag_food_code, 'openai_client', client):
            chagApp_openai.Vision(config.MODELS['llm_vision']).chat(
                'Which food is this?', 'data:image/png;base64,iVBORw0KGgo=')
            llm, llm_vision, _ = rag_food_code.initialize_clients(config.MODELS)
            llm.invoke('Which food code?')          # text steps (multi-query, food code)
            llm_vision.invoke('Which food?')        # image description
        self.assertEqual(len(self.sent), 3)
        for body in self.sent:
            self.assertEqual(body['temperature'], 0)  # LangChain sends the float 0.0

    def test_no_other_temperature_in_pipeline(self):
        # chatApp_azure.py keeps the published 0.3, but no script imports it (CHECKLIST.md A2, A4).
        for path in sorted(CODE.glob('*.py')):
            tree = ast.parse(path.read_text())
            imported = {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
            imported |= {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
            self.assertNotIn('chatApp_azure', imported, path.name)
            if path.name == 'chatApp_azure.py':
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.keyword) and node.arg == 'temperature':
                    with self.subTest(script=path.name, line=node.value.lineno):
                        self.assertIsInstance(node.value, ast.Call)
                        self.assertEqual(node.value.func.id, 'temperature_for')


if __name__ == '__main__':
    unittest.main()
