"""Post-completion development comparison; no fitting or provider imports.

This script refuses to open labels before both new profiles and summary seal.
Only comparison.json is written; frozen prediction/scoring files stay unchanged.
"""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import statistics

HERE = Path(__file__).resolve().parent
V2 = HERE.parent
OLD = V2 / 'cj_full_20261104'
KEYS = ('weight', 'energy', 'fat', 'carbs', 'protein')


def load(path):
    return json.loads(Path(path).read_text())


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def fingerprint(value):
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,
        separators=(',', ':'),allow_nan=False).encode()).hexdigest()


def indexed(value):
    if isinstance(value, dict):
        value = value['predictions']
    result = {r['sample_id']: r for r in value}
    if len(result) != len(value):
        raise ValueError('duplicate_prediction_id')
    return result


def stats(ids, records, labels, conditional=False):
    output = {}
    for key in KEYS:
        true = [labels[s]['truth'][key] for s in ids]
        predicted = [(records[s]['conditional']['prediction'] if conditional else records[s]['prediction'])[key] for s in ids]
        mean = statistics.mean(true) if true else None
        mae = statistics.mean(abs(a-b) for a,b in zip(true,predicted)) if true else None
        output[key] = dict(mae=mae, reference_mean=mean,
            per_unit=mae/mean if mean is not None and mean>0 else None)
    return dict(n=len(ids), metrics=output)


def paired(ids, new, old, labels):
    result = {}
    for key in KEYS:
        changes = [abs(new[s]['prediction'][key]-labels[s]['truth'][key])-
                   abs(old[s]['prediction'][key]-labels[s]['truth'][key]) for s in ids]
        result[key] = dict(new_minus_old_mae=statistics.mean(changes),
            improved_n=sum(x < -1e-9 for x in changes), worse_n=sum(x > 1e-9 for x in changes),
            tied_n=sum(abs(x)<=1e-9 for x in changes))
    return result


def counts(records):
    return {key:sum(bool(r.get(key)) for r in records.values())
        for key in ('fallback','method_fallback','repair_used','native_complete')}


