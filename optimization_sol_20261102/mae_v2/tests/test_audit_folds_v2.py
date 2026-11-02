"""Synthetic assignment audit tests; no real labels or images are opened."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'tools'), str(ROOT / 'src')]
import audit_folds_v2 as audit
import cohorts_v2


def assignments():
    rows = []
    for dataset in audit.DATASETS:
        groups = [dataset + '-group-' + str(i) for i in range(6)]
        expected = audit.registered_folds(groups)
        for i, group in enumerate(groups):
            for image in range(2 if i == 0 else 1):
                fold = (expected[group] + 1) % 5 if dataset == 'asa24' and i == 0 else expected[group]
                rows.append({'sample_id': group + '-sample-' + str(image), 'dataset': dataset,
                             'group_id': group, 'split': 'dev', 'fold': fold})
    return rows


class FoldAuditTests(unittest.TestCase):
    def test_independent_rule_matches_existing_n5_preparer(self):
        groups = ['synthetic-' + str(i) for i in range(23)]
        self.assertEqual(audit.registered_folds(groups), cohorts_v2.five_folds(groups))
        self.assertEqual(audit.registered_folds(reversed(groups)), audit.registered_folds(groups))

    def test_both_datasets_and_group_vs_image_counts(self):
        rows = assignments()
        before = deepcopy(rows)
        result = audit.compare_assignments(rows, rows)
        self.assertEqual(result['asa24']['registered_seed_mismatch_groups'], 1)
        self.assertEqual(result['asa24']['registered_seed_mismatch_images'], 2)
        self.assertEqual(result['nutrition5k']['registered_seed_mismatch_groups'], 0)
        self.assertEqual(result['nutrition5k']['registered_seed_mismatch_images'], 0)
        self.assertEqual(rows, before)
        self.assertNotIn('synthetic-', json.dumps(result))
        self.assertNotIn('sample_id', json.dumps(result))
        self.assertNotIn('group_id', json.dumps(result))

    def test_asa_change_from_legacy_and_n5_seed_mismatch_fail(self):
        rows = assignments()
        changed = deepcopy(rows)
        for row in changed:
            if row['dataset'] == 'asa24':
                row['fold'] = (row['fold'] + 1) % 5
        with self.assertRaises(ValueError):
            audit.compare_assignments(changed, rows)
        changed = deepcopy(rows)
        for row in changed:
            if row['dataset'] == 'nutrition5k':
                row['fold'] = (row['fold'] + 1) % 5
        with self.assertRaises(ValueError):
            audit.compare_assignments(changed, rows)

    def test_group_leak_invalid_fold_duplicate_nondev_or_missing_dataset_fail(self):
        original = assignments()
        cases = []
        for key, value in (('fold', (original[0]['fold'] + 1) % 5), ('fold', True), ('split', 'validation')):
            rows = deepcopy(original)
            rows[0][key] = value
            cases.append(rows)
        cases.extend([original + [original[0]], [r for r in original if r['dataset'] == 'asa24']])
        for rows in cases:
            with self.subTest(case=cases.index(rows)), self.assertRaises(ValueError):
                audit.compare_assignments(rows, original)

    def setup_artifacts(self, base):
        root, v1 = base / 'v2', base / 'v1'
        rows = assignments()
        def put(parent, relative, data):
            target = parent / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        for relative in audit.ORIGINALS.values():
            put(root, relative, b'{}\n')
        manifest = b''.join(audit.canonical(row) for row in rows)
        put(root, 'data/cohorts/dev.jsonl', manifest)
        put(v1, 'data/cohorts/dev.jsonl', manifest)
        put(root, 'data/cohorts/dev_freeze.json', audit.canonical({'seed': audit.SEED,
            'artifacts': {'data/cohorts/dev.jsonl': audit.sha(manifest)}}))
        put(root, 'runs/development/completion.json', audit.canonical({
            'status': 'development_targets_not_met', 'active_development_rows': len(rows)}))
        put(root, 'runs/development/asa-retrieval-portion/run_config.json', audit.canonical({
            'protocol_sha256': audit.sha((root / 'PROTOCOL.md').read_bytes())}))
        return root, v1

    def test_file_audit_never_opens_labels_images_or_validation_and_preserves_originals(self):
        with tempfile.TemporaryDirectory(dir=ROOT, prefix='.fold-audit-test-') as temporary:
            root, v1 = self.setup_artifacts(Path(temporary))
            original = Path.open
            def guard(path, *args, **kwargs):
                if 'labels' in path.name or 'images' in path.parts or 'sealed' in path.parts or 'validation' in path.parts or path.name == '.env':
                    raise AssertionError('forbidden read')
                return original(path, *args, **kwargs)
            with patch.object(Path, 'open', guard):
                result = audit.audit(root, v1)
                audit.write_evidence(root, result)
                audit.write_evidence(root, result)
            self.assertTrue(result['original_artifacts_unchanged'])
            self.assertFalse(result['prediction_or_metric_recomputation_performed'])
            self.assertFalse(result['labels_read'])
            self.assertNotIn('asa24-group', json.dumps(result))
            for alias, relative in audit.ORIGINALS.items():
                self.assertEqual(audit.sha((root / relative).read_bytes()), result['original_artifact_sha256'][alias])
            with self.assertRaises(ValueError):
                audit.write_evidence(root, {**result, 'changed': True})

    def test_manifest_seal_and_protocol_binding_fail_closed(self):
        with tempfile.TemporaryDirectory(dir=ROOT, prefix='.fold-audit-test-') as temporary:
            root, v1 = self.setup_artifacts(Path(temporary))
            path = root / 'data/cohorts/dev.jsonl'
            before = path.read_bytes()
            path.write_bytes(before + b'\n')
            with self.assertRaises(ValueError):
                audit.audit(root, v1)
            path.write_bytes(before)
            (root / 'PROTOCOL.md').write_text('changed')
            with self.assertRaises(ValueError):
                audit.audit(root, v1)

    def test_original_change_during_audit_is_detected(self):
        with tempfile.TemporaryDirectory(dir=ROOT, prefix='.fold-audit-test-') as temporary:
            root, v1 = self.setup_artifacts(Path(temporary))
            compare = audit.compare_assignments
            def drift(*args):
                result = compare(*args)
                (root / audit.ORIGINALS['selected_oof_predictions']).write_text('changed during audit')
                return result
            with patch.object(audit, 'compare_assignments', side_effect=drift):
                with self.assertRaises(ValueError):
                    audit.audit(root, v1)


if __name__ == '__main__':
    unittest.main()
