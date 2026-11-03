from copy import deepcopy
import unittest

import capacity_cohort_v4 as capacity
from source_census import sha


def fixture():
    mapping={};core=[];accepted=[];proposals=[];old=[]
    def identity(i,split):
        dish=f'dish_{i:010d}';mapping[dish]='g'+str(i)
        return dish,{'sample_id':'nutrition5k-'+dish,'dataset':'nutrition5k','split':split,
            'group_id':'old'+str(i),'fold':i%5 if split=='dev' else None,
            'image_path':f'data/nutrition5k/{split}/images/{i}.png','image_sha256':sha(str(i).encode())}
    for i in range(84):core.append(identity(i,'dev')[1])
    for i in range(1000,1230):
        dish,row=identity(i,'train');row.pop('fold');digest=row['image_sha256']
        row.update(original_component_id='o'+str(i),recipe_sha256=digest,rgb_sha256=digest,
                   image_path='round4/data/train/images/'+digest+'.png');accepted.append(row)
        proposals.append({'dish_id':dish,'bytes_sha256':digest,'rgb_sha256':digest,
            'recipe_sha256':digest,'screening_component_id':row['group_id'],
            'original_component_id':row['original_component_id']})
    for i in range(2000,2200):old.append(identity(i,'validation')[1])
    for i in range(2000,2098):mapping[f'dish_{i:010d}']='g0'
    for i in range(2190,2200):mapping[f'dish_{i:010d}']='g'+str(i-10)
    fresh=[]
    for i in range(3000,3137):
        dish=f'dish_{i:010d}';mapping[dish]='new'+str((i-3000)%57);fresh.append(dish)
    state={'mapping':mapping,'core_rows':{r['sample_id'].removeprefix('nutrition5k-'):deepcopy(r) for r in core},
        'quarantine':{'g1','g2'},'allowed_ids':set(fresh),
        'protected':{'history':{'dish_ids':[]},'retired':{'dish_ids':[]},'core':{'dish_ids':[f'dish_{i:010d}' for i in range(84)]},
            'training':{'dish_ids':[p['dish_id'] for p in proposals]},
            'legacy_reserved':{'dish_ids':[r['sample_id'].removeprefix('nutrition5k-') for r in old]},
            'potential_extra':{'dish_ids':[r['sample_id'].removeprefix('nutrition5k-') for r in old]}}}
    return core,{'accepted_manifest_private':accepted,'protected_proposals_private':proposals},state,old,fresh


class CapacityTests(unittest.TestCase):
    def test314_preserves_all_sources_and_uncertainty_unit(self):
        core,train,state,old,fresh=fixture();before=deepcopy((core,train,state))
        result=capacity.developer_identity_bindings(core,train,state)
        self.assertEqual(result['counts']['development_rows'],314)
        bindings=result['development_bindings_private']
        self.assertEqual(bindings['dish_0000000001']['fold_unit'],bindings['dish_0000000002']['fold_unit'])
        self.assertFalse(result['historical_support_is_fresh_or_independent'])
        self.assertEqual(result['original_training_manifest_private'],train['accepted_manifest_private'])
        self.assertEqual((core,train,state),before)

    def test102plus98_group_counts_and_order(self):
        core,train,state,old,fresh=fixture()
        result=capacity.acceptance_identity_proposal(old,state,fresh)
        self.assertEqual(result['counts'],{'retained_old_rows':102,'new_rows':98,'proposed_rows':200,
            'retained_old_components':92,'full_association_groups':149})
        self.assertEqual(result['shortfall_reasons'],[])
        reordered=capacity.acceptance_identity_proposal(list(reversed(old)),state,list(reversed(fresh)))
        self.assertEqual(result['new_acceptance_dish_ids_private'],reordered['new_acceptance_dish_ids_private'])
        self.assertEqual(result['retained_old_rows_private'],reordered['retained_old_rows_private'])
        selected=result['new_acceptance_dish_ids_private']
        self.assertEqual(len({state['mapping'][d] for d in selected[:57]}),57)
        self.assertTrue(result['pending_boundary_confirmation'])
        self.assertFalse(result['new_acceptance_designated'])

    def test_original_validation_list_order_is_preserved(self):
        _,_,state,old,fresh=fixture();result=capacity.acceptance_identity_proposal(old,state,fresh)
        self.assertEqual(result['old_validation_legacy_reserved_private'],old)

    def test_source_missing_duplicate_dataset_fold_and_truth_poison(self):
        for mode in ('missing','duplicate','dataset','fold','truth','sourcehash'):
            core,train,state,_,_=fixture()
            if mode=='missing':train['accepted_manifest_private'].pop()
            elif mode=='duplicate':core[1]=deepcopy(core[0])
            elif mode=='dataset':core[0]['dataset']='asa24'
            elif mode=='fold':core[0]['fold']=True
            elif mode=='truth':train['accepted_manifest_private'][0]['truth']=1
            else:train['accepted_manifest_private'][0]['rgb_sha256']='f'*64
            with self.subTest(mode=mode),self.assertRaises(ValueError):capacity.developer_identity_bindings(core,train,state)

    def test_fewer_than_five_units_stops(self):
        core,train,state,_,_=fixture()
        for dish in state['mapping']:state['mapping'][dish]='one'
        with self.assertRaisesRegex(ValueError,'five_capacity_fold_units_required'):
            capacity.developer_identity_bindings(core,train,state)

    def test_forbidden_candidate_and_oldvalidation_allowed_refused(self):
        for mode in ('candidate','oldallowed','truth'):
            _,_,state,old,fresh=fixture()
            if mode=='candidate':fresh[0]='dish_0000000000'
            elif mode=='oldallowed':state['allowed_ids'].add('dish_0000002000')
            else:old[0]['truth']={'weight':1}
            with self.subTest(mode=mode),self.assertRaises(ValueError):capacity.acceptance_identity_proposal(old,state,fresh)

    def test_shortfall_no_topup(self):
        _,_,state,old,fresh=fixture();result=capacity.acceptance_identity_proposal(old,state,fresh[:10])
        self.assertEqual(result['counts']['new_rows'],10)
        self.assertIn('new_acceptance_fixed_order_shortfall',result['shortfall_reasons'])


if __name__=='__main__':unittest.main()
