"""D8: a whole run on a small offline world; inference sees images and retrieved FNDDS rows only.

run_experiment.run drives every step with the API mocked. Each request is classified by its
prompt; no reference label may appear in any of them, except in the registered conditions of
the paper protocol (C5, D1): the portion requests of images whose answer includes the labeled
code carry that code's description, its portion series and the labeled unit.
"""
import base64
import hashlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import httpx
import numpy as np
import pandas as pd
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'code'))

import api_log  # noqa: E402
import chagApp_openai  # noqa: E402
import config  # noqa: E402
import rag_food_code  # noqa: E402
import run_experiment  # noqa: E402

FOODS = {11111000: 'milk, whole', 11112110: 'milk, reduced fat (2%)', 63101000: 'apple, raw',
         24198340: 'chicken breast, grilled', 56205000: 'rice, white, cooked'}
NUTRIENTS = {11111000: (61, 3.27, 4.63, 3.20), 11112110: (50, 3.30, 4.80, 1.90), 63101000: (61, 0.17, 14.8, 0.15),
             24198340: (165, 31.0, 0.0, 3.6), 56205000: (130, 2.7, 28.2, 0.3)}
# reference labels that inference must not see
ASA24_LABELS = [('Milk, cow\'s, fluid, whole', '1-1/2 cups', 366.0, 'Largest', 11111000),
                ('Apple, raw, with skin (label)', '1/2 fruit', 91.0, 'Medium', 63101000)]
N5K_LABELS = [('dish_1', 312.0, 432.5, 'roasted kohlrabi, farro'), ('dish_2', 207.0, 288.75, 'quinoa, pomelo')]


class FakeTokenizer:
    def encode(self, text, **kwargs):
        return [int(hashlib.md5(word.encode()).hexdigest(), 16) % 5000 for word in text.lower().split()] or [0]


def vector(tokens):
    v = np.zeros(16)
    for t in tokens:
        v[t % 16] += 1
    return (v / (np.linalg.norm(v) or 1)).tolist()


