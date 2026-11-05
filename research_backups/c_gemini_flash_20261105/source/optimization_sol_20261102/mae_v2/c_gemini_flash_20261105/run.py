#!/usr/bin/env python3
"""One frozen C/MultiQuery/mean-density comparison on 843 development images."""
from __future__ import annotations
import sys
sys.dont_write_bytecode = True
from pathlib import Path
HERE = Path(__file__).resolve().parent
V2 = HERE.parent
REPO = V2.parents[1]
sys.path[:0] = [str(HERE), str(V2 / 'src'), str(V2)]
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import deepcopy
import fcntl
import importlib.metadata
import math
import os
import statistics
import subprocess
import time
from newcommon import Store, CachedProvider, load, event, usage_summary
from opt_provider import atomic_json, fingerprint, sha, stamp
import pipeline as method
from chroma_index import prepare_copy, SearchIndex

os.umask(0o077)
COHORT = V2 / 'round11/prepared/cohort'
PREVIOUS = V2 / 'cj_full_20261104'
SNAPSHOT = V2 / 'deliverables/j_c_20261104/C/source/optimization_sol_20261102/mae_v2/src'
KEYS = ('weight', 'energy', 'fat', 'carbs', 'protein')
C_CONFIG = dict(crop_review=False, portion_mode='total_ratio', profile='C', identity_profile='A')
ASA_CONFIG = dict(variant='optimized', image_mode='square256', candidate_cap=32,
                  portion_mode='continuous_option', examples=False)


def require(value, message):
    if not value:
        raise ValueError(message)


def rows_only():
    rows = load(COHORT / 'dev.json')
    require(len(rows) == 843 and len({r['sample_id'] for r in rows}) == 843, 'fixed843_required')
    require(all(r['split'] == 'dev' for r in rows), 'development_only')
    groups = {}
    for row in rows:
        group = (row['dataset'], row['group_id'])
        require(groups.setdefault(group, row['fold']) == row['fold'], 'complete_group_crosses_folds')
    for dataset, count, group_count in (('nutrition5k', 314, 293), ('asa24', 529, 43)):
        chosen = [r for r in rows if r['dataset'] == dataset]
        require(len(chosen) == count and len({r['group_id'] for r in chosen}) == group_count,
                'development_scope_changed')
    return rows


def write_once(path, value):
    if path.exists():
        require(load(path) == value, 'immutable_preparation_changed:' + path.name)
    else:
        atomic_json(path, value)



def prepare():
    rows = rows_only()
    frozen_cohort = load(COHORT / 'freeze.json')
    require(sha(COHORT / 'dev.json') == frozen_cohort['manifest_sha256']
            and sha(COHORT / 'dev_labels.json') == frozen_cohort['labels_sha256'], 'development_source_changed')
    for row in rows:
        path = V2 / row['image_path']
        require(path.resolve() == path and path.is_file() and sha(path) == row['image_sha256'], 'development_image_changed')
    labels = load(COHORT / 'dev_labels.json')
    fallbacks = {}
    for dataset in ('nutrition5k', 'asa24'):
        fallbacks[dataset] = {}
        for fold in range(5):
            train = [r for r in rows if r['dataset'] == dataset and r['fold'] != fold]
            values = {k: statistics.median(labels[r['sample_id']]['truth'][k] for r in train) for k in KEYS}
            require(all(math.isfinite(v) and v >= 0 for v in values.values()), 'invalid_training_fallback')
            fallbacks[dataset][str(fold)] = dict(vector=values, training_ids=[r['sample_id'] for r in train],
                training_groups=sorted({r['group_id'] for r in train}))
    write_once(HERE / 'prepared/context.json', dict(rows=rows, fallbacks=fallbacks))
    prepare_copy()
    index = SearchIndex()
    require(index.collection.count() == 5624, 'original5624_Chroma_required')
    # No model/client is constructed by preparation.
    write_once(HERE / 'authorization.json', {
        'date': '2026-11-05', 'authorization': 'Explicit user request to replace only visualmodel with Gemini and run full C.',
        'text_model': 'gpt-6.1-sol', 'visual_model': 'gemini-3.8-flash',
        'chat_destination': 'https://api.zicc.cc/v1/chat/completions',
        'embedding_destination': 'https://api.openai.com/v1/embeddings',
        'development_images': 843, 'global_concurrency': 32,
        'independent_acceptance': 'sealed', 'github_upload': False})
    write_once(HERE / 'freeze.json', freeze_value())
    event(status='prepared', development_images=843, Gemini_layouts_to_predict=314,
          FNDDS_vectors_reused=5624, new_api_calls=0, global_concurrency=32)


