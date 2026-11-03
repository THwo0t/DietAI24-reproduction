from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import n5_sources as sources


def digest(raw):return hashlib.sha256(raw).hexdigest()


class RestrictedIdentitySourceTests(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory();self.addCleanup(self.temporary.cleanup)
        self.root=Path(self.temporary.name).resolve()
        self.values={}
        self.pixel={'dish_id':'dish_1000000000','bytes_sha256':'1'*64,'rgb_sha256':'2'*64,
                    'truth':{'weight':'MUST_NOT_EXPORT'}}
        for slot in ('cafe1','cafe2','available'):
            self.write_raw(slot,b'SYNTHETIC_RAW_ONLY_NO_REAL_LABELS\n')
        self.write('objects',[])
        self.write('registry',{'exposed_dish_ids':[],'local_dish_ids':[],
                               'exposed_ingredient_group_sha256':[]})
        self.write('cohort_proposal',{'selected_dish_ids':[],
            'original_development_exposure_ids':[],'retired_validation_dish_ids':[]})
        source_pins={sources.PATHS[slot]:self.hash(slot) for slot in
                     ('registry','cafe1','cafe2','available','objects')}
        # These paths must never be chased, even though a trusted inventory
        # records their hashes. None exists in the synthetic directory.
        source_pins.update({'data/cohorts/sealed/validation.jsonl':'3'*64,
            'data/cohorts/sealed/labels.json':'4'*64,'validation/rgb.png':'5'*64,'.env':'6'*64})
        self.write('index',{'original_components':{},'recipe_sha256':{},'screening_components':{},
            'known_image_fingerprints':[self.pixel],'blocked_screening_components':[],
            'source_sha256':source_pins})
        common={'component_members':{},'source_sha256':deepcopy(source_pins)}
        self.write('original_snapshot',common)
        self.write('final_snapshot',{**common,'ambiguous_component_ids':[],
            'active_development_ids':[],'historical_exposure_ids':[]})
        self.write('validation_seal',{'proposal_sha256':self.hash('cohort_proposal'),
            'rules_sha256':'7'*64,'artifacts':{'sealed/labels.json':'8'*64}})
        self.write('development_seal',{'rules_sha256':'7'*64})
        self.write('training_proposal',{'entries':[{'dish_id':'dish_1000000000',
            'unused_source_truth':'MUST_NOT_EXPORT'}]})
        self.write('training_summary',{})
        self.write('training_audit',{'candidate_audit':[self.pixel],
            'target_sum_max_abs_residual':{'weight':'MUST_NOT_EXPORT'}})
        self.write('training_freeze',{'binding':{'proposal_sha256':self.hash('training_proposal'),
            'private_audit_index_sha256':self.hash('index')},
            'artifacts':{'audit.json':self.hash('training_audit'),'labels.json':'9'*64,
                         'images/protected.png':'a'*64}})
        self.anchors={slot:self.hash(slot) for slot in sources.ANCHORS}

    def path(self,slot):return self.root/sources.PATHS[slot]
    def hash(self,slot):return digest(self.path(slot).read_bytes())
    def write_raw(self,slot,raw):
        path=self.path(slot);path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(raw)
    def write(self,slot,value):
        self.values[slot]=deepcopy(value)
        self.write_raw(slot,(json.dumps(value,sort_keys=True)+'\n').encode())
    def load(self):return sources.load_identity_sources(self.root,anchors=self.anchors)

    def test_only_fixed_identity_slots_are_opened_not_protected_inventory_paths(self):
        original=sources.os.open;opened=[]
        allowed={self.path(slot) for slot in sources.PATHS}
        def observe(path,*args,**kwargs):
            self.assertIn(Path(path),allowed);opened.append(Path(path))
            return original(path,*args,**kwargs)
        with patch.object(sources.os,'open',side_effect=observe):projection,reader=self.load()
        self.assertEqual(set(opened),allowed)
        self.assertEqual(len(reader.hashes),15)
        self.assertNotIn('MUST_NOT_EXPORT',str(projection['index']))
        self.assertNotIn('MUST_NOT_EXPORT',str(projection['train_pixels']))
        self.assertEqual(projection['train_entries'],[{'dish_id':'dish_1000000000'}])

    def test_same_size_source_tamper_refuses_initial_load_and_final_revalidation(self):
        _,reader=self.load()
        old=self.path('available').read_bytes()
        self.path('available').write_bytes(b'X'+old[1:])
        with self.assertRaisesRegex(ValueError,'hash_changed'):reader.revalidate()
        with self.assertRaisesRegex(ValueError,'hash_changed'):self.load()

    def test_symlink_substitution_refuses_before_source_open(self):
        target=self.root/'unregistered.csv';target.write_bytes(self.path('available').read_bytes())
        self.path('available').unlink();self.path('available').symlink_to(target)
        with self.assertRaisesRegex(ValueError,'linked_source'):self.load()

    def test_an_index_cannot_redirect_a_fixed_source_or_use_conflicting_alias_pins(self):
        index=deepcopy(self.values['index'])
        index['source_sha256'][str(self.path('available'))]='f'*64
        self.write('index',index);self.anchors['index']=self.hash('index')
        freeze=deepcopy(self.values['training_freeze'])
        freeze['binding']['private_audit_index_sha256']=self.anchors['index']
        self.write('training_freeze',freeze);self.anchors['training_freeze']=self.hash('training_freeze')
        with self.assertRaisesRegex(ValueError,'unambiguous_fixed_source_pin'):self.load()

    def test_changed_trusted_binding_and_missing_anchors_refuse(self):
        missing=deepcopy(self.anchors);missing.pop('training_freeze')
        with self.assertRaisesRegex(ValueError,'complete_trusted'):
            sources.load_identity_sources(self.root,anchors=missing)
        freeze=deepcopy(self.values['training_freeze']);freeze['binding']['proposal_sha256']='f'*64
        self.write('training_freeze',freeze);self.anchors['training_freeze']=self.hash('training_freeze')
        with self.assertRaisesRegex(ValueError,'training_identity_binding'):self.load()

    def test_duplicate_keys_nonfinite_json_and_unregistered_slot_refuse(self):
        reader=sources.IdentitySourceReader(self.root)
        with self.assertRaisesRegex(ValueError,'unregistered_source_slot'):reader.bind('.env','0'*64)
        for raw,error in ((b'{"a":1,"a":2}', 'duplicate_source_json_key'),
                          (b'{"a":NaN}', 'nonfinite_source_json')):
            with self.subTest(error=error):
                self.write_raw('training_summary',raw)
                with self.assertRaisesRegex(ValueError,error):reader.bind('training_summary',digest(raw))

    def test_complete_restricted_reader_to_pool_preserves_protected_target_isolation(self):
        from test_n5_preparation import BlindN5PreparationTests
        from n5_preparation import inspect_pool
        fixture=BlindN5PreparationTests('test_all_protected_targets_remain_poison_and_only_unblocked_candidates_get_truths')
        fixture.setUp();projection=fixture.projection
        for slot,raw in projection['raw_tables'].items():self.write_raw(slot,raw)
        self.write('objects',projection['official_objects'])
        self.write('registry',projection['registry'])
        self.write('cohort_proposal',projection['cohort_proposal'])
        pins={sources.PATHS[slot]:self.hash(slot) for slot in ('registry','cafe1','cafe2','available','objects')}
        self.write('index',{**projection['index'],'source_sha256':pins})
        common={'component_members':projection['snapshot']['component_members'],'source_sha256':pins}
        self.write('original_snapshot',common)
        self.write('final_snapshot',{**common,**projection['snapshot']})
        self.write('validation_seal',{'proposal_sha256':self.hash('cohort_proposal'),'rules_sha256':'7'*64})
        self.write('training_proposal',{'entries':projection['train_entries']})
        self.write('training_audit',{'candidate_audit':projection['train_pixels']})
        self.write('training_freeze',{'binding':{'proposal_sha256':self.hash('training_proposal'),
            'private_audit_index_sha256':self.hash('index')},
            'artifacts':{'audit.json':self.hash('training_audit')}})
        self.anchors={slot:self.hash(slot) for slot in sources.ANCHORS}
        authenticated,reader=self.load()
        private,aggregate=inspect_pool(authenticated,expected_counts=fixture.counts)
        reader.revalidate()
        self.assertEqual(len(private['candidates']),3)
        self.assertEqual(aggregate['source_files_bound'],15)
        self.assertEqual(aggregate['validation_intersections'],0)
        self.assertEqual(aggregate['new_samples_selected'],0)
        self.assertFalse(aggregate['latest_exposure_completeness_proven'])


if __name__=='__main__':unittest.main()
