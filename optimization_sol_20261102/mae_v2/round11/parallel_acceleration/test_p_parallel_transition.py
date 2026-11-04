"""Synthetic host handoff and detached execution tests; no real P PID/API."""
from contextlib import ExitStack, contextmanager, nullcontext
from pathlib import Path
from types import ModuleType, SimpleNamespace
import fcntl
import io
import json
import os
import runpy
import signal
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import p_parallel_transition as t
import p_parallel_execution as execution


class TransitionTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.directory = self.root/'round11/provider/P'
        (self.directory/'locks').mkdir(parents=True)
        (self.directory/'locks/admission.lock').touch()
        (self.directory/'outcomes').mkdir()
        self.outcome = self.directory/'outcomes/synthetic-response-uuid.json'
        self.outcome.write_text('{"synthetic":"durable response"}\n')
        self.state = {'binding':'science',
                      'reservations':[{'id':'synthetic-response-uuid'}],
                      'outcomes':{'synthetic-response-uuid':t.sha(self.outcome)}}
        self.admission = self.directory/'admission.json'
        self.save_state()
        self.engineering = {'science_freeze_sha256':'freeze', 'science_binding_sha256':'science'}
        self.launch = self.root/'launch.json'
        self.launch.write_text(json.dumps({'pid':t.OLD_PID,
            'freeze_sha256':'freeze','science_sha256':'science'}))
        self.original = {'pid':t.OLD_PID, 'start_time':'synthetic-startticks',
                         'command_sha256':'synthetic-command-hash'}
        self.registration = SimpleNamespace(runtime_engineering=lambda:self.engineering,
            RECEIPT='receipt.json', STOP_EVIDENCE='stop.json', controller_lock=nullcontext,
            _state_tree=lambda root:t.fingerprint(json.loads(self.admission.read_bytes())))
        self.kill = Mock()

    def save_state(self):
        self.admission.write_text(json.dumps(self.state))

    @contextmanager
    def wired(self, identity=None, sleep=None):
        with ExitStack() as stack:
            for target, value in [('ROOT',self.root), ('OLD_LAUNCH',self.launch),
                                  ('registration',self.registration)]:
                stack.enter_context(patch.object(t, target, value))
            process = stack.enter_context(patch.object(t, 'process_identity',
                return_value=(self.original, 'S')))
            if identity is not None:
                process.side_effect = identity
            stack.enter_context(patch.object(t, 'exited', return_value=True))
            stack.enter_context(patch.object(t.os, 'kill', self.kill))
            stack.enter_context(patch.object(t.time, 'monotonic', return_value=0.))
            stack.enter_context(patch.object(t.time, 'sleep', side_effect=sleep))
            yield

    def test_quiescent_transition_preserves_state_and_uuid_anchors(self):
        before = self.admission.read_bytes(), self.outcome.read_bytes()
        with self.wired():
            result = t.transition()
        self.kill.assert_called_once_with(t.OLD_PID, signal.SIGTERM)
        self.assertEqual(before, (self.admission.read_bytes(), self.outcome.read_bytes()))
        receipt = json.loads((self.root/'receipt.json').read_bytes())
        self.assertEqual(receipt['engineering_sha256'], t.fingerprint(self.engineering))
        self.assertEqual(receipt['state_tree_sha256'], t.fingerprint(self.state))
        self.assertEqual(receipt['stop_evidence_sha256'], t.sha(self.root/'stop.json'))
        self.assertEqual(receipt['original_process'], self.original)
        self.assertEqual(result['preserved_reservations'], 1)
        self.assertEqual(result['pending_reservations'], 0)

    def test_pending_releases_admission_before_waiting_and_does_not_kill(self):
        self.state['outcomes'] = {}
        self.save_state()
        waits = []
        def finish_pending(delay):
            self.kill.assert_not_called()
            fd = os.open(self.directory/'locks/admission.lock', os.O_RDWR)
            try:
                # A second open cannot acquire this if transition still holds it.
                fcntl.flock(fd, fcntl.LOCK_EX|fcntl.LOCK_NB)
                waits.append(delay)
                self.state['outcomes'] = {'synthetic-response-uuid':t.sha(self.outcome)}
                self.save_state()
            finally:
                os.close(fd)
        with self.wired(sleep=finish_pending):
            t.transition()
        self.assertEqual(waits, [.1])
        self.kill.assert_called_once_with(t.OLD_PID, signal.SIGTERM)

    def test_launch_binding_and_process_mismatch_never_signal(self):
        self.launch.write_text(json.dumps({'pid':-1,'freeze_sha256':'freeze','science_sha256':'science'}))
        with self.wired(), self.assertRaisesRegex(ValueError, 'old_launch_binding_changed'):
            t.transition()
        self.kill.assert_not_called()
        self.launch.write_text(json.dumps({'pid':t.OLD_PID,'freeze_sha256':'freeze','science_sha256':'science'}))
        different = {**self.original, 'start_time':'reused-pid'}
        with self.wired(identity=[(self.original,'S'),(different,'S')]), \
                self.assertRaisesRegex(ValueError, 'original_process_identity_changed'):
            t.transition()
        self.kill.assert_not_called()
        self.assertFalse((self.root/'receipt.json').exists())

    def test_host_exit_checks_startticks_and_zombie(self):
        def stat(state, start):
            fields = [state] + ['0']*18 + [start]
            return '123 (synthetic process with spaces) '+' '.join(fields)
        with patch.object(Path, 'read_text', return_value=stat('Z','old')):
            self.assertTrue(t.exited(123, {'start_time':'old'}))
        with patch.object(Path, 'read_text', return_value=stat('S','old')):
            self.assertFalse(t.exited(123, {'start_time':'old'}))
        with patch.object(Path, 'read_text', return_value=stat('Z','new')):
            with self.assertRaisesRegex(ValueError, 'pid_reused'):
                t.exited(123, {'start_time':'old'})
        with patch.object(Path, 'read_text', side_effect=FileNotFoundError):
            self.assertTrue(t.exited(123, {'start_time':'old'}))


class ExecutionTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.launch = self.root/'launch'
        self.launch.mkdir()
        self.engineering = {'science_freeze_sha256':'synthetic-freeze'}
        self.registration = ModuleType('p_parallel_registration')
        self.registration.runtime_engineering = lambda:self.engineering
        self.registration._digest = lambda value: type(value) is str and len(value) == 64
        self.controller = ModuleType('p_parallel_controller')
        self.controller.run = Mock(return_value={'status':'synthetic complete'})

    def test_postscore_uses_network_isolation_and_clean_environment(self):
        from adapter_p import CLEAN_ENV
        summary = {'status':'P_development_postscore_complete','rows':843,
                   'api_calls':0,'validation_opened':False,'selected_profile':None,
                   'private_result_sha256':'0'*64}
        def child(command, **kwargs):
            self.assertEqual(command, ['/usr/bin/unshare','-Urn',sys.executable,'-B',
                str(self.root/'round11/postscore_p.py')])
            self.assertEqual(kwargs['env'], dict(CLEAN_ENV))
            self.assertEqual(kwargs['cwd'], self.root)
            self.assertEqual(kwargs['stdin'], execution.subprocess.DEVNULL)
            self.assertIs(kwargs['stdout'], kwargs['stderr'])
            kwargs['stdout'].write((json.dumps(summary)+'\n').encode())
            return SimpleNamespace(returncode=0)
        with patch.object(execution, 'ROOT', self.root), \
                patch.object(execution, 'LAUNCH', self.launch), \
                patch.object(execution, 'registration', self.registration), \
                patch.dict(sys.modules, {'p_parallel_controller':self.controller}), \
                patch.object(execution.subprocess, 'run', side_effect=child) as run, \
                patch('sys.stdout', new_callable=io.StringIO):
            execution.execute()
        self.controller.run.assert_called_once_with(allow_paid=True, workers=32)
        run.assert_called_once()
        self.assertEqual(json.loads((self.launch/'terminal.json').read_bytes()), summary)

    def test_script_failure_emits_no_exception_message(self):
        sentinel = 'SYNTHETIC_PRIVATE_ERROR_SENTINEL'
        self.controller.run.side_effect = ValueError(sentinel)
        # run_path computes its own launch directory from __file__; intercept
        # only write_once, preserving its real exclusive/durable file behavior.
        real_write = t.write_once
        def local_write(path, value):
            real_write(self.launch/path.name, value)
        with patch.dict(sys.modules, {'p_parallel_registration':self.registration,
                                     'p_parallel_controller':self.controller}), \
                patch.object(t, 'write_once', side_effect=local_write), \
                patch('sys.stdout', new_callable=io.StringIO) as output, \
                self.assertRaises(SystemExit):
            runpy.run_path(str(HERE/'p_parallel_execution.py'), run_name='__main__')
        terminal = (self.launch/'terminal.json').read_text()
        self.assertNotIn(sentinel, terminal + output.getvalue())
        self.assertEqual(json.loads(terminal)['error_type'], 'ValueError')

    def test_secondary_receipt_failure_does_not_escape_private_exception(self):
        sentinel = 'SYNTHETIC_PRIVATE_SECONDARY_SENTINEL'
        self.controller.run.side_effect = ValueError(sentinel)
        real_write = t.write_once
        def fail_terminal(path, value):
            if path.name == 'terminal.json':
                raise OSError('synthetic receipt failure')
            real_write(self.launch/path.name, value)
        with patch.dict(sys.modules, {'p_parallel_registration':self.registration,
                                     'p_parallel_controller':self.controller}), \
                patch.object(t, 'write_once', side_effect=fail_terminal), \
                patch('sys.stdout', new_callable=io.StringIO) as output, \
                patch('sys.stderr', new_callable=io.StringIO) as errors, \
                self.assertRaises(SystemExit):
            runpy.run_path(str(HERE/'p_parallel_execution.py'), run_name='__main__')
        self.assertNotIn(sentinel, output.getvalue()+errors.getvalue())
        self.assertIn('P_parallel_terminal_receipt_write_failed', output.getvalue())
        self.assertEqual(errors.getvalue(), '')


if __name__ == '__main__':
    unittest.main()
