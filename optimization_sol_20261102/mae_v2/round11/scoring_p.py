"""Pure post-seal P scoring. Caller authenticates completed records and sources.

No provider/replay/file access; postscore fits are separate from inference freeze.
OOF search/tolerance never constitute independent acceptance or action permission.
"""
from copy import deepcopy
import math
from statistics import median
from fractions import Fraction

import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
import opt_metrics as metrics
from metrics_v2 import ratios
from source_census import require, encoded, sha

PROFILES=('O','Q','D','Q+D')
STRATA={'nutrition5k':{'core84','historical_support230_reused_not_fresh'},
        'asa24':{'asa_core','asa_core_all_legal_extra','asa_broader_frame'}}


def _vector(value):
    require(isinstance(value,dict) and set(value)==set(metrics.KEYS),'five_exact_scoring_targets_required')
    require(all(type(v) in (int,float) and math.isfinite(v) and v>=0 for v in value.values()),
            'finite_nonnegative_scoring_targets_required')
    return dict(value)


def _prepare(rows,labels,records,catalog,strata):
    metrics._training(rows,labels)
    require(set(labels)=={r['sample_id'] for r in rows} and len(rows)==len(records),
            'complete_P_population_required')
    require(all(type(r['fold']) is int and r['fold'] in range(5) for r in rows),'five_registered_folds_required')
    by_id={}
    for record in records:
        row=record['row'];sid=row['sample_id']
        require(sid not in by_id and set(record['profiles'])==set(PROFILES),'unique_four_profile_record_required')
        by_id[sid]=record
    require(set(by_id)==set(labels),'complete_P_record_identities_required')
    if strata is not None:
        require(set(strata)==set(labels) and all(strata[r['sample_id']] in STRATA[r['dataset']] for r in rows),
                'source_bound_complete_strata_required')
    output={p:[] for p in PROFILES};exact={p:set() for p in PROFILES}
    for row in rows:
        sid=row['sample_id'];record=by_id[sid]
        require(record['row']==row,'P_record_manifest_binding_changed');_vector(labels[sid]['truth'])
        shared=record['conditional']
        is_exact=row['dataset']=='asa24' and labels[sid]['food_code'] in record['coding']['final_codes']
        require(is_exact or shared is None,'conditional_branch_outside_common_Exact')
        for profile in PROFILES:
            value=record['profiles'][profile];codes=value['final_codes']
            require(value['profile']==profile and value['status'] in ('native','repaired','fallback')
                    and type(value['fallback']) is bool and value['fallback']==(value['status']=='fallback')
                    and value['conditional']==shared and codes==record['coding']['final_codes'],
                    'coherent_shared_P_profile_required')
            _vector(value['prediction']);_vector(value['e2e']['prediction'])
            require(value['e2e']['prediction']==value['prediction'],'P_e2e_prediction_changed')
            pred={**deepcopy(value),'sample_id':sid,'dataset':row['dataset'],
                'group_id':row['group_id'],'fold':row['fold'],
                'native_complete':value['status']=='native','repair_used':value['status']=='repaired'}
            if row['dataset']=='asa24' and labels[sid]['food_code'] in codes:
                exact[profile].add(sid)
                require(shared is not None and shared['code']==labels[sid]['food_code'],
                        'complete_common_Exact_branch_required')
                _vector(shared['prediction']);options=catalog['asa_options'][shared['code']]
                require(type(shared['fallback']) is bool and shared['status'] in ('native','repaired','fallback')
                        and shared['fallback']==(shared['status']=='fallback')
                        and shared['options']==options,'shared_conditional_status_or_catalog_changed')
                option=metrics.median_option(options) if shared['fallback'] else metrics.nearest_option(
                    metrics._number(shared['continuous_grams'],'continuous_grams'),options)
                require(shared['option_id']==option['option_id'] and
                        shared['prediction']==metrics.option_prediction(option,catalog['foods'][shared['code']]['density']),
                        'legal_shared_conditional_prediction_required')
            output[profile].append(pred)
    require(all(exact[p]==exact['O'] for p in PROFILES),'common_Exact_population_changed')
    for profile in PROFILES:metrics._validate(rows,labels,output[profile])
    return output


