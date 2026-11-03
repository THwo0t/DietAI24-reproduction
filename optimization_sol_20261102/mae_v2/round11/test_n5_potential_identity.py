from copy import deepcopy
import unittest
from test_cohort_lineage_v3 import LineageTests
from n5_potential_identity import overlay_potential_identity, RGB_ALGORITHM
from test_n5_identity import digest


class PotentialOverlayTests(LineageTests):
    def row(self,path='charts/example.png',**overrides):
        value={'path':path,'classification':'chart','bytes_sha256':digest('new-byte'),
            'rgb_sha256':digest('new-rgb'),'rgb_algorithm':RGB_ALGORITHM,'width':2,'height':3,
            'mode':'RGB','format':'PNG','nontrivial_render_semantics':False,
            'asa_compatible':False,'asa_rgb_sha256':None,'asa_algorithm':None}
        value.update(overrides);return value

    def overlay(self,rows,state=None):
        state=self.new_run()[0] if state is None else state
        return overlay_potential_identity(self.scans,state,self.old_pixels,self.incoming,rows)

    def test_hash_only_alias_reaches_known_identity_and_preserves_all_bindings(self):
        state=self.new_run()[0];row=self.row(bytes_sha256=self.pixel(self.ids['core'])['bytes_sha256'])
        args=(self.scans,state,self.old_pixels,self.incoming,[row]);before=deepcopy(args)
        out,summary=overlay_potential_identity(*args)
        self.assertEqual(args,before)
        self.assertEqual(out['protected']['potential_extra']['dish_ids'],[self.ids['core']])
        self.assertEqual(out['potential_path_aliases_private'][self.ids['core']],[row['path']])
        self.assertEqual(out['core_rows'],state['core_rows']);self.assertEqual(out['labels_sha256'],state['labels_sha256'])
        self.assertNotIn(self.ids['core'],str(summary))
        for k in ('download_authorized','inference_authorized','freeze_authorized','frozen',
                  'eligibility_established','source_completeness_proven','latest_exposure_completeness_proven'):
            self.assertIs(out[k],False)

    def test_path_hash_bridge_combines_identities_and_all_aliases_transitively(self):
        a,b=self.ids['a'],self.ids['b']
        rows=[self.row('arbitrary/alias.png'),self.row('local/'+a+'/photo.png',
            bytes_sha256=self.pixel(self.ids['core'])['bytes_sha256']),
            self.row('local/'+b+'/photo.png',rgb_sha256=digest('new-rgb'))]
        out,_=self.overlay(rows)
        self.assertEqual(len({out['mapping'][d] for d in (a,b,self.ids['core'])}),1)
        self.assertFalse({a,b}&out['allowed_ids'])
        self.assertEqual(out['potential_path_aliases_private'][a],sorted(r['path'] for r in rows))
        self.assertEqual(self.overlay(list(reversed(rows)))[0]['mapping'],out['mapping'])

    def test_full_recipe_closure_and_prior_unnamed_block_survive(self):
        self.index['blocked_screening_components'].append(self.index['screening_components'][self.ids['b']])
        state=self.new_run()[0]
        out,_=self.overlay([self.row('local/'+self.ids['a']+'/x.png',
            rgb_sha256=self.pixel(self.ids['train'])['rgb_sha256'])],state)
        self.assertFalse({self.ids['a'],self.ids['b'],self.ids['train']}&out['allowed_ids'])
        self.assertTrue(set(state['allowed_ids'])>=out['allowed_ids'])

    def test_raw_ambiguity_recipe_and_pixel_bridges_remain_excluded(self):
        from cohorts_v2 import Scan, build_components
        from n5_identity import screening_closure
        from decimal import Decimal
        a,b,c=(self.ids[k] for k in ('a','b','c'))
        # Two incompatible adjacent scans create raw ambiguity; a recipe link
        # reaches c before a potential image bridges the whole association.
        self.scans[a]=Scan(a,'ambiguity',1,(('x',Decimal(1)),('y',Decimal(2))),digest('same-recipe'))
        self.scans[b]=Scan(b,'ambiguity',2,(('x',Decimal(1)),('y',Decimal(1))),digest('recipe-b'))
        old=self.scans[c]
        self.scans[c]=Scan(c,old.cafe,old.timestamp,old.masses,digest('same-recipe'))
        raw,quarantine,_,members=build_components(self.scans,self.old_pixels)
        recipes={d:r.recipe_hash for d,r in self.scans.items()}
        self.index['original_components']=raw;self.index['recipe_sha256']=recipes
        self.index['screening_components']=screening_closure(raw,recipes,self.old_pixels)
        self.index['blocked_screening_components']=[]
        self.snapshot['component_members']=members
        self.snapshot['ambiguous_component_ids']=list(quarantine)
        state=self.new_run()[0]
        out,_=self.overlay([self.row('local/'+a+'/x.png',
            bytes_sha256=self.pixel(self.ids['train'])['bytes_sha256'])],state)
        self.assertEqual(out['mapping'][a],out['mapping'][c])
        self.assertIn(out['mapping'][a],out['quarantine'])
        self.assertFalse({a,b,c,self.ids['train']}&out['allowed_ids'])
        self.assertEqual(out['core_rows'],state['core_rows'])

    def test_unassigned_charts_and_dependencies_are_retained(self):
        rows=[self.row(),self.row('dependency/picture.png',classification='dependency')]
        out,summary=self.overlay(rows)
        self.assertEqual(out['unassigned_potential_digests_private'],rows)
        self.assertEqual(out['potential_local_rows_private'],rows)
        self.assertEqual(summary['local_image_rows'],2);self.assertEqual(summary['unassigned_local_rows'],2)
        self.assertTrue(out['postdownload_blind_collision_check_required'])

    def test_dependency_gif_preserves_paths_hashes_and_aliases(self):
        from local_input_inventory import DEPENDENCY_GIF_LIB_ROOTS
        rows = [self.row(root + 'tk8.6/images/asset.gif', classification='dependency',
                         format='GIF', mode='P',
                         rgb_sha256=self.pixel(self.ids['core'])['rgb_sha256'])
                for root in DEPENDENCY_GIF_LIB_ROOTS]
        out, summary = self.overlay(rows)
        self.assertEqual(out['potential_local_rows_private'], rows)
        self.assertEqual(out['potential_path_aliases_private'][self.ids['core']],
                         sorted(r['path'] for r in rows))
        self.assertEqual(summary['local_image_rows'], 5)
        for row in (self.row('research/x.gif', format='GIF'),
                    self.row('.tools/other/x.gif', format='GIF', classification='dependency'),
                    dict(rows[0], classification='research_potential'),
                    dict(rows[0], asa_compatible=True), dict(rows[0], rgb_sha256='bad')):
            with self.assertRaises(ValueError):
                self.overlay([row])
        poison = dict(rows[0], target=object())
        with self.assertRaisesRegex(ValueError, 'identity_only_local_row'):
            self.overlay([poison])

    def test_unknown_path_dish_and_target_fields_refused_without_touching(self):
        with self.assertRaisesRegex(ValueError,'path_dish_outside'):
            self.overlay([self.row('dish_9999999999/x.png')])
        class Poison:
            def __deepcopy__(self,memo):raise AssertionError('target touched')
        row=self.row();row['target']=Poison()
        with self.assertRaisesRegex(ValueError,'identity_only_local_row'):
            self.overlay([row])
        with self.assertRaises(TypeError):
            overlay_potential_identity(self.scans,self.new_run()[0],self.old_pixels,self.incoming,[],targets=Poison())

    def test_wrong_rgb_algorithm_and_missing_full_fingerprints_refused(self):
        with self.assertRaisesRegex(ValueError,'registered_local_rgb'):
            self.overlay([self.row(rgb_algorithm='asa-only')])
        with self.assertRaisesRegex(ValueError,'complete_old_training'):
            overlay_potential_identity(self.scans,self.new_run()[0],[],self.incoming,[])


if __name__=='__main__':unittest.main()
