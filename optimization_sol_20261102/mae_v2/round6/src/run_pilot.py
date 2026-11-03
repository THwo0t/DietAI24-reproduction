#!/usr/bin/env python3
"""Run/replay the fixed 25-pair training-only region-atlas pilot.

Default preflight is read-only. Paid construction is lazy, and completed replay
reparses every stage plus its external service evidence with zero Provider.
No target scoring or development/validation input belongs to this entry point.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import io
import json
import os
from pathlib import Path
import sys
import threading

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / 'src')]
from opt_pipeline import encode_image
from round4.src.artifacts import ArtifactStore, fingerprint, key_path
from round4.src import pipeline, retrieval, vision_stages, catalog_estimator
from round4.src.run_base import _execute
from round6.src import train_context as context
from round6.src import atlas_estimator as atlas
from round6.src.runtime import PilotProvider, BoundTrace, NAMESPACE, image_digest, run_stage
from round6.src.service_evidence import audit_state, completion_proof

OUTPUT = 'round6/runs/L_pilot'
SOURCES = context.SOURCES
METHOD_CONFIG = context.METHOD_CONFIG
PROTOCOL, PROTOCOL_SHA256 = context.PROTOCOL, context.PROTOCOL_SHA256


def require(condition, code):
    if not condition:
        raise ValueError(code)


class LazyProvider:
    namespace = NAMESPACE

    def __init__(self, base, allow_paid):
        self.base, self.allow_paid, self.instance = Path(base), allow_paid, None
        self.cache = self.base / 'runtime_cache/responses'
        self.lock = threading.Lock()

    def chat(self, messages, max_completion_tokens=4096):
        with self.lock:
            if self.instance is None:
                require(self.allow_paid, 'registered_paid_execution_required')
                self.instance = PilotProvider(self.base / 'round6/provider/L', allow_paid=True)
        return self.instance.chat(messages, max_completion_tokens=max_completion_tokens)

    def close(self):
        if self.instance is not None:
            self.instance.close()


def _snapshot(image):
    path = Path(image['image_path'])
    require(path.resolve() == path and path.is_file(), 'unsafe_image_snapshot')
    raw = path.read_bytes()
    require(context.digest(raw) == image['image_sha256'] and context.rgb_hash(raw) == image['rgb_sha256'],
            'bound_image_changed')
    return raw, encode_image(io.BytesIO(raw), 'native')


def _same(value, expected):
    require(value == expected, 'deterministic_pilot_stage_changed')
    return deepcopy(expected)


def _branch(result, fallback, catalog, *, rerank, atlas_results=None):
    unavailable = sum(r['failure'] is not None for r in (atlas_results or []))
    repaired = bool(rerank['repair_used'] or result['repair_used'] or
                    any(r['repair_used'] for r in (atlas_results or [])))
    method_fallback = rerank['failure'] is not None or unavailable > 0
    failed = result['failure'] is not None
    return {'prediction': deepcopy(fallback if failed else result['prediction']),
        'raw_prediction': deepcopy(result['prediction']), 'items': deepcopy(result['items']),
        'raw_leaves': [] if failed else pipeline._leaves(result['items'], catalog),
        'fallback': failed, 'fallback_reason': 'estimate:' + result['failure'] if failed else None,
        'method_fallback': method_fallback, 'repair_used': repaired,
        'native_complete': not failed and not method_fallback and not repaired,
        'failure': result['failure'], 'atlas_unavailable_supports': unavailable,
        'status': 'fallback' if failed else ('method_fallback' if method_fallback else 'ok')}


def infer_one(ctx, query, store, traced, atlas_locks, *, base=ROOT):
    sid = query['query_id']
    meta = next(row for row in ctx['rows'] if row['sample_id'] == sid)
    fold = meta['fold']
    assets, entries = ctx['fold_assets'][fold], ctx['fold_entries'][fold]
    by_train = {row['train_id']: row for row in entries}
    require(sid not in by_train and all(ctx['group_folds'][r['screening_group_id']] != fold for r in entries),
            'whole_query_fold_must_be_excluded')
    catalog, supports = assets['catalog'], assets['supports']
    query_raw, query_url = _snapshot(query)
    proof = {k: query[k] for k in ('image_sha256', 'rgb_sha256')}
    prefix = 'pilot-' + fingerprint({'query_id': sid, **proof})[:24]
    stages, refs, stage_keys = {}, {}, []
    def call_stage(name, inputs, images, call, validator):
        stage_keys.append(name)
        return run_stage(base, store, traced, name, inputs, images, call, validator,
                         refs_sink=lambda values: refs.__setitem__(name, values))
    index = retrieval.build_index(entries, ctx['fold_vectors'][fold])
    exclusions = {'train_ids': [sid], 'screening_group_ids': [query['screening_group_id']],
                  'image_sha256': [query['image_sha256']], 'rgb_sha256': [query['rgb_sha256']]}
    retrieved = retrieval.retrieve(index, ctx['query_vectors'][sid], exclusions)
    name = prefix + ':retrieval'
    stage_keys.append(name)
    stages['retrieval'] = store.stage_runner(name, {'method': retrieval.METHOD_VERSION,
        'fold_training_assets_sha256': assets['training_sha256'],
        'vector_sha256': fingerprint(ctx['query_vectors'][sid]), 'exclusions': exclusions},
        lambda: retrieved, lambda value: _same(value, retrieved))
    by_candidate = dict(zip(vision_stages.CANDIDATE_IDS, retrieved))
    candidates = [{'candidate_id': cid, 'image_path': supports[row['train_id']]['image_path']}
                  for cid, row in by_candidate.items()]
    candidate_urls = [_snapshot({**row, 'image_path': supports[row['train_id']]['image_path']})[1]
                      for row in retrieved]
    rerank = call_stage(prefix + ':rerank', {'method': vision_stages.METHOD_VERSION, 'query': proof,
        'candidates': [{'candidate_id': cid, **{k: row[k] for k in ('image_sha256', 'rgb_sha256')}}
                       for cid, row in by_candidate.items()],
        'image_payload_sha256': [image_digest(url) for url in [query_url] + candidate_urls]},
        [query_url] + candidate_urls,
        lambda: vision_stages.rerank(traced, query['image_path'], candidates), pipeline.validate_rerank_result)
    stages['rerank'] = rerank
    selected_candidate_ids = rerank['selected_ids'] if rerank['failure'] is None else list(vision_stages.CANDIDATE_IDS[:4])
    selected = [by_candidate[cid] for cid in selected_candidate_ids]
    examples = [deepcopy(supports[row['train_id']]) for row in selected]
    snapshots = [_snapshot({**row, 'image_path': example['image_path']}) for row, example in zip(selected, examples)]
    support_raws, support_urls = [x[0] for x in snapshots], [x[1] for x in snapshots]
    common = {'query': proof, 'training_sha256': assets['training_sha256'], 'catalog': catalog,
              'supports': [{**{k: row[k] for k in ('image_sha256', 'rgb_sha256')},
                            'ingredients': example['ingredients']} for row, example in zip(selected, examples)]}
    baseline = call_stage(prefix + ':baseline', {**common, 'method': catalog_estimator.METHOD_VERSION,
        'image_payload_sha256': [image_digest(url) for url in support_urls + [query_url]]},
        support_urls + [query_url],
        lambda: catalog_estimator.infer(traced, query['image_path'], examples, catalog),
        lambda value: pipeline.validate_estimate_result(value, catalog))
    stages['baseline'] = baseline
    atlas_results, atlas_stages = [], {}
    for row, example, url in zip(selected, examples, support_urls):
        tid = row['train_id']
        names = deepcopy(ctx['fold_annotation_names'][fold][tid])
        require({item['ingredient_id'] for item in names} ==
                {item['ingredient_id'] for item in example['ingredients']}, 'annotation_support_names_changed')
        name = 'atlas-' + fingerprint({k: row[k] for k in ('image_sha256', 'rgb_sha256')})[:24]
        # Nonblocking ArtifactStore stage locks are protected by this batch's
        # per-image lock: two queries sharing a support issue one annotation.
        with atlas_locks[tid]:
            result = call_stage(name, {'method': METHOD_CONFIG['method'],
                **{k: row[k] for k in ('image_sha256', 'rgb_sha256')}, 'ingredient_names': names,
                'image_payload_sha256': image_digest(url)}, [url],
                lambda: atlas.annotate(traced, example['image_path'], names),
                lambda value: atlas.validate_annotation_result(value, names))
        atlas_results.append(result)
        atlas_stages[tid] = {'stage_key': name, 'result': result}
    stages['atlas'] = atlas_stages
    crop_provenance = []
    for row, raw, result in zip(selected, support_raws, atlas_results):
        for card in atlas.crop_cards_from_bytes(raw, result['annotations']):
            crop_provenance.append({'support_train_id': row['train_id'],
                                    'ingredient_id': card['ingredient_id'],
                                    'proof': deepcopy(card['proof'])})
    messages = atlas.build_messages_from_bytes(query_raw, support_raws, examples, catalog, atlas_results,
                                              query_image_path=query['image_path'])
    images = atlas.ordered_image_urls(messages)
    require(len(images) <= 13, 'pilot_candidate_image_budget_exceeded')
    candidate = call_stage(prefix + ':candidate', {**common, 'method': METHOD_CONFIG['method'],
        'atlas_results_sha256': fingerprint(atlas_results),
        'crop_provenance': crop_provenance,
        'image_payload_sha256': [image_digest(url) for url in images]}, images,
        lambda: atlas.infer(traced, query['image_path'], examples, catalog, atlas_results),
        lambda value: atlas.validate_candidate_result(value, catalog))
    stages['candidate'] = candidate
    return {**meta, 'query_id': sid, 'selected_candidate_ids': selected_candidate_ids,
        'selected_train_ids': [r['train_id'] for r in selected],
        'fold_training_assets_sha256': assets['training_sha256'],
        'crop_provenance': crop_provenance,
        'baseline': _branch(baseline, assets['fallback'], catalog, rerank=rerank),
        'candidate': _branch(candidate, assets['fallback'], catalog, rerank=rerank, atlas_results=atlas_results),
        'stages': stages, 'request_refs': refs, 'stage_keys': sorted(set(stage_keys))}


def collect_service_refs(records):
    out, annotations = {}, set()
    for sid, record in records.items():
        stages = record['stages']
        result_by_key = {name: stages[role] for role in ('rerank', 'baseline', 'candidate')
                         for name in record['request_refs'] if name.endswith(':' + role)}
        for tid, entry in stages['atlas'].items():
            require(tid in record['selected_train_ids'], 'unexpected_atlas_support')
            result_by_key[entry['stage_key']] = entry['result']
            annotations.add(entry['stage_key'])
        require(set(result_by_key) == set(record['request_refs']), 'pilot_receipt_coverage_changed')
        for key, result in result_by_key.items():
            entry = {'refs': deepcopy(record['request_refs'][key]), 'values': deepcopy(result['raw_outputs'])}
            require(key not in out or out[key] == entry, 'shared_atlas_receipts_changed')
            out[key] = entry
    require(len(annotations) <= 100 and sum(len(x['refs']) for x in out.values()) <= 350,
            'pilot_logical_request_ceiling_exceeded')
    return out


def base(*, allow_paid=False, workers=2, verify_only=False, root=ROOT, context_loader=None):
    require(type(workers) is int and 1 <= workers <= 2, 'pilot_workers_must_be_one_or_two')
    root = Path(root)
    audit_state(root)
    ctx = (context_loader or context.load_context)(root)
    require(len(ctx['queries']) == len(ctx['rows']) == 25, 'complete_25_query_population_required')
    store = ArtifactStore(root / OUTPUT, ctx['binding'], [r['sample_id'] for r in ctx['rows']],
                          verify_sources=ctx['verify_quick'], root=root / 'round6')
    complete = (root / OUTPUT / 'completion.json').exists()
    saved = store.verify_completed() if complete or verify_only else None
    if saved is None:
        require(allow_paid, 'registered_paid_execution_required')
        store.initialize()
    lazy, locks = LazyProvider(root, allow_paid and saved is None), {}
    for assets in ctx['fold_assets'].values():
        for tid in assets['supports']:
            locks.setdefault(tid, threading.Lock())
    traced = BoundTrace(lazy)
    try:
        records = _execute(ctx['queries'], lambda q: (q['query_id'], infer_one(ctx, q, store, traced, locks, base=root)), workers)
        ctx['reader'].unchanged()
        ctx['verify_gallery']()
        stage_refs = collect_service_refs(records)
        proof = completion_proof(root, stage_refs)
        store.stage_runner('service:completion_provenance',
            {'method': METHOD_CONFIG['method'], 'stage_refs_sha256': fingerprint(stage_refs)},
            lambda: proof, lambda value: _same(value, completion_proof(root, stage_refs)))
        expected = {key_path(key) for record in records.values() for key in record['stage_keys']}
        expected.add(key_path('service:completion_provenance'))
        require({p.name for p in store._path('stages').iterdir()} == expected, 'pilot_stage_inventory_changed')
        if saved is not None:
            require(saved == records, 'completed_pilot_replay_changed')
        else:
            store.finalize(records)
    finally:
        lazy.close()
    return {'status': 'base_verified' if saved is not None else 'base_complete_unscored',
        'n': len(records), 'records': records, 'binding': deepcopy(store.binding),
        'completion_sha256': context.digest((root / OUTPUT / 'completion.json').read_bytes()),
        'provider_constructed': lazy.instance is not None, 'development_opened': False, 'validation_opened': False}


def main(argv=None):
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase', choices=('preflight', 'base', 'verify'))
    parser.add_argument('--allow-paid', action='store_true')
    parser.add_argument('--workers', type=int, default=2)
    args = parser.parse_args(argv)
    try:
        # User steering after implementation requires every full candidate to
        # test a common method on ASA24 and Nutrition5k. This unexecuted N5-only
        # pilot is retained as engineering source, not a paid-run entry point.
        require(args.phase != 'base', 'N5_only_pilot_shelved_pending_dual_dataset_protocol')
        if args.phase == 'preflight':
            audit_state(ROOT)
            ctx = context.load_context(ROOT)
            result = {'status': 'pilot_preflight_pass', 'n': len(ctx['queries']), 'training_n': 230,
                      'fold_training_n': 184, 'api_calls': 0, 'provider_constructed': False,
                      'development_opened': False, 'validation_opened': False,
                      'source_sha256': {name: ctx['reader'].hashes[name] for name in SOURCES}}
        else:
            result = base(allow_paid=args.allow_paid, workers=args.workers, verify_only=args.phase == 'verify')
        print(json.dumps({k: v for k, v in result.items() if k not in ('records', 'binding')}, sort_keys=True, allow_nan=False))
        return 0
    except BaseException as error:
        if isinstance(error, (KeyboardInterrupt, SystemExit)):
            raise
        print(json.dumps({'status': 'stopped', 'error_type': type(error).__name__}, sort_keys=True))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
