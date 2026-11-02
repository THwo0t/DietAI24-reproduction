#!/usr/bin/env python3
"""Linux fixture installation rehearsal or exact complete-candidate check.

Reports/profile are synthetic fixtures in both modes, never final deliverables.
The default mode mocks uv operations and reuses the existing fixed interpreter.
--real-install executes setup.sh, downloads its fixed uv/Python, and syncs a new
venv. All work/cache files stay in a unique directory under mae_v2; only that
directory is removed. Machine-readable evidence and installer output remain
under evidence/. --candidate uses an existing fixed interpreter and the actual
ZIP reports/profile, without synthetic replacement, installation or downloads.
No .env or research cohort is read.
"""
import argparse
from datetime import datetime, timezone
import importlib.util
import importlib.metadata
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shlex
import stat
import subprocess
import sys
import tempfile
import zipfile

import demo
import package_demo as package


GUARD = '''import builtins
import io
import sys
from pathlib import Path
_original = builtins.open
_io_original = io.open
_path_original = Path.open
def _deny(path):
    if isinstance(path, (str, Path)):
        parts = Path(path).parts
        if Path(path).name == '.env' or 'cohorts' in parts or 'freeze' in parts or 'sealed' in parts:
            raise AssertionError('private input read attempted')
def _guard(path, *args, **kwargs):
    _deny(path)
    return _original(path, *args, **kwargs)
def _io_guard(path, *args, **kwargs):
    _deny(path)
    return _io_original(path, *args, **kwargs)
def _path_guard(path, *args, **kwargs):
    _deny(path)
    return _path_original(path, *args, **kwargs)
builtins.open = _guard
io.open = _io_guard
Path.open = _path_guard
sys._mae_demo_private_read_guard = True
'''

VERSION_PROBE = '''import importlib.metadata as metadata
import json
from pathlib import Path
import sys
assert getattr(sys, '_mae_demo_private_read_guard', False)
assert sys.version_info[:3] == (3,10,13)
expected={}
for line in Path('requirements-demo.txt').read_text().splitlines():
    if line.strip() and not line.startswith('#'):
        name, version=line.split(';')[0].strip().split('==')
        expected[name]=version
actual={name:metadata.version(name) for name in expected}
assert actual==expected
try:
    Path('../.env').read_text()
except AssertionError:
    blocked=True
else:
    raise AssertionError('private read guard is inactive')
print(json.dumps({'python':'.'.join(map(str,sys.version_info[:3])),
    'packages':actual,'prefix':sys.prefix,'base_prefix':sys.base_prefix,
    'executable':sys.executable,'private_read_guard_active':blocked}))
'''

# This is a regression guard, not an OS filesystem sandbox. The separate Linux
# network namespace is mandatory for every exact-candidate Python check.
CANDIDATE_GUARD = GUARD + '''
import os
def _audit_guard(event, args):
    if event == 'open' and isinstance(args[0], (str, bytes, os.PathLike)):
        path = Path(os.fsdecode(args[0]))
        for value in (path, path.resolve()):
            if (value.name.startswith('.env') or
                set(value.parts) & {'cohorts', 'freeze', 'sealed'} or
                any(part in value.parts for part in ('asa24', 'nutrition5k'))):
                raise AssertionError('private input read attempted')
    if event.startswith('socket.') or event in ('subprocess.Popen', 'os.system', 'os.posix_spawn'):
        raise AssertionError('network or subprocess attempted')
sys.addaudithook(_audit_guard)
sys._mae_demo_candidate_guard = True
'''

