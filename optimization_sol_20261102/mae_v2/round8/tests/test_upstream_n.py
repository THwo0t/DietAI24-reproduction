"""Negative proofs for sealed-source and caller-catalog boundaries; synthetic only."""
from copy import deepcopy
from contextlib import ExitStack
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

BASE = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(BASE), str(BASE/'src'), str(BASE/'round7/src'), str(BASE/'round8/src')]
import upstream_n as u
from opt_provider import fingerprint

class ImportBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.catalog = {'foods': {'unused': {'density': {'energy': 20}}}}
        self.rows = [{'sample_id': str(i)} for i in range(183)]
        self.frozen = {'source_files': {'old.py': 'frozen-source'}}
        self.proof = {'complete_images': 183, 'M_replay_provider_constructed': False,
            'query_references_loaded': False, 'validation_opened': False, 'new_api_calls': 0,
            'M_freeze_sha256': u.M_FREEZE_SHA256, 'M_source_sha256': deepcopy(self.frozen['source_files']),
            'importer_sha256': 'importer', 'catalog_sha256': 'catalog', 'manifest_sha256': 'manifest',
            'rows_sha256': fingerprint(self.rows)}
        self.bundle = {'schema_version': 1, 'rows': self.rows, 'records': {str(i): {} for i in range(183)},
                       'proof': self.proof}
        (self.root/'round7/prepared').mkdir(parents=True)
        (self.root/'data/cohorts').mkdir(parents=True)
        import json
        (self.root/'round7/prepared/freeze.json').write_text(json.dumps(self.frozen))
        (self.root/'data/catalog.json').write_text(json.dumps(self.catalog))
        (self.root/'data/cohorts/dev.jsonl').write_text('\n'.join(json.dumps(r) for r in self.rows))
        self.stack = ExitStack(); self.addCleanup(self.stack.close)
        self.enter = self.stack.enter_context
        self.enter(patch.object(u, 'ROOT', self.root)); self.enter(patch.object(u, 'M', self.root/'round7'))
        def sha(path):
            path = Path(path)
            return { 'freeze.json': u.M_FREEZE_SHA256, 'upstream_n.py': 'importer',
                     'catalog.json': 'catalog', 'dev.jsonl': 'manifest'}[path.name]
        self.enter(patch.object(u, 'sha', sha))
        self.pins = self.enter(patch.object(u, 'm_source_pins', return_value=self.proof['M_source_sha256']))

    def test_synchronized_source_and_self_reported_proof_cannot_escape_frozen_source(self):
        self.proof['M_source_sha256'] = {'old.py': 'changed-source'}
        self.pins.return_value = self.proof['M_source_sha256']
        with self.assertRaisesRegex(ValueError, 'unfrozen_M_sources'):
            u.verify_imports(self.bundle, self.catalog)

    def test_unused_caller_food_change_is_rejected_before_store_or_inference(self):
        changed = deepcopy(self.catalog); changed['foods']['unused']['density']['energy'] = 21
        with patch.object(u, 'ArtifactStore', side_effect=AssertionError('must reject before store')):
            with self.assertRaisesRegex(ValueError, 'caller_catalog_changed'):
                u.verify_imports(self.bundle, changed)

    def test_false_zero_api_claim_and_population_changes_rejected(self):
        for key, value in [('new_api_calls', 1), ('validation_opened', True), ('complete_images', 182)]:
            changed = deepcopy(self.bundle); changed['proof'][key] = value
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, 'audit_claim_changed'):
                u.verify_imports(changed, self.catalog)
        changed = deepcopy(self.bundle); changed['rows'].pop()
        with self.assertRaisesRegex(ValueError, 'assets_changed'):
            u.verify_imports(changed, self.catalog)

    def test_scientific_stage_raw_and_parsed_cannot_diverge(self):
        class Store:
            def _json(self, name): return {'kind':'result','raw':{'grams':1},'parsed':{'grams':2}}
        with self.assertRaisesRegex(ValueError, 'stage_envelope_changed'):
            u.stage_raw(Store(), 'synthetic-stage')

if __name__ == '__main__': unittest.main()
