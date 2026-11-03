"""Synthetic-only tests; no actual sources or network calls."""
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch
import asa_source_capture as s
import source_census as c
import n5_sources
import test_source_capture as fixtures

class AsaSourceCaptureTests(unittest.TestCase):
    def setUp(self):
        self.f = f = fixtures.SourceCaptureTests()
        f.setUp()
        self.addCleanup(f.doCleanups)
        self.repo, self.base = f.repo, f.base
        for name in s.IMPLEMENTATION_FILES:
            path = self.base / name
            if not path.exists(): path.write_bytes(b'# SYNTHETIC implementation\n')
        self.refusal = {'status': 'mechanical_identity_capture_stopped_for_blind_linkage_resolution',
            'stop_code': 'validation_linkage_requires_separate_resolution',
            'eligibility_or_inference_granted': False, 'completed_capture_artifact': False,
            'asa_source_archive_opened': False}
        self.diagnostic = {'original_linkage_guard_remains_stopped': True,
            'grants_eligibility_download_or_inference': False,
            'actual_API_exposure_proven': False, 'api_calls': 0}
        for name, value in ((s.REFUSAL, self.refusal), (s.DIAGNOSTIC, self.diagnostic)):
            (self.base / name).write_bytes(c.encoded(value))
        self.refusal_raw = (self.base / s.REFUSAL).read_bytes()
        path = self.repo / s.ASA_SOURCES[2]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'ALL_NUMERIC_FIELDS_POISON_DO_NOT_PARSE\n')
        # Historical protocols legitimately omitted top1000.
        self.f.protocol['source_sha256'].pop(s.ASA_SOURCES[2])
        self.persist_protocol()

    def persist_protocol(self):
        f = self.f
        f.protocol_path.write_bytes(c.encoded(f.protocol))
        snapshot = dict(f.data.values['original_snapshot'])
        snapshot['source_sha256'] = {**snapshot['source_sha256'],
            s.PROTOCOLS[0]: c.sha(f.protocol_path.read_bytes())}
        f.data.write('original_snapshot', snapshot)


    def capture(self):
        f = self.f
        return s._capture_at(self.repo, self.base, controls=f.controls.pins,
            census_sha=f.census_sha, snapshot_sha=f.data.hash('original_snapshot'),
            refusal_sha=c.sha(c.encoded(self.refusal)), diagnostic_sha=c.sha(c.encoded(self.diagnostic)))

    def test_fixed_source_allowlist_poison_and_original_stop_retained(self):
        f = self.f
        allowed = {self.base / name for name in (*s.IMPLEMENTATION_FILES, s.REFUSAL, s.DIAGNOSTIC)}
        allowed |= {self.base / name for name in f.controls.blobs}
        allowed |= {self.repo / name for name in (s.CENSUS, s.PROTOCOLS[0],
            n5_sources.PATHS['original_snapshot'], *s.ASA_SOURCES[:3])}
        opened = []; original = os.open
        def observe(path, flags, *args, **kwargs):
            if not flags & os.O_DIRECTORY:
                parent = Path('/proc/self/fd/' + str(kwargs['dir_fd'])).resolve() if 'dir_fd' in kwargs else None
                full = parent / Path(path) if parent is not None else Path(path)
                self.assertIn(full, allowed); opened.append(full)
            return original(path, flags, *args, **kwargs)
        with patch.object(c.os, 'open', side_effect=observe), patch.object(
                n5_sources, 'load_identity_sources', side_effect=AssertionError('no N5 replay')):
            private, summary = self.capture()
        self.assertTrue(opened)
        self.assertEqual(private['asa_source_pin_origin'][s.ASA_SOURCES[2]],
                         'prospective_fixed_source_capture')
        self.assertEqual(private['registered_asa_sources_sha256'],
                         {name: (c.sha((self.repo / name).read_bytes()) if name == s.ASA_SOURCES[2]
                         else f.protocol['source_sha256'][name]) for name in s.ASA_SOURCES})
        self.assertEqual(summary['asa_archive']['png_members'], 2)
        for marker in ('PROTECTED_TARGET', '=1/0', 'a.png', '11111111'):
            self.assertNotIn(marker, json.dumps(summary))
        for marker in ('PROTECTED_TARGET', '=1/0', 'raw_tables', 'frozen_sha256'):
            self.assertNotIn(marker, json.dumps(private))
        self.assertFalse(summary['candidate_eligibility_evaluated'])
        self.assertFalse(summary['grants_sampling_download_or_inference'])
        self.assertEqual((self.base / s.REFUSAL).read_bytes(), self.refusal_raw)

    def test_protocol_drift_refuses(self):
        self.f.protocol_path.write_bytes(b'{}')
        with self.assertRaisesRegex(ValueError, 'source_hash_changed'): self.capture()

    def test_conflicting_fixed_protocol_pins_refuse(self):
        f = self.f
        path = self.repo / s.PROTOCOLS[1]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(c.encoded({'source_sha256': {s.ASA_SOURCES[0]: 'a' * 64}}))
        snapshot = dict(f.data.values['original_snapshot'])
        snapshot['source_sha256'] = {**snapshot['source_sha256'], s.PROTOCOLS[1]: c.sha(path.read_bytes())}
        f.data.write('original_snapshot', snapshot)
        with self.assertRaisesRegex(ValueError, 'consistent_fixed_asa_pins'): self.capture()

    def test_source_and_implementation_drift_refuse(self):
        original = s.asa_archive.capture_archive
        for name in (s.IMPLEMENTATION_FILES[0], None, 'TOP1000'):
            path = self.repo / s.ASA_SOURCES[2] if name == 'TOP1000' else (self.base / name if name else self.f.protocol_path)
            before = path.read_bytes()
            def drift(*args):
                result = original(*args); path.write_bytes(before + b' '); return result
            with patch.object(s.asa_archive, 'capture_archive', side_effect=drift):
                with self.assertRaisesRegex(ValueError, 'sources_changed'): self.capture()
            path.write_bytes(before)

    def test_original_refusal_is_required_and_retained(self):
        (self.base / s.REFUSAL).write_bytes(self.refusal_raw + b' ')
        with patch.object(s.asa_archive, 'capture_archive', side_effect=AssertionError('no archive')):
            with self.assertRaisesRegex(ValueError, 'source_hash_changed'): self.capture()
        self.assertEqual((self.base / s.REFUSAL).read_bytes(), self.refusal_raw + b' ')

    def test_missing_source_and_conflicting_alias_refuse(self):
        f = self.f
        for conflict in (False, True):
            protocol = json.loads(c.encoded(f.protocol))
            if conflict:
                protocol['source_sha256'][str(self.repo / s.ASA_SOURCES[0])] = 'a' * 64
            else:
                del protocol['source_sha256'][s.ASA_SOURCES[3]]
            f.protocol_path.write_bytes(c.encoded(protocol))
            snapshot = dict(f.data.values['original_snapshot'])
            snapshot['source_sha256'] = {**snapshot['source_sha256'],
                s.PROTOCOLS[0]: c.sha(f.protocol_path.read_bytes())}
            f.data.write('original_snapshot', snapshot)
            with self.assertRaises(ValueError): self.capture()

    def test_control_and_census_drift_refuse_before_archive(self):
        for path in (self.repo / s.CENSUS, self.base / next(iter(self.f.controls.pins))):
            before = path.read_bytes()
            path.write_bytes(before + b' ')
            with patch.object(s.asa_archive, 'capture_archive', side_effect=AssertionError('no archive')):
                with self.assertRaises(ValueError): self.capture()
            path.write_bytes(before)

    def test_inherited_top1000_pin_must_match_prospective_bytes(self):
        self.f.protocol['source_sha256'][s.ASA_SOURCES[2]] = 'a' * 64
        self.persist_protocol()
        with self.assertRaisesRegex(ValueError, 'inherited_top1000_source_hash_changed'):
            self.capture()
        self.f.protocol['source_sha256'][s.ASA_SOURCES[2]] = c.sha(
            (self.repo / s.ASA_SOURCES[2]).read_bytes())
        self.persist_protocol()
        value, _ = self.capture()
        self.assertEqual(value['asa_source_pin_origin'][s.ASA_SOURCES[2]],
                         'inherited_registered_protocol')

    def test_public_capture_has_no_override(self):
        with self.assertRaises(TypeError): s.capture(repo=self.repo)

if __name__ == '__main__': unittest.main()
