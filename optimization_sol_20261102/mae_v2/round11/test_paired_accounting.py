from copy import deepcopy
import json
import math
from pathlib import Path
import sys
import unittest

import paired_accounting as p


class PairedAccountingTests(unittest.TestCase):
    def setUp(self):
        self.items = [
            {'item_id': 'i1', 'description': 'synthetic food A', 'broad_query': 'food A',
             'region_ids': ['r1'], 'primary_code': '11111111', 'alternative_codes': ['22222222']},
            {'item_id': 'i2', 'description': 'synthetic food B', 'broad_query': 'food B',
             'region_ids': ['r2'], 'primary_code': '33333333', 'alternative_codes': []},
        ]
        self.foods = {code: {'description': 'synthetic state ' + str(i),
            'density': dict(zip(p.NUTRIENTS, values)), 'current_image_truth': 'DO_NOT_EXPORT'}
            for i, (code, values) in enumerate((('11111111', (100, 10, 20, 30)),
                ('22222222', (200, 20, 40, 60)), ('33333333', (50, 2, 5, 10))))}
        self.original = [{'item_id': 'i1', 'grams': 100}, {'item_id': 'i2', 'grams': 200}]
        self.qraw = json.dumps({'total_grams': 600, 'items': [
            {'item_id': 'i2', 'ratio': 2}, {'item_id': 'i1', 'ratio': 1}]})
        self.draw = json.dumps({'items': [{'item_id': 'i2', 'density_code': '33333333'},
                                        {'item_id': 'i1', 'density_code': '22222222'}]})

    def result(self):
        return p.successful_profiles(self.items, self.foods, self.original,
            p.parse_quantity(self.qraw, self.items), p.parse_density(self.draw, self.items))

    def test_hand_calculated_four_profiles_and_exact_mass_manipulation(self):
        result = self.result()['profiles']
        expected = {'O': (300, 250, 19, 40, 65), 'Q': (600, 500, 38, 80, 130),
                    'D': (300, 300, 24, 50, 80), 'Q+D': (600, 600, 48, 100, 160)}
        for name, values in expected.items():
            self.assertEqual(result[name]['prediction'], dict(zip(p.TARGETS, values)))
        for left, right in (('O', 'D'), ('Q', 'Q+D')):
            self.assertEqual([row['grams'] for row in result[left]['leaves']],
                             [row['grams'] for row in result[right]['leaves']])
        self.assertEqual(result['D']['leaves'][0]['mass_context_code'], '11111111')
        self.assertEqual(result['D']['leaves'][0]['density_code'], '22222222')
        self.assertEqual(result['D']['leaves'][0]['original_final_codes'], ['11111111', '22222222'])

    def test_control_matches_original_O_arithmetic_on_synthetic_identity(self):
        base = Path(__file__).resolve().parents[1]
        sys.path[:0] = [str(base/'round10'), str(base/'round8/src'), str(base/'src'),
                       str(base/'round7/src'), str(base/'round4/src')]
        from source_portions import SourcePortionPipeline
        identity = {'status': 'ok', 'items': deepcopy(self.items),
                    'candidates': {'i1': ['11111111', '22222222'], 'i2': ['33333333']},
                    'final_codes': ['11111111', '33333333']}
        old = SourcePortionPipeline(None, None, {'foods': self.foods}, None)
        reference = old.aggregate_quantities(identity, 'nutrition5k', self.original)
        self.assertEqual(self.result()['profiles']['O']['prediction'], reference['prediction'])

    def test_contexts_project_only_fixed_blind_fields_and_do_not_change_inputs(self):
        before = deepcopy((self.items, self.foods))
        prompts = p.quantity_prompt(self.items, self.foods) + p.density_prompt(self.items, self.foods)
        self.assertNotIn('DO_NOT_EXPORT', prompts)
        self.assertNotIn('current_image_truth', prompts)
        self.assertNotIn('density":', prompts)
        self.assertEqual((self.items, self.foods), before)
        self.result()['profiles']['D']['leaves'][0]['original_final_codes'].clear()
        self.assertEqual((self.items, self.foods), before)
        bad = deepcopy(self.items); bad[0]['truth'] = 'DO_NOT_EXPORT'
        with self.assertRaises(p.PairContractError):
            p.quantity_prompt(bad, self.foods)

    def test_join_is_complete_unique_and_independent_of_response_order(self):
        q = p.parse_quantity(self.qraw, self.items)
        self.assertEqual([row['item_id'] for row in q['items']], ['i1', 'i2'])
        self.assertEqual([row['grams'] for row in q['items']], [200, 400])
        for rows in ([], [{'item_id': 'i1', 'ratio': 1}] * 2,
                     [{'item_id': 'i1', 'ratio': 1}, {'item_id': 'i3', 'ratio': 1}]):
            with self.subTest(rows=rows), self.assertRaises(p.PairContractError):
                p.parse_quantity(json.dumps({'total_grams': 100, 'items': rows}), self.items)

    def test_invalid_numeric_or_structure_responses_never_become_partial_predictions(self):
        for value in (0, -1, True, '100', float('nan'), float('inf')):
            raw = json.dumps({'total_grams': value, 'items': [
                {'item_id': 'i1', 'ratio': 1}, {'item_id': 'i2', 'ratio': 1}]})
            with self.subTest(value=str(value)), self.assertRaises(p.PairContractError):
                p.parse_quantity(raw, self.items)
        for raw in ('{"items":[],"items":[]}', 'not JSON', '{"total_grams":1,"items":[],"extra":1}',
                    'x' * (p.MAX_RESPONSE_BYTES + 1)):
            with self.assertRaises(p.PairContractError):
                p.parse_quantity(raw, self.items)
        with self.assertRaises(p.PairContractError):
            p.number(10**1000)

    def test_density_cannot_add_code_item_or_quantity_fields(self):
        bad = json.loads(self.draw)
        bad['items'][0]['density_code'] = '11111111'
        with self.assertRaisesRegex(p.PairContractError, 'outside_fixed_final_set'):
            p.parse_density(json.dumps(bad), self.items)
        bad = json.loads(self.draw); bad['items'][0]['grams'] = 42
        with self.assertRaises(p.PairContractError):
            p.parse_density(json.dumps(bad), self.items)
        bad = deepcopy(self.items); bad[1]['region_ids'] = ['r1']
        with self.assertRaisesRegex(p.PairContractError, 'disjoint_fixed_regions'):
            p.parse_density(self.draw, bad)

    def test_result_tampering_and_aggregate_overflow_refuse(self):
        q = p.parse_quantity(self.qraw, self.items)
        d = p.parse_density(self.draw, self.items)
        q['items'][0]['grams'] += 1
        with self.assertRaisesRegex(p.PairContractError, 'quantity_result_changed'):
            p.successful_profiles(self.items, self.foods, self.original, q, d)
        food = deepcopy(self.foods); food['11111111']['density']['energy'] = float('inf')
        with self.assertRaises(p.PairContractError):
            p.successful_profiles(self.items, food, self.original,
                p.parse_quantity(self.qraw, self.items), d)
        original = deepcopy(self.original); original[0]['grams'] = 1e308
        food = deepcopy(self.foods); food['11111111']['density']['energy'] = 1e308
        with self.assertRaises(p.PairContractError):
            p.successful_profiles(self.items, food, original,
                p.parse_quantity(self.qraw, self.items), d)

    def test_large_positive_ratios_normalize_without_overflow_and_zeros_refuse(self):
        q = p.parse_quantity(json.dumps({'total_grams': 1, 'items': [
            {'item_id': 'i1', 'ratio': 1e308}, {'item_id': 'i2', 'ratio': 1e308}]}), self.items)
        self.assertEqual([row['share'] for row in q['items']], [.5, .5])
        self.assertEqual(math.fsum(row['grams'] for row in q['items']), 1)
        with self.assertRaises(p.PairContractError):
            p.parse_quantity(json.dumps({'total_grams': 1, 'items': [
                {'item_id': 'i1', 'ratio': 0}, {'item_id': 'i2', 'ratio': 1}]}), self.items)


if __name__ == '__main__':
    unittest.main()
