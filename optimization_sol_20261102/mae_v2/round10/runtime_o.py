"""O-only lazy dual-route transport, explicit imports and exact stage replay."""
from contextlib import contextmanager
from copy import deepcopy
import json
import threading
import time

import httpx
from opt_provider import ProviderStop,read_credentials,sanitize,fingerprint
from service_o import (payload,embedding_payload,route,request_hash,slot_id)
from imports_o import imported_value,refuse_unregistered_old_state


class OProvider:
    def __init__(self,ledger,imports,*,allow_paid=False,keys=None,transport=None,sleep=time.sleep):
        if not allow_paid: raise ProviderStop('O_explicit_paid_authorization_required')
        self.ledger,self.imports,self.sleep=ledger,imports,sleep
        self.keys=tuple(keys) if keys is not None else read_credentials()
        if len(self.keys)!=2 or not all(self.keys) or self.keys[0]==self.keys[1]:
            raise ProviderStop('O_distinct_dual_credentials_required')
        self.client=httpx.Client(transport=transport,trust_env=False,follow_redirects=False,
            timeout=httpx.Timeout(read=600,connect=30,write=120,pool=120))

    def request(self,sid,value):
        h=request_hash(value);url,model,_=route(value);role=value['role']
        if role=='embedding':refuse_unregistered_old_state(self.imports,h)
        with self.ledger.lock('payload-'+h):
            self.ledger.bind(sid,value)
            old=self.ledger.target(h,recover=True);before=old['cache'] is not None
            if old['fatal']:raise ProviderStop('O_permanent_service_failure_preserved')
            while old['cache'] is None:
                self.ledger.verify_task(sid,value)
                reservation=self.ledger.reserve(sid,h)
                try:
                    response=self.client.post(url,json=value['payload'],
                        headers={'Authorization':'Bearer '+self.keys[0 if role=='chat' else 1]})
                except httpx.HTTPError as exc:
                    outcome={'kind':'retryable','status':None,'error_type':type(exc).__name__,'body':None}
                else:
                    try:body=response.json()
                    except ValueError:body=None
                    body=sanitize(body,self.keys)
                    try:json.dumps(body,allow_nan=False)
                    except (ValueError,TypeError,OverflowError):
                        body={'invalid_json_numeric':True,'raw_redacted_text':sanitize(response.text,self.keys)}
                    outcome={'kind':'fatal','status':response.status_code,'body':body,'error_type':None}
                    if response.status_code==429 or response.status_code>=500:
                        outcome['kind']='retryable'
                    elif response.status_code==200 and isinstance(body,dict) and body.get('model')==model:
                        try:
                            if role=='chat':
                                choice=body['choices'][0];content=choice['message']['content']
                                answer=content if choice.get('finish_reason')=='stop' else ''
                            else:
                                answer=body['data'][0]['embedding']
                            success={**outcome,'kind':'success','value':answer,'value_hash':fingerprint(answer)}
                            self.ledger.validate_outcome({'reservation':reservation,**success},reservation)
                        except (ValueError,KeyError,TypeError,IndexError,OverflowError): pass
                        else: outcome=success
                self.ledger.persist(reservation,outcome)
                old=self.ledger.target(h)
                if old['fatal']:raise ProviderStop('O_authentication_model_or_permanent_service_failure')
                if old['cache'] is None:
                    if old['reserved']>=3:raise ProviderStop('O_transport_budget_exhausted')
                    self.sleep((2,8)[old['reserved']-1])
            cached=old['cache']
            return cached['value'],{'slot':sid,'payload_hash':h,'value_hash':cached['value_hash'],
                'reservation_id':cached['reservation_id'],'cache_present_before':before,'origin':'new_O'}

    def close(self):self.client.close()


