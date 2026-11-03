"""Synthetic-only identity reader checks; never load project data."""
from contextlib import ExitStack
from copy import deepcopy
from pathlib import Path
import os
import json
import tempfile
import unittest
from unittest.mock import Mock, patch

import training_identity as training
from source_census import encoded, sha


def line(value):
    return json.dumps(value, sort_keys=True).encode()+b'\n'


def fixture():
    dishes = ['dish_0000000001', 'dish_0000000002']
    hashes = [sha(str(i).encode()) for i in range(6)]
    candidates = [{'dish_id': d, 'screening_component_id': 'screen-'+str(i),
        'bytes_sha256': hashes[2*i], 'rgb_sha256': hashes[2*i+1],
        'quarantine_reasons': [] if i == 0 else ['protected_bytes_sha256']}
        for i,d in enumerate(dishes)]
    n5 = {'source_hashes': {'training_proposal': hashes[4], 'index': hashes[5]},
        'train_entries': [{'dish_id': d} for d in dishes],
        'train_pixels': [{k:r[k] for k in ('dish_id', 'bytes_sha256', 'rgb_sha256')}
                         for r in candidates],
        'index': {'screening_components': {d:'screen-'+str(i) for i,d in enumerate(dishes)},
                  'original_components': {d:'original-'+str(i) for i,d in enumerate(dishes)},
                  'recipe_sha256': {d:hashes[4] for d in dishes}}}
    row = {'sample_id': 'nutrition5k-'+dishes[0], 'dataset': 'nutrition5k', 'split': 'train',
        'group_id': 'screen-0', 'original_component_id': 'original-0', 'recipe_sha256': hashes[4],
        'image_path': training.TRAIN+'/images/'+hashes[0]+'.png',
        'image_sha256': hashes[0], 'rgb_sha256': hashes[1]}
    counts = {'accepted_images': 1, 'accepted_groups': 1, 'quarantined_images': 1}
    binding = {'proposal_sha256': hashes[4], 'private_audit_index_sha256': hashes[5]}
    audit = {'schema_version': 1, **binding, **counts, 'complete_candidate_count': 2,
        'candidate_audit': candidates,
        'quarantine_reason_counts_overlapping': {'protected_bytes_sha256': 1},
        # Mixed audit numerical fields are deliberately never projected/interpreted.
        'target_sum_max_abs_residual': {'poison': 'not a number'}}
    raw = line(row)
    freeze = {'schema_version': 1, 'status': 'accepted_external_training_frozen',
        'binding': binding, **counts, 'artifacts': {'manifest.jsonl': sha(raw),
            'images/'+hashes[0]+'.png': hashes[0],
            '../protected/labels.json': 'poison'}}
    return n5, audit, freeze, raw


