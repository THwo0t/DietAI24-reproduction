#!/usr/bin/env python3
"""Separate post-score algebra/accounting audit; never fit or predict."""
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys
from types import SimpleNamespace

sys.dont_write_bytecode=True
BASE=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(BASE),str(BASE/'src'),str(BASE/'round7/src'),str(BASE/'round8/src'),
              str(BASE/'round7/tools'),str(BASE/'round10')]
from opt_provider import ROOT,sha,fingerprint
from opt_metrics import evaluate
from opt_pipeline import nearest_option
from round4.src.artifacts import ArtifactStore,decode
from diagnose_completed_m import errors,mass_density,require,close
from context_o import ROUND,source_pins
from stores_o import identity_store,final_store,name
from scoring_o import public_summary
from source_portions import SourcePortionPipeline
from records_o import coding_snapshot

SCOPE='posthoc_O_development_accounting_diagnostic_not_selection_or_acceptance'


def prerequisites(directory):
    for relative in ('prepared/freeze.json','runs/identities/completion.json',
                     'runs/development/completion.json','runs/verification.json',
                     'runs/scoring/completion.json','development_checkpoint.json',
                     'launch/automatic_followup.json'):
        path=directory/relative
        require(path.is_file() and not path.is_symlink(),'O_complete_scored_batch_required')
    status=decode((directory/'launch/automatic_followup.json').read_bytes())
    require(status.get('status')=='development_scored','O_offline_followup_incomplete')
    verified=decode((directory/'runs/verification.json').read_bytes())
    require(verified.get('completed_replay') is True and verified.get('provider_constructed') is False
            and verified.get('records')==183
            and verified.get('completion_sha256')==sha(directory/'runs/development/completion.json')
            and verified.get('freeze_sha256')==sha(directory/'prepared/freeze.json'),
            'O_zero_Provider_verification_required')


def physical_audit(rows,identities,records,catalog):
    pipeline=SourcePortionPipeline(None,None,catalog,None)
    out={}
    for ds in ('asa24','nutrition5k'):
        counts=Counter();mass=Counter();conflicts=0;item_counts=Counter();multi_primary=0
        population=[r for r in rows if r['dataset']==ds]
        for row in population:
            sid=row['sample_id'];record=records[sid];identity=identities[sid]
            require(record['coding']==coding_snapshot(identity),'O_diagnostic_identity_changed')
            if identity.get('status')=='ok':
                items=pipeline.checked_items(identity,ds);item_counts[len(items)]+=1
                multi_primary+=len({i['primary_code'] for i in items})<len(items)
            if record['fallback']:continue
            context=pipeline.portion_context(identity,ds)
            conflicts+=sum(len(item['excluded_unit_conflicts']) for item in context)
            choices=record['portion_result']['portions'];raw=[]
            for choice in choices:
                keys={'standard':('item_id','mode','option_id'),
                      'adjusted':('item_id','mode','no_standard_fit','unit_id','count'),
                      'grams':('item_id','mode','grams')}[choice['mode']]
                raw.append({k:choice[k] for k in keys})
                counts[choice['mode']]+=1;mass[choice['mode']]+=choice['grams']
            replay=pipeline.parse_quantities(json.dumps({'items':raw}),identity,ds,context)
            for k in ('prediction','raw_prediction','raw_leaves','portions'):
                require(replay[k]==record['portion_result'][k],'O_diagnostic_quantity_mapping_changed')
            require(replay['prediction']==record['prediction']==record['e2e']['prediction']
                    and replay['raw_leaves']==record['raw_leaves'],'O_diagnostic_main_aggregation_changed')
        total=sum(mass.values())
        out[ds]={'population_n':len(population),'complete_n':sum(not records[r['sample_id']]['fallback'] for r in population),
            'physical_item_counts_on_successful_identities':{str(k):v for k,v in item_counts.items()},'mode_item_counts':dict(counts),
            'mode_grams':dict(mass),'mode_mass_fractions':{k:v/total for k,v in mass.items()} if total else {},
            'excluded_canonical_unit_conflicts':conflicts,'multiple_items_sharing_primary_code_n':multi_primary,
            'mapping_or_join_inconsistencies':0,
            'limitation':'Shared codes can represent separate visible items; no annotated omission/duplication rate is available.'}
    return out


