"""E1: the bookkeeping of the run driver, on the offline world of D8 (tests/test_leakage.py)."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import httpx
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'code'))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import api_log  # noqa: E402
import chagApp_openai  # noqa: E402
import config  # noqa: E402
import rag_food_code  # noqa: E402
import report_tables  # noqa: E402
import run_experiment  # noqa: E402
from test_leakage import FakeTokenizer, World  # noqa: E402


class MultilineWorld(World):
    """Descriptions on two lines: one CSV record each, over two lines of the file."""

    def answer(self, body):
        kind, image, content = super().answer(body)
        return kind, image, (content + '\nseen from above' if kind == 'description' else content)


class OfflineRun(unittest.TestCase):
    """A world in a temporary directory, its mocked API and the run driver's paths."""
    world_class = World

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        world = self.world = self.world_class(tmp.name)
        (world.tmp / '.env').write_text('OPENAI_API_KEY=sk-test\n')
        client = lambda: api_log.openai_client(transport=httpx.MockTransport(world.handler))
        for patch in [mock.patch.object(config, 'ENV_PATH', str(world.tmp / '.env')),
                      mock.patch.object(config, 'API_LOG_PATH', str(world.tmp / 'api.jsonl')),
                      mock.patch.object(rag_food_code, 'openai_client', client),
                      mock.patch.object(chagApp_openai, 'openai_client', client),
                      mock.patch('tiktoken.encoding_for_model', return_value=FakeTokenizer()),
                      mock.patch.object(run_experiment, 'SPLITS', {'tiny': (str(world.tmp / 'asa24.csv'),
                                                                            str(world.tmp / 'n5k.csv'))}),
                      mock.patch.object(run_experiment, 'IMAGE_LINK_CSV', str(world.tmp / 'link.csv')),
                      mock.patch.object(run_experiment, 'FOOD_WEIGHTS_CSV', str(world.tmp / 'weights.csv')),
                      mock.patch.object(run_experiment, 'NUTRITION_XLSX', str(world.tmp / 'nutrition.xlsx')),
                      mock.patch('time.sleep'), mock.patch('builtins.print')]:
            patch.start()
            self.addCleanup(patch.stop)
        self.run_dir = world.tmp / 'run'

    def run_split(self, run_dir=None):
        return run_experiment.run('tiny', str(run_dir or self.run_dir), workers=2,
                                  foods_csv=str(self.world.tmp / 'foods.csv'), index_dir=str(self.world.tmp / 'index'))

    def saved(self, name):
        return json.loads((self.run_dir / name).read_text())

    def ledgers(self):
        """The responses of the global API log (only this run's in the test) and of the run's copy."""
        read = lambda path: [json.loads(line) for line in path.read_text().splitlines()]
        return read(self.world.tmp / 'api.jsonl'), read(self.run_dir / 'openai_api.jsonl')


