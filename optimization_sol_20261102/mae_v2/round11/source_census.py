#!/usr/bin/env python3
"""First P-C action: private path census, never dataset/exposure qualification.

No research-file body is opened by the census. Fixed, previously completed
control receipts are authenticated separately. This consumes the existing O
recovery, not its verifier/scorer. No sampling, download or inference permit is
returned. Private fixture hooks are deliberately absent from the CLI.
"""
import hashlib
import json
import os
from pathlib import Path
import stat
import sys

sys.dont_write_bytecode = True
BASE = Path(__file__).resolve().parents[1]
REPO = BASE.parents[1]
PREFIX = 'optimization_sol_20261102/mae_v2/'
OUTPUT = PREFIX + 'round11/preparation/inventory/source_census.json'
MAX_FILE = 64 * 1024 * 1024
MAX_ENTRIES = 250000
CONTROL_PINS = {
    'round11/DESIGN.md': '63d0690e20f463fff2f74e697e4d72901947a1af6c31bcce4c571b72dd78370a',
    'round11/retrospective/REVIEW.md': 'b82782a6858caeae195acb89037f4bf72604d8d30bcbcbd67a2d994f3907e20e',
    'round11/evidence/github_completed_O_backup.json': '42c17727ae34417dfbe3a745eeefb81ebf0cffef4526297378ab7fbd6dbbeabc',
    'round10/evidence/postscore_guard_recovery.json': '64f8539ce65917a346ae74bd0c3961d8d78744bb6ea07429d42577ae9e20d1a4',
}
# These directories are inventoried as exclusions, never silently traversed.
# In particular, this does not certify that noncanonical copies had no inputs.
EXCLUDED_NAMES = {'.git', '.venv', '__pycache__', '.pytest_cache', '.codex', '.agents', '.aws'}
EXCLUDED_RELATIVE = {
    PREFIX + 'backups',
    PREFIX + 'round11/preparation/inventory',
}
LEGACY_MANIFESTS = (
    'DietAI24/data/dev_manifests/asa24_dev10.csv',
    'DietAI24/data/reproduce_manifests/paper50_all.csv',
    'DietAI24_mac_snapshot_20261022/data/reproduce_manifests/paper50_all.csv',
    'DietAI24_mac_snapshot_20261022/data/nutrition5k/smoke_manifest.csv',
)


def require(value, code):
    if not value:
        raise ValueError(code)


def encoded(value):
    return (json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + '\n').encode()


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def decode(raw):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, 'duplicate_control_json_key')
            result[key] = value
        return result
    def nonfinite(_):
        raise ValueError('nonfinite_control_json')
    return json.loads(raw, object_pairs_hook=unique, parse_constant=nonfinite)


def directory_fd(path):
    """Acquire every absolute directory component without following links."""
    path = Path(path)
    require(path.is_absolute() and '..' not in path.parts, 'absolute_directory_required')
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    fd = os.open('/', flags)
    try:
        for part in path.parts[1:]:
            child = os.open(part, flags, dir_fd=fd)
            os.close(fd)
            fd = child
        result, fd = fd, None
        return result
    finally:
        if fd is not None:
            os.close(fd)


def same_directory(path, original_fd):
    fresh = directory_fd(path)
    try:
        old, new = os.fstat(original_fd), os.fstat(fresh)
        return (old.st_dev, old.st_ino) == (new.st_dev, new.st_ino)
    finally:
        os.close(fresh)


def bounded_read(base, relative):
    relative = Path(relative)
    require(not relative.is_absolute() and '..' not in relative.parts, 'unsafe_control_path')
    path = base / relative
    require(path.resolve() == path, 'linked_control_path')
    parent = directory_fd(path.parent)
    try:
        fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
        try:
            info = os.fstat(fd)
            require(stat.S_ISREG(info.st_mode) and info.st_size <= MAX_FILE, 'bounded_regular_control_required')
            with os.fdopen(fd, 'rb', closefd=False) as stream:
                raw = stream.read(MAX_FILE + 1)
            require(len(raw) <= MAX_FILE, 'control_size_exceeded')
            current = os.stat(path.name, dir_fd=parent, follow_symlinks=False)
            require((current.st_dev, current.st_ino) == (info.st_dev, info.st_ino)
                    and same_directory(path.parent, parent), 'control_path_changed')
            return raw
        finally:
            os.close(fd)
    finally:
        os.close(parent)


