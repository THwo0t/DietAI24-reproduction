"""Offline orchestration tests using only synthetic rows/stores and processes."""
from concurrent.futures import Future
from contextlib import nullcontext
from pathlib import Path
from types import ModuleType, SimpleNamespace
import os
import sys
import tempfile
import io
import unittest
from unittest.mock import patch

BASE = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(BASE), str(BASE / 'round11')]
from round11.parallel_acceleration import p_parallel_controller as c


def synthetic_process_task(number):
    return number * 2, os.getpid()


def synthetic_process_initializer():
    pass


class TrackingFuture(Future):
    def __init__(self):
        super().__init__()
        self.reads = 0

    def result(self, *args, **kwargs):
        self.reads += 1
        return super().result(*args, **kwargs)


class ImmediatePool:
    instances = []

    def __init__(self, **kwargs):
        self.kwargs, self.submitted, self.exited = kwargs, [], False
        self.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.exited = True

    def submit(self, task, *args):
        future = TrackingFuture()
        self.submitted.append((args, future))
        try:
            future.set_result(task(*args))
        except BaseException as error:
            future.set_exception(error)
        return future


class SchedulerTests(unittest.TestCase):
    def setUp(self):
        ImmediatePool.instances = []

    def test_real_fork_pool_returns_each_synthetic_item_once(self):
        results = list(c._bounded_results(synthetic_process_task,
            ((n,) for n in range(9)), 4, synthetic_process_initializer))
        self.assertEqual({args[0] for args, _ in results}, set(range(9)))
        self.assertEqual(len(results), 9)
        for args, (value, pid) in results:
            self.assertEqual(value, args[0] * 2)
            self.assertNotEqual(pid, os.getpid())

    def test_failure_stops_refill_and_drains_every_submitted_future(self):
        def task(n):
            if n == 1:
                raise ValueError('synthetic failure')
            return n
        with patch.object(c, 'ProcessPoolExecutor', ImmediatePool):
            with self.assertRaisesRegex(ValueError, 'synthetic failure'):
                list(c._bounded_results(task, ((n,) for n in range(20)), 4, lambda: None))
        pool, = ImmediatePool.instances
        self.assertEqual(len(pool.submitted), 4)
        self.assertTrue(all(f.reads >= 1 for _, f in pool.submitted))
        self.assertTrue(pool.exited)

    def test_empty_population_still_closes_pool(self):
        with patch.object(c, 'ProcessPoolExecutor', ImmediatePool):
            self.assertEqual(list(c._bounded_results(lambda: None, (), 4, lambda: None)), [])
        self.assertTrue(ImmediatePool.instances[0].exited)


class PublicBoundaryTests(unittest.TestCase):
    def test_invalid_arguments_refuse_before_registration(self):
        for workers in (0, 1, 3, 5, True, '4'):
            with self.assertRaises(ValueError):
                c.run(workers=workers)
        with self.assertRaises(ValueError):
            c.run(allow_paid=1)
        with self.assertRaises(TypeError):
            c.run(root='/tmp/synthetic')
        with self.assertRaises(TypeError):
            c.run(ctx=object())

    def test_cli_only_accepts_paid_and_frozen_worker_choices(self):
        with patch.object(c, 'run', return_value='synthetic') as run:
            self.assertEqual(c.main(['--allow-paid', '--workers', '8']), 'synthetic')
            run.assert_called_once_with(allow_paid=True, workers=8)
        for workers in (4, 8, 16, 32):
            with patch.object(c, 'run', return_value='synthetic') as run:
                c.main(['--workers', str(workers)])
                run.assert_called_once_with(allow_paid=False, workers=workers)
        with patch.object(c, 'run', return_value='synthetic') as run:
            c.main([])
            run.assert_called_once_with(allow_paid=False, workers=16)
        for argv in (['--workers', '2'], ['--root', '/tmp/synthetic']):
            with patch('sys.stderr'), self.assertRaises(SystemExit):
                c.main(argv)

    def test_authorization_precedes_execution_inside_unique_lock(self):
        events = []
        registration = ModuleType('p_parallel_registration')
        registration.runtime_engineering = lambda: {'synthetic': True}
        registration.verify_engineering = lambda e: events.append('verify')
        registration.authorize_continuation = lambda *args: events.append('authorize')
        class Lock:
            def __enter__(self): events.append('lock')
            def __exit__(self, *args): events.append('unlock')
        registration.controller_lock = Lock
        with patch.dict(sys.modules, {registration.__name__: registration}), \
                patch.object(c, '_execute', side_effect=lambda *args: events.append('execute') or {}):
            c.run(allow_paid=True)
        self.assertEqual(events, ['lock', 'verify', 'authorize', 'execute', 'unlock'])


