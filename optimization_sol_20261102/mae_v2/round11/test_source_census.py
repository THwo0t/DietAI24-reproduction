import copy
import hashlib
import json
import os
from pathlib import Path
import stat
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import source_census as c


class SourceCensusTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = Path(self.tmp.name) / 'repo'
        self.base = self.repo / c.PREFIX
        self.base.mkdir(parents=True)
        self.blobs = {}
        def put(relative, value):
            raw = value if isinstance(value, bytes) else c.encoded(value)
            path = self.base / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
            self.blobs[relative] = c.sha(raw)
            return self.blobs[relative]
        self.put = put
        mappings = [
            ('freeze_sha256', 'round10/prepared/freeze.json'),
            ('development_completion_sha256', 'round10/runs/development/completion.json'),
            ('identities_completion_sha256', 'round10/runs/identities/completion.json'),
            ('scoring_completion_sha256', 'round10/runs/scoring/completion.json'),
            ('verification_sha256', 'round10/runs/verification.json'),
            ('checkpoint_sha256', 'round10/development_checkpoint.json'),
        ]
        evidence = {field: put(relative, {'synthetic': relative}) for field, relative in mappings}
        source_pins = {relative: put(relative, b'# synthetic source\n') for relative in (
            'round10/postscore/guarded_diagnose_o.py', 'round10/postscore/reverify_sealed_o.py',
            'round11/o_completion.py')}
        self.recovery = {
            'status': 'O_sealed_diagnostic_reverified', 'api_calls': 0,
            'validation_opened': False, 'recomputed_score': False, 'recomputed_diagnostic': False,
            'completed_O_evidence': evidence,
            'diagnostic_completion_sha256': put('round10/diagnostics/completed_o/completion.json', {'done': True}),
            'recovery_source_pins': source_pins,
        }
        backup = {'status': 'completed_O_failure_backup_remote_verified',
                  'public_commit': '42a8721322e98f2dda4fab66949f39090c3dc2f7',
                  'credential_matches': 0, 'O': {'accepted': False}}
        put('round11/DESIGN.md', b'# synthetic prospective registration\n')
        put('round11/retrospective/REVIEW.md', b'# synthetic dispositions\n')
        put('round11/evidence/github_completed_O_backup.json', backup)
        put('round10/evidence/postscore_guard_recovery.json', self.recovery)
        self.pins = {key: self.blobs[key] for key in c.CONTROL_PINS}

    def build(self):
        return c._build_at(self.repo, self.base, self.pins)

    def test_census_never_opens_research_or_secret_bodies(self):
        for relative in ('data/validation_labels.json', 'data/images/x.png', 'provider/raw.json', '.env'):
            path = self.repo / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b'UNOPENABLE synthetic body')
        original = c.bounded_read
        opened = []
        def guarded(base, relative):
            self.assertIn(str(relative), self.blobs)
            opened.append(str(relative))
            return original(base, relative)
        with patch.object(c, 'bounded_read', side_effect=guarded):
            value = self.build()
        self.assertTrue(opened)
        self.assertEqual(value['research_file_bodies_opened'], 0)
        self.assertFalse(value['exposure_complete'])
        self.assertFalse(value['grants_sampling_download_or_inference'])
        self.assertFalse(value['fresh_O_store_replay'])
        self.assertNotIn('.env', json.dumps(value))
        self.assertNotIn('UNOPENABLE', json.dumps(value))
        self.assertEqual(value['legacy_manifest_presence'][0]['status'], 'missing_unresolved')

    def test_same_size_restored_mtime_control_drift_refuses(self):
        path = self.base / 'round11/DESIGN.md'
        before = path.stat()
        path.write_bytes(b'x' * before.st_size)
        os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
        with self.assertRaisesRegex(ValueError, 'phase_control_changed'):
            self.build()

    def test_control_symlink_and_nonregular_refuse(self):
        path = self.base / 'round11/DESIGN.md'
        raw = path.read_bytes()
        outside = self.repo.parent / 'outside.md'
        outside.write_bytes(raw)
        path.unlink()
        path.symlink_to(outside)
        with self.assertRaisesRegex(ValueError, 'linked_control_path'):
            self.build()
        path.unlink()
        os.mkfifo(path)
        with self.assertRaisesRegex(ValueError, 'bounded_regular_control_required'):
            self.build()

    def test_control_parent_swap_never_opens_foreign_body(self):
        for timing in ('parent_acquisition', 'leaf_open'):
            with self.subTest(timing=timing), tempfile.TemporaryDirectory() as temporary:
                base = Path(temporary)
                parent = base / 'controls'
                parent.mkdir()
                (parent / 'control').write_bytes(b'allowed synthetic anchor')
                foreign = base / 'foreign'
                foreign.mkdir()
                (foreign / 'control').write_bytes(b'protected synthetic body')
                original = os.open
                opened_foreign = []
                swapped = []
                def racing_open(path, flags, *args, **kwargs):
                    path = Path(path)
                    trigger = ((timing == 'parent_acquisition' and path in (parent, Path('controls')))
                               or (timing == 'leaf_open' and path in (parent / 'control', Path('control'))))
                    if trigger and not swapped:
                        parent.rename(base / 'held_controls')
                        parent.symlink_to(foreign, target_is_directory=True)
                        swapped.append(True)
                    fd = original(path, flags, *args, **kwargs)
                    if Path('/proc/self/fd/' + str(fd)).resolve() == foreign / 'control':
                        opened_foreign.append(True)
                    return fd
                with patch.object(c.os, 'open', side_effect=racing_open):
                    with self.assertRaises((ValueError, OSError)):
                        c.bounded_read(base, 'controls/control')
                self.assertTrue(swapped)
                self.assertEqual(opened_foreign, [])

    def test_census_records_links_without_following_them(self):
        outside = self.repo.parent / 'outside'
        outside.mkdir()
        (outside / 'not_in_census').write_text('synthetic')
        (self.repo / 'alias').symlink_to(outside, target_is_directory=True)
        entries = self.build()['entries']
        self.assertIn({'path': 'alias', 'kind': 'symlink_unresolved'}, entries)
        self.assertNotIn('not_in_census', json.dumps(entries))

    def test_current_anchor_or_recovery_drift_refuses(self):
        path = self.base / 'round10/runs/development/completion.json'
        path.write_text('{}')
        with self.assertRaisesRegex(ValueError, 'phase_control_changed'):
            self.build()
        self.put('round10/runs/development/completion.json', {'synthetic': 'round10/runs/development/completion.json'})
        changed = copy.deepcopy(self.recovery)
        changed['recomputed_score'] = True
        key = 'round10/evidence/postscore_guard_recovery.json'
        self.pins[key] = self.put(key, changed)
        with self.assertRaisesRegex(ValueError, 'completed_O_recovery_required'):
            self.build()

    def test_new_or_changed_path_during_capture_refuses(self):
        original = c.census
        calls = []
        def mutate(repo):
            rows = original(repo)
            calls.append(True)
            if len(calls) == 1:
                (self.repo / 'new_run').write_text('synthetic')
            return rows
        with patch.object(c, 'census', side_effect=mutate):
            with self.assertRaisesRegex(ValueError, 'census_changed_during_capture'):
                self.build()

    def test_bounded_paths_entries_json_and_complete_pins(self):
        with self.assertRaisesRegex(ValueError, 'unsafe_control_path'):
            c.bounded_read(self.base, '../outside')
        with patch.object(c, 'MAX_ENTRIES', 1):
            with self.assertRaisesRegex(ValueError, 'census_entry_bound_exceeded'):
                self.build()
        with self.assertRaisesRegex(ValueError, 'duplicate_control_json_key'):
            c.decode(b'{"x":1,"x":2}')
        with self.assertRaisesRegex(ValueError, 'nonfinite_control_json'):
            c.decode(b'{"x":NaN}')
        self.pins.pop('round11/DESIGN.md')
        with self.assertRaisesRegex(ValueError, 'complete_control_pins_required'):
            self.build()

    def test_network_and_cli_overrides_fail_closed(self):
        header = (b'Inter-| Receive | Transmit\n'
                  b' face |bytes packets errs drop fifo frame compressed multicast|bytes packets errs drop fifo colls carrier compressed\n')
        self.assertTrue(c.isolated_network(header + b'lo: ' + b'0 ' * 16))
        self.assertFalse(c.isolated_network(header + b'eth0: ' + b'0 ' * 16))
        self.assertFalse(c.isolated_network(header + b'lo: ' + b'0 ' * 15))
        with patch.object(c.sys, 'argv', ['source_census.py', '--root', '/tmp']):
            with self.assertRaisesRegex(ValueError, 'census_cli_overrides_refused'):
                c.main()

    def test_directory_entry_bound_applies_before_sort_allocation(self):
        consumed = []
        class CountingIterator:
            def __enter__(self):
                return self
            def __exit__(self, *args):
                pass
            def __iter__(self):
                for i in range(250):
                    consumed.append(i)
                    yield SimpleNamespace(name=str(i), stat=lambda **_: SimpleNamespace(st_mode=stat.S_IFREG, st_size=1))
        with patch.object(c, 'MAX_ENTRIES', 3), patch.object(c.os, 'scandir', return_value=CountingIterator()):
            with self.assertRaisesRegex(ValueError, 'census_entry_bound_exceeded'):
                c.census(self.repo)
        self.assertEqual(len(consumed), 4)

    def test_private_exclusive_output_and_successful_main(self):
        value = self.build()
        with patch.object(c, 'REPO', self.repo), patch.object(c, 'BASE', self.base), \
                patch.object(c, 'CONTROL_PINS', self.pins), patch.object(c.sys, 'argv', ['source_census.py']), \
                patch('builtins.print') as printed:
            c.main()
        output = self.repo / c.OUTPUT
        self.assertEqual(c.decode(output.read_bytes()), value)
        self.assertEqual(stat.S_IMODE(output.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(output.parent.stat().st_mode), 0o700)
        summary = json.loads(printed.call_args.args[0])
        self.assertNotIn('entries', summary)
        self.assertFalse(summary['exposure_complete'])
        self.assertEqual(summary['census_sha256'], c.sha(c.encoded(value)))
        with self.assertRaises(FileExistsError):
            c._write_at(self.repo, c.OUTPUT, value)

    def test_output_parent_swap_cannot_write_into_foreign_directory(self):
        for timing in ('parent_acquisition', 'leaf_open'):
            with self.subTest(timing=timing), tempfile.TemporaryDirectory() as temporary:
                repo = Path(temporary) / 'repo'
                intended = repo / 'private'
                intended.mkdir(parents=True, mode=0o700)
                foreign = repo.parent / 'foreign'
                foreign.mkdir(mode=0o755)
                original = os.open
                swapped = []
                def racing_open(path, flags, *args, **kwargs):
                    path = Path(path)
                    trigger = ((timing == 'parent_acquisition' and path in (intended, Path('private')))
                               or (timing == 'leaf_open' and path in (intended / 'result.json', Path('result.json'))))
                    if trigger and not swapped:
                        intended.rename(repo / 'held_private')
                        intended.symlink_to(foreign, target_is_directory=True)
                        swapped.append(True)
                    return original(path, flags, *args, **kwargs)
                with patch.object(c.os, 'open', side_effect=racing_open):
                    with self.assertRaises((ValueError, OSError)):
                        c._write_at(repo, 'private/result.json', {'private': True})
                self.assertTrue(swapped)
                self.assertFalse((foreign / 'result.json').exists())
                if timing == 'leaf_open':
                    self.assertEqual(c.decode((repo / 'held_private/result.json').read_bytes()), {'private': True})

    def test_main_output_parent_swap_refuses_without_foreign_output(self):
        output = self.repo / c.OUTPUT
        output.parent.mkdir(parents=True, mode=0o700)
        foreign = self.repo.parent / 'foreign_output'
        foreign.mkdir(mode=0o755)
        original = os.open
        swapped = []
        def racing_open(path, flags, *args, **kwargs):
            if flags & os.O_CREAT and Path(path) in (output, Path(output.name)) and not swapped:
                output.parent.rename(self.repo / 'held_inventory')
                output.parent.symlink_to(foreign, target_is_directory=True)
                swapped.append(True)
            return original(path, flags, *args, **kwargs)
        with patch.object(c, 'REPO', self.repo), patch.object(c, 'BASE', self.base), \
                patch.object(c, '_build_at', return_value={'status': 'synthetic', 'entries': []}), \
                patch.object(c.sys, 'argv', ['source_census.py']), patch.object(c.os, 'open', side_effect=racing_open), \
                patch('builtins.print'):
            with self.assertRaises((ValueError, OSError)):
                c.main()
        self.assertTrue(swapped)
        self.assertFalse((foreign / output.name).exists())

    def test_preexisting_regular_and_linked_outputs_remain_unchanged(self):
        for linked in (False, True):
            with self.subTest(linked=linked), tempfile.TemporaryDirectory() as temporary:
                repo = Path(temporary)
                parent = repo / 'private'
                parent.mkdir(mode=0o700)
                target = repo / 'existing'
                target.write_bytes(b'synthetic preserved evidence')
                output = parent / 'result.json'
                if linked:
                    output.symlink_to(target)
                else:
                    output.write_bytes(target.read_bytes())
                with self.assertRaises((ValueError, OSError)):
                    c._write_at(repo, 'private/result.json', {'replacement': True})
                self.assertEqual(target.read_bytes(), b'synthetic preserved evidence')
                self.assertEqual(output.read_bytes(), b'synthetic preserved evidence')

    def test_failed_write_or_fsync_preserves_exclusive_artifact(self):
        original = os.fdopen
        for failure in ('write', 'fsync'):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as temporary:
                repo = Path(temporary)
                value = {'private': 'synthetic value'}
                class PartialWriter:
                    def __init__(self, *args, **kwargs):
                        self.stream = original(*args, **kwargs)
                    def __enter__(self):
                        return self
                    def __exit__(self, *args):
                        self.stream.close()
                    def write(self, raw):
                        self.stream.write(raw[:len(raw)//2])
                        raise OSError('synthetic write failure')
                if failure == 'write':
                    mutation = patch.object(c.os, 'fdopen', PartialWriter)
                else:
                    mutation = patch.object(c.os, 'fsync', side_effect=OSError('synthetic fsync failure'))
                with mutation:
                    with self.assertRaises(OSError):
                        c._write_at(repo, 'private/result.json', value)
                output = repo / 'private/result.json'
                self.assertTrue(output.exists())
                self.assertGreater(output.stat().st_size, 0)
                self.assertEqual(stat.S_IMODE(output.stat().st_mode), 0o600)
                if failure == 'write':
                    self.assertLess(output.stat().st_size, len(c.encoded(value)))
                with self.assertRaises(FileExistsError):
                    c._write_at(repo, 'private/result.json', value)


if __name__ == '__main__':
    unittest.main()
