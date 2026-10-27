"""C: the food code, portion and nutrient steps of the original scripts (offline, mocked API)."""
import base64
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import httpx
import numpy as np
import pandas as pd
from langchain.retrievers.multi_query import MultiQueryRetriever
from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langchain_core.retrievers import BaseRetriever
from langchain_core.runnables import RunnableLambda
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'code'))

import api_log  # noqa: E402
import config  # noqa: E402
import evaluate  # noqa: E402
import nutrient_estimate  # noqa: E402
import nutrient_estimate_mix  # noqa: E402
import rag_food_code  # noqa: E402
import rag_portion_size  # noqa: E402


class CountingEmbeddings(Embeddings):
    """Deterministic vectors; counts the texts it embeds and can fail once."""

    def __init__(self, fail_after=None):
        self.embedded = []
        self.fail_after = fail_after

    def embed_documents(self, texts):
        if self.fail_after is not None and len(self.embedded) + len(texts) > self.fail_after:
            self.fail_after = None
            raise RuntimeError('connection reset')
        self.embedded.extend(texts)
        return [[float(len(t)), float(sum(map(ord, t)) % 97), 1.0] for t in texts]

    def embed_query(self, text):
        return self.embed_documents([text])[0]


def documents(n):
    return [Document(page_content=f'Food code: {10000000 + i}\nFood description: food {i}',
                     metadata={'source': 'foods.csv', 'row': i}) for i in range(n)]


