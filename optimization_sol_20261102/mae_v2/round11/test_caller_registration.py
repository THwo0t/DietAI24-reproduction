"""Finite source registration on synthetic identities only."""
from contextlib import ExitStack
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import caller_registration as callers
from source_census import sha


def fixture():
    def rows(dataset,n,groups):
        result=[]
        for i in range(n):
            sample=(f'asa24-{10000000+i:08d}-photo' if dataset=='asa24'
                    else f'nutrition5k-dish_{1000+i:010d}')
            name=sha(('dietai24-mae-v2-20261102|sample|'+sample).encode())+'.png'
            result.append({'sample_id':sample,'dataset':dataset,'split':'dev',
                'fold':(i%groups)%5,'group_id':dataset+'-'+str(i%groups),
                'image_path':f'data/{dataset}/dev/images/{name}',
                'image_sha256':sha(sample.encode())})
        return result
    dev={'asa_rows':rows('asa24',99,23),
         'n5_core':{'rows':rows('nutrition5k',84,78),'labels_sha256':'0'*64},
         'source_hashes':{'dev':'a'*64}}
    proposals=[]
    for i in range(230):
        dish=f'dish_{i:010d}'; digest=sha(dish.encode())
        proposals.append({'dish_id':dish,'sample_id':'nutrition5k-'+dish,
            'screening_component_id':'s'+str(i),'original_component_id':'o'+str(i),
            'recipe_sha256':digest,'bytes_sha256':digest,'rgb_sha256':digest,
            'quarantine_reasons':['protected_bytes_sha256'] if i==229 else [],
            'protected_training_proposal':True})
    train={'protected_proposals_private':proposals,
        'counts':{'protected_training_proposals':230},'source_hashes':{'train':'b'*64},
        'actual_api_exposure_complete':False,'candidate_eligibility_evaluated':False,
        'grants_sampling_download_or_inference':False}
    return dev,train


class CallerTests(unittest.TestCase):
    def setup_fixture(self,stack):
        root=Path(stack.enter_context(tempfile.TemporaryDirectory())).resolve()
        for name in callers.SOURCE_FILES:
            p=root/callers.PREFIX/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text('# synthetic source\n')
        dev,train=fixture();dr,tr=Mock(),Mock()
        stack.enter_context(patch.object(callers.development_identity,'_load_development_identity',return_value=(dev,dr)))
        stack.enter_context(patch.object(callers.training_identity,'_load_at',return_value=(train,tr)))
        return root,dev,train,dr,tr

    def test_complete_table_preserves_rejected230_capability_not_execution(self):
        with ExitStack() as stack:
            root,dev,train,dr,tr=self.setup_fixture(stack)
            value,bound=callers._load_at(root);bound.revalidate()
            entries={e['caller']:e for e in value['entries_private']}
            self.assertEqual(set(entries),callers.CALLERS)
            rejected=train['protected_proposals_private'][-1]['sample_id']
            self.assertIn(rejected,entries['J_capability']['potential_query_ids_private'])
            self.assertIn(rejected,entries['L_shelved_callable']['potential_support_or_supervision_ids_private'])
            self.assertEqual(value['counts']['ASA_core_supervision'],99)
            self.assertEqual(value['external_ASA_gallery_in_registered_CLI'],[])
            self.assertFalse(value['actual_api_exposure_complete'])
            self.assertFalse(value['programmatic_override_boundary_resolved'])
            self.assertTrue(all(not e['actual_execution_proven'] for e in entries.values()))
            self.assertGreaterEqual(tr.revalidate.call_count,3)

    def test_identity_poison_and_altered_populations(self):
        for mode in ('dev_target','train_target','dev_missing','train_missing','false_grant'):
            with self.subTest(mode=mode),ExitStack() as stack:
                root,dev,train,_,_=self.setup_fixture(stack)
                if mode=='dev_target':dev['asa_rows'][0]['truth']={'energy':1}
                elif mode=='train_target':train['protected_proposals_private'][0]['truth']=1
                elif mode=='dev_missing':dev['asa_rows'].pop()
                elif mode=='train_missing':train['protected_proposals_private'].pop()
                else:train['grants_sampling_download_or_inference']=True
                with self.assertRaises(ValueError):callers._load_at(root)

    def test_missing_caller_is_refused(self):
        with ExitStack() as stack:
            root,*_=self.setup_fixture(stack)
            stack.enter_context(patch.object(callers,'SPECS',callers.SPECS[:-1]))
            with self.assertRaisesRegex(ValueError,'complete_finite_caller_table_required'):
                callers._load_at(root)

    def test_source_hash_drift_and_missing_source(self):
        with ExitStack() as stack:
            root,*_=self.setup_fixture(stack);_,bound=callers._load_at(root)
            (root/callers.PREFIX/callers.SOURCE_FILES[0]).write_text('# changed\n')
            with self.assertRaisesRegex(ValueError,'caller_held_source_binding_changed'):bound.revalidate()
        with ExitStack() as stack:
            root,*_=self.setup_fixture(stack)
            (root/callers.PREFIX/callers.SOURCE_FILES[0]).unlink()
            with self.assertRaises(FileNotFoundError):callers._load_at(root)

    def test_held_identity_drift_and_fixed_reader_drift(self):
        with ExitStack() as stack:
            root,dev,train,dr,tr=self.setup_fixture(stack)
            _,bound=callers._load_at(root);dev['asa_rows'][0]['group_id']='changed'
            with self.assertRaisesRegex(ValueError,'caller_held_source_binding_changed'):bound.revalidate()
        with ExitStack() as stack:
            root,_,_,dr,tr=self.setup_fixture(stack)
            _,bound=callers._load_at(root);tr.revalidate.side_effect=ValueError('training_manifest_changed')
            with self.assertRaisesRegex(ValueError,'training_manifest_changed'):bound.revalidate()

    def test_only_explicit_python_sources_opened(self):
        with ExitStack() as stack:
            root,*_=self.setup_fixture(stack)
            original=callers.bounded_read;opened=[]
            def read(base,path):
                self.assertEqual(base,root)
                self.assertIn(path,tuple(callers.PREFIX+p for p in callers.SOURCE_FILES))
                self.assertTrue(path.endswith('.py'));opened.append(path)
                return original(base,path)
            stack.enter_context(patch.object(callers,'bounded_read',side_effect=read))
            callers._load_at(root)
            self.assertEqual(set(opened),{callers.PREFIX+p for p in callers.SOURCE_FILES})

    def test_public_entry_no_overrides(self):
        with patch.object(callers,'_load_at',return_value=('value','reader')) as load:
            self.assertEqual(callers.load_caller_registration(),('value','reader'))
            load.assert_called_once_with(callers.REPO)
        with self.assertRaises(TypeError):callers.load_caller_registration('/tmp')


if __name__=='__main__':unittest.main()
