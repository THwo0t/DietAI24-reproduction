"""O's complete-cohort raw and grouped OOF mass comparison, no inference."""
from copy import deepcopy

from opt_metrics import evaluate,fold_medians,median_option,option_prediction,_stats
import metrics_v2 as fitting
from scoring_m import tolerance
from opt_provider import fingerprint


def score(rows,labels,records,catalog,*,bootstrap=10000):
    if (len(rows)!=len(records) or {r['sample_id'] for r in rows}!={r['sample_id'] for r in records}
            or set(labels)!={r['sample_id'] for r in rows}):
        raise ValueError('O_complete_cohort_score_required')
    density={c:v['density'] for c,v in catalog['foods'].items()}
    options=catalog['asa_options']
    raw=fitting.crossvalidate(rows,labels,records,options,density,calibrate=False)
    selected={p['sample_id']:deepcopy(p) for p in raw['predictions']}
    calibration={};parameters={}
    for dataset in ('asa24','nutrition5k'):
        calibrated=fitting.crossvalidate(rows,labels,records,options,density,calibrate=True,dataset=dataset)
        enabled=fitting.calibration_improves(raw['metrics'],calibrated['metrics'],dataset)
        calibration[dataset]={'enabled':enabled,
            'reason':'strict_worst_improvement_without_lost_pass' if enabled else 'calibration_not_retained',
            'raw_primary':raw['metrics']['datasets'][dataset]['primary'],
            'calibrated_primary':calibrated['metrics']['datasets'][dataset]['primary'],
            'fold_parameters':calibrated['fold_parameters']}
        if enabled:
            for pred in calibrated['predictions']:
                if pred['dataset']==dataset:selected[pred['sample_id']]=deepcopy(pred)
        subset=[r for r in rows if r['dataset']==dataset]
        ids={r['sample_id'] for r in subset}
        parameters[dataset]=fitting.fit_final(subset,{sid:labels[sid] for sid in ids},
            [p for p in records if p['sample_id'] in ids],options,density,dataset=dataset,enabled=enabled)
    selected_predictions=[selected[r['sample_id']] for r in rows]
    raw_metrics=evaluate(rows,labels,raw['predictions'],bootstrap=bootstrap,seed=20261102)
    selected_metrics=evaluate(rows,labels,selected_predictions,bootstrap=bootstrap,seed=20261102)
    baselines={}
    for dataset in ('asa24','nutrition5k'):
        population=[r for r in rows if r['dataset']==dataset]
        baseline=[fold_medians(rows,labels,heldout_fold=r['fold'],dataset=dataset) for r in population]
        baselines[dataset+'_all_population_median']=_stats([labels[r['sample_id']] for r in population],baseline,dataset)
    by_id={r['sample_id']:r for r in records}
    exact=[r for r in rows if r['dataset']=='asa24'
           and labels[r['sample_id']]['food_code'] in by_id[r['sample_id']]['final_codes']]
    legal=[]
    for r in exact:
        code=labels[r['sample_id']]['food_code']
        legal.append(option_prediction(median_option(options[code]),density[code]))
    baselines['asa24_fixed_Exact_median_legal_option']=_stats([labels[r['sample_id']] for r in exact],legal,'asa24')
    result={'scope':'O_development_OOF_not_independent_validation',
        'raw':{'metrics':raw_metrics,'tolerance':tolerance(raw_metrics)},
        'OOF_mass':{'metrics':selected_metrics,'tolerance':tolerance(selected_metrics)},
        'calibration':calibration,'full_development_parameters':parameters,
        'pure_median_baselines':baselines,
        'conditional_success':{'n':len(exact),
            'native_n':sum(bool(by_id[r['sample_id']]['conditional'].get('native_complete')) for r in exact),
            'repair_success_n':sum(bool(by_id[r['sample_id']].get('conditional_repair_used'))
                and not by_id[r['sample_id']]['conditional']['fallback'] for r in exact),
            'fallback_n':sum(by_id[r['sample_id']]['conditional']['fallback'] for r in exact)},
        'source_records_sha256':fingerprint(records),'validation_opened':False,'api_calls':0}
    result['selection']={'profile':'OOF_mass','accepted':result['OOF_mass']['tolerance']['accepted'],
        'reason':'preregistered_per_dataset_OOF_retention_rule_on_one_common_raw_method'}
    return result,selected_predictions


def public_summary(result):
    out=deepcopy(result)
    for value in out['calibration'].values():value.pop('fold_parameters',None)
    for value in out['full_development_parameters'].values():
        for name in ('training_ids','eligible_ids'):value.pop(name,None)
    return out