class TestC1VectorIndex(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def test_built_once_and_reused(self):
        index = os.path.join(self.tmp.name, 'chroma')
        first = CountingEmbeddings()
        db = rag_food_code.setup_vector_database(documents(30), first, index)
        self.assertEqual(db._collection.count(), 30)
        self.assertEqual(len(first.embedded), 30)
        self.assertFalse(db._client_settings.anonymized_telemetry)
        again = CountingEmbeddings()
        db = rag_food_code.setup_vector_database(documents(30), again, index)
        self.assertEqual(db._collection.count(), 30)
        self.assertEqual(again.embedded, [])  # loaded from disk, nothing embedded
        self.assertEqual(sorted(db.get(include=[])['ids'], key=int), [str(i) for i in range(30)])

    def test_retry_adds_only_what_is_missing(self):
        index = os.path.join(self.tmp.name, 'chroma')
        rag_food_code.setup_vector_database(documents(10), CountingEmbeddings(), index)  # a partial build
        embedding = CountingEmbeddings(fail_after=5)
        with mock.patch.object(rag_food_code.time, 'sleep') as sleep:
            db = rag_food_code.setup_vector_database(documents(30), embedding, index)
        sleep.assert_called_once()
        self.assertEqual(db._collection.count(), 30)
        self.assertEqual(len(embedding.embedded), 20)  # rows 10-29, embedded once

    def test_added_in_batches_chroma_accepts(self):
        # 5,624 rows exceed Chroma's maximum batch (5,461 here); a failed batch is not embedded again
        index = os.path.join(self.tmp.name, 'chroma')
        db = rag_food_code.setup_vector_database(documents(0), CountingEmbeddings(), index)
        embedding = CountingEmbeddings(fail_after=10)
        with mock.patch.object(type(db._client), 'max_batch_size', new_callable=mock.PropertyMock, return_value=4), \
                mock.patch.object(rag_food_code.time, 'sleep'):
            db = rag_food_code.setup_vector_database(documents(23), embedding, index)
        self.assertEqual(db._collection.count(), 23)
        self.assertEqual(len(embedding.embedded), 23)



class FakeVision:
    """Stands in for llm_vision.invoke in the description step."""

    def __init__(self, answer='Apple, raw, with skin'):
        self.answer = answer
        self.calls = []

    def invoke(self, messages):
        self.calls.append(messages)
        return SimpleNamespace(content=self.answer)


def results_table(links):
    return pd.DataFrame({'Link': links, 'GPTFoodDescription': pd.Series([np.nan] * len(links), dtype=object),
                         'GPTFoodCode': pd.Series([np.nan] * len(links), dtype=object)})


class TestC2ImageDescription(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.image = os.path.join(self.tmp.name, 'apple.png')
        Image.new('RGBA', (160, 160), (255, 255, 255, 0)).save(self.image)

    def test_message_carries_the_resized_image(self):
        system, human = rag_food_code.get_messages_from_url(self.image)
        self.assertTrue(system.content.startswith('You are an expert at analyzing images with computer vision.'))
        text, image = human.content
        self.assertTrue(text['text'].startswith('Could you name the food shown in the image?'))
        url = image['image_url']['url']  # an object, as the API requires, not a bare string
        self.assertTrue(url.startswith('data:image/png;base64,'))
        self.assertEqual(Image.open(io.BytesIO(base64.b64decode(url.split(',', 1)[1]))).size, (256, 256))

    def test_local_images_need_no_http(self):
        results = os.path.join(self.tmp.name, 'results.csv')
        missing = os.path.join(self.tmp.name, 'missing.png')
        df = results_table([self.image, missing])
        chain = mock.Mock(invoke=mock.Mock(return_value={'context': [], 'answer': '63101000'}))
        with mock.patch.object(rag_food_code.requests, 'head') as head:
            rag_food_code.process_image_url(0, self.image, FakeVision(), df, chain, results)
            rag_food_code.process_image_url(1, missing, FakeVision(), df, chain, results)
        head.assert_not_called()
        self.assertEqual(df.loc[0, 'GPTFoodCode'], "['63101000']")
        # a missing file is a failure, recorded as such
        self.assertEqual(df.loc[1, 'GPTFoodDescription'], 'Image URL is not accessible')
        self.assertTrue(pd.isna(df.loc[1, 'GPTFoodCode']))



class RecordingChatModel(FakeListChatModel):
    """Fake chat model that keeps the messages it was sent."""
    received: list = []

    def _call(self, messages, stop=None, run_manager=None, **kwargs):
        self.received.append(messages)
        return super()._call(messages, stop, run_manager, **kwargs)


class RecordingRetriever(BaseRetriever):
    """Fake similarity search: the FNDDS rows for each query, recorded."""
    queries: list = []
    rows: dict = {}

    def _get_relevant_documents(self, query, *, run_manager):
        self.queries.append(query)
        return [Document(page_content=f'Food code: {code}\nFood description: The image shows {code}.',
                         metadata={'source': 'foods.csv', 'row': code}) for code in self.rows.get(query, [])]


def food_code_chain(code_answer='63101000', rows=None):
    query_llm = RecordingChatModel(responses=['Raw apple slices\nFresh fruit, apple\nSliced apple'], received=[])
    code_llm = RecordingChatModel(responses=[code_answer], received=[])
    base = RecordingRetriever(queries=[], rows=rows or {'Raw apple slices': ['63101000', '63101110'],
                                                       'Fresh fruit, apple': ['63101000'],
                                                       'Sliced apple': ['63101110', '63115010']})
    retriever = MultiQueryRetriever.from_llm(retriever=base, llm=query_llm, prompt=rag_food_code.setup_retrieval_prompt())
    return rag_food_code.setup_code_prompt_chain(retriever, code_llm), query_llm, base, code_llm


class TestC3Retrieval(unittest.TestCase):

    def test_retriever_gets_the_description_only(self):
        chain, query_llm, base, _ = food_code_chain()
        result = chain.invoke({'question': 'Sliced apple, raw', 'url_str': '/images/apple.png'})
        prompt = query_llm.received[0][0].content
        self.assertTrue(prompt.endswith('Original food description: Sliced apple, raw'))
        self.assertNotIn('apple.png', prompt)
        self.assertNotIn('url_str', prompt)
        # each generated query is searched; the union of the rows, without duplicates, is the context
        self.assertEqual(base.queries, ['Raw apple slices', 'Fresh fruit, apple', 'Sliced apple'])
        self.assertEqual(rag_food_code.candidate_codes(result['context']), ['63101000', '63101110', '63115010'])
        self.assertEqual(result['answer'], '63101000')

    def test_candidates_are_recorded(self):
        chain, *_ = food_code_chain()
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        image = os.path.join(tmp.name, 'apple.png')
        Image.new('RGB', (64, 64)).save(image)
        results = os.path.join(tmp.name, 'results.csv')
        results_table([image]).to_csv(results, index=False)
        rag_food_code.process_image_urls(results, os.path.join(tmp.name, 'checkpoint.txt'), FakeVision('Sliced apple'),
                                         chain)
        saved = pd.read_csv(results)
        self.assertEqual(saved.loc[0, 'GPTFoodCode'], "['63101000']")
        self.assertEqual(saved.loc[0, 'GPTCandidateCodes'], "['63101000', '63101110', '63115010']")



def chat_response(content):
    return httpx.Response(200, json={
        'id': 'chatcmpl-1', 'object': 'chat.completion', 'created': 0, 'model': 'gpt-4o-2024-08-06',
        'choices': [{'index': 0, 'finish_reason': 'stop', 'message': {'role': 'assistant', 'content': content}}],
        'usage': {'prompt_tokens': 10, 'completion_tokens': 2, 'total_tokens': 12}})


class MockedAPI:
    """Patches the .env, the API log and the OpenAI transport; answers() gives each reply."""

    def __init__(self, test, answers):
        self.sent = []
        tmp = tempfile.TemporaryDirectory()
        test.addCleanup(tmp.cleanup)
        env_path = os.path.join(tmp.name, '.env')
        with open(env_path, 'w') as f:
            f.write('OPENAI_API_KEY=sk-test\n')

        def handler(request):
            body = json.loads(request.content)
            self.sent.append(body)
            return chat_response(answers(body))
        client = lambda: api_log.openai_client(transport=httpx.MockTransport(handler))
        for patch in [mock.patch.object(config, 'ENV_PATH', env_path),
                      mock.patch.object(config, 'API_LOG_PATH', os.path.join(tmp.name, 'api.jsonl')),
                      mock.patch.object(rag_food_code, 'openai_client', client)]:
            patch.start()
            test.addCleanup(patch.stop)


class TestC4CodeSelection(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.image = os.path.join(self.tmp.name, 'apple.png')
        Image.new('RGB', (300, 200), (200, 30, 30)).save(self.image)

    def test_vision_model_sees_the_image_and_the_candidates(self):
        chain, _, _, code_llm = food_code_chain()
        result = chain.invoke({'question': 'Sliced apple, raw', 'url_str': self.image})
        (message,) = code_llm.received[0]
        text, image = message.content
        self.assertTrue(text['text'].startswith(
            'Could you identify and provide the eight-digit food code corresponding to the given food image,'))
        for code in ('63101000', '63101110', '63115010'):  # the candidates from C3
            self.assertIn(f'Food code: {code}', text['text'])
        self.assertNotIn(self.image, text['text'])
        url = image['image_url']['url']
        self.assertEqual(Image.open(io.BytesIO(base64.b64decode(url.split(',', 1)[1]))).size, (256, 256))
        self.assertEqual(result['answer'], '63101000')

    def test_request_goes_to_the_vision_model_without_a_token_cap(self):
        api = MockedAPI(self, lambda body: '63101000')
        _, llm_vision, _ = rag_food_code.initialize_clients(config.MODELS)
        retriever = RunnableLambda(lambda query: [Document(page_content='Food code: 63101000\nFood description: apple',
                                                           metadata={'row': 0})])
        chain = rag_food_code.setup_code_prompt_chain(retriever, rag_food_code.code_model(llm_vision))
        self.assertEqual(chain.invoke({'question': 'apple', 'url_str': self.image})['answer'], '63101000')
        (body,) = api.sent
        self.assertEqual(body['model'], config.MODELS['llm_vision'])
        self.assertNotIn('max_tokens', body)
        self.assertEqual(body['temperature'], 0)
        self.assertEqual(llm_vision.max_tokens, 200)  # the description step keeps its cap
        text, image = body['messages'][0]['content']
        self.assertTrue(image['image_url']['url'].startswith('data:image/png;base64,'))



class RateLimitedVision(FakeVision):
    """Raises a 429 error the first `limited` times (all times when None)."""

    def __init__(self, limited=None):
        super().__init__()
        self.limited = limited

    def invoke(self, messages):
        if self.limited is None or len(self.calls) < self.limited:
            self.calls.append(messages)
            raise RuntimeError("Error code: 429 - {'error': {'code': 'rate_limit_exceeded'}}")
        return super().invoke(messages)


class TestC9Retries(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.images = []
        for i in range(8):
            self.images.append(os.path.join(self.tmp.name, f'{i}.png'))
            Image.new('RGB', (32, 32), (i * 30, 0, 0)).save(self.images[-1])
        self.results = os.path.join(self.tmp.name, 'results.csv')
        self.chain = mock.Mock(invoke=mock.Mock(return_value={'context': [], 'answer': '63101000'}))

    def test_rate_limit_backoff(self):
        # min(2 ** attempts * 30) raised TypeError, so the original never waited and lost the 429
        df = results_table(self.images[:2])
        with mock.patch.object(rag_food_code.time, 'sleep') as sleep:
            rag_food_code.process_image_url(0, self.images[0], RateLimitedVision(2), df, self.chain, self.results)
        self.assertEqual([c.args[0] for c in sleep.call_args_list], [30, 60])
        self.assertEqual(df.loc[0, 'GPTFoodCode'], "['63101000']")
        with mock.patch.object(rag_food_code.time, 'sleep') as sleep:
            rag_food_code.process_image_url(1, self.images[1], RateLimitedVision(), df, self.chain, self.results)
        self.assertEqual([c.args[0] for c in sleep.call_args_list], [30, 60, 120, 240])
        self.assertIn('Error code: 429', df.loc[1, 'GPTFoodDescription'])
        self.assertTrue(pd.isna(df.loc[1, 'GPTFoodCode']))

    def test_attempts_are_counted_over_passes(self):
        results_table(self.images[:2]).to_csv(self.results, index=False)
        answers = iter(['No appropriate food codes found from the context information.', '63101000', '63101110'])
        self.chain.invoke = lambda inputs: {'context': [], 'answer': next(answers)}
        rag_food_code.process_image_urls(self.results, os.path.join(self.tmp.name, 'checkpoint.txt'), FakeVision(),
                                         self.chain)
        saved = pd.read_csv(self.results)
        self.assertEqual(saved['GPTAttempts'].tolist(), [2, 1])  # image 0 failed in pass 1, succeeded in pass 2
        self.assertEqual(saved['GPTFoodCode'].tolist(), ["['63101110']", "['63101000']"])

    def test_skip_reads_codes_as_the_evaluation(self):
        # R-C9-1: characters 3-10 decided the skip, while D1, D4 and D6 read whole 8-digit codes
        for answer in ["['63101000']", "['Food code: 63101000']", "['631010001']", "['No code']", np.nan]:
            self.assertEqual(rag_food_code.has_food_code(answer), len(rag_portion_size.parse_food_codes(answer)) > 0, answer)
        results_table(self.images[:2]).to_csv(self.results, index=False)
        answers = {self.images[0]: iter(['Food code: 63101000']), self.images[1]: iter(['631010001', '63101000'])}

        def invoke(inputs):
            answer = next(answers[inputs['url_str']], None)
            if answer is None:
                raise RuntimeError('a later failure')
            return {'context': [], 'answer': answer}
        self.chain.invoke = invoke
        rag_food_code.process_image_urls(self.results, os.path.join(self.tmp.name, 'checkpoint.txt'), FakeVision(),
                                         self.chain)
        saved = pd.read_csv(self.results)
        # the prefixed code is not asked again and overwritten by a failure (it was: 5 passes, no code);
        # nine digits are no code and use the next pass (they were skipped)
        self.assertEqual(saved['GPTAttempts'].tolist(), [1, 2])
        self.assertEqual(saved['GPTFoodCode'].tolist(), ["['Food code: 63101000']", "['63101000']"])

    def test_parallel_images(self):
        results_table(self.images).to_csv(self.results, index=False)
        checkpoint = os.path.join(self.tmp.name, 'checkpoint.txt')
        rag_food_code.process_image_urls(self.results, checkpoint, FakeVision(), self.chain, workers=4)
        saved = pd.read_csv(self.results)
        self.assertEqual(saved['GPTFoodCode'].tolist(), ["['63101000']"] * 8)
        self.assertEqual(saved['GPTAttempts'].tolist(), [1] * 8)
        self.assertEqual(Path(checkpoint).read_text(), '5,0')

    def test_sdk_resends_rate_limited_requests(self):
        replies = iter([429, 429, 200])

        def handler(request):
            status = next(replies)
            if status == 429:
                return httpx.Response(429, headers={'retry-after-ms': '1'},
                                      json={'error': {'message': 'Rate limit reached', 'type': 'requests',
                                                      'param': None, 'code': 'rate_limit_exceeded'}})
            return chat_response('an apple')
        tmp = self.tmp.name
        with open(os.path.join(tmp, '.env'), 'w') as f:
            f.write('OPENAI_API_KEY=sk-test\n')
        with mock.patch.object(config, 'ENV_PATH', os.path.join(tmp, '.env')), \
                mock.patch.object(config, 'API_LOG_PATH', os.path.join(tmp, 'api.jsonl')):
            client = api_log.openai_client(transport=httpx.MockTransport(handler))
            self.assertEqual(client.max_retries, 6)
            client.chat.completions.create(model=config.MODELS['llm_vision'], messages=[{'role': 'user', 'content': 'hi'}])
        statuses = [json.loads(line)['status'] for line in Path(tmp, 'api.jsonl').read_text().splitlines()]
        self.assertEqual(statuses, [429, 429, 200])  # every response is logged



ASA24_LINK = pd.DataFrame({
    'FoodCode': [63101000, 63101000, 63101000, 11111000, 11111000, 11111000],
    'FC_Description': ['Apple, raw', 'Apple, raw', 'Apple, raw', "Milk, cow's, fluid, whole, NFS",
                       "Milk, cow's, fluid, whole, NFS", "Milk, cow's, fluid, whole, NFS"],
    'Image': ['a1.png', 'a2.png', 'a3.png', 'm1.png', 'm2.png', 'm3.png'],
    'Portion': ['1/4 fruit', '1/2 fruit', '1 fruit', '1/4 cup', '1-1/2 cups', '2 cups'],
    'PortionCode': [60813, 60813, 60813, 30000, 10205, 10205],
    'PortionSubCode': [0] * 6,
    'Multiplier': [0.25, 0.5, 1.0, 2.0, 1.5, 2.0],
    'PortionWeight': [182.0, 182.0, 182.0, 30.5, 244.0, 244.0],
    'Weight': [45.5, 91.0, 182.0, 61.0, 366.0, 488.0],
})


def asa24_results(answers):
    """Three labeled images (apple 1/2 fruit, milk 1-1/2 cups, milk 1/4 cup) and their answers."""
    return pd.DataFrame({
        'FoodCode': [63101000, 11111000, 11111000], 'Image': ['a2.png', 'm2.png', 'm1.png'],
        'Portion': ['1/2 fruit', '1-1/2 cups', '1/4 cup'], 'PortionCode': [60813, 10205, 30000],
        'PortionSubCode': [0, 0, 0], 'Multiplier': [0.5, 1.5, 2.0], 'PortionWeight': [182.0, 244.0, 30.5],
        'Weight': [91.0, 366.0, 61.0], 'Link': ['/img/a2.png', '/img/m2.png', '/img/m1.png'],
        'Size': ['Medium', 'Largest', 'Smallest'], 'GPTFoodDescription': ['apple', 'milk', 'milk'],
        'GPTFoodCode': answers})


class FakePortionVision:
    """Stands in for chagApp_openai.Vision: answers the shot and amount prompts."""

    def __init__(self, shot='1/2 fruit', amount='0.5'):
        self.prompts = []
        self.shot, self.amount = shot, amount

    def chat(self, prompt, image_path):
        self.prompts.append((prompt, image_path))
        return self.shot if 'choose the option' in prompt else self.amount


class TestC5PortionProtocol(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def processed(self):
        df = asa24_results(["['63101000']", "['11111000', '11112110']", "['11112110']"])
        df = rag_portion_size.add_food_code_common(df, ASA24_LINK)
        return rag_portion_size.process_dataframe(df, ASA24_LINK, rag_portion_size.inflect.engine())

    def test_labels_and_options(self):
        df = self.processed()
        self.assertEqual(df['LabelAmount'].tolist(), [0.5, 1.5, 0.25])  # '1-1/2' raised ValueError before
        self.assertEqual(df['LabelUnit'].tolist(), ['fruit', 'cup', 'cup'])
        # the options are the series of FoodCodeCommon, by Multiplier as in the original
        self.assertEqual(df.loc[0, 'PortionShot'], '1 fruit ,1/2 fruit ,1/4 fruit')
        self.assertEqual(df.loc[1, 'PortionShot'], '1/4 cup ,2 cups ,1-1/2 cups')
        self.assertEqual(df.loc[2, 'PortionShot'], '')
        self.assertEqual(df.loc[1, 'FC_Description'], "Milk, cow's, fluid, whole, not further specified subcategory assigned")
        self.assertTrue(pd.isna(df.loc[2, 'FC_Description']))

    def test_prompts_and_skipped_rows(self):
        df = self.processed()
        df['GPTPortionDescription'] = np.nan
        df['GPTPortionReason'] = np.nan
        llm = FakePortionVision()
        out = os.path.join(self.tmp.name, 'portion.csv')
        rag_portion_size.analyze_portions(df, llm, 'GPTPortionDescription', 'GPTPortionReason', df['PortionShot'],
                                          output_path=out, workers=2)
        # the third image has no FoodCodeCommon: not asked
        self.assertEqual(sorted(path for _, path in llm.prompts), ['/img/a2.png', '/img/m2.png'])
        prompt = dict((path, text) for text, path in llm.prompts)['/img/m2.png']
        self.assertIn("described as Milk, cow's, fluid, whole, not further specified subcategory assigned", prompt)
        self.assertIn('following choices: 1/4 cup ,2 cups ,1-1/2 cups.', prompt)
        self.assertEqual(pd.read_csv(out)['GPTPortionDescription'].tolist()[:2], ['1/2 fruit', '1/2 fruit'])
        # answered rows are not asked again
        rag_portion_size.analyze_portions(df, llm, 'GPTPortionDescription', 'GPTPortionReason', df['PortionShot'],
                                          output_path=out, workers=2)
        self.assertEqual(len(llm.prompts), 2)

    def test_main(self):
        paths = {name: os.path.join(self.tmp.name, f'{name}.csv') for name in ('results', 'link', 'output', 'portion')}
        asa24_results(["['63101000']", "['11111000']", np.nan]).to_csv(paths['results'], index=False)
        ASA24_LINK.to_csv(paths['link'], index=False)
        llm = FakePortionVision(shot='1-1/2 cups', amount='1.5')
        args = rag_portion_size.parse_args(['--results_path', paths['results'], '--image_link_path', paths['link'],
                                            '--output_path', paths['output'], '--portion_path', paths['portion']])
        with mock.patch.object(rag_portion_size, 'Vision', return_value=llm), \
                mock.patch.object(rag_portion_size.time, 'sleep'):
            rag_portion_size.main(args)
        saved = pd.read_csv(paths['portion'])
        self.assertEqual(saved['GPTPortionDescription'].tolist()[:2], ['1-1/2 cups', '1-1/2 cups'])
        self.assertEqual(saved['GPTPortionAmount'].tolist()[:2], [1.5, 1.5])
        self.assertTrue(pd.isna(saved.loc[2, 'GPTPortionDescription']))
        amount_prompts = [text for text, _ in llm.prompts if 'how many' in text]
        self.assertIn('how many fruit of the food are visible', amount_prompts[0])
        self.assertIn('how many cup of the food are visible', amount_prompts[1])



FOOD_WEIGHTS = pd.DataFrame({'Food Code': [63101000, 11111000, 11111000], 'Portion Code': [60813, 30000, 10205],
                             'Subcode': [0, 0, 0], 'Portion Weight': [182.0, 30.5, 244.0]})
NUTRITION = pd.DataFrame({'Food code': [63101000, 11111000], 'Main food description': ['Apple, raw', 'Milk, whole'],
                          'WWEIA Category number': [6002, 1002], 'WWEIA Category description': ['Apples', 'Milk, whole'],
                          'Energy (kcal)': [52.0, 61.0], 'Protein (g)': [0.26, 3.27], 'Total Fat (g)': [0.17, 3.2]})


class TestC6PortionToGrams(unittest.TestCase):

    def test_option_lookup(self):
        lookup = lambda code, text: nutrient_estimate.map_portion(ASA24_LINK, code, text)
        self.assertEqual(lookup(11111000.0, '1-1/2 cups'), (10205, 0, 1.5))
        self.assertEqual(lookup(11111000.0, ' "1/4 Cup." '), (30000, 0, 2.0))  # case, quotes, final period
        for code, text in ((11111000.0, '1 cup'), (11111000.0, 'About 1-1/2 cups'), (63101000.0, '2 cups'),
                           (np.nan, '1/4 cup'), (11111000.0, np.nan)):
            self.assertTrue(all(pd.isna(v) for v in lookup(code, text)), text)

    def test_amount_answers(self):
        parse = nutrient_estimate.parse_portion_amount
        self.assertEqual([parse(a) for a in ('1.5', '1/2', '1-1/2', '2 cups', 0.75)], [1.5, 0.5, 1.5, 2.0, 0.75])
        self.assertTrue(pd.isna(parse("I can't help to analyze this image.")))
        self.assertTrue(pd.isna(parse('none')))
        # R-C6-2: one non-negative number, with its unit; a thousands separator is read, not cut
        self.assertEqual([parse(a) for a in ('1 1/2 cups', '.5', '0', '2.', '1,000', '1,000.5 g', 3)],
                         [1.5, 0.5, 0.0, 2.0, 1000.0, 1000.5, 3.0])
        for answer in ('-2', '1,5', '12,34', '2-3 cups', '2 or 3', 'about 2', '1e309', 'inf', 'nan', '3/0', '2\nmaybe 3',
                       'I cannot determine whether there are 2 cups from this image.', -2.0, float('inf'), np.nan):
            self.assertTrue(pd.isna(parse(answer)), answer)
        grams = nutrient_estimate_mix.GRAMS
        self.assertEqual([parse(a, grams) for a in ('150', '150 g', '150g', '150 grams of rice')], [150.0] * 4)
        self.assertTrue(pd.isna(parse('1/2 cup', grams)))

    def test_weights_and_nutrients(self):
        df = pd.DataFrame({'FoodCodeCommon': [11111000.0, 11111000.0, 63101000.0, np.nan],
                           'GPTPortionDescription': ['1-1/2 cups', '1 quart', '1/2 fruit', np.nan],
                           'GPTPortionAmount': ['1.5', "I can't help to analyze this image.", '0.5', np.nan],
                           'LabelUnit': ['cup', 'cup', 'fruit', 'cup']})
        with mock.patch('builtins.print'):
            df = nutrient_estimate.estimate(df, FOOD_WEIGHTS, ASA24_LINK, NUTRITION, NUTRITION.columns[4:])
        self.assertEqual(df.loc[0, 'TotalWeight'], 366.0)  # 1.5 x 1 cup (244 g)
        self.assertAlmostEqual(df.loc[0, 'Energy (kcal)'], 61.0 * 3.66)
        self.assertEqual(df.loc[2, 'TotalWeight'], 91.0)
        self.assertAlmostEqual(df.loc[2, 'Protein (g)'], 0.26 * 0.91)
        # the answer is not an option, or there is no common code: no weight, no nutrients
        for i in (1, 3):
            self.assertTrue(pd.isna(df.loc[i, 'TotalWeight']))
            self.assertTrue(pd.isna(df.loc[i, 'Energy (kcal)']))
        # amount reading: 1.5 cups x 244 g per cup (from '1/4 cup', '1-1/2 cups' and '2 cups')
        self.assertEqual(df.loc[0, 'AmountWeight'], 366.0)
        self.assertEqual(df.loc[2, 'AmountWeight'], 91.0)
        self.assertTrue(pd.isna(df.loc[1, 'AmountWeight']))

    def test_gram_portion_code(self):
        # R-C6-1: PortionCode 98 is one gram (B4); FNDDS has no code 98, so its weight was NaN
        link = pd.DataFrame({'FoodCode': [24123120] * 2, 'Portion': ['6 pieces', '1 cup'], 'PortionCode': [98, 10049],
                             'PortionSubCode': 0, 'Multiplier': [270.0, 1.0], 'Weight': [270.0, 135.0]})
        weights = pd.DataFrame({'Food Code': [24123120], 'Portion Code': [10049], 'Subcode': [0], 'Portion Weight': [135.0]})
        nutrition = pd.DataFrame({'Food code': [24123120], 'Main food description': ['Chicken'], 'WWEIA Category number': [0],
                                  'WWEIA Category description': ['-'], 'Energy (kcal)': [200.0], 'Total Fat (g)': [10.0],
                                  'Carbohydrate (g)': [5.0], 'Protein (g)': [25.0]})
        df = pd.DataFrame({'FoodCode': [24123120], 'Size': ['Largest'], 'Portion': ['6 pieces'], 'Weight': [270.0],
                           'GPTFoodCode': ["['24123120']"], 'FoodCodeCommon': [24123120.0],
                           'GPTPortionDescription': ['6 pieces'], 'GPTPortionAmount': ['6'], 'LabelUnit': ['piece']})
        df = nutrient_estimate.estimate(df, weights, link, nutrition, nutrition.columns[4:])
        self.assertEqual(df.loc[0, 'TotalWeight'], 270.0)
        self.assertAlmostEqual(df.loc[0, 'Energy (kcal)'], 200.0 * 2.7)
        self.assertEqual(evaluate.asa24_mae(df, nutrition)['option']['Total']['Weight (g)'],
                         {'n': 1, 'per_dish': 0.0, 'per_unit': 0.0})
        self.assertEqual(evaluate.asa24_success_rates(df)['Total']['portion_option'], 1.0)

    def test_every_option_of_the_series(self):
        # R-C6-1: choosing the labeled option gives the reference grams of B4, for every row
        paths = [ROOT / 'df_image_link.csv', ROOT / 'FoodWeights.csv']
        if not all(path.exists() for path in paths):
            raise unittest.SkipTest('run code/asa24_proc.py first')
        link, weights = (pd.read_csv(path) for path in paths)
        grams = []
        for code, portion in zip(link['FoodCode'], link['Portion']):
            portion_code, subcode, multiplier = nutrient_estimate.map_portion(link, code, portion)
            grams.append(multiplier * nutrient_estimate.get_portion_weight(weights, code, portion_code, subcode))
        np.testing.assert_allclose(grams, link['Weight'])



NUTRIENT_VALUES = ROOT / 'FNDDS' / '2019-2020 FNDDS At A Glance - FNDDS Nutrient Values.xlsx'


class TestC7Nutrients(unittest.TestCase):

    def test_fndds_nutrient_table(self):
        if not NUTRIENT_VALUES.exists():
            raise unittest.SkipTest('run code/place_inputs.py first')
        df, columns = nutrient_estimate.load_nutrition(NUTRIENT_VALUES)
        self.assertEqual(list(df.columns[:4]), ['Food code', 'Main food description', 'WWEIA Category number',
                                                'WWEIA Category description'])
        self.assertEqual(len(columns), 65)  # paper.txt:151: l = 65 components
        self.assertEqual(len(df), 5624)
        self.assertTrue(df['Food code'].is_unique)
        for name in ('Energy (kcal)', 'Protein (g)', 'Carbohydrate (g)', 'Total Fat (g)'):
            self.assertIn(name, columns)
        # per 100 g x grams / 100 (paper.txt:151-160); whole milk, 1 cup = 244 g (looked up by hand)
        values = nutrient_estimate.get_nutrition_values(df, columns, 11111000, 244.0)
        self.assertAlmostEqual(values['Energy (kcal)'], 61 * 2.44)
        self.assertAlmostEqual(values['Protein (g)'], 3.27 * 2.44)
        self.assertAlmostEqual(values['Carbohydrate (g)'], 4.63 * 2.44)
        self.assertAlmostEqual(values['Total Fat (g)'], 3.20 * 2.44)



class TestC8Nutrition5k(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def test_food_code_answer_format(self):
        answer = 'Grilled chicken: 24198340, 24198350\nWhite rice: 56205000'
        chain, query_llm, base, code_llm = food_code_chain(code_answer=answer)
        n5k_chain = rag_food_code.setup_code_prompt_chain(
            MultiQueryRetriever.from_llm(retriever=base, llm=query_llm, prompt=rag_food_code.setup_retrieval_prompt()),
            code_llm, 'nutrition5k')
        image = os.path.join(self.tmp.name, 'rgb.png')
        Image.new('RGB', (64, 48)).save(image)
        n5k_chain.invoke({'question': 'chicken and rice', 'url_str': image})
        text = code_llm.received[-1][0].content[0]['text']
        self.assertIn("in the format 'food name: code, code; food name: code'", text)
        self.assertNotIn('Please provide only the eight-digit codes', text)
        chain.invoke({'question': 'apple', 'url_str': image})  # ASA24 keeps the original sentence
        self.assertIn('Please provide only the eight-digit codes', code_llm.received[-1][0].content[0]['text'])
        # stored as one line, as nutrient_estimate_mix.match_food_codes reads it
        df = results_table([image])
        rag_food_code.process_image_url(0, image, FakeVision('chicken and rice'), df,
                                        mock.Mock(invoke=lambda x: {'context': [], 'answer': answer}),
                                        os.path.join(self.tmp.name, 'r.csv'), dataset='nutrition5k')
        self.assertEqual(df.loc[0, 'GPTFoodCode'], 'Grilled chicken: 24198340, 24198350; White rice: 56205000')
        self.assertTrue(rag_food_code.has_food_code(df.loc[0, 'GPTFoodCode'], 'nutrition5k'))
        self.assertFalse(rag_food_code.has_food_code('No food here', 'nutrition5k'))

    def test_grams_prompt(self):
        self.assertEqual(rag_portion_size.food_names('Grilled chicken: 24198340, 24198350; White rice: 56205000'),
                         'Grilled chicken; White rice')
        self.assertTrue(pd.isna(rag_portion_size.food_names(np.nan)))
        prompt = rag_portion_size.create_prompt('Grilled chicken; White rice', 'grams', type='grams')
        self.assertIn('The image displays the following foods: Grilled chicken; White rice.', prompt)
        self.assertIn('how many grams of each food are visible in the image?', prompt)
        self.assertIn('"food: numerical value"', prompt)
        # no refusal sentence (E1); the estimate sentence of the user's decision after the second development run
        self.assertTrue(prompt.endswith('using the food names above. \n'
                                        'If you cannot determine the exact weight, still give your best estimate in grams.'))
        self.assertNotIn("I can't help", prompt)

    def test_food_items(self):
        # R-C8-1: two food code answers of E1 (runs/dev/nutrition5k_food_codes.csv, lines joined by '; ')
        leafy = 'Chicken or turkey, rice, and vegetables including carrots, broccoli, and/or dark-green leafy'
        e1 = ["I'm unable to identify specific foods or their codes from images. However, based on the context provided, "
              "here are some possible matches:; - Chicken or turkey with vegetables: 27345410, 27345010; If these don't "
              "match the image, you might need to provide more context or details.",
              "I can't identify or describe the contents of the image. However, based on the context provided, here are "
              f"potential matches:; - {leafy}; no sauce: 27345010; - {leafy}; cream sauce, white sauce, or mushroom sauce: "
              "27345410; If these don't match the image, please provide more details or context."]
        items = rag_portion_size.food_items
        self.assertEqual(items(e1[0]), [('Chicken or turkey with vegetables', [27345410, 27345010])])
        self.assertEqual(items(e1[1]), [(f'{leafy}; no sauce', [27345010]),
                                        (f'{leafy}; cream sauce, white sauce, or mushroom sauce', [27345410])])
        self.assertEqual(rag_portion_size.food_names(e1[0]), 'Chicken or turkey with vegetables')
        # two more E1 answers: the code list of the last food is kept whole (it lost its last code)
        self.assertEqual(items('almonds: 42101120, 42101130, 42101000; cauliflower: 99997535, 75214011, 75214027, 75107000'),
                         [('almonds', [42101120, 42101130, 42101000]), ('cauliflower', [99997535, 75214011, 75214027, 75107000])])
        self.assertEqual(items('Chicken or turkey: 27440110, 27442110, 27446400; green beans: 75205005, 75205044'),
                         [('Chicken or turkey', [27440110, 27442110, 27446400]), ('green beans', [75205005, 75205044])])
        self.assertEqual(items('x: 11111111, 222222222; y: 33333333'), [('x', [11111111]), ('y', [33333333])])
        # no space after the colon; a food without a valid code stays a food; a colon in the name
        self.assertEqual(items('rice: 11111111; chicken:22222222'), [('rice', [11111111]), ('chicken', [22222222])])
        self.assertEqual(items('Sauce: none; Rice: 56205000; Corn: 123456789'),
                         [('Sauce', []), ('Rice', [56205000]), ('Corn', [])])
        self.assertEqual(items('Beef taco filling: beef, cheese, tomato, taco sauce: 27515010, Rice: 56205000'),
                         [('Beef taco filling: beef, cheese, tomato, taco sauce', [27515010]), ('Rice', [56205000])])
        self.assertEqual(items('1. Rice: 56205000 (white); **rice**: 56205010'), [('Rice', [56205000, 56205010])])
        self.assertEqual(items(np.nan), [])
        self.assertTrue(pd.isna(rag_portion_size.food_names('Sauce: none')))  # no food with a code: no grams question

    def test_empty_item_is_no_food(self):
        # ';;' (an answer line that ended with ';', joined with '; ') left ';' in the next name; a
        # food code answer of runs/dev-grams-estimate/ (dish_1563307575)
        answer = 'beef and vegetables: 27416450, 27410210;; spinach: 72125220, 72125218, 72125211, 72125221, 72125217'
        self.assertEqual(rag_portion_size.food_items(answer),
                         [('beef and vegetables', [27416450, 27410210]),
                          ('spinach', [72125220, 72125218, 72125211, 72125221, 72125217])])
        self.assertEqual(rag_portion_size.food_names(answer), 'beef and vegetables; spinach')
        self.assertEqual(rag_portion_size.food_items('Sauce: none;; Rice: 56205000'), [('Sauce', []), ('Rice', [56205000])])
        # the grams of that dish's answer now meet both names
        weights = nutrient_estimate_mix.match_food_codes(
            answer, nutrient_estimate_mix.parse_food_items('beef and vegetables: 150 grams  \nspinach: 50 grams'))
        self.assertEqual([weight for _, weight in weights.values()], [150.0, 50.0])

    def test_lost_foods_are_failures(self):
        # R-C8-1: 'chicken:22222222' was dropped, so the dish was complete with rice only
        nutrition = pd.DataFrame({'Food code': [11111111, 22222222], 'a': 0, 'b': 0, 'c': 0, 'Energy (kcal)': [100.0, 200.0]})
        columns = nutrition.columns[4:]
        df = pd.DataFrame({'GPTFoodCode': ['rice: 11111111; chicken:22222222'] * 2 + ['rice: 11111111; sauce: none'],
                           'GPTAmount': ['rice: 100\nchicken: 100', 'rice: 100', 'rice: 100\nsauce: 20']})
        df['GPTAmountWeight'] = df['GPTAmount'].apply(nutrient_estimate_mix.parse_food_items)
        df[columns] = np.nan
        with mock.patch('builtins.print'):
            df = nutrient_estimate_mix.process_results(df, nutrition, columns)
        self.assertEqual(df['IngredientNum'].tolist(), [2, 2, 2])
        self.assertEqual(df['WeightError'].tolist(), [0, 1, 0])
        self.assertEqual(df['FoodCodeError'].tolist(), [0, 0, 1])
        self.assertEqual(df.loc[0, 'GPTWeight'], 200.0)
        self.assertAlmostEqual(df.loc[0, 'Energy (kcal)'], 300.0)
        # D6 and D7: only the first dish is complete (with chicken dropped, the first two were, rice alone)
        for column in evaluate.NUTRIENTS:
            df[column] = df.get(column, np.nan)
        df['total_mass'] = 200.0
        for label in ('total_calories', 'total_fat', 'total_carbs', 'total_protein'):
            df[label] = 1.0
        rates = evaluate.nutrition5k_success_rates(df)
        self.assertEqual((rates['portion_per_dish'], rates['portion_per_food_item'], rates['food_items']), (2 / 3, 5 / 6, 6))
        self.assertEqual(evaluate.nutrition5k_mae(df)['complete']['Weight (g)'], {'n': 1, 'per_dish': 0.0, 'per_unit': 0.0})

    def test_food_name_with_a_colon(self):
        # R-C8-1: the one FNDDS name with a colon, read the same in the codes and the grams answers
        name = 'Beef taco filling: beef, cheese, tomato, taco sauce'
        nutrition = pd.DataFrame({'Food code': [27515010], 'a': 0, 'b': 0, 'c': 0, 'Energy (kcal)': [150.0]})
        df = pd.DataFrame({'GPTFoodCode': [f'{name}: 27515010'], 'GPTAmount': [f'{name}: 150']})
        self.assertEqual(rag_portion_size.food_names(df.loc[0, 'GPTFoodCode']), name)
        df['GPTAmountWeight'] = df['GPTAmount'].apply(nutrient_estimate_mix.parse_food_items)
        df[nutrition.columns[4:]] = np.nan
        df = nutrient_estimate_mix.process_results(df, nutrition, nutrition.columns[4:])
        self.assertEqual(df.loc[0, ['IngredientNum', 'WeightError', 'FoodCodeError', 'GPTWeight']].tolist(), [1, 0, 0, 150.0])
        self.assertAlmostEqual(df.loc[0, 'Energy (kcal)'], 225.0)

    def test_grams_step(self):
        path = os.path.join(self.tmp.name, 'dishes.csv')
        pd.DataFrame({'dish_id': ['dish_1', 'dish_2'], 'Link': ['/img/1.png', '/img/2.png'],
                      'GPTFoodCode': ['Grilled chicken: 24198340; White rice: 56205000', np.nan]}).to_csv(path, index=False)
        llm = FakePortionVision(amount='Grilled chicken: 120.5\nWhite rice: 150')
        args = rag_portion_size.parse_args(['--results_path', path, '--portion_path', path, '--dataset', 'nutrition5k'])
        with mock.patch.object(rag_portion_size, 'Vision', return_value=llm), mock.patch.object(rag_portion_size.time, 'sleep'):
            rag_portion_size.main_nutrition5k(args)
        saved = pd.read_csv(path)
        self.assertEqual(len(llm.prompts), 1)  # the dish without food codes is not asked
        self.assertEqual(saved.loc[0, 'GPTAmount'], 'Grilled chicken: 120.5\nWhite rice: 150')
        self.assertTrue(pd.isna(saved.loc[1, 'GPTAmount']))

    def test_parse_grams(self):
        parse = nutrient_estimate_mix.parse_food_items
        with mock.patch('builtins.print'):
            self.assertEqual(parse('Grilled chicken: 120.5\nWhite rice: 150 g\nSauce: none'),
                             {'Grilled chicken': 120.5, 'White rice': 150.0, 'Sauce': parse('x: none')['x']})
        self.assertTrue(pd.isna(parse('Sauce: none')['Sauce']))
        # R-C6-2: -20 was read as 20 g and 1,000 as 1 g
        parsed = parse('Rice: -20\nBeans: 1,000\nCorn: 1/2 cup')
        self.assertTrue(pd.isna(parsed['Rice']) and pd.isna(parsed['Corn']))
        self.assertEqual(parsed['Beans'], 1000.0)
        self.assertTrue(pd.isna(parse("I can't help to analyze this image.\nToo dark")))
        self.assertTrue(pd.isna(parse(np.nan)))

    def test_estimates_after_a_disclaimer(self):
        # The user's decision after the third development run: the whole grams answer is read,
        # not its first paragraph (split('\n\n')[0]); an answer of runs/dev-grams-estimate/ (dish_1562184628)
        nutrition = pd.DataFrame({'Food code': [21601000, 21601010, 27211300], 'a': 0, 'b': 0, 'c': 0,
                                  'Energy (kcal)': [500.0, 520.0, 200.0]})
        columns = nutrition.columns[4:]
        df = pd.DataFrame({
            'GPTFoodCode': ["I can't identify or describe the contents of the image. However, based on the context provided, "
                            "here are the relevant food codes:; - Bacon: 21601000, 21601010; - Beef roast: 27211300"],
            'GPTAmount': ["I'm unable to determine the exact weight, but here is an estimate:\n\nBacon: 50 grams  \n"
                          "Beef roast: 70 grams"]})
        df['GPTAmountWeight'] = df['GPTAmount'].apply(nutrient_estimate_mix.parse_food_items)
        df[columns] = np.nan
        with mock.patch('builtins.print'):
            df = nutrient_estimate_mix.process_results(df, nutrition, columns)
        self.assertEqual(df.loc[0, ['IngredientNum', 'WeightError', 'FoodCodeError', 'GPTWeight']].tolist(), [2, 0, 0, 120.0])
        self.assertAlmostEqual(df.loc[0, 'Energy (kcal)'], 510.0 * 0.5 + 200.0 * 0.7)
        # a refusal still is one, with its reason after a blank line
        self.assertTrue(pd.isna(nutrient_estimate_mix.parse_food_items("I can't help to analyze this image.\n\nToo dark")))

    def test_dish_nutrition(self):
        nutrition = pd.DataFrame({'Food code': [24198340, 24198350, 56205000], 'a': [0] * 3, 'b': [0] * 3, 'c': [0] * 3,
                                  'Energy (kcal)': [190.0, 210.0, 130.0], 'Protein (g)': [30.0, 28.0, 2.7]})
        columns = nutrition.columns[4:]
        df = pd.DataFrame({
            'GPTFoodCode': ['Grilled chicken: 24198340, 24198350; White rice: 56205000',
                            'Grilled chicken: 24198340; Mystery: 99999999', np.nan,
                            'Grilled chicken: 24198340; White rice: 56205000'],
            'GPTAmount': ['Grilled chicken: 120.5\nWhite rice: 150', 'Grilled chicken: 100\nMystery: 50', np.nan,
                          "I can't help to analyze this image.\nToo dark"]})
        df['GPTAmountWeight'] = df['GPTAmount'].apply(nutrient_estimate_mix.parse_food_items)
        df[columns] = np.nan
        with mock.patch('builtins.print'):
            df = nutrient_estimate_mix.process_results(df, nutrition, columns)
        # two candidate codes of one food: their mean (nutrient_estimate_mix.py); foods summed
        self.assertAlmostEqual(df.loc[0, 'Energy (kcal)'], 200.0 * 1.205 + 130.0 * 1.5)
        self.assertAlmostEqual(df.loc[0, 'GPTWeight'], 270.5)
        self.assertEqual(df.loc[0, ['FoodCodeError', 'WeightError', 'IngredientNum']].tolist(), [0, 0, 2])
        # a code missing from FNDDS is counted (it added weight but no nutrients)
        self.assertEqual(df.loc[1, 'FoodCodeError'], 1)
        self.assertAlmostEqual(df.loc[1, 'Energy (kcal)'], 190.0)
        # no food code; no grams answer
        self.assertEqual(df.loc[2, 'IngredientNum'], 0)
        self.assertTrue(pd.isna(df.loc[2, 'Energy (kcal)']))
        self.assertEqual(df.loc[3, 'WeightError'], 2)
        self.assertTrue(pd.isna(df.loc[3, 'GPTWeight']))



def published(path):
    """A file as released (the first commit, v1.0-paper)."""
    try:
        return subprocess.run(['git', 'show', f'5946365:{path}'], cwd=ROOT, capture_output=True, text=True,
                              check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        raise unittest.SkipTest('needs the git history')


# E1, the user's decision (b): the last sentence of the released description and portion prompts
REFUSAL_SENTENCE = re.compile(r"\s*If you can(?:'t provide assistance with this image|not analyze the image), "
                              r".*I can't help to analyze this image\..* on a new line\.$", re.S)


class TestPublishedPrompts(unittest.TestCase):
    """The prompt texts are the released ones, apart from the registered C4 and C8 changes and
    the refusal sentence dropped after E1."""

    def test_portion_prompts(self):
        source = published('code/rag_portion_size.py')
        original = {}
        exec(source[source.index('def create_prompt'):source.index('def update_dataframe')], original)
        for kind in ('shot', 'amount'):
            released = original['create_prompt']('Apple, raw', '1 cup ,2 cups', kind)
            self.assertRegex(released, REFUSAL_SENTENCE)
            self.assertEqual(rag_portion_size.create_prompt('Apple, raw', '1 cup ,2 cups', kind),
                             REFUSAL_SENTENCE.sub('', released))

    def test_food_code_prompts(self):
        source = published('code/rag_food_code.py')
        original = {'SystemMessage': lambda content: content, 'HumanMessage': lambda content: content,
                    'PromptTemplate': rag_food_code.PromptTemplate}
        exec(source[source.index('def get_messages_from_url'):source.index('def configure_retrievers')], original)
        system, human = original['get_messages_from_url']('https://img.invalid/0.png')
        new_system, new_human = rag_food_code.get_messages_from_url('https://img.invalid/0.png')
        self.assertEqual(new_system.content, system)
        self.assertRegex(human[0]['text'], REFUSAL_SENTENCE)
        self.assertEqual(new_human.content[0], {**human[0], 'text': REFUSAL_SENTENCE.sub('', human[0]['text'])})
        self.assertEqual(rag_food_code.setup_retrieval_prompt().template, original['setup_retrieval_prompt']().template)
        # C4: the image is attached instead of written as {url_str}; the rest of the text is unchanged
        start = source.index('template = """Could you identify') + len('template = """')
        code = source[start:source.index('"""', start)]
        chain, *_, code_llm = food_code_chain()
        chain.invoke({'question': 'apple', 'url_str': 'https://img.invalid/0.png'})
        sent = code_llm.received[0][0].content[0]['text']
        context = sent[sent.index('provided: ') + len('provided: '):sent.index('?\n')]
        self.assertEqual(sent, code.replace('the given food image: {url_str},', 'the given food image,')
                         .replace('{context}', context))


if __name__ == '__main__':
    unittest.main()
