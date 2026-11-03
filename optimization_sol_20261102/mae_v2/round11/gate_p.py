"""Reconstruct actual frozen Pipeline tasks from durable earlier answers."""
from copy import deepcopy

from opt_provider import ROOT,sha,fingerprint
from opt_pipeline import ContractError,encode_image
from source_portions import SourcePortionPipeline,CONFIG
from service_p import (payload,embedding_payload,slot_id,request_hash,load)
from paired_stage_pipeline import PairedStagePipeline

STAGES={'identify':'identify','select':'select','source_standard_first':'whole',
        'portion_conditional_option_continuous_option':'conditional',
        'paired_quantity':'quantity','paired_density':'density'}


class Captured(BaseException):
    def __init__(self,value):self.value=value


class Inspector(PairedStagePipeline):
    def __init__(self,machine):
        self.machine=machine
        super().__init__(machine.chat,machine.embed,machine.gate.ctx.catalog,machine.gate.ctx.retriever)

    def _stage(self,name,prompt,image,parser,stages):
        stage=STAGES.get(name)
        if stage is None:raise ValueError('P_unregistered_scientific_stage')
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
        if self.meta['stage'] in ('whole','quantity','density','conditional'):
            identities,_=self.gate.identities()
            if identity!=identities.get(self.sample):raise ValueError('P_verified_identity_reconstruction_changed')
        if self.meta['stage']=='whole':return pipeline.whole_portions(image,identity,row['dataset'])
        if self.meta['stage']=='quantity':return pipeline.quantity_intervention(image,identity,row['dataset'])
        if self.meta['stage']=='density':return pipeline.density_intervention(image,identity,row['dataset'])
        if self.meta['stage']=='conditional':
            identities,_=self.gate.identities()
            if identity!=identities[self.sample]:raise ValueError('P_conditional_coding_reconstruction_changed')
            context=self.gate.contexts().get(self.sample)
            if row['dataset']!='asa24' or context is None:raise ValueError('P_conditional_not_registered_Exact')
            if (set(context)!= {'code','options'} or context['code'] not in identity['final_codes']
                    or context['options']!=self.gate.ctx.catalog['asa_options'][context['code']]):
                raise ValueError('P_conditional_context_changed')
            return pipeline.conditional_portion(image,identity,context)
        raise ValueError('P_unknown_gate_stage')