def freeze_value():
    source = [HERE / n for n in ('run.py', 'pipeline.py', 'score.py', 'newcommon.py', 'chroma_index.py', 'provider.py', 'config.py', 'verify_completed.py')]
    source += list(SNAPSHOT.glob('*.py'))
    source += [V2 / ('src/' + n) for n in ('opt_pipeline.py', 'opt_provider.py', 'opt_metrics.py')]
    source += [PREVIOUS / 'score.py', PREVIOUS / 'common.py', V2 / 'round4/src/artifacts.py']
    source += [REPO / 'code/rag_food_code.py', REPO / 'code/nutrient_estimate_mix.py']
    inputs = [COHORT / n for n in ('freeze.json', 'dev.json', 'dev_labels.json')]
    inputs += [HERE / 'prepared/context.json', HERE / 'prepared/chroma_source.json', HERE / 'authorization.json']
    inputs += [V2 / ('data/vectors/' + n) for n in ('manifest.json', 'collection.json', 'codes.json', 'embeddings.npy')]
    inputs += [V2 / 'data/catalog.json', V2 / 'round11/prepared/catalog.json']
    return dict(schema_version=1, name='C-visualmodel-Gemini-3.8-Flash-text-Sol',
        format_compatibility='Ignore empty query separators; Gemini unique JSON exact-substring extraction; raw cache preserved, no redraw.',
        scope=dict(nutrition5k=314, asa24=529, unique_development_images=843,
                   complete_groups=dict(nutrition5k=293, asa24=43), independent_acceptance='sealed'),
        models=dict(chat='gpt-6.1-sol', visual='gemini-3.8-flash', embedding='text-embedding-3-large', temperature=1),
        retrieval=dict(prompt='release_original_literal_five_rewrites_plus_original_sixth',
                       parser="strip_and_split_newlines_drop_only_blank_separator_lines_keep_other_text", include_original=False, search='original_Chroma_L2',
                       k_per_query=4, union='first_seen_in_query_result_order', BM25=False,
                       query_scope='C_fixed_leaf_descriptions_or_ASA_single_item_description'),
        N5=dict(layout='fresh_Gemini_original_C_layout_prompt', crops=False, image_mode='native_max1024',
                portion_mode='total_ratio', selected_codes_per_physical_leaf='one_to_three',
                nutrition='arithmetic_mean_density_times_one_gram_mass', completion_tokens=8192,
                calibration='other_fold_shared_mass_grid0.8_to1.25_half_shrinkage'),
        ASA=dict(identity='existing_optimized_prompt_with_MultiQuery_retrieval', image_mode='square256',
                 portion_mode='continuous_option', completion_tokens=4096, examples=False,
                 calibration='new_other_fold_raw_factor_full_without_half_shrinkage',
                 primary='conditional_Exact_reference_code_density_not_candidate_mean', E2E='all529_separately'),
        no_labeled_support_gallery=True, no_model_estimated_nutrient_densities=True,
        cumulative_transmissions_per_exact_request=3, global_concurrent_requests=32,
        selection='one_whole_raw_profile_and_one_predeclared_corrected_profile_no_column_splicing',
        versions={name: importlib.metadata.version(name) for name in ('chromadb', 'langchain', 'langchain-community', 'langchain-core', 'numpy')},
        files={str(p.relative_to(REPO)): sha(p) for p in source + inputs})


def context(profile=None):
    require(load(HERE / 'freeze.json') == freeze_value(), 'frozen_method_or_inputs_changed')
    value = load(HERE / 'prepared/context.json')
    require(value['rows'] == rows_only(), 'prepared_rows_changed')
    value['catalog'] = load(V2 / 'round11/prepared/catalog.json')
    value['frozen'] = fingerprint(load(HERE / 'freeze.json'))
    if profile:
        dataset = 'nutrition5k' if profile == 'N5' else 'asa24'
        value['selected_rows'] = [r for r in value['rows'] if r['dataset'] == dataset]
        for row in value['selected_rows']:
            path = V2 / row['image_path']
            require(path.resolve() == path and sha(path) == row['image_sha256'], 'actual_development_image_changed')
    return value


