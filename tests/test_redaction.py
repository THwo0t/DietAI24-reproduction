"""R-A3-1: an API error that quotes the key leaves no key or fragment in exceptions, logs,
prints or result CSVs, and keeps the status code, error type and code. R-A3-2: only echoes
of the key are replaced, so the error fields and the JSON response stay intact (offline)."""
import contextlib
import io
import json
import logging
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import httpx
import numpy as np
import openai
import pandas as pd
from langchain_core.documents import Document
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'code'))

import api_log  # noqa: E402
import chagApp_openai  # noqa: E402
import config  # noqa: E402
import rag_food_code  # noqa: E402
import rag_portion_size  # noqa: E402

with mock.patch('pandas.read_excel', return_value=pd.DataFrame(columns=range(5))):
    import baseline_chatGPT  # noqa: E402  (reads the FNDDS nutrient table at import)

PLAIN_KEY = 'test-key-0123456789abcdefghijklmnopqrstuvwxyz'
SK_KEY = 'sk-' + 'proj-' + 'A1b2C3d4' * 6  # built at run time so the repository key scan stays clean
# R-A3-2: keys whose last 4 characters occur in ordinary error fields, and one whose first 8
# and last 4 frame the 401 error code
COLLIDING_KEYS = ['sk-' + 'proj-' + 'Q1w2E3r4' * 6 + end for end in ('rate', '_key', 'null')] \
    + ['invalid_' + 'Q1w2E3r4' * 5 + '_key']
REQUEST_ID = 'req_test401'
IMAGE = 'data:image/png;base64,iVBORw0KGgo='
RATE_LIMIT_ERROR = {
    'message': 'Rate limit reached for gpt-4o-2024-08-06 (task-limit-exceeded, see risk-assessment-policy). '
               'Visit https://platform.openai.com/account/rate-limits to learn more.',
    'type': 'rate_limit_error', 'param': None, 'code': 'rate_limit_exceeded'}


def wrong_key_error(api_key):
    """The error the OpenAI API returns for a wrong key: the message quotes it as head****tail."""
    return {'message': f'Incorrect API key provided: {api_key[:8]}{"*" * 40}{api_key[-4:]}. '
                       'You can find your API key at https://platform.openai.com/account/api-keys.',
            'type': 'invalid_request_error', 'param': None, 'code': 'invalid_api_key'}


def reply(status, error):
    def handler(request):
        # x-should-retry: false, or the SDK waits and retries a 429
        return httpx.Response(status, headers={'x-request-id': REQUEST_ID, 'x-should-retry': 'false'},
                              json={'error': error})
    return handler


def reject(api_key):
    return reply(401, wrong_key_error(api_key))


def describe(request):
    return httpx.Response(200, json={
        'id': 'chatcmpl-1', 'object': 'chat.completion', 'created': 0, 'model': 'gpt-4o-2024-08-06',
        'choices': [{'index': 0, 'finish_reason': 'stop',
                     'message': {'role': 'assistant', 'content': 'an apple'}}],
        'usage': {'prompt_tokens': 10, 'completion_tokens': 2, 'total_tokens': 12}})


