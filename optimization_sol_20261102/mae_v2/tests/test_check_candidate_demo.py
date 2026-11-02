"""Exact archive checker tests use explicitly synthetic reports and vectors."""
import hashlib
import io
import json
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import warnings
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import check_clean_demo as checker
import demo
import package_demo as package
from test_demo_v2 import fixture, write


class CandidateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.shared = tempfile.TemporaryDirectory(prefix='.candidate-fixture-tests-', dir=ROOT)
        cls.base = Path(cls.shared.name)
        staged = cls.base / 'staged'
        _, selection, parameters = fixture(staged)
        write(staged, 'requirements-demo.txt', (ROOT / 'requirements-demo.txt').read_bytes())
        # A correctly shaped all-zero array is synthetic, not the saved corpus.
        import numpy as np
        data = io.BytesIO()
        np.save(data, np.zeros((5624, 3072), dtype=np.float32), allow_pickle=False)
        write(staged, 'data/vectors/embeddings.npy', data.getvalue())
        manifest = json.loads((staged / 'data/vectors/manifest.json').read_text())
        manifest['files']['embeddings.npy'] = demo.sha256(staged / 'data/vectors/embeddings.npy')
        write(staged, 'data/vectors/manifest.json', json.dumps(manifest))
        write(staged, 'reports/demo_profile.json', json.dumps(demo.make_demo_profile(selection, parameters, staged)))
        built = package.build(staged, cls.base / 'built', 'complete')
        cls.archive = cls.base / 'built' / built['archive']
        cls.archive_hash = built['archive_sha256']

    @classmethod
    def tearDownClass(cls):
        cls.shared.cleanup()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='.candidate-case-', dir=ROOT)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        write(self.root, 'requirements-demo.txt', (ROOT / 'requirements-demo.txt').read_bytes())
        self.patch = patch.object(demo, 'ROOT', self.root)
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def changed(self, changes=None, *, manifest_change=None, member_mode=None, duplicate=False):
        with zipfile.ZipFile(self.archive) as archive:
            files = {name: archive.read(name) for name in archive.namelist()}
        if changes:
            for name, value in changes.items():
                if value is None:
                    files.pop(name, None)
                else:
                    files[name] = value
        manifest = json.loads(files[package.MANIFEST_NAME])
        if manifest_change:
            manifest_change(manifest)
            files[package.MANIFEST_NAME] = json.dumps(manifest).encode()
        destination = self.root / 'changed.zip'
        with warnings.catch_warnings():
            warnings.simplefilter('ignore', UserWarning)
            with zipfile.ZipFile(destination, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
                for name, data in files.items():
                    info = zipfile.ZipInfo(name)
                    info.external_attr = (member_mode if member_mode and name == 'README.md' else stat.S_IFREG | 0o644) << 16
                    info.compress_type = zipfile.ZIP_DEFLATED
                    archive.writestr(info, data)
                if duplicate:
                    archive.writestr('README.md', files['README.md'])
        return destination, demo.sha256(destination)

    def test_actual_archive_mode_keeps_fixture_bytes_and_records_safe_evidence(self):
        # No fixture generator is reachable from the exact-candidate entry point.
        original = Path.open
        def guard(path, *args, **kwargs):
            if path.name == '.env' or set(path.parts) & {'cohorts', 'freeze', 'sealed'}:
                raise AssertionError('private input read')
            return original(path, *args, **kwargs)
        with patch.object(checker, 'rehearsal', side_effect=AssertionError('synthetic substitution')):
            with patch.object(Path, 'open', guard):
                result = checker.check_candidate(self.archive, self.archive_hash)
        self.assertEqual(result['status'], 'PASS', result)
        self.assertEqual(result['mode'], 'exact_candidate')
        self.assertEqual(result['archive_sha256'], self.archive_hash)
        self.assertEqual(result['versions']['private_and_network_guard_probes_passed'], 3)
        self.assertEqual(result['pinned_packages_verified'], 19)
        self.assertFalse(result['synthetic_replacements'])
        self.assertFalse(result['fresh_interpreter'])
        self.assertTrue(result['extracted_members_unchanged'])
        self.assertFalse(list(self.root.glob('.demo-candidate-check-*')))
        saved = json.loads((self.root / result['evidence']).read_text())
        self.assertEqual(saved['archive_sha256'], self.archive_hash)
        self.assertEqual(demo.sha256(self.archive), self.archive_hash)

    def test_checksum_missing_archive_and_symlink_are_rejected(self):
        for path, digest in ((self.archive, '0' * 64), (self.root / 'absent.zip', self.archive_hash)):
            with self.assertRaises(ValueError):
                checker.candidate_payload(path, digest)
        target = self.root / 'symlink.zip'
        target.symlink_to(self.archive)
        with self.assertRaises(ValueError):
            checker.candidate_payload(target, self.archive_hash)

    def test_unexpected_paths_duplicates_missing_members_and_symlinks_are_rejected(self):
        cases = ({'changes': {'../escape': b'bad'}}, {'changes': {'data/cohorts/dev.jsonl': b'private'}},
                 {'changes': {'reports/demo_profile.json': None}}, {'duplicate': True},
                 {'member_mode': stat.S_IFLNK | 0o777}, {'member_mode': stat.S_IFIFO | 0o600})
        for options in cases:
            with self.subTest(options=options):
                path, digest = self.changed(**options)
                with self.assertRaises(ValueError):
                    checker.candidate_payload(path, digest)

    def test_payload_and_manifest_hash_size_schema_and_inventory_must_match(self):
        cases = ({'changes': {'README.md': b'changed'}},
            {'manifest_change': lambda m: m.update(kind='source')},
            {'manifest_change': lambda m: m.update(schema_version=2.0)},
            {'manifest_change': lambda m: m['files']['README.md'].update(bytes=True)},
            {'manifest_change': lambda m: m['files']['README.md'].update(sha256='0' * 64)},
            {'manifest_change': lambda m: m['files'].pop('README.md')})
        for options in cases:
            with self.subTest(options=options):
                path, digest = self.changed(**options)
                with self.assertRaises(ValueError):
                    checker.candidate_payload(path, digest)

    def test_duplicate_manifest_keys_and_expansion_budget_are_rejected(self):
        with zipfile.ZipFile(self.archive) as archive:
            manifest = archive.read(package.MANIFEST_NAME)
        malformed = manifest.replace(b'"schema_version": 2', b'"schema_version": 2, "schema_version": 2')
        path, digest = self.changed({package.MANIFEST_NAME: malformed})
        with self.assertRaises(ValueError):
            checker.candidate_payload(path, digest)
        with patch.object(checker, 'MAX_CANDIDATE_BYTES', 1024):
            with self.assertRaises(ValueError):
                checker.candidate_payload(self.archive, self.archive_hash)

    def test_requirement_pins_are_checked_against_trusted_runner(self):
        changed = b'httpx==0.0.1\n'
        def update(manifest):
            manifest['files']['requirements-demo.txt'] = {'bytes': len(changed), 'sha256': hashlib.sha256(changed).hexdigest()}
        path, digest = self.changed({'requirements-demo.txt': changed}, manifest_change=update)
        with self.assertRaises(ValueError):
            checker.candidate_payload(path, digest)

    def test_extraction_rejects_new_changed_missing_and_symlink_files(self):
        for kind in ('new', 'changed', 'missing', 'symlink', 'directory'):
            with tempfile.TemporaryDirectory(dir=self.root) as temporary:
                clean = Path(temporary)
                write(clean, 'dir/original.txt', b'original')
                files = {'dir/original.txt': b'original'}
                checker._verify_extraction(clean, files)
                if kind == 'new':
                    write(clean, 'added', b'new')
                elif kind == 'changed':
                    write(clean, 'dir/original.txt', b'changed')
                elif kind == 'directory':
                    (clean / 'extra').mkdir()
                else:
                    (clean / 'dir/original.txt').unlink()
                    if kind == 'symlink':
                        (clean / 'dir/original.txt').symlink_to(self.archive)
                with self.assertRaises(ValueError, msg=kind):
                    checker._verify_extraction(clean, files)

    def test_unshare_failure_has_no_unisolated_fallback_and_no_raw_error_output(self):
        commands = []
        original = subprocess.run
        def deny(command, *args, **kwargs):
            if command[0] == 'unshare':
                commands.append(command)
                raise subprocess.CalledProcessError(1, command, output='PRIVATE DIAGNOSTIC', stderr='DO NOT EMIT')
            return original(command, *args, **kwargs)
        with patch.object(checker.subprocess, 'run', deny):
            result = checker.check_candidate(self.archive, self.archive_hash)
        self.assertEqual(result['status'], 'FAILED')
        self.assertEqual(len(commands), 1)
        self.assertNotIn('PRIVATE', json.dumps(result))
        self.assertNotIn('DO NOT EMIT', json.dumps(result))
        self.assertFalse(list(self.root.glob('.demo-candidate-check-*')))

    def test_evidence_is_immutable(self):
        write(self.root, 'evidence/M2-9_candidate_check.json', '{}')
        with self.assertRaises(ValueError):
            checker.check_candidate(self.archive, self.archive_hash)


if __name__ == '__main__':
    unittest.main()