class TestE1Resume(OfflineRun):
    """R-E1-1: a resumed or failed invocation keeps the cost, the served models and the step of
    every response; another configuration does not reuse the directory."""

    def test_resume_without_requests(self):
        first = self.run_split()
        second = self.run_split()  # everything is answered: no request
        lines, run = self.ledgers()
        self.assertEqual(len(run), len(lines))
        self.assertEqual(second['run'], run_experiment.cost(lines))
        self.assertEqual(second, first)  # the cost was $0 and the served models none
        self.assertEqual(self.saved('cost.json'), second)
        saved = self.saved('config.json')
        self.assertEqual(saved['models_served'], ['gpt-4o-2024-08-06', 'text-embedding-3-large'])
        self.assertEqual([(i['status'], i['requests']) for i in saved['invocations']],
                         [('completed', len(lines)), ('completed', 0)])

    def test_failure_then_resume(self):
        real, calls = run_experiment.rag_portion_size.analyze_portions, []

        def stopped(*args, **kwargs):  # stopped by hand after the shot question of the protocol step
            calls.append(args)
            real(*args, **kwargs)
            if len(calls) == 1:
                raise KeyboardInterrupt
        with mock.patch.object(run_experiment.rag_portion_size, 'analyze_portions', stopped):
            with self.assertRaises(KeyboardInterrupt):
                self.run_split()
        lines, run = self.ledgers()
        self.assertEqual(len(run), len(lines))  # every paid response, with its step
        self.assertEqual([r['step'] for r in run][-1], 'asa24 portions (protocol)')
        self.assertEqual(self.saved('cost.json')['run'], run_experiment.cost(lines))
        failed = self.saved('config.json')['invocations'][0]
        self.assertEqual(failed['status'], 'failed: KeyboardInterrupt')
        self.assertEqual(failed['steps'][-1], {'name': 'asa24 portions (protocol)', 'api_log_lines': [len(lines) - 1, len(lines)]})
        self.assertEqual(failed['requests'], len(lines))

        usage = self.run_split()  # resumed: the amount question and the later steps
        lines, run = self.ledgers()
        self.assertEqual(len(run), len(lines))
        self.assertEqual(usage['run'], run_experiment.cost(lines))
        self.assertEqual(usage['asa24 portions (protocol)']['requests'], 2)  # one in each invocation
        self.assertEqual(usage['nutrition5k grams']['requests'], 1)
        invocations = self.saved('config.json')['invocations']
        self.assertEqual([i['status'] for i in invocations], ['failed: KeyboardInterrupt', 'completed'])
        self.assertEqual(sum(i['requests'] for i in invocations), len(lines))
        self.assertEqual(sorted({(r['invocation'], r['step']) for r in run if r['step'].startswith('asa24 portions')}),
                         [(1, 'asa24 portions (protocol)'), (2, 'asa24 portions (end to end)'), (2, 'asa24 portions (protocol)')])

    def test_other_configuration_is_refused(self):
        self.run_split()
        before = {p.name: p.read_bytes() for p in self.run_dir.iterdir()}, len(self.world.requests)
        with mock.patch.dict(config.MODELS, llm_vision='gpt-4o-mini'):
            with self.assertRaisesRegex(RuntimeError, 'another configuration'):
                self.run_split()
        link = self.world.tmp / 'link.csv'
        link.write_text(link.read_text().replace('1 fruit', '1 large fruit'))  # another portion option
        with self.assertRaisesRegex(RuntimeError, 'another configuration'):
            self.run_split()
        self.assertEqual(({p.name: p.read_bytes() for p in self.run_dir.iterdir()}, len(self.world.requests)), before)
        old = self.world.tmp / 'old'  # a directory of the old driver, as runs/dev
        old.mkdir()
        (old / 'config.json').write_text(json.dumps({'split': 'tiny', 'commit': '8f81d2e'}))
        with self.assertRaisesRegex(RuntimeError, 'another configuration'):
            self.run_split(old)
        (old / 'config.json').unlink()
        (old / 'asa24_food_codes.csv').write_text('x\n')
        with self.assertRaisesRegex(RuntimeError, 'no config.json'):
            self.run_split(old)
        self.assertEqual(len(self.world.requests), before[1])


class TestE1Images(OfflineRun):
    """R-E1-2: images are the CSV records of a table, not its lines."""
    world_class = MultilineWorld

    def test_records_not_lines(self):
        usage = self.run_split()
        self.assertGreater((self.run_dir / 'asa24_food_codes.csv').read_text().count('\n'), 3)
        self.assertEqual(self.saved('config.json')['images'], {'asa24': 2, 'nutrition5k': 2})  # asa24 was 4
        self.assertEqual(self.saved('metrics.json')['asa24']['images'], 2)
        asa24 = sum(v['usd'] for k, v in usage.items() if k.startswith('asa24') and isinstance(v, dict))
        self.assertAlmostEqual(usage['asa24 per image'], asa24 / 2)

    def test_tables_must_agree(self):
        self.run_split()
        table = self.run_dir / 'asa24_food_codes.csv'
        df = pd.read_csv(table)
        pd.concat([df, df.iloc[:1]]).to_csv(table, index=False)
        with self.assertRaisesRegex(RuntimeError, r'asa24: .* differ in rows \[2, 3\]'):
            self.run_split()


class TestE3Tables(OfflineRun):
    """E3: the tables of REPORT.md, from the metrics.json of a run, with the paper's values."""

    def test_tables_of_a_run(self):
        self.run_split()
        metrics = self.saved('metrics.json')
        mae, success = report_tables.mae_tables(metrics), report_tables.success_table(metrics)
        match, portions = report_tables.match_table(metrics), report_tables.portion_table(metrics)
        rows = lambda lines: [line for line in lines[2:] if line.startswith('| ') and not line.startswith('| 目标')]
        self.assertEqual((len(rows(mae)), len(rows(success)), len(rows(match)), len(rows(portions))), (10, 8, 4, 4))
        weight = metrics['nutrition5k']['mae']['complete']['Weight (g)']
        self.assertIn(f"| Weight (g) | {report_tables.mae_cell(weight)} |", '\n'.join(mae))
        self.assertTrue(any(line.endswith('| 49.4 / 0.348 |') for line in mae))  # Table 1
        self.assertIn('| 29.1 | 77.3 | 84.5 | 14.5 |', match[2])  # Table 3, GPT-4 Turbo, largest portions
        self.assertIn('| 74.3 |', portions[-1])  # Table 5, total


if __name__ == '__main__':
    unittest.main()
