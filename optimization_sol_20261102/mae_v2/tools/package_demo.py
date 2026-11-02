#!/usr/bin/env python3
"""Build explicitly allowlisted local candidates; never publish or download."""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
from pathlib import Path
import re
import shutil
import stat
import subprocess
import tempfile
import zipfile

import demo

ROOT = demo.ROOT
RESEARCH_SOURCES = tuple('src/' + name for name in ('cohorts_v2.py', 'download_cohorts_v2.py',
    'diagnostics_v2.py', 'study.py', 'validation_adapter.py', 'report_v2.py', 'render_report_v2.py', 'plot_report_v2.py'))
TEST_FILES = tuple('tests/' + name for name in ('test_cohorts_v2.py', 'test_download_cohorts_v2.py',
    'test_demo_v2.py', 'test_demo_presentation.py', 'test_check_candidate_demo.py', 'test_finalize_demo_profile.py', 'test_diagnostics_v2.py', 'test_metrics_v2.py', 'test_opt_provider.py',
    'test_pipeline_v2.py', 'test_provider_resume.py', 'test_report_v2.py', 'test_render_report_v2.py', 'test_plot_report_v2.py', 'test_study.py',
    'test_validation_adapter.py'))
AGGREGATE_FILES = ('analysis/paper_targets.json', 'analysis/historical_summary.json',
    'analysis/diagnostics_v2.json', 'evidence/official-embedding-price.json')
SOURCE_REQUIRED = ('setup.sh', 'START_HERE_MAC.md', 'MAC_DEMO.md', 'requirements-demo.txt',
    'README.md', 'PROTOCOL.md', 'CHECKLIST.md', 'REVIEW.md',
    'config/experiment.json', 'config/candidates.json',
    'tools/demo.py', 'tools/package_demo.py', 'tools/check_clean_demo.py', 'tools/finalize_demo_profile.py', 'tools/env.example', 'tools/demo_inputs.json',
    'tools/demo_images/asa24.png', 'tools/demo_images/nutrition5k.png') + demo.INFERENCE_FILES + RESEARCH_SOURCES + TEST_FILES + AGGREGATE_FILES + demo.REPORTS + (demo.REPORT_STEM + '.json', 'reports/demo_profile.json')
SOURCE_OPTIONAL = ('reports/metrics.json', 'reports/metrics.csv', 'reports/ablation.csv', 'reports/summary.json',
    'analysis/imported_source_manifest.json', 'reports/DietAI24_MAE_v2_Ratios.png',
    'reports/DietAI24_MAE_v2_Ratios.pdf')
MANIFEST_NAME = 'PACKAGE_MANIFEST.json'
RELEASE_NAME = 'runtime-release.json'
MAX_RUNTIME_BYTES = 160 * 1024 * 1024
SECRET_PATTERNS = (
    re.compile(rb'(?<![A-Za-z0-9])sk-[A-Za-z0-9_-]{24,}'),
    re.compile(rb'gh[pousr]_[A-Za-z0-9]{30,}'),
    re.compile(rb'github_pat_[A-Za-z0-9_]{30,}'),
    re.compile(rb'AKIA[A-Z0-9]{16}'),
    re.compile(rb'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----'),
)
ASSIGNMENT = re.compile(rb'(?im)^\s*[\"\']?(?:[A-Z0-9_]*(?:API_KEY|ACCESS_TOKEN|AUTH_TOKEN|PASSWORD))[\"\']?\s*[:=]\s*[\"\']?([^\r\n\"\' ,}]+)')


def scan_bytes(data, relative):
    """Generic credential scan without opening any credential files."""
    if any(pattern.search(data) for pattern in SECRET_PATTERNS):
        raise ValueError('Credential-shaped content in an allowlisted package member')
    for match in ASSIGNMENT.finditer(data):
        value = match.group(1)
        if len(value) >= 12 and not value.startswith((b'replace_', b'${', b'os.', b'values.', b'None', b'False')):
            raise ValueError('Credential assignment in an allowlisted package member')
    if relative.endswith('.docx'):
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            if sum(info.file_size for info in archive.infolist()) > 64 * 1024 * 1024:
                raise ValueError('Report expansion is too large')
            for info in archive.infolist():
                if not info.is_dir():
                    scan_bytes(archive.read(info), 'docx-member')


