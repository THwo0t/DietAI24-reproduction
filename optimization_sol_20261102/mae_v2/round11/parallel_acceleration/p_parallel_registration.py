"""Read-only engineering gates for continuation of the same frozen P state.

This module never creates a freeze, review, stop receipt, Provider, or old
process action. A host-side reviewer must supply those attestations first.
"""
from contextlib import contextmanager
from copy import deepcopy
import fcntl
import json
import os
from pathlib import Path
import sys

BASE = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(BASE), *(str(BASE/p) for p in
    ('src', 'round7/src', 'round8/src', 'round10', 'round11'))]
from opt_provider import ROOT, sha, fingerprint

DIRECTORY = 'round11/parallel_acceleration'
FREEZE = DIRECTORY+'/engineering_freeze.json'
REVIEW = DIRECTORY+'/engineering_review.json'
RECEIPT = DIRECTORY+'/continuation_receipt.json'
STOP_EVIDENCE = DIRECTORY+'/stop_evidence.json'
SCIENCE_FREEZE = 'round11/prepared/freeze.json'
STATE_PATHS = ['round11/provider/P', 'round11/runs/identities',
               'round11/runs/development', 'round11/runs/conditional-adapter']
WORKERS = [4, 8, 16, 32]
_SCIENCE_BINDING = None
_LOCK_PID = None


def _require(ok, code):
    if not ok:
        raise ValueError(code)


def _digest(value):
    return type(value) is str and len(value) == 64 and all(c in '0123456789abcdef' for c in value)


def _path(root, relative):
    path = root/relative
    _require(root.is_absolute() and root.resolve() == root and path.resolve() == path,
             'P_parallel_noncanonical_or_symlink_path')
    return path


def _read(root, relative):
    path = _path(root, relative)
    _require(path.is_file(), 'P_parallel_required_gate_missing')
    try:
        value = json.loads(path.read_text())
    except (ValueError, UnicodeError):
        raise ValueError('P_parallel_gate_invalid_json') from None
    _require(type(value) is dict, 'P_parallel_gate_schema_changed')
    return value


def _source_files(root):
    directory = _path(root, DIRECTORY)
    paths = sorted(directory.rglob('*.py'))
    _require(paths and all(path.is_file() and path.resolve() == path for path in paths),
             'P_parallel_engineering_source_invalid')
    return {str(path.relative_to(root)):sha(path) for path in paths}


def _state_tree(root):
    """Host receipt commits to the exact continuing ledger/store bytes."""
    files, directories = {}, {}
    for index, relative in enumerate(STATE_PATHS):
        directory = _path(root, relative)
        if not directory.exists():
            _require(index != 0, 'P_parallel_existing_state_required')
            directories[relative] = 'absent'
            continue
        _require(directory.is_dir(), 'P_parallel_existing_state_required')
        directories[relative] = 'present'
        for path in sorted(directory.rglob('*')):
            _require(path.resolve() == path, 'P_parallel_state_symlink_forbidden')
            if path.is_file():
                files[str(path.relative_to(root))] = sha(path)
            else:
                _require(path.is_dir(), 'P_parallel_state_special_file_forbidden')
    _require(files, 'P_parallel_existing_state_required')
    return fingerprint({'directories':directories, 'files':files})


def _science_binding():
    global _SCIENCE_BINDING
    if _SCIENCE_BINDING is None:
        from context_p import runtime_context
        ctx = runtime_context()
        ctx.verify_sources()
        _SCIENCE_BINDING = fingerprint(ctx.binding)
    return _SCIENCE_BINDING