CANDIDATE_PROBE = '''import importlib.metadata as metadata
import json, os, socket, sys
from pathlib import Path
assert sys.version_info[:3] == (3,10,13) and sys.flags.no_user_site
assert getattr(sys, '_mae_demo_candidate_guard', False)
expected = json.loads(sys.argv[1])
actual = {name: metadata.version(name) for name in expected}
assert actual == expected
checks = 0
for operation in (lambda: Path('../.env').read_bytes(),
                  lambda: os.open(b'../.env', os.O_RDONLY),
                  lambda: socket.socket()):
    try:
        operation()
    except AssertionError:
        checks += 1
assert checks == 3
import numpy as np
vectors = np.load('data/vectors/embeddings.npy', allow_pickle=False, mmap_mode='r')
assert vectors.shape == (5624,3072)
print(json.dumps({'python': '.'.join(map(str,sys.version_info[:3])),
    'packages': actual, 'no_user_site': bool(sys.flags.no_user_site),
    'private_and_network_guard_probes_passed': checks, 'vector_shape': list(vectors.shape)}))
'''

MAX_CANDIDATE_BYTES = 512 * 1024 * 1024


def _strict_json(data):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('Duplicate JSON key')
            result[key] = value
        return result
    return json.loads(data, object_pairs_hook=unique,
        parse_constant=lambda _: (_ for _ in ()).throw(ValueError('Nonfinite JSON')))


def candidate_payload(archive_path, expected_sha256):
    """Validate and return exactly the same in-memory ZIP bytes to be extracted."""
    path = Path(archive_path).absolute()
    if (not re.fullmatch('[0-9a-f]{64}', expected_sha256 or '') or path.suffix != '.zip'
            or any(p.is_symlink() for p in (path, *path.parents))
            or set(path.parts) & {'cohorts', 'freeze', 'sealed'} or not path.is_file()
            or path.stat().st_size > MAX_CANDIDATE_BYTES):
        raise ValueError('Candidate path, size or expected checksum is invalid')
    payload = path.read_bytes()
    if len(payload) > MAX_CANDIDATE_BYTES or hashlib.sha256(payload).hexdigest() != expected_sha256:
        raise ValueError('Candidate archive checksum differs')
    required = set(package.SOURCE_REQUIRED + demo.RUNTIME_FILES) | {package.RELEASE_NAME}
    allowed = required | set(package.SOURCE_OPTIONAL) | {package.MANIFEST_NAME}
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        entries = archive.infolist()
        names = [item.filename for item in entries]
        if (archive.comment or len(names) != len(set(names)) or not required.issubset(names)
                or set(names) - allowed or package.MANIFEST_NAME not in names
                or sum(item.file_size for item in entries) > MAX_CANDIDATE_BYTES):
            raise ValueError('Candidate inventory or expansion budget differs')
        for item in entries:
            if (item.orig_filename != item.filename or not stat.S_ISREG(item.external_attr >> 16) or item.flag_bits & 1
                    or item.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED)):
                raise ValueError('Candidate contains a nonregular or unsupported member')
        if archive.getinfo(package.MANIFEST_NAME).file_size > 1024 * 1024:
            raise ValueError('Candidate manifest exceeds the budget')
        manifest_bytes = archive.read(package.MANIFEST_NAME)
        manifest = _strict_json(manifest_bytes)
        if (not isinstance(manifest, dict) or type(manifest.get('schema_version')) is not int
                or manifest.get('schema_version') != 2 or manifest.get('kind') != 'complete'
                or set(manifest.get('files', {})) != set(names) - {package.MANIFEST_NAME}):
            raise ValueError('Candidate manifest schema or inventory differs')
        files, actual_bytes = {}, len(manifest_bytes)
        for name in sorted(manifest['files']):
            data = archive.read(name)
            actual_bytes += len(data)
            expected = manifest['files'][name]
            if (actual_bytes > MAX_CANDIDATE_BYTES or type(expected.get('bytes')) is not int
                    or expected != {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}):
                raise ValueError('Candidate member checksum or size differs')
            package.inspect_member(name, data)
            files[name] = data
        if manifest != package._manifest(files, 'complete'):
            raise ValueError('Candidate manifest metadata differs')
        if files['requirements-demo.txt'] != demo.safe_file(demo.ROOT, 'requirements-demo.txt').read_bytes():
            raise ValueError('Candidate dependency pins differ from the trusted runner')
        files[package.MANIFEST_NAME] = manifest_bytes
    return files, {'archive_sha256': expected_sha256, 'archive_bytes': len(payload),
        'manifest_sha256': hashlib.sha256(manifest_bytes).hexdigest(),
        'member_count': len(files), 'payload_bytes': actual_bytes}