def _fit_factor(values,targets,scalable=None):
    """Exact bounded L1 optimum via weighted median interval, half shrunk.

    Positive scalable x contributes weight x at ratio y/x. Zero predictors and
    frozen fallbacks contribute constants, so cannot move the minimizer. For an
    interval of minimizers choose the point closest to one before half shrink.
    """
    require(len(values)==len(targets),'calibration_population_changed')
    scalable=[True]*len(values) if scalable is None else scalable
    require(len(scalable)==len(values) and all(type(v) is bool for v in scalable),
            'calibration_scalability_required')
    require(all(type(v) in (int,float) and math.isfinite(v) and v>=0
                for v in list(values)+list(targets)), 'finite_L1_inputs_required')
    pairs=sorted((Fraction(y)/Fraction(x),Fraction(x))
                 for x,y,scale in zip(values,targets,scalable) if scale and x>0)
    if not pairs:return 1.0
    half=sum((w for _,w in pairs),Fraction(0))/2
    cumulative=Fraction(0);lower=upper=None
    for ratio,weight in pairs:
        cumulative+=weight
        if lower is None and cumulative>=half:lower=ratio
        if cumulative>half:
            upper=ratio;break
    if upper is None:upper=pairs[-1][0]
    lower=max(Fraction(4,5),min(Fraction(5,4),lower))
    upper=max(Fraction(4,5),min(Fraction(5,4),upper))
    optimum=max(lower,min(Fraction(1),upper))
    return float(1+Fraction(1,2)*(optimum-1))


def fit_outer_parameters(training_rows,training_labels,training_predictions,catalog):
    """Only outer-training labels accepted; fallback predictors rebuilt here.

    Never pass the full label dictionary: exact equality rejects extra heldout IDs.
    Model-success predictions remain label-free; failed training rows receive a
    median using this outer training population, not their original OOF fallback.
    """
    require(set(training_labels)=={r['sample_id'] for r in training_rows},'outer_training_labels_only_required')
    metrics._training(training_rows,training_labels)
    metrics._validate(training_rows,training_labels,training_predictions)
    for row in training_rows:_vector(training_labels[row['sample_id']]['truth'])
    for pred in training_predictions:_vector(pred['prediction'])
    pi=metrics._index(training_predictions,'outer training predictions')
    require(set(pi)==set(training_labels),'outer_training_predictions_complete_required')
    parameters={}
    for ds in metrics.DATASETS:
        subset=[r for r in training_rows if r['dataset']==ds]
        if not subset:continue
        med=metrics.fold_medians(subset,training_labels,dataset=ds)
        info={'dataset':ds,'training_ids':[r['sample_id'] for r in subset],'fallback':med}
        if ds=='nutrition5k':
            rebuilt=[med if pi[r['sample_id']]['fallback'] else pi[r['sample_id']]['prediction'] for r in subset]
            info['factors']={k:_fit_factor([p[k] for p in rebuilt],
                [training_labels[r['sample_id']]['truth'][k] for r in subset],
                [not pi[r['sample_id']]['fallback'] for r in subset]) for k in metrics.KEYS}
            info['outer_training_fallback_recomputed_ids']=[r['sample_id'] for r in subset if pi[r['sample_id']]['fallback']]
        else:
            usable=[r for r in subset if training_labels[r['sample_id']]['food_code'] in pi[r['sample_id']]['final_codes']
                    and pi[r['sample_id']]['conditional'] is not None
                    and not pi[r['sample_id']]['conditional']['fallback']]
            groups={r['group_id'] for r in usable}
            info.update(usable_Exact_groups=len(groups),factor=1.0 if len(groups)<5 else _fit_factor(
                [pi[r['sample_id']]['conditional']['continuous_grams'] for r in usable],
                [training_labels[r['sample_id']]['truth']['weight'] for r in usable]))
        parameters[ds]=info
    return parameters