def parallel(rows, fn, provider, workers):
    executor = ThreadPoolExecutor(max_workers=workers)
    futures = {executor.submit(fn, row): row['sample_id'] for row in rows}
    output = {}
    try:
        for future in as_completed(futures):
            output[futures[future]] = future.result()
    except BaseException:
        provider.stopped = True
        for future in futures:
            future.cancel()
        raise
    finally:
        executor.shutdown(wait=True, cancel_futures=True)
    return [output[r['sample_id']] for r in rows]


def n5_record(row, identity, portion, fallback):
    valid = portion.get('status') == 'ok' and portion.get('prediction') is not None
    repair = bool(identity.get('repaired') or portion.get('repaired'))
    codes = identity.get('final_codes', [])
    return dict(sample_id=row['sample_id'], dataset=row['dataset'], group_id=row['group_id'], fold=row['fold'],
        final_codes=codes, primary_code=codes[0] if codes else None, retrieved_codes=identity.get('retrieved_codes', []),
        items=deepcopy(identity.get('items', [])), parents=deepcopy(identity.get('parents', [])),
        raw_prediction=deepcopy(portion.get('prediction')) if valid else None,
        prediction=deepcopy(portion['prediction'] if valid else fallback),
        raw_leaves=deepcopy(portion.get('raw_leaves', [])) if valid else [],
        portion_result=deepcopy(portion), native_complete=valid and not repair, repair_used=repair,
        fallback=not valid, fallback_reason=None if valid else portion.get('failure', 'incomplete_dish'),
        method_fallback=False, conditional=None, e2e=None,
        method='C_release_MultiQuery_and_same_food_candidate_mean')


def run_n5(ctx, provider, store, index, workers):
    pipe = method.make_component_pipeline(lambda m: provider.chat(m, max_completion_tokens=8192),
                                         provider.embed, ctx['catalog'], index.search4)
    def one(row):
        sid = row['sample_id']
        fallback = ctx['fallbacks'][row['dataset']][str(row['fold'])]['vector']
        layout_binding = dict(row=row, stage='original_C_layout', visual_model='gemini-3.8-flash')
        layout = store.get('layout', sid, layout_binding)
        if layout is None:
            layout = pipe.layout(V2 / row['image_path'])
            store.put('layout', sid, layout_binding, layout)
        binding = dict(row=row, layout_sha256=fingerprint(layout), config=C_CONFIG)
        saved = store.get('record', sid, binding)
        if saved is not None:
            return saved
        identity = store.get('identity', sid, binding)
        if identity is None:
            identity = pipe.identify(V2 / row['image_path'], C_CONFIG, layout=layout)
            store.put('identity', sid, binding, identity)
        portion_binding = dict(identity_sha256=fingerprint(identity), config=C_CONFIG)
        portion = store.get('portion', sid, portion_binding)
        if portion is None:
            portion = pipe.portion(V2 / row['image_path'], identity, C_CONFIG)
            store.put('portion', sid, portion_binding, portion)
        record = n5_record(row, identity, portion, fallback)
        store.put('record', sid, binding, record)
        return record
    return parallel(ctx['selected_rows'], one, provider, workers)


def asa_branch(result, code, options, catalog, fallback):
    valid = result.get('status') == 'ok' and result.get('continuous_grams') is not None
    if valid:
        option = method.current.nearest_option(options, result['continuous_grams'])
    elif options:
        center = statistics.median(o['grams'] for o in options)
        option = min(options, key=lambda o: (abs(o['grams'] - center), o['grams'], o['option_id']))
    else:
        option = None
    prediction = ({'weight': option['grams'], **{k: option['grams'] * catalog['foods'][code]['density'][k] / 100 for k in KEYS[1:]}}
                  if option else dict(fallback))
    return dict(code=code, prediction=prediction, option_id=option['option_id'] if option else None,
        continuous_grams=result.get('continuous_grams') if valid else None,
        fallback=not valid, fallback_reason=None if valid else result.get('failure', 'portion_failed'), raw_result=result)


