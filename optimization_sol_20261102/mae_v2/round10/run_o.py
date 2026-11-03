#!/usr/bin/env python3
"""O's resumable two-phase inference, zero-Provider replay and post-seal score."""
from concurrent.futures import ThreadPoolExecutor,as_completed
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
import threading

sys.dont_write_bytecode=True
BASE=Path(__file__).resolve().parent.parent
sys.path[:0]=[str(BASE),str(BASE/'src'),str(BASE/'round7/src'),str(BASE/'round8/src'),str(BASE/'round10')]

from opt_provider import ROOT,sha,fingerprint,atomic_json,ProviderStop
from context_o import ROUND,runtime_context,require
from service_o import Ledger,allowed_slots
from runtime_o import Trace
from engine_o import RowLive,RowReplay,identify,portions
from stores_o import (name,identity_store,final_store,proof_for_refs,sealed_identities,sealed_contexts)
from records_o import main_record,coding_snapshot,attach_conditional
from source_portions import SourcePortionPipeline
from round4.src.artifacts import key_path,decode,ArtifactStore


def event(**value):print(json.dumps(value,allow_nan=False),flush=True)


def cached(store,complete,stage,inputs,call,validate):
    if complete:return store._cached('stages/'+key_path(stage),store._stage_intent(stage,inputs),validate)
    return store.stage_runner(stage,inputs,call,validate)


def parallel(rows,call,workers):
    if workers==1:
        for row in rows:call(row)
        return
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures=[pool.submit(call,row) for row in rows]
        try:
            for future in as_completed(futures):future.result()
        except BaseException:
            for future in futures:future.cancel()
            raise


