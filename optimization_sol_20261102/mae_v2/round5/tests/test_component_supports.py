"""Synthetic K support selection; no real data, images, credentials or API."""
from copy import deepcopy
import hashlib
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from round5.src import component_supports as c


def vector(x=1., y=0.):
    return [x, y] + [0.] * 3070


def entry(sid, group=None):
    return {'train_id': sid, 'screening_group_id': group or 'group-' + sid,
            'image_sha256': hashlib.sha256(('bytes-' + sid).encode()).hexdigest(),
            'rgb_sha256': hashlib.sha256(('rgb-' + sid).encode()).hexdigest()}


def fixture(specs):
    """Ordered ID -> positive ingredient-mass dictionary."""
    return {'query_vector': vector(), 'entries': [entry(sid) for sid in specs],
            'vectors_by_id': {sid: vector() for sid in specs},
            'supports': {sid: [{'ingredient_id': code, 'grams': grams} for code, grams in items.items()]
                         for sid, items in specs.items()},
            'query_groups': [{'group_id': 'g1', 'hypotheses': ['a']}],
            'exclusions': {key: [] for key in c.retrieval.EXCLUSION_KEYS},
            'catalog_ids': sorted({code for items in specs.values() for code in items}),
            'fill_train_ids': []}


class ComponentSupportTests(unittest.TestCase):
    def test_exact_quarter_is_dominant_and_beats_nearby_higher_cosine(self):
        data = fixture({'below': {'a': 24.999, 'other': 75.001}, 'edge': {'a': 25, 'other': 75}})
        data['vectors_by_id']['edge'] = vector(0, 1)
        result = c.select_supports(**data)
        self.assertEqual(result['selected_train_ids'], ['edge'])
        support = result['hypothesis_supports'][0]
        self.assertTrue(support['dominant'])
        self.assertEqual(support['ingredient_mass_fraction'], .25)

    def test_cosine_precedes_fraction_within_dominance_tier(self):
        data = fixture({'large': {'a': 99, 'other': 1}, 'close': {'a': 26, 'other': 74}})
        data['vectors_by_id']['large'] = vector(.8, .6)
        self.assertEqual(c.select_supports(**data)['selected_train_ids'], ['close'])

    def test_fraction_then_stable_id_ties_and_mapping_order_invariance(self):
        data = fixture({'a': {'a': 30, 'other': 70}, 'c': {'a': 40, 'other': 60},
                        'b': {'a': 40, 'other': 60}})
        first = c.select_supports(**data)
        self.assertEqual(first['selected_train_ids'], ['b'])
        data['entries'].reverse()
        data['vectors_by_id'] = dict(reversed(list(data['vectors_by_id'].items())))
        self.assertEqual(first, c.select_supports(**data))

    def test_group_major_then_hypothesis_order_is_fixed(self):
        data = fixture({code: {code: 100} for code in 'abcd'})
        data['query_groups'] = [{'group_id': 'g1', 'hypotheses': ['a', 'b']},
                                {'group_id': 'g2', 'hypotheses': ['c', 'd']}]
        result = c.select_supports(**data)
        self.assertEqual(result['selected_train_ids'], list('abcd'))
        self.assertEqual([r['ingredient_id'] for r in result['hypothesis_supports']], list('abcd'))

    def test_trace_in_selected_image_does_not_cover_better_component_support(self):
        data = fixture({'first': {'a': 99, 'b': 1}, 'second': {'b': 100}})
        data['query_groups'][0]['hypotheses'] = ['a', 'b']
        result = c.select_supports(**data)
        self.assertEqual(result['selected_train_ids'], ['first', 'second'])
        self.assertEqual([a['status'] for a in result['hypothesis_supports']], ['selected', 'selected'])

    def test_highest_feasible_selected_support_is_reused(self):
        data = fixture({'first': {'a': 50, 'b': 50}, 'second': {'b': 30, 'other': 70}})
        data['query_groups'][0]['hypotheses'] = ['a', 'b']
        result = c.select_supports(**data)
        self.assertEqual(result['selected_train_ids'], ['first'])
        self.assertEqual(result['hypothesis_supports'][1]['status'], 'reused')
        self.assertTrue(result['hypothesis_supports'][1]['covered'])

    def test_used_group_other_image_skipped_for_next_feasible_group(self):
        data = fixture({'a': {'a': 100}, 'b': {'b': 100}, 'c': {'b': 50, 'other': 50}})
        data['entries'][1]['screening_group_id'] = data['entries'][0]['screening_group_id']
        data['query_groups'][0]['hypotheses'] = ['a', 'b']
        self.assertEqual(c.select_supports(**data)['selected_train_ids'], ['a', 'c'])

    def test_group_conflict_distinct_from_missing_id(self):
        data = fixture({'a': {'a': 100}, 'b': {'b': 100}})
        data['entries'][1]['screening_group_id'] = data['entries'][0]['screening_group_id']
        data['catalog_ids'].append('missing')
        data['query_groups'] = [{'group_id': 'g1', 'hypotheses': ['a', 'b']},
                                {'group_id': 'g2', 'hypotheses': ['missing']}]
        result = c.select_supports(**data)
        self.assertEqual([a['status'] for a in result['hypothesis_supports']],
                         ['selected', 'group_conflict', 'unavailable'])
        self.assertEqual(result['hypothesis_supports'][1]['eligible_support_count'], 1)
        self.assertEqual(result['hypothesis_supports'][1]['feasible_support_count'], 0)

    def test_budget_does_not_downgrade_to_trace_reuse(self):
        specs = {'t' + str(i): {'id' + str(i): 100} for i in range(9)}
        specs['t0']['id8'] = 1
        data = fixture(specs)
        data['query_groups'] = [{'group_id': 'g' + str(i), 'hypotheses': ['id' + str(2*i), 'id' + str(2*i+1)]}
                                for i in range(4)] + [{'group_id': 'g4', 'hypotheses': ['id8', 'id0']}]
        result = c.select_supports(**data)
        self.assertEqual(result['selected_train_ids'], ['t' + str(i) for i in range(8)])
        self.assertEqual(result['hypothesis_supports'][-2]['status'], 'budget')
        self.assertFalse(result['hypothesis_supports'][-2]['covered'])
        self.assertEqual(result['hypothesis_supports'][-1]['status'], 'reused')

    def test_each_exclusion_channel_propagates_to_entire_association_group(self):
        data = fixture({'a': {'a': 100}, 'alias': {'a': 100}, 'b': {'a': 100}})
        data['entries'][1]['screening_group_id'] = data['entries'][0]['screening_group_id']
        row = data['entries'][0]
        channels = {'train_ids': row['train_id'], 'screening_group_ids': row['screening_group_id'],
                    'image_sha256': row['image_sha256'], 'rgb_sha256': row['rgb_sha256']}
        data['fill_train_ids'] = ['alias', 'a', 'b']
        for key, value in channels.items():
            case = deepcopy(data); case['exclusions'][key] = [value]
            with self.subTest(channel=key):
                result = c.select_supports(**case)
                self.assertEqual(result['selected_train_ids'], ['b'])
                self.assertEqual(result['audit']['eligible_training_groups'], 1)

    def test_fill_obeys_explicit_order_deduplicates_groups_and_allows_exhaustion(self):
        data = fixture({sid: {'a': 100} for sid in 'abcd'})
        data['query_groups'][0]['hypotheses'] = []
        data['entries'][2]['screening_group_id'] = data['entries'][1]['screening_group_id']
        data['vectors_by_id']['d'] = vector(0, 1)
        data['fill_train_ids'] = ['d', 'b', 'd', 'c', 'a']
        result = c.select_supports(**data)
        self.assertEqual(result['selected_train_ids'], ['d', 'b', 'a'])
        self.assertEqual(result['audit']['filled_train_ids'], ['d', 'b', 'a'])
        self.assertEqual(result['hypothesis_supports'], [])

    def test_fill_never_exceeds_eight_and_empty_fill_is_explicitly_legal(self):
        data = fixture({'t' + str(i): {'a': 100} for i in range(10)})
        data['query_groups'][0]['hypotheses'] = []
        self.assertEqual(c.select_supports(**data)['selected_train_ids'], [])
        data['fill_train_ids'] = list(data['supports'])
        self.assertEqual(c.select_supports(**data)['selected_train_ids'], list(data['supports'])[:8])

    def test_duplicate_training_id_entries_sum_before_fraction(self):
        data = fixture({'a': {'a': 25, 'other': 75}})
        data['supports']['a'] = [{'ingredient_id': 'a', 'grams': 10}, {'ingredient_id': 'a', 'grams': 15},
                                 {'ingredient_id': 'other', 'grams': 75}]
        support = c.select_supports(**data)['hypothesis_supports'][0]
        self.assertTrue(support['dominant'])
        self.assertEqual(support['ingredient_mass_fraction'], .25)

    def test_nonfinite_nonpositive_and_boolean_training_mass_fail_even_if_excluded(self):
        data = fixture({'a': {'a': 100}, 'b': {'a': 100}})
        data['exclusions']['train_ids'] = ['b']
        for value in (-1, 0, float('nan'), float('inf'), True, '20'):
            case = deepcopy(data); case['supports']['b'][0]['grams'] = value
            with self.subTest(value=value), self.assertRaisesRegex(c.SupportError, 'finite_positive'):
                c.select_supports(**case)
        data['supports']['b'] = [{'ingredient_id': 'a', 'grams': 1e308}] * 2
        with self.assertRaisesRegex(c.SupportError, 'nonfinite_training_mass_sum'):
            c.select_supports(**data)

    def test_bad_vectors_and_missing_vector_fail(self):
        data = fixture({'a': {'a': 100}})
        for bad in (vector(float('nan')), vector(float('inf')), [0.] * 3072, [1.] * 3071, [True] + [0.] * 3071):
            case = deepcopy(data); case['query_vector'] = bad
            with self.subTest(kind='query'), self.assertRaises(c.retrieval.RetrievalError): c.select_supports(**case)
            case = deepcopy(data); case['vectors_by_id']['a'] = bad
            with self.subTest(kind='gallery'), self.assertRaises(c.retrieval.RetrievalError): c.select_supports(**case)
        data['vectors_by_id'] = {}
        with self.assertRaises(c.retrieval.RetrievalError): c.select_supports(**data)

    def test_unrecognized_catalog_support_population_and_fill_rejected(self):
        data = fixture({'a': {'a': 100}})
        cases = []
        case = deepcopy(data); case['supports']['a'][0]['ingredient_id'] = 'unknown'; cases.append(case)
        case = deepcopy(data); case['supports'] = {}; cases.append(case)
        case = deepcopy(data); case['fill_train_ids'] = ['unknown']; cases.append(case)
        case = deepcopy(data); case['catalog_ids'] = ['a', 'a']; cases.append(case)
        case = deepcopy(data); case['supports']['a'][0]['truth'] = 100; cases.append(case)
        for case in cases:
            with self.assertRaises(c.SupportError): c.select_supports(**case)

    def test_hypothesis_contract_and_query_label_fields_rejected(self):
        data = fixture({'a': {'a': 100}, 'b': {'b': 100}, 'c': {'c': 100}})
        cases = [[], [{'group_id': 'g1', 'hypotheses': ['a', 'b', 'c']}],
                 [{'group_id': 'g1', 'hypotheses': ['unknown']}],
                 [{'group_id': 'g1', 'hypotheses': ['a', 'a']}],
                 [{'group_id': 'g1', 'hypotheses': []}] * 2,
                 [{'group_id': 'g1', 'hypotheses': [], 'truth': 100}]]
        for groups in cases:
            case = deepcopy(data); case['query_groups'] = groups
            with self.assertRaises(c.SupportError): c.select_supports(**case)

    def test_input_immutability_deterministic_hash_binding_and_no_io(self):
        data = fixture({'a': {'a': 100}, 'b': {'b': 100}})
        before = deepcopy(data)
        with patch('builtins.open', side_effect=AssertionError('file read')):
            first = c.select_supports(**data)
        self.assertEqual(data, before)
        self.assertEqual(first, c.select_supports(**data))
        self.assertTrue(all(len(value) == 64 for value in first['audit']['input_sha256'].values()))
        changed = deepcopy(data); changed['supports']['b'][0]['grams'] = 99
        other = c.select_supports(**changed)
        self.assertEqual(first['selected_train_ids'], other['selected_train_ids'])
        self.assertNotEqual(first['audit']['input_sha256']['supports'], other['audit']['input_sha256']['supports'])
        first['selected_train_ids'].append('mutated-result')
        self.assertEqual(c.select_supports(**data)['selected_train_ids'], ['a'])


if __name__ == '__main__':
    unittest.main()