def full_development_parameters(rows,labels,selected_profile_records,catalog,*,
                                selected_profile,selection_confirmed):
    """Fit once AFTER method selection; caller stores this separate fit artifact.

    Supply the selected arm's uncalibrated inference projections, not previously
    transformed OOF predictions. This helper is never called by score(). It is
    development-only and grants no inference or independent acceptance action.
    """
    require(selection_confirmed is True and selected_profile in PROFILES,
            'completed_method_selection_required')
    require(all(p.get('profile')==selected_profile and 'postscore_derivation' not in p
                for p in selected_profile_records),'uncalibrated_selected_arm_required')
    params=fit_outer_parameters(rows,labels,selected_profile_records,catalog)
    return {'scope':'selected_method_full_development_fit_not_independent_acceptance',
        'selected_profile':selected_profile,'parameters':params,
        'grants_inference_or_acceptance':False}


def _apply(pred,params,catalog,calibrate):
    out=deepcopy(pred);ds=pred['dataset'];info=params[ds]
    if 'prediction_sha256' in out:out['inference_prediction_sha256']=out.pop('prediction_sha256')
    out['postscore_derivation']='bounded_shrunk_OOF' if calibrate else 'fold_fallback_verified_raw'
    if out['fallback']:
        out['prediction']=dict(info['fallback']);out['e2e']['prediction']=dict(info['fallback'])
    elif calibrate and ds=='nutrition5k':
        out['prediction']={k:out['prediction'][k]*info['factors'][k] for k in metrics.KEYS}
        out['e2e']['prediction']=dict(out['prediction'])
    branch=out.get('conditional')
    if ds=='asa24' and branch is not None:
        code=branch['code'];options=catalog['asa_options'][code]
        option=metrics.median_option(options) if branch['fallback'] else metrics.nearest_option(
            branch['continuous_grams']*(info['factor'] if calibrate else 1),options)
        branch.update(option_id=option['option_id'],prediction=metrics.option_prediction(option,catalog['foods'][code]['density']))
    out['postscore_prediction_sha256']=sha(encoded(out['prediction']))
    return out


def crossvalidate(rows,labels,predictions,catalog,*,calibrate):
    """Outer-fold parameters never see query labels, including fallback paths."""
    metrics._training(rows,labels);pi=metrics._index(predictions,'P predictions')
    output={};parameters=[]
    for fold in sorted({r['fold'] for r in rows}):
        train=[r for r in rows if r['fold']!=fold];hold=[r for r in rows if r['fold']==fold]
        require(all(any(r['dataset']==ds for r in train) for ds in metrics.DATASETS),'outer_training_dataset_required')
        params=fit_outer_parameters(train,{r['sample_id']:labels[r['sample_id']] for r in train},
            [pi[r['sample_id']] for r in train],catalog)
        parameters.append({'heldout_fold':fold,'parameters':params})
        for row in hold:output[row['sample_id']]=_apply(pi[row['sample_id']],params,catalog,calibrate)
    return [output[r['sample_id']] for r in rows],parameters


def decision(scores):
    checks=scores['checks'];require(len(checks)==20,'twenty_P_checks_required')
    failed={ds:sum(not c['pass'] for c in checks if c['dataset']==ds) for ds in metrics.DATASETS}
    asa=scores['datasets']['asa24'];n=asa['n'];floor15=(15*n+99)//100;target18=(18*n+99)//100
    guard=n>0 and asa['exact_n']>=floor15 and asa['exact_groups']>=5
    finite=all(c['value'] is not None and math.isfinite(c['value']) for c in checks)
    return {'strict20':all(c['pass'] for c in checks),'failed_checks':failed,
        'development_tolerance':finite and guard and all(n<=2 for n in failed.values()),
        'recognition15_and5groups':guard,'minimum_15_percent_n':floor15,
        'original_18_percent_n':target18,'original_18_percent_pass':asa['exact_n']>=target18 if n else False}


