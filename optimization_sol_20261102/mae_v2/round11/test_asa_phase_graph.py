"""Synthetic-only phase integration tests; no project identities or files read."""
import copy
import hashlib
import inspect
import unittest
from asa_content_identity import ALGORITHM
from asa_identity import ROLES
from asa_phase_graph import _build_phase_graph, build_phase_graph


def digest(s): return hashlib.sha256(s.encode()).hexdigest()


def fixture():
    pairs = [('11111111','a.png'), ('22222222','b.png'), ('33333333','c.png')]
    fps = [{'image':n,'bytes_sha256':digest(n),'rgb_sha256':digest('rgb'+n),
            'width':1,'height':1,'algorithm':ALGORITHM} for _,n in pairs]
    roles = {r:{k:set() for k in ('codes','images','hashes','rgb_hashes')} for r in ROLES}
    old = {'core':[], 'validation':[]}
    for role, code, name, fold in [('core','11111111','a.png',0),
                                  ('core','22222222','b.png',1),
                                  ('validation','33333333','c.png',None)]:
        old[role].append(dict(sample_id='asa24-'+code+'-one', dataset='asa24',
            split='dev' if role=='core' else 'validation', group_id='old-'+code,
            fold=fold, image_path='old/'+name, image_sha256=digest(name)))
        roles[role]['codes'].add(code); roles[role]['images'].add(name)
        roles[role]['hashes'].add(digest(name))
    current = copy.deepcopy(old)
    for rows in current.values():
        for row in rows: row['image_path']='neutral/'+digest(row['sample_id'])+'.png'
    capture = {'asa_workbook_identity':{'pairs':pairs,'metadata_images':{'a.png','b.png','c.png'}},
               'asa_archive_identity':{'image_fingerprints':fps}}
    projection = {'roleanchors':roles,'historical_pairs':[], 'originalmanifestbinding':old,
        'currentmanifestbinding':current,'role_inventory_complete':False,
        'source_association_complete':False}
    return capture,projection,{'rows_private':[]}


def run(args):
    return _build_phase_graph(*args, expected_counts={'core':(2,2),'validation':(1,1)})


