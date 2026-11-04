"""User-requested direct 32-thread continuation, without repeated full audits.

Scientific stage functions, model/credential routes, parsing, fallback and OOF
scoring are retained. This entry does not claim the old provenance replay seals.
"""
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from copy import deepcopy
import datetime
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from types import SimpleNamespace

BASE = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(BASE), *(str(BASE/p) for p in
    ('src','round7/src','round8/src','round10','round11'))]
import numpy as np
from opt_provider import ROOT, fingerprint, sha
from opt_pipeline import Retriever
from runtime_p import Trace
from engine_p import RowLive, identify, portions, quantity, density
from stores_p import identity_store, name
from records_p import compose_record, attach_conditional
from round4.src.artifacts import ArtifactStore
from direct_ledger import FastLedger


def load(path):
    return json.loads(Path(path).read_bytes())


def write(path, value):
    path = Path(path)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    pending = path.with_name(path.name+'.tmp')
    fd = os.open(pending, os.O_WRONLY|os.O_CREAT|os.O_TRUNC|os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'w') as stream:
        json.dump(value, stream, sort_keys=True, allow_nan=False)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(pending, path)


def emit(**value):
    print(json.dumps({'utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
                      **value}, sort_keys=True), flush=True)


def context():
    common = load(BASE/'round11/prepared/common.json')
    catalog = load(BASE/'round11/prepared/catalog.json')
    vectors = np.load(BASE/'data/vectors/embeddings.npy', allow_pickle=False)
    retriever = Retriever(load(BASE/'data/vectors/codes.json'), vectors, catalog)
    retriever.vectors.setflags(write=False)
    return SimpleNamespace(rows=load(BASE/'round11/prepared/cohort/dev.json'),
        catalog=catalog, retriever=retriever,
        fallbacks=load(BASE/'round11/prepared/fallbacks.json'),
        calibration=load(BASE/'round11/prepared/calibration.json'),
        imports=load(BASE/'round11/prepared/embeddings.json'),
        manifest_sha256=common['hashes']['embeddings'],
        binding=load(BASE/'round11/prepared/freeze.json'),
        verify_sources=lambda:True)


def parallel(stage, rows, operation):
    rows = iter(rows)
    results = {}
    start = last = time.monotonic()
    with ThreadPoolExecutor(max_workers=32) as pool:
        pending = {}
        def submit():
            try:
                row = next(rows)
            except StopIteration:
                return
            pending[pool.submit(operation, row)] = row
        for _ in range(32):
            submit()
        while pending:
            finished, _ = wait(pending, timeout=15, return_when=FIRST_COMPLETED)
            for future in finished:
                row = pending.pop(future)
                results[row['sample_id']] = future.result()
            if finished and (len(results)%20 == 0 or time.monotonic()-last >= 15):
                emit(stage=stage, completed=len(results), total=843,
                     elapsed_seconds=round(time.monotonic()-start,1))
                last = time.monotonic()
            for _ in finished:
                submit()
    emit(stage=stage, completed=len(results), total=843,
         elapsed_seconds=round(time.monotonic()-start,1))
    return results


