"""Resumable paired P runner prototype; public execution awaits integrated review.

Main inference never parses labels. The separate offline adapter currently
requires Linux user/network namespaces; no Mac isolation fallback or real Mac
hardware acceptance is implemented. Synthetic tests inject their own offline
ledger, trace, stores and isolated adapter seam. No scoring or fitting here.
"""
from copy import deepcopy
from pathlib import Path
import argparse
import os
import subprocess
import sys

BASE=Path(__file__).resolve().parent.parent
sys.path[:0]=[str(BASE),str(BASE/'src'),str(BASE/'round7/src'),str(BASE/'round8/src'),str(BASE/'round10'),str(BASE/'round11')]

from opt_provider import ROOT,sha,fingerprint
from service_p import Ledger,allowed_slots
from runtime_p import Trace
from engine_p import RowLive,RowReplay,identify,portions,quantity,density
from stores_p import name,identity_store,final_store,adapter_store,proof_for_refs,verified_contexts
from identity_gate_p import build_loader
from round4.src.artifacts import key_path


def require(ok,code):
    if not ok:raise ValueError(code)


def cached(store,complete,stem,inputs,call,validate):
    if complete:return store._cached('stages/'+key_path(stem),store._stage_intent(stem,inputs),validate)
    return store.stage_runner(stem,inputs,call,validate)


def _contexts(ctx,store,snapshot,identity_seal):
    require(snapshot.load()[1]['coding_completion_sha256']==identity_seal,'P_adapter_identity_seal_changed')
    return verified_contexts(ctx,None,snapshot,store)


def _isolated_adapter(ctx,ledger,snapshot):
    """Linux-only separate offline projection; no credential-bearing environment."""
    from adapter_p import CLEAN_ENV
    require(sys.platform.startswith('linux'),'P_adapter_portable_isolation_unimplemented')
    ctx.verify_sources();snapshot.revalidate_full()
    require(ledger.binding==fingerprint(ctx.binding),'P_adapter_launch_science_changed')
    child=subprocess.run(['/usr/bin/unshare','-Urn',sys.executable,'-B',str(Path(__file__).with_name('adapter_p.py'))],
        cwd=ROOT,env=dict(CLEAN_ENV),stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,check=False)
    require(child.returncode==0,'P_isolated_adapter_child_failed_preserve_state')
    ctx.verify_sources();snapshot.revalidate_full()


