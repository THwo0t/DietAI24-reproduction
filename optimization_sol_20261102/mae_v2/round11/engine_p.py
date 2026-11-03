"""Thin paired scientific execution and exact request-reference replay.

No provider, context loader, composition or paid entry. Production replay needs
future runtime_p.verify_reference; the complete P Trace/gate/freeze is separate.
"""
from copy import deepcopy

from opt_pipeline import ContractError, encode_image
from opt_provider import ROOT
from source_portions import SourcePortionPipeline, CONFIG
from paired_stage_pipeline import PairedStagePipeline
from service_p import payload, embedding_payload, slot_id

STAGES = ('identify','retrieval','select','whole','quantity','density','conditional')


def _chat_stage(stage):
    if stage not in STAGES or stage == 'retrieval':
        raise ValueError('P_unregistered_chat_stage')


class RowLive:
    def __init__(self,row,trace):
        self.sample=row['sample_id'];self.trace=trace;self.refs={k:[] for k in STAGES}

    def chat(self,stage,messages,image):
        _chat_stage(stage)
        with self.trace.expect(self.sample,stage,image,refs=self.refs[stage]):
            return self.trace.chat(messages)

    def embed(self,texts):
        with self.trace.expect(self.sample,'retrieval',refs=self.refs['retrieval']):
            return self.trace.embed(texts)

    def finish(self):return deepcopy(self.refs)


class RowReplay:
    def __init__(self,row,ledger,imports,manifest_sha256,refs,*,_verifier=None):
        if (type(refs) is not dict or set(refs)!=set(STAGES)
                or any(type(v) is not list or any(type(r) is not dict or 'slot' not in r for r in v)
                       for v in refs.values())):
            raise ValueError('P_replay_stage_reference_schema_changed')
        self.sample=row['sample_id'];self.ledger,self.imports,self.manifest_sha256=ledger,imports,manifest_sha256
        self.refs=deepcopy(refs);self.positions={k:0 for k in STAGES};self._verifier=_verifier

    def request(self,stage,value):
        if stage not in STAGES:raise ValueError('P_replay_unknown_stage')
        if value.get('role')!=('embedding' if stage=='retrieval' else 'chat'):
            raise ValueError('P_replay_stage_role_changed')
        index=self.positions[stage]
        if index>=len(self.refs[stage]):raise ValueError('P_replay_missing_request')
        ref=self.refs[stage][index]
        expected=slot_id(self.sample,f'embed_{index:02d}',0) if stage=='retrieval' else slot_id(self.sample,stage,index)
        if ref['slot']!=expected:raise ValueError('P_replay_stage_slot_order_changed')
        verifier=self._verifier
        if verifier is None:
            from runtime_p import verify_reference
            verifier=verify_reference
        answer=verifier(self.ledger,self.imports,self.manifest_sha256,ref,value)
        self.positions[stage]+=1
        return answer

    def chat(self,stage,messages,image):
        _chat_stage(stage)
        return self.request(stage,payload(messages))

    def embed(self,texts):return [self.request('retrieval',embedding_payload(text)) for text in texts]

    def finish(self):
        if any(self.positions[k]!=len(self.refs[k]) for k in STAGES):raise ValueError('P_replay_extra_request')
        return deepcopy(self.refs)


def identify(ctx,row,client,*,root=ROOT):
    image_path=root/row['image_path'];image=encode_image(image_path,'square256')
    phase={'embedding_started':False}
    def chat(messages):return client.chat('select' if phase['embedding_started'] else 'identify',messages,image)
    def embed(texts):
        phase['embedding_started']=True
        return client.embed(texts)
    pipeline=SourcePortionPipeline(chat,embed,ctx.catalog,ctx.retriever)
    result=pipeline.identify_select(image_path,row['dataset'],CONFIG)
    return {'result':result,'request_refs':client.finish()}


def _forbidden(*args,**kwargs):raise AssertionError('P_portion_stage_cannot_embed_or_retrieve')


def portions(ctx,row,identity,client,*,conditional_context=None,root=ROOT):
    stage='whole' if conditional_context is None else 'conditional'
    if conditional_context is not None and row['dataset']!='asa24':raise ContractError('P_conditional_requires_asa24')
    pipeline=SourcePortionPipeline(lambda messages:client.chat(stage,messages,image),_forbidden,ctx.catalog,None)
    pipeline.checked_items(identity,row['dataset'])
    image_path=root/row['image_path'];image=encode_image(image_path,'square256')
    result=(pipeline.whole_portions(image_path,identity,row['dataset']) if conditional_context is None else
            pipeline.conditional_portion(image_path,identity,conditional_context))
    return {'result':result,'request_refs':client.finish()}


def _intervention(ctx,row,identity,client,kind,root):
    pipeline=PairedStagePipeline(lambda messages:client.chat(kind,messages,image),_forbidden,ctx.catalog,None)
    pipeline._fixed(identity,row['dataset'])
    image_path=root/row['image_path'];image=encode_image(image_path,'square256')
    result=getattr(pipeline,kind+'_intervention')(image_path,identity,row['dataset'])
    return {'result':result,'request_refs':client.finish()}


def quantity(ctx,row,identity,client,*,root=ROOT):return _intervention(ctx,row,identity,client,'quantity',root)


def density(ctx,row,identity,client,*,root=ROOT):return _intervention(ctx,row,identity,client,'density',root)