class Trace:
    def __init__(self,ledger,imports,manifest_sha256,*,allow_paid=False):
        self.ledger,self.imports,self.manifest_sha256=ledger,imports,manifest_sha256
        self.allow_paid=allow_paid;self.provider=None
        self.local,self.guard=threading.local(),threading.Lock()

    @contextmanager
    def expect(self,sample,stage,image_url=None,refs=None):
        if getattr(self.local,'scope',None) is not None:raise ValueError('O_nested_stage_scope')
        self.local.scope={'sample':sample,'stage':stage,'image':fingerprint(image_url) if image_url else None,
                          'refs':refs if refs is not None else []}
        try:yield self.local.scope['refs']
        finally:self.local.scope=None

    def get(self):
        with self.guard:
            if self.provider is None:
                self.provider=OProvider(self.ledger,self.imports,allow_paid=self.allow_paid)
        return self.provider

    def request(self,sid,value):
        self.ledger.verify_task(sid,value)
        h=request_hash(value)
        if value['role']=='embedding' and h in self.imports['entries']:
            vector=imported_value(self.imports,h)
            entry=self.imports['entries'][h]
            usage=self.ledger.import_usage(sid,value,self.manifest_sha256,fingerprint(vector),entry['origin'])
            return vector,{**usage,'reservation_id':None,'cache_present_before':True}
        return self.get().request(sid,value)

    def chat(self,messages):
        scope=getattr(self.local,'scope',None)
        if scope is None or scope['stage'] not in ('identify','select','whole','conditional'):
            raise ValueError('O_chat_outside_registered_stage')
        urls=[b['image_url']['url'] for m in messages if isinstance(m.get('content'),list)
              for b in m['content'] if b.get('type')=='image_url']
        if len(urls)!=1 or fingerprint(urls[0])!=scope['image']:
            raise ValueError('O_exact_query_image_changed')
        ordinal=len(scope['refs']);sid=slot_id(scope['sample'],scope['stage'],ordinal)
        if ordinal==1:
            initial=slot_id(scope['sample'],scope['stage'],0)
            state=self.ledger.read();cache=self.ledger.target(state['bindings'][initial])['cache']
            if cache is None:raise ValueError('O_repair_without_initial_answer')
            raw=cache['value'];error=self.ledger.task_gate().format_error(initial,raw)
            if error is None:raise ValueError('O_valid_answer_cannot_acquire_repair')
            self.ledger.format_failure(initial,raw,error,self.ledger.parser_sha256)
        value,ref=self.request(sid,payload(messages));scope['refs'].append(ref)
        return value

    def embed(self,texts):
        scope=getattr(self.local,'scope',None)
        if (scope is None or scope['stage']!='retrieval' or not isinstance(texts,list)
                or not 1<=len(texts)<=12):raise ValueError('O_embedding_outside_fixed_query_stage')
        result=[]
        for text in texts:
            index=len(scope['refs']);sid=slot_id(scope['sample'],f'embed_{index:02d}',0)
            value,ref=self.request(sid,embedding_payload(text));scope['refs'].append(ref);result.append(value)
        return result

    def close(self):
        if self.provider is not None:self.provider.close()


def verify_reference(ledger,imports,manifest_sha256,ref,value):
    fields={'slot','payload_hash','value_hash','reservation_id','cache_present_before','origin'}
    if ref.get('origin') in ('legacy','M'):fields.add('manifest_sha256')
    if set(ref)!=fields or type(ref.get('cache_present_before')) is not bool:
        raise ValueError('O_replay_reference_schema_changed')
    sid=ref['slot'];h=request_hash(value)
    ledger.verify_task(sid,value)
    if ref['payload_hash']!=h:raise ValueError('O_replay_payload_changed')
    if ref['origin']=='new_O':
        if ledger.read()['bindings'].get(sid)!=h:raise ValueError('O_replay_slot_binding_changed')
        cache=ledger.target(h)['cache']
        if cache is None or cache['reservation_id']!=ref['reservation_id']:
            raise ValueError('O_replay_reservation_changed')
        answer=cache['value']
    else:
        if (ref['origin'] not in ('legacy','M') or ref['manifest_sha256']!=manifest_sha256
                or imports['entries'].get(h,{}).get('origin')!=ref['origin']):
            raise ValueError('O_replay_import_origin_or_manifest_changed')
        usage={'slot':sid,'payload_hash':h,'manifest_sha256':manifest_sha256,
               'value_hash':ref['value_hash'],'origin':ref['origin']}
        from service_o import load
        if (ref['reservation_id'] is not None or load(ledger.path('imports/'+sid+'.json'))!=usage
                or value['role']!='embedding'):
            raise ValueError('O_replay_import_usage_changed')
        answer=imported_value(imports,h)
    if fingerprint(answer)!=ref['value_hash']:raise ValueError('O_replay_return_value_changed')
    return answer