class World:
    """Files of a small run, the mocked API and the requests it received."""

    def __init__(self, tmp):
        self.tmp = Path(tmp)
        self.requests = []
        images = {}
        (self.tmp / 'images').mkdir()
        for i, name in enumerate(['milk', 'apple', 'dish_1', 'dish_2']):
            images[name] = str(self.tmp / 'images' / f'{name}.png')
            Image.new('RGB', (300 + i, 200), (40 * i, 100, 200)).save(images[name])
        self.image_of = {chagApp_openai.image_url(path): name for name, path in images.items()}
        foods = pd.DataFrame({'Food code': list(FOODS), 'Food description': [
            f'The image shows the food category of {d}.' for d in FOODS.values()]})
        foods.to_csv(self.tmp / 'foods.csv', index=False)
        nutrition = pd.DataFrame({'Food code': list(FOODS), 'Main food description': [d.capitalize() for d in FOODS.values()],
                                  'WWEIA Category number': 0, 'WWEIA Category description': '-',
                                  'Energy (kcal)': [n[0] for n in NUTRIENTS.values()],
                                  'Protein (g)': [n[1] for n in NUTRIENTS.values()],
                                  'Carbohydrate (g)': [n[2] for n in NUTRIENTS.values()],
                                  'Total Fat (g)': [n[3] for n in NUTRIENTS.values()]})
        nutrition.to_excel(self.tmp / 'nutrition.xlsx', sheet_name='FNDDS Nutrient Values', startrow=1, index=False)
        pd.DataFrame({'Food Code': [11111000, 11111000, 11111000, 11112110, 11112110, 63101000, 63101000],
                      'Seq Num': [1, 2, 3, 1, 2, 1, 2], 'Portion Code': [10205, 30000, 90000, 10205, 30000, 62015, 61238],
                      'Subcode': 0, 'Portion Weight': [244.0, 30.5, 244.0, 244.0, 30.5, 149.0, 182.0],
                      'Portion Description': ['1 cup', '1 fl oz', 'Quantity not specified', '1 cup', '1 fl oz', '1 small',
                                              '1 medium']}).to_csv(self.tmp / 'weights.csv', index=False)
        pd.DataFrame({'FoodCode': [11111000] * 3 + [63101000] * 3,
                      'FC_Description': [ASA24_LABELS[0][0]] * 3 + [ASA24_LABELS[1][0]] * 3,
                      'Category': 'X', 'Image': ['m1', 'milk', 'm3', 'a1', 'apple', 'a3'],
                      'Portion': ['1/4 cup', '1-1/2 cups', '2 cups', '1/4 fruit', '1/2 fruit', '1 fruit'],
                      'PortionCode': [10205] * 3 + [60813] * 3, 'PortionSubCode': 0,
                      'Multiplier': [0.25, 1.5, 2.0, 0.25, 0.5, 1.0], 'PortionWeight': [244.0] * 3 + [182.0] * 3,
                      'Weight': [61.0, 366.0, 488.0, 45.5, 91.0, 182.0], 'Link': ''}).to_csv(self.tmp / 'link.csv', index=False)
        pd.DataFrame({'FoodCode': [l[4] for l in ASA24_LABELS], 'Image': ['milk', 'apple'],
                      'Portion': [l[1] for l in ASA24_LABELS], 'PortionCode': [10205, 60813], 'PortionSubCode': 0,
                      'Multiplier': [1.5, 0.5], 'PortionWeight': [244.0, 182.0], 'Weight': [l[2] for l in ASA24_LABELS],
                      'Link': [images['milk'], images['apple']], 'Size': [l[3] for l in ASA24_LABELS],
                      'GPTFoodDescription': np.nan, 'GPTFoodCode': np.nan}).to_csv(self.tmp / 'asa24.csv', index=False)
        pd.DataFrame({'dish_id': [l[0] for l in N5K_LABELS], 'total_calories': [l[2] for l in N5K_LABELS],
                      'total_mass': [l[1] for l in N5K_LABELS], 'total_fat': [12.5, 9.25], 'total_carbs': [40.5, 30.25],
                      'total_protein': [35.5, 15.25], 'ingredients': [l[3] for l in N5K_LABELS],
                      'sorted_ingredients': [l[3] for l in N5K_LABELS], 'Link': [images['dish_1'], images['dish_2']],
                      'GPTFoodDescription': np.nan, 'GPTFoodCode': np.nan}).to_csv(self.tmp / 'n5k.csv', index=False)

    def answer(self, body):
        """What the model says, by the kind of request."""
        messages = body['messages']
        text = ' '.join(part['text'] for m in messages for part in
                        (m['content'] if isinstance(m['content'], list) else [{'text': m['content']}]) if 'text' in part)
        image = next((self.image_of[part['image_url']['url']] for m in messages if isinstance(m['content'], list)
                      for part in m['content'] if part.get('type') == 'image_url'), None)
        if 'Could you name the food' in text:
            return 'description', image, {'milk': 'A glass of milk', 'apple': 'A sliced apple',
                                          'dish_1': 'Grilled chicken with white rice', 'dish_2': 'A bowl'}[image]
        if 'generate five' in text:
            return 'queries', None, 'milk drink\nfruit apple\nchicken rice'
        if 'eight-digit food code' in text:
            return 'food code', image, {'milk': '11111000', 'apple': '11112110',
                                        'dish_1': 'Grilled chicken: 24198340; White rice: 56205000',
                                        'dish_2': 'No appropriate food codes found from the context information.'}[image]
        if 'following foods' in text:
            return 'grams', image, 'Grilled chicken: 120\nWhite rice: 150'
        kind = 'protocol' if 'described as Milk, cow' in text or 'described as Apple, raw, with skin' in text else 'end to end'
        if 'choose the option' in text:
            return f'{kind} shot', image, '1-1/2 cups' if kind == 'protocol' else '1 cup'
        return f'{kind} amount', image, '1.5'

    def handler(self, request):
        body = json.loads(request.content)
        if request.url.path.endswith('/embeddings'):
            data = [{'object': 'embedding', 'index': i, 'embedding': vector(tokens)} for i, tokens in enumerate(body['input'])]
            return httpx.Response(200, json={'object': 'list', 'model': 'text-embedding-3-large', 'data': data,
                                             'usage': {'prompt_tokens': 3, 'total_tokens': 3}})
        kind, image, content = self.answer(body)
        self.requests.append((kind, image, body))
        return httpx.Response(200, json={
            'id': 'chatcmpl-1', 'object': 'chat.completion', 'created': 0, 'model': 'gpt-4o-2024-08-06',
            'choices': [{'index': 0, 'finish_reason': 'stop', 'message': {'role': 'assistant', 'content': content}}],
            'usage': {'prompt_tokens': 100, 'completion_tokens': 10, 'total_tokens': 110}})


def texts(body):
    """The text of a request, without its images."""
    out = []
    for m in body['messages']:
        for part in (m['content'] if isinstance(m['content'], list) else [{'type': 'text', 'text': m['content']}]):
            if part.get('type') == 'text':
                out.append(part['text'])
    return '\n'.join(out)