def retain_calibration(raw,calibrated):
    old=[c['value']/c['threshold'] if c['value'] is not None else math.inf for c in raw['checks']]
    new=[c['value']/c['threshold'] if c['value'] is not None else math.inf for c in calibrated['checks']]
    return max(new)<max(old) and not any(a<=1<b for a,b in zip(old,new))


def _density_primary_recognition(rows,labels,predictions,strata):
    """Separate post-D primary report; common coding/Exact and guards unchanged.

    Every ASA row stays in each denominator. Missing D code is an unavailable
    failure, not an omitted observation. Quantity failure does not erase an
    otherwise authenticated successful density choice.
    """
    pi=metrics._index(predictions,'density primary predictions');private=[]
    for row in rows:
        if row['dataset']!='asa24':continue
        sid=row['sample_id'];pred=pi[sid];match=pred.get('match') or {}
        code=pred.get('density_primary_code',match.get('reported_primary_code'))
        if 'reported_primary_code' in match:
            require(code==match['reported_primary_code'],'density_reported_primary_binding_changed')
        require(code is None or metrics._code(code) and code in pred['final_codes'],
                'density_primary_outside_common_code_set')
        provenance=pred.get('provenance') or {}
        density_status=(provenance.get('stage_statuses') or {}).get('density')
        identity_failed=provenance.get('identity_status')=='failed'
        require(not (identity_failed or density_status=='failed') or code is None,
                'failed_density_contains_reported_primary')
        available=code is not None
        reason=(None if available else 'identity_failed' if identity_failed else
                'density_stage_failed' if density_status=='failed' else 'density_selected_code_unavailable')
        private.append({'sample_id':sid,'original_primary_code':pred.get('primary_code'),
            'density_reported_primary_code':code,'reference_code':labels[sid]['food_code'],
            'available':available,'density_stage_status':density_status,'unavailable_reason':reason,
            'first_match':available and code==labels[sid]['food_code'],
            'common_Exact':labels[sid]['food_code'] in pred['final_codes'],
            'size':str(labels[sid].get('size','unknown')),
            'stratum':strata[sid] if strata is not None else None})
    def aggregate(entries):
        n=len(entries);hits=sum(r['first_match'] for r in entries)
        available=sum(r['available'] for r in entries)
        return {'n':n,'first_n':hits,'first_rate':hits/n if n else None,
            'available_n':available,'unavailable_n':n-available,
            'unavailable_rate':(n-available)/n if n else None,
            'common_Exact_n':sum(r['common_Exact'] for r in entries),
            'unavailable_reason_counts':{reason:sum(r['unavailable_reason']==reason for r in entries)
                for reason in sorted({r['unavailable_reason'] for r in entries if not r['available']})},
            'changed_primary_n':sum(r['available'] and r['density_reported_primary_code']!=r['original_primary_code']
                                    for r in entries)}
    return {'scope':'separate_density_selected_primary_not_common_coding_guard',
        **aggregate(private),'by_size':{size:aggregate([r for r in private if r['size']==size])
            for size in sorted({r['size'] for r in private})},
        'by_stratum':{name:aggregate([r for r in private if r['stratum']==name])
            for name in sorted({r['stratum'] for r in private})} if strata is not None else {},
        'code_identity_private':private}