class TrainingTests(unittest.TestCase):
    def project(self, values):
        n5,audit,freeze,raw=values
        return training._projection(n5,audit,freeze,raw,expected_count=2)

    def test_rejected_proposal_remains_protected(self):
        result=self.project(fixture())
        self.assertEqual(result['counts']['protected_training_proposals'],2)
        self.assertEqual(len(result['accepted_manifest_private']),1)
        self.assertTrue(all(r['protected_training_proposal'] for r in result['protected_proposals_private']))
        self.assertFalse(result['grants_sampling_download_or_inference'])
        self.assertNotIn('target_sum_max_abs_residual',result)

    def test_missing_accepted_or_extra_identity(self):
        for mode in ('missing','extra'):
            n5,audit,freeze,raw=fixture()
            if mode=='missing': raw=b''
            else:
                row=training.decode(raw); row['sample_id']='nutrition5k-dish_0000000003'
                raw+=line(row)
            with self.subTest(mode=mode),self.assertRaises(ValueError):
                self.project((n5,audit,freeze,raw))

    def test_manifest_target_poison_and_untrusted_path_refused(self):
        for key,value in [('truth',{'energy':1}),('image_path','/tmp/protected.png'),
                          ('image_sha256','bad')]:
            n5,audit,freeze,raw=fixture(); row=training.decode(raw); row[key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):
                self.project((n5,audit,freeze,line(row)))

    def test_audit_proposal_pixels_and_counts_tamper(self):
        for mode in ('proposal','pixels','counts','quarantine'):
            values=list(deepcopy(fixture())); n5,audit,freeze,_=values
            if mode=='proposal': n5['train_entries'].pop()
            elif mode=='pixels': audit['candidate_audit'][0]['bytes_sha256']='f'*64
            elif mode=='counts': freeze['accepted_images']=2
            else: audit['candidate_audit'][1]['quarantine_reasons']=[]
            with self.subTest(mode=mode),self.assertRaises(ValueError):self.project(values)

    def load_fixture(self,stack):
        root=Path(stack.enter_context(tempfile.TemporaryDirectory())).resolve()
        n5,audit,freeze,raw=fixture()
        reader=Mock();reader.bound={'training_freeze':encoded(freeze),'training_audit':encoded(audit)}
        stack.enter_context(patch.object(training.n5_sources,'load_identity_sources',return_value=(n5,reader)))
        opened=[]
        def read(repo,path):
            opened.append((repo,path))
            self.assertEqual(repo,root);self.assertEqual(path,training.MANIFEST)
            return raw
        readmock=stack.enter_context(patch.object(training,'bounded_read',side_effect=read))
        return root,reader,readmock,opened

    def test_fixed_slots_env_and_protected_paths_not_followed(self):
        with ExitStack() as stack:
            root,reader,_,opened=self.load_fixture(stack)
            stack.enter_context(patch.dict(os.environ,{'TRAINING_ROOT':'/forbidden',
                'TRAINING_FREEZE_SHA256':'f'*64,'MANIFEST':'/forbidden/labels.json'}))
            result,bound=training._load_at(root,expected_count=2)
            bound.revalidate()
            self.assertGreaterEqual(len(opened),3)
            self.assertGreaterEqual(reader.revalidate.call_count,3)
            self.assertFalse(result['labels_or_ingredients_or_images_opened'])

    def test_manifest_hash_and_later_snapshot_tamper(self):
        with ExitStack() as stack:
            root,reader,readmock,_=self.load_fixture(stack)
            readmock.side_effect=None;readmock.return_value=b'tamper'
            with self.assertRaisesRegex(ValueError,'training_manifest_hash_changed'):
                training._load_at(root,expected_count=2)
        with ExitStack() as stack:
            root,reader,readmock,_=self.load_fixture(stack)
            _,bound=training._load_at(root,expected_count=2)
            readmock.side_effect=None;readmock.return_value=b'tamper'
            with self.assertRaisesRegex(ValueError,'training_manifest_changed'):bound.revalidate()

    def test_source_reader_drift_propagates(self):
        with ExitStack() as stack:
            root,reader,_,_=self.load_fixture(stack)
            _,bound=training._load_at(root,expected_count=2)
            reader.revalidate.side_effect=ValueError('identity_source_hash_changed')
            with self.assertRaisesRegex(ValueError,'identity_source_hash_changed'):bound.revalidate()

    def test_manifest_symlink_and_linked_ancestor_refused(self):
        for ancestor in (False, True):
            with self.subTest(ancestor=ancestor), tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp).resolve(); n5,audit,freeze,raw=fixture()
                reader=Mock(); reader.bound={'training_freeze':encoded(freeze),
                                             'training_audit':encoded(audit)}
                target=root/'private-target'; target.write_bytes(raw)
                manifest=root/training.MANIFEST
                if ancestor:
                    outside=root/'alternate'; outside.mkdir()
                    (root/'optimization_sol_20261102').symlink_to(outside,target_is_directory=True)
                else:
                    manifest.parent.mkdir(parents=True)
                    manifest.symlink_to(target)
                with patch.object(training.n5_sources,'load_identity_sources',return_value=(n5,reader)):
                    with self.assertRaises((ValueError,OSError)):
                        training._load_at(root,expected_count=2)
                self.assertEqual(target.read_bytes(),raw)

    def test_public_entry_has_no_overrides(self):
        with patch.object(training,'_load_at',return_value=('projection','reader')) as load:
            self.assertEqual(training.load_training_identity(),('projection','reader'))
            load.assert_called_once_with(training.REPO)
        with self.assertRaises(TypeError):training.load_training_identity('/tmp')


if __name__=='__main__':unittest.main()