def _run(ctx,allow_paid=False,*,ledger=None,trace=None,adapter_runner=None,data_root=ROOT,stores=None,emit=lambda **kw:None):
    """Private synthetic seam; public entry supplies only fixed reviewed sources."""
    from records_p import compose_record,attach_conditional
    root=Path(data_root);ctx.verify_sources()
    require(root.is_absolute() and root.resolve()==root,'P_runner_absolute_root_required')
    require(ctx.binding.get('schema_version')==1,'P_runner_scientific_freeze_required')
    ledger=Ledger(root/'round11/provider/P',ctx.binding,allowed_slots(ctx.rows)) if ledger is None else ledger
    require(ledger.binding==fingerprint(ctx.binding),'P_runner_ledger_science_binding_changed')
    ids,out=(identity_store(ctx),final_store(ctx)) if stores is None else stores[:2]
    require(ids.binding==ctx.binding and out.binding==ctx.binding,'P_runner_artifact_science_binding_changed')
    require(set(ids.expected_records)=={name('identity',r) for r in ctx.rows}|{'service-proof'} and
            set(out.expected_records)=={name('record',r) for r in ctx.rows}|{'service-proof'},
            'P_runner_artifact_population_changed')
    id_complete=(ids.directory/'completion.json').is_file();complete=(out.directory/'completion.json').is_file()
    require(not complete or id_complete,'P_final_without_complete_coding')
    if complete:
        adapter=(adapter_store(ctx) if stores is None else stores[2])
        require((adapter.directory/'completion.json').is_file(),'P_complete_replay_requires_existing_adapter_seal')
        ids.verify_completed();out.verify_completed();adapter.verify_completed()
    require(complete or allow_paid or trace is not None,'P_paid_flag_required_for_incomplete_batch')
    if not complete:
        ledger.initialize();ledger.recover_pending()
        if not id_complete:ids.initialize()
        out.initialize()
    ledger.audit(complete=complete)
    trace=Trace(ledger,ctx.imports,ctx.manifest_sha256,allow_paid=allow_paid) if trace is None else trace
    require(not complete or trace.provider is None,'P_complete_replay_requires_zero_provider')
    identities={};envelopes={};id_refs={};all_refs={};records={}

    def stage(store,sealed,stem,row,operation,inputs):
        def validate(envelope):
            require(type(envelope) is dict and set(envelope)=={'result','request_refs'},'P_scientific_envelope_changed')
            replay=operation(RowReplay(row,ledger,ctx.imports,ctx.manifest_sha256,envelope['request_refs']))
            require(replay==envelope,'P_exact_scientific_replay_changed')
            return envelope
        envelope=cached(store,sealed,stem,inputs,lambda:operation(RowLive(row,trace)),validate)
        for phase,refs in envelope['request_refs'].items():all_refs[stem+'-'+phase]=deepcopy(refs)
        return envelope

    try:
        for row in ctx.rows:
            sid=row['sample_id'];stem=name('identity',row)
            envelope=stage(ids,id_complete,stem,row,lambda client:identify(ctx,row,client,root=root),
                {'row_sha256':fingerprint(row),'image_sha256':row['image_sha256']})
            identities[sid]=envelope['result'];envelopes[sid]=envelope
            for phase,refs in envelope['request_refs'].items():id_refs[stem+'-'+phase]=deepcopy(refs)
            emit(phase='identities',completed=len(identities),total=len(ctx.rows))
        coding={name('identity',r):identities[r['sample_id']] for r in ctx.rows}
        coding['service-proof']=proof_for_refs(ledger,id_refs);ctx.verify_sources()
        if id_complete:require(ids.verify_completed()==coding,'P_sealed_coding_changed')
        else:ids.finalize(coding)
        snapshot=build_loader(ctx,ledger,ids,data_root=root,envelopes=envelopes)
        ledger.task_gate().identity_loader=snapshot.load
        identity_seal=sha(ids.directory/'completion.json')
        adapter=adapter_store(ctx) if stores is None else stores[2]
        if not (adapter.directory/'completion.json').is_file():
            (adapter_runner or _isolated_adapter)(ctx,ledger,snapshot)
        contexts=_contexts(ctx,adapter,snapshot,identity_seal)
        ledger.task_gate().context_loader=lambda:deepcopy(contexts)

        for row in ctx.rows:
            sid=row['sample_id'];identity=identities[sid];stem=name('record',row)
            inputs={'row_sha256':fingerprint(row),'identity_sha256':fingerprint(identity),
                    'coding_completion_sha256':identity_seal}
            stage_envelopes={}
            if identity.get('status')=='ok':
                for kind,operation in [('whole',portions),('quantity',quantity),('density',density)]:
                    stage_envelopes[kind]=stage(out,complete,stem+'-'+kind,row,
                        lambda client,op=operation:op(ctx,row,identity,client,root=root),inputs)
            else:stage_envelopes={kind:None for kind in ('whole','quantity','density')}
            fallback_proof=ctx.fallbacks['folds'][row['dataset']][str(row['fold'])]
            row_refs={}
            for kind,envelope in [('identity',envelopes[sid])]+list(stage_envelopes.items()):
                if envelope is not None:
                    for phase,refs in envelope['request_refs'].items():row_refs[kind+'-'+phase]=refs
            record=compose_record(row,envelopes[sid],stage_envelopes['whole'],stage_envelopes['quantity'],
                stage_envelopes['density'],ctx.catalog,fallback_proof['value'],evidence_binding={
                    'row_sha256':fingerprint(row),'identity_seal_sha256':identity_seal,
                    'request_proof_sha256':fingerprint(proof_for_refs(ledger,row_refs)),
                    'fallback_binding_sha256':fingerprint({'science':ctx.binding,'dataset':row['dataset'],
                        'fold':row['fold'],'training_fold':fallback_proof})})
            if sid in contexts:
                context=contexts[sid]
                conditional=stage(out,complete,stem+'-conditional',row,
                    lambda client:portions(ctx,row,identity,client,conditional_context=context,root=root),
                    {**inputs,'task_context_sha256':fingerprint(context)})
                refs={phase:group for phase,group in conditional['request_refs'].items()}
                record=attach_conditional(record,conditional,context,ctx.catalog,adapter_binding={
                    'identity_seal_sha256':identity_seal,'context_sha256':fingerprint(context),
                    'request_proof_sha256':fingerprint(proof_for_refs(ledger,refs))})
            def validate_record(old):
                require(old==record,'P_completed_record_changed');return old
            cached(out,complete,stem+'-record',inputs,lambda:deepcopy(record),validate_record)
            records[stem]=record;emit(phase='predictions',completed=len(records),total=len(ctx.rows))
        snapshot.revalidate_full();_contexts(ctx,adapter,snapshot,identity_seal)
        proof=ledger.audit(complete=True)
        proof['stage_refs_sha256']=fingerprint(all_refs);proof['logical_answers']=sum(len(v) for v in all_refs.values())
        records['service-proof']=proof;ctx.verify_sources()
        if complete:require(out.verify_completed()==records,'P_full_completed_records_changed')
        else:out.finalize(records)
        return {'status':'completed','records':len(ctx.rows),'completed_replay':complete,
                'provider_constructed':trace.provider is not None,'service_counts':proof['counts']}
    finally:trace.close()