def _verify_extraction(clean, files):
    expected_dirs = {str(parent) for name in files for parent in Path(name).parents if str(parent) != '.'}
    actual_files, actual_dirs = set(), set()
    for path in clean.rglob('*'):
        name = str(path.relative_to(clean))
        if path.is_symlink():
            raise ValueError('Candidate extraction acquired a symlink')
        if path.is_dir():
            actual_dirs.add(name)
        elif path.is_file():
            actual_files.add(name)
            if name not in files or demo.sha256(path) != hashlib.sha256(files[name]).hexdigest():
                raise ValueError('Candidate extraction acquired a new or changed file')
        else:
            raise ValueError('Candidate extraction acquired a nonregular file')
    if actual_files != set(files) or actual_dirs != expected_dirs:
        raise ValueError('Candidate extraction inventory changed')


def check_candidate(archive_path, expected_sha256, *, evidence_relative='evidence/M2-9_candidate_check.json'):
    if sys.platform != 'linux' or sys.version_info[:3] != (3, 10, 13):
        raise ValueError('Use the fixed Python 3.10.13 Linux environment for exact-candidate checks')
    evidence = _evidence_path(evidence_relative)
    result = {'status': 'RUNNING', 'mode': 'exact_candidate', 'started_utc': datetime.now(timezone.utc).isoformat(),
        'archive_sha256': expected_sha256, 'fresh_interpreter': False, 'dependency_installation_performed': False,
        'synthetic_replacements': False, 'formal_candidate_created': False, 'mac_execution': 'not_verified',
        'report_profile_origin': 'unchanged_candidate_archive', 'independent_review': 'not_performed',
        'publication_status': 'not_published_by_this_tool',
        'api_calls': 0, 'credentials_read': False, 'research_cohorts_read': False,
        'guard_scope': 'Python read/network regression guards; not an OS filesystem sandbox',
        'checker_sha256': demo.sha256(Path(__file__))}
    try:
        expected = _expected_versions()
        if len(expected) != 19 or any(importlib.metadata.version(n) != v for n, v in expected.items()):
            raise ValueError('The existing interpreter dependencies differ from the fixed pins')
        files, inventory = candidate_payload(archive_path, expected_sha256)
        result.update(inventory)
        with tempfile.TemporaryDirectory(prefix='.demo-candidate-check-', dir=demo.ROOT) as temporary:
            work, clean = Path(temporary), Path(temporary) / 'clean'
            for name, data in files.items():
                target = clean / name
                target.parent.mkdir(parents=True, exist_ok=True)
                with target.open('xb') as handle:
                    handle.write(data)
            _verify_extraction(clean, files)
            guard = work / 'guard'
            guard.mkdir()
            (guard / 'sitecustomize.py').write_text(CANDIDATE_GUARD)
            temp = work / 'tmp'
            temp.mkdir()
            environment = {'PATH': os.defpath, 'LANG': 'C.UTF-8', 'PYTHONPATH': str(guard),
                'PYTHONDONTWRITEBYTECODE': '1', 'PYTHONNOUSERSITE': '1', 'TMPDIR': str(temp)}
            def run(*arguments):
                # Never fall back to an unisolated command if unshare fails.
                output = subprocess.run(['unshare', '-rn', sys.executable, '-B', '-s', *arguments],
                    cwd=clean, env=environment, check=True, capture_output=True, text=True, timeout=120)
                return _strict_json(output.stdout)
            versions = run('-c', CANDIDATE_PROBE, json.dumps(expected))
            check = run('tools/demo.py', '--check', '--require-runtime')
            dry = run('tools/demo.py', '--live')
            for item, status in ((check, 'PASS'), (dry, 'READY_DRY_RUN')):
                if (item.get('status') != status or item.get('api_calls') != 0
                        or item.get('credentials_read') is not False or item.get('research_cohorts_read') is not False):
                    raise ValueError('Exact candidate offline result differs')
            _verify_extraction(clean, files)
            # Detect original artifact replacement as well as extracted mutations.
            original = Path(archive_path).absolute()
            if any(p.is_symlink() for p in (original, *original.parents)) or demo.sha256(original) != expected_sha256:
                raise ValueError('Candidate archive changed during its check')
            result.update(status='PASS', versions=versions, pinned_packages_verified=len(expected),
                network_namespace='unshare -rn for every Python check; no fallback',
                offline_status=check['status'], live_dry_run_status=dry['status'],
                extracted_members_unchanged=True, source_files=len(demo.INFERENCE_FILES + package.RESEARCH_SOURCES),
                test_files=len(package.TEST_FILES))
    except Exception as error:
        result.update(status='FAILED', error_type=type(error).__name__)
    result.update(temporary_files_deleted_on_exit=True, finished_utc=datetime.now(timezone.utc).isoformat())
    package.scan_bytes(json.dumps(result).encode(), 'candidate-check-evidence')
    with evidence.open('x') as handle:
        json.dump(result, handle, indent=2, sort_keys=True)
        handle.write('\n')
    return {**result, 'evidence': str(evidence.relative_to(demo.ROOT))}