class TestRedaction(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.api_log_path = os.path.join(self.tmp.name, 'openai_api.jsonl')
        patch = mock.patch.object(config, 'API_LOG_PATH', self.api_log_path)
        patch.start()
        self.addCleanup(patch.stop)
        self.use_key(PLAIN_KEY)

    def use_key(self, key):
        self.key = key
        env_path = os.path.join(self.tmp.name, '.env')
        with open(env_path, 'w') as f:
            f.write(f'OPENAI_API_KEY={key}\n')
        patch = mock.patch.object(config, 'ENV_PATH', env_path)
        patch.start()
        self.addCleanup(patch.stop)

    def client(self, handler):
        return lambda: api_log.openai_client(transport=httpx.MockTransport(handler))

    def assertClean(self, text):
        for fragment in [self.key, self.key[:8], self.key[-4:], '****']:
            self.assertNotIn(fragment, text)

    def capture_log(self, name):
        """Send the root logger to a file through the scripts' own setup_logging()."""
        root = logging.getLogger()
        saved = root.handlers[:]
        root.handlers = []
        path = os.path.join(self.tmp.name, name)
        rag_food_code.setup_logging(path)

        def restore():
            for handler in root.handlers:
                handler.close()
            root.handlers = saved
        self.addCleanup(restore)
        return path

    def test_api_errors_carry_no_key_but_keep_status_and_codes(self):
        for key in [PLAIN_KEY, SK_KEY]:
            self.use_key(key)
            with mock.patch.object(chagApp_openai, 'openai_client', self.client(reject(key))), \
                    mock.patch.object(rag_food_code, 'openai_client', self.client(reject(key))):
                vision = chagApp_openai.Vision(config.MODELS['llm_vision'])
                llm, _, embedding = rag_food_code.initialize_clients(config.MODELS)
            calls = {'Vision.chat': lambda: vision.chat('Which food is this?', IMAGE),
                     'ChatOpenAI': lambda: llm.invoke('Which food code?'),
                     'embeddings': lambda: embedding.client.create(input=['apple'], model=embedding.model)}
            for name, call in calls.items():
                with self.subTest(key_style=key[:3], call=name):
                    with self.assertRaises(openai.AuthenticationError) as raised:
                        call()
                    e = raised.exception
                    for text in [str(e), repr(e), e.message, json.dumps(e.body), e.response.text]:
                        self.assertClean(text)
                    self.assertIn('Error code: 401', str(e))
                    self.assertIn("'type': 'invalid_request_error'", str(e))
                    self.assertIn("'code': 'invalid_api_key'", str(e))
                    self.assertEqual(e.code, 'invalid_api_key')
                    self.assertEqual(e.response.headers['x-request-id'], REQUEST_ID)

    def test_error_fields_and_json_survive_key_collisions(self):
        # R-A3-2: type, code and param stay exact, e.response still parses and agrees with e.body
        # and str(e), and the check at rag_food_code.py:163 still tells a 429 from a 401
        for key in COLLIDING_KEYS:
            self.use_key(key)
            wrong_key = wrong_key_error(key)
            echo = key[:8] + '*' * 40 + key[-4:]
            cases = [(401, wrong_key, openai.AuthenticationError,
                      dict(wrong_key, message=wrong_key['message'].replace(echo, api_log.REDACTED))),
                     (429, RATE_LIMIT_ERROR, openai.RateLimitError, RATE_LIMIT_ERROR)]
            for status, error, exception, expected in cases:
                with mock.patch.object(chagApp_openai, 'openai_client', self.client(reply(status, error))), \
                        mock.patch.object(rag_food_code, 'openai_client', self.client(reply(status, error))):
                    vision = chagApp_openai.Vision(config.MODELS['llm_vision'])
                    llm, _, embedding = rag_food_code.initialize_clients(config.MODELS)
                calls = {'Vision.chat': lambda: vision.chat('Which food is this?', IMAGE),
                         'ChatOpenAI': lambda: llm.invoke('Which food code?'),
                         'embeddings': lambda: embedding.client.create(input=['apple'], model=embedding.model)}
                for name, call in calls.items():
                    with self.subTest(key_ends=(key[:8], key[-4:]), status=status, call=name):
                        with self.assertRaises(exception) as raised:
                            call()
                        e = raised.exception
                        self.assertEqual(e.body, expected)
                        self.assertEqual((e.type, e.code, e.param), (error['type'], error['code'], error['param']))
                        self.assertEqual(e.response.json(), {'error': expected})
                        self.assertEqual(e.response.text, json.dumps({'error': expected}))
                        self.assertEqual(str(e), f"Error code: {status} - {({'error': expected})}")
                        self.assertEqual('429' in str(e) or 'rate limit' in str(e).lower(), status == 429)
                        for text in [str(e), e.response.text]:
                            self.assertNotIn(key, text)
                            self.assertNotIn('***', text)

    def test_redact_replaces_echoes_not_words(self):
        # R-A3-2: a fragment of the key inside a word, or sk- inside a word, is not an echo
        key = COLLIDING_KEYS[0]  # ends with rate
        for text in ['rate_limit_exceeded', 'see https://platform.openai.com/account/rate-limits.',
                     'task-limit-exceeded', 'risk-assessment-policy']:
            self.assertEqual(api_log.redact(text, key), text)
        sk_token = 'sk-' + 'abcdefgh' * 2
        for text, redacted in [(f'Bearer {key}', 'Bearer [REDACTED]'),
                               (f'provided: {key[:8]}{"*" * 20}{key[-4:]}.', 'provided: [REDACTED].'),
                               (f'provided: {key[:8]}...{key[-4:]}.', 'provided: [REDACTED].'),
                               (f'key={sk_token}&model=gpt-4o', 'key=[REDACTED]&model=gpt-4o')]:
            self.assertEqual(api_log.redact(text, key), redacted)
        # a body that is not JSON is redacted as text; one with nothing to redact is passed on
        request = httpx.Request('POST', 'https://api.openai.com/v1/embeddings')
        page = httpx.Response(502, request=request, text=f'Bad gateway for {key[:8]}{"*" * 20}{key[-4:]}')
        self.assertEqual(api_log.redact_response(page, key).text, 'Bad gateway for [REDACTED]')
        page = httpx.Response(502, request=request, text='Bad gateway, see rate-limits')
        self.assertIs(api_log.redact_response(page, key), page)

    def test_process_image_url_writes_no_key_to_log_or_csv(self):
        # rag_food_code.py:174 logs the error, :183-188 writes str(e) to the results CSV
        log_path = self.capture_log('process_images.log')
        results_path = os.path.join(self.tmp.name, 'results.csv')
        df = pd.DataFrame({'Link': ['https://img.invalid/0.png', 'https://img.invalid/1.png'],
                           'GPTFoodDescription': pd.Series([np.nan] * 2, dtype=object),
                           'GPTFoodCode': [np.nan, np.nan]})
        with mock.patch.object(rag_food_code, 'openai_client', self.client(reject(self.key))):
            failing_llm, failing_vision, _ = rag_food_code.initialize_clients(config.MODELS)
        with mock.patch.object(rag_food_code, 'openai_client', self.client(describe)):
            _, working_vision, _ = rag_food_code.initialize_clients(config.MODELS)
        code_chain = ChatPromptTemplate.from_template('{question}') | failing_llm | StrOutputParser()
        with mock.patch.object(rag_food_code.requests, 'head', return_value=mock.Mock(status_code=200)):
            # image 0 fails at the description step, image 1 at the food code step
            rag_food_code.process_image_url(0, df.loc[0, 'Link'], failing_vision, df, code_chain, results_path)
            rag_food_code.process_image_url(1, df.loc[1, 'Link'], working_vision, df, code_chain, results_path)
        log_text = Path(log_path).read_text()
        self.assertClean(log_text)
        self.assertClean(Path(results_path).read_text())
        self.assertIn('Failed to invoke llm_vision at index 0: Error code: 401', log_text)
        saved = pd.read_csv(results_path)
        for i in range(2):
            self.assertIn('Error code: 401', saved.loc[i, 'GPTFoodDescription'])
            self.assertIn('invalid_api_key', saved.loc[i, 'GPTFoodDescription'])
            self.assertTrue(pd.isna(saved.loc[i, 'GPTFoodCode']))
        with open(self.api_log_path) as f:
            errors = [r for r in map(json.loads, f) if r['status'] == 401]
        self.assertEqual([(r['request_id'], r['error_code']) for r in errors],
                         [(REQUEST_ID, 'invalid_api_key')] * 2)

    def test_vector_database_error_log_has_no_key(self):
        # rag_food_code.py:65-66 logs the error of every indexing attempt
        log_path = self.capture_log('index.log')
        with mock.patch.object(rag_food_code, 'openai_client', self.client(reject(self.key))):
            _, _, embedding = rag_food_code.initialize_clients(config.MODELS)
        tokenizer = mock.Mock(encode=mock.Mock(return_value=[1, 2, 3]))  # real tiktoken downloads its vocabulary
        index = os.path.join(self.tmp.name, 'chroma')  # C1: the index is persisted, here in a temporary directory
        with mock.patch('tiktoken.encoding_for_model', return_value=tokenizer), \
                mock.patch.object(rag_food_code.time, 'sleep'):
            with self.assertRaises(Exception):
                rag_food_code.setup_vector_database([Document(page_content='apple', metadata={'row': 0})],
                                                    embedding, index)
        log_text = Path(log_path).read_text()
        self.assertClean(log_text)
        self.assertEqual(log_text.count('Failed to setup vector database: Error code: 401'), 5)

    def test_portion_and_baseline_prints_have_no_key(self):
        # rag_portion_size.py:79-80 and baseline_chatGPT.py:73-74 print(e)
        df = pd.DataFrame({'Link': [IMAGE], 'FC_Description': ['Apple, raw'],
                           'GPTPortionDescription': [np.nan], 'GPTPortionReason': [np.nan]})
        printed = io.StringIO()
        with mock.patch.object(chagApp_openai, 'openai_client', self.client(reject(self.key))), \
                contextlib.redirect_stdout(printed):
            vision = chagApp_openai.Vision(config.MODELS['llm_vision'])
            rag_portion_size.analyze_portions(df, vision, 'GPTPortionDescription', 'GPTPortionReason',
                                              ['1 cup, 2 cups'])
            baseline_chatGPT.process_images(pd.DataFrame({'Link': [IMAGE]}),
                                            {'basic nutrients': ['Calorie (kcal)']},
                                            os.path.join(self.tmp.name, 'baseline.csv'))
        self.assertClean(printed.getvalue())
        self.assertEqual(printed.getvalue().count('Error code: 401'), 2)


if __name__ == '__main__':
    unittest.main()