def validate_identity_seal(ctx, directory):
    ids = {r['sample_id'] for r in ctx['rows'] if r['dataset'] == 'asa24'}
    store = Store(directory, ctx['frozen'], 529)
    seal_binding = dict(population=sorted(ids), method='all_blind_identities_before_conditional_context')
    sealed = store.get('identity_seal', 'all', seal_binding)
    require(sealed is not None and set(sealed) == ids, 'complete_blind_ASA_identity_seal_required')
    for row in ctx['rows']:
        if row['dataset'] != 'asa24':
            continue
        binding = dict(row=row, config=ASA_CONFIG)
        identity = store.get('identity', row['sample_id'], binding)
        require(identity is not None and fingerprint(identity) == sealed[row['sample_id']], 'ASA_identity_seal_changed')
    return sealed


def run_asa(ctx, provider, store, index, workers):
    rows, catalog = ctx['selected_rows'], ctx['catalog']
    pipe = method.make_asa_pipeline(lambda m: provider.chat(m, max_completion_tokens=4096),
                                   provider.embed, catalog, index.search4)
    def identify(row):
        sid, binding = row['sample_id'], dict(row=row, config=ASA_CONFIG)
        result = store.get('identity', sid, binding)
        if result is None:
            result = pipe.identify_select(V2 / row['image_path'], 'asa24', ASA_CONFIG)
            store.put('identity', sid, binding, result)
        return result
    ordered = parallel(rows, identify, provider, workers)
    identities = dict(zip((r['sample_id'] for r in rows), ordered))
    seal = {sid: fingerprint(value) for sid, value in identities.items()}
    seal_binding = dict(population=sorted(identities), method='all_blind_identities_before_conditional_context')
    store.put('identity_seal', 'all', seal_binding, seal)
    validate_identity_seal(ctx, store.directory)
    # The predictor sees no query labels until ALL blind identities are sealed.
    all_labels = load(COHORT / 'dev_labels.json')
    labels = {row['sample_id']: all_labels[row['sample_id']] for row in rows}
    del all_labels
    def one(row):
        sid, identity = row['sample_id'], identities[row['sample_id']]
        fallback = ctx['fallbacks']['asa24'][str(row['fold'])]['vector']
        codes = identity.get('final_codes', []) if identity.get('status') == 'ok' else []
        code = codes[0] if codes else None
        true_code = labels[sid]['food_code']
        permitted = dict(code=true_code, options=deepcopy(catalog['asa_options'][true_code])) if true_code in codes else None
        binding = dict(row=row, identity_sha256=seal[sid], conditional_context=permitted, config=ASA_CONFIG)
        cached = store.get('record', sid, binding)
        if cached is not None:
            return cached
        def infer(context_value, stage):
            bound = dict(identity_sha256=seal[sid], context=context_value, config=ASA_CONFIG)
            value = store.get(stage, sid, bound)
            if value is None:
                value = pipe.portion(V2 / row['image_path'], identity, 'asa24', ASA_CONFIG,
                                     conditional_context=context_value)
                store.put(stage, sid, bound, value)
            return value
        raw = infer(None, 'portion_e2e')
        e2e = asa_branch(raw, code, catalog['standard_options'].get(code, []), catalog, fallback)
        conditional = None
        if permitted:
            cond_raw = deepcopy(raw) if code == true_code and raw.get('status') == 'ok' else infer(permitted, 'portion_conditional')
            conditional = asa_branch(cond_raw, true_code, permitted['options'], catalog, fallback)
        repaired = bool(identity.get('repaired') or raw.get('repaired') or
                        (conditional and conditional['raw_result'].get('repaired')))
        record = dict(sample_id=sid, dataset='asa24', group_id=row['group_id'], fold=row['fold'],
            final_codes=codes, primary_code=code, retrieved_codes=identity.get('retrieved_codes', []),
            items=identity.get('items', []), description=identity.get('description'),
            identity_status=identity.get('status'), identity_failure=identity.get('failure'),
            conditional=conditional, e2e=e2e, prediction=e2e['prediction'],
            raw_prediction=e2e['prediction'] if not e2e['fallback'] else None,
            native_complete=not e2e['fallback'] and not repaired, fallback=e2e['fallback'],
            fallback_reason=e2e['fallback_reason'], repair_used=repaired, method_fallback=False)
        store.put('record', sid, binding, record)
        return record
    return parallel(rows, one, provider, workers)


