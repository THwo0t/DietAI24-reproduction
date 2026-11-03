"""Post-seal alternative-aware option scoring; never called by N inference."""
from copy import deepcopy
from opt_metrics import evaluate, nearest_option, median_option, option_prediction
from scoring_m import tolerance
from records_n import validate_leaves

PROFILES = ('N-density','N-units')


def adapt_asa(rows, labels, core_records, catalog):
    by_id = {p['sample_id']:deepcopy(p) for p in core_records}
    if len(by_id) != len(core_records) or set(by_id) != {r['sample_id'] for r in rows}:
        raise ValueError('N_score_population_changed')
    for row in rows:
        pred = by_id[row['sample_id']]
        if row['dataset'] != 'asa24': continue
        code = labels[row['sample_id']]['food_code']
        if code not in pred['final_codes']: continue
        options, density = catalog['asa_options'][code], catalog['foods'][code]['density']
        grams = None
        if not pred['fallback']:
            # Full successful leaf/alternative/density join is checked again,
            # independently of the query's code and legal options.
            identity = {'status':pred['identity_status'],'leaves':pred['items']}
            validate_leaves(identity,{'raw_leaves':pred['raw_leaves'],'prediction':pred['prediction']})
            grams = sum(p['grams'] for p in pred['raw_leaves'] if code in p['codes'])
            if grams <= 0: raise ValueError('N_exact_code_without_physical_mass')
        option = median_option(options) if grams is None else nearest_option(grams,options)
        pred['conditional'] = {'code':code,'option_id':option['option_id'],'continuous_grams':grams,
            'fallback':grams is None,'prediction':option_prediction(option,density)}
    return [by_id[r['sample_id']] for r in rows]


def score(rows, labels, records, catalog, bootstrap=10000):
    predictions = adapt_asa(rows,labels,records,catalog)
    result = evaluate(rows,labels,predictions,bootstrap=bootstrap,seed=20261102)
    return {'metrics':result,'tolerance':tolerance(result),'predictions':predictions}


def shared_identity(records):
    if set(records) != set(PROFILES): raise ValueError('N_two_complete_profiles_required')
    by_profile = {name:{r['sample_id']:r for r in records[name]} for name in PROFILES}
    a,b = (by_profile[name] for name in PROFILES)
    if set(a) != set(b) or any(len(by_profile[n]) != len(records[n]) for n in PROFILES):
        raise ValueError('N_paired_population_changed')
    for sid in a:
        fields = ('dataset','group_id','fold','identity_sha256','coding','final_codes','primary_code')
        if any(a[sid][key] != b[sid][key] for key in fields): raise ValueError('N_shared_identity_changed')
    return True


def select(results):
    if set(results) != set(PROFILES): raise ValueError('N_complete_profile_results_required')
    eligible = [n for n in PROFILES if results[n]['tolerance']['recognition_guard_pass']
                and results[n]['tolerance']['rank'] is not None]
    if not eligible: return {'selected':None,'accepted':False,'reason':'no_defined_guarded_profile'}
    name = min(eligible,key=lambda n:(*results[n]['tolerance']['rank'],PROFILES.index(n)))
    return {'selected':name,'accepted':results[name]['tolerance']['accepted'],
            'reason':'one_shared_profile_ranked_on_both_complete_datasets'}
