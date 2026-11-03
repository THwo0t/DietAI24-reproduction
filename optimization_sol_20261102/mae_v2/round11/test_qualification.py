from copy import deepcopy
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parent))
from qualification import associations,ambiguous_query_weights,new_group_order


class ExpansionPrimitiveTests(unittest.TestCase):
    def test_missing_pair_hash_cannot_report_a_false_zero_protected_intersection(self):
        roles={'current_dev':{'codes':['11111111'],'images':[],'hashes':[]},
               'validation':{'codes':[],'images':[],'hashes':['a'*64]}}
        with self.assertRaisesRegex(ValueError,'complete_pair_image_hashes_required'):
            associations([('11111111','one.png')],{},roles)
        _,proof=associations([('11111111','one.png')],{'one.png':'a'*64},roles)
        self.assertEqual(proof['protected_intersections']['current_dev__validation'],1)

    def test_ineligible_bridge_and_duplicate_bytes_stay_in_complete_closure(self):
        pairs=[('11111111','one.png'),('99999999','one.png'),('99999999','two.png'),
               ('22222222','two.png'),('33333333','renamed.png')]
        hashes={'one.png':'a'*64,'two.png':'b'*64,'renamed.png':'b'*64}
        protected={'validation':{'codes':['11111111'],'images':[],'hashes':[]},
                   'current_dev':{'codes':['33333333'],'images':[],'hashes':[]}}
        private,public=associations(pairs,hashes,protected)
        self.assertEqual(public['components'],1)
        self.assertEqual(public['protected_intersections']['current_dev__validation'],1)
        self.assertEqual(len(set(private['node_groups'].values())),1)
        self.assertNotIn('11111111',str(public))
        self.assertNotIn('one.png',str(public))

    def test_unknown_protected_anchor_is_not_misreported_as_a_new_eligible_group(self):
        private,public=associations([('11111111','one.png')],{'one.png':'a'*64},
            {'history':{'codes':['88888888'],'images':[],'hashes':[]}})
        self.assertEqual(public['components'],2)
        self.assertNotEqual(private['node_groups']['c:11111111'],private['node_groups']['c:88888888'])
        with self.assertRaisesRegex(ValueError,'all_protected'):
            associations([],{}, {'validation':{'codes':[]}})

    def test_same_physical_query_conflicts_are_found_without_any_model_prediction(self):
        rows=[{'FoodCode':'11111111','Image':'one.png','Weight':100.},
              {'FoodCode':'11111111','Image':'copy.png','Weight':150.},
              {'FoodCode':'22222222','Image':'copy.png','Weight':200.}]
        hashes={'one.png':'a'*64,'copy.png':'a'*64}
        self.assertEqual(ambiguous_query_weights(rows,hashes),{('11111111','a'*64)})
        rows[1]['Weight']=100.5
        self.assertEqual(ambiguous_query_weights(rows,hashes),set())
        rows[1]['Weight']=101.
        self.assertEqual(ambiguous_query_weights(rows,hashes),set())
        rows[1]['Weight']=101.01
        self.assertEqual(ambiguous_query_weights(rows,hashes),{('11111111','a'*64)})

    def test_group_order_is_permutation_invariant_and_never_rerolls_for_shortfall(self):
        a=new_group_order(['a','b','c'],seed='fixed',count=20)
        self.assertEqual(a,new_group_order(['c','a','b','a'],seed='fixed',count=20))
        self.assertEqual(len(a),3)
        self.assertEqual(new_group_order(a,seed='fixed',count=2),a[:2])


if __name__=='__main__':unittest.main()