def profile_run(profile, workers, allow_paid):
    ctx = context(profile)
    directory = HERE / 'run' / profile
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / '.process.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if (directory / 'completion.json').exists():
            import score
            score.completed_records(ctx['selected_rows'], profile, ctx['frozen'])
            event(profile=profile, status='already_complete', new_api_calls=0)
            return
        index = SearchIndex()
        store = Store(directory, ctx['frozen'], len(ctx['selected_rows']))
        provider = CachedProvider(profile, allow_paid=allow_paid)
        atomic_json(directory / 'status.json', dict(profile=profile, status='running', started=stamp(), workers=workers))
        try:
            records = (run_n5 if profile == 'N5' else run_asa)(ctx, provider, store, index, workers)
            require(len(records) == len(ctx['selected_rows']), 'incomplete_prediction_population')
            context(profile)
            atomic_json(directory / 'records.json', records)
            atomic_json(directory / 'completion.json', dict(profile=profile, records=len(records),
                freeze_sha256=ctx['frozen'], records_sha256=sha(directory / 'records.json'), finished=stamp()))
            atomic_json(directory / 'status.json', dict(profile=profile, status='completed', records=len(records), finished=stamp()))
            event(profile=profile, status='completed', records=len(records))
        except BaseException as exc:
            provider.stopped = True
            atomic_json(directory / 'status.json', dict(profile=profile, status='stopped', error_type=type(exc).__name__, updated=stamp()))
            raise
        finally:
            atomic_json(directory / 'usage.json', usage_summary(profile))
            provider.close()


def score_completed():
    ctx = context()
    import score
    for profile, dataset in (('N5', 'nutrition5k'), ('ASA', 'asa24')):
        score.completed_records([r for r in ctx['rows'] if r['dataset'] == dataset], profile, ctx['frozen'])
    validate_identity_seal(ctx, HERE / 'run/ASA')
    # Full843 completion and ASA barrier verified BEFORE loading evaluation labels.
    labels = load(COHORT / 'dev_labels.json')
    result = score.score_all(ctx['rows'], labels, ctx['catalog'], ctx['frozen'])
    event(status='scored', raw_passed=result['profiles']['raw']['passed_checks'],
          retained_passed=result['profiles']['retained']['passed_checks'], total_checks=20)


def coordinate(workers, allow_paid):
    context()
    require(allow_paid, 'explicit_paid_flag_required')
    with (HERE / '.coordinator.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        children, streams = {}, []
        for profile in ('N5', 'ASA'):
            stream = (HERE / (profile + '.log')).open('a')
            streams.append(stream)
            child = subprocess.Popen([sys.executable, '-B', str(__file__), '--profile', profile,
                                      '--workers', str(workers), '--allow-paid'],
                                     stdout=stream, stderr=subprocess.STDOUT, cwd=REPO)
            children[profile] = child
        event(status='launched', pids={p: c.pid for p, c in children.items()}, global_concurrency=32)
        try:
            while any(c.poll() is None for c in children.values()):
                if any(c.poll() not in (None, 0) for c in children.values()):
                    for c in children.values():
                        if c.poll() is None:
                            c.terminate()
                    break
                time.sleep(2)
            codes = {p: c.wait() for p, c in children.items()}
        finally:
            for stream in streams:
                stream.close()
        atomic_json(HERE / 'process_completion.json', dict(exit_codes=codes, finished=stamp()))
        require(all(code == 0 for code in codes.values()), 'one_or_more_profiles_stopped')
        score_completed()
        event(status='all843_complete', finished=stamp())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument('--prepare', action='store_true')
    action.add_argument('--run', action='store_true')
    action.add_argument('--score', action='store_true')
    action.add_argument('--profile', choices=['N5', 'ASA'])
    parser.add_argument('--workers', type=int, default=32)
    parser.add_argument('--allow-paid', action='store_true')
    args = parser.parse_args()
    require(1 <= args.workers <= 32, 'workers_must_be_1_to32')
    if args.prepare:
        prepare()
    elif args.profile:
        profile_run(args.profile, args.workers, args.allow_paid)
    elif args.score:
        score_completed()
    else:
        coordinate(args.workers, args.allow_paid)


if __name__ == '__main__':
    main()