def _expected_versions():
    versions = {}
    for line in demo.safe_file(demo.ROOT, 'requirements-demo.txt').read_text().splitlines():
        if line.strip() and not line.startswith('#'):
            name, version = line.split(';')[0].strip().split('==')
            versions[name] = version
    return versions


def _evidence_path(relative):
    pure = Path(relative)
    if pure.is_absolute() or '..' in pure.parts or pure.parts[0:1] != ('evidence',) or pure.suffix != '.json':
        raise ValueError('Evidence must be a relative JSON path under evidence/')
    target = demo.ROOT / pure
    for parent in (target, *target.parents):
        if parent == demo.ROOT:
            break
        if parent.is_symlink():
            raise ValueError('Evidence symlinks are forbidden')
    if target.exists():
        raise ValueError('Evidence already exists; select a new evidence name')
    target.parent.mkdir(parents=True, exist_ok=True)
    return target


def rehearsal(*, real_install=False, evidence_relative='evidence/M2-9_real_install.json'):
    if sys.platform != 'linux' and real_install:
        raise ValueError('This real-install evidence helper currently targets Linux')
    evidence = _evidence_path(evidence_relative) if real_install else None
    expected = _expected_versions()
    if not real_install:
        if sys.version_info[:3] != (3, 10, 13):
            raise ValueError('Use the existing fixed Python 3.10.13 environment')
        if any(importlib.metadata.version(name) != version for name, version in expected.items()):
            raise ValueError('An installed dependency differs from the fixed requirements')
    demo.check_runtime()
    code_files = demo.INFERENCE_FILES + package.RESEARCH_SOURCES + package.TEST_FILES
    for relative in code_files:
        demo.safe_file(demo.ROOT, relative)
    spec = importlib.util.spec_from_file_location('demo_test_fixtures', demo.ROOT / 'tests/test_demo_v2.py')
    fixtures = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fixtures)
    started = datetime.now(timezone.utc).isoformat()
    result = {'status': 'RUNNING', 'fixture_reports_and_profile': True, 'formal_candidate_created': False,
        'mode': 'real_install' if real_install else 'mock_installer', 'started_utc': started,
        'mac_execution': 'not_verified', 'platform': sys.platform, 'api_calls': 0,
        'credentials_read': False, 'research_cohorts_read': False}
    setup_output = b''
    with tempfile.TemporaryDirectory(prefix='.demo-install-check-', dir=demo.ROOT) as temporary:
        work = Path(temporary)
        staged = work / 'staged'
        _, selection, parameters = fixtures.fixture(staged)
        for name in package.SOURCE_REQUIRED + package.SOURCE_OPTIONAL + demo.RUNTIME_FILES:
            source = demo.ROOT / name
            if source.is_file() and not name.startswith('reports/') and name != 'analysis/diagnostics_v2.json':
                fixtures.write(staged, name, demo.safe_file(demo.ROOT, name).read_bytes())
        profile = demo.make_demo_profile(selection, parameters, staged)
        fixtures.write(staged, 'reports/demo_profile.json', json.dumps(profile))
        output = work / 'candidate-fixture'
        built = package.build(staged, output, 'complete')
        if built['status'] != 'READY_CANDIDATE':
            raise ValueError('Synthetic rehearsal package was incomplete')
        clean = work / 'clean'
        import zipfile
        with zipfile.ZipFile(output / built['archive']) as archive:
            archive.extractall(clean)
        fixtures.write(work, '.env', 'SYNTHETIC PARENT FILE: MUST NOT BE READ').chmod(0o000)
        guard = work / 'guard'
        fixtures.write(guard, 'sitecustomize.py', GUARD)
        temporary_files = work / 'tmp'
        temporary_files.mkdir()
        # Strip inherited credentials/provider/index configuration. curl disables
        # user curlrc, uv disables user config, and setup pins all download URLs.
        environment = {'PATH': os.defpath + ':/usr/bin/core_perl', 'LANG': 'C.UTF-8',
            'PYTHONPATH': str(guard), 'PYTHONDONTWRITEBYTECODE': '1', 'TMPDIR': str(temporary_files),
            'UV_NO_CONFIG': '1', 'UV_INDEX_URL': 'https://pypi.org/simple',
            'UV_PYTHON_PREFERENCE': 'only-managed', 'PIP_CONFIG_FILE': os.devnull,
            'PIP_NO_INPUT': '1', 'PIP_DISABLE_PIP_VERSION_CHECK': '1'}
        if not real_install:
            fixtures.write(clean, '.venv-demo/bin/python', '#!/bin/sh\nexec ' + shlex.quote(sys.executable) + ' "$@"\n').chmod(0o755)
            fixtures.write(clean, '.tools/uv/uv', '#!/bin/sh\ncase "$1" in python|pip) exit 0;; *) exit 2;; esac\n').chmod(0o755)
        else:
            if (clean / '.venv-demo').exists() or (clean / '.tools').exists() or (work / '.tools').exists():
                raise ValueError('Real installation requires absent venv, tools and parent uv')
            print(json.dumps({'stage': 'real_install_started', 'fixture_only': True, 'api_calls': 0}), flush=True)
        def run(command, *, timeout=60, offline=False):
            if offline and real_install:
                command = ['unshare', '-rn', *command]
            return subprocess.run(command, cwd=clean, env=environment, check=True,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=timeout)
        try:
            run(['bash', '-n', 'setup.sh'])
            install = run(['bash', 'setup.sh', 'offline'], timeout=900 if real_install else 60)
            setup_output = ('STDOUT\n' + install.stdout + '\nSTDERR\n' + install.stderr).encode()
            executable = str(clean / '.venv-demo/bin/python')
            versions = json.loads(run([executable, '-B', '-c', VERSION_PROBE], offline=True).stdout)
            uv_version = None
            if real_install:
                if Path(versions['prefix']) != clean / '.venv-demo' or not Path(versions['base_prefix']).is_relative_to(clean / '.tools/python'):
                    raise ValueError('Installed environment reused an outside interpreter')
                uv_version = run([str(clean / '.tools/uv/uv'), '--version']).stdout.strip()
                if uv_version.split()[1] != '0.9.6':
                    raise ValueError('Installed uv version differs')
            check = json.loads(run([executable, '-B', 'tools/demo.py', '--check', '--require-runtime'], offline=True).stdout)
            dry = json.loads(run([executable, '-B', 'tools/demo.py', '--live'], offline=True).stdout)
            run([executable, '-B', '-c', "import numpy as np; a=np.load('data/vectors/embeddings.npy',allow_pickle=False); assert a.shape==(5624,3072)"], offline=True)
            # Credential-helper unit tests deliberately read synthetic .env
            # files. Run presentation tests here so this installation acceptance
            # opens no .env at all; the separate focused suite covers credentials.
            tests = run([executable, '-B', '-m', 'unittest', 'discover', '-s', 'tests', '-p', 'test_demo_presentation.py'], timeout=120, offline=True)
            if check['status'] != 'PASS' or dry['status'] != 'READY_DRY_RUN':
                raise ValueError('Clean offline check failed')
            result.update(status='PASS', setup_uv_operations='real_download_and_sync' if real_install else 'mocked_no_install_or_download',
                fresh_venv=real_install, fresh_managed_python=real_install, uv_version=uv_version,
                versions=versions, pinned_packages_verified=len(versions['packages']),
                real_saved_vector_shape=[5624, 3072], source_files=len(demo.INFERENCE_FILES + package.RESEARCH_SOURCES),
                test_files=len(package.TEST_FILES), offline_checks_network_namespace=bool(real_install),
                check=check, live_dry_run=dry, presentation_test_output=tests.stderr.strip(),
                fixture_archive_sha256=built['archive_sha256'],
                input_sha256={name: demo.sha256(demo.safe_file(staged, name)) for name in
                              ('setup.sh', 'requirements-demo.txt', 'tools/check_clean_demo.py') + code_files + demo.RUNTIME_FILES})
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
            stdout = error.stdout or ''
            stderr = error.stderr or ''
            if isinstance(stdout, bytes):
                stdout = stdout.decode(errors='replace')
            if isinstance(stderr, bytes):
                stderr = stderr.decode(errors='replace')
            setup_output += ('FAILED COMMAND STDOUT\n' + stdout + '\nSTDERR\n' + stderr).encode()
            result.update(status='FAILED', error_type=type(error).__name__,
                          returncode=getattr(error, 'returncode', None))
        except Exception as error:
            result.update(status='FAILED', error_type=type(error).__name__)
        finally:
            if evidence:
                package.scan_bytes(setup_output, 'installation.log')
                log = evidence.with_suffix('.setup.log')
                with log.open('xb') as handle:
                    handle.write(setup_output)
                result['setup_log'] = str(log.relative_to(demo.ROOT))
                result['setup_log_sha256'] = demo.sha256(log)
    result['temporary_files_deleted_on_exit'] = True
    result['finished_utc'] = datetime.now(timezone.utc).isoformat()
    if evidence:
        with evidence.open('x') as handle:
            json.dump(result, handle, indent=2, sort_keys=True)
            handle.write('\n')
        result['evidence'] = str(evidence.relative_to(demo.ROOT))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument('--real-install', action='store_true', help='Actually download fixed tools/Python and sync a fresh venv')
    modes.add_argument('--candidate', type=Path, help='Check an actual complete ZIP without replacing reports/profile')
    parser.add_argument('--expected-sha256', help='Required trusted complete-archive digest with --candidate')
    parser.add_argument('--evidence', help='New relative JSON path under evidence/')
    args = parser.parse_args()
    if bool(args.candidate) != bool(args.expected_sha256):
        parser.error('--candidate and --expected-sha256 must be supplied together')
    try:
        if args.candidate:
            result = check_candidate(args.candidate, args.expected_sha256,
                evidence_relative=args.evidence or 'evidence/M2-9_candidate_check.json')
        else:
            result = rehearsal(real_install=args.real_install,
                evidence_relative=args.evidence or 'evidence/M2-9_real_install.json')
    except Exception as error:
        result = {'status': 'FAILED', 'error_type': type(error).__name__, 'api_calls': 0,
                  'notice': 'Environment rehearsal stopped; no credential or research data was substituted.'}
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result['status'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
