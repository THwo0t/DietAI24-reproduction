#!/usr/bin/env python3
"""Resume J in a separately sealed run; old scientific sources stay immutable.

Imports are explicit validated callbacks, never copied ArtifactStore envelopes.
Old intents, independent receipts, raw responses, caches and request references
must agree. Completed verification replays the pure pipeline against sealed
stages, constructs zero providers, and performs no writes. No development label
reader or scorer is imported here.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import os
from pathlib import Path
import sys
import threading

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / 'src')]
import opt_provider as original
from round4.src import run_base as old
from round4.src.artifacts import (ArtifactStore, TerminalStageError, decode,
                                 fingerprint, key_path, normalized)
from round4.src.image_guard import ImageGuard, expected_images
from round4.src.trace_provider import TraceProvider
from round4.continuation.integrity import (AUDIT, NEW_RUN, OLD_RUN, PROVIDER_RUN,
    Registration, digest, path, read, require)
from round4.continuation.provider import ContinuationProvider


class LazyProvider:
    """The imported-only route never constructs an HTTP client or reads keys."""
    namespace = old.NAMESPACE

    def __init__(self, root, registration, allow_paid):
        self.cache = root / 'runtime_cache/responses'
        self.root, self.registration, self.allow_paid = root, registration, allow_paid
        self.instance = None
        self.lock = threading.Lock()

    def _get(self):
        with self.lock:
            if self.instance is None:
                require(self.allow_paid, 'explicit_paid_flag_required_for_unsealed_stage')
                self.instance = ContinuationProvider(self.root / PROVIDER_RUN, self.registration,
                                                     allow_paid=True)
            return self.instance

    def chat(self, *args, **kwargs):
        return self._get().chat(*args, **kwargs)

    def embed(self, *args, **kwargs):
        return self._get().embed(*args, **kwargs)

    def close(self):
        if self.instance is not None:
            self.instance.close()


def _refs(name, result, refs, registration, *, imported):
    refs = old._validate_refs(refs)
    kind = name.rsplit(':', 1)[-1]
    if kind == 'retrieval':
        values, role = [], None
    elif kind == 'embedding':
        values, role = [result['vector']], 'embedding'
    elif kind in ('description', 'rerank', 'estimate'):
        values, role = result['raw_outputs'], 'chat'
    else:
        raise ValueError('unknown_traced_stage')
    require(isinstance(values, list) and len(values) == len(refs), 'raw_output_request_count_changed')
    for value, ref in zip(values, refs):
        require(ref['role'] == role and ref['value_hash'] == original.fingerprint(value),
                'raw_output_request_hash_changed')
        h = ref['request_hash']
        file = f'runtime_cache/responses/{role}/{h}.json'
        if imported:
            require(file in registration.data['successful_cache_sha256'], 'old_request_cache_not_registered')
        raw = read(registration.root, file)
        if imported:
            require(digest(raw) == registration.data['successful_cache_sha256'][file], 'old_success_cache_changed')
        saved = decode(raw)
        model = original.CHAT_MODEL if role == 'chat' else original.EMBED_MODEL
        require(isinstance(saved, dict) and saved.get('request_hash') == h and saved.get('model') == model
                and saved.get('value_hash') == ref['value_hash']
                and original.fingerprint(saved.get('value')) == ref['value_hash']
                and saved['value'] == value, 'stage_response_cache_mismatch')
        if imported and role == 'chat':
            counter = f'runtime_cache/attempts/chat/{h}.json'
            require(counter in registration.data['attempt_snapshots'], 'old_chat_counter_not_registered')
            if not ref['cache_present_before']:
                require(any(r.get('request_hash') == h and r.get('role') == role
                            and r.get('status') == 200 and r.get('model_served') == model
                            for r in registration.original_requests), 'old_chat_success_log_missing')
        # An embedding inherited by the original provider may have no local
        # transmission. Its exact registered cache is the provenance anchor;
        # cache_present_before is deliberately not called an HTTP/cache-hit fact.
    return refs


class ImportRunner:
    def __init__(self, old_store, store, traced, payloads, registration, *, completed_verified=False):
        self.old, self.store, self.traced = old_store, store, traced
        self.payloads, self.registration = payloads, registration
        self.completed_verified = completed_verified
        self.imported = set()
        self.lock = threading.Lock()

    def _old_result(self, name, inputs, validator):
        stage = 'stages/' + key_path(name)
        intent = self.old._stage_intent(name, inputs)
        existing = self.old._path(stage + '/intent.json')
        if not existing.exists():
            return None
        require(self.old._json(stage + '/intent.json') == intent, 'old_stage_exact_inputs_changed')
        seal = self.old._path(stage + '/result.seal.json')
        result = self.old._path(stage + '/result.json')
        if not seal.exists():
            require(not result.exists(), 'old_result_without_receipt')
            return None
        def validate(envelope):
            require(isinstance(envelope, dict) and set(envelope) == {'result', 'request_refs'},
                    'invalid_old_traced_envelope')
            parsed = validator(envelope['result'])
            refs = _refs(name, envelope['result'], envelope['request_refs'], self.registration, imported=True)
            return {'result': parsed, 'request_refs': refs}
        if result.exists():
            try:
                parsed = self.old._cached(stage, intent, validate)
            except TerminalStageError as error:
                return {'terminal': error.code}
            body = self.old._json(stage + '/result.json')
        else:
            # Receipt-before-publication crash: validate pending bytes without
            # publishing, unlinking, locking, or otherwise touching the old run.
            raw = self.old._bytes(stage + '/result.json.pending')
            require(self.old._json(stage + '/result.seal.json') == {
                'result_sha256': digest(raw), 'stage_intent_sha256': fingerprint(intent),
                'run_binding_sha256': fingerprint(self.old.intent)}, 'old_pending_receipt_changed')
            body = decode(raw)
            if body.get('kind') == 'terminal':
                require(set(body) == {'kind', 'error_code'}, 'old_terminal_shape_changed')
                return {'terminal': TerminalStageError(body['error_code']).code}
            require(set(body) == {'kind', 'raw', 'parsed'} and body['kind'] == 'result',
                    'old_pending_result_changed')
            parsed = normalized(validate(deepcopy(body['raw'])))
            require(parsed == body['parsed'], 'old_pending_reparse_changed')
            self.old._sources()
        return {'raw': deepcopy(body['raw']), 'parsed': parsed}

    def __call__(self, name, inputs, call, validator):
        imported = self._old_result(name, inputs, validator)
        if imported is not None:
            with self.lock:
                self.imported.add(name)
        def invoke():
            if imported is not None:
                if 'terminal' in imported:
                    raise TerminalStageError(imported['terminal'])
                return deepcopy(imported['raw'])
            mark = self.traced.mark()
            with self.traced.expect(expected_images(name, inputs, self.payloads)):
                result = call()
            return {'result': result, 'request_refs': self.traced.refs_since(mark)}
        def validate(envelope):
            require(isinstance(envelope, dict) and set(envelope) == {'result', 'request_refs'},
                    'invalid_continuation_traced_envelope')
            parsed = {'result': validator(envelope['result']), 'request_refs': _refs(
                name, envelope['result'], envelope['request_refs'], self.registration,
                imported=imported is not None)}
            if imported is not None and 'parsed' in imported:
                require(parsed == imported['parsed'] and envelope == imported['raw'],
                        'imported_old_stage_changed')
            return parsed
        if self.completed_verified:
            # base() already checked the entire immutable completion inventory.
            # Reparse each stage once without repeatedly walking that inventory.
            return self.store._cached('stages/' + key_path(name),
                                      self.store._stage_intent(name, inputs), validate)['result']
        return self.store.stage_runner(name, inputs, invoke, validate)['result']

    def verify_import_coverage(self):
        expected = set()
        for name in self.registration.snapshot['files']:
            if name.endswith('/result.seal.json'):
                directory = str(Path(name).parent)
                expected.add(decode(read(self.registration.root, directory + '/intent.json'))['name'])
        require(self.imported == expected, 'sealed_old_stage_not_imported')
        return sorted(expected)


def _stores(ctx, registration):
    original_store, index = old._base_store(ctx)
    require(original_store._json('intent.json') == original_store.intent, 'original_run_intent_changed')
    r = registration.data
    require(original_store.binding['gallery_completion_sha256'] == r['gallery_completion_sha256']
            and ctx['binding']['training_freeze_sha256'] == r['training_freeze_sha256']
            and ctx['reader'].hashes[old.context.DEV_MANIFEST] == r['query_manifest_sha256'],
            'original_context_differs_from_registration')
    binding = {**deepcopy(original_store.binding), 'service_continuation': registration.service_binding()}
    def verify():
        original_store._sources()
        registration.verify_static()
    store = ArtifactStore(ROOT / NEW_RUN, binding, original_store.expected_records,
                          verify_sources=verify, root=ROOT / 'round4')
    return original_store, store, index


def _provenance(registration, imported):
    states = registration.attempt_states()
    files = {}
    for name in (AUDIT, PROVIDER_RUN + '/requests.jsonl'):
        p = path(ROOT, name, exists=False)
        files[name] = digest(p.read_bytes()) if p.exists() else None
    return {'registration_sha256': registration.sha256, 'imported_stages': imported,
            'service_log_sha256': files,
            'attempt_counter_sha256': {name: item['sha256'] for name, item in sorted(states.items())}}


def base(*, allow_paid=False, workers=2, verify_only=False):
    require(type(workers) is int and 1 <= workers <= 2, 'continuation_workers_must_be_one_or_two')
    registration = Registration(ROOT)
    registration.attempt_states(allow_pending=not verify_only)
    ctx = old.context.load_context(ROOT)
    original_store, store, index = _stores(ctx, registration)
    complete = store._path('completion.json').exists()
    saved = store.verify_completed() if complete or verify_only else None
    require(len(ctx['rows']) == 84 and len({r['group_id'] for r in ctx['rows']}) == 78,
            'original_development_population_changed')
    if saved is None:
        # R-SC-2: publish/verify the new intent once before parallel workers.
        # The frozen ArtifactStore deliberately uses nonblocking run locks.
        store.initialize()
    proxy = LazyProvider(ROOT, registration, allow_paid and not (complete or verify_only))
    traced = ImageGuard(TraceProvider(proxy))
    runner = ImportRunner(original_store, store, traced, ctx['payloads'], registration,
                          completed_verified=saved is not None)
    by_id = {row['sample_id']: row for row in ctx['rows']}
    try:
        def work(query):
            result = old.pipeline.infer(traced, query, ctx['assets'], index, stage_runner=runner)
            row = by_id[query['query_id']]
            record = {k: row[k] for k in ('sample_id', 'dataset', 'group_id', 'fold')}
            record.update(result)
            record.update({'final_codes': [], 'primary_code': None})
            return row['sample_id'], record
        records = old._execute(ctx['queries'], work, workers)
        imported = runner.verify_import_coverage()
        ctx['reader'].unchanged()
        ctx['verify_gallery']()
        registration.verify_static()
        registration.verify_snapshot()
        proof = _provenance(registration, imported)
        def validate_proof(value):
            require(value == _provenance(registration, imported), 'service_completion_provenance_changed')
            return value
        store.stage_runner('service:completion_provenance', registration.service_binding(),
                           lambda: proof, validate_proof)
        if saved is not None:
            require(records == saved, 'completed_pipeline_replay_changed')
        else:
            store.finalize(records)
    finally:
        proxy.close()
    return {'status': 'base_verified' if saved is not None else 'base_complete_unscored',
            'n': len(records), 'records': records, 'binding': deepcopy(store.binding),
            'completion_sha256': digest(store._bytes('completion.json')),
            'provider_constructed': proxy.instance is not None, 'validation_opened': False}


def main(argv=None):
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase', choices=('base', 'verify'))
    parser.add_argument('--allow-paid', action='store_true')
    parser.add_argument('--workers', type=int, default=2)
    args = parser.parse_args(argv)
    try:
        result = base(allow_paid=args.allow_paid, workers=args.workers, verify_only=args.phase == 'verify')
        old.event(**{k: v for k, v in result.items() if k not in ('records', 'binding')})
        return 0
    except (Exception, original.ProviderStop) as error:
        old.event(status='stopped', error_type=type(error).__name__)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
