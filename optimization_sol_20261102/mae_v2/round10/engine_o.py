"""Exact source Pipeline execution with per-stage live or zero-Provider refs."""
from copy import deepcopy

from opt_pipeline import encode_image
from opt_provider import ROOT
from source_portions import SourcePortionPipeline,CONFIG
from service_o import payload,embedding_payload,slot_id
from runtime_o import verify_reference

STAGES=('identify','retrieval','select','whole','conditional')


class RowLive:
    def __init__(self,row,trace):
        self.sample=row['sample_id'];self.trace=trace;self.refs={k:[] for k in STAGES}

    def chat(self,stage,messages,image):
        with self.trace.expect(self.sample,stage,image,refs=self.refs[stage]):
            return self.trace.chat(messages)

    def embed(self,texts):
        with self.trace.expect(self.sample,'retrieval',refs=self.refs['retrieval']):
            return self.trace.embed(texts)

    def finish(self):return deepcopy(self.refs)


class RowReplay:
    def __init__(self,row,ledger,imports,manifest_sha256,refs):
        if set(refs)!=set(STAGES) or any(not isinstance(v,list) for v in refs.values()):
            raise ValueError('O_replay_stage_reference_schema_changed')
        self.sample=row['sample_id'];self.ledger,self.imports,self.manifest_sha256=ledger,imports,manifest_sha256
        self.refs=deepcopy(refs);self.positions={k:0 for k in STAGES}

    def request(self,stage,value):
        index=self.positions[stage]
        if index>=len(self.refs[stage]):raise ValueError('O_replay_missing_request')
        ref=self.refs[stage][index]
        expected=slot_id(self.sample,f'embed_{index:02d}',0) if stage=='retrieval' else \
                 slot_id(self.sample,stage,index)
        if ref['slot']!=expected:raise ValueError('O_replay_stage_slot_order_changed')
        answer=verify_reference(self.ledger,self.imports,self.manifest_sha256,ref,value)
        self.positions[stage]+=1
        return answer

    def chat(self,stage,messages,image):return self.request(stage,payload(messages))
    def embed(self,texts):return [self.request('retrieval',embedding_payload(text)) for text in texts]

    def finish(self):
        if any(self.positions[k]!=len(self.refs[k]) for k in STAGES):
            raise ValueError('O_replay_extra_request')
        return deepcopy(self.refs)


def identify(ctx,row,client,*,root=ROOT):
    image_path=root/row['image_path'];image=encode_image(image_path,'square256')
    phase={'embedding_started':False}
    def chat(messages):
        return client.chat('select' if phase['embedding_started'] else 'identify',messages,image)
    def embed(texts):
        phase['embedding_started']=True
        return client.embed(texts)
    pipeline=SourcePortionPipeline(chat,embed,ctx.catalog,ctx.retriever)
    result=pipeline.identify_select(image_path,row['dataset'],CONFIG)
    return {'result':result,'request_refs':client.finish()}


def portions(ctx,row,identity,client,*,conditional_context=None,root=ROOT):
    image_path=root/row['image_path'];image=encode_image(image_path,'square256')
    stage='whole' if conditional_context is None else 'conditional'
    def forbidden(*args,**kwargs):raise AssertionError('O_portions_cannot_embed_or_retrieve')
    pipeline=SourcePortionPipeline(lambda messages:client.chat(stage,messages,image),forbidden,ctx.catalog,None)
    result=(pipeline.whole_portions(image_path,identity,row['dataset']) if conditional_context is None else
            pipeline.conditional_portion(image_path,identity,conditional_context))
    return {'result':result,'request_refs':client.finish()}