class TestD8NoLabelsInInference(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        world = cls.world = World(cls.tmp.name)
        with open(world.tmp / '.env', 'w') as f:
            f.write('OPENAI_API_KEY=sk-test\n')
        client = lambda: api_log.openai_client(transport=httpx.MockTransport(world.handler))
        patches = [mock.patch.object(config, 'ENV_PATH', str(world.tmp / '.env')),
                   mock.patch.object(config, 'API_LOG_PATH', str(world.tmp / 'api.jsonl')),
                   mock.patch.object(rag_food_code, 'openai_client', client),
                   mock.patch.object(chagApp_openai, 'openai_client', client),
                   mock.patch('tiktoken.encoding_for_model', return_value=FakeTokenizer()),
                   mock.patch.object(run_experiment, 'SPLITS', {'tiny': (str(world.tmp / 'asa24.csv'), str(world.tmp / 'n5k.csv'))}),
                   mock.patch.object(run_experiment, 'IMAGE_LINK_CSV', str(world.tmp / 'link.csv')),
                   mock.patch.object(run_experiment, 'FOOD_WEIGHTS_CSV', str(world.tmp / 'weights.csv')),
                   mock.patch.object(run_experiment, 'NUTRITION_XLSX', str(world.tmp / 'nutrition.xlsx')),
                   mock.patch('time.sleep')]
        for patch in patches:
            patch.start()
        try:
            cls.run_dir = world.tmp / 'run'
            cls.usage = run_experiment.run('tiny', str(cls.run_dir), workers=2, foods_csv=str(world.tmp / 'foods.csv'),
                                           index_dir=str(world.tmp / 'index'))
        finally:
            for patch in patches:
                patch.stop()

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def kinds(self, image):
        return sorted(kind for kind, i, _ in self.world.requests if i == image)

    def test_requests_of_each_image(self):
        # milk: right code, so the protocol portion step runs; apple: wrong code, so it does not
        self.assertEqual(self.kinds('milk'), ['description', 'end to end amount', 'end to end shot', 'food code',
                                              'protocol amount', 'protocol shot'])
        self.assertEqual(self.kinds('apple'), ['description', 'end to end amount', 'end to end shot', 'food code'])
        self.assertEqual(self.kinds('dish_1'), ['description', 'food code', 'grams'])
        self.assertEqual(self.kinds('dish_2'), ['description'] * 5 + ['food code'] * 5)  # five passes, then a failure

    def test_no_label_in_any_request(self):
        labels = ['366', '91', *[str(v) for l in N5K_LABELS for v in l[1:3]], 'kohlrabi', 'farro', 'quinoa', 'pomelo',
                  'milk.png', 'apple.png', 'dish_1', 'dish_2', str(self.world.tmp / 'images')]
        for kind, image, body in self.world.requests:
            text = texts(body)
            for label in labels:
                self.assertNotIn(label, text, (kind, image))

    def test_protocol_conditions_only_where_registered(self):
        asa24_labels = [l[0] for l in ASA24_LABELS] + [l[1] for l in ASA24_LABELS]
        for kind, image, body in self.world.requests:
            text = texts(body)
            if kind.startswith('protocol'):
                self.assertEqual(image, 'milk')  # only the image whose answer includes the labeled code
                continue
            for label in asa24_labels:
                self.assertNotIn(label, text, (kind, image))
            if kind in ('description', 'queries'):
                for code in FOODS:
                    self.assertNotIn(str(code), text, (kind, image))
            if kind == 'food code':  # codes only as retrieved FNDDS rows
                outside = text.split('considering only the context provided: ')[0] + text.split('?\n', 1)[1]
                self.assertNotRegex(outside, r'\d{8}')

    def test_images_are_256(self):
        for kind, image, body in self.world.requests:
            for m in body['messages']:
                for part in (m['content'] if isinstance(m['content'], list) else []):
                    if part.get('type') == 'image_url':
                        data = base64.b64decode(part['image_url']['url'].split(',', 1)[1])
                        self.assertEqual(Image.open(io.BytesIO(data)).size, (256, 256))

    def test_run_outputs(self):
        metrics = json.loads((self.run_dir / 'metrics.json').read_text())
        option = metrics['asa24']['mae_protocol']['option']['Total']['Weight (g)']
        self.assertEqual(option, {'n': 1, 'per_dish': 0.0, 'per_unit': 0.0})  # milk: 1-1/2 cups chosen
        end_to_end = metrics['asa24']['mae_end_to_end']['Total']
        self.assertEqual(end_to_end['success_rate'], 1.0)  # 1.5 cups of whole milk / of 2% milk for the apple
        self.assertEqual(end_to_end['Weight (g)']['per_dish'], (0 + abs(366 - 91)) / 2)
        self.assertEqual(metrics['asa24']['success_rates']['Total']['nutrients'], 0.5)
        self.assertEqual(metrics['nutrition5k']['success_rates']['food_code_per_dish'], 0.5)
        self.assertEqual(metrics['nutrition5k']['mae']['complete']['Weight (g)'], {'n': 1, 'per_dish': 42.0, 'per_unit': 42.0 / 312})
        cost = json.loads((self.run_dir / 'cost.json').read_text())
        chats = len(self.world.requests)
        self.assertEqual(cost['run']['completion_tokens'], 10 * chats)
        self.assertGreater(cost['run']['usd'], 0)
        run_config = json.loads((self.run_dir / 'config.json').read_text())
        self.assertEqual(run_config['models_served'], ['gpt-4o-2024-08-06', 'text-embedding-3-large'])
        self.assertEqual(run_config['images'], {'asa24': 2, 'nutrition5k': 2})
        for path in self.run_dir.iterdir():
            self.assertNotIn('sk-test', path.read_text(errors='ignore'), path.name)


if __name__ == '__main__':
    unittest.main()
