"""Resumable paired P runner prototype; public execution awaits integrated review.

Main inference never opens labels. Synthetic tests inject their own offline
ledger, trace, stores and isolated adapter seam. No scoring or fitting here.
"""
from copy import deepcopy
from pathlib import Path

from opt_provider import ROOT,sha,fingerprint
from service_p import Ledger,allowed_slots
from runtime_p import Trace
from engine_p import RowLive,RowReplay,identify,portions,quantity,density
from stores_p import name,identity_store,final_store,adapter_store,proof_for_refs
from identity_gate_p import build_loader
from round4.src.artifacts import key_path


def require(ok,code):
    if not ok:raise ValueError(code)


def cached(store,complete,stem,inputs,call,validate):
    if complete:return store._cached('stages/'+key_path(stem),store._stage_intent(stem,inputs),validate)
    return store.stage_runner(stem,inputs,call,validate)


def _contexts(ctx,store,snapshot,identity_seal):
    identities,proof=snapshot.load();values=store.verify_completed()
    require(type(values) is dict and set(values)=={'contexts','provenance'},'P_adapter_record_schema_changed')
    provenance=values['provenance']
    fields={'coding_completion_sha256','labels_sha256','identity_records_sha256','adapter_source_sha256',
            'input_rows','Exact_contexts','permitted_fields','current_portion_truth_exported','api_calls','validation_opened'}
    require(type(provenance) is dict and set(provenance)==fields and
        provenance['coding_completion_sha256']==identity_seal==proof['coding_completion_sha256'] and
        provenance['labels_sha256']==ctx.binding['labels_sha256'] and
        provenance['identity_records_sha256']==fingerprint(identities) and
        provenance['adapter_source_sha256']==sha(Path(__file__).with_name('adapter_p.py')) and
        type(provenance['input_rows']) is int and provenance['input_rows']==len(ctx.rows) and
        provenance['permitted_fields']==['code','options'] and provenance['current_portion_truth_exported'] is False and
        type(provenance['api_calls']) is int and provenance['api_calls']==0 and provenance['validation_opened'] is False,
        'P_adapter_provenance_changed')
    contexts=values['contexts'];rows={r['sample_id']:r for r in ctx.rows}
    require(type(contexts) is dict and type(provenance['Exact_contexts']) is int and
            provenance['Exact_contexts']==len(contexts),'P_adapter_exact_count_changed')
    require(store.binding=={'science':ctx.binding,'coding_completion_sha256':identity_seal,
            'labels_sha256':ctx.binding['labels_sha256'],'role':'post_coding_ASA_code_and_full_catalogue_only'},
            'P_adapter_store_binding_changed')
    for sid,context in contexts.items():
        require(sid in rows and rows[sid]['dataset']=='asa24' and identities[sid].get('status')=='ok'
                and type(context) is dict and set(context)=={'code','options'} and
                context['code'] in identities[sid]['final_codes'] and
                context['options']==ctx.catalog['asa_options'][context['code']],
                'P_adapter_context_changed')
    return deepcopy(contexts)


def _isolated_adapter_unavailable(*args):
    raise ValueError('P_reviewed_isolated_adapter_entry_not_implemented')


def _run(ctx,allow_paid=False,*,ledger=None,trace=None,adapter_runner=None,data_root=ROOT,stores=None,emit=lambda **kw:None):
    """Private integration seam; production entry below intentionally closed."""
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
            (adapter_runner or _isolated_adapter_unavailable)(ctx,ledger,snapshot)
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


def run():
    raise ValueError('P_runner_first_integrated_review_required')


if __name__=='__main__':
    raise SystemExit('P_runner_first_integrated_review_required')
