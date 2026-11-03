from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path[:0]=[str(Path(__file__).resolve().parent),str(Path(__file__).resolve().parents[1])]
import diagnose_o as d
import guarded_diagnose_o as g
import test_source_portions as fixture_module
from records_o import main_record,coding_snapshot,attach_conditional
from opt_metrics import option_prediction


class DiagnosticTests(unittest.TestCase):
    def test_namespace_check_uses_strict_kernel_process_view_and_rejects_other_interfaces(self):
        headers=(b'Inter-|   Receive |  Transmit\n'
                 b' face |bytes packets errs drop fifo frame compressed multicast|bytes packets errs drop fifo colls carrier compressed\n')
        loop=b' lo: '+b' '.join([b'0']*16)+b'\n'
        self.assertTrue(g.kernel_loopback_only(headers+loop))
        for raw in (b'',headers,headers+loop+loop,headers+loop.replace(b'lo:',b'eth0:'),
                    headers+loop+loop.replace(b'lo:',b'eth0:'),headers+loop.replace(b'0',b'-1',1),
                    headers+loop.replace(b'0',b'NaN',1),headers+loop.replace(b' lo:',b' lo'),
                    b'wrong headers\n'+loop,headers+loop+b'\xff'):
            with self.subTest(raw=raw):
                self.assertFalse(g.kernel_loopback_only(raw))

    def test_global_read_allowlist_blocks_external_credentials_labels_and_other_images(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)/'experiment';output=root/'diagnostics'
            label=root/'dev_labels.json';source=root/'source.py'
            policy=dict(allowed_files={source,label},read_trees=[root/'sealed_records'],
                        write_tree=output,receipt=root/'evidence/guard.json',
                        label_path=label,labels_allowed=False)
            for name in ('credentials.json','.env.local','val.jsonl','photo.tiff','photo.avif','secret.bin'):
                external=Path(temp)/'external'/name
                self.assertFalse(g.allowed_path(external,False,**policy),name)
                self.assertFalse(g.allowed_path(external,True,**policy),name)
            self.assertTrue(g.allowed_path(source,False,**policy))
            self.assertFalse(g.allowed_path(source,True,**policy))
            self.assertFalse(g.allowed_path(label,False,**policy))
            policy['labels_allowed']=True
            self.assertTrue(g.allowed_path(label,False,**policy))
            self.assertTrue(g.allowed_path(output/'aggregate.json',True,**policy))
            self.assertFalse(g.allowed_path(output/'unrequested.tiff',True,**policy))

    def test_partial_batch_refuses_before_label_hook(self):
        with tempfile.TemporaryDirectory() as temp:
            with patch.object(d,'ROUND',Path(temp)),patch.object(d,'sha',side_effect=AssertionError('no hash before gate')):
                called=[]
                with self.assertRaisesRegex(ValueError,'complete_scored_batch_required'):
                    d.run(before_labels=lambda:called.append(True))
                self.assertEqual(called,[])

    def test_markers_without_valid_followup_or_replay_refuse_before_labels(self):
        for case in ('followup','replay'):
            with self.subTest(case=case),tempfile.TemporaryDirectory() as temp:
                directory=Path(temp)
                for relative in ('prepared/freeze.json','runs/identities/completion.json',
                                 'runs/development/completion.json','runs/verification.json',
                                 'runs/scoring/completion.json','development_checkpoint.json',
                                 'launch/automatic_followup.json'):
                    q=directory/relative;q.parent.mkdir(parents=True,exist_ok=True);q.write_text('{}')
                (directory/'launch/automatic_followup.json').write_text(json.dumps({
                    'status':'waiting' if case=='followup' else 'development_scored'}))
                with patch.object(d,'ROUND',directory):
                    with self.assertRaisesRegex(ValueError,'followup_incomplete' if case=='followup' else 'verification_required'):
                        d.run(before_labels=lambda:(_ for _ in ()).throw(AssertionError('no labels')))

    def fixture(self,mode='standard'):
        f=fixture_module.SourcePortionTests('test_standard_is_exact_and_alternatives_do_not_duplicate_mass');f.setUp()
        f.identity['retrieved_codes']=[f.code,f.alt]
        row=dict(sample_id='synthetic',dataset='asa24',group_id='g',fold=0)
        context=f.pipeline.portion_context(f.identity,'asa24')
        choice=({'item_id':'i1','mode':'standard','option_id':'half'} if mode=='standard' else
                {'item_id':'i1','mode':'adjusted','no_standard_fit':True,
                 'unit_id':context[0]['canonical_units'][0]['unit_id'],'count':1.5})
        portion=f.parse(choice)
        record=main_record(row,f.identity,portion,dict(weight=1,energy=1,fat=1,carbs=1,protein=1),
                           f.pipeline,coding_snapshot(f.identity))
        return f,row,record

    def test_physical_mode_audit_replays_exact_standard_and_unit_arithmetic(self):
        for mode,grams in [('standard',80.),('adjusted',240.)]:
            f,row,record=self.fixture(mode)
            result=d.physical_audit([row],{'synthetic':f.identity},{'synthetic':record},f.catalog)['asa24']
            self.assertEqual(result['mode_grams'],{mode:grams})
            self.assertEqual(result['mode_item_counts'],{mode:1})
            self.assertEqual(result['mapping_or_join_inconsistencies'],0)
            changed=deepcopy(record);changed['portion_result']['portions'][0]['grams']+=1
            with self.assertRaisesRegex(ValueError,'quantity_mapping_changed'):
                d.physical_audit([row],{'synthetic':f.identity},{'synthetic':changed},f.catalog)

    def test_physical_audit_is_json_stable_before_immutable_seal_comparison(self):
        f,row,record=self.fixture()
        result=d.physical_audit([row],{'synthetic':f.identity},{'synthetic':record},f.catalog)
        self.assertEqual(result,json.loads(json.dumps(result,allow_nan=False)))
        self.assertEqual(result['asa24']['physical_item_counts_on_successful_identities'],{'1':1})

    def test_mass_density_hand_identity_separates_signed_terms_without_claiming_MAE_shares(self):
        rows=[{'sample_id':'x','group_id':'g'}]
        truth={'weight':100.,'energy':100.,'fat':10.,'carbs':20.,'protein':30.}
        pred={k:3*v for k,v in truth.items()};pred['weight']=200.
        out=d.mass_density(rows,{'x':{'truth':truth}},{'x':pred})
        self.assertEqual(out['targets']['energy']['mass_signed_sum'],125.)
        self.assertEqual(out['targets']['energy']['density_signed_sum'],75.)
        self.assertEqual(out['targets']['energy']['max_identity_residual'],0.)

    def test_raw_continuous_projection_diagnostic_keeps_legal_primary(self):
        f,row,record=self.fixture()
        options=deepcopy(f.catalog['standard_options'][f.code]);f.catalog['asa_options']={f.code:options}
        result={'status':'ok','code':f.code,'option_id':'half','continuous_grams':100.,
                'prediction':option_prediction(options[0],f.catalog['foods'][f.code]['density'])}
        record=attach_conditional(record,result,{'code':f.code,'options':options},f.catalog)
        labels={'synthetic':{'truth':{'weight':90.},'food_code':f.code}}
        out=d.conditional_projection([row],labels,{'synthetic':record},{'primary':{'frozen':True}})
        self.assertEqual(out['continuous_weight_mae_on_nonfallback_Exact'],10.)
        self.assertEqual(out['legal_option_weight_mae_on_same_nonfallback_Exact'],10.)
        self.assertEqual(out['mean_absolute_legal_projection_move'],20.)
        self.assertEqual(out['official_primary_includes_fallbacks'],{'frozen':True})


if __name__=='__main__':unittest.main()