class PhaseGraphTests(unittest.TestCase):
    def test_binding_and_no_permission(self):
        private, summary = run(fixture())
        self.assertTrue(all(r['source_image_hash_verified'] for rows in private['manifest_bindings'].values() for r in rows))
        self.assertEqual(summary['empty_unproven_roles'],['training','retired'])
        for key in ('role_inventory_complete','source_association_complete','actual_api_exposure_complete',
                    'candidate_eligibility_evaluated','grants_sampling_download_or_inference'):
            self.assertIs(summary[key], False)
        self.assertEqual(summary['api_calls'],0)
        self.assertNotIn('a.png',repr(summary)); self.assertNotIn('11111111',repr(summary))
        self.assertEqual(list(inspect.signature(build_phase_graph).parameters),
                         ['asa_capture','role_projection','local_content'])

    def test_full_metadata_mod_orphan_transitive(self):
        args = fixture(); cap, roles, _ = args
        cap['asa_workbook_identity']['pairs'] += [('11111111','mod.png'),('44444444','mod.png')]
        cap['asa_workbook_identity']['metadata_images'].update({'mod.png','orphan.png'})
        roles['historical_pairs'] += [('44444444','b.png')]
        graph, summary = run(args)
        self.assertEqual(summary['old_core_fold_bridge_components'],1)
        self.assertEqual(summary['unknown_byte_image_count'],2)
        self.assertIn('i:orphan.png',graph['node_groups'])
        self.assertEqual(graph['node_groups']['c:11111111'],graph['node_groups']['c:22222222'])

    def test_large_full_pair_population(self):
        args=fixture(); cap=args[0]
        cap['asa_workbook_identity']['pairs'] += [('11111111','a.png')]*253069
        _, summary=run(args)
        self.assertEqual(summary['supplied_association_rows'],253072)

    def test_cross_core_validation_pixel_bridge(self):
        args=fixture(); fps=args[0]['asa_archive_identity']['image_fingerprints']
        fps[2]['rgb_sha256']=fps[0]['rgb_sha256']
        graph,summary=run(args)
        self.assertEqual(summary['core_validation_intersection_components'],1)
        self.assertIn('core_validation_intersections',graph['stop_reasons'])

    def test_neutral_alias_matches_bytes_without_history(self):
        args=fixture(); args[2]['rows_private']=[self.local('neutral/'+digest('alias')+'.png','a.png')]
        graph, summary=run(args)
        self.assertEqual(summary['local_attachment_count'],1)
        self.assertEqual(graph['protected_groups']['history'],set())
        self.assertNotIn('i:'+digest('alias')+'.png',graph['node_groups'])

    @staticmethod
    def local(path, identity):
        return {'path':path,'bytes_sha256':digest(identity),'asa_compatible':True,
                'asa_algorithm':ALGORITHM,'asa_rgb_sha256':digest('rgb'+identity), 'width':1,'height':1}

    def test_unknown_hash_remains_unregistered(self):
        args=fixture(); args[2]['rows_private']=[self.local('other.png','unknown')]
        graph, summary=run(args)
        self.assertEqual(summary['unmatched_local_potential_input_count'],1)
        self.assertEqual(len(graph['unmatched_local_potential_inputs']),1)
        self.assertNotIn('i:other.png', graph['node_groups'])

    def test_unknown_metadata_name_does_not_authenticate_bytes(self):
        args=fixture(); args[0]['asa_workbook_identity']['metadata_images'].add('unknown.png')
        args[2]['rows_private']=[self.local('unknown.png','unknown')]
        _,summary=run(args)
        self.assertEqual(summary['unknown_byte_image_count'],1)
        self.assertEqual(summary['unmatched_local_potential_input_count'],1)

    def test_original_local_conflict_fatal(self):
        args=fixture(); args[2]['rows_private']=[self.local('a.png','wrong')]
        with self.assertRaisesRegex(ValueError,'conflicting_local_original_bytes'):run(args)

    def test_zip_conflict_fatal(self):
        args=fixture(); row=copy.deepcopy(args[0]['asa_archive_identity']['image_fingerprints'][0])
        row['bytes_sha256']=digest('wrong');args[0]['asa_archive_identity']['image_fingerprints'].append(row)
        with self.assertRaisesRegex(ValueError,'conflicting_image_basename_bytes'):run(args)

    def test_changed_old_binding_rejected(self):
        for field,value in [('fold',4),('group_id','changed'),('image_sha256',digest('changed'))]:
            args=fixture();args[1]['currentmanifestbinding']['core'][0][field]=value
            with self.assertRaises(ValueError):run(args)

    def test_old_rgb_version_rejected(self):
        args=fixture();args[0]['asa_archive_identity']['image_fingerprints'][0]['algorithm']='png-rgb-v1'
        with self.assertRaisesRegex(ValueError,'registered_pixel_semantics_required'):run(args)
        args=fixture();row=self.local('alias.png','a.png');row['asa_algorithm']='png-rgb-v1'
        args[2]['rows_private']=[row]
        with self.assertRaisesRegex(ValueError,'registered_pixel_semantics_required'):run(args)

    def test_target_payload_rejected(self):
        args=fixture();args[1]['originalmanifestbinding']['core'][0]['target']=4
        with self.assertRaisesRegex(ValueError,'identity_only_manifest_required'):run(args)

    def test_trusted_old_name_local_supplies_missing_zip(self):
        args=fixture(); args[0]['asa_archive_identity']['image_fingerprints'].pop(0)
        args[2]['rows_private']=[self.local('a.png','a.png')]
        _,summary=run(args)
        self.assertEqual(summary['unknown_byte_image_count'],0)
        self.assertEqual(summary['unverified_original_image_bindings'],0)


if __name__ == '__main__': unittest.main()