def run(*,allow_paid=False):
    require(type(allow_paid) is bool,'P_explicit_paid_flag_required')
    from context_p import runtime_context
    return _run(runtime_context(),allow_paid=allow_paid)


def _verified_completed(ctx,ledger,*,data_root=ROOT,stores=None):
    """Private fixture seam. Always complete-only, no adapter/Provider creation."""
    root=Path(data_root)
    ids,out,adapter=(identity_store(ctx),final_store(ctx),adapter_store(ctx)) if stores is None else stores
    require(all((s.directory/'completion.json').is_file() for s in (ids,out,adapter)),
            'P_verify_completed_requires_all_three_seals')
    result=_run(ctx,ledger=ledger,data_root=root,stores=(ids,out,adapter))
    require(result['completed_replay'] is True and result['provider_constructed'] is False,
            'P_completed_verifier_requires_zero_provider')
    values=out.verify_completed()
    from context_p import _load,_read
    closure_path='round11/prepared/cohort/source_closure.json'
    require(_read(root,closure_path,digest_only=True)==ctx.binding['source_files'][closure_path],
            'P_completed_source_snapshot_changed')
    closure=_load(root,closure_path)
    strata=closure['strata_private'];records=[values[name('record',row)] for row in ctx.rows]
    require(type(strata) is dict and set(strata)=={r['sample_id'] for r in ctx.rows},'P_completed_strata_changed')
    sources=ctx.binding['source_files']
    bindings={'science_sha256':fingerprint(ctx.binding),
        'manifest_sha256':sources['round11/prepared/cohort/dev.json'],'labels_sha256':ctx.binding['labels_sha256'],
        'record_seal_sha256':sha(out.directory/'completion.json'),'coding_seal_sha256':sha(ids.directory/'completion.json'),
        'adapter_seal_sha256':sha(adapter.directory/'completion.json'),'model_environment_sha256':fingerprint(ctx.binding['environment']),
        'matrix_sha256':sources['data/vectors/embeddings.npy'],'request_cache_proof_sha256':fingerprint(values['service-proof']),
        'source_snapshot_sha256':sources['round11/prepared/cohort/source_closure.json']}
    ctx.verify_sources()
    require(_read(root,closure_path,digest_only=True)==sources[closure_path],'P_completed_source_snapshot_changed')
    snapshot=fingerprint({'bindings':bindings,'records':records,'strata':strata})
    def revalidate():
        current=_verified_completed(ctx,ledger,data_root=root,stores=(ids,out,adapter))
        require(fingerprint({k:current[k] for k in ('bindings','records','strata')})==snapshot,'P_completed_evidence_changed')
        return True
    return {'rows':deepcopy(ctx.rows),'records':deepcopy(records),'catalog':deepcopy(ctx.catalog),
        'strata':deepcopy(strata),'bindings':bindings,
        'audit':{'completed':True,'provider_constructed':False,'labels_parsed':False,'validation_opened':False,
                 'exact_records_reconstructed':True,'all_cache_model_matrix_refs_authenticated':True},
        'revalidate':revalidate}


def verify_completed():
    """Fixed, cache-only full scientific replay for independently gated scoring."""
    from context_p import runtime_context
    ctx=runtime_context()
    require((ROOT/'round11/runs/development/completion.json').is_file() and
            (ROOT/'round11/runs/identities/completion.json').is_file() and
            (ROOT/'round11/runs/conditional-adapter/completion.json').is_file(),
            'P_verify_completed_requires_all_three_seals')
    ledger=Ledger(ROOT/'round11/provider/P',ctx.binding,allowed_slots(ctx.rows))
    return _verified_completed(ctx,ledger)


verified_completed=verify_completed


def main():
    parser=argparse.ArgumentParser(description='Frozen P paired development runner')
    parser.add_argument('--allow-paid',action='store_true',help='Explicitly allow incomplete frozen inference')
    args=parser.parse_args()
    return run(allow_paid=args.allow_paid)


if __name__=='__main__':
    import json
    try:print(json.dumps(main(),sort_keys=True))
    except BaseException:
        # ProviderStop inherits BaseException; never print service error bodies.
        print(json.dumps({'status':'P_runner_refused_preserve_state'}));raise SystemExit(1)