def inspect_member(relative, data):
    scan_bytes(data, relative)
    if relative.startswith(('reports/', 'analysis/')) or relative == 'evidence/official-embedding-price.json':
        if relative.endswith('.json'):
            demo.aggregate_only(json.loads(data))
        elif relative.endswith('.csv'):
            rows = csv.reader(io.StringIO(data.decode('utf-8-sig')))
            fields = next(rows, [])
            if demo.FORBIDDEN_AGGREGATE_KEYS & {v.strip().lower() for v in fields}:
                raise ValueError('Row-level CSV is forbidden')
        # The report records the digest of this exact aggregate freeze metadata
        # file. Allow only that complete path token; do not export the file or
        # permit suffixes, siblings, label/manifest paths, or individual images.
        references = re.sub(rb'(?<![A-Za-z0-9_./\\-])data/cohorts/dev_freeze\.json(?![A-Za-z0-9_./\\-])',
                            b'<aggregate-freeze-provenance>', data)
        if re.search(rb'dish_[0-9]{8,}|data/(?:cohorts|images|freeze|sealed|incoming|downloads)/|data/(?:asa24|nutrition5k)/(?:images/|dev/|validation/)', references):
            raise ValueError('Research row identity or private path in report')
        if relative.endswith('.docx'):
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                for name in archive.namelist():
                    if name.endswith('.xml'):
                        inspect_member('reports/document.xml', archive.read(name))
        if relative.endswith('.pdf'):
            binary = shutil.which('pdftotext')
            if binary is None:
                raise ValueError('Building a candidate requires pdftotext for report scanning')
            result = subprocess.run([binary, '-', '-'], input=data, stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE, check=True, timeout=30)
            inspect_member('reports/document.txt', result.stdout)


def gather(root=ROOT, kind='source'):
    if kind not in ('source', 'runtime', 'complete'):
        raise ValueError('Unknown candidate kind')
    root = Path(root).resolve()
    ready = demo.check(root, require_runtime=kind in ('runtime', 'complete'))
    missing = list(ready['missing'])
    # Filename discovery never opens unlisted files. New code requires an
    # explicit packaging decision, rather than silently omitting full source.
    if kind != 'runtime':
        known_code = set(demo.INFERENCE_FILES + RESEARCH_SOURCES + TEST_FILES)
        actual_code = {str(path.relative_to(root)) for folder in ('src', 'tests')
                       for path in (root / folder).glob('*.py')}
        if actual_code - known_code:
            raise ValueError('Source inventory changed; update the explicit allowlist')
    source = SOURCE_REQUIRED + tuple(name for name in SOURCE_OPTIONAL if (root / name).exists())
    names = demo.RUNTIME_FILES if kind == 'runtime' else source
    if kind == 'complete':
        names += demo.RUNTIME_FILES
    for name in names:
        if not (root / name).is_file():
            missing.append(name)
    if missing:
        return {}, {'status': 'INCOMPLETE', 'missing': sorted(set(missing)), 'api_calls': 0}
    data = {}
    for name in sorted(names):
        data[name] = demo.safe_file(root, name).read_bytes()
        inspect_member(name, data[name])
    return data, {'status': 'READY_CANDIDATE', 'kind': kind, 'files': len(data),
        'payload_bytes': sum(map(len, data.values())), 'api_calls': 0, 'credentials_read': False,
        'research_cohorts_read': False, 'secret_scan': 'generic patterns and assignments; no local credentials read',
        'review_status': 'see_review_ledger', 'publication_status': 'not_published_by_this_tool', 'mac_execution': 'not_verified'}