def run(ctx,allow_paid=False,*,ledger=None,trace=None,adapter_runner=None,workers=2,emit=event):
    require(ctx.binding.get('schema_version')==1,'O_scientific_freeze_required')
    require(workers in (1,2),'O_fixed_worker_count')
    ledger=Ledger(ROUND/'provider/O',ctx.binding,allowed_slots(ctx.rows)) if ledger is None else ledger
    ids_store,out_store=identity_store(ctx),final_store(ctx)
    id_complete=(ids_store.directory/'completion.json').is_file()
    complete=(out_store.directory/'completion.json').is_file()
    require(not complete or id_complete,'O_final_without_complete_coding')
    if not complete and not allow_paid:raise ValueError('O_paid_flag_required_for_incomplete_batch')
    if not complete:
        ledger.initialize();ledger.recover_pending()
        if not id_complete:ids_store.initialize()
        out_store.initialize()
    ledger.audit(complete=complete)
    manifest_sha=sha(ROUND/'prepared/embeddings.json')
    trace=Trace(ledger,ctx.imports,manifest_sha,allow_paid=allow_paid) if trace is None else trace
    identities,id_refs,all_refs,records={},{},{},{}
    guard=threading.Lock()

    def stage(store,is_complete,stem,row,operation,inputs):
        def invoke():return operation(RowLive(row,trace))
        def validate(envelope):
            require(set(envelope)=={'result','request_refs'},'O_scientific_envelope_changed')
            replay=RowReplay(row,ledger,ctx.imports,manifest_sha,envelope['request_refs'])
            actual=operation(replay)
            require(actual==envelope,'O_exact_scientific_replay_changed')
            return envelope
        envelope=cached(store,is_complete,stem,inputs,invoke,validate)
        with guard:
            for phase,refs in envelope['request_refs'].items():
                all_refs[stem+'-'+phase]=deepcopy(refs)
        return envelope

    def id_one(row):
        stem=name('identity',row);inputs={'row_sha256':fingerprint(row),'image_sha256':row['image_sha256']}
        envelope=stage(ids_store,id_complete,stem,row,
            lambda client:identify(ctx,row,client,root=ROOT),inputs)
        result=envelope['result']
        if result.get('status')=='ok':SourcePortionPipeline(None,None,ctx.catalog,None).checked_items(result,row['dataset'])
        coding_snapshot(result)
        with guard:
            identities[row['sample_id']]=result
            for phase,refs in envelope['request_refs'].items():id_refs[stem+'-'+phase]=deepcopy(refs)
            emit(phase='identities',completed=len(identities),total=len(ctx.rows),dataset=row['dataset'])

    try:
        parallel(ctx.rows,id_one,1 if id_complete else workers)
        coding_records={name('identity',r):identities[r['sample_id']] for r in ctx.rows}
        coding_records['service-proof']=proof_for_refs(ledger,id_refs)
        ctx.verify_sources()
        if id_complete:require(ids_store.verify_completed()==coding_records,'O_sealed_coding_changed')
        else:ids_store.finalize(coding_records)
        # The main inference process never opens full query labels. Its offline
        # child projects the already permitted true code + complete catalogue.
        if adapter_runner is not None:adapter_runner(ctx,ledger)
        elif not (ROUND/'runs/conditional-adapter/completion.json').is_file():
            result=subprocess.run([sys.executable,'-B',str(ROUND/'adapter_o.py')],
                stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,check=False)
            require(result.returncode==0,'O_isolated_conditional_adapter_failed')
            require(decode(result.stdout)['status']=='O_conditional_adapter_sealed',
                    'O_conditional_adapter_status_changed')
        contexts=sealed_contexts(ctx)
        checked_identities,_=sealed_identities(ctx,ledger)
        require(checked_identities==identities,'O_post_adapter_coding_changed')

        def one(row):
            sid=row['sample_id'];identity=identities[sid];stem=name('record',row)
            inputs={'row_sha256':fingerprint(row),'identity_sha256':fingerprint(identity),
                    'coding_completion_sha256':sha(ROUND/'runs/identities/completion.json')}
            if identity.get('status')=='ok':
                whole=stage(out_store,complete,stem+'-whole',row,
                    lambda client:portions(ctx,row,identity,client,root=ROOT),inputs)['result']
            else:
                whole={'status':'failed','failure':'O_identity_contract','prediction':None,
                       'raw_prediction':None,'raw_leaves':[],'portions':[],'repaired':False}
            fallback=ctx.fallbacks['vectors'][row['dataset']][str(row['fold'])]
            record=main_record(row,identity,whole,fallback,
                SourcePortionPipeline(None,None,ctx.catalog,None),coding_snapshot(identity))
            if sid in contexts:
                context=contexts[sid]
                conditional=stage(out_store,complete,stem+'-conditional',row,
                    lambda client:portions(ctx,row,identity,client,conditional_context=context,root=ROOT),
                    {**inputs,'task_context_sha256':fingerprint(context)})['result']
                record=attach_conditional(record,conditional,context,ctx.catalog)
            def validate(old):
                require(old==record,'O_completed_record_changed');return old
            cached(out_store,complete,stem+'-record',inputs,lambda:deepcopy(record),validate)
            with guard:
                records[name('record',row)]=record
                emit(phase='quantities',completed=len(records),total=len(ctx.rows),dataset=row['dataset'])
        parallel(ctx.rows,one,1 if complete else workers)
        proof=ledger.audit(complete=True);proof['stage_refs_sha256']=fingerprint(all_refs)
        proof['logical_answers']=sum(len(v) for v in all_refs.values())
        records['service-proof']=proof;ctx.verify_sources()
        if complete:require(out_store.verify_completed()==records,'O_full_completed_records_changed')
        else:out_store.finalize(records)
        return {'status':'completed','records':len(ctx.rows),'completed_replay':complete,
                'provider_constructed':trace.provider is not None,'service_counts':proof['counts']}
    finally:trace.close()


def verify_completed():
    result=run(runtime_context(),allow_paid=False)
    require(result['completed_replay'] and not result['provider_constructed'],'O_zero_Provider_replay_required')
    atomic_json(ROUND/'runs/verification.json',{**result,
        'completion_sha256':sha(ROUND/'runs/development/completion.json'),
        'freeze_sha256':sha(ROUND/'prepared/freeze.json')})
    return result


def score_completed():
    ctx=runtime_context();records=final_store(ctx).verify_completed()
    verified=decode((ROUND/'runs/verification.json').read_bytes())
    require(verified.get('completed_replay') is True and verified.get('provider_constructed') is False
        and verified['completion_sha256']==sha(ROUND/'runs/development/completion.json')
        and verified['freeze_sha256']==sha(ROUND/'prepared/freeze.json'),'O_verify_before_scoring_required')
    labels_path=ROOT/'data/cohorts/dev_labels.json'
    require(sha(labels_path)==ctx.binding['labels_sha256'],'O_score_label_binding_changed')
    labels=decode(labels_path.read_bytes())
    from scoring_o import score,public_summary
    result,predictions=score(ctx.rows,labels,[records[name('record',r)] for r in ctx.rows],ctx.catalog)
    result['new_service_usage']=service_usage(Ledger(ROUND/'provider/O',ctx.binding,allowed_slots(ctx.rows)))
    binding={'science':ctx.binding,'completion_sha256':sha(ROUND/'runs/development/completion.json')}
    store=ArtifactStore(ROUND/'runs/scoring',binding,['results','OOF_predictions'],
                         verify_sources=ctx.verify_sources,root=ROUND)
    values={'results':result,'OOF_predictions':predictions}
    if (store.directory/'completion.json').is_file():
        require(store.verify_completed()==values,'O_existing_score_changed')
    else:store.finalize(values)
    atomic_json(ROUND/'development_checkpoint.json',public_summary(result))
    return {'status':'O_development_scored','selection':result['selection'],
            'failed_checks':{k:result[k]['tolerance']['failed_checks'] for k in ('raw','OOF_mass')},
            'api_calls':0,'validation_opened':False}


