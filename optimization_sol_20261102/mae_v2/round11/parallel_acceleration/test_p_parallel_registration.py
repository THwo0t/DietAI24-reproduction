"""Private temporary-root gate tests; no real state, process, credentials or API."""
from copy import deepcopy
import fcntl
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import p_parallel_registration as registration
from opt_provider import fingerprint, sha


class RegistrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.write(registration.SCIENCE_FREEZE, {'synthetic':'science'})
        self.write(registration.DIRECTORY+'/synthetic.py', {'synthetic':'source'})
        for relative in registration.STATE_PATHS:
            self.write(relative+'/existing.json', {'synthetic':'preserved-state'})
        self.binding = fingerprint({'synthetic':'binding'})
        self.engineering = {'schema_version':1, 'science_freeze_sha256':sha(self.root/registration.SCIENCE_FREEZE),
            'science_binding_sha256':self.binding, 'source_files':registration._source_files(self.root),
            'state_paths':registration.STATE_PATHS, 'allowed_workers':registration.WORKERS}
        self.write(registration.FREEZE, self.engineering)
        self.review = {'schema_version':1, 'engineering_sha256':fingerprint(self.engineering),
            'status':'approved', 'unresolved_p1_p2':0, 'reviewer':'synthetic reviewer', 'reviewed_at':'synthetic time'}
        self.write(registration.REVIEW, self.review)
        process = {'pid':43210, 'start_time':'synthetic-startticks', 'command_sha256':fingerprint('synthetic command')}
        self.stop = {'schema_version':1, 'original_process':process, 'observer':'host_root',
            'method':'host_proc_startticks_and_exit', 'exit_observed':True, 'observed_at':'synthetic time'}
        self.write(registration.STOP_EVIDENCE, self.stop)
        self.receipt = {'schema_version':1, 'engineering_sha256':fingerprint(self.engineering),
            'science_binding_sha256':self.binding, 'original_process':process,
            'original_process_stopped':True, 'quiescent':True, 'pending_reservations':0,
            'state_tree_sha256':registration._state_tree(self.root),
            'stop_evidence_sha256':sha(self.root/registration.STOP_EVIDENCE),
            'attested_by':'synthetic host root', 'attested_at':'synthetic time'}
        self.write(registration.RECEIPT, self.receipt)

    def write(self, relative, value):
        path = self.root/relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value))

    def verify(self):
        return registration._verify(self.engineering, self.root, self.binding)

    def authorize(self, workers=4, paid=True):
        return registration._authorize(self.engineering, workers, paid, self.root)

    def test_verified_gate_and_explicit_paid_continuation(self):
        self.assertTrue(self.verify())
        for workers in (4, 8, 16, 32):
            self.assertTrue(self.authorize(workers))
        with self.assertRaisesRegex(ValueError, 'paid_flag'):
            self.authorize(paid=False)
        with self.assertRaisesRegex(ValueError, 'workers'):
            self.authorize(workers=True)

    def test_missing_review_or_engineering_freeze_fails_closed(self):
        for relative in (registration.REVIEW, registration.FREEZE):
            path = self.root/relative
            saved = path.read_bytes()
            path.unlink()
            with self.assertRaisesRegex(ValueError, 'required_gate_missing'):
                self.verify()
            path.write_bytes(saved)
        self.review['unresolved_p1_p2'] = 1
        self.write(registration.REVIEW, self.review)
        with self.assertRaisesRegex(ValueError, 'review_required'):
            self.verify()

    def test_science_new_source_and_state_path_change_refused(self):
        self.write(registration.DIRECTORY+'/additional.py', {'unexpected':True})
        with self.assertRaisesRegex(ValueError, 'source_changed'):
            self.verify()
        (self.root/registration.DIRECTORY/'additional.py').unlink()
        self.write(registration.SCIENCE_FREEZE, {'changed':True})
        with self.assertRaisesRegex(ValueError, 'science_freeze_changed'):
            self.verify()
        altered = deepcopy(self.engineering)
        altered['state_paths'] = ['other-ledger']
        with self.assertRaisesRegex(ValueError, 'scope_changed'):
            registration._verify(altered, self.root, self.binding)

    def test_pid_absence_is_never_a_stop_authorization(self):
        with patch('os.kill', side_effect=AssertionError('PID probing forbidden')):
            self.assertTrue(self.authorize())
            self.stop['exit_observed'] = False
            self.write(registration.STOP_EVIDENCE, self.stop)
            self.receipt['stop_evidence_sha256'] = sha(self.root/registration.STOP_EVIDENCE)
            self.write(registration.RECEIPT, self.receipt)
            with self.assertRaisesRegex(ValueError, 'host_exit_evidence'):
                self.authorize()
        (self.root/registration.RECEIPT).unlink()
        with self.assertRaisesRegex(ValueError, 'required_gate_missing'):
            self.authorize()

    def test_pending_and_changed_continuation_state_refused(self):
        self.receipt['pending_reservations'] = 1
        self.write(registration.RECEIPT, self.receipt)
        with self.assertRaisesRegex(ValueError, 'stop_and_quiescence'):
            self.authorize()
        self.receipt['pending_reservations'] = 0
        self.write(registration.RECEIPT, self.receipt)
        self.write(registration.STATE_PATHS[0]+'/existing.json', {'changed':'state'})
        with self.assertRaisesRegex(ValueError, 'continuation_state_changed'):
            self.authorize()

    def test_not_yet_created_adapter_is_bound_as_absent(self):
        relative = registration.STATE_PATHS[-1]
        directory = self.root/relative
        (directory/'existing.json').unlink()
        directory.rmdir()
        self.receipt['state_tree_sha256'] = registration._state_tree(self.root)
        self.write(registration.RECEIPT, self.receipt)
        self.assertTrue(self.authorize())
        self.assertFalse(directory.exists())
        directory.mkdir()
        with self.assertRaisesRegex(ValueError, 'continuation_state_changed'):
            self.authorize()

    def test_public_authorization_requires_controller_lock(self):
        with self.assertRaisesRegex(ValueError, 'controller_lock_required'):
            registration.authorize_continuation(self.engineering, 4, True)

    def test_exclusive_lock_and_symlink_refusal(self):
        with patch.object(registration, 'ROOT', self.root):
            with registration.controller_lock():
                with (self.root/registration.DIRECTORY/'controller.lock').open('r+') as competing:
                    with self.assertRaises(BlockingIOError):
                        fcntl.flock(competing, fcntl.LOCK_EX | fcntl.LOCK_NB)
                with self.assertRaisesRegex(ValueError, 'already_locked'):
                    with registration.controller_lock():
                        pass
        target = self.root/registration.DIRECTORY/'synthetic.py'
        target.unlink()
        target.symlink_to(self.root/registration.SCIENCE_FREEZE)
        with self.assertRaisesRegex(ValueError, 'source_invalid'):
            registration._source_files(self.root)


if __name__ == '__main__':
    unittest.main()
