"""Reconstruct actual frozen Pipeline tasks from durable earlier answers."""
from copy import deepcopy

from opt_provider import ROOT,sha,fingerprint
from opt_pipeline import ContractError,encode_image
from source_portions import SourcePortionPipeline,CONFIG
from service_o import (payload,embedding_payload,slot_id,request_hash,load)
from imports_o import imported_value

STAGES={'identify':'identify','select':'select','source_standard_first':'whole',
        'portion_conditional_option_continuous_option':'conditional'}


class Captured(BaseException):
    def __init__(self,value):self.value=value


class Inspector(SourcePortionPipeline):
    def __init__(self,machine):
        self.machine=machine
        super().__init__(machine.chat,machine.embed,machine.gate.ctx.catalog,machine.gate.ctx.retriever)

    def _stage(self,name,prompt,image,parser,stages):
        stage=STAGES.get(name)
        if stage is None:raise ValueError('O_unregistered_scientific_stage')
        self.machine.stage=stage;self.machine.ordinal=0
        if self.machine.format_raw is not None and stage==self.machine.meta['stage']:
            try:parser(self.machine.format_raw)
            except ContractError as exc:raise Captured(str(exc))
            raise Captured(None)
        return super()._stage(name,prompt,image,parser,stages)


class Machine:
    def __init__(self,gate,sid=None,format_raw=None):
        self.gate,self.sid,self.format_raw=gate,sid,format_raw
        self.meta=gate.ledger.slots[sid] if sid is not None else None
        self.sample=self.meta['sample_id'] if self.meta else None
        self.stage,self.ordinal,self.query_index=None,0,0

    def step(self,sid,value):
        if sid==self.sid and self.format_raw is None:raise Captured(value)
        return self.gate.previous(sid,value)

    def chat(self,messages):
        sid=slot_id(self.sample,self.stage,self.ordinal);self.ordinal+=1
        return self.step(sid,payload(messages))

    def embed(self,texts):
        values=[]
        for text in texts:
            sid=slot_id(self.sample,f'embed_{self.query_index:02d}',0);self.query_index+=1
            values.append(self.step(sid,embedding_payload(text)))
        return values

    def identity(self):
        row=self.gate.rows[self.sample]
        return Inspector(self).identify_select(self.gate.root/row['image_path'],row['dataset'],CONFIG)

    def execute(self):
        identity=self.identity()
        if self.meta['stage'] in ('identify','select') or self.meta['role']=='embedding':return identity
        row=self.gate.rows[self.sample];pipeline=Inspector(self);image=self.gate.root/row['image_path']
        if self.meta['stage']=='whole':return pipeline.whole_portions(image,identity,row['dataset'])
        if self.meta['stage']=='conditional':
            identities,_=self.gate.identities()
            if identity!=identities[self.sample]:raise ValueError('O_conditional_coding_reconstruction_changed')
            context=self.gate.contexts().get(self.sample)
            if row['dataset']!='asa24' or context is None:raise ValueError('O_conditional_not_registered_Exact')
            if (set(context)!= {'code','options'} or context['code'] not in identity['final_codes']
                    or context['options']!=self.gate.ctx.catalog['asa_options'][context['code']]):
                raise ValueError('O_conditional_context_changed')
            return pipeline.conditional_portion(image,identity,context)
        raise ValueError('O_unknown_gate_stage')


class Gate:
    def __init__(self,ctx,ledger,*,root=ROOT,identity_loader=None,context_loader=None):
        self.ctx,self.ledger,self.root=ctx,ledger,root
        self.rows={r['sample_id']:r for r in ctx.rows}
        self.parser_sha256=ledger.parser_sha256
        self.manifest_sha256=sha(ROOT/'round10/prepared/embeddings.json') if root==ROOT else 'synthetic-manifest'
        self.identity_loader,self.context_loader=identity_loader,context_loader

    def identities(self):
        if self.identity_loader is not None:return self.identity_loader()
        from stores_o import sealed_identities
        return sealed_identities(self.ctx,self.ledger)

    def contexts(self):
        if self.context_loader is not None:return self.context_loader()
        from stores_o import sealed_contexts
        return sealed_contexts(self.ctx)

    def previous(self,sid,value):
        meta=self.ledger.slots.get(sid)
        if meta is None or meta['role']!=value['role']:raise ValueError('O_previous_task_slot_changed')
        h=request_hash(value)
        if value['role']=='embedding' and h in self.ctx.imports['entries']:
            usage=load(self.ledger.path('imports/'+sid+'.json'))
            expected={'slot':sid,'payload_hash':h,'manifest_sha256':self.manifest_sha256,
                      'value_hash':self.ctx.imports['entries'][h]['value_hash'],
                      'origin':self.ctx.imports['entries'][h]['origin']}
            if usage!=expected:raise ValueError('O_previous_import_usage_changed')
            return imported_value(self.ctx.imports,h)
        state=self.ledger.read()
        if state['bindings'].get(sid)!=h:raise ValueError('O_previous_exact_request_missing_or_changed')
        cached=self.ledger.target(h)['cache']
        if cached is None:raise ValueError('O_previous_answer_not_complete')
        return cached['value']

    def validate(self,sid,value):
        self.ctx.verify_sources()
        if sid not in self.ledger.slots:raise ValueError('O_unknown_task_slot')
        try:Machine(self,sid).execute()
        except Captured as capture:
            if capture.value!=value:raise ValueError('O_frozen_task_payload_changed')
            return True
        raise ValueError('O_task_not_reachable_from_frozen_previous_answers')

    def format_error(self,sid,raw):
        self.ctx.verify_sources()
        meta=self.ledger.slots.get(sid)
        if meta is None or meta['role']!='chat' or meta['ordinal']!=0:
            raise ValueError('O_format_parser_scope_changed')
        try:Machine(self,sid,format_raw=raw).execute()
        except Captured as capture:return capture.value
        raise ValueError('O_format_parser_not_reached')

    def verify_import(self,record):
        if set(record)!= {'slot','payload_hash','manifest_sha256','value_hash','origin'}:
            raise ValueError('O_import_record_schema_changed')
        sid=record['slot'];meta=self.ledger.slots.get(sid)
        if meta is None or meta['role']!='embedding':raise ValueError('O_import_task_role_changed')
        try:Machine(self,sid).execute()
        except Captured as capture:value=capture.value
        else:raise ValueError('O_import_task_unreachable')
        h=request_hash(value);entry=self.ctx.imports['entries'].get(h)
        if (entry is None or record['payload_hash']!=h or record['manifest_sha256']!=self.manifest_sha256
                or record['origin']!=entry['origin'] or record['value_hash']!=entry['value_hash']):
            raise ValueError('O_import_record_provenance_changed')
        if fingerprint(imported_value(self.ctx.imports,h))!=record['value_hash']:
            raise ValueError('O_import_vector_changed')
        return True


def frozen_gate(ledger):
    from context_o import runtime_context
    from service_o import allowed_slots
    ctx=runtime_context()
    if fingerprint(ctx.binding)!=ledger.binding or allowed_slots(ctx.rows)!=ledger.slots:
        raise ValueError('O_task_gate_not_bound_to_frozen_context')
    return Gate(ctx,ledger)