def main():
    if sys.argv[1:] != ['--allow-paid']:
        raise ValueError('direct_explicit_paid_flag_required')
    emit(status='direct_starting', workers=32, repeated_full_audits=False)
    ctx = context()
    if len(ctx.rows) != 843:
        raise ValueError('direct_population_changed')
    saved = load(BASE/'round11/provider/P/admission.json')
    ledger = FastLedger(BASE/'round11/provider/P', ctx.binding, saved['allowed_slots'])
    ids = identity_store(ctx)
    out = ArtifactStore(HERE/'prediction_stages', ctx.binding,
        [name('record', row) for row in ctx.rows], verify_sources=ctx.verify_sources,
        root=BASE/'round11')
    ids.initialize()
    out.initialize()
    identities, contexts = {}, {}
    # Only format-repair paths need the original Gate parser. Its source scan
    # callback is intentionally cheap in this user-requested direct mode.
    from gate_p import Gate
    class RepairParser(Gate):
        """Original parser reconstruction only; normal admission uses FastLedger."""
        def __init__(self):
            self.ctx, self.ledger, self.root = ctx, ledger, ROOT
            self.rows = {row['sample_id']:row for row in ctx.rows}
            self.manifest_sha256 = ctx.manifest_sha256
            self.parser_sha256 = ledger.parser_sha256
            self.identity_loader = lambda:({sid:value['result'] for sid,value in identities.items()}, {})
            self.context_loader = lambda:deepcopy(contexts)
        def verify_context(self):
            # No full-image conversion/source scan: the user explicitly asked
            # for direct execution. Actual request role/model/image and output
            # parser contracts are still checked at their normal boundaries.
            return None
    ledger._gate = RepairParser()
    trace = Trace(ledger, ctx.imports, ctx.manifest_sha256, allow_paid=True)
    def stage(store, stem, row, operation, inputs):
        return store.stage_runner(stem, inputs,
            lambda:operation(RowLive(row, trace)), validator=lambda value:value)
    def identity_row(row):
        return stage(ids, name('identity', row), row,
            lambda client:identify(ctx, row, client, root=ROOT),
            {'row_sha256':fingerprint(row), 'image_sha256':row['image_sha256']})
    try:
        identities.update(parallel('identities', ctx.rows, identity_row))
        write(HERE/'identities.json', identities)
        identity_sha = sha(HERE/'identities.json')
        from adapter_p import CLEAN_ENV
        child = subprocess.run(['/usr/bin/unshare','-Urn',sys.executable,'-B',
            str(HERE/'direct_adapter.py')], cwd=ROOT, env=dict(CLEAN_ENV),
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        if child.returncode != 0:
            raise ValueError('direct_isolated_adapter_failed')
        contexts.update(load(HERE/'contexts.json'))
        emit(status='direct_coding_complete', rows=843, ASA_Exact_contexts=len(contexts))
        def predict(row):
            sid, stem = row['sample_id'], name('record', row)
            path = HERE/'records_individual'/(fingerprint(sid)+'.json')
            if path.is_file():
                return load(path)
            identity = identities[sid]
            inputs = {'row_sha256':fingerprint(row),
                'identity_sha256':fingerprint(identity['result']),
                'coding_completion_sha256':identity_sha}
            if identity['result'].get('status') == 'ok':
                stages = {kind:stage(out, stem+'-'+kind, row,
                    lambda client, op=operation:op(ctx,row,identity['result'],client,root=ROOT), inputs)
                    for kind,operation in [('whole',portions),('quantity',quantity),('density',density)]}
            else:
                stages = {kind:None for kind in ('whole','quantity','density')}
            fallback = ctx.fallbacks['folds'][row['dataset']][str(row['fold'])]
            refs = {kind:envelope['request_refs'] for kind,envelope in
                    [('identity',identity),*stages.items()] if envelope is not None}
            record = compose_record(row,identity,stages['whole'],stages['quantity'],stages['density'],
                ctx.catalog,fallback['value'],evidence_binding={
                    'row_sha256':fingerprint(row),'identity_seal_sha256':identity_sha,
                    'request_proof_sha256':fingerprint(refs),
                    'fallback_binding_sha256':fingerprint({'science':ctx.binding,
                        'dataset':row['dataset'],'fold':row['fold'],'training_fold':fallback})})
            if sid in contexts:
                optional = contexts[sid]
                conditional = stage(out,stem+'-conditional',row,
                    lambda client:portions(ctx,row,identity['result'],client,
                        conditional_context=optional,root=ROOT),
                    {**inputs,'task_context_sha256':fingerprint(optional)})
                record = attach_conditional(record,conditional,optional,ctx.catalog,
                    adapter_binding={'identity_seal_sha256':identity_sha,
                        'context_sha256':fingerprint(optional),
                        'request_proof_sha256':fingerprint(conditional['request_refs'])})
            write(path,record)
            return record
        records = parallel('predictions',ctx.rows,predict)
        write(HERE/'records.json',records)
        emit(status='direct_inference_complete', rows=len(records))
    finally:
        trace.close()
        if hasattr(ledger, 'flush_original'):
            ledger.flush_original()
    # Provider has been closed and every prediction is durable before the
    # scoring process is permitted to load development numerical labels.
    child = subprocess.run(['/usr/bin/unshare','-Urn',sys.executable,'-B',
        str(HERE/'direct_scoring.py')], cwd=ROOT, env=dict(CLEAN_ENV),
        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    if child.returncode != 0:
        raise ValueError('direct_scoring_failed')
    emit(status='direct_scoring_complete', summary=str(HERE/'summary.json'))


if __name__ == '__main__':
    try:
        main()
    except BaseException as error:
        emit(status='direct_stopped_preserve_state', error_type=type(error).__name__)
        raise SystemExit(1) from None