def conditional_projection(rows,labels,records,saved):
    exact=[r for r in rows if r['dataset']=='asa24'
           and labels[r['sample_id']]['food_code'] in records[r['sample_id']]['final_codes']]
    continuous=[];mapped=[];moves=[];fallbacks=0
    for row in exact:
        branch=records[row['sample_id']]['conditional']
        if branch['fallback']:fallbacks+=1;continue
        grams=branch['continuous_grams'];option=nearest_option(branch['options'],grams)
        require(option['option_id']==branch['option_id'],'O_raw_conditional_projection_changed')
        truth=labels[row['sample_id']]['truth']['weight']
        continuous.append(abs(grams-truth));mapped.append(abs(option['grams']-truth))
        moves.append(abs(option['grams']-grams))
    n=len(continuous)
    return {'fixed_Exact_n':len(exact),'fixed_Exact_groups':len({r['group_id'] for r in exact}),
        'native_or_repaired_continuous_n':n,'fallback_n':fallbacks,
        'continuous_weight_mae_on_nonfallback_Exact':sum(continuous)/n if n else None,
        'legal_option_weight_mae_on_same_nonfallback_Exact':sum(mapped)/n if n else None,
        'mean_absolute_legal_projection_move':sum(moves)/n if n else None,
        'projection_improved_n':sum(b<a for a,b in zip(continuous,mapped)),
        'projection_worsened_n':sum(b>a for a,b in zip(continuous,mapped)),
        'official_primary_includes_fallbacks':saved['primary'],
        'limitation':'Continuous values are diagnostic only; final legal options remain the primary task.'}