class FakeStore:
    def __init__(self, directory, binding, expected, events, label):
        self.directory, self.binding = directory, binding
        self.expected_records, self.events, self.label = expected, events, label
        directory.mkdir()
        self.values = None

    def initialize(self):
        self.events.append(self.label + ':initialize')

    def finalize(self, values):
        self.events.append(self.label + ':seal')
        self.values = values
        (self.directory / 'completion.json').write_text('synthetic seal')

    def verify_completed(self):
        return self.values


class PhaseBarrierTests(unittest.TestCase):
    def execute_synthetic(self, prediction_failure=False):
        events = []
        binding = {'schema_version': 1}
        rows = [{'sample_id': str(n), 'dataset': 'synthetic', 'fold': 0} for n in range(2)]
        ctx = SimpleNamespace(rows=rows, binding=binding, imports={}, manifest_sha256='synthetic',
            fallbacks={'folds': {'synthetic': {'0': {'value': {}}}}},
            verify_sources=lambda: events.append('science:verify'))
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        ids = FakeStore(root / 'ids', binding,
            [c.name('identity', row) for row in rows] + ['service-proof'], events, 'identity')
        out = FakeStore(root / 'out', binding,
            [c.name('record', row) for row in rows] + ['service-proof'], events, 'record')
        adapter = FakeStore(root / 'adapter', {}, [], events, 'adapter')
        gate = SimpleNamespace()
        ledger = SimpleNamespace(binding=c.fingerprint(binding),
            initialize=lambda: events.append('ledger:initialize'),
            recover_pending=lambda: events.append('ledger:recover'),
            audit=lambda **kw: {'counts': {'synthetic': 1}}, task_gate=lambda: gate)
        snapshot = SimpleNamespace(load=lambda: ({}, {'coding_completion_sha256': 'seal'}),
            revalidate_full=lambda: events.append('snapshot:terminal'))
        registration = ModuleType('p_parallel_registration')
        registration.verify_engineering = lambda e: events.append('engineering:verify')
        worker = ModuleType('round11.parallel_acceleration.p_parallel_worker')
        worker.configure = lambda *a, **k: events.append('configure:prediction' if k.get('snapshot') else 'configure:identity')
        worker.initialize_forked_worker = lambda: None
        def identity_task(row):
            events.append('identity:task')
            return {'envelope': {'result': {'status': 'ok'}, 'request_refs': {'identify': []}},
                    'provider_constructed': False}
        def prediction_task(row, *args):
            self.assertIn('adapter:contexts', events)
            events.append('prediction:task')
            if prediction_failure:
                raise ValueError('synthetic prediction failure')
            return {'record': {'sample': row['sample_id']},
                'all_refs': {c.name('record', row) + '-whole-whole': []},
                'provider_constructed': False}
        worker.identity_task, worker.prediction_task = identity_task, prediction_task
        def bounded(task, arguments, *unused, **kwargs):
            for args in arguments:
                yield args, task(*args)
        def build(*args, **kwargs):
            self.assertIn('identity:seal', events)
            self.assertNotIn('prediction:task', events)
            events.append('snapshot:build')
            return snapshot
        def adapter_run(*args):
            self.assertIn('snapshot:build', events)
            events.append('adapter:run')
            (adapter.directory / 'completion.json').write_text('synthetic seal')
        def contexts(*args):
            self.assertTrue((adapter.directory / 'completion.json').is_file())
            events.append('adapter:contexts')
            return {}
        with patch('sys.stdout', new_callable=io.StringIO), \
                patch.dict(sys.modules, {registration.__name__: registration, worker.__name__: worker}), \
                patch('context_p.runtime_context', return_value=ctx), \
                patch.object(c, 'ROOT', root), patch.object(c, 'Ledger', return_value=ledger), \
                patch.object(c, 'allowed_slots', return_value={}), \
                patch.object(c, 'identity_store', return_value=ids), \
                patch.object(c, 'final_store', return_value=out), \
                patch.object(c, 'adapter_store', return_value=adapter), \
                patch.object(c, 'proof_for_refs', return_value={}), \
                patch.object(c, 'sha', return_value='seal'), \
                patch.object(c, '_bounded_results', side_effect=bounded), \
                patch.object(c, 'build_loader', side_effect=build), \
                patch.object(c, '_isolated_adapter', side_effect=adapter_run), \
                patch.object(c, '_contexts', side_effect=contexts):
            if prediction_failure:
                with self.assertRaisesRegex(ValueError, 'synthetic prediction failure'):
                    c._execute({'synthetic': True}, 4, True)
                return events, None
            return events, c._execute({'synthetic': True}, 4, True)

    def test_unique_controller_seals_after_phase_barriers(self):
        events, result = self.execute_synthetic()
        self.assertEqual(events.count('identity:seal'), 1)
        self.assertEqual(events.count('record:seal'), 1)
        self.assertLess(events.index('identity:seal'), events.index('adapter:run'))
        self.assertLess(events.index('adapter:contexts'), events.index('prediction:task'))
        self.assertLess(events.index('snapshot:terminal'), events.index('record:seal'))
        self.assertEqual(result['records'], 2)
        self.assertFalse(result['provider_constructed'])
        self.assertEqual(result['engineering_binding'], c.fingerprint({'synthetic': True}))

    def test_prediction_failure_never_seals_final_store(self):
        events, _ = self.execute_synthetic(prediction_failure=True)
        self.assertNotIn('record:seal', events)
        self.assertNotIn('snapshot:terminal', events)


