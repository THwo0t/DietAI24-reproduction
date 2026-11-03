from copy import deepcopy
from decimal import Decimal
import hashlib
from pathlib import Path
import sys
import unittest
BASE=Path(__file__).resolve().parent.parent
sys.path[:0]=[str(BASE/'src'),str(BASE/'round7/src'),str(BASE/'round11')]
from cohorts_v2 import Scan,build_components
from n5_identity import screening_closure
import lineage_pool_v3 as p
from cohort_lineage_v3 import ordered_proposal_split,SEED


def digest(text):return hashlib.sha256(text.encode()).hexdigest()

class Poison:
    def __iter__(self):raise AssertionError('protected_truth_inspected')
    def __getitem__(self,key):raise AssertionError('protected_truth_inspected')
    def values(self):raise AssertionError('protected_truth_inspected')


class PoolTests(unittest.TestCase):
    def setUp(self):self.fixture(5)
    def fixture(self,n):
        self.names=['core','history','legacy_reserved','training','retired','potential_extra','oldblock']+[f'candidate{i}' for i in range(n)]
        self.ids={name:f'dish_{1000000000+i:010d}' for i,name in enumerate(self.names)}
        self.scans={dish:Scan(dish,'cafe'+str(i),i,((f'ingr_{i:010d}',Decimal(1)),),digest('recipe'+dish))
                    for i,dish in enumerate(self.ids.values())}
        self.roles={role:{'dish_ids':[self.ids[role]],'recipe_hashes':[]} for role in p.REQUIRED_ROLES}
        self.pixels=[dict(dish_id=d,bytes_sha256=digest('b'+d),rgb_sha256=digest('r'+d)) for d in self.scans]
        self.rebuild()
        self.available=[dict(dish_id=d,truth=(Poison() if name in p.REQUIRED_ROLES or name=='oldblock' else
                        dict(weight=100,energy=200,fat=2,carbs=30,protein=5))) for name,d in self.ids.items()]
    def state(self,overlay):
        raw,amb,_,_=build_components(self.scans,self.pixels)
        recipes={d:s.recipe_hash for d,s in self.scans.items()};mapping=screening_closure(raw,recipes,self.pixels)
        protected={k:deepcopy(v) for k,v in self.roles.items() if overlay or k!='potential_extra'}
        quarantine={mapping[d] for d in self.scans if raw[d] in amb}
        blocked=quarantine|{mapping[d] for r in protected.values() for d in r['dish_ids']}|{mapping[self.ids['oldblock']]}
        recipes_blocked={h for r in protected.values() for h in r['recipe_hashes']}|{recipes[d] for r in protected.values() for d in r['dish_ids']}
        core=self.ids['core']
        state=dict(mapping=mapping,raw_mapping=raw,quarantine=quarantine,blocked_screening_components=blocked,
            protected=protected,allowed_ids={d for d in self.scans if mapping[d] not in blocked and recipes[d] not in recipes_blocked},
            core_rows={core:dict(sample_id='nutrition5k-'+core,dataset='nutrition5k',split='dev',group_id=raw[core],fold=0,
                image_path='synthetic.png',image_sha256=digest('image'))},labels_sha256=digest('labels'),fingerprints=deepcopy(self.pixels),
            status='provisional_potential_input_overlay' if overlay else 'provisional',
            **{k:False for k in p.FLAGS})
        if overlay:state.update(potential_local_rows_private=[],potential_path_aliases_private={},
                unassigned_potential_digests_private=[],postdownload_blind_collision_check_required=True,eligibility_established=False)
        return state
    def rebuild(self):self.prior=self.state(False);self.overlay=self.state(True)
    def pool(self):return p.candidate_pool(self.scans,self.available,self.overlay,prior_state=self.prior)

    def test_protected_poison_and_legacy_core_overlap_stay_blocked(self):
        self.roles['legacy_reserved']['dish_ids'].append(self.ids['core']);self.rebuild()
        candidates,summary=self.pool()
        self.assertEqual(set(candidates),{self.ids[f'candidate{i}'] for i in range(5)})
        self.assertFalse(summary['legacy_independent_validation_claimed'])
        self.assertFalse(summary['eligibility_established'])
        self.assertNotIn('truth',str(candidates));self.assertNotIn('dish_',str(summary))

    def test_missing_roles_unknown_mapping_and_fabricated_allowed_rejected(self):
        baseline=deepcopy(self.overlay)
        for mutation in ('missingrole','validation','mapping','allowed','legacyempty'):
            self.overlay=deepcopy(baseline)
            if mutation=='missingrole':self.overlay['protected'].pop('potential_extra')
            elif mutation=='validation':self.overlay['protected']['validation']={'dish_ids':[],'recipe_hashes':[]}
            elif mutation=='mapping':self.overlay['mapping'].pop(self.ids['core'])
            elif mutation=='allowed':self.overlay['allowed_ids'].add(self.ids['legacy_reserved'])
            else:self.overlay['protected']['legacy_reserved']['dish_ids']=[]
            with self.subTest(mutation=mutation),self.assertRaises(ValueError):self.pool()
        self.overlay=baseline

    def test_prior_block_and_old_role_cannot_be_cleared_with_allowed_ids(self):
        for mutation in ('block','role','recipe'):
            self.rebuild()
            if mutation=='block':
                d=self.ids['oldblock'];self.overlay['blocked_screening_components'].remove(self.overlay['mapping'][d]);self.overlay['allowed_ids'].add(d)
            elif mutation=='role':
                d=self.ids['history'];self.overlay['protected']['history']['dish_ids']=[self.ids['core']]
                self.overlay['blocked_screening_components'].remove(self.overlay['mapping'][d]);self.overlay['allowed_ids'].add(d)
            else:
                h=self.scans[self.ids['candidate0']].recipe_hash
                self.prior['protected']['history']['recipe_hashes']=[h];self.prior['allowed_ids'].remove(self.ids['candidate0'])
            with self.subTest(mutation=mutation),self.assertRaises(ValueError):self.pool()

    def test_recipe_bridge_excludes_before_truth_inspection(self):
        d=self.ids['candidate0'];old=self.scans[d]
        self.scans[d]=Scan(d,old.cafe,old.timestamp,old.masses,self.scans[self.ids['legacy_reserved']].recipe_hash)
        self.rebuild();next(row for row in self.available if row['dish_id']==d)['truth']=Poison()
        candidates,_=self.pool();self.assertNotIn(d,candidates)

    def test_candidate_numeric_completeness_and_positive_weight(self):
        row=next(row for row in self.available if row['dish_id']==self.ids['candidate0']);original=deepcopy(row['truth'])
        for truth in ({'weight':100},{**original,'fat':float('nan')},{**original,'weight':0},
                      {**original,'energy':-1},{**original,'weight':True},{**original,'weight':10**1000}):
            row['truth']=truth
            with self.subTest(truth_type=type(truth['weight'])),self.assertRaises(ValueError):self.pool()
        row['truth']={k:(100 if k=='weight' else 0) for k in p.TARGETS}
        candidates,summary=self.pool();self.assertNotIn(row['dish_id'],candidates);self.assertEqual(summary['excluded']['missing_nutrition'],1)

    def test_recipe_dedup_and_available_population_rules(self):
        a,b=(self.ids[f'candidate{i}'] for i in (0,1));s=self.scans[b]
        self.scans[b]=Scan(b,s.cafe,s.timestamp,s.masses,self.scans[a].recipe_hash);self.rebuild()
        with self.assertRaisesRegex(ValueError,'recipe_deduplication'):self.pool()
        self.available.append(self.available[-1])
        with self.assertRaises(ValueError):self.pool()

    def test_fixed_216_200_proposal_order_disjointness_and_shortfall(self):
        self.fixture(430);proposal,summary=p.propose(self.scans,self.available,self.overlay,prior_state=self.prior)
        candidates,_=self.pool();self.assertEqual(proposal,ordered_proposal_split(candidates))
        ordered=sorted(candidates,key=lambda d:(digest(SEED+'|groups|'+candidates[d]['group_id']),candidates[d]['group_id']))
        self.assertEqual(proposal['development_dish_ids'],ordered[:216])
        self.assertEqual(proposal['acceptance_dish_ids'],ordered[216:416])
        self.assertEqual(len(proposal['development_dish_ids']),216);self.assertEqual(len(proposal['acceptance_dish_ids']),200)
        self.assertFalse(set(proposal['development_dish_ids'])&set(proposal['acceptance_dish_ids']))
        self.available.reverse();other,_=p.propose(self.scans,self.available,self.overlay,prior_state=self.prior)
        self.assertEqual(proposal,other);self.assertEqual(proposal['acceptance_status'],'pending_boundary_confirmation')
        self.assertFalse(proposal['freeze_authorized']);self.assertFalse(proposal['frozen'])
        self.fixture(3);short,_=p.propose(self.scans,self.available,self.overlay,prior_state=self.prior)
        self.assertEqual(short['development_shortfall'],213);self.assertEqual(short['acceptance_shortfall'],200)
        self.assertEqual(short['replacement_policy'],'none')

    def test_quarantine_truth_stays_opaque_and_quarantine_cannot_be_removed(self):
        a,b=(self.ids[f'candidate{i}'] for i in (0,1))
        self.scans[a]=Scan(a,'ambiguous',1,(('a',Decimal(1)),('b',Decimal(2)),('c',Decimal(3))),digest('a'))
        self.scans[b]=Scan(b,'ambiguous',2,(('a',Decimal(1)),('b',Decimal(4)),('d',Decimal(5))),digest('b'))
        self.rebuild()
        for row in self.available:
            if row['dish_id'] in (a,b):row['truth']=Poison()
        candidates,_=self.pool();self.assertNotIn(a,candidates);self.assertNotIn(b,candidates)
        self.assertTrue(self.overlay['quarantine']);self.overlay['quarantine']=set()
        with self.assertRaisesRegex(ValueError,'quarantine'):self.pool()

    def test_actual_lineage_and_overlay_producers_interoperate(self):
        from test_cohort_lineage_v3 import LineageTests
        from n5_potential_identity import overlay_potential_identity
        fixture=LineageTests();fixture.setUp();prior,_=fixture.new_run()
        state,_=overlay_potential_identity(fixture.scans,prior,fixture.old_pixels,fixture.incoming,[])
        protected=set().union(*(set(r['dish_ids']) for r in state['protected'].values()))
        available=[dict(dish_id=d,truth=Poison() if d in protected else
                       dict(weight=100,energy=100,fat=1,carbs=10,protein=2)) for d in fixture.scans]
        candidates,summary=p.candidate_pool(fixture.scans,available,state,prior_state=prior)
        self.assertEqual(set(candidates),{fixture.ids[k] for k in ('a','b','c')})
        self.assertFalse(summary['freeze_authorized'])

    def test_required_prior_state_and_no_authorization_grant(self):
        with self.assertRaises(TypeError):p.candidate_pool(self.scans,self.available,self.overlay)
        self.overlay['source_completeness_proven']=True
        with self.assertRaises(ValueError):self.pool()

if __name__=='__main__':unittest.main()
