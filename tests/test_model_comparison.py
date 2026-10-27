"""F1-F3: compare models without changing prompts, embeddings or baseline requests."""
import json
import sys
import unittest
from pathlib import Path
from unittest import mock

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'code'))
sys.path.insert(0, str(ROOT / 'tests'))

import api_log
import chagApp_openai
import config
import rag_food_code
import run_experiment
import test_temperature
import test_run_experiment


class TestComparisonRequests(unittest.TestCase):
    setUp = test_temperature.TestTemperature.setUp
    tearDown = test_temperature.TestTemperature.tearDown
    fake_openai = test_temperature.TestTemperature.fake_openai

    # All four chat clients must select Sol at the actual wire boundary.
    def test_sol_all_chat_steps(self):
        client = lambda: api_log.openai_client(transport=httpx.MockTransport(self.fake_openai))
        with mock.patch.dict(config.MODELS), \
                mock.patch.object(chagApp_openai, 'openai_client', client), \
                mock.patch.object(rag_food_code, 'openai_client', client):
            config.select_model(config.COMPARISON_MODEL)
            self.assertEqual(config.MODELS['embedding'], 'text-embedding-3-large')
            chagApp_openai.Vision(config.MODELS['llm_vision']).chat('portion?', 'data:image/png;base64,aA==')
            llm, vision, _ = rag_food_code.initialize_clients(config.MODELS)
            llm.invoke('queries')
            vision.invoke('description')
            rag_food_code.code_model(vision).invoke('codes')
        self.assertEqual(len(self.sent), 4)
        for request in self.sent:
            self.assertEqual(request['model'], config.COMPARISON_MODEL)
            self.assertEqual(request['temperature'], 1)
            self.assertNotIn('max_tokens', request)
            self.assertNotIn('extra_body', request)
        self.assertEqual([r.get('max_completion_tokens') for r in self.sent], [600, None, 4096, None])
        with open(config.API_LOG_PATH) as file:
            logged = [json.loads(line) for line in file]
        self.assertEqual([r['max_completion_tokens'] for r in logged], [600, None, 4096, None])

    def test_switch_preserves_messages(self):
        client = lambda: api_log.openai_client(transport=httpx.MockTransport(self.fake_openai))
        with mock.patch.object(chagApp_openai, 'openai_client', client):
            for model in config.CHAT_MODELS:
                chagApp_openai.Vision(model).chat('same prompt', 'data:image/png;base64,aA==')
        self.assertEqual(self.sent[0]['messages'], self.sent[1]['messages'])
        self.assertEqual(self.sent[0]['max_tokens'], 600)
        self.assertNotIn('max_completion_tokens', self.sent[0])


class TestComparisonCLI(unittest.TestCase):
    def test_default_and_explicit_model(self):
        self.assertEqual(run_experiment.parse_args(['--split', 'dev']).model, config.DEFAULT_MODEL)
        self.assertEqual(run_experiment.parse_args(['--split', 'dev', '--model', config.COMPARISON_MODEL]).model,
                         config.COMPARISON_MODEL)

    def test_unknown_model_is_rejected(self):
        with self.assertRaises(ValueError):
            config.select_model('unknown')


class TestComparisonCost(unittest.TestCase):
    def record(self, **usage):
        return {'status': 200, 'model_served': config.COMPARISON_MODEL,
                'model_requested': config.COMPARISON_MODEL, 'usage': usage}

    def test_reasoning_is_counted_once_and_cache_is_discounted(self):
        row = self.record(prompt_tokens=1000, prompt_tokens_details={'cached_tokens': 400},
                          completion_tokens=200, completion_tokens_details={'reasoning_tokens': 128})
        counted = run_experiment.cost([row])
        self.assertAlmostEqual(counted['usd'], .00324)
        self.assertEqual(counted['reasoning_tokens'], 128)
        self.assertEqual(counted['completion_tokens'], 200)

    def test_unpriced_model_or_context_fails(self):
        row = self.record(prompt_tokens=272001)
        with self.assertRaisesRegex(ValueError, 'long-context'):
            run_experiment.cost([row])
        row['model_served'] = 'unknown'
        with self.assertRaisesRegex(KeyError, 'no price'):
            run_experiment.cost([row])


class TestComparisonPipeline(test_run_experiment.OfflineRun):
    def test_sol_pipeline_and_configuration_isolation(self):
        with mock.patch.dict(config.MODELS):
            config.select_model(config.COMPARISON_MODEL)
            self.run_split()
            saved = self.saved('config.json')
            self.assertEqual(saved['temperature'], 1)
            self.assertEqual(saved['models']['llm'], config.COMPARISON_MODEL)
            for kind, image, body in self.world.requests:
                self.assertEqual(body['model'], config.COMPARISON_MODEL)
                self.assertEqual(body['temperature'], 1)
                self.assertNotIn('max_tokens', body)
            config.select_model(config.DEFAULT_MODEL)
            before = len(self.world.requests)
            with self.assertRaisesRegex(RuntimeError, 'another configuration'):
                self.run_split()
            self.assertEqual(len(self.world.requests), before)


if __name__ == '__main__':
    unittest.main()
