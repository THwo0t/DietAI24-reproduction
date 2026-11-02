"""R-M2-3-2: verify the documented as-run candidate context at prompt boundaries."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from pipeline_v2 import ComponentPipeline

CODE = '11111111'
CATEGORY = 'OFFICIAL_CATEGORY_SENTINEL'
CATALOG = {'foods': {CODE: {'description': 'cooked rice', 'category': CATEGORY,
    'density': {'energy': 130, 'fat': 1, 'carbs': 28, 'protein': 2.5}}}}
LEAF = {'component_id': 'p1c1', 'description': 'rice', 'parent_description': 'rice',
        'parent_id': 'p1', 'accounting': 'composite', 'primary_code': CODE}


class CandidateContextTests(unittest.TestCase):
    def assert_as_run_context(self, prompt):
        context = json.loads(prompt.split(' Context: ', 1)[1])
        candidate = context[0]['candidates'][0]
        self.assertEqual(set(candidate), {'code', 'description', 'density_per_100g', 'relationship_hints'})
        self.assertEqual(candidate['description'], CATALOG['foods'][CODE]['description'])
        self.assertEqual(candidate['density_per_100g'], CATALOG['foods'][CODE]['density'])
        self.assertNotIn(CATEGORY, prompt)
        self.assertNotIn('category', candidate)

    def test_actual_selection_prompt_uses_documented_as_run_fields(self):
        requests = []
        def chat(messages):
            requests.append(deepcopy(messages))
            return json.dumps({'items': [{'component_id': 'p1c1', 'primary_code': CODE}]})
        pipeline = ComponentPipeline(chat, None, CATALOG, None)
        selected = pipeline._select([LEAF], {'p1c1': [CODE]}, [], [])
        self.assertEqual(selected[0]['primary_code'], CODE)
        self.assertEqual(len(requests), 1)
        self.assert_as_run_context(requests[0][1]['content'][0]['text'])

    def test_semantic_review_uses_the_same_documented_context(self):
        pipeline = ComponentPipeline(None, None, CATALOG, None)
        identity = {'leaves': [LEAF], 'candidates': {'p1c1': [CODE]}}
        with patch.object(pipeline, '_checked_identity'), \
             patch.object(pipeline, '_checked_base_masses', return_value={}), \
             patch.object(pipeline, 'semantic_conflicts', return_value=[]), \
             patch('pipeline_v2.encode_image', return_value='synthetic-image'), \
             patch.object(pipeline, '_stage', return_value=None) as stage:
            pipeline.review_codes('unused.png', identity, {'stages': []}, {})
        self.assertEqual(stage.call_args.args[0], 'semantic_review')
        self.assert_as_run_context(stage.call_args.args[1])


if __name__ == '__main__':
    unittest.main()