def control_evidence(base, pins):
    require(set(pins) == set(CONTROL_PINS), 'complete_control_pins_required')
    hashes = {}
    values = {}
    def read(relative, expected):
        raw = bounded_read(base, relative)
        require(sha(raw) == expected, 'phase_control_changed')
        hashes[relative] = expected
        return raw
    for relative, expected in pins.items():
        raw = read(relative, expected)
        if relative.endswith('.json'):
            values[relative] = decode(raw)
    recovery = values['round10/evidence/postscore_guard_recovery.json']
    backup = values['round11/evidence/github_completed_O_backup.json']
    require(recovery.get('status') == 'O_sealed_diagnostic_reverified'
            and recovery.get('api_calls') == 0 and recovery.get('validation_opened') is False
            and recovery.get('recomputed_score') is False and recovery.get('recomputed_diagnostic') is False,
            'completed_O_recovery_required')
    require(backup.get('status') == 'completed_O_failure_backup_remote_verified'
            and backup.get('public_commit') == '42a8721322e98f2dda4fab66949f39090c3dc2f7'
            and backup.get('credential_matches') == 0 and backup['O']['accepted'] is False,
            'completed_O_safe_backup_required')
    evidence = recovery['completed_O_evidence']
    for field, relative in (
        ('freeze_sha256', 'round10/prepared/freeze.json'),
        ('development_completion_sha256', 'round10/runs/development/completion.json'),
        ('identities_completion_sha256', 'round10/runs/identities/completion.json'),
        ('scoring_completion_sha256', 'round10/runs/scoring/completion.json'),
        ('verification_sha256', 'round10/runs/verification.json'),
        ('checkpoint_sha256', 'round10/development_checkpoint.json'),
    ):
        read(relative, evidence[field])
    read('round10/diagnostics/completed_o/completion.json', recovery['diagnostic_completion_sha256'])
    for relative, expected in recovery['recovery_source_pins'].items():
        require(relative in ('round10/postscore/guarded_diagnose_o.py',
                            'round10/postscore/reverify_sealed_o.py', 'round11/o_completion.py'),
                'unregistered_recovery_source')
        read(relative, expected)
    # This is an anchor check, not a second full store/proof replay.
    # The recorded recovery is the provenance for the already completed O work.
    return hashes


