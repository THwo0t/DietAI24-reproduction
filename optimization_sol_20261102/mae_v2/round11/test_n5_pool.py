from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parent))
from n5_pool import candidate_pool,choose_new_dishes,REQUIRED_ROLES


class N5ExpansionPoolTests(unittest.TestCase):
    def setUp(self):
        self.scans={name:SimpleNamespace(recipe_hash='recipe-'+name,masses=(('ingredient',1),))
                    for name in ('old','core','val','train','retired','a','b','c')}
        self.mapping={name:'group-'+name for name in self.scans}
        self.protected={role:{'dish_ids':[{'history':'old','validation':'val','training':'train'}.get(role,role)],
                             'recipe_hashes':[]} for role in REQUIRED_ROLES}
        self.available=[{'dish_id':name,'truth':dict(weight=100,energy=100,fat=2,carbs=10,protein=5)}
                        for name in self.scans]

    def test_all_exposure_roles_and_associations_are_excluded_before_selection(self):
        self.mapping['b']=self.mapping['old']
        self.scans['c'].recipe_hash=self.scans['val'].recipe_hash
        candidates,summary=candidate_pool(self.scans,self.available,self.mapping,set(),self.protected)
        self.assertEqual(set(candidates),{'a'})
        self.assertEqual(summary['eligible_groups'],1)
        self.assertEqual(summary['excluded']['protected_recipe'],1)
        self.assertNotIn('truth',str(candidates));self.assertNotIn('recipe-val',str(summary))

    def test_a_new_bridge_between_current_core_and_validation_stops_instead_of_silently_dropping_it(self):
        self.mapping['val']=self.mapping['core']
        with self.assertRaisesRegex(ValueError,'separate_resolution'):
            candidate_pool(self.scans,self.available,self.mapping,set(),self.protected)

    def test_exclusion_never_interprets_protected_or_related_target_values(self):
        self.mapping['b']=self.mapping['old']
        self.scans['c'].recipe_hash=self.scans['val'].recipe_hash
        class ForbiddenTruth:
            def __iter__(self):raise AssertionError('protected_target_iteration')
            def values(self):raise AssertionError('protected_target_values')
            def __getitem__(self,key):raise AssertionError('protected_target_index')
        for row in self.available:
            if row['dish_id']!='a':row['truth']=ForbiddenTruth()
        candidates,summary=candidate_pool(self.scans,self.available,self.mapping,set(),self.protected)
        self.assertEqual(set(candidates),{'a'})
        self.assertEqual(summary['excluded']['protected_recipe'],1)

    def test_new_ambiguity_touching_validation_is_a_hard_stop(self):
        with self.assertRaisesRegex(ValueError,'separate_resolution'):
            candidate_pool(self.scans,self.available,self.mapping,{self.mapping['val']},self.protected)

    def test_original_recipe_deduplication_and_missing_label_rules_are_preserved(self):
        self.scans['b'].recipe_hash=self.scans['a'].recipe_hash
        with self.assertRaisesRegex(ValueError,'recipe_deduplication'):
            candidate_pool(self.scans,self.available,self.mapping,set(),self.protected)
        self.available[-2]['truth'].update(energy=0,fat=0,carbs=0,protein=0)
        candidates,summary=candidate_pool(self.scans,self.available,self.mapping,set(),self.protected)
        self.assertEqual(set(candidates),{'a','c'})
        self.assertEqual(summary['excluded']['missing_nutrition'],1)

    def test_incomplete_raw_graph_or_exposure_registry_or_nonfinite_label_refuses(self):
        for case in ('mapping','role','nan'):
            with self.subTest(case=case):
                mapping=deepcopy(self.mapping);roles=deepcopy(self.protected);rows=deepcopy(self.available)
                if case=='mapping':mapping.pop('old')
                elif case=='role':roles.pop('training')
                else:rows[-1]['truth']['fat']=float('nan')
                with self.assertRaises(ValueError):candidate_pool(self.scans,rows,mapping,set(),roles)

    def test_fixed_component_sampling_has_no_same_group_fill_or_target_ranking(self):
        candidates={'a':{'group_id':'g1','recipe_hash':'r1'},'b':{'group_id':'g1','recipe_hash':'r2'},
                    'c':{'group_id':'g2','recipe_hash':'r3'}}
        selected,counts=choose_new_dishes(candidates,seed='fixed',count=216)
        other,_=choose_new_dishes(dict(reversed(list(candidates.items()))),seed='fixed',count=216)
        self.assertEqual(selected,other);self.assertEqual(len(selected),2)
        self.assertEqual(counts['shortfall'],214)
        bad=deepcopy(candidates);bad['a']['truth']={'weight':9999}
        with self.assertRaisesRegex(ValueError,'label_free'):choose_new_dishes(bad,seed='fixed',count=2)


if __name__=='__main__':unittest.main()
