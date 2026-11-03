from copy import deepcopy
import unittest
from test_n5_identity import IdentityReconciliationTests,digest
from cohort_lineage_v3 import reconcile_lineage,rebuild_core_folds,ordered_proposal_split,FOLD_SEED
from n5_identity import screening_closure


class LineageTests(IdentityReconciliationTests):
    # Inherit historical guard regression tests as well as the new adapter tests.
    def new_inputs(self):
        counts={('legacy_reserved' if k=='validation' else k):v for k,v in self.counts.items()}
        d=self.ids['core']
        manifest={'rows':[{'sample_id':'nutrition5k-'+d,'dataset':'nutrition5k','split':'dev',
            'group_id':self.index['original_components'][d],'fold':0,'image_path':'identity-only.png',
            'image_sha256':self.pixel(d)['bytes_sha256']}], 'labels_sha256':digest('sealed-labels')}
        return counts,manifest

    def new_run(self):
        counts,manifest=self.new_inputs()
        return reconcile_lineage(self.scans,self.index,self.snapshot,self.proposal,self.registry,
                                 self.entries,self.incoming,manifest,expected_counts=counts)

    def test_legacy_bridge_is_reserved_without_reclassifying_exposure(self):
        self.incoming[0]['rgb_sha256']=self.pixel(self.ids['val'])['rgb_sha256']
        state,summary=self.new_run()
        self.assertEqual(state['protected']['legacy_reserved']['dish_ids'],[self.ids['val']])
        self.assertNotIn(self.ids['val'],state['allowed_ids'])
        self.assertNotIn(self.ids['train'],state['allowed_ids'])
        self.assertEqual(summary['legacy_reserved_intersections']['training'],1)
        self.assertNotIn(self.ids['val'],state['protected']['history']['dish_ids'])
        for key in ('download_authorized','inference_authorized','frozen','source_completeness_proven'):
            self.assertIs(state[key],False)

    def test_complete_core_binding_no_targets_and_immutable_inputs(self):
        counts,manifest=self.new_inputs()
        args=(self.scans,self.index,self.snapshot,self.proposal,self.registry,self.entries,self.incoming,manifest)
        before=deepcopy(args)
        state,_=reconcile_lineage(*args,expected_counts=counts)
        self.assertEqual(args,before)
        self.assertEqual(state['core_rows'][self.ids['core']],manifest['rows'][0])
        manifest['rows'][0]['image_sha256']=digest('wrong')
        with self.assertRaisesRegex(ValueError,'core_image_binding_changed'):
            reconcile_lineage(*args,expected_counts=counts)
        manifest['rows']=[]
        with self.assertRaisesRegex(ValueError,'complete_core_manifest'):
            reconcile_lineage(*args,expected_counts=counts)

    def test_all_prior_exclusions_and_recipe_bridge_remain_blocked(self):
        self.index['blocked_screening_components'].append(self.index['screening_components'][self.ids['a']])
        state,_=self.new_run()
        self.assertEqual(state['allowed_ids'],{self.ids['b'],self.ids['c']})
        # Protected targets are never an input; opaque poison extra values remain untouched.
        class Poison:
            def __float__(self):raise AssertionError('target touched')
        self.entries[0]['truth']=Poison()
        self.new_run()

    def test_core_projection_rejects_label_payload(self):
        counts,manifest=self.new_inputs();manifest['labels']={'protected':object()}
        with self.assertRaisesRegex(ValueError,'identity_only_core_projection'):
            reconcile_lineage(self.scans,self.index,self.snapshot,self.proposal,self.registry,
                              self.entries,self.incoming,manifest,expected_counts=counts)


class FoldProposalTests(unittest.TestCase):
    def state(self):
        # Two ambiguous components and one deterministic old-fold bridge.
        rows={f'dish_{1000000000+i}':{'fold':i%5,'image_sha256':digest(str(i)),
               'image_path':str(i),'sample_id':str(i)} for i in range(10)}
        mapping={d:'group-'+str(i) for i,d in enumerate(rows)}
        ds=list(rows);mapping[ds[1]]=mapping[ds[0]]
        return {'core_rows':rows,'mapping':mapping,'quarantine':{'group-2','group-3'},
                'labels_sha256':digest('labels')}

    def test_full_groups_ambiguity_containment_old_bridges_and_immutability(self):
        state=self.state();before=deepcopy(state)
        result=rebuild_core_folds(state);self.assertEqual(state,before)
        bindings=result['bindings'];ds=list(state['core_rows'])
        self.assertEqual(bindings[ds[0]]['fold'],bindings[ds[1]]['fold'])
        self.assertEqual(bindings[ds[2]]['fold_unit_id'],bindings[ds[3]]['fold_unit_id'])
        self.assertEqual(result['old_fold_bridge_components'],['group-0'])
        self.assertEqual(result['fold_unit_count'],8)
        self.assertEqual(result['original_core_rows'],state['core_rows'])
        self.assertEqual(result['seed'],FOLD_SEED)
        self.assertEqual(rebuild_core_folds(state),result)
        state['quarantine']=set(state['mapping'].values())
        with self.assertRaisesRegex(ValueError,'at_least_five'):
            rebuild_core_folds(state)

    def test_recipe_byte_rgb_bridges_are_transitive_before_folds(self):
        state=self.state();ds=list(state['core_rows'])
        raw={d:'r'+str(i) for i,d in enumerate(ds)}
        recipes={d:digest('recipe'+str(i)) for i,d in enumerate(ds)}
        recipes[ds[1]]=recipes[ds[0]]
        pixels=[{'dish_id':d,'bytes_sha256':digest('byte'+str(i)),
                 'rgb_sha256':digest('rgb'+str(i))} for i,d in enumerate(ds)]
        pixels[2]['bytes_sha256']=pixels[1]['bytes_sha256']
        pixels[3]['rgb_sha256']=pixels[2]['rgb_sha256']
        state['mapping']=screening_closure(raw,recipes,pixels);state['quarantine']=set()
        result=rebuild_core_folds(state)
        self.assertEqual(len({result['bindings'][d]['fold_unit_id'] for d in ds[:4]}),1)
        self.assertEqual(result['screening_component_count'],7)
        self.assertEqual(len(result['old_fold_bridge_components']),1)

    def test_fixed_disjoint_representatives_shortfalls_and_pending_permission(self):
        candidates={f'dish_{1000000000+i}':{'group_id':'g'+str(i//2),'recipe_hash':digest(str(i))}
                    for i in range(16)}
        before=deepcopy(candidates)
        result=ordered_proposal_split(candidates,development_count=5,acceptance_count=5)
        self.assertEqual(candidates,before)
        self.assertEqual(result,ordered_proposal_split(dict(reversed(list(candidates.items()))),
                         development_count=5,acceptance_count=5))
        dev=result['development_dish_ids'];accept=result['acceptance_dish_ids']
        self.assertEqual((len(dev),len(accept)),(5,3));self.assertFalse(set(dev)&set(accept))
        self.assertEqual(len({candidates[d]['group_id'] for d in dev+accept}),8)
        self.assertEqual(result['acceptance_shortfall'],2)
        self.assertEqual(result['acceptance_status'],'pending_boundary_confirmation')
        self.assertIs(result['download_authorized'],False);self.assertIs(result['frozen'],False)
        candidates[next(iter(candidates))]['truth']=object()
        with self.assertRaisesRegex(ValueError,'label_free_safe_candidate'):
            ordered_proposal_split(candidates)


if __name__=='__main__':unittest.main()
