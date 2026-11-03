"""Synthetic-only offline Q/D stage contract tests."""
from copy import deepcopy
import base64
from io import BytesIO
import json
from pathlib import Path
import sys
import tempfile
import unittest

from PIL import Image
BASE = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(BASE / name) for name in
                ('src', 'round8/src', 'round7/src', 'round10', 'round11')]
from paired_stage_pipeline import PairedStagePipeline
from opt_pipeline import ContractError


class PairedStageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.image = Path(self.tmp.name) / 'synthetic.png'
        Image.new('RGB', (17, 31), 'red').save(self.image)
        self.catalog = {'foods': {code: {'description': text,
            'density': dict(energy=100, fat=2, carbs=20, protein=4)}
            for code, text in [('12345678', 'rice'), ('12345679', 'other rice'),
                               ('22345678', 'beans')]}}
        self.identity = {'status': 'ok', 'items': [dict(item_id='i1', description='rice',
            broad_query='rice', region_ids=['r1'], primary_code='12345678',
            alternative_codes=['12345679'])],
            'candidates': {'i1': ['12345678', '12345679']},
            'final_codes': ['12345678', '12345679']}
        self.q = json.dumps({'total_grams': 240, 'items': [{'item_id': 'i1', 'ratio': 2}]})
        self.d = json.dumps({'items': [{'item_id': 'i1', 'density_code': '12345679'}]})
        self.calls = []

    def pipeline(self, answers):
        responses = iter(answers)
        def chat(messages):
            self.calls.append(deepcopy(messages))
            return next(responses)
        return PairedStagePipeline(chat, None, self.catalog, None)

    def run_stage(self, kind, answers, dataset='asa24'):
        pipeline = self.pipeline(answers)
        return getattr(pipeline, kind + '_intervention')(self.image, self.identity, dataset)

    def test_native_quantity_and_binding_without_mutation(self):
        before = deepcopy((self.identity, self.catalog))
        value = self.run_stage('quantity', [self.q])
        self.assertEqual(value['status'], 'native')
        self.assertEqual(value['value']['items'][0]['grams'], 240)
        self.assertEqual(value['stages'][0]['attempts'][0]['raw'], self.q)
        self.assertEqual((self.identity, self.catalog), before)
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(len(value['fixed_source_sha256']), 64)

    def test_quantity_normalizes_ratios_for_nutrition5k(self):
        self.identity['items'].append(dict(item_id='i2', description='beans', broad_query='beans',
            region_ids=['r2'], primary_code='22345678', alternative_codes=[]))
        self.identity['candidates']['i2'] = ['22345678']
        self.identity['final_codes'] = ['12345678', '22345678']
        raw = json.dumps({'total_grams': 240, 'items': [dict(item_id='i2', ratio=3), dict(item_id='i1', ratio=1)]})
        result = self.run_stage('quantity', [raw], 'nutrition5k')
        self.assertEqual([r['grams'] for r in result['value']['items']], [60, 180])

    def test_density_chooses_one_fixed_code(self):
        result = self.run_stage('density', [self.d])
        self.assertEqual(result['value'], json.loads(self.d))
        self.assertNotIn('prediction', result)

    def test_structural_repair_once_and_failure(self):
        result = self.run_stage('quantity', ['{}', self.q])
        self.assertEqual(result['status'], 'repaired')
        self.assertTrue(result['repaired'])
        self.assertIn('FORMAT only', self.calls[-1][-1]['content'])
        self.calls.clear()
        result = self.run_stage('density', ['{}', '{}', self.d])
        self.assertEqual(len(self.calls), 2)
        self.assertEqual(result['status'], 'failed')
        self.assertIsNone(result['value'])
        self.assertIsNone(result['parsed_sha256'])
        self.assertEqual(len(result['stages'][0]['attempts']), 2)

    def test_response_contract_errors_do_not_escape_repair(self):
        cases = [('quantity', '{"total_grams":NaN,"items":[]}'),
                 ('quantity', '{"total_grams":2,"items":[{"item_id":"unknown","ratio":1}]}'),
                 ('quantity', '{"total_grams":2,"items":[{"item_id":"i1","ratio":1,"extra":4}]}'),
                 ('density', '{"items":[{"item_id":"i1","density_code":"22345678"}]}'),
                 ('density', '{"items":[{"item_id":"unknown","density_code":"12345678"}]}')]
        for kind, raw in cases:
            with self.subTest(raw=raw):
                self.calls.clear()
                result = self.run_stage(kind, [raw, raw])
                self.assertEqual(result['status'], 'failed')
                self.assertEqual(len(self.calls), 2)
                self.assertTrue(result['stages'][0]['attempts'][0]['error'].startswith('paired_'))

    def test_invalid_identity_fails_before_chat_or_image_read(self):
        original = deepcopy(self.identity)
        changes = [lambda i: i.update(final_codes=[]),
                   lambda i: i['candidates'].update(i1=['22345678']),
                   lambda i: i['items'][0].update(region_ids=['r1', 'r1']),
                   lambda i: i['items'][0].update(primary_code='99999999'),
                   lambda i: i.update(items=None)]
        for change in changes:
            with self.subTest(change=change):
                self.identity = deepcopy(original)
                change(self.identity)
                with self.assertRaises(ContractError):
                    self.pipeline([]).quantity_intervention('/nonexistent', self.identity, 'asa24')
        self.assertEqual(self.calls, [])

    def test_poison_metadata_projected_away_and_square256(self):
        poison = 'TARGET_POISON_DO_NOT_SEND'
        self.identity['reference_weight'] = poison
        self.catalog['foods']['12345678']['true_code'] = poison
        before = deepcopy((self.identity, self.catalog))
        result = self.run_stage('quantity', [self.q])
        self.assertNotIn(poison, json.dumps(self.calls))
        self.assertNotIn(poison, json.dumps(result['source_binding']))
        self.assertEqual((self.identity, self.catalog), before)
        image = self.calls[0][1]['content'][1]['image_url']['url']
        with Image.open(BytesIO(base64.b64decode(image.split(',')[1]))) as encoded:
            self.assertEqual(encoded.size, (256, 256))
        self.assertEqual(result['image_mode'], 'square256')

    def test_disjoint_items_and_both_dataset_density_contract(self):
        self.identity['items'].append(dict(item_id='i2', description='beans', broad_query='beans',
            region_ids=['r1'], primary_code='22345678', alternative_codes=[]))
        self.identity['candidates']['i2'] = ['22345678']
        self.identity['final_codes'] = ['12345678', '22345678']
        with self.assertRaises(ContractError):
            self.run_stage('density', [], 'nutrition5k')
        self.assertEqual(self.calls, [])
        self.identity['items'][1]['region_ids'] = ['r2']
        raw = json.dumps({'items': [dict(item_id='i1', density_code='12345679'),
                                   dict(item_id='i2', density_code='22345678')]})
        self.assertEqual(self.run_stage('density', [raw], 'nutrition5k')['status'], 'native')

    def test_public_methods_have_only_blind_inputs(self):
        import inspect
        for name in ('quantity_intervention', 'density_intervention'):
            self.assertEqual(list(inspect.signature(getattr(PairedStagePipeline, name)).parameters),
                             ['self', 'image_path', 'identity', 'dataset'])

    def test_provider_failure_propagates_without_retry(self):
        def chat(messages):
            self.calls.append(messages)
            raise RuntimeError('synthetic_provider_stop')
        pipeline = PairedStagePipeline(chat, None, self.catalog, None)
        with self.assertRaisesRegex(RuntimeError, 'synthetic_provider_stop'):
            pipeline.density_intervention(self.image, self.identity, 'asa24')
        self.assertEqual(len(self.calls), 1)

    def test_identity_mutation_during_chat_cannot_succeed(self):
        def chat(messages):
            self.calls.append(messages)
            self.identity['final_codes'] = []
            return self.q
        pipeline = PairedStagePipeline(chat, None, self.catalog, None)
        result = pipeline.quantity_intervention(self.image, self.identity, 'asa24')
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(len(self.calls), 2)


if __name__ == '__main__':
    unittest.main()