def census(repo):
    """List path types/sizes only; a linked directory remains an unresolved entry."""
    result = []
    def walk(directory_fd, prefix=''):
        with os.scandir(directory_fd) as iterator:
            entries = []
            for entry in iterator:
                require(len(entries) < MAX_ENTRIES - len(result), 'census_entry_bound_exceeded')
                entries.append(entry)
        entries.sort(key=lambda entry: entry.name)
        for entry in entries:
            relative = prefix + entry.name
            require(len(result) < MAX_ENTRIES, 'census_entry_bound_exceeded')
            # Credential names are counted, without preserving names or sizes.
            if entry.name.startswith('.env') or entry.name in ('credentials', 'credentials.json'):
                result.append({'kind': 'credential_name_excluded'})
                continue
            if entry.name in EXCLUDED_NAMES or relative in EXCLUDED_RELATIVE:
                result.append({'path': relative, 'kind': 'excluded'})
                continue
            info = entry.stat(follow_symlinks=False)
            if stat.S_ISLNK(info.st_mode):
                kind = 'symlink_unresolved'
            elif stat.S_ISDIR(info.st_mode):
                kind = 'directory'
            elif stat.S_ISREG(info.st_mode):
                kind = 'file'
            else:
                kind = 'special_unresolved'
            row = {'path': relative, 'kind': kind}
            if kind == 'file':
                row['bytes'] = info.st_size
            result.append(row)
            if kind == 'directory':
                child_fd = os.open(entry.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                                   dir_fd=directory_fd)
                try:
                    captured = os.fstat(child_fd)
                    require((captured.st_dev, captured.st_ino) == (info.st_dev, info.st_ino),
                            'census_directory_changed')
                    walk(child_fd, relative + '/')
                finally:
                    os.close(child_fd)
    root_fd = os.open(repo, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        info = os.fstat(root_fd)
        walk(root_fd)
        current = os.stat(repo, follow_symlinks=False)
        require((current.st_dev, current.st_ino) == (info.st_dev, info.st_ino), 'census_root_changed')
    finally:
        os.close(root_fd)
    return result


def legacy_presence(repo):
    rows = []
    for relative in LEGACY_MANIFESTS:
        path = repo.parent / relative
        try:
            info = path.lstat()
        except FileNotFoundError:
            rows.append({'path': relative, 'status': 'missing_unresolved'})
            continue
        status = ('regular_unopened' if path.resolve() == path and stat.S_ISREG(info.st_mode)
                  else 'linked_or_special_unresolved')
        rows.append({'path': relative, 'status': status})
    return rows


def _build_at(repo, base, pins):
    """Private fixture interface. This does not write anything."""
    repo, base = Path(repo), Path(base)
    require(repo.is_absolute() and repo.resolve() == repo
            and base == repo / PREFIX.rstrip('/'), 'canonical_census_roots_required')
    hashes = control_evidence(base, pins)
    entries = census(repo)
    legacy = legacy_presence(repo)
    require(control_evidence(base, pins) == hashes, 'phase_controls_changed_during_census')
    require(census(repo) == entries and legacy_presence(repo) == legacy,
            'census_changed_during_capture')
    return {
        'schema_version': 1,
        'status': 'path_census_complete_not_exposure_closure',
        'control_sha256': hashes,
        'entries': entries,
        'legacy_manifest_presence': legacy,
        'research_file_bodies_opened': 0,
        'fresh_O_store_replay': False,
        'previous_completed_O_recovery_consumed': True,
        'validation_content_opened': False,
        'exposure_complete': False,
        'source_association_complete': False,
        'new_samples_selected': 0,
        'new_downloads': 0,
        'api_calls': 0,
        'grants_sampling_download_or_inference': False,
        'limitations': [
            'path metadata only; no actual request or pixel admission inferred',
            'excluded directories and missing legacy manifests require explicit disposition',
            'O anchors checked; original full recovery and scoring were not repeated',
            'candidate eligibility and target parsing remain forbidden',
        ],
    }


def isolated_network(raw):
    try:
        lines = raw.decode('ascii').strip().splitlines()
        fields = [part.strip() for part in lines[0].split('|')]
        header = [part.split() for part in lines[1].split('|')]
        name, sep, counters = lines[2].rpartition(':')
    except (UnicodeDecodeError, IndexError, AttributeError):
        return False
    return (len(lines) == 3 and fields == ['Inter-', 'Receive', 'Transmit']
            and header == [['face'], ['bytes', 'packets', 'errs', 'drop', 'fifo', 'frame', 'compressed', 'multicast'],
                           ['bytes', 'packets', 'errs', 'drop', 'fifo', 'colls', 'carrier', 'compressed']]
            and bool(sep) and name.strip() == 'lo' and len(counters.split()) == 16
            and all(value.isdecimal() for value in counters.split()))


def _write_at(repo, relative, value):
    """Private fixture hook; production supplies only the fixed OUTPUT path."""
    relative = Path(relative)
    require(not relative.is_absolute() and '..' not in relative.parts and len(relative.parts) > 1,
            'unsafe_census_output_path')
    raw = encoded(value)
    require(len(raw) <= MAX_FILE, 'census_output_size_exceeded')
    output = repo / relative
    require(output.resolve() == output, 'linked_census_output')
    parent = directory_fd(repo)
    try:
        for i, part in enumerate(relative.parts[:-1]):
            final = i == len(relative.parts) - 2
            try:
                os.mkdir(part, mode=0o700 if final else 0o755, dir_fd=parent)
            except FileExistsError:
                pass
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
            os.close(parent)
            parent = child
        require(stat.S_IMODE(os.fstat(parent).st_mode) == 0o700
                and same_directory(output.parent, parent), 'private_census_directory_required')
        fd = os.open(output.name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                     0o600, dir_fd=parent)
        # Any failed/partial exclusive artifact remains in its held private
        # parent. It is never replaced, unlinked or declared successful.
        with os.fdopen(fd, 'wb') as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        require(stat.S_IMODE(os.fstat(parent).st_mode) == 0o700
                and same_directory(output.parent, parent), 'census_output_parent_changed')
        os.fsync(parent)
    finally:
        os.close(parent)


def main():
    require(len(sys.argv) == 1, 'census_cli_overrides_refused')
    require(isolated_network(Path('/proc/self/net/dev').read_bytes()), 'isolated_network_namespace_required')
    output = REPO / OUTPUT
    require(output.resolve() == output and not output.exists(), 'fresh_census_output_required')
    value = _build_at(REPO, BASE, CONTROL_PINS)
    _write_at(REPO, OUTPUT, value)
    counts = {}
    for entry in value['entries']:
        counts[entry['kind']] = counts.get(entry['kind'], 0) + 1
    print(json.dumps({'status': value['status'], 'census_sha256': sha(encoded(value)),
                      'entry_counts': counts, 'api_calls': 0, 'new_samples_selected': 0,
                      'validation_content_opened': False, 'exposure_complete': False,
                      'grants_sampling_download_or_inference': False}, sort_keys=True))


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print(json.dumps({'status': 'source_census_refused', 'error_type': type(exc).__name__}))
        raise SystemExit(1)
