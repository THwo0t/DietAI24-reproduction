"""Engineering-bound process orchestration over the unchanged frozen P science.

Only this process initializes and seals stores. Workers own disjoint rows and
retain the original payload/admission locks and exact scientific replay.
"""
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
from copy import deepcopy
import argparse
import json
import multiprocessing
from pathlib import Path
import sys
import time

BASE = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(Path(__file__).resolve().parent), str(BASE), *(str(BASE / p) for p in
    ('src', 'round7/src', 'round8/src', 'round10', 'round11'))]

from opt_provider import ROOT, fingerprint, sha
from service_p import Ledger, allowed_slots
from stores_p import (name, identity_store, final_store, adapter_store,
                      proof_for_refs)
from identity_gate_p import build_loader
from run_p import require, _contexts, _isolated_adapter


class _Progress:
    """Metadata only: never emits row identifiers, responses or errors."""
    def __init__(self, stage, total):
        self.stage, self.total, self.completed = stage, total, 0
        self.started = self.last_time = time.monotonic()
        self.last_count = 0
        self.update(force=True)

    def update(self, completed=None, *, force=False):
        if completed is not None:
            self.completed = completed
        now = time.monotonic()
        if force or self.completed - self.last_count >= 20 or now - self.last_time >= 30:
            print(json.dumps({'stage': self.stage, 'completed': self.completed,
                              'total': self.total, 'elapsed': round(now - self.started, 3)},
                             sort_keys=True), flush=True)
            self.last_count, self.last_time = self.completed, now


def _bounded_results(task, arguments, workers, initializer, *, heartbeat=None):
    """At most workers submitted tasks; stop refilling on any observed failure.

    Do not cancel/kill running API calls. Executor shutdown drains every task
    already submitted before the first error is propagated to the controller.
    """
    iterator = iter(arguments)
    with ProcessPoolExecutor(max_workers=workers,
                             mp_context=multiprocessing.get_context('fork'),
                             initializer=initializer) as pool:
        pending = {}

        def submit_one():
            try:
                args = next(iterator)
            except StopIteration:
                return False
            pending[pool.submit(task, *args)] = args
            return True

        for _ in range(workers):
            if not submit_one():
                break
        while pending:
            finished, _ = wait(pending, timeout=30, return_when=FIRST_COMPLETED)
            if heartbeat is not None:
                heartbeat()
            if not finished:
                continue
            completed = []
            failure = None
            # Inspect the entire completed set before submitting replacement
            # work: a simultaneous success must not hide a failed sibling.
            for future in finished:
                args = pending.pop(future)
                try:
                    completed.append((args, future.result()))
                except BaseException as error:
                    if failure is None:
                        failure = error
            if failure is not None:
                for future in pending:
                    try:
                        future.result()
                    except BaseException:
                        pass
                raise failure
            for args, result in completed:
                yield args, result
            for _ in completed:
                if not submit_one():
                    break


