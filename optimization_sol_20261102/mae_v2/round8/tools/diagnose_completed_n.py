#!/usr/bin/env python3
"""Post-seal N mechanism/error diagnostic; no inference, selection or bootstrap."""
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys

BASE=Path(__file__).resolve().parents[2]
sys.dont_write_bytecode=True
sys.path[:0]=[str(BASE),str(BASE/'src'),str(BASE/'round7/src'),str(BASE/'round8/src'),str(BASE/'round7/tools')]
# These helpers are pure arithmetic/guard functions; neither M.run nor its
# label-reading diagnostic entry is invoked. Both helper sources are bound.
from diagnose_completed_m import errors,mass_density,paired,require,require_scored,close
from opt_provider import ROOT,fingerprint,sha
from round4.src.artifacts import ArtifactStore,decode
from context_n import ROUND,source_pins
from run_n import record_name
from scoring_n import adapt_asa,shared_identity,PROFILES
from scoring_m import adapt_asa as adapt_m0

TARGETS=('weight','energy','fat','carbs','protein')
SCOPE='posthoc_N_development_diagnostic_not_selection_or_acceptance'


def paired_named(rows,labels,baseline,candidate,a,b):
    out=paired(rows,labels,baseline,candidate)
    out['direction']=b+'_absolute_error_minus_'+a+'_absolute_error'
    return out


def physical_changes(rows,baseline,candidate,mode):
    require(mode in ('density','quantity'),'unknown_physical_comparison')
    result={'population_n':len(rows),'both_complete_n':0,'fallback_pairs_n':0,
            'changed_weight_n':0,'changed_code_lists_n':0,'max_nutrient_identity_residual':0.0}
    ratios=[]
    for row in rows:
        sid=row['sample_id']; a,b=baseline[sid],candidate[sid]
        if a['fallback'] or b['fallback']:
            result['fallback_pairs_n']+=1;continue
        aa={p['component_id']:p for p in a['raw_leaves']}
        bb={p['component_id']:p for p in b['raw_leaves']}
        require(len(aa)==len(a['raw_leaves']) and len(bb)==len(b['raw_leaves']) and set(aa)==set(bb),
                'physical_leaf_population_changed')
        result['both_complete_n']+=1
        result['changed_weight_n']+=a['prediction']['weight']!=b['prediction']['weight']
        ratios.append(b['prediction']['weight']/a['prediction']['weight'])
        changed=False
        for cid in aa:
            require(aa[cid]['parent_id']==bb[cid]['parent_id'],'physical_parent_join_changed')
            ac=aa[cid].get('codes',[aa[cid]['code']]);bc=bb[cid].get('codes',[bb[cid]['code']])
            changed|=ac!=bc
            if mode=='density': require(aa[cid]['grams']==bb[cid]['grams'],'N_density_mass_not_fixed')
            else: require(ac==bc and aa[cid]['density']==bb[cid]['density'],'N_units_identity_or_density_changed')
        result['changed_code_lists_n']+=changed
        for k in TARGETS[1:]:
            if mode=='density':
                expected=sum(aa[c]['grams']*((bb[c]['density'][k]-aa[c]['density'][k])/100) for c in aa)
            else:
                expected=sum((bb[c]['grams']-aa[c]['grams'])*(aa[c]['density'][k]/100) for c in aa)
            actual=b['prediction'][k]-a['prediction'][k]
            require(close(expected,actual),'physical_nutrition_difference_identity_failed')
            result['max_nutrient_identity_residual']=max(result['max_nutrient_identity_residual'],abs(expected-actual))
    result['mean_predicted_mass_ratio_on_complete_pairs']=sum(ratios)/len(ratios) if ratios else None
    result['interpretation']=('fixed-mass identity and alternative-density intervention; not isolated averaging'
        if mode=='density' else 'same-identity quantity-path intervention, including direct mode; not unit-only causality')
    return result


