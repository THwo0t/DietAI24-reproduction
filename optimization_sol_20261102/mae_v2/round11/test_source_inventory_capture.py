from contextlib import ExitStack
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

import source_inventory_capture as s


class SourceInventoryCaptureTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.repo = Path(temporary.name) / 'project'
        self.repo.mkdir()
        self.base = self.repo / s.PREFIX.rstrip('/')
        for name in s.IMPLEMENTATION_FILES:
            path = self.base / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b'SYNTHETIC implementation')
        self.image = 'frozen/copy.png'
        (self.repo / 'frozen').mkdir()
        (self.repo / self.image).write_bytes(b'SYNTHETIC IMAGE')
        self.controls = {'recorded_O_receipt': 'a' * 64}
        self.n5 = {'raw_tables': {'available': b'POISON_ALL_TARGETS'},
            'index': {'known_image_fingerprints': []}, 'snapshot': {}, 'cohort_proposal': {},
            'registry': {}, 'train_entries': [], 'train_pixels': [], 'source_hashes': {}}
        self.development = {'n5_core': {'rows': [], 'labels_sha256': 'b' * 64}, 'asa_rows': []}
        self.metadata = {'projection': {'entries': [{'path': self.image, 'bytes': 15, 'image': True}],
                'counts': {'images': 1}}, 'link_metadata_private': {'links': []}}
        self.content = {'rows_private': [{'path': self.image,
            'bytes_sha256': s.sha(b'SYNTHETIC IMAGE')}], 'counts': {'images': 1}}
        self.metadata['projection']['entries'][0]['bytes'] = len(b'SYNTHETIC IMAGE')
        self.asa = {'source_sha256': {}, 'registered_asa_sources_sha256': {}}
        self.legacy = {'sources': [], 'summary': {'fixed_manifest_count': 4}, 'private_identities': []}
        self.folds = {'screening_component_count': 6, 'fold_unit_count': 6,
            'ambiguous_core_components': 0, 'uncertainty_containment_units': 0,
            'fold_row_counts': {0: 2, 1: 1, 2: 1, 3: 1, 4: 1}, 'old_fold_bridge_components': []}
        self.revalidations = []

    def mocked_collection(self, action=None):
        def n5_loaded(*args, **kwargs):
            return self.n5, SimpleNamespace(revalidate=lambda: self.revalidations.append('n5'))
        def dev_loaded(*args, **kwargs):
            return self.development, SimpleNamespace(revalidate=lambda: self.revalidations.append('dev'))
        with ExitStack() as stack:
            bindings = [
                (s, 'control_evidence', lambda *a: self.controls),
                (s.n5_sources, 'load_identity_sources', n5_loaded),
                (s.development_identity, '_load_development_identity', dev_loaded),
                (s.asa_source_capture, '_capture_at', lambda *a, **k: (self.asa, {'status': 'mechanical'})),
                (s.legacy_input_identity, '_load_at', lambda *a: self.legacy),
                (s.local_input_inventory, 'inventory_metadata', lambda *a: self.metadata),
                (s.local_input_inventory, 'load_projected', lambda *a: self.metadata['projection']),
                (s.local_input_inventory, 'inspect_links', lambda *a: self.metadata['link_metadata_private']),
                (s.local_content_inventory, '_load_at', lambda *a: self.content),
                (s, 'raw_scans', lambda *a: {'identity_only': True}),
                (s, 'reconcile_lineage', lambda *a, **k: ({'original_core_unchanged': True}, {'supplied': True})),
                (s, 'overlay_potential_identity', lambda *a: ({'all_local_rows_retained': True}, {'source_completeness_proven': False})),
                (s, 'rebuild_core_folds', action or (lambda *a: self.folds)),
            ]
            for owner, name, function in bindings:
                stack.enter_context(patch.object(owner, name, side_effect=function))
            return s._collect_at(self.repo, self.base)

    def test_orchestration_keeps_all_actions_and_source_closure_pending(self):
        before = deepcopy((self.n5, self.development, self.metadata, self.content))
        value, summary = self.mocked_collection()
        self.assertEqual(self.revalidations, ['n5', 'dev'])
        self.assertEqual((self.n5, self.development, self.metadata, self.content), before)
        for key in ('source_association_complete', 'potential_input_coverage_complete',
                    'actual_api_exposure_complete', 'candidate_eligibility_evaluated',
                    'grants_sampling_download_or_inference', 'food_visual_analysis_performed'):
            self.assertIs(summary[key], False)
        self.assertTrue(summary['local_images_may_include_sealed_copies'])
        self.assertEqual(summary['local_images_mechanically_fingerprinted'], 1)
        self.assertEqual(summary['candidate_targets_interpreted'], 0)
        self.assertEqual(summary['sealed_label_files_opened'], 0)
        self.assertEqual(value['n5_identity_state_private'], {'all_local_rows_retained': True})
        self.assertNotIn('POISON_ALL_TARGETS', str(value))
        self.assertNotIn(self.image, str(summary))
        self.assertNotIn('a' * 64, str(summary))

    def test_drift_after_composition_refuses_before_any_write(self):
        def drift(*a):
            (self.repo / self.image).write_bytes(b'CHANGED')
            return self.folds
        with patch.object(s, '_write_at', side_effect=AssertionError('must not write')):
            with self.assertRaisesRegex(ValueError, 'local_inventory_image_changed'):
                self.mocked_collection(drift)

    def test_implementation_drift_refuses(self):
        def drift(*a):
            (self.base / s.IMPLEMENTATION_FILES[0]).write_bytes(b'CHANGED')
            return self.folds
        with self.assertRaisesRegex(ValueError, 'inventory_sources_changed'):
            self.mocked_collection(drift)

    def test_empty_legacy_manifest_change_during_composition_refuses(self):
        relative = s.legacy_input_identity.LEGACY_MANIFESTS[0]
        path = self.repo.parent / relative
        path.parent.mkdir(parents=True)
        original = b'dataset,image_path\n'
        path.write_bytes(original)
        self.legacy['sources'] = [{'path': relative, 'status': 'empty_unresolved',
                                  'sha256': s.sha(original)}]
        def drift(*a):
            path.write_bytes(b'CHANGED')
            return self.folds
        with self.assertRaisesRegex(ValueError, 'legacy_inventory_source_changed'):
            self.mocked_collection(drift)

    def test_missing_legacy_manifest_appearance_during_composition_refuses(self):
        relative = s.legacy_input_identity.LEGACY_MANIFESTS[0]
        path = self.repo.parent / relative
        self.legacy['sources'] = [{'path': relative, 'status': 'missing_unresolved'}]
        def drift(*a):
            path.parent.mkdir(parents=True)
            path.write_bytes(b'APPEARED')
            return self.folds
        with self.assertRaisesRegex(ValueError, 'legacy_inventory_source_changed'):
            self.mocked_collection(drift)

    def test_empty_legacy_manifest_removal_during_composition_refuses(self):
        relative = s.legacy_input_identity.LEGACY_MANIFESTS[0]
        path = self.repo.parent / relative
        path.parent.mkdir(parents=True)
        original = b'dataset,image_path\n'
        path.write_bytes(original)
        self.legacy['sources'] = [{'path': relative, 'status': 'empty_unresolved',
                                  'sha256': s.sha(original)}]
        def drift(*a):
            path.unlink()
            return self.folds
        with self.assertRaisesRegex(ValueError, 'legacy_inventory_source_changed'):
            self.mocked_collection(drift)

    def test_unchanged_empty_and_missing_legacy_records_remain_unresolved(self):
        empty, missing = s.legacy_input_identity.LEGACY_MANIFESTS[:2]
        path = self.repo.parent / empty
        path.parent.mkdir(parents=True)
        path.write_bytes(b'dataset,image_path\n')
        self.legacy['sources'] = [
            {'path': empty, 'status': 'empty_unresolved', 'sha256': s.sha(path.read_bytes())},
            {'path': missing, 'status': 'missing_unresolved'}]
        value, summary = self.mocked_collection()
        self.assertFalse(summary['potential_input_coverage_complete'])
        self.assertEqual(value['legacy_inputs_private']['sources'], self.legacy['sources'])

    def test_duplicate_or_omitted_local_image_inventory_refuses(self):
        self.content['rows_private'] = []
        with self.assertRaisesRegex(ValueError, 'complete_local_image_inventory_required'):
            self.mocked_collection()

    def test_fixed_asa_source_final_hashes_include_archive_and_catalogue(self):
        hashes = {}
        for relative in s.asa_source_capture.ASA_SOURCES:
            path = self.repo / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b'SYNTHETIC source')
            hashes[relative] = s.sha(b'SYNTHETIC source')
        value = {'source_sha256': {}, 'registered_asa_sources_sha256': hashes}
        s.verify_asa_bindings(self.repo, value)
        (self.repo / s.asa_source_capture.ASA_SOURCES[-1]).write_bytes(b'CHANGED')
        with self.assertRaisesRegex(ValueError, 'asa_inventory_source_changed'):
            s.verify_asa_bindings(self.repo, value)

    def test_public_cli_rejects_overrides_and_existing_output(self):
        with patch.object(s.sys, 'argv', ['capture', '--root', '/other']), \
                patch.object(s, '_collect_at', side_effect=AssertionError('must not collect')):
            with self.assertRaisesRegex(ValueError, 'inventory_cli_overrides_refused'):
                s.main()
        output = self.repo / s.OUTPUT
        output.parent.mkdir(parents=True)
        output.write_bytes(b'IMMUTABLE')
        with patch.object(s.sys, 'argv', ['capture']), patch.object(s, 'REPO', self.repo), \
                patch.object(s, 'isolated_network', return_value=True), \
                patch.object(s, '_collect_at', side_effect=AssertionError('must not collect')):
            with self.assertRaisesRegex(ValueError, 'fresh_inventory_output_required'):
                s.main()
        self.assertEqual(output.read_bytes(), b'IMMUTABLE')


if __name__ == '__main__':
    unittest.main()