def _execute(engineering, workers, allow_paid):
    """Fixed production dependencies; synthetic tests patch module boundaries."""
    from context_p import runtime_context
    import p_parallel_registration as registration
    from round11.parallel_acceleration import p_parallel_worker as worker

    registration.verify_engineering(engineering)
    ctx = runtime_context()
    ctx.verify_sources()
    require(ROOT.is_absolute() and ROOT.resolve() == ROOT,
            'P_runner_absolute_root_required')
    require(ctx.binding.get('schema_version') == 1,
            'P_runner_scientific_freeze_required')
    ledger = Ledger(ROOT / 'round11/provider/P', ctx.binding, allowed_slots(ctx.rows))
    require(ledger.binding == fingerprint(ctx.binding),
            'P_runner_ledger_science_binding_changed')
    ids, out = identity_store(ctx), final_store(ctx)
    require(ids.binding == ctx.binding and out.binding == ctx.binding,
            'P_runner_artifact_science_binding_changed')
    require(set(ids.expected_records) == {name('identity', r) for r in ctx.rows} | {'service-proof'}
            and set(out.expected_records) == {name('record', r) for r in ctx.rows} | {'service-proof'},
            'P_runner_artifact_population_changed')
    id_complete = (ids.directory / 'completion.json').is_file()
    complete = (out.directory / 'completion.json').is_file()
    require(not complete or id_complete, 'P_final_without_complete_coding')
    if complete:
        adapter = adapter_store(ctx)
        require((adapter.directory / 'completion.json').is_file(),
                'P_complete_replay_requires_existing_adapter_seal')
        ids.verify_completed()
        out.verify_completed()
        adapter.verify_completed()
    require(complete or allow_paid, 'P_paid_flag_required_for_incomplete_batch')
    if not complete:
        ledger.initialize()
        ledger.recover_pending()
        if not id_complete:
            ids.initialize()
        out.initialize()
    ledger.audit(complete=complete)
    registration.verify_engineering(engineering)

    identities, envelopes, id_refs, all_refs, records = {}, {}, {}, {}, {}
    provider_constructed = False
    # Preload the unchanged original Gate before fork. Its context/image
    # caches are read-only science state; no Trace or HTTP client exists here.
    ledger.task_gate()
    worker.configure(ctx, ledger, ids, out, id_complete, complete,
                     engineering=engineering, allow_paid=allow_paid and not complete)
    progress = _Progress('identities', len(ctx.rows))
    for (row,), result in _bounded_results(worker.identity_task,
            ((row,) for row in ctx.rows), workers, worker.initialize_forked_worker,
            heartbeat=progress.update):
        registration.verify_engineering(engineering)
        envelope = result['envelope']
        require(type(envelope) is dict and set(envelope) == {'result', 'request_refs'},
                'P_scientific_envelope_changed')
        require(type(result['provider_constructed']) is bool,
                'P_parallel_provider_audit_required')
        provider_constructed |= result['provider_constructed']
        sid, stem = row['sample_id'], name('identity', row)
        identities[sid], envelopes[sid] = envelope['result'], envelope
        for phase, refs in envelope['request_refs'].items():
            id_refs[stem + '-' + phase] = deepcopy(refs)
            all_refs[stem + '-' + phase] = deepcopy(refs)
        progress.update(len(identities))
    progress.update(len(identities), force=True)
    require(set(identities) == {r['sample_id'] for r in ctx.rows},
            'P_parallel_incomplete_identity_population')
    coding = {name('identity', r): identities[r['sample_id']] for r in ctx.rows}
    coding['service-proof'] = proof_for_refs(ledger, id_refs)
    ctx.verify_sources()
    registration.verify_engineering(engineering)
    if id_complete:
        require(ids.verify_completed() == coding, 'P_sealed_coding_changed')
    else:
        ids.finalize(coding)

    snapshot = build_loader(ctx, ledger, ids, data_root=ROOT, envelopes=envelopes)
    ledger.task_gate().identity_loader = snapshot.load
    identity_seal = sha(ids.directory / 'completion.json')
    adapter = adapter_store(ctx)
    if not (adapter.directory / 'completion.json').is_file():
        _isolated_adapter(ctx, ledger, snapshot)
    contexts = _contexts(ctx, adapter, snapshot, identity_seal)
    ledger.task_gate().context_loader = lambda: deepcopy(contexts)
    registration.verify_engineering(engineering)

    worker.configure(ctx, ledger, ids, out, id_complete, complete,
                     snapshot=snapshot, contexts=contexts,
                     engineering=engineering, allow_paid=allow_paid and not complete)
    progress = _Progress('predictions', len(ctx.rows))

    def prediction_arguments():
        for row in ctx.rows:
            sid = row['sample_id']
            fallback = ctx.fallbacks['folds'][row['dataset']][str(row['fold'])]
            yield (row, identities[sid], envelopes[sid], identity_seal,
                   fallback, contexts.get(sid))

    for args, result in _bounded_results(worker.prediction_task,
            prediction_arguments(), workers, worker.initialize_forked_worker,
            heartbeat=progress.update):
        registration.verify_engineering(engineering)
        require(type(result['provider_constructed']) is bool,
                'P_parallel_provider_audit_required')
        provider_constructed |= result['provider_constructed']
        records[name('record', args[0])] = result['record']
        require(not set(all_refs) & set(result['all_refs']),
                'P_parallel_duplicate_stage_reference')
        all_refs.update(deepcopy(result['all_refs']))
        progress.update(len(records))
    progress.update(len(records), force=True)
    require(set(records) == {name('record', r) for r in ctx.rows},
            'P_parallel_incomplete_record_population')

    # All workers have exited before any final audit/seal is attempted.
    snapshot.revalidate_full()
    _contexts(ctx, adapter, snapshot, identity_seal)
    proof = ledger.audit(complete=True)
    proof['stage_refs_sha256'] = fingerprint(all_refs)
    proof['logical_answers'] = sum(len(v) for v in all_refs.values())
    records['service-proof'] = proof
    ctx.verify_sources()
    registration.verify_engineering(engineering)
    require(not complete or not provider_constructed,
            'P_complete_replay_requires_zero_provider')
    if complete:
        require(out.verify_completed() == records, 'P_full_completed_records_changed')
    else:
        out.finalize(records)
    registration.verify_engineering(engineering)
    return {'status': 'completed', 'records': len(ctx.rows),
            'completed_replay': complete, 'provider_constructed': provider_constructed,
            'service_counts': proof['counts'],
            'engineering_binding': fingerprint(engineering)}


def run(*, allow_paid=False, workers=16):
    require(type(allow_paid) is bool, 'P_explicit_paid_flag_required')
    require(type(workers) is int and workers in (4, 8, 16, 32),
            'P_parallel_workers_must_be_4_8_16_or_32')
    require(sys.platform.startswith('linux'), 'P_parallel_linux_fork_required')
    import p_parallel_registration as registration
    engineering = registration.runtime_engineering()
    with registration.controller_lock():
        registration.verify_engineering(engineering)
        registration.authorize_continuation(engineering, workers, allow_paid)
        return _execute(engineering, workers, allow_paid)


def main(argv=None):
    parser = argparse.ArgumentParser(description='Engineering-bound P continuation')
    parser.add_argument('--allow-paid', action='store_true')
    parser.add_argument('--workers', type=int, choices=(4, 8, 16, 32), default=16)
    args = parser.parse_args(argv)
    return run(allow_paid=args.allow_paid, workers=args.workers)


if __name__ == '__main__':
    try:
        print(json.dumps(main(), sort_keys=True))
    except BaseException:
        print(json.dumps({'status': 'P_parallel_refused_preserve_state'}))
        raise SystemExit(1)