def run(before_labels=None):
    prerequisites(ROUND)  # No query-label open or hash until all gates pass.
    require(not (ROUND/'diagnostics/completed_o/completion.json').exists(),'O_diagnostic_already_completed')
    inputs={}
    def read(relative):
        path=ROOT/relative
        require(path.resolve()==path and not path.is_symlink(),'O_diagnostic_symlink')
        raw=path.read_bytes();digest=hashlib.sha256(raw).hexdigest()
        require(relative not in inputs or inputs[relative]==digest,'O_diagnostic_input_changed')
        inputs[relative]=digest
        return decode(raw)
    frozen=read('round10/prepared/freeze.json')
    def sources_unchanged():
        return source_pins()==frozen['source_files'] and sha(ROUND/'REVIEW.md')==frozen['review_sha256']
    require(sources_unchanged(),'O_diagnostic_frozen_source_changed')
    prepared=read('round10/prepared/common.json');rows=prepared['rows']
    require(inputs['round10/prepared/common.json']==frozen['prepared_sha256']
            and fingerprint(rows)==frozen['rows_sha256']
            and Counter(r['dataset'] for r in rows)=={'asa24':99,'nutrition5k':84}
            and len({r['sample_id'] for r in rows})==183,'O_diagnostic_both_complete_cohorts_required')
    ctx=SimpleNamespace(binding=frozen,rows=rows,verify_sources=sources_unchanged)
    sealed=final_store(ctx).verify_completed();identity=identity_store(ctx).verify_completed()
    completion=read('round10/runs/development/completion.json')
    score_binding={'science':frozen,'completion_sha256':sha(ROUND/'runs/development/completion.json')}
    scored=ArtifactStore(ROUND/'runs/scoring',score_binding,['results','OOF_predictions'],
                        verify_sources=sources_unchanged,root=ROUND).verify_completed()
    result=scored['results'];checkpoint=read('round10/development_checkpoint.json')
    require(checkpoint==public_summary(result),'O_diagnostic_score_outputs_disagree')
    read('round10/runs/scoring/completion.json');read('round10/runs/verification.json')
    records={r['sample_id']:sealed[name('record',r)] for r in rows}
    identities={r['sample_id']:identity[name('identity',r)] for r in rows}
    selected={r['sample_id']:r for r in scored['OOF_predictions']}
    require(set(selected)==set(records),'O_diagnostic_selected_population_changed')
    catalog=read('data/catalog.json')
    require(inputs['data/catalog.json']==prepared['catalog_sha256'],'O_diagnostic_catalog_changed')
    # The full score, independent replay and immutable stores are established.
    if before_labels is not None:before_labels()
    labels=read('data/cohorts/dev_labels.json')
    require(inputs['data/cohorts/dev_labels.json']==frozen['labels_sha256'] and set(labels)==set(records),
            'O_diagnostic_labels_changed')
    out={'scope':SCOPE,'api_calls':0,'validation_opened':False,'new_fit_or_selection':False,
         'new_bootstrap_replicates':0,'existing_selection':result['selection'],'arms':{}}
    for arm,index in [('raw',records),('OOF_mass',selected)]:
        point=evaluate(rows,labels,[index[r['sample_id']] for r in rows],bootstrap=0)
        saved=result[arm]['metrics']
        for actual,expected in zip(point['checks'],saved['checks']):
            require(actual['pass']==expected['pass'] and close(actual['value'],expected['value']),
                    'O_diagnostic_point_check_changed')
        arm_out={}
        for ds in ('asa24','nutrition5k'):
            population=[r for r in rows if r['dataset']==ds]
            exact=[r for r in population if ds=='nutrition5k'
                   or labels[r['sample_id']]['food_code'] in index[r['sample_id']]['final_codes']]
            full={sid:p['prediction'] for sid,p in index.items()}
            primary={r['sample_id']:(index[r['sample_id']]['conditional']['prediction'] if ds=='asa24'
                                    else index[r['sample_id']]['prediction']) for r in exact}
            arm_out[ds]={'primary':errors(exact,labels,primary,saved['datasets'][ds]['primary']),
                'full_serving':errors(population,labels,full,
                    saved['datasets'][ds]['e2e'] if ds=='asa24' else saved['datasets'][ds]['primary']),
                'mass_density_identity':mass_density(population,labels,full)}
        out['arms'][arm]=arm_out
    out['physical_accounting']=physical_audit(rows,identities,records,catalog)
    out['ASA_raw_projection']=conditional_projection(rows,labels,records,result['raw']['metrics']['datasets']['asa24'])
    out['limitations']=['Algebraic mass/density terms are not additive MAE shares or causal ingredient errors.',
        'Total mass discrepancy can include omitted or duplicated foods; it is not pure portion error.',
        'Whole-dish density discrepancy cannot isolate code, recipe, water or FNDDS causes.',
        'Repeated development diagnostics are not independent validation. No oracle weights are used.']
    helper=ROOT/'round7/tools/diagnose_completed_m.py'
    binding={'scope':SCOPE,'inputs':inputs,'source_sha256':sha(Path(__file__)),'helper_sha256':sha(helper)}
    def unchanged():
        return sources_unchanged() and sha(Path(__file__))==binding['source_sha256'] \
            and sha(helper)==binding['helper_sha256'] and all(sha(ROOT/k)==v for k,v in inputs.items())
    require(unchanged() and final_store(ctx).verify_completed()==sealed,'O_diagnostic_input_mutated')
    out['provenance_sha256']={'inputs':fingerprint(inputs),'source':binding['source_sha256'],
                               'helper':binding['helper_sha256']}
    store=ArtifactStore(ROUND/'diagnostics/completed_o',binding,['aggregate'],verify_sources=unchanged,root=ROUND)
    store.finalize({'aggregate':out})
    require(store.verify_completed()=={'aggregate':out},'O_diagnostic_seal_failed')
    return out


if __name__=='__main__':
    try:
        run();print(json.dumps({'status':'O_postscore_diagnostic_completed','api_calls':0,'validation_opened':False}))
    except Exception as exc:
        print(json.dumps({'status':'O_postscore_diagnostic_refused','error_type':type(exc).__name__}))
        raise SystemExit(1)
