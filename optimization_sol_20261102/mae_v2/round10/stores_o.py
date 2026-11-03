"""O's separate coding, conditional-adapter and complete-prediction seals."""
from copy import deepcopy

from opt_provider import ROOT,sha,fingerprint
from context_o import ROUND,require
from round4.src.artifacts import ArtifactStore
from service_o import load


def name(prefix,row):return prefix+'-'+fingerprint(row['sample_id'])[:32]


def identity_store(ctx):
    return ArtifactStore(ROUND/'runs/identities',ctx.binding,
        [name('identity',r) for r in ctx.rows]+['service-proof'],
        verify_sources=ctx.verify_sources,root=ROUND)


def final_store(ctx):
    return ArtifactStore(ROUND/'runs/development',ctx.binding,
        [name('record',r) for r in ctx.rows]+['service-proof'],
        verify_sources=ctx.verify_sources,root=ROUND)


def proof_for_refs(ledger,refs):
    flat=[ref for group in refs.values() for ref in group]
    state=ledger.read();bindings={};hashes=set();files={}
    for ref in flat:
        sid,h=ref['slot'],ref['payload_hash']
        if ref['origin']=='new_O':
            require(state['bindings'].get(sid)==h,'O_identity_request_binding_changed')
            cached=ledger.target(h)['cache']
            require(cached is not None and cached['reservation_id']==ref['reservation_id']
                    and cached['value_hash']==ref['value_hash'],'O_identity_request_value_changed')
            bindings[sid]=h;hashes.add(h)
            files['responses/'+h+'.json']=sha(ledger.cache_path(h))
        else:
            path=ledger.path('imports/'+sid+'.json')
            usage=load(path)
            require(all(usage[k]==ref[k] for k in usage),'O_identity_import_usage_changed')
            ledger.task_gate().verify_import(usage)
            files['imports/'+sid+'.json']=sha(path)
    reservations=[r for r in state['reservations'] if r['payload_hash'] in hashes]
    anchors={}
    for reservation in reservations:
        rid=reservation['id']
        if rid in state['outcomes']:
            anchors[rid]=state['outcomes'][rid]
            files['outcomes/'+rid+'.json']=sha(ledger.outcome_path(rid))
    return {'bindings':bindings,'reservations':deepcopy(reservations),'outcomes':anchors,
            'files':files,'request_refs_sha256':fingerprint(refs),'logical_answers':len(flat)}


def verify_proof(ledger,proof):
    state=ledger.read()
    require(all(state['bindings'].get(sid)==h for sid,h in proof['bindings'].items()),
            'O_sealed_identity_bindings_changed')
    hashes=set(proof['bindings'].values())
    require([r for r in state['reservations'] if r['payload_hash'] in hashes]==proof['reservations'],
            'O_sealed_identity_reservations_changed')
    require(all(state['outcomes'].get(rid)==h for rid,h in proof['outcomes'].items()),
            'O_sealed_identity_outcome_anchors_changed')
    for relative,expected in proof['files'].items():
        path=ledger.path(relative)
        require(sha(path)==expected,'O_sealed_identity_service_file_changed')
        if relative.startswith('imports/'):
            ledger.task_gate().verify_import(load(path))
    return True


def sealed_identities(ctx,ledger):
    records=identity_store(ctx).verify_completed()
    verify_proof(ledger,records['service-proof'])
    identities={r['sample_id']:records[name('identity',r)] for r in ctx.rows}
    return identities,{'complete':True,'identity_records_sha256':fingerprint(identities)}


def adapter_store(ctx):
    binding={'science':ctx.binding,'coding_completion_sha256':sha(ROUND/'runs/identities/completion.json'),
             'labels_sha256':ctx.binding['labels_sha256'],'role':'post_coding_ASA_code_and_full_catalogue_only'}
    return ArtifactStore(ROUND/'runs/conditional-adapter',binding,['contexts','provenance'],
                         verify_sources=ctx.verify_sources,root=ROUND)


def sealed_contexts(ctx):
    values=adapter_store(ctx).verify_completed()
    require(values['provenance']['coding_completion_sha256']==sha(ROUND/'runs/identities/completion.json')
            and values['provenance']['labels_sha256']==ctx.binding['labels_sha256'],
            'O_conditional_adapter_provenance_changed')
    return values['contexts']