def _manifest(files, kind):
    return {'schema_version': 2, 'kind': kind, 'review_status': 'see_review_ledger',
        'publication_status': 'not_published_by_this_tool',
        'files': {name: {'sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data)} for name, data in sorted(files.items())},
        'research_images': 0, 'historical_demo_images': 0 if kind == 'runtime' else 2,
        'credentials_read': False, 'api_calls': 0, 'mac_execution': 'not_verified'}


def _write_zip(path, files, kind):
    entries = dict(files)
    entries[MANIFEST_NAME] = (json.dumps(_manifest(files, kind), indent=2, sort_keys=True) + '\n').encode()
    with zipfile.ZipFile(path, 'x', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for name, data in sorted(entries.items()):
            info = zipfile.ZipInfo(name, date_time=(2026, 11, 2, 0, 0, 0))
            info.external_attr = ((stat.S_IFREG | (0o755 if name == 'setup.sh' else 0o644)) << 16)
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, data)


def build(root, destination, kind='complete'):
    files, result = gather(root, kind)
    if result['status'] == 'INCOMPLETE':
        return result
    destination = Path(destination).resolve()
    destination.mkdir(parents=True, exist_ok=True)
    # A fixed local runtime archive accompanies source; no remote URL is invented.
    runtime_hash = None
    if kind in ('source', 'complete'):
        runtime, runtime_status = gather(root, 'runtime')
        if runtime_status['status'] == 'INCOMPLETE':
            return runtime_status
        runtime_path = destination / 'mae-v2-runtime.zip'
        _write_zip(runtime_path, runtime, 'runtime')
        runtime_hash = demo.sha256(runtime_path)
        files[RELEASE_NAME] = (json.dumps({'schema_version': 2, 'filename': runtime_path.name,
            'sha256': runtime_hash, 'bytes': runtime_path.stat().st_size, 'url': None,
            'status': 'local_candidate_not_published'}, indent=2, sort_keys=True) + '\n').encode()
    path = destination / f'mae-v2-{kind}.zip'
    _write_zip(path, files, kind)
    summary = {**result, 'archive': path.name, 'archive_sha256': demo.sha256(path),
        'archive_bytes': path.stat().st_size, 'runtime_archive_sha256': runtime_hash}
    with (destination / f'mae-v2-{kind}.manifest.json').open('x') as handle:
        json.dump({**summary, 'inventory': _manifest(files, kind)}, handle, indent=2, sort_keys=True)
        handle.write('\n')
    return summary


def install_runtime(root, archive_path):
    root = Path(root).resolve()
    release = json.loads(demo.safe_file(root, RELEASE_NAME).read_text())
    archive_path = Path(archive_path)
    if archive_path.is_symlink() or not archive_path.is_file():
        raise ValueError('Runtime must be a local regular file')
    if archive_path.stat().st_size != release['bytes'] or demo.sha256(archive_path) != release['sha256']:
        raise ValueError('Runtime archive checksum differs')
    data = {}
    with zipfile.ZipFile(archive_path) as archive:
        entries = archive.infolist()
        names = [info.filename for info in entries]
        if len(names) != len(set(names)) or set(names) != set(demo.RUNTIME_FILES) | {MANIFEST_NAME}:
            raise ValueError('Unexpected runtime archive inventory')
        if sum(info.file_size for info in entries) > MAX_RUNTIME_BYTES:
            raise ValueError('Runtime uncompressed budget exceeded')
        for info in entries:
            if stat.S_ISLNK(info.external_attr >> 16) or info.is_dir():
                raise ValueError('Runtime symlink/directory entries are forbidden')
            data[info.filename] = archive.read(info)
    manifest = json.loads(data.pop(MANIFEST_NAME))
    if manifest.get('kind') != 'runtime' or set(manifest.get('files', {})) != set(demo.RUNTIME_FILES):
        raise ValueError('Runtime manifest differs')
    profile = demo.validate_profile(json.loads(demo.safe_file(root, 'reports/demo_profile.json').read_text()), root)
    for name, content in data.items():
        expected = manifest['files'][name]
        digest = hashlib.sha256(content).hexdigest()
        if expected != {'sha256': digest, 'bytes': len(content)} or digest != profile['runtime_sha256'][name]:
            raise ValueError('Runtime payload checksum differs')
        inspect_member(name, content)
        target = root / name
        for parent in (target, *target.parents):
            if parent == root:
                break
            if parent.is_symlink():
                raise ValueError('Runtime target symlink forbidden')
        if target.exists() and (not target.is_file() or demo.sha256(target) != digest):
            raise ValueError('Runtime target already contains different data')
    # Validate the complete vector/catalog inventory before touching the target.
    with tempfile.TemporaryDirectory(prefix='mae-v2-runtime-') as temp:
        staged = Path(temp)
        for name, content in data.items():
            path = staged / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
        demo.check_runtime(staged, profile)
        for name in sorted(data):
            target = root / name
            if not target.exists():
                target.parent.mkdir(parents=True, exist_ok=True)
                with target.open('xb') as handle:
                    handle.write(data[name])
    return {'status': 'INSTALLED', 'files': len(data), 'api_calls': 0, 'corpus_embedding_calls': 0}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument('--check', action='store_true')
    modes.add_argument('--build', type=Path, metavar='OUTPUT_DIRECTORY')
    modes.add_argument('--install-runtime', type=Path, metavar='LOCAL_ZIP')
    parser.add_argument('--kind', choices=('source', 'runtime', 'complete'), default='complete')
    args = parser.parse_args()
    try:
        if args.install_runtime:
            result = install_runtime(ROOT, args.install_runtime)
        elif args.build:
            result = build(ROOT, args.build, args.kind)
        else:
            _, result = gather(ROOT, args.kind)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 1 if result['status'] == 'INCOMPLETE' else 0
    except Exception as error:
        print(json.dumps({'status': 'STOPPED', 'error_type': type(error).__name__,
            'notice': 'Candidate or runtime integrity check failed. Existing files were not substituted.'}))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