class Gate:
    def __init__(self,ctx,ledger,*,root=ROOT,identity_loader=None,context_loader=None):
        self.ctx,self.ledger,self.root=ctx,ledger,root
        from service_p import allowed_slots
        images={r['sample_id']:fingerprint(encode_image(root/r['image_path'],'square256')) for r in ctx.rows}
        if allowed_slots(ctx.rows,image_hashes=images)!=ledger.slots:
            raise ValueError('P_frozen_rows_or_slots_changed')
        self.rows={r['sample_id']:deepcopy(r) for r in ctx.rows}
        self.parser_sha256=ledger.parser_sha256
        self.manifest_sha256=getattr(ctx,'manifest_sha256',None)
        if (type(self.manifest_sha256) is not str or len(self.manifest_sha256)!=64
                or any(c not in '0123456789abcdef' for c in self.manifest_sha256)):
            raise ValueError('P_explicit_embedding_manifest_required')
        self.catalog_sha256=fingerprint(ctx.catalog)
        self.imports_sha256=fingerprint(ctx.imports)
        self.identity_loader,self.context_loader=identity_loader,context_loader
        self._snapshot=None

    def verify_context(self):
        self.ctx.verify_sources()
        if (getattr(self.ctx,'manifest_sha256',None)!=self.manifest_sha256
                or fingerprint(self.ctx.catalog)!=self.catalog_sha256
                or fingerprint(self.ctx.imports)!=self.imports_sha256):
            raise ValueError('P_frozen_context_changed')
        from service_p import allowed_slots
        images={r['sample_id']:fingerprint(encode_image(self.root/r['image_path'],'square256')) for r in self.ctx.rows}
        if ({r['sample_id']:r for r in self.ctx.rows}!=self.rows
                or allowed_slots(self.ctx.rows,image_hashes=images)!=self.ledger.slots):
            raise ValueError('P_frozen_rows_or_slots_changed')

    def identities(self):
        if self.identity_loader is not None:return self.identity_loader()
        return self.coding_snapshot().load()

    def contexts(self):
        if self.context_loader is not None:return self.context_loader()
        from stores_p import verified_contexts,adapter_store
        return verified_contexts(self.ctx,self.ledger,self.coding_snapshot(),adapter_store(self.ctx))

    def coding_snapshot(self):
        if self._snapshot is None:
            from identity_gate_p import coding_snapshot
            self._snapshot=coding_snapshot(self.ctx,self.ledger)
        return self._snapshot

    def previous(self,sid,value):
        meta=self.ledger.slots.get(sid)
        if meta is None or meta['role']!=value['role']:raise ValueError('P_previous_task_slot_changed')
        if meta['ordinal']==1:self.verify_repair(sid)
        h=request_hash(value)
        if value['role']=='embedding' and h in self.ctx.imports['entries']:
            usage=load(self.ledger.path('imports/'+sid+'.json'))
            expected={'slot':sid,'payload_hash':h,'manifest_sha256':self.manifest_sha256,
                      'value_hash':self.ctx.imports['entries'][h]['value_hash'],
                      'origin':self.ctx.imports['entries'][h]['origin']}
            if usage!=expected:raise ValueError('P_previous_import_usage_changed')
            from imports_p import imported_value
            return imported_value(self.ctx.imports,h)
        state=self.ledger.read()
        if state['bindings'].get(sid)!=h:raise ValueError('P_previous_exact_request_missing_or_changed')
        cached=self.ledger.target(h)['cache']
        if cached is None:raise ValueError('P_previous_answer_not_complete')
        return cached['value']

    def validate(self,sid,value):
        self.verify_context()
        if sid not in self.ledger.slots:raise ValueError('P_unknown_task_slot')
        if self.ledger.slots[sid]['ordinal']==1:self.verify_repair(sid)
        try:Machine(self,sid).execute()
        except Captured as capture:
            if capture.value!=value:raise ValueError('P_frozen_task_payload_changed')
            return True
        raise ValueError('P_task_not_reachable_from_frozen_previous_answers')

    def verify_repair(self,sid):
        meta=self.ledger.slots[sid]
        initial=slot_id(meta['sample_id'],meta['stage'],0)
        state=self.ledger.read();proof=state['repairs'].get(initial)
        h=state['bindings'].get(initial)
        cached=self.ledger.target(h)['cache'] if h else None
        if (proof is None or cached is None
                or proof!={'raw_hash':fingerprint(cached['value']),
                           'error':self.format_error(initial,cached['value']),
                           'parser_sha256':self.parser_sha256}
                or proof['error'] is None):
            raise ValueError('P_repair_proof_not_actual_cached_failure')

    def format_error(self,sid,raw):
        self.verify_context()
        meta=self.ledger.slots.get(sid)
        if meta is None or meta['role']!='chat' or meta['ordinal']!=0:
            raise ValueError('P_format_parser_scope_changed')
        try:Machine(self,sid,format_raw=raw).execute()
        except Captured as capture:return capture.value
        raise ValueError('P_format_parser_not_reached')

    def verify_import(self,record):
        self.verify_context()
        if set(record)!= {'slot','payload_hash','manifest_sha256','value_hash','origin'}:
            raise ValueError('P_import_record_schema_changed')
        sid=record['slot'];meta=self.ledger.slots.get(sid)
        if meta is None or meta['role']!='embedding':raise ValueError('P_import_task_role_changed')
        try:Machine(self,sid).execute()
        except Captured as capture:value=capture.value
        else:raise ValueError('P_import_task_unreachable')
        h=request_hash(value);entry=self.ctx.imports['entries'].get(h)
        if (entry is None or record['payload_hash']!=h or record['manifest_sha256']!=self.manifest_sha256
                or record['origin']!=entry['origin'] or record['value_hash']!=entry['value_hash']):
            raise ValueError('P_import_record_provenance_changed')
        from imports_p import imported_value
        if fingerprint(imported_value(self.ctx.imports,h))!=record['value_hash']:
            raise ValueError('P_import_vector_changed')
        return True


def frozen_gate(ledger):
    from context_p import runtime_context
    ctx=runtime_context()
    if ledger.binding!=fingerprint(ctx.binding) or ledger.directory!=ROOT/'round11/provider/P':
        raise ValueError('P_frozen_ledger_science_or_root_changed')
    ctx.verify_sources()
    return Gate(ctx,ledger,root=ROOT)