class ProgressTests(unittest.TestCase):
    def test_emits_only_metadata_at_count_and_time_boundaries(self):
        import json
        now = [100.]
        with patch.object(c.time, 'monotonic', side_effect=lambda: now[0]), \
                patch('sys.stdout', new_callable=io.StringIO) as output:
            progress = c._Progress('synthetic', 843)
            progress.update(19)
            progress.update(20)
            now[0] = 131.
            progress.update()
            messages = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual([m['completed'] for m in messages], [0, 20, 20])
        self.assertTrue(all(set(m) == {'stage', 'completed', 'total', 'elapsed'} for m in messages))
        self.assertEqual(messages[-1]['elapsed'], 31.)

    def test_idle_scheduler_polls_progress_without_new_submissions(self):
        heartbeat = []
        from concurrent.futures import wait as real_wait
        attempts = [0]
        def delayed_wait(pending, **kwargs):
            self.assertEqual(kwargs['timeout'], 30)
            attempts[0] += 1
            if attempts[0] == 1:
                return set(), set(pending)
            return real_wait(pending, **kwargs)
        with patch.object(c, 'ProcessPoolExecutor', ImmediatePool), \
                patch.object(c, 'wait', side_effect=delayed_wait):
            result = list(c._bounded_results(lambda n:n, [(1,)], 4, lambda: None,
                                           heartbeat=lambda:heartbeat.append(True)))
        self.assertEqual(result, [((1,), 1)])
        self.assertEqual(len(heartbeat), 2)


if __name__ == '__main__':
    unittest.main()
