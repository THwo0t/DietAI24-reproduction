#!/usr/bin/env python3
"""Prepare/freeze/preflight/run/replay/score N on both complete dev cohorts."""
from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import deepcopy
import argparse
import json
from pathlib import Path
import sys
import threading

BASE = Path(__file__).resolve().parents[2]
sys.dont_write_bytecode = True
sys.path[:0] = [str(BASE),str(BASE/'src'),str(BASE/'round7/src'),str(BASE/'round8/src')]
from opt_provider import ROOT, fingerprint, sha
from opt_pipeline import encode_image
from round4.src.artifacts import ArtifactStore,key_path
from context_n import ROUND,write_once,prepare,freeze,runtime_context
from records_n import core_record,coding_snapshot
from scoring_n import PROFILES,shared_identity
from runtime_n import Trace,Replay
from uncertain_portions import UncertainPortionPipeline


def event(**value): print(json.dumps(value,allow_nan=False),flush=True)

def record_name(profile,row): return profile+'-'+fingerprint(row['sample_id'])[:32]

def run(ctx,allow_paid=False):
    names = [record_name(p,r) for r in ctx.rows for p in PROFILES]+['service-proof']
    store = ArtifactStore(ROUND/'runs/development',ctx.binding,names,verify_sources=ctx.verify_sources,root=ROUND)
    complete = (store.directory/'completion.json').is_file()
    if not complete and not allow_paid: raise ValueError('N_paid_flag_required_for_incomplete_batch')
    saved = store.verify_completed() if complete else None
    if not complete:
        store.initialize(); ctx.ledger.initialize(); ctx.ledger.recover_pending()
    ctx.ledger.audit(complete=complete)
    trace = Trace(ctx.ledger,ctx.parser_sha256,allow_paid=allow_paid)
    records,refs,guard = {},{},threading.Lock()

    def cached(name,inputs,call,validate):
        if complete:
            return store._cached('stages/'+key_path(name),store._stage_intent(name,inputs),validate)
        return store.stage_runner(name,inputs,call,validate)

    def fixed(name,inputs,value):
        def validate(old):
            if old != value: raise ValueError('N_fixed_stage_changed')
            return old
        return cached(name,inputs,lambda:deepcopy(value),validate)

    def stage(name,row,stage_name,inputs,call):
        image = ROOT/row['image_path']
        def pipeline(chat,repair):
            p = UncertainPortionPipeline(chat,lambda _:(_ for _ in ()).throw(AssertionError('N_embedding_forbidden')),
                                         ctx.catalog,None)
            p.on_format_failure = repair
            return p
        def invoke():
            with trace.expect(row['sample_id'],stage_name,encode_image(image,'native')) as request_refs:
                result = call(pipeline(trace.chat,trace.format_failure))
            return {'result':result,'request_refs':deepcopy(request_refs)}
        def validate(envelope):
            if set(envelope) != {'result','request_refs'}: raise ValueError('N_stage_envelope_changed')
            replay = Replay(ctx.ledger,row['sample_id'],stage_name,envelope['request_refs'],ctx.parser_sha256)
            result = call(pipeline(replay.chat,replay.format_failure)); replay.finish()
            if result != envelope['result']: raise ValueError('N_scientific_reparse_changed')
            return envelope
        envelope = cached(name,inputs,invoke,validate)
        with guard: refs[name] = deepcopy(envelope['request_refs'])
        return envelope['result']

    def one(row):
        image = ROOT/row['image_path']; old = ctx.imported['records'][row['sample_id']]
        inputs = {'row_sha256':fingerprint(row),'image_sha256':row['image_sha256'],
                  'upstream_sha256':fingerprint(old)}
        stem = record_name('N',row)
        identity = stage(stem+'-identity',row,'N_identity',inputs,
                         lambda p:p.identify_uncertain(image,old['identity']))
        coding = fixed(stem+'-coding',{'identity_sha256':fingerprint(identity)},coding_snapshot(identity))
        p = UncertainPortionPipeline(lambda _:None,lambda _:None,ctx.catalog,None)
        density = fixed(stem+'-density',{'identity_sha256':fingerprint(identity),'coding_sha256':fingerprint(coding)},
                        p.density_portion(image,identity,old['identity'],old['portion']))
        units = stage(stem+'-units',row,'N_units',
            {**inputs,'identity_sha256':fingerprint(identity),'coding_sha256':fingerprint(coding)},
            lambda p:p.unit_portion(image,identity,old['identity']))
        fallback = ctx.fallbacks['vectors'][row['dataset']][str(row['fold'])]
        pair = {profile:core_record(row,identity,portion,fallback,coding)
                for profile,portion in zip(PROFILES,(density,units))}
        for profile,record in pair.items(): fixed(record_name(profile,row)+'-record',inputs,record)
        with guard:
            for profile,record in pair.items(): records[record_name(profile,row)] = record
            event(completed_pairs=len(records)//2,total_pairs=len(ctx.rows),dataset=row['dataset'])

    try:
        if complete:
            for row in ctx.rows: one(row)
        else:
            with ThreadPoolExecutor(max_workers=2) as pool:
                pending = [pool.submit(one,row) for row in ctx.rows]
                try:
                    for future in as_completed(pending): future.result()
                except BaseException:
                    for future in pending: future.cancel()
                    raise
        shared_identity({p:[records[record_name(p,r)] for r in ctx.rows] for p in PROFILES})
        proof = ctx.ledger.audit(complete=True)
        proof['stage_refs_sha256'] = fingerprint(refs)
        proof['logical_answers'] = sum(len(v) for v in refs.values())
        fixed('completion-service-proof',{'stage_refs_sha256':fingerprint(refs)},proof)
        records['service-proof'] = proof; ctx.verify_sources()
        if complete:
            if records != saved: raise ValueError('N_completed_records_changed')
            store.verify_completed()
        else: store.finalize(records)
        return {'status':'completed','pairs':len(ctx.rows),'completed_replay':complete,
            'provider_constructed':trace.provider is not None,'service_counts':proof['counts']}
    finally: trace.close()


def score_completed():
    # All predictions sealed before this function imports any label loader.
    ctx = runtime_context()
    names = [record_name(p,r) for r in ctx.rows for p in PROFILES]+['service-proof']
    store = ArtifactStore(ROUND/'runs/development',ctx.binding,names,verify_sources=ctx.verify_sources,root=ROUND)
    records = store.verify_completed(); ctx.ledger.audit(complete=True)
    from cohorts_v2 import load_dev
    from diagnostics_v2 import asa24_exact_intersection
    from opt_metrics import evaluate
    from scoring_n import score,select
    rows,labels = load_dev()
    if rows != ctx.rows or sha(ROOT/'data/cohorts/dev_labels.json') != ctx.fallbacks['labels_sha256']:
        raise ValueError('N_score_references_changed')
    by_profile = {p:[records[record_name(p,r)] for r in rows] for p in PROFILES}
    shared_identity(by_profile)
    results = {p:score(rows,labels,by_profile[p],ctx.catalog) for p in PROFILES}
    common = asa24_exact_intersection(rows,labels,results[PROFILES[0]]['predictions'],results[PROFILES[1]]['predictions'],
                                     draws=10000,seed=20261102)
    median_rows = []
    for row in rows:
        fallback = ctx.fallbacks['vectors'][row['dataset']][str(row['fold'])]
        median_rows.append({'sample_id':row['sample_id'],'dataset':row['dataset'],'prediction':fallback,
            'final_codes':[],'primary_code':None,'native_complete':False,'fallback':True,
            'e2e':{'prediction':fallback,'fallback':True},'conditional':None})
    medians = evaluate(rows,labels,median_rows)['datasets']
    outcomes = [load_json for h in set(ctx.ledger.read()['bindings'].values())
                for load_json in ctx.ledger.target(h)['outcomes']]
    usage = {k:sum(((o.get('body') or {}).get('usage') or {}).get(k,0) or 0 for o in outcomes)
             for k in ('prompt_tokens','completion_tokens','total_tokens')}
    usage['reasoning_tokens'] = sum(((((o.get('body') or {}).get('usage') or {}).get('completion_tokens_details') or {})
                                      .get('reasoning_tokens',0) or 0) for o in outcomes)
    unit_counts = {'images':0,'leaves':0,'with_units':0,'direct':0,'conflicting_labels':0}
    coverage = {'identity_success_images':0,'identity_failed_images':0,'leaves':0,
                'with_units':0,'direct':0,'all_unit_images':0,'partial_unit_images':0,
                'no_unit_images':0,'conflicting_labels':0}
    # Unit choices/provenance stay in sealed stages; aggregate only successful
    # per-leaf modes from the raw scientific stage, not reference information.
    unit_pipeline = UncertainPortionPipeline(lambda _:None,lambda _:None,ctx.catalog,None)
    for row in rows:
        ident_name = record_name('N',row)+'-identity'
        identity = store._json('stages/'+key_path(ident_name)+'/result.json')['parsed']['result']
        if identity['status'] == 'ok':
            coverage['identity_success_images'] += 1
            contexts = unit_pipeline.unit_context(identity)
            modes = [bool(v['units']) for v in contexts.values()]
            coverage['leaves'] += len(modes); coverage['with_units'] += sum(modes)
            coverage['direct'] += len(modes)-sum(modes)
            coverage['all_unit_images' if all(modes) else 'partial_unit_images' if any(modes) else 'no_unit_images'] += 1
            coverage['conflicting_labels'] += sum(len(v['conflicts']) for v in contexts.values())
        else: coverage['identity_failed_images'] += 1
        name = record_name('N',row)+'-units'
        env = store._json('stages/'+key_path(name)+'/result.json')['parsed']['result']
        if env['status'] == 'ok':
            unit_counts['images'] += 1
            for choice in env['unit_choices']:
                unit_counts['leaves'] += 1
                unit_counts['with_units' if choice['mode']=='unit' else 'direct'] += 1
            unit_counts['conflicting_labels'] += sum(len(v['conflicts']) for v in env['unit_options'].values())
    control = json.loads((ROOT/'round7/development_checkpoint.json').read_text())['arms']['M0']
    output = {'arms':{p:{k:v for k,v in r.items() if k!='predictions'} for p,r in results.items()},
        'selection':select(results),'common_exact':common,'service_proof':records['service-proof'],
        'imported_M0_control':control,'unit_coverage_after_N_identity':coverage,
        'unit_mode_successful_subset':unit_counts,
        'pure_median_baseline':{'asa24_e2e':medians['asa24']['e2e'],'nutrition5k':medians['nutrition5k']['primary']},
        'new_service_usage':usage,'service_counts':records['service-proof']['counts'],
        'cost_notice':'Money unverified; request/token counts only. Reasoning included in completion. Old imported work is separate.',
        'scope':'development only; both profiles share identity; original test and sealed validation not used for selection'}
    write_once(ROUND/'runs/scoring/results.json',output)
    write_once(ROUND/'development_checkpoint.json',{k:v for k,v in output.items() if k!='service_proof'})
    return {'selection':output['selection'],'failed_checks':{p:r['tolerance']['failed_checks'] for p,r in results.items()}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase',choices=['prepare','freeze','preflight','base','verify','score'])
    parser.add_argument('--allow-paid',action='store_true'); parser.add_argument('--pre-review',action='store_true')
    args = parser.parse_args()
    if args.pre_review and args.phase != 'preflight': raise ValueError('N_pre_review_only_for_preflight')
    if args.phase=='prepare': result = prepare()
    elif args.phase=='freeze': result = {'freeze_sha256':fingerprint(freeze())}
    elif args.phase=='preflight':
        ctx = runtime_context(pre_review=args.pre_review)
        result = {'rows':len(ctx.rows),'imported_pairs':len(ctx.imported['records']),'api_calls':0,
                  'labels_loaded':False,'service_state_exists':ctx.ledger.path('admission.json').exists()}
    elif args.phase=='base': result = run(runtime_context(),args.allow_paid)
    elif args.phase=='verify':
        if not (ROUND/'runs/development/completion.json').is_file(): raise ValueError('N_incomplete_run')
        result = run(runtime_context(),False)
    else: result = score_completed()
    event(**result)

if __name__=='__main__':
    try: main()
    except SystemExit: raise
    except BaseException as exc:
        event(status='stopped',error_type=type(exc).__name__)
        raise SystemExit(1)
