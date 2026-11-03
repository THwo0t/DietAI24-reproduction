#!/usr/bin/env python3
"""Offline-only label projection after the complete O coding seal."""
import json
from pathlib import Path
import sys

sys.dont_write_bytecode=True
BASE=Path(__file__).resolve().parent.parent
sys.path[:0]=[str(BASE),str(BASE/'src'),str(BASE/'round7/src'),str(BASE/'round8/src'),str(BASE/'round10')]

from opt_provider import ROOT,sha
from context_o import runtime_context,ROUND,require
from service_o import Ledger,allowed_slots
from stores_o import sealed_identities,adapter_store
from conditional_o import contexts_after_seal,code_only
from round4.src.artifacts import decode


def prepare(ctx=None,ledger=None):
    ctx=runtime_context() if ctx is None else ctx
    ledger=Ledger(ROUND/'provider/O',ctx.binding,allowed_slots(ctx.rows)) if ledger is None else ledger
    identities,proof=sealed_identities(ctx,ledger) # All183 coding before labels.
    labels_path=ROOT/'data/cohorts/dev_labels.json'
    require(sha(labels_path)==ctx.binding['labels_sha256'],'O_adapter_label_binding_changed')
    labels=decode(labels_path.read_bytes())
    require(set(labels)=={r['sample_id'] for r in ctx.rows},'O_adapter_label_population_changed')
    contexts=contexts_after_seal(ctx.rows,identities,ctx.catalog,code_only(labels,ctx.rows),proof)
    # Do not retain the full label object or expose it to the caller/process.
    del labels
    require(sha(labels_path)==ctx.binding['labels_sha256'],'O_adapter_labels_changed_during_projection')
    provenance={'coding_completion_sha256':sha(ROUND/'runs/identities/completion.json'),
        'labels_sha256':ctx.binding['labels_sha256'],'adapter_source_sha256':sha(Path(__file__)),
        'input_rows':len(ctx.rows),'Exact_contexts':len(contexts),'permitted_fields':['code','options'],
        'current_portion_truth_exported':False,'api_calls':0,'validation_opened':False}
    store=adapter_store(ctx);values={'contexts':contexts,'provenance':provenance}
    if (store.directory/'completion.json').is_file():
        require(store.verify_completed()==values,'O_existing_conditional_projection_changed')
    else:store.finalize(values)
    return {'status':'O_conditional_adapter_sealed','Exact_contexts':len(contexts),'api_calls':0,
            'current_portion_truth_exported':False,'validation_opened':False}


if __name__=='__main__':
    import socket,httpx,opt_provider
    def forbidden(*args,**kwargs):raise AssertionError('O_adapter_provider_and_network_forbidden')
    socket.socket=forbidden;socket.create_connection=forbidden
    httpx.Client=forbidden;opt_provider.Provider=forbidden;opt_provider.read_credentials=forbidden
    try:print(json.dumps(prepare()))
    except Exception as exc:
        print(json.dumps({'status':'O_adapter_refused','error_type':type(exc).__name__}))
        raise SystemExit(1)
