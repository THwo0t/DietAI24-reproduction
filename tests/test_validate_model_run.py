"""R-F3-1: ledger-consistent bad responses must not receive an overall PASS."""
import copy
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'agents'))
import validate_model_run as audit


class TestResponseHealth(unittest.TestCase):
    def setUp(self):
        self.good = {'status': 200, 'request_id': 'req_mock', 'step': 'grams',
                     'finish_reasons': ['stop'], 'empty_contents': [False]}

    def test_empty_truncated_and_missing_metadata_are_explicit(self):
        variants = [{'finish_reasons': ['length'], 'empty_contents': [True]},
                    {'finish_reasons': ['content_filter']}, {'empty_contents': [True]},
                    {'finish_reasons': None}, {'empty_contents': None}, {'status': 500}]
        for change in variants:
            with self.subTest(change=change):
                issues = audit.response_health([{**self.good, **change}])
                self.assertEqual(issues[0]['request_id'], 'req_mock')
                self.assertEqual(issues[0]['step'], 'grams')
        self.assertEqual(audit.response_health([self.good]), [])

    def test_same_bad_response_in_both_ledgers_is_not_pass(self):
        # Exercise validate(), real file ledgers and cost reconciliation without requiring
        # publication of historical development logs. Numerical evaluation has separate
        # tests; isolate it here so this response-health regression is self-contained.
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);directory=root/'run';directory.mkdir()
            (root/'code').mkdir();(root/'logs').mkdir()
            (root/'code/source.py').write_text('synthetic source fingerprint\n')
            global_rows=[{**self.good,'request_id':'req_mock_'+str(i),
                'endpoint':'/v1/chat/completions','model_requested':'gpt-6.1-sol','model_served':'gpt-6.1-sol',
                'temperature':1,'max_tokens':None,'max_completion_tokens':600,
                'usage':{'prompt_tokens':100,'completion_tokens':10,
                         'completion_tokens_details':{'reasoning_tokens':4}}} for i in range(2)]
            steps=['asa24 portions','nutrition5k grams']
            records=[{**row,'invocation':1,'step':steps[i]} for i,row in enumerate(global_rows)]
            for path,rows in [(root/'logs/openai_api.jsonl',global_rows),(directory/'openai_api.jsonl',records)]:
                path.write_text(''.join(json.dumps(row)+'\n' for row in rows))
            conf={'split':'synthetic','invocations':[{'status':'completed','uncommitted_changes':False,
                'steps':[{'name':name,'api_log_lines':[i,i+1]} for i,name in enumerate(steps)]}],
                'images':{'asa24':1,'nutrition5k':1},
                'code_sha256':{'source.py':hashlib.sha256((root/'code/source.py').read_bytes()).hexdigest()}}
            (directory/'config.json').write_text(json.dumps(conf))
            (directory/'metrics.json').write_text('{}')
            (directory/'cost.json').write_text(json.dumps({'run':audit.cost(records),
                'asa24 per image':audit.cost(records[:1])['usd'],'nutrition5k per image':audit.cost(records[1:])['usd']}))
            identity=records[0]['request_id'];original=audit.read_lines
            def injected(path):
                rows=copy.deepcopy(original(path))
                for row in rows:
                    if row['request_id']==identity:row.update(finish_reasons=['length'],empty_contents=[True])
                return rows
            with mock.patch.object(audit,'ROOT',root),mock.patch.object(audit.evaluate,'evaluate_run',return_value={}):
                with mock.patch.object(audit,'read_lines',side_effect=injected):result=audit.validate(directory)
                self.assertEqual(result['reconciliation_checks'],'PASS')
                self.assertEqual(result['checks'],'needs review')
                self.assertEqual(result['response_health'],'needs review')
                self.assertEqual(result['health_issues'][0]['request_id'],identity)
                self.assertIn('empty_content',result['health_issues'][0]['problems'])
                self.assertEqual(audit.validate(directory)['checks'],'PASS')


if __name__ == '__main__':
    unittest.main()
