from copy import deepcopy
import unittest

import scoring_p as scoring
import opt_metrics as metrics


def fixture():
    rows=[];labels={};records=[];code='12345678'
    catalog={'foods':{code:{'density':{k:100 for k in metrics.KEYS[1:]}}},
        'asa_options':{code:[{'option_id':str(w),'grams':w} for w in (50,100,150)]}}
    for ds in metrics.DATASETS:
        for i in range(5):
            sid=ds+str(i);row={'sample_id':sid,'dataset':ds,'split':'dev','group_id':sid,'fold':i,
                'image_path':sid+'.png','image_sha256':'a'*64};rows.append(row)
            labels[sid]={'truth':{k:100.0 for k in metrics.KEYS},'split':'dev'}
            if ds=='asa24':labels[sid]['food_code']=code
            branch=({'code':code,'options':catalog['asa_options'][code],'option_id':'100',
                'continuous_grams':100,'prediction':{k:100.0 for k in metrics.KEYS},'fallback':False,
                'status':'native'} if ds=='asa24' else None)
            profiles={}
            for p in scoring.PROFILES:
                profiles[p]={'profile':p,'prediction':{k:100.0 for k in metrics.KEYS},
                    'e2e':{'prediction':{k:100.0 for k in metrics.KEYS},'fallback':False},
                    'raw_prediction':{k:100.0 for k in metrics.KEYS},'status':'native',
                    'fallback':False,'final_codes':[code] if ds=='asa24' else [],
                    'primary_code':code if ds=='asa24' else None,'conditional':deepcopy(branch)}
            records.append({'row':deepcopy(row),'coding':{'final_codes':[code] if ds=='asa24' else []},
                            'profiles':profiles,'conditional':deepcopy(branch)})
    return rows,labels,records,catalog