def service_usage(ledger):
    state=ledger.read()
    usage={role:{'logged_transmissions':0,'errors':0,'prompt_tokens':0,'completion_tokens':0,
                 'total_tokens':0,'reasoning_tokens':0,'missing_usage_responses':0}
           for role in ('chat','embedding')}
    for reservation in state['reservations']:
        rid=reservation['id']
        if rid not in state['outcomes']:continue
        outcome=decode(ledger.outcome_path(rid).read_bytes())
        ledger.validate_outcome(outcome,reservation)
        target=usage[reservation['role']];target['logged_transmissions']+=1
        target['errors']+=outcome['kind']!='success'
        body=outcome.get('body');tokens=body.get('usage') if isinstance(body,dict) else None
        if not isinstance(tokens,dict):
            target['missing_usage_responses']+=1;continue
        missing=False
        for key in ('prompt_tokens','completion_tokens','total_tokens'):
            v=tokens.get(key)
            if type(v) is int and v>=0:target[key]+=v
            else:missing=True
        target['missing_usage_responses']+=missing
        details=tokens.get('completion_tokens_details')
        if isinstance(details,dict) and type(details.get('reasoning_tokens')) is int:
            target['reasoning_tokens']+=max(0,details['reasoning_tokens'])
    imported={'legacy':0,'M':0}
    for path in ledger.path('imports').glob('*.json'):
        origin=decode(path.read_bytes())['origin'];imported[origin]+=1
    return {'providers':usage,'old_import_logical_hits':imported,
            'unknown_reservations':len(state['reservations'])-sum(v['logged_transmissions'] for v in usage.values()),
            'third_party_cost_usd':None,'official_embedding_cost_usd':None,
            'notice':'Reported token usage only; money unverified. Reasoning is already included in completion.'}


def preflight(*,pre_review=False):
    from gate_o import Gate,Machine,Captured
    ctx=runtime_context(pre_review=pre_review)
    slots=allowed_slots(ctx.rows);ledger=Ledger(ROUND/'provider/O',ctx.binding,slots)
    gate=Gate(ctx,ledger);ledger._gate=gate
    for row in ctx.rows:
        from service_o import slot_id
        sid=slot_id(row['sample_id'],'identify',0)
        try:Machine(gate,sid).execute()
        except Captured as capture:gate.validate(sid,capture.value)
        else:raise ValueError('O_initial_task_capture_failed')
    return {'status':'O_preflight_passed','rows':len(ctx.rows),'slots':len(slots),
            'source_pins':len(ctx.binding['source_files']),'pre_review':pre_review,
            'provider_constructed':False,'query_labels_loaded':False,'api_calls':0,'validation_opened':False}


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('phase',choices=('prepare','freeze','preflight','preflight-pre-review','run','verify','score'))
    parser.add_argument('--allow-paid',action='store_true');args=parser.parse_args()
    if args.allow_paid and args.phase!='run':parser.error('--allow-paid only applies to run')
    try:
        if args.phase=='prepare':
            from context_o import prepare
            from imports_o import prepare as prepare_imports
            result={'inputs':prepare(),'embedding_imports':prepare_imports()}
        elif args.phase=='freeze':
            from context_o import freeze
            frozen=freeze();result={'status':'O_frozen','source_pins':len(frozen['source_files']),
                                    'freeze_sha256':sha(ROUND/'prepared/freeze.json')}
        elif args.phase in ('preflight','preflight-pre-review'):
            result=preflight(pre_review=args.phase=='preflight-pre-review')
        elif args.phase=='run':result=run(runtime_context(),allow_paid=args.allow_paid)
        elif args.phase=='verify':result=verify_completed()
        else:result=score_completed()
        event(**result)
    except (Exception,ProviderStop) as exc:
        event(status='O_stopped_preserve_state',error_type=type(exc).__name__)
        raise SystemExit(1)
