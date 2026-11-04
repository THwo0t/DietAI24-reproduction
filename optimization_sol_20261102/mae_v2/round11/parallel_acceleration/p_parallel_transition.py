"""Host-only, zero-inflight handoff of the existing P process and state.

No request, credential reader, label decoder, state reset, or source rewrite.
The old process keeps running until all engineering gates have passed.
"""
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import signal
import sys
import time

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import p_parallel_registration as registration
from opt_provider import ROOT, fingerprint, sha, stamp

OLD_PID = 669614
OLD_ENTRY = ROOT/'round11/launch/P_integrity2/execution.py'
OLD_LAUNCH = ROOT/'round11/launch/P_integrity2/launch.json'


def require(ok, code):
    if not ok:
        raise ValueError(code)


def process_identity(pid):
    """Read only the intended host process; never return its command text."""
    directory = Path('/proc')/str(pid)
    raw = (directory/'stat').read_text()
    fields = raw[raw.rfind(')')+2:].split()
    command = (directory/'cmdline').read_bytes()
    parts = command.rstrip(b'\0').split(b'\0')
    require(parts and os.fsencode(OLD_ENTRY) in parts,
            'P_parallel_original_process_command_changed')
    return {'pid':pid, 'start_time':fields[19],
            'command_sha256':hashlib.sha256(command).hexdigest()}, fields[0]


def exited(pid, original):
    try:
        raw = (Path('/proc')/str(pid)/'stat').read_text()
    except FileNotFoundError:
        return True
    fields = raw[raw.rfind(')')+2:].split()
    require(fields[19] == original['start_time'], 'P_parallel_pid_reused')
    return fields[0] in ('Z', 'X')


def write_once(path, value):
    require(path.resolve() == path and path.parent.resolve() == path.parent,
            'P_parallel_receipt_path_changed')
    raw = (json.dumps(value, sort_keys=True, allow_nan=False)+'\n').encode()
    fd = os.open(path, os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'wb') as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    fd = os.open(path.parent, os.O_RDONLY|os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def pending(state):
    return {entry['id'] for entry in state['reservations']} - set(state['outcomes'])


@contextmanager
def admission_boundary(path):
    require(path.is_file() and path.resolve() == path,
            'P_parallel_existing_admission_lock_required')
    fd = os.open(path, os.O_RDWR|os.O_NOFOLLOW)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)


def transition():
    engineering = registration.runtime_engineering()
    metadata = json.loads(OLD_LAUNCH.read_bytes())
    require(metadata['pid'] == OLD_PID and metadata['freeze_sha256'] ==
            engineering['science_freeze_sha256'] and metadata['science_sha256'] ==
            engineering['science_binding_sha256'], 'P_parallel_old_launch_binding_changed')
    require(not (ROOT/registration.RECEIPT).exists() and
            not (ROOT/registration.STOP_EVIDENCE).exists(), 'P_parallel_transition_already_recorded')
    original, status = process_identity(OLD_PID)
    require(status not in ('Z', 'X'), 'P_parallel_old_process_already_exited')
    directory = ROOT/'round11/provider/P'
    with registration.controller_lock():
        deadline = time.monotonic()+55
        while True:
            require(time.monotonic() < deadline, 'P_parallel_no_quiescent_boundary_preserve_old')
            with admission_boundary(directory/'locks/admission.lock'):
                state = json.loads((directory/'admission.json').read_bytes())
                require(state['binding'] == engineering['science_binding_sha256'],
                        'P_parallel_ledger_binding_changed')
                if not pending(state):
                    current, status = process_identity(OLD_PID)
                    require(current == original and status not in ('Z', 'X'),
                            'P_parallel_original_process_identity_changed')
                    require(all(sha(directory/'outcomes'/f'{rid}.json') == digest
                                for rid, digest in state['outcomes'].items()),
                            'P_parallel_existing_outcome_anchor_changed')
                    # Holding admission prevents the original writer reserving
                    # a new request. All past reservations have durable answers.
                    os.kill(OLD_PID, signal.SIGTERM)
                    while not exited(OLD_PID, original):
                        require(time.monotonic() < deadline, 'P_parallel_stop_wait_timeout')
                        time.sleep(.05)
                    after = json.loads((directory/'admission.json').read_bytes())
                    require(after == state and not pending(after),
                            'P_parallel_state_changed_under_transition_lock')
                    break
            # Never hold admission while waiting for an active request to
            # persist: publishing its anchor also needs this same lock.
            time.sleep(.1)
        stop = {'schema_version':1, 'original_process':original, 'observer':'host_root',
                'method':'host_proc_startticks_and_exit', 'exit_observed':True,
                'observed_at':stamp()}
        write_once(ROOT/registration.STOP_EVIDENCE, stop)
        receipt = {'schema_version':1, 'engineering_sha256':fingerprint(engineering),
            'science_binding_sha256':engineering['science_binding_sha256'],
            'original_process':original, 'original_process_stopped':True,
            'quiescent':True, 'pending_reservations':0,
            'state_tree_sha256':registration._state_tree(ROOT),
            'stop_evidence_sha256':sha(ROOT/registration.STOP_EVIDENCE),
            'attested_by':'host_root_quiescent_transition', 'attested_at':stamp()}
        write_once(ROOT/registration.RECEIPT, receipt)
    return {'status':'P_parallel_quiescent_transition_complete',
            'preserved_reservations':len(state['reservations']),
            'preserved_outcomes':len(state['outcomes']), 'pending_reservations':0}


if __name__ == '__main__':
    try:
        print(json.dumps(transition(), sort_keys=True), flush=True)
    except BaseException as error:
        print(json.dumps({'status':'P_parallel_transition_refused_preserve_state',
                          'error_type':type(error).__name__}), flush=True)
        raise SystemExit(1)