def main():
    # Do not move a label read above this barrier.
    summary_path = HERE / 'summary.json'
    if not summary_path.is_file():
        raise ValueError('new_summary_required_before_comparison')
    frozen = fingerprint(load(HERE / 'freeze.json'))
    summary = load(summary_path)
    if summary.get('freeze_sha256') != frozen:
        raise ValueError('new_summary_freeze_changed')
    new = {}
    sources = {}
    for profile, count in (('N5',314),('ASA',529)):
        path = HERE / 'run' / profile / 'records.json'
        seal = load(path.with_name('completion.json'))
        if (seal.get('profile') != profile or seal.get('records') != count
                or seal.get('freeze_sha256') != frozen or seal.get('records_sha256') != sha(path)):
            raise ValueError('complete_new_prediction_seals_required')
        records = indexed(load(path))
        if len(records) != count:
            raise ValueError('complete_new_prediction_population_required')
        new[profile] = records
        sources[str(path.relative_to(V2))] = sha(path)
    for name in ('N5_calibrated_oof.json','ASA_calibrated_oof.json'):
        path = HERE / name
        if not path.is_file():
            raise ValueError('new_oof_scoring_required')
        sources[str(path.relative_to(V2))] = sha(path)
    rows = load(V2 / 'round11/prepared/cohort/dev.json')
    labels_path = V2 / 'round11/prepared/cohort/dev_labels.json'
    # All records are completed and scored; labels are opened only here.
    labels = load(labels_path)
    manifest = {r['sample_id']:r for r in rows}
    for profile, dataset in (('N5','nutrition5k'),('ASA','asa24')):
        expected = {s for s,r in manifest.items() if r['dataset']==dataset}
        if set(new[profile]) != expected:
            raise ValueError('new_prediction_cohort_changed')
        for sid,r in new[profile].items():
            if any(r[k]!=manifest[sid][k] for k in ('dataset','group_id','fold')):
                raise ValueError('new_prediction_group_or_fold_changed')
    new_n5_cal = indexed(load(HERE / 'N5_calibrated_oof.json'))
    new_asa_cal = indexed(load(HERE / 'ASA_calibrated_oof.json'))
    old_n5 = indexed(load(OLD / 'run/C/records.json'))
    old_n5_cal = indexed(load(OLD / 'C_calibrated_oof.json'))
    adopted_path = OLD / 'retained_asa_full_correction_20261104/ASA_predictions.json'
    old_asa_adopted = indexed(load(adopted_path))
    if set(new_n5_cal)!=set(new['N5']) or set(old_n5)!=set(new['N5']) or set(old_n5_cal)!=set(new['N5']):
        raise ValueError('paired_N5_population_must_be_identical')
    if set(new_asa_cal)!=set(new['ASA']) or set(old_asa_adopted)!=set(new['ASA']):
        raise ValueError('ASA_population_must_be_identical_before_Exact_selection')
    exact=lambda rs:{s for s,r in rs.items() if labels[s]['food_code'] in r.get('final_codes',[])}
    new_exact,old_exact=exact(new['ASA']),exact(old_asa_adopted)
    intersection=sorted(new_exact & old_exact)
    for records in (new['ASA'],new_asa_cal,old_asa_adopted):
        for sid in exact(records):
            branch=records[sid].get('conditional')
            if not isinstance(branch,dict) or branch.get('code')!=labels[sid]['food_code'] or branch.get('prediction') is None:
                raise ValueError('Exact_requires_explicit_conditional_prediction')
    n5_ids=sorted(new['N5'])
    n5_comparisons={}
    for nn,nr in (('new_raw',new['N5']),('new_retained',new_n5_cal)):
        for on,orr in (('previous_C_raw',old_n5),('previous_C_calibrated',old_n5_cal)):
            n5_comparisons[nn+'_vs_'+on]=paired(n5_ids,nr,orr,labels)
    old_summary=load(OLD/'retained_asa_full_correction_20261104/summary.json')
    result=dict(scope='development_only; no_refit_no_API_no_independent_acceptance',
        N5_same_314_paired=n5_comparisons,
        N5_metrics={name:stats(n5_ids,records,labels) for name,records in (
            ('new_raw',new['N5']),('new_retained',new_n5_cal),('previous_C_raw',old_n5),('previous_C_calibrated',old_n5_cal))},
        ASA=dict(total_n=529,new_exact_n=len(new_exact),previous_exact_n=len(old_exact),
            new_exact_rate=len(new_exact)/529,previous_exact_rate=len(old_exact)/529,
            Exact_intersection_n=len(intersection),new_only_Exact_n=len(new_exact-old_exact),
            previous_only_Exact_n=len(old_exact-new_exact),
            full_population_warning='Each method conditional MAE uses its OWN Exact set; only intersection below is paired.',
            own_Exact=dict(new_raw=stats(sorted(new_exact),new['ASA'],labels,True),
                new_retained=stats(sorted(new_exact),new_asa_cal,labels,True),
                previous_adopted_full_correction=stats(sorted(old_exact),old_asa_adopted,labels,True)),
            same_Exact_intersection=dict(new_raw=stats(intersection,new['ASA'],labels,True),
                new_retained=stats(intersection,new_asa_cal,labels,True),
                previous_adopted_full_correction=stats(intersection,old_asa_adopted,labels,True)),
            previous_adoption_status=old_summary.get('status')),
        current_raw_and_retained_20=summary['profiles'],
        counts=dict(N5=counts(new['N5']),ASA=counts(new['ASA'])),
        usage=summary.get('usage'),independent_acceptance_opened=False,
        source_sha256={**sources,str(summary_path.relative_to(V2)):sha(summary_path),
            str(adopted_path.relative_to(V2)):sha(adopted_path),str(labels_path.relative_to(V2)):sha(labels_path)})
    output=HERE/'comparison.json'
    raw=(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+'\n').encode()
    if output.exists() and output.read_bytes()!=raw:
        raise ValueError('existing_comparison_is_immutable')
    if not output.exists():output.write_bytes(raw)
    print(json.dumps(dict(status='comparison_complete',N5_n=314,ASA_n=529,Exact_intersection_n=len(intersection))))


if __name__=='__main__':main()
