from copy import deepcopy
from decimal import Decimal
import hashlib
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parent))
from n5_identity import reconcile,screening_closure
from cohorts_v2 import Scan,build_components


def digest(value):return hashlib.sha256(value.encode()).hexdigest()


class IdentityReconciliationTests(unittest.TestCase):
    def setUp(self):
        self.ids={name:f'dish_{1000000000+i:010d}' for i,name in enumerate(
                  ('history','core','val','retired','train','a','b','c'))}
        self.scans={dish:Scan(dish,'synthetic_cafe',int(dish[5:]),
                    ((f'ingr_{i:010d}',Decimal(i+1)),),digest('recipe-'+dish))
                    for i,dish in enumerate(self.ids.values())}
        self.old_pixels=[self.pixel(self.ids[name]) for name in ('history','core','val','retired')]
        mapping,quarantine,_,members=build_components(self.scans,self.old_pixels)
        recipes={dish:scan.recipe_hash for dish,scan in self.scans.items()}
        screening=screening_closure(mapping,recipes,self.old_pixels)
        self.index={'original_components':mapping,'recipe_sha256':recipes,
            'screening_components':screening,'known_image_fingerprints':self.old_pixels,
            'blocked_screening_components':[screening[self.ids[name]]
                for name in ('history','core','val','retired')]}
        self.snapshot={'component_members':members,'ambiguous_component_ids':list(quarantine),
            'active_development_ids':[self.ids['core']],
            'historical_exposure_ids':[self.ids['history']]}
        self.proposal={'selected_dish_ids':[self.ids['val']],
            'original_development_exposure_ids':[self.ids['core'],self.ids['retired']],
            'retired_validation_dish_ids':[]}
        self.registry={'exposed_dish_ids':[self.ids['history']],'local_dish_ids':[],
            'exposed_ingredient_group_sha256':[]}
        self.entries=[{'dish_id':self.ids['train']}]
        self.incoming=[self.pixel(self.ids['train'])]
        self.counts={'core':1,'validation':1,'training':1,'original_development':2}

    def pixel(self,dish):return {'dish_id':dish,'bytes_sha256':digest('bytes-'+dish),
                               'rgb_sha256':digest('pixels-'+dish)}

    def run_reconcile(self):
        return reconcile(self.scans,self.index,self.snapshot,self.proposal,self.registry,
                         self.entries,self.incoming,expected_counts=self.counts)

    def test_all_protected_roles_and_retired_original_development_are_preserved(self):
        private,aggregate=self.run_reconcile()
        self.assertEqual(private['allowed_ids'],{self.ids[n] for n in ('a','b','c')})
        self.assertEqual(private['protected']['retired']['dish_ids'],[self.ids['retired']])
        self.assertEqual(aggregate['role_counts']['training'],1)
        self.assertEqual(aggregate['validation_intersections'],0)
        self.assertFalse(any(dish in str(aggregate) for dish in self.ids.values()))

    def test_full_training_pixels_including_quarantined_items_are_required(self):
        self.entries.append({'dish_id':self.ids['a'],'quarantine_reasons':['synthetic']})
        self.counts['training']=2
        with self.assertRaisesRegex(ValueError,'complete_selected_training_pixels'):
            self.run_reconcile()
        self.incoming.append(self.pixel(self.ids['a']))
        private,_=self.run_reconcile()
        self.assertNotIn(self.ids['a'],private['allowed_ids'])

    def test_new_training_byte_or_rgb_bridge_to_validation_refuses(self):
        for field in ('bytes_sha256','rgb_sha256'):
            with self.subTest(field=field):
                incoming=deepcopy(self.incoming)
                self.incoming[0][field]=self.pixel(self.ids['val'])[field]
                try:
                    with self.assertRaisesRegex(ValueError,'validation_linkage_requires_separate_resolution'):
                        self.run_reconcile()
                finally:self.incoming=incoming

    def test_old_snapshot_or_index_or_raw_universe_drift_is_not_silently_repaired(self):
        for case in ('original','recipe','screening','snapshot','count','duplicate_training'):
            with self.subTest(case=case):
                before=deepcopy((self.index,self.snapshot,self.counts,self.entries))
                if case=='original':self.index['original_components'][self.ids['a']]='changed'
                elif case=='recipe':self.index['recipe_sha256'][self.ids['a']]=digest('changed')
                elif case=='screening':self.index['screening_components'][self.ids['a']]='changed'
                elif case=='snapshot':self.snapshot['component_members'].pop(next(iter(self.snapshot['component_members'])))
                elif case=='count':self.counts['core']=2
                else:self.entries.append(deepcopy(self.entries[0]))
                try:
                    with self.assertRaises(ValueError):self.run_reconcile()
                finally:self.index,self.snapshot,self.counts,self.entries=before

    def test_prior_exclusions_without_materialized_role_are_not_lost(self):
        self.index['blocked_screening_components'].append(self.index['screening_components'][self.ids['a']])
        private,_=self.run_reconcile()
        self.assertNotIn(self.ids['a'],private['allowed_ids'])

    def test_stricter_recipe_closure_keeps_unselected_bridges(self):
        mapping={'a':'one','b':'one','c':'two','d':'two','e':'three'}
        recipes={'a':'r1','b':'r2','c':'r2','d':'r3','e':'r3'}
        result=screening_closure(mapping,recipes,[])
        self.assertEqual(len(set(result.values())),1)
        self.assertEqual(mapping['e'],'three')


if __name__=='__main__':unittest.main()
