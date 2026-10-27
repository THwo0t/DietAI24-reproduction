"""R-F3-1: ledger-consistent bad responses must not receive an overall PASS."""
import copy
import sys
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
        # Exercise validate(), not just the helper: mutate only in-memory log copies,
        # keep costs/config/CSVs unchanged, exactly as the independent review did.
        directory = ROOT / 'runs/dev-gpt-6.1-sol-4096'
        records = audit.read_lines(directory / 'openai_api.jsonl')
        identity = next(row['request_id'] for row in records if row['endpoint'].endswith('chat/completions'))
        original = audit.read_lines
        def injected(path):
            rows = copy.deepcopy(original(path))
            for row in rows:
                if row['request_id'] == identity:
                    row.update(finish_reasons=['length'], empty_contents=[True])
            return rows
        with mock.patch.object(audit, 'read_lines', side_effect=injected):
            result = audit.validate(directory)
        self.assertEqual(result['reconciliation_checks'], 'PASS')
        self.assertEqual(result['checks'], 'needs review')
        self.assertEqual(result['response_health'], 'needs review')
        self.assertEqual(result['health_issues'][0]['request_id'], identity)
        self.assertIn('empty_content', result['health_issues'][0]['problems'])
        self.assertEqual(audit.validate(directory)['checks'], 'PASS')


if __name__ == '__main__':
    unittest.main()