def _verify(engineering, root, science_binding):
    _require(type(engineering) is dict and set(engineering) == {
        'schema_version', 'science_freeze_sha256', 'science_binding_sha256',
        'source_files', 'state_paths', 'allowed_workers'}, 'P_parallel_engineering_schema_changed')
    _require(type(engineering['schema_version']) is int and engineering['schema_version'] == 1
        and engineering['state_paths'] == STATE_PATHS and engineering['allowed_workers'] == WORKERS,
        'P_parallel_engineering_scope_changed')
    _require(engineering['science_binding_sha256'] == science_binding and _digest(science_binding)
        and _digest(engineering['science_freeze_sha256'])
        and sha(_path(root, SCIENCE_FREEZE)) == engineering['science_freeze_sha256'],
        'P_parallel_science_freeze_changed')
    _require(engineering['source_files'] == _source_files(root), 'P_parallel_engineering_source_changed')
    _require(_read(root, FREEZE) == engineering, 'P_parallel_write_once_freeze_changed')
    review = _read(root, REVIEW)
    _require(set(review) == {'schema_version', 'engineering_sha256', 'status',
                            'unresolved_p1_p2', 'reviewer', 'reviewed_at'}
        and type(review['schema_version']) is int and review['schema_version'] == 1
        and review['engineering_sha256'] == fingerprint(engineering)
        and review['status'] == 'approved'
        and type(review['unresolved_p1_p2']) is int and review['unresolved_p1_p2'] == 0
        and all(type(review[k]) is str and review[k].strip() for k in ('reviewer', 'reviewed_at')),
        'P_parallel_engineering_review_required')
    return True


def runtime_engineering():
    engineering = _read(ROOT, FREEZE)
    verify_engineering(engineering)
    return deepcopy(engineering)


def verify_engineering(engineering):
    return _verify(engineering, ROOT, _science_binding())


@contextmanager
def controller_lock():
    """Nonblocking exclusive flock; held through every worker exit and seal."""
    global _LOCK_PID
    _require(_LOCK_PID is None, 'P_parallel_controller_already_locked')
    path = _path(ROOT, DIRECTORY+'/controller.lock')
    fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError('P_parallel_controller_already_running') from None
        _LOCK_PID = os.getpid()
        yield
    finally:
        _LOCK_PID = None
        os.close(fd)


def _authorize(engineering, workers, allow_paid, root):
    _require(type(workers) is int and workers in WORKERS,
             'P_parallel_workers_must_be_4_8_16_or_32')
    _require(type(allow_paid) is bool, 'P_explicit_paid_flag_required')
    receipt = _read(root, RECEIPT)
    _require(set(receipt) == {'schema_version', 'engineering_sha256', 'science_binding_sha256',
        'original_process', 'original_process_stopped', 'quiescent', 'pending_reservations',
        'state_tree_sha256', 'stop_evidence_sha256', 'attested_by', 'attested_at'}
        and type(receipt['schema_version']) is int and receipt['schema_version'] == 1
        and receipt['engineering_sha256'] == fingerprint(engineering)
        and receipt['science_binding_sha256'] == engineering['science_binding_sha256']
        and receipt['original_process_stopped'] is True and receipt['quiescent'] is True
        and type(receipt['pending_reservations']) is int and receipt['pending_reservations'] == 0
        and all(type(receipt[k]) is str and receipt[k].strip() for k in ('attested_by', 'attested_at')),
        'P_parallel_host_stop_and_quiescence_receipt_required')
    process = receipt['original_process']
    _require(type(process) is dict and set(process) == {'pid', 'start_time', 'command_sha256'}
        and type(process['pid']) is int and process['pid'] > 0
        and type(process['start_time']) is str and process['start_time'].strip()
        and _digest(process['command_sha256']), 'P_parallel_original_process_identity_required')
    stop = _read(root, STOP_EVIDENCE)
    _require(_digest(receipt['stop_evidence_sha256']) and
        receipt['stop_evidence_sha256'] == sha(_path(root, STOP_EVIDENCE)) and
        set(stop) == {'schema_version', 'original_process', 'observer', 'method',
                      'exit_observed', 'observed_at'} and
        type(stop['schema_version']) is int and stop['schema_version'] == 1 and
        stop['original_process'] == process and stop['observer'] == 'host_root' and
        stop['method'] == 'host_proc_startticks_and_exit' and stop['exit_observed'] is True and
        type(stop['observed_at']) is str and stop['observed_at'].strip(),
        'P_parallel_host_exit_evidence_required')
    _require(_digest(receipt['state_tree_sha256']) and
             receipt['state_tree_sha256'] == _state_tree(root),
             'P_parallel_continuation_state_changed')
    complete = all(_path(root, relative+'/completion.json').is_file()
                   for relative in STATE_PATHS[1:])
    _require(complete or allow_paid, 'P_paid_flag_required_for_incomplete_batch')
    return True


def authorize_continuation(engineering, workers, allow_paid):
    _require(_LOCK_PID == os.getpid(), 'P_parallel_controller_lock_required')
    verify_engineering(engineering)
    return _authorize(engineering, workers, allow_paid, ROOT)