class ScoringTests(unittest.TestCase):
    def test_complete_four_profiles_exact_and_bootstrap(self):
        rows,labels,records,catalog=fixture();result=scoring.score(rows,labels,records,catalog,bootstrap=12)
        self.assertEqual(result['selected_profile'],'O')
        self.assertFalse(result['independent_acceptance_success'])
        for p in scoring.PROFILES:
            value=result['profiles'][p]
            self.assertTrue(value['raw_decision']['strict20'])
            self.assertEqual(value['raw']['datasets']['asa24']['primary']['n'],5)
            self.assertEqual(value['raw']['datasets']['asa24']['bootstrap']['replicates'],12)

    def test_hand_MAE_perunit_and_zero_reference(self):
        stats=metrics._stats([{'truth':dict.fromkeys(metrics.KEYS,0)},
                            {'truth':dict.fromkeys(metrics.KEYS,10)}],
                           [dict.fromkeys(metrics.KEYS,2),dict.fromkeys(metrics.KEYS,14)],'nutrition5k')
        self.assertEqual(stats['metrics']['weight']['mae'],3)
        self.assertEqual(stats['metrics']['weight']['per_unit'],.6)
        zero=metrics._stats([{'truth':dict.fromkeys(metrics.KEYS,0)}],[dict.fromkeys(metrics.KEYS,0)],'nutrition5k')
        self.assertIsNone(zero['metrics']['weight']['per_unit'])
        self.assertFalse(zero['metrics']['weight']['pass_per_unit'])

    def test_fallback_all_rows_and_common_Exact_denominator(self):
        rows,labels,records,catalog=fixture()
        for p in records[0]['profiles'].values():
            p['status']='fallback';p['fallback']=True;p['e2e']['fallback']=True
            p['conditional']['fallback']=True;p['conditional']['status']='fallback';p['conditional']['continuous_grams']=None
        records[0]['conditional']['fallback']=True;records[0]['conditional']['status']='fallback';records[0]['conditional']['continuous_grams']=None
        result=scoring.score(rows,labels,records,catalog,bootstrap=0)
        asa=result['profiles']['O']['raw']['datasets']['asa24']
        self.assertEqual(asa['primary']['n'],5);self.assertEqual(asa['conditional_fallback_n'],1)
        self.assertEqual(asa['e2e']['n'],5)

    def test_failclosed_poison_missing_dupe_stratum_shared(self):
        for mode in ('nan','negative','missing','duplicate','shared','strata'):
            rows,labels,records,catalog=fixture();strata=None
            if mode=='nan':labels[rows[0]['sample_id']]['truth']['weight']=float('nan')
            elif mode=='negative':records[0]['profiles']['O']['prediction']['weight']=-1
            elif mode=='missing':records.pop()
            elif mode=='duplicate':records[-1]=deepcopy(records[0])
            elif mode=='shared':records[0]['profiles']['Q']['conditional']['continuous_grams']=200
            else:strata={r['sample_id']:'invalid' for r in rows}
            with self.subTest(mode=mode),self.assertRaises(ValueError):
                scoring.score(rows,labels,records,catalog,strata=strata,bootstrap=0)

    def test_no_lost_pass_and_unrounded_cap(self):
        rows,labels,records,catalog=fixture();pred=scoring._prepare(rows,labels,records,catalog,None)['O']
        raw=metrics.evaluate(rows,labels,pred);cal=deepcopy(raw)
        raw['checks'][0].update({'value':2,'threshold':1,'pass':False})
        cal['checks'][0].update({'value':1.5,'threshold':1,'pass':False})
        self.assertTrue(scoring.retain_calibration(raw,cal))
        cal['checks'][1].update({'value':1.0000000001,'threshold':1,'pass':False})
        self.assertFalse(scoring.retain_calibration(raw,cal))
        self.assertFalse(scoring.decision(cal)['strict20'])
        self.assertEqual(scoring.decision(raw)['minimum_15_percent_n'],1)
        self.assertEqual(scoring.decision(raw)['original_18_percent_n'],1)

    def test_integer_floors_group_bootstrap_and_shrink_bounds(self):
        rows,labels,records,catalog=fixture()
        preds=scoring._prepare(rows,labels,records,catalog,None)['O']
        a=metrics.evaluate(rows,labels,preds,bootstrap=8,seed=20261104)
        b=metrics.evaluate(rows,labels,preds,bootstrap=8,seed=20261104)
        self.assertEqual(a,b)
        asa=a['datasets']['asa24'];asa.update(n=99,exact_n=17,exact_groups=5)
        guard=scoring.decision(a)
        self.assertEqual(guard['minimum_15_percent_n'],15)
        self.assertEqual(guard['original_18_percent_n'],18)
        self.assertTrue(guard['recognition15_and5groups'])
        self.assertFalse(guard['original_18_percent_pass'])
        self.assertEqual(scoring._fit_factor([100],[200]),1.125)
        self.assertEqual(scoring._fit_factor([100],[0]),.9)
        # An unscaled fallback contributes a constant, never drives a factor.
        self.assertEqual(scoring._fit_factor([100],[200],[False]),1)
        subset=[r for r in rows if r['fold']!=0]
        with self.assertRaisesRegex(ValueError,'outer_training_labels_only_required'):
            scoring.fit_outer_parameters(subset,labels,[p for p in preds if p['fold']!=0],catalog)

    def test_analytic_weighted_median_tie_intervals_and_constants(self):
        # Weight x=3 dominates x=1: optimum 1.1, half shrink 1.05.
        self.assertAlmostEqual(scoring._fit_factor([1,3],[.9,3.3]),1.05)
        # Equal weights produce an interval: choose closest-to-one, not a grid.
        self.assertEqual(scoring._fit_factor([1,1],[.9,1.2]),1)
        self.assertAlmostEqual(scoring._fit_factor([1,1],[1.031,1.2]),1.0155)
        self.assertAlmostEqual(scoring._fit_factor([1,1],[.81,.91]),.955)
        self.assertEqual(scoring._fit_factor([0,0],[100,1000]),1)
        self.assertEqual(scoring._fit_factor([0,1,9999],[100,1.1,0],[True,True,False]),1.05)
        self.assertEqual(scoring._fit_factor([1],[100]),1.125)
        self.assertEqual(scoring._fit_factor([1],[0]),.9)

    def test_full_development_fit_only_after_selected_raw_arm(self):
        rows,labels,records,catalog=fixture()
        preds=scoring._prepare(rows,labels,records,catalog,None)['O']
        with self.assertRaisesRegex(ValueError,'completed_method_selection_required'):
            scoring.full_development_parameters(rows,labels,preds,catalog,
                selected_profile='O',selection_confirmed=False)
        fitted=scoring.full_development_parameters(rows,labels,preds,catalog,
            selected_profile='O',selection_confirmed=True)
        self.assertEqual(fitted['parameters']['nutrition5k']['factors'],dict.fromkeys(metrics.KEYS,1))
        self.assertFalse(fitted['grants_inference_or_acceptance'])
        transformed=scoring.crossvalidate(rows,labels,preds,catalog,calibrate=True)[0]
        with self.assertRaisesRegex(ValueError,'uncalibrated_selected_arm_required'):
            scoring.full_development_parameters(rows,labels,transformed,catalog,
                selected_profile='O',selection_confirmed=True)

    def test_R_P_2_density_primary_separate_from_original_common_identity(self):
        rows,labels,records,catalog=fixture();true='12345678';wrong='87654321'
        strata={r['sample_id']:('core84' if r['dataset']=='nutrition5k' else
            ('asa_core','asa_core_all_legal_extra','asa_broader_frame')[r['fold']%3]) for r in rows}
        for record in records:
            if record['row']['dataset']!='asa24':continue
            sid=record['row']['sample_id'];labels[sid]['size']=('smallest','medium','largest')[record['row']['fold']%3]
            record['coding']['final_codes']=[wrong,true]
            for profile,pred in record['profiles'].items():
                reported=true if profile in ('D','Q+D') else wrong
                pred.update(final_codes=[wrong,true],primary_code=wrong,density_primary_code=reported,
                    match={'original_primary_code':wrong,'reported_primary_code':reported,
                           'final_code_set':sorted([wrong,true])})
        before=deepcopy(records);result=scoring.score(rows,labels,records,catalog,strata=strata,bootstrap=0)
        for profile in scoring.PROFILES:
            original=result['profiles'][profile]['raw']['datasets']['asa24']
            self.assertEqual(original['first_n'],0);self.assertEqual(original['exact_n'],5)
            self.assertEqual(original['primary']['n'],5)
            if profile in ('D','Q+D'):
                separate=result['profiles'][profile]['density_selected_primary_recognition']
                self.assertEqual((separate['first_n'],separate['first_rate']),(5,1))
                self.assertEqual(separate['changed_primary_n'],5)
                self.assertEqual(separate['common_Exact_n'],5)
                self.assertEqual(sum(x['n'] for x in separate['by_size'].values()),5)
                self.assertEqual(sum(x['first_n'] for x in separate['by_stratum'].values()),5)
            else:self.assertNotIn('density_selected_primary_recognition',result['profiles'][profile])
        self.assertEqual(records,before)
        # A missing density choice remains an all-row recognition failure, even
        # though its true code stays in the shared coding/Exact population.
        for profile in ('D','Q+D'):
            records[4]['profiles'][profile]['density_primary_code']=None
            records[4]['profiles'][profile]['match']['reported_primary_code']=None
            records[4]['profiles'][profile]['provenance']={'stage_statuses':{'density':'failed'}}
        failed=scoring.score(rows,labels,records,catalog,strata=strata,bootstrap=0)
        for profile in ('D','Q+D'):
            separate=failed['profiles'][profile]['density_selected_primary_recognition']
            self.assertEqual((separate['n'],separate['first_n'],separate['first_rate']),(5,4,.8))
            self.assertEqual(separate['unavailable_n'],1)
            self.assertEqual(separate['common_Exact_n'],5)
            self.assertEqual(separate['code_identity_private'][4]['unavailable_reason'],
                             'density_stage_failed')
            self.assertEqual(separate['unavailable_reason_counts'],{'density_stage_failed':1})
        self.assertEqual(failed['selected_profile'],result['selected_profile'])

    def test_R_P_2_absent_codes_and_altered_density_identity(self):
        rows,labels,records,catalog=fixture()
        predictions=scoring._prepare(rows,labels,records,catalog,None)['D']
        predictions[0].update(final_codes=[],primary_code=None,density_primary_code=None,
                              match={'reported_primary_code':None})
        report=scoring._density_primary_recognition(rows,labels,predictions,None)
        self.assertEqual(report['n'],5);self.assertEqual(report['unavailable_n'],5)
        self.assertFalse(report['code_identity_private'][0]['common_Exact'])
        predictions[1]['density_primary_code']='87654321'
        with self.assertRaisesRegex(ValueError,'density_primary_outside_common_code_set'):
            scoring._density_primary_recognition(rows,labels,predictions,None)

    def test_outer_query_poison_does_not_change_fold_fit_or_fallback(self):
        rows,labels,records,catalog=fixture()
        # Failed outer-training rows previously had their own OOF fallback,
        # which could include the heldout query label. Poison it aggressively.
        for record in records:
            if record['row']['dataset']=='nutrition5k' and record['row']['fold']==1:
                for p in record['profiles'].values():
                    p['fallback']=True;p['status']='fallback'
                    p['prediction']=dict.fromkeys(metrics.KEYS,999999)
                    p['e2e']['prediction']=dict(p['prediction']);p['e2e']['fallback']=True
        preds=scoring._prepare(rows,labels,records,catalog,None)['O']
        first=scoring.crossvalidate(rows,labels,preds,catalog,calibrate=True)[1]
        poisoned=deepcopy(labels)
        for row in rows:
            if row['fold']==0:poisoned[row['sample_id']]['truth']=dict.fromkeys(metrics.KEYS,1e8)
        second=scoring.crossvalidate(rows,poisoned,preds,catalog,calibrate=True)[1]
        self.assertEqual(first[0],second[0])
        params=first[0]['parameters']['nutrition5k']
        self.assertEqual(params['fallback'],dict.fromkeys(metrics.KEYS,100))
        self.assertEqual(params['factors'],dict.fromkeys(metrics.KEYS,1))


if __name__=='__main__':unittest.main()
