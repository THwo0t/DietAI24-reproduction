"""Hand identities and partial-run rejection for the separate post-score helper."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch
BASE=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(BASE),str(BASE/'src'),str(BASE/'round7/src'),str(BASE/'round8/src')]
spec=importlib.util.spec_from_file_location('diagnose_n',BASE/'round8/tools/diagnose_completed_n.py')
d=importlib.util.module_from_spec(spec);spec.loader.exec_module(d)

class CompletedDiagnosticTests(unittest.TestCase):
    def setUp(self):
        self.rows=[{'sample_id':'x','group_id':'g'}]
        self.a={'x':self.record(50,100,['A'])}
        self.b={'x':self.record(50,200,['A','B'])}

    @staticmethod
    def record(grams,density,codes):
        densities={k:density for k in d.TARGETS[1:]}
        return {'fallback':False,'raw_leaves':[{'component_id':'p1c1','parent_id':'p1','grams':grams,
             'code':codes[0],'codes':codes,'density':densities}],
             'prediction':{'weight':grams,**{k:grams*density/100 for k in densities}}}

    def test_fixed_mass_density_change_has_zero_algebraic_residual(self):
        out=d.physical_changes(self.rows,self.a,self.b,'density')
        self.assertEqual(out['max_nutrient_identity_residual'],0)
        self.assertEqual(out['changed_weight_n'],0);self.assertEqual(out['changed_code_lists_n'],1)

    def test_same_density_mass_change_has_zero_residual_and_ratio_two(self):
        self.a={'x':self.record(50,200,['A','B'])};self.b={'x':self.record(100,200,['A','B'])}
        out=d.physical_changes(self.rows,self.a,self.b,'quantity')
        self.assertEqual(out['max_nutrient_identity_residual'],0)
        self.assertEqual(out['mean_predicted_mass_ratio_on_complete_pairs'],2)
        self.assertEqual(out['changed_code_lists_n'],0)

    def test_mass_parent_and_density_drift_cannot_claim_pure_intervention(self):
        bad=deepcopy(self.b);bad['x']['raw_leaves'][0]['grams']=51
        with self.assertRaisesRegex(ValueError,'mass_not_fixed'):d.physical_changes(self.rows,self.a,bad,'density')
        bad=deepcopy(self.b);bad['x']['raw_leaves'][0]['parent_id']='other'
        with self.assertRaisesRegex(ValueError,'parent_join'):d.physical_changes(self.rows,self.a,bad,'density')
        with self.assertRaisesRegex(ValueError,'identity_or_density'):
            d.physical_changes(self.rows,self.a,self.b,'quantity')

    def test_fallback_stays_in_population_and_is_separate_from_leaf_identity_check(self):
        self.b['x']['fallback']=True
        out=d.physical_changes(self.rows,self.a,self.b,'density')
        self.assertEqual(out['population_n'],1);self.assertEqual(out['fallback_pairs_n'],1)
        self.assertEqual(out['both_complete_n'],0)

    def test_incomplete_real_run_entry_rejects_before_any_label_open(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);original=Path.open;label_opens=[]
            def guarded(path,*a,**kw):
                if 'dev_labels' in str(path):label_opens.append(str(path));raise AssertionError('no labels')
                return original(path,*a,**kw)
            with patch.object(d,'ROUND',root),patch.object(Path,'open',guarded):
                with self.assertRaisesRegex(ValueError,'complete_scored_batch_required'):d.run()
            self.assertEqual(label_opens,[])

    def test_sealed_fixture_still_rejects_bad_score_follower_or_replay_before_labels(self):
        for case,message in [('score','scoring_outputs_disagree'),('follower','offline_follower_not_finished'),
                             ('replay','offline_replay_not_confirmed')]:
            with self.subTest(case=case),tempfile.TemporaryDirectory() as temp:
                root=Path(temp);round_dir=root/'round8'
                def write(name,value):
                    p=root/name;p.parent.mkdir(parents=True,exist_ok=True)
                    p.write_text(json.dumps(value));return p
                rows=[{'sample_id':str(i),'dataset':'asa24' if i<99 else 'nutrition5k','group_id':str(i)}
                      for i in range(183)]
                manifest=root/'data/cohorts/dev.jsonl';manifest.parent.mkdir(parents=True)
                manifest.write_text('\n'.join(json.dumps(r) for r in rows))
                review=round_dir/'REVIEW.md';review.parent.mkdir();review.write_text('synthetic review')
                write('round8/prepared/freeze.json',{'source_files':{},'review_sha256':d.sha(review),
                    'manifest_sha256':d.sha(manifest),'rows_sha256':d.fingerprint(rows)})
                write('round8/runs/development/completion.json',{'synthetic_seal':True})
                proof={'files':{},'counts':{'payloads':0}}
                score={'service_proof':proof}
                write('round8/runs/scoring/results.json',score)
                write('round8/development_checkpoint.json',{'wrong':True} if case=='score' else {})
                write('round8/launch/automatic_followup.json',{'status':'waiting' if case=='follower' else 'development_scored'})
                write('round8/launch/automatic_verify.log',{'status':'completed','completed_replay':True,
                    'provider_constructed':case=='replay','pairs':183,'service_counts':proof['counts']})
                records={'service-proof':proof}
                for profile in d.PROFILES:
                    for row in rows:records[d.record_name(profile,row)]={}
                original=Path.open;label_opens=[]
                def guarded(path,*a,**kw):
                    if 'dev_labels' in str(path):label_opens.append(str(path));raise AssertionError('no labels')
                    return original(path,*a,**kw)
                with patch.object(d,'ROOT',root),patch.object(d,'ROUND',round_dir),\
                     patch.object(d,'source_pins',return_value={}),\
                     patch.object(d,'ArtifactStore',return_value=SimpleNamespace(verify_completed=lambda:records)),\
                     patch.object(Path,'open',guarded):
                    with self.assertRaisesRegex(ValueError,message):d.run()
                self.assertEqual(label_opens,[])

if __name__=='__main__':unittest.main()
