from copy import deepcopy
import json
import os
from pathlib import Path
import stat
import unittest
from unittest.mock import patch

import source_capture as s
import source_census as c
import n5_sources
import test_source_census as census_fixtures
import test_n5_sources as reader_fixtures
import test_n5_preparation as n5_fixtures
from test_asa_workbook import workbook
import test_asa_archive as archive_fixtures
from test_asa_content_identity import png


class SourceCaptureTests(unittest.TestCase):
    def setUp(self):
        controls = census_fixtures.SourceCensusTests('test_census_never_opens_research_or_secret_bodies')
        controls.setUp()
        self.addCleanup(controls.doCleanups)
        self.repo, self.base, self.controls = controls.repo, controls.base, controls
        for relative in s.IMPLEMENTATION_FILES:
            path = self.base / relative
            if not path.exists():
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b'# SYNTHETIC implementation identity\n')
        self.n5 = n5_fixtures.BlindN5PreparationTests()
        self.n5.setUp()
        p = deepcopy(self.n5.projection)
        p['raw_tables']['available'] = p['raw_tables']['available'].replace(
            b',100,120,2,15,6', b',ALL_TARGETS_POISON,ALL_TARGETS_POISON,ALL_TARGETS_POISON,ALL_TARGETS_POISON,ALL_TARGETS_POISON')
        data = reader_fixtures.RestrictedIdentitySourceTests()
        data.root, data.values = self.repo, {}
        self.data = data
        for slot, raw in p['raw_tables'].items():
            data.write_raw(slot, raw)
        data.write('objects', p['official_objects'])
        data.write('registry', p['registry'])
        data.write('cohort_proposal', p['cohort_proposal'])
        source_pins = {n5_sources.PATHS[slot]: data.hash(slot)
                       for slot in ('registry', 'cafe1', 'cafe2', 'available', 'objects')}
        self.workbook_raw = workbook(
            rows=[[11111111, 'a.png', 'PORTION', 'PROTECTED_TARGET', '=1/0', '=1/0']],
            inventory=[['a.png', '=1/0'], ['orphan.png', 'PROTECTED_TARGET']])
        book_path = self.repo / s.ASA_SOURCES[1]
        book_path.parent.mkdir(parents=True)
        book_path.write_bytes(self.workbook_raw)
        self.archive_path, archive_pin = archive_fixtures.ArchiveTests().write(
            self.repo, [('a.png', png()), ('orphan.png', png((9, 8, 7)))])
        self.protocol = {'source_sha256': {
            s.ASA_SOURCES[0]: archive_pin, s.ASA_SOURCES[1]: c.sha(self.workbook_raw),
            **{name: 'f' * 64 for name in s.ASA_SOURCES[2:]},
            '.env': 'a' * 64, 'data/cohorts/sealed/labels.json': 'b' * 64},
            'frozen_sha256': {'sealed/validation.jsonl': 'c' * 64}}
        self.protocol_path = self.repo / s.V1_PROTOCOL
        self.protocol_path.parent.mkdir(parents=True, exist_ok=True)
        self.protocol_path.write_bytes(c.encoded(self.protocol))
        source_pins[s.V1_PROTOCOL] = c.sha(self.protocol_path.read_bytes())
        data.write('index', {**p['index'], 'source_sha256': source_pins})
        common = {'component_members': p['snapshot']['component_members'], 'source_sha256': source_pins}
        data.write('original_snapshot', common)
        data.write('final_snapshot', {**common, **p['snapshot']})
        data.write('validation_seal', {'proposal_sha256': data.hash('cohort_proposal'), 'rules_sha256': '7' * 64})
        data.write('development_seal', {'rules_sha256': '7' * 64})
        data.write('training_proposal', {'entries': p['train_entries']})
        data.write('training_audit', {'candidate_audit': p['train_pixels']})
        data.write('training_summary', {})
        data.write('training_freeze', {'binding': {'proposal_sha256': data.hash('training_proposal'),
            'private_audit_index_sha256': data.hash('index')}, 'artifacts': {'audit.json': data.hash('training_audit')}})
        self.anchors = {slot: data.hash(slot) for slot in n5_sources.ANCHORS}
        self.census = controls.build()
        c._write_at(self.repo, s.CENSUS, self.census)
        self.census_sha = c.sha(c.encoded(self.census))

    def capture(self):
        return s._capture_at(self.repo, self.base, controls=self.controls.pins,
            census_sha=self.census_sha, n5_anchors=self.anchors, expected_counts=self.n5.counts)

    def test_fixed_source_capture_never_uses_poison_targets_or_protected_inventory_paths(self):
        allowed = {self.repo / relative for relative in n5_sources.PATHS.values()}
        allowed |= {self.base / relative for relative in self.controls.blobs}
        allowed |= {self.base / relative for relative in s.IMPLEMENTATION_FILES}
        allowed |= {self.repo / s.CENSUS, self.protocol_path, self.archive_path,
                    self.repo / s.ASA_SOURCES[1]}
        original = os.open
        opened = []
        def observe(path, flags, *args, **kwargs):
            if not flags & os.O_DIRECTORY:
                parent = Path('/proc/self/fd/' + str(kwargs['dir_fd'])).resolve() if 'dir_fd' in kwargs else None
                full = parent / Path(path) if parent is not None else Path(path)
                self.assertIn(full, allowed)
                opened.append(full)
            return original(path, flags, *args, **kwargs)
        with patch.object(c.os, 'open', side_effect=observe):
            value, summary = self.capture()
        self.assertTrue(opened)
        self.assertEqual(summary['sources_captured'], 18)
        self.assertEqual(summary['implementation_files_bound'], 12)
        self.assertEqual(summary['asa_archive']['png_members'], 2)
        self.assertFalse(value['latest_exposure_completeness_proven'])
        self.assertFalse(value['candidate_eligibility_evaluated'])
        self.assertFalse(value['grants_sampling_download_or_inference'])
        self.assertEqual(value['candidate_targets_interpreted'], 0)
        self.assertNotIn('allowed_ids', value['n5_identity_state'])
        for marker in ('ALL_TARGETS_POISON', 'PROTECTED_TARGET', '=1/0', 'raw_tables', 'frozen_sha256'):
            self.assertNotIn(marker, json.dumps(value))
        self.assertFalse(any(dish in json.dumps(summary) for dish in self.n5.ids.values()))
        self.assertNotIn('a.png', json.dumps(summary))

    def test_stale_census_or_protocol_pin_refuses(self):
        path = self.repo / s.CENSUS
        before = path.read_bytes()
        path.write_bytes(before + b' ')
        with self.assertRaisesRegex(ValueError, 'registered_path_census_required'):
            self.capture()
        path.write_bytes(before)
        self.protocol_path.write_bytes(c.encoded(self.protocol) + b' ')
        with self.assertRaisesRegex(ValueError, 'registered_v1_protocol_changed'):
            self.capture()

    def test_fixed_pin_alias_conflicts_and_arbitrary_paths_are_not_followed(self):
        mapping = {s.ASA_SOURCES[0]: '1' * 64, str(self.repo / s.ASA_SOURCES[0]): '2' * 64,
                   '/never/open/.env': '3' * 64}
        with self.assertRaisesRegex(ValueError, 'unambiguous_registered_capture_pin'):
            s.pin_for(mapping, self.repo, s.ASA_SOURCES[0])
        mapping.pop(str(self.repo / s.ASA_SOURCES[0]))
        self.assertEqual(s.pin_for(mapping, self.repo, s.ASA_SOURCES[0]), '1' * 64)
        with self.assertRaisesRegex(ValueError, 'unambiguous_registered_capture_pin'):
            s.pin_for(mapping, self.repo, s.ASA_SOURCES[1])

    def test_capture_revalidates_sources_after_archive_fingerprinting(self):
        original = s.asa_archive.capture_archive
        def mutate(*args):
            result = original(*args)
            self.data.path('available').write_bytes(b'SYNTHETIC source drift')
            return result
        with patch.object(s.asa_archive, 'capture_archive', side_effect=mutate):
            with self.assertRaisesRegex(ValueError, 'hash_changed'):
                self.capture()

    def test_new_validation_bridge_refuses_before_archive_or_target_eligibility(self):
        original = s.n5_sources.load_identity_sources
        def bridge(*args, **kwargs):
            projection, reader = original(*args, **kwargs)
            projection['train_pixels'][0]['rgb_sha256'] = next(
                row['rgb_sha256'] for row in projection['index']['known_image_fingerprints']
                if row['dish_id'] == self.n5.ids['val'])
            return projection, reader
        with patch.object(s.n5_sources, 'load_identity_sources', side_effect=bridge), \
                patch.object(s.asa_archive, 'capture_archive', side_effect=AssertionError('no archive')):
            with self.assertRaisesRegex(ValueError, 'validation_linkage_requires_separate_resolution'):
                self.capture()

    def test_capture_rejects_implementation_drift(self):
        original = s.asa_archive.capture_archive
        def mutate(*args):
            result = original(*args)
            (self.base / 'round11/source_capture.py').write_bytes(b'# SYNTHETIC changed implementation\n')
            return result
        with patch.object(s.asa_archive, 'capture_archive', side_effect=mutate):
            with self.assertRaisesRegex(ValueError, 'capture_sources_changed'):
                self.capture()

    def test_cli_has_no_fixture_root_pin_or_download_override(self):
        with patch.object(s.sys, 'argv', ['source_capture.py', '--root', '/tmp']):
            with self.assertRaisesRegex(ValueError, 'capture_cli_overrides_refused'):
                s.main()

    def test_successful_synthetic_cli_is_private_and_refuses_a_second_capture(self):
        original = s._capture_at
        def fixture_capture(repo, base):
            self.assertEqual((repo, base), (self.repo, self.base))
            return original(repo, base, controls=self.controls.pins, census_sha=self.census_sha,
                n5_anchors=self.anchors, expected_counts=self.n5.counts)
        with patch.object(s, 'REPO', self.repo), patch.object(s, 'BASE', self.base), \
                patch.object(s, '_capture_at', side_effect=fixture_capture) as capture, \
                patch.object(s.sys, 'argv', ['source_capture.py']), patch('builtins.print') as printed:
            s.main()
            with self.assertRaisesRegex(ValueError, 'fresh_capture_output_required'):
                s.main()
        self.assertEqual(capture.call_count, 1)
        output = self.repo / s.OUTPUT
        value = c.decode(output.read_bytes())
        self.assertEqual(stat.S_IMODE(output.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(output.parent.stat().st_mode), 0o700)
        summary = json.loads(printed.call_args.args[0])
        self.assertEqual(summary['capture_sha256'], c.sha(c.encoded(value)))
        self.assertEqual(summary['api_calls'], 0)
        self.assertFalse(summary['grants_sampling_download_or_inference'])
        self.assertFalse(any(dish in json.dumps(summary) for dish in self.n5.ids.values()))


if __name__ == '__main__':
    unittest.main()