def score(rows,labels,records,catalog,*,strata=None,bootstrap=2000):
    """Caller supplies only post-seal authenticated completed records; no replay.

    Select one coherent profile and one whole postprocessor, never dataset/target
    splices. No full-development final fit is performed by this function.
    """
    predictions=_prepare(rows,labels,records,catalog,strata);reports={};candidates=[]
    for index,profile in enumerate(PROFILES):
        raw,rawparams=crossvalidate(rows,labels,predictions[profile],catalog,calibrate=False)
        calibrated,params=crossvalidate(rows,labels,predictions[profile],catalog,calibrate=True)
        rm=metrics.evaluate(rows,labels,raw,bootstrap=bootstrap,seed=20261104)
        cm=metrics.evaluate(rows,labels,calibrated,bootstrap=bootstrap,seed=20261104)
        keep=retain_calibration(rm,cm);selected=calibrated if keep else raw;chosen=cm if keep else rm
        subsets={}
        if strata:
            for name in sorted(set(strata.values())):
                subset=[r for r in rows if strata[r['sample_id']]==name];ids={r['sample_id'] for r in subset}
                subsets[name]=metrics.evaluate(subset,{s:labels[s] for s in ids},
                    [p for p in selected if p['sample_id'] in ids],bootstrap=bootstrap,seed=20261104)
        baselines={}
        for ds in metrics.DATASETS:
            population=[r for r in rows if r['dataset']==ds]
            baselines[ds+'_all_row_fold_median']=metrics._stats([labels[r['sample_id']] for r in population],
                [metrics.fold_medians(rows,labels,r['fold'],ds) for r in population],ds)
        exact=[r for r in rows if r['dataset']=='asa24' and labels[r['sample_id']]['food_code'] in
               predictions[profile][rows.index(r)]['final_codes']]
        baselines['asa_Exact_legal_median']=metrics._stats([labels[r['sample_id']] for r in exact],
            [metrics.option_prediction(metrics.median_option(catalog['asa_options'][labels[r['sample_id']]['food_code']]),
                catalog['foods'][labels[r['sample_id']]['food_code']]['density']) for r in exact],'asa24')
        reports[profile]={'raw':rm,'raw_decision':decision(rm),'calibrated':cm,
            'calibration_retained':keep,'selected_postprocessor':'bounded_shrunk' if keep else 'raw',
            'selected':chosen,'decision':decision(chosen),'fold_parameters':params,
            'strata':subsets,'baselines':baselines,'selected_predictions_private':selected,
            'conditional_success':{'common_Exact_n':len(exact),
                **{status+'_n':sum((by['conditional'] or {}).get('status')==status for by in predictions[profile]
                    if by['sample_id'] in {r['sample_id'] for r in exact}) for status in ('native','repaired','fallback')},
                **{status+'_rate':sum((by['conditional'] or {}).get('status')==status for by in predictions[profile]
                    if by['sample_id'] in {r['sample_id'] for r in exact})/len(exact) if exact else None
                   for status in ('native','repaired','fallback')}}}
        if profile in ('D','Q+D'):
            reports[profile]['density_selected_primary_recognition']=_density_primary_recognition(
                rows,labels,predictions[profile],strata)
        q=[v for ds in metrics.DATASETS for v in ratios(chosen,ds)]
        eligible=decision(chosen)['development_tolerance']
        method_calls={'O':1,'Q':1,'D':2,'Q+D':2}[profile]
        reports[profile]['registered_quantity_density_stage_calls']=method_calls
        candidates.append((not eligible,max(q),sum(q)/len(q),method_calls,index,profile))
    # Shared ASA conditional is an invariant through both raw and calibrated fits.
    asa_params=[[f['parameters']['asa24'] for f in reports[p]['fold_parameters']] for p in PROFILES]
    require(all(v==asa_params[0] for v in asa_params),'shared_ASA_calibration_source_changed')
    best=min(candidates);winner=best[-1] if not best[0] else None
    return {'scope':'P_complete_development_OOF_not_independent_acceptance','profiles':reports,
        'selected_profile':winner,'gap_ranked_profile':best[-1],
        'selection_rule':'eligible_worst_unrounded_ratio_mean_fixed_call_complexity_order',
        'full_development_final_fit_performed':False,'api_calls':0,
        'independent_acceptance_success':False,'grants_inference_or_acceptance':False}