def run():
    require_scored(ROUND) # Must precede every label open, including hash checks.
    inputs={}
    def read(relative):
        path=ROOT/relative
        require(path.resolve()==path and not path.is_symlink(),'diagnostic_symlink_rejected')
        raw=path.read_bytes();digest=hashlib.sha256(raw).hexdigest()
        require(relative not in inputs or inputs[relative]==digest,'diagnostic_input_changed')
        inputs[relative]=digest
        return decode(raw)
    frozen=read('round8/prepared/freeze.json')
    require(source_pins()==frozen['source_files'] and sha(ROUND/'REVIEW.md')==frozen['review_sha256'],
            'N_frozen_source_or_review_changed')
    rows=[decode(line) for line in (ROOT/'data/cohorts/dev.jsonl').read_text().splitlines()]
    inputs['data/cohorts/dev.jsonl']=sha(ROOT/'data/cohorts/dev.jsonl')
    require(inputs['data/cohorts/dev.jsonl']==frozen['manifest_sha256'] and fingerprint(rows)==frozen['rows_sha256']
            and Counter(r['dataset'] for r in rows)=={'asa24':99,'nutrition5k':84},'N_full_population_required')
    store=ArtifactStore(ROUND/'runs/development',frozen,
        [record_name(p,r) for r in rows for p in PROFILES]+['service-proof'],
        verify_sources=lambda:source_pins()==frozen['source_files'],root=ROUND)
    records=store.verify_completed();read('round8/runs/development/completion.json')
    for relative,expected in records['service-proof']['files'].items():
        path=ROUND/'provider/N'/relative
        require(path.resolve()==path and sha(path)==expected,'N_completed_service_evidence_changed')
    score=read('round8/runs/scoring/results.json');checkpoint=read('round8/development_checkpoint.json')
    require(checkpoint=={k:v for k,v in score.items() if k!='service_proof'}
            and score['service_proof']==records['service-proof'],'N_scoring_outputs_disagree')
    verify_path=ROUND/'launch/automatic_verify.log'
    require(verify_path.resolve()==verify_path,'verify_log_symlink')
    verified=decode(verify_path.read_text().splitlines()[-1]);inputs['round8/launch/automatic_verify.log']=sha(verify_path)
    require(verified.get('status')=='completed' and verified.get('completed_replay') is True
            and verified.get('provider_constructed') is False and verified.get('pairs')==183
            and verified.get('service_counts')==records['service-proof']['counts'],'N_offline_replay_not_confirmed')
    by_profile={p:[records[record_name(p,r)] for r in rows] for p in PROFILES};shared_identity(by_profile)
    imported=read('round8/prepared/upstream.json')
    m0={r['sample_id']:imported['records'][r['sample_id']]['baseline_record'] for r in rows}
    # The complete base+score+follower+zero-Provider proof is now established.
    labels=read('data/cohorts/dev_labels.json')
    require(inputs['data/cohorts/dev_labels.json']==imported['fallbacks']['labels_sha256']
            and set(labels)=={r['sample_id'] for r in rows},'N_diagnostic_labels_changed')
    catalog=read('data/catalog.json');require(inputs['data/catalog.json']==frozen['catalog_sha256'],'catalog_changed')
    adapted={p:{r['sample_id']:r for r in adapt_asa(rows,labels,by_profile[p],catalog)} for p in PROFILES}
    adapted['M0']={r['sample_id']:r for r in adapt_m0(rows,labels,list(m0.values()),catalog)}
    out={'schema_version':1,'scope':SCOPE,'arms':{},'comparisons':{},'existing_selection':score['selection'],
         'existing_common_exact':score['common_exact'],'api_calls':0,'bootstrap_replicates':0,
         'validation_opened':False,'new_profile_selected':False,'row_outputs_exported':False}
    for name in PROFILES:
        arm={};index=adapted[name]
        for ds in ('asa24','nutrition5k'):
            population=[r for r in rows if r['dataset']==ds]
            exact=[r for r in population if labels[r['sample_id']]['food_code'] in index[r['sample_id']]['final_codes']] if ds=='asa24' else population
            full={sid:p['prediction'] for sid,p in index.items()}
            primary={r['sample_id']:(index[r['sample_id']]['conditional']['prediction'] if ds=='asa24'
                      else index[r['sample_id']]['prediction']) for r in exact}
            saved=score['arms'][name]['metrics']['datasets'][ds]
            arm[ds]={'primary':errors(exact,labels,primary,saved['primary']),
                'full_serving':errors(population,labels,full,saved['e2e'] if ds=='asa24' else saved['primary']),
                'mass_density_identity':mass_density(population,labels,full),
                'fallback_n':sum(index[r['sample_id']]['fallback'] for r in population),
                'new_repair_n':sum(index[r['sample_id']]['new_repair_used'] for r in population),
                'upstream_repair_n':sum(index[r['sample_id']]['upstream_identity_repaired'] for r in population),
                'imported_quantity_repair_n':sum(index[r['sample_id']]['imported_quantity_repaired'] for r in population)}
        out['arms'][name]=arm
    for a,b,mode in [('M0','N-density','density'),('N-density','N-units','quantity')]:
        comparison={}
        for ds in ('asa24','nutrition5k'):
            population=[r for r in rows if r['dataset']==ds]
            comparison[ds]={'paired_full_serving':paired_named(population,labels,
                {sid:p['prediction'] for sid,p in adapted[a].items()},
                {sid:p['prediction'] for sid,p in adapted[b].items()},a,b),
                'physical_difference_check':physical_changes(population,adapted[a],adapted[b],mode)}
            if ds=='asa24':
                cells={k:[] for k in ('both','baseline_only','candidate_only','neither')}
                for r in population:
                    sid=r['sample_id'];code=labels[sid]['food_code']
                    aa=code in adapted[a][sid]['final_codes'];bb=code in adapted[b][sid]['final_codes']
                    cells['both' if aa and bb else 'baseline_only' if aa else 'candidate_only' if bb else 'neither'].append(r)
                comparison[ds]['exact_membership']={k:{'n':len(v),'groups':len({r['group_id'] for r in v})} for k,v in cells.items()}
                comparison[ds]['paired_common_exact']=paired_named(cells['both'],labels,
                    {sid:(p.get('conditional') or {}).get('prediction') for sid,p in adapted[a].items()},
                    {sid:(p.get('conditional') or {}).get('prediction') for sid,p in adapted[b].items()},a,b)
        out['comparisons'][a+'_to_'+b]=comparison
    out['limitations']=['Repeated development comparisons are not independent validation.',
        'Conditional option and full-serving E2E populations differ; changed Exact membership is separate.',
        'Algebraic mass/density identities do not yield additive MAE or causal contributions.',
        'Fallbacks remain in every full-population score; pure intervention checks use complete paired leaves only.']
    helper=ROOT/'round7/tools/diagnose_completed_m.py'
    binding={'scope':SCOPE,'inputs':inputs,'helper_sha256':sha(helper),'source_sha256':sha(Path(__file__))}
    def unchanged():
        return (source_pins()==frozen['source_files'] and sha(helper)==binding['helper_sha256']
                and sha(Path(__file__))==binding['source_sha256'] and all(sha(ROOT/p)==h for p,h in inputs.items()))
    require(unchanged() and store.verify_completed()==records,'N_inputs_changed_during_diagnostic')
    # Publish only semantic provenance, never private per-query paths/outputs.
    out['provenance_sha256']={'inputs':fingerprint(inputs),'helper':binding['helper_sha256'],'source':binding['source_sha256']}
    target=ArtifactStore(ROUND/'diagnostics/completed_n',binding,['aggregate'],verify_sources=unchanged,root=ROUND)
    if (target.directory/'completion.json').is_file(): require(target.verify_completed()=={'aggregate':out},'N_diagnostic_changed')
    else: target.finalize({'aggregate':out})
    require(target.verify_completed()=={'aggregate':out},'N_diagnostic_seal_changed')
    return out

if __name__=='__main__':
    try:
        output=run()
        print(json.dumps({'status':'completed_N_diagnostic','api_calls':0,'validation_opened':False}))
    except Exception as exc:
        print(json.dumps({'status':'N_diagnostic_refused','error_type':type(exc).__name__}))
        raise SystemExit(1)
