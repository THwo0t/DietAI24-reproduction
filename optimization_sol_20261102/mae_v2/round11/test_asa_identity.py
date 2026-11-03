from copy import deepcopy
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parent))
from asa_identity import inventory,ROLES


class PartialByteIdentityTests(unittest.TestCase):
    def setUp(self):
        self.roles={role:{'codes':[],'images':[],'hashes':[]} for role in ROLES}

    def test_missing_image_retains_metadata_bridge_and_never_claims_full_byte_coverage(self):
        self.roles['core']['codes']=['11111111']
        self.roles['validation']['codes']=['22222222']
        pairs=[('11111111','unknown.png'),('22222222','unknown.png'),('33333333','known.png')]
        private,proof=inventory(pairs,[('known.png','a'*64)],self.roles,unknown_images={'unknown.png'})
        self.assertEqual(proof['observed_protected_intersections']['core__validation'],1)
        self.assertFalse(proof['supplied_graph_byte_closure_complete'])
        self.assertEqual(proof['unknown_image_count'],1)
        self.assertIn(private['node_groups']['c:11111111'],private['unresolved_groups'])
        self.assertFalse(proof['external_source_completeness_proven'])

    def test_two_unknown_images_do_not_share_a_fictitious_none_hash(self):
        private,proof=inventory([('11111111','one.png'),('22222222','two.png')],[],
            self.roles,unknown_images={'one.png','two.png'})
        self.assertNotEqual(private['node_groups']['i:one.png'],private['node_groups']['i:two.png'])
        self.assertEqual(proof['unresolved_component_count'],2)
        self.assertFalse(any(node.startswith('h:') for node in private['node_groups']))

    def test_missing_or_extra_unknown_claim_and_conflicting_basename_refuse(self):
        pairs=[('11111111','one.png')]
        for rows,unknown in (([],set()),([('one.png','a'*64)],{'one.png'}),
                             ([('one.png','a'*64),('one.png','b'*64)],set())):
            with self.subTest(rows=rows,unknown=unknown):
                with self.assertRaises(ValueError):inventory(pairs,rows,self.roles,unknown_images=unknown)

    def test_unmatched_protected_anchor_is_explicit_unresolved(self):
        self.roles['validation']['codes']=['22222222']
        private,proof=inventory([('11111111','one.png')],[('one.png','a'*64)],
                                self.roles,unknown_images=set())
        self.assertIn('c:22222222',private['node_groups'])
        self.assertEqual(proof['protected_unresolved_component_counts']['validation'],1)
        self.assertFalse(proof['supplied_graph_byte_closure_complete'])

    def test_complete_supplied_pixels_still_do_not_prove_external_source_coverage(self):
        self.roles['core']['codes']=['11111111']
        self.roles['validation']['hashes']=['a'*64]
        private,proof=inventory([('11111111','one.png')],[('one.png','a'*64)],
                                self.roles,unknown_images=set())
        self.assertTrue(proof['supplied_graph_byte_closure_complete'])
        self.assertFalse(proof['external_source_completeness_proven'])
        self.assertEqual(proof['observed_protected_intersections']['core__validation'],1)
        self.assertNotIn('11111111',str(proof));self.assertNotIn('one.png',str(proof))

    def test_unknown_known_component_independence_is_not_inferred_and_all_roles_required(self):
        _,proof=inventory([('11111111','known.png'),('22222222','unknown.png')],
                         [('known.png','a'*64)],self.roles,unknown_images={'unknown.png'})
        self.assertFalse(proof['supplied_graph_byte_closure_complete'])
        roles=deepcopy(self.roles);roles.pop('retired')
        with self.assertRaisesRegex(ValueError,'complete_protected_role'):
            inventory([('11111111','one.png')],[],roles,unknown_images={'one.png'})


if __name__=='__main__':unittest.main()
