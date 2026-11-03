from copy import deepcopy
from pathlib import Path
import sys
import unittest
BASE=Path(__file__).resolve().parent.parent
sys.path[:0]=[str(BASE/'src'),str(BASE/'round7/src'),str(BASE/'round11')]
import source_scope_v3 as s
from test_asa_phase_graph import fixture,digest
import test_lineage_pool_v3 as lineage_fixture
from asa_phase_graph import _build_phase_graph
from source_capture import plain
from opt_provider import fingerprint


class ScopeTests(unittest.TestCase):
    def setUp(self):
        cap,roles,_=fixture();fps=cap['asa_archive_identity']['image_fingerprints']
        fps[2]['rgb_sha256']=fps[0]['rgb_sha256']
        for code,name in [('44444444','d.png'),('55555555','e.png'),('77777777','bridge.png')]:
            cap['asa_workbook_identity']['pairs'].append((code,name));cap['asa_workbook_identity']['metadata_images'].add(name)
            fps.append(dict(image=name,bytes_sha256=digest(name),rgb_sha256=digest('rgb'+name),width=1,height=1,algorithm=s.ALGORITHM))
        cap['asa_workbook_identity']['pairs'] += [('66666666','missing.png'),('66666666','bridge.png')]
        cap['asa_workbook_identity']['metadata_images'].add('missing.png')
        roles['roleanchors']['history']['codes'].add('11111111')
        def local(path,classification,byte,rgb):
            return dict(path=path,classification=classification,bytes_sha256=byte,rgb_sha256=digest('N5'+rgb),
                asa_compatible=True,asa_rgb_sha256=rgb,asa_algorithm=s.ALGORITHM,width=1,height=1,
                mode='RGB',format='PNG',nontrivial_render_semantics=False)
        rows=[local('neutral/alias.png','research_potential',digest('a.png'),digest('rgba.png')),
              local('neutral/n5.png','research_potential',digest('n5'),digest('n5rgb')),
              local('unknown/dependency.png','dependency',digest('dependency'),digest('dependencyrgb')),
              local('unknown/evidence.png','rendered_evidence',digest('evidence'),digest('evidencergb')),
              local('unknown/recompressed.png','research_potential',digest('newencoding'),digest('rgbd.png'))]
        localcontent={'rows_private':rows}
        graph,summary=_build_phase_graph(cap,roles,localcontent,expected_counts={'core':(2,2),'validation':(1,1)})
        n5fixture=lineage_fixture.PoolTests();n5fixture.setUp();n5=plain(n5fixture.overlay)
        n5['potential_path_aliases_private']={n5fixture.ids['potential_extra']:['neutral/n5.png']}
        core=n5fixture.ids['core'];train=n5fixture.ids['training']
        n5row=dict(sample_id='nutrition5k-'+core,dataset='nutrition5k',split='dev',group_id='n5old',fold=0,
            image_path='',image_sha256=digest('N5core'))
        def path(row):row['image_path']='data/'+row['dataset']+'/dev/images/'+digest('dietai24-mae-v2-20261102|sample|'+row['sample_id'])+'.png';return row
        development=dict(n5_core={'rows':[path(n5row)]},asa_rows=[path(deepcopy(r)) for r in roles['currentmanifestbinding']['core']],source_hashes={'dev.json':digest('dev')})
        proposal=dict(dish_id=train,sample_id='nutrition5k-'+train,screening_component_id=n5['mapping'][train],
            original_component_id=n5['raw_mapping'][train],recipe_sha256=digest('recipe'),bytes_sha256=digest('trainbytes'),
            rgb_sha256=digest('trainrgb'),quarantine_reasons=[],protected_training_proposal=True)
        self.flags={k:False for k in s.NO_GRANTS}
        self.training=dict(protected_proposals_private=[proposal],counts={'protected_training_proposals':1},
            source_hashes={s.PATHS['training_freeze']:digest('trainfreeze')},**self.flags)
        self.mechanical=dict(development_identity=development,n5_source_sha256={'training_freeze':digest('trainfreeze')},
            n5_identity_state_private=n5,asa_mechanical_sources=cap,local_content_private=localcontent,
            original_linkage_guard_remains_stopped=True,**self.flags)
        self.audit=dict(inventory_sha256=s.PINS['inventory'],asa_role_sources_private=roles,
            asa_phase_graph_private=plain(graph),asa_summary_private=plain(summary),**self.flags)
        env=s._identities(development,self.training,populations=(2,1,2,1,1));entries=[];pins={}
        for caller,query,support,source,lines,capability in s.SPECS:
            pins[s.PREFIX+source]=digest(source)
            entries.append(dict(caller=caller,potential_query_ids_private=sorted(env[query]),
                potential_support_or_supervision_ids_private=sorted(env[support]),potential_envelope_is_conservative_superset=True,
                source_proves_historical_invocation=False,actual_execution_proven=False,
                programmatic_injection_disposition='unresolved_capability_not_execution',
                registered_CLI_external_ASA_gallery='none_in_this_finite_call_graph',source_path=s.PREFIX+source,source_sha256=digest(source)))
        self.callers=dict(fixed_CLI_identity_union_registered=True,programmatic_override_boundary_resolved=False,
            external_ASA_gallery_in_registered_CLI=[],identity_source_sha256={'development':development['source_hashes'],'training':self.training['source_hashes']},
            entries_private=entries,source_sha256=pins,counts={'registered_callers':16,'potential_development_queries':3,
                'protected_training_proposals':1,'ASA_core_supervision':2},ASA_core_supervision_ids_private=sorted(env['asa_core']),**self.flags)
        self.local=dict(counts={'unassigned_local_images':3,'dependency':1,'rendered_evidence':1,
            'research_potential':1,'research_unknown':1,'research_source_writer_proven':0},input_sha256={s.INVENTORY:s.PINS['inventory'],s.AUDIT:s.PINS['audit']},
            all_unassigned_byte_and_rgb_digests_retained=True,research_dispositions_private=[dict(identity_metadata=deepcopy(rows[4]),
                disposition='unknown',source_writer_proven=False,actual_api_exposure_proven=False,excluded_from_potential_inputs=False,
                retained_for_collision_checks=True,candidate_source_proofs=[])],other_unassigned_identity_metadata_private=deepcopy(rows[2:4]),
            unresolved_link_metadata_private=[dict(path='link',status='unresolved',suffix='',suffix_in_image_allowlist=False,followed=False,body_opened=False)],**self.flags)
        self.repair=dict(source_disposition_design_sha256=digest('prospective_design'),original_linkage_guard_remains_stopped=True,
            ASA_bridge_pending_replacement={'affected_validation_records':1,'old_validation_records':1,'status':'proposal_only_pending_boundary_confirmation'})
        self.counts={**s.COUNTS,'asa_core':2,'n5_core':1,'asa_core_groups':2,'n5_core_groups':1,'training':1,
            'asa_validation':1,'asa_validation_groups':1,'legacy_reserved':1,'local':5,'n5_local':1,'asa_local':1,
            'unassigned':3,'dependency':1,'rendered_evidence':1,'research_potential':1,'unresolved_links':1,
            'missing_names':1,'missing_components':1,'core_validation_components':1,'affected_validation':1}
    def run_scope(self):return s._disposition(self.mechanical,self.audit,self.callers,self.training,self.local,self.repair,
        counts=self.counts,pins=s.PINS)

    def test_missing_unselected_bridge_and_RGB_recompressed_local_blocked(self):
        out=self.run_scope();self.assertIn('55555555',out['asa_permitted_codes_private'])
        self.assertNotIn('44444444',out['asa_permitted_codes_private'])
        self.assertNotIn('77777777',out['asa_permitted_codes_private'])
        self.assertEqual(out['missing_source_names_private'],['missing.png'])
        self.assertEqual(out['original_role_anchors_private'],plain(self.audit['asa_role_sources_private']['roleanchors']))
        self.assertEqual(len(out['all_unassigned_identity_metadata_private']),3)
        self.assertFalse(out['global_supplied_byte_closure_complete']);self.assertFalse(out['actual_api_exposure_complete'])
        self.assertTrue(out['known_scope']['source_corpus_is_not_prior_API_exposure'])

    def test_legacy_validation_and_N5_proposal_roles_unchanged(self):
        before=deepcopy(self.mechanical['n5_identity_state_private']);out=self.run_scope()
        self.assertEqual(out['n5_identity_state_private'],before)
        self.assertEqual(out['original_ASA_validation_bindings_private'],self.audit['asa_phase_graph_private']['manifest_bindings']['validation'])
        self.assertFalse(out['ASA_pending_repair_private']['new_acceptance_designated'])
        self.assertEqual(out['ASA_pending_repair_private']['affected_old_validation_sample_ids'],['asa24-33333333-one'])
        self.assertTrue(out['potential_training_upper_bound_anchors_private']['codes'])
        self.assertFalse(out['role_upper_bounds_are_actual_training_or_retirement_claims'])

    def test_fake_closure_flags_unregistered_repair_and_identity_sources_rejected(self):
        for change in ('closure','repair','sources','caller','proposal'):
            original=deepcopy((self.mechanical,self.repair,self.callers,self.training))
            if change=='closure':self.mechanical['supplied_pixel_closure_complete']=True
            elif change=='repair':self.repair['ASA_bridge_pending_replacement']['status']='approved'
            elif change=='sources':self.callers['identity_source_sha256']['development']={'forged':digest('x')}
            elif change=='caller':self.callers['entries_private'].pop()
            else:self.mechanical['n5_identity_state_private']['protected']['training']['dish_ids']=[]
            with self.subTest(change=change),self.assertRaises(ValueError):self.run_scope()
            self.mechanical,self.repair,self.callers,self.training=original

    def test_unknown_research_cannot_be_discarded_by_classification(self):
        self.local['research_dispositions_private'][0]['excluded_from_potential_inputs']=True
        with self.assertRaisesRegex(ValueError,'must_stay_protected'):self.run_scope()
        self.local['research_dispositions_private'][0]['excluded_from_potential_inputs']=False
        self.local['other_unassigned_identity_metadata_private'].pop()
        with self.assertRaisesRegex(ValueError,'must_be_retained'):self.run_scope()

    def test_unmatched_protected_anchor_remains_fatal(self):
        roles=self.audit['asa_role_sources_private'];roles['roleanchors']['history']['hashes'].add(digest('unmatched'))
        graph,summary=_build_phase_graph(self.mechanical['asa_mechanical_sources'],roles,self.mechanical['local_content_private'],
            expected_counts={'core':(2,2),'validation':(1,1)})
        self.audit['asa_phase_graph_private']=plain(graph);self.audit['asa_summary_private']=plain(summary)
        with self.assertRaisesRegex(ValueError,'unmatched_protected_anchor'):self.run_scope()

    def test_serialized_sets_compare_and_public_counts_cannot_be_overridden(self):
        # Actual receipt projections have all sets converted to sorted JSON lists.
        self.mechanical=plain(self.mechanical);self.audit=plain(self.audit)
        self.assertEqual(self.run_scope()['known_scope']['project_local_images'],5)
        with self.assertRaises(TypeError):s.disposition(self.mechanical,self.audit,self.callers,self.training,self.local,
            repair_registration=self.repair,counts=self.counts)

if __name__=='__main__':unittest.main()
