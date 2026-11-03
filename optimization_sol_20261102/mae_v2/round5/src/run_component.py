#!/usr/bin/env python3
"""Independent K development entry point; never load development targets.

Verify the frozen parent before whitelisting its upstream data. New stages and
request receipts are independently sealed. Completed replay creates no client.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import json
import os
from pathlib import Path
import sys
import threading

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / 'src')]
from opt_pipeline import encode_image
from opt_provider import fingerprint as response_fingerprint
from round4.continuation import runner as parent_runner
from round4.src import context, run_base as old
from round4.src.artifacts import ArtifactStore, canonical, decode, fingerprint
from round5.src import component_estimator as estimator
from round5.src import component_supports as selection
from round5.src.component_runtime import BoundTrace, ComponentProvider, NAMESPACE, image_digest
from round5.src.verified_j_prefix import extract_prefixes
from round5.src.service_evidence import audit_state, verify_refs, completion_proof

PROTOCOL = 'round5/K_PROTOCOL.md'
PROTOCOL_SHA256 = '255a965f4340e5aa9c74b4864f9b5f853a8e1bb7a2a09ca04e4e286a8849f467'
PARENT_COMPLETION = 'round4/runs/J_service_continuation/completion.json'
PARENT_COMPLETION_SHA256 = '11fc4c720a3bd9c5b59cd5f3cca8fb291b0865e9ebc8e32e8643498d3ae22b1f'
OUTPUT = 'round5/runs/K'
SOURCES = (PROTOCOL, 'round5/src/run_component.py',
           'round5/src/component_estimator.py', 'round5/src/component_supports.py',
           'round5/src/component_runtime.py', 'round5/src/verified_j_prefix.py',
           'round5/src/service_evidence.py', 'round5/tests/test_service_evidence.py',
           'round5/tests/test_component_estimator.py', 'round5/tests/test_component_supports.py',
           'round5/tests/test_component_runtime.py', 'round5/tests/test_verified_j_prefix.py',
           'round5/tests/test_run_component.py')
METHOD_CONFIG = {'candidate': 'K', 'method': 'component_comparison_mass_budget_r5.1',
    'namespace': NAMESPACE, 'chat_model': 'gpt-6.1-sol', 'temperature': 1,
    'hypothesis_tokens': 4096, 'mass_tokens': 8192, 'format_repairs': 1,
    'http_attempts': 3, 'read_timeout_seconds': 600, 'max_workers': 2,
    'max_comparison_groups': 4, 'max_support_images': 8, 'max_total_images': 13,
    'dominance_threshold': .25, 'crop_margin_fraction': .05,
    'calibration': None, 'fallback': 'fixed_external_training_official_target_medians',
    'validation_opened': False}


def require(condition, code):
    if not condition:
        raise ValueError(code)


def load_inputs():
    audit_state(ROOT)  # R5-K4-1: read-only resume audit before loading/inference.
    parent = parent_runner.base(verify_only=True)
    require(parent.get('status') == 'base_verified' and parent.get('n') == 84
            and parent.get('provider_constructed') is False and parent.get('validation_opened') is False
            and parent.get('completion_sha256') == PARENT_COMPLETION_SHA256,
            'completed_frozen_parent_required')
    ctx = context.load_context(ROOT)
    reader = ctx['reader']
    reader.read(PROTOCOL, PROTOCOL_SHA256)
    reader.read(PARENT_COMPLETION, PARENT_COMPLETION_SHA256)
    for relative in SOURCES:
        reader.read(relative)
    gallery_store = old._gallery_store(ctx)
    gallery_records = gallery_store.verify_completed()
    old._gallery_index(ctx, gallery_records)
    vectors = {sid: record['result']['embedding']['vector'] for sid, record in gallery_records.items()}
    prefixes = extract_prefixes(parent, {**ctx['assets'], 'queries': ctx['queries'],
                                       'gallery_entries': ctx['entries']})
    require(prefixes['n'] == len(ctx['queries']) == 84 and len({r['group_id'] for r in ctx['rows']}) == 78,
            'complete_registered_population_required')
    # A valid parent description is necessary for its immutable query vector.
    # J has all four prefixes for all 84; never silently create a new embedding.
    require(all(not p['fallback'] and p['stages']['embedding'] is not None
                for p in prefixes['prefixes'].values()), 'complete_parent_vectors_required')
    ctx.update(parent_provenance=prefixes['provenance'], prefixes=prefixes['prefixes'], vectors=vectors)
    ctx['binding'] = {**ctx['binding'], 'phase': 'development_component_base',
        'method_config': deepcopy(METHOD_CONFIG), 'parent_provenance': prefixes['provenance'],
        'prefixes_sha256': fingerprint(prefixes),
        'input_sha256': dict(reader.hashes)}
    gallery_complete = (ROOT / 'round4/runs/J_gallery/completion.json').read_bytes()
    def quick():
        old._verify_quick(ctx)
        for relative in (*SOURCES, PARENT_COMPLETION):
            require(context.digest(context.safe_path(ROOT, relative).read_bytes()) == reader.hashes[relative],
                    'component_bound_source_changed')
        require((ROOT / 'round4/runs/J_gallery/completion.json').read_bytes() == gallery_complete,
                'component_gallery_completion_changed')
    ctx.update(verify_quick=quick, verify_gallery=gallery_store.verify_completed)
    reader.unchanged()
    return ctx


class LazyProvider:
    namespace = NAMESPACE
    cache = ROOT / 'runtime_cache/responses'

    def __init__(self, allow_paid):
        self.allow_paid, self.instance, self.lock = allow_paid, None, threading.Lock()

    def chat(self, messages, max_completion_tokens=4096):
        with self.lock:
            if self.instance is None:
                require(self.allow_paid, 'registered_paid_execution_required')
                self.instance = ComponentProvider(ROOT / 'round5/provider/K', allow_paid=True)
        return self.instance.chat(messages, max_completion_tokens=max_completion_tokens)

    def close(self):
        if self.instance is not None:
            self.instance.close()


def _stage(store, traced, name, inputs, images, call, validator, *, refs_sink=None):
    def invoke():
        cursor = traced.mark()
        with traced.expect(images):
            result = call()
        return {'result': result, 'request_refs': traced.refs_since(cursor)}
    def validate(envelope):
        require(isinstance(envelope, dict) and set(envelope) == {'result', 'request_refs'},
                'component_stage_envelope_changed')
        result = validator(envelope['result'])
        refs = old._validate_refs(envelope['request_refs'])
        require(len(refs) == len(result['raw_outputs']) and all(
            ref['role'] == 'chat' and ref['value_hash'] == response_fingerprint(value)
            for ref, value in zip(refs, result['raw_outputs'])), 'component_request_value_binding_changed')
        verify_refs(ROOT, refs, result['raw_outputs'])
        return {'result': result, 'request_refs': refs}
    envelope = store.stage_runner(name, inputs, invoke, validate)
    if refs_sink is not None:
        refs_sink(deepcopy(envelope['request_refs']))
    return envelope['result']


def infer_one(ctx, query, store, traced):
    sid = query['query_id']
    prefix = ctx['prefixes'][sid]
    assets = ctx['assets']
    catalog = assets['catalog']
    names = [{key: row[key] for key in ('ingredient_id', 'name')} for row in catalog]
    query_url = encode_image(query['image_path'], 'native')
    query_proof = {key: query[key] for key in ('image_sha256', 'rgb_sha256')}
    stage_name = 'component-' + fingerprint({'query_id': sid, **query_proof})[:24]
    stages = {}
    state = {'method': METHOD_CONFIG['method'], 'query_id': sid, 'prediction': None,
        'raw_prediction': None, 'items': [], 'raw_leaves': [], 'fallback': False,
        'fallback_reason': None, 'method_fallback': prefix['method_fallback'],
        'native_complete': False, 'repair_used': prefix['repair_used'], 'failure': None,
        'status': 'pending', 'stages': stages,
        'request_refs': {},
        'audit': {'parent_prefix_provenance': deepcopy(prefix['provenance']),
                  'parent_method_fallback_reason': prefix['method_fallback_reason'],
                  'training_sha256': assets['training_sha256']}}
    def fallback(stage, result):
        reason = stage + ':' + result['failure']
        state.update(prediction=deepcopy(assets['fallback']), fallback=True,
                     fallback_reason=reason, failure=reason, status='fallback')
        state['audit']['whole_fallback_source'] = 'fixed_external_training_official_target_medians'
        return state
    hypothesis_inputs = {'method': METHOD_CONFIG['method'], 'query': query_proof,
        'query_payload_sha256': image_digest(query_url), 'catalog_names': names}
    hypotheses = _stage(store, traced, stage_name + ':hypotheses', hypothesis_inputs, [query_url],
        lambda: estimator.infer_hypotheses(traced, query['image_path'], names),
        lambda value: estimator.validate_hypotheses_result(value, names),
        refs_sink=lambda refs: state['request_refs'].__setitem__('hypotheses', refs))
    stages['hypotheses'] = hypotheses
    state['repair_used'] |= hypotheses['repair_used']
    if hypotheses['failure'] is not None:
        return fallback('hypotheses', hypotheses)
    groups = hypotheses['groups']
    major = estimator.major_groups(groups)
    crops = estimator.make_crops(query['image_path'], groups)
    fill = list(prefix['selected_train_ids'])
    fill += [row['train_id'] for row in prefix['stages']['retrieval'] if row['train_id'] not in fill]
    selected = selection.select_supports(prefix['stages']['embedding']['vector'], ctx['entries'],
        ctx['vectors'], {tid: support['ingredients'] for tid, support in assets['supports'].items()},
        [{'group_id': group['group_id'], 'hypotheses': group['hypotheses']} for group in major],
        {'train_ids': {sid}, 'screening_group_ids': {query['screening_group_id']},
         'image_sha256': {query['image_sha256']}, 'rgb_sha256': {query['rgb_sha256']}},
        catalog_ids=[row['ingredient_id'] for row in catalog], fill_train_ids=fill)
    # Deterministic selector is saved and revalidated as a separate offline stage.
    select_inputs = {'method': selection.VERSION, 'query': query_proof,
                     'selection_inputs_sha256': selected['audit']['input_sha256']}
    def validate_selected(value):
        require(value == selected, 'component_training_selection_changed')
        return value
    selected = store.stage_runner(stage_name + ':supports', select_inputs,
                                  lambda: selected, validate_selected)
    stages['supports'] = selected
    supports = [deepcopy(assets['supports'][tid]) for tid in selected['selected_train_ids']]
    support_urls = [encode_image(support['image_path'], 'native') for support in supports]
    images = [query_url] + [crop['image_url'] for crop in crops] + support_urls
    require(len(images) <= 13, 'component_image_budget_violated')
    mass_inputs = {'method': METHOD_CONFIG['method'], 'query': query_proof,
        'hypotheses': groups, 'image_payload_sha256': [image_digest(url) for url in images],
        'catalog': catalog, 'support_training_ids': selected['selected_train_ids'],
        'support_ingredients': [support['ingredients'] for support in supports],
        'selection_sha256': selected['audit']['selection_sha256']}
    mass = _stage(store, traced, stage_name + ':mass', mass_inputs, images,
        lambda: estimator.infer_mass(traced, query['image_path'], groups, crops, supports, catalog),
        lambda value: estimator.validate_mass_result(value, groups, catalog),
        refs_sink=lambda refs: state['request_refs'].__setitem__('mass', refs))
    stages['mass'] = mass
    state['repair_used'] |= mass['repair_used']
    state['audit'].update(selected_train_ids=selected['selected_train_ids'],
        selection_sha256=selected['audit']['selection_sha256'],
        crop_payload_sha256=[crop['sha256'] for crop in crops], mass=deepcopy(mass['audit']))
    if mass['failure'] is not None:
        return fallback('mass', mass)
    state.update(prediction=deepcopy(mass['prediction']), raw_prediction=deepcopy(mass['prediction']),
                 items=deepcopy(mass['items']), raw_leaves=deepcopy(mass['raw_leaves']),
                 native_complete=not state['repair_used'] and not state['method_fallback'],
                 status='method_fallback' if state['method_fallback'] else 'ok')
    return state


def collect_service_refs(records):
    """Project only recorded chat receipts and their sealed returned strings."""
    out = {}
    for sid, record in records.items():
        stages, refs = record.get('stages'), record.get('request_refs')
        require(isinstance(stages, dict) and isinstance(refs, dict)
                and set(refs) == set(stages) - {'supports'}
                and set(refs) in ({'hypotheses'}, {'hypotheses', 'mass'}),
                'component_service_stage_coverage_changed')
        for name in sorted(refs):
            out[fingerprint({'query_id': sid, 'stage': name})] = {
                'refs': deepcopy(refs[name]), 'values': deepcopy(stages[name]['raw_outputs'])}
    return out


def base(*, allow_paid=False, workers=2, verify_only=False):
    require(type(workers) is int and 1 <= workers <= 2, 'component_workers_must_be_one_or_two')
    ctx = load_inputs()
    store = ArtifactStore(ROOT / OUTPUT, ctx['binding'], [row['sample_id'] for row in ctx['rows']],
                          verify_sources=ctx['verify_quick'], root=ROOT / 'round5')
    complete = (ROOT / OUTPUT / 'completion.json').exists()
    saved = store.verify_completed() if complete or verify_only else None
    if saved is None:
        require(allow_paid, 'registered_paid_execution_required')
        store.initialize()
    lazy = LazyProvider(allow_paid and saved is None)
    traced = BoundTrace(lazy)
    by_id = {row['sample_id']: row for row in ctx['rows']}
    try:
        def work(query):
            result = infer_one(ctx, query, store, traced)
            row = by_id[query['query_id']]
            record = {key: row[key] for key in ('sample_id', 'dataset', 'group_id', 'fold')}
            record.update(result)
            record.update(final_codes=[], primary_code=None)
            return row['sample_id'], record
        records = old._execute(ctx['queries'], work, workers)
        ctx['reader'].unchanged()
        ctx['verify_gallery']()
        # Every worker has joined. No other request can still be between its
        # log write and successful cache publication when this proof is made.
        service_refs = collect_service_refs(records)
        proof = completion_proof(ROOT, service_refs)
        def validate_proof(value):
            require(value == completion_proof(ROOT, service_refs),
                    'component_service_completion_provenance_changed')
            return value
        store.stage_runner('service:completion_provenance',
            {'method': METHOD_CONFIG['method'], 'stage_refs_sha256': fingerprint(service_refs)},
            lambda: proof, validate_proof)
        if saved is not None:
            require(records == saved, 'completed_component_replay_changed')
        else:
            store.finalize(records)
    finally:
        lazy.close()
    return {'status': 'base_verified' if saved is not None else 'base_complete_unscored',
        'n': len(records), 'records': records, 'binding': deepcopy(store.binding),
        'completion_sha256': context.digest((ROOT / OUTPUT / 'completion.json').read_bytes()),
        'provider_constructed': lazy.instance is not None, 'validation_opened': False}


def main(argv=None):
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase', choices=('preflight', 'base', 'verify'))
    parser.add_argument('--allow-paid', action='store_true')
    parser.add_argument('--workers', type=int, default=2)
    args = parser.parse_args(argv)
    try:
        if args.phase == 'preflight':
            ctx = load_inputs()
            result = {'status': 'component_preflight_pass', 'n': len(ctx['queries']),
                      'training_n': len(ctx['entries']), 'api_calls': 0, 'validation_opened': False,
                      'source_sha256': {name: ctx['reader'].hashes[name] for name in SOURCES}}
        else:
            result = base(allow_paid=args.allow_paid, workers=args.workers, verify_only=args.phase == 'verify')
        old.event(**{key: value for key, value in result.items() if key not in ('records', 'binding')})
        return 0
    except BaseException as error:
        if isinstance(error, (KeyboardInterrupt, SystemExit)):
            raise
        old.event(status='stopped', error_type=type(error).__name__)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
