from copy import deepcopy
from decimal import Decimal
import unittest

import asa_expansion_v3 as expansion
from source_census import sha


def fixture(groups=21):
    def identity(code,i,split,group):
        return {'sample_id':f'asa24-{code}-p{i}','dataset':'asa24','split':split,
            'group_id':group,'fold':0 if split=='dev' else None,
            'image_path':f'data/asa24/{split}/images/p{i}.png','image_sha256':sha(str(i).encode())}
    core=[identity('10000000',0,'dev','oldcore')]
    val=[identity('10000000',i,'validation','linked') for i in (1,2,3)]+[
        identity('10000001',4,'validation','retained')]
    mapping={'c:10000000':'core','c:10000001':'val'};hashes={};rows=[]
    def legal(code,image,weight,digest=None):
        hashes[image]=digest or sha(image.encode());mapping['i:'+image]=mapping['c:'+code]
        rows.append({'FoodCode':code,'Image':image,'Portion':str(weight),'PortionCode':98,
            'Multiplier':Decimal(weight),'PortionWeight':Decimal(1),'Weight':Decimal(weight)})
    legal('10000000','original.png',10,core[0]['image_sha256'])
    legal('10000000','extra.png',20)
    permitted=set();codes=set()
    for i in range(groups):
        code=str(20000000+i);group='new-'+str(i);mapping['c:'+code]=group
        permitted.add(group);codes.add(code)
        for w in (10,20,30):legal(code,f'n{i}-{w}.png',w)
    scope={'asa_permitted_components_private':permitted,'asa_permitted_codes_private':codes,
        'asa_blocked_components_private':{'core','val'},
        'missing_source_quarantine_components_private':set()}
    return core,val,{'core':deepcopy(core),'validation':deepcopy(val)}, {'rows':rows,'ambiguous_code_images':set()}, {'node_groups':mapping},scope,hashes,codes


def build(values):
    return expansion._build(*values,counts={'core':(1,1),'validation':(4,2)},broader_count=20)


class ExpansionTests(unittest.TestCase):
    def test_original_rows_unchanged_and_core_linked_val_additions_excluded(self):
        values=fixture();before=deepcopy(values);result=build(values)
        self.assertEqual(values,before)
        self.assertEqual(result['original_core_private'],values[0])
        self.assertEqual(result['original_validation_legacy_reserved_private'],values[1])
        self.assertEqual(result['core_extra_proposals_private'],[])
        self.assertEqual(len(result['chosen_broader_components_private']),20)
        self.assertEqual(result['validation_proposal_private']['resulting_rows'],4)
        self.assertEqual(result['shortfall_reasons'],[])
        self.assertTrue(result['pending_boundary_confirmation'])
        self.assertFalse(result['grants_sampling_download_or_inference'])

    def test_core_duplicate_photo_excluded_but_new_photo_kept(self):
        values=list(fixture());core,val,old,legal,graph,scope,hashes,top=values
        # Move linked validation to its own protected component, leaving core safe
        # for the specifically registered within-core expansion exemption.
        for row in val[:3]:row['sample_id']=row['sample_id'].replace('10000000','10000002')
        old['validation']=deepcopy(val);graph['node_groups']['c:10000002']='linked-val'
        scope['asa_blocked_components_private'].add('linked-val')
        result=build(values)
        self.assertEqual([r['Image'] for r in result['core_extra_proposals_private']],['extra.png'])
        self.assertEqual(result['original_core_private'][0]['fold'],0)

    def test_missing_or_blocked_components_excluded(self):
        values=list(fixture());scope=values[5]
        scope['asa_permitted_components_private'].remove('new-0')
        scope['asa_permitted_codes_private'].remove('20000000')
        scope['asa_blocked_components_private'].add('new-0')
        scope['missing_source_quarantine_components_private'].add('new-0')
        result=build(values)
        self.assertNotIn('new-0',result['chosen_broader_components_private'])
        self.assertIn('validation_record_shortfall_or_population_mismatch',result['shortfall_reasons'])

    def test_bad_legal_code_nan_and_illegal_column(self):
        for key,value in [('FoodCode','bad'),('Weight',Decimal('NaN')),('truth',1)]:
            values=list(fixture());values[3]['rows'][0][key]=value
            with self.subTest(key=key),self.assertRaises((ValueError,KeyError)):build(values)

    def test_deterministic_group20_then_replacement_and_weight_ties(self):
        values=fixture();a=build(values)
        reordered=list(deepcopy(values));reordered[3]['rows'].reverse();b=build(reordered)
        self.assertEqual(a,b)
        proposal=a['validation_proposal_private']
        self.assertEqual(proposal['replacement_component'],a['broader_component_order_private'][20])
        self.assertNotIn(proposal['replacement_component'],a['chosen_broader_components_private'])
        self.assertEqual([r['portion_source_private']['Weight'] for r in proposal['new_triplet_rows']],
                         [Decimal(30),Decimal(20),Decimal(10)])

    def test_shortfall_no_topup_or_reroll(self):
        result=build(fixture(19))
        self.assertEqual(len(result['chosen_broader_components_private']),19)
        self.assertEqual(result['validation_proposal_private']['new_triplet_rows'],[])
        self.assertIn('broader_component_shortfall',result['shortfall_reasons'])
        values=list(fixture());ordered=build(values)['broader_component_order_private']
        last=ordered[20]
        values[3]['rows']=[r for r in values[3]['rows']
            if values[4]['node_groups']['c:'+r['FoodCode']]!=last or r['Weight']==10]
        result=build(values)
        self.assertEqual(result['validation_proposal_private']['replacement_component'],last)
        self.assertEqual(result['validation_proposal_private']['new_triplet_rows'],[])


if __name__=='__main__':unittest.main()
