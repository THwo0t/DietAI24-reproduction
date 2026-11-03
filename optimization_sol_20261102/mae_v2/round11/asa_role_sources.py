"""Fixed ASA identity projections. No labels/images, graph or action permission.

Inputs are held projections from the reviewed capture/development/legacy loaders.
The caller must revalidate those loaders before and after consuming this result.
"""
import csv
import io
import re
from copy import deepcopy
from decimal import Decimal, InvalidOperation
from pathlib import Path

from source_census import REPO, PREFIX, LEGACY_MANIFESTS, bounded_read, decode, sha, require
from source_capture import CENSUS, CENSUS_SHA, V1_PROTOCOL, pin_for
from n5_sources import PATHS, ANCHORS, HEX
from development_identity import FIELDS

V1 = 'optimization_sol_20261102/'
MANIFESTS = {s: V1 + 'data/cohorts/' + s + '.jsonl' for s in ('dev', 'validation')}
VALIDATION = PREFIX + 'data/cohorts/sealed/validation.jsonl'
HISTORY = ('df_results.csv', 'df_results_dev.csv')
RUN = re.compile(r'runs/[A-Za-z0-9_.-]+/asa24_food_codes\.csv\Z')
CODE = re.compile(r'[0-9]{8}\Z')
NAME = re.compile(r'[A-Za-z0-9_.-]+\Z')


def source_code(value):
    require(isinstance(value, str) and 0 < len(value) <= 64 and value == value.strip(),
            'exact_history_food_code_required')
    try:
        number = Decimal(value)
    except InvalidOperation:
        raise ValueError('exact_history_food_code_required') from None
    require(number.is_finite() and Decimal(10000000) <= number < Decimal(100000000)
            and number == number.to_integral_value(), 'exact_history_food_code_required')
    return str(int(number))


def _rows(raw, split, counts, *, generation):
    require(generation in (1, 2), 'registered_manifest_generation_required')
    rows = [decode(line) for line in raw.splitlines()]
    require(len(rows) == sum(counts.values()), 'exact_manifest_population_required')
    seen = set(); images = set(); populations = {k: [] for k in counts}
    for row in rows:
        require(isinstance(row, dict) and set(row) == FIELDS, 'identity_only_manifest_required')
        dataset = row['dataset']; sample = row['sample_id']
        require(dataset in populations and isinstance(sample, str) and sample.startswith(dataset+'-')
                and sample not in seen, 'unique_manifest_identity_required')
        require(row['split'] == split and isinstance(row['group_id'], str) and row['group_id']
                and ((type(row['fold']) is int and row['fold'] in range(5)) if split == 'dev'
                     else row['fold'] is None), 'manifest_binding_required')
        path = row['image_path']
        if generation == 1 and dataset == 'nutrition5k':
            dish = sample.removeprefix('nutrition5k-')
            valid_path = (re.fullmatch(r'dish_[0-9]{10}', dish) is not None
                          and path == f'data/{split}/images/{dish}/rgb.png')
        elif generation == 2:
            name = sha(('dietai24-mae-v2-20261102|sample|' + sample).encode()) + '.png'
            valid_path = path == f'data/{dataset}/{split}/images/{name}'
        else:
            valid_path = (isinstance(path, str) and
                re.fullmatch(r'data/asa24/' + split + r'/images/[A-Za-z0-9_.-]+\.png', path) is not None
                and '..' not in path.split('/'))
        require(valid_path and path not in images and HEX.fullmatch(row['image_sha256']),
                'manifest_image_binding_required')
        seen.add(sample); images.add(path); populations[dataset].append(row)
    require(all(len(populations[d]) == n for d,n in counts.items()), 'dataset_population_required')
    return populations['asa24']


def _same(old, current):
    keys = FIELDS - {'image_path'}
    def projection(rows):
        require(len({r['sample_id'] for r in rows}) == len(rows), 'duplicate_current_identity')
        return {r['sample_id']: {k:r[k] for k in keys} for r in rows}
    require(projection(old) == projection(current), 'preserved_asa_identity_changed')


def _load_at(repo, capture, development, legacy, *, census_sha=CENSUS_SHA,
             validation_sha=ANCHORS['validation_seal']):
    repo = Path(repo)
    require(repo.is_absolute() and repo.resolve() == repo, 'canonical_role_root_required')
    held = {}; sources = {}; unresolved = []
    def read(path, expected=None, root=repo):
        raw = bounded_read(root, path)
        require(expected is None or sha(raw) == expected, 'asa_role_source_hash_changed')
        held[(root,path)] = raw; sources[str(root/path)] = sha(raw)
        return raw
    protocol = decode(read(V1_PROTOCOL, pin_for(capture['source_sha256'], repo, V1_PROTOCOL)))
    old = {}
    for split, path in MANIFESTS.items():
        key = path.removeprefix(V1)
        old[split] = _rows(read(path, protocol['frozen_sha256'][key]), split,
            {'asa24':99 if split=='dev' else 78, 'nutrition5k':100 if split=='dev' else 200}, generation=1)
    core = development['asa_rows']
    require(len(core) == 99 and len({r['group_id'] for r in core}) == 23,
            'immutable_asa_core_population_required')
    _same(old['dev'], core)
    seal = decode(read(PATHS['validation_seal'], validation_sha))
    artifacts = seal['artifacts']
    val = _rows(read(VALIDATION, artifacts[VALIDATION.removeprefix(PREFIX)]), 'validation',
                {'asa24':78,'nutrition5k':200}, generation=2)
    for row in val:
        require(artifacts.get(row['image_path']) == row['image_sha256'], 'validation_image_seal_changed')
    _same(old['validation'], val)
    require(len({r['group_id'] for r in val}) == 23, 'immutable_asa_validation_groups_required')
    require(capture.get('census_sha256', census_sha) == census_sha, 'capture_census_binding_changed')
    census = decode(read(CENSUS, census_sha))
    require(census['status'] == 'path_census_complete_not_exposure_closure', 'completed_census_required')
    entries = census['entries']; paths = [e['path'] for e in entries
        if e.get('kind') == 'file' and RUN.fullmatch(e.get('path',''))]
    require(len(paths) == len(set(paths)), 'duplicate_history_census_path')
    roles = {r:{k:set() for k in ('codes','images','hashes','rgb_hashes')}
             for r in ('history','core','validation','training','retired')}
    pairs = []
    def code_image(code, image):
        code = source_code(code)
        require(CODE.fullmatch(code) and NAME.fullmatch(image) and image not in ('.','..'),
                'exact_history_code_image_required')
        roles['history']['codes'].add(code); roles['history']['images'].add(image)
        pairs.append((code,image))
    registered = protocol['source_sha256']
    def inherited(path, root=repo):
        keys = [k for k in (path,str(root/path)) if k in registered]
        if not keys:
            unresolved.append({'source_path':path,'reason':'unresolved_history_pin'})
            return None
        require(len({registered[k] for k in keys}) == 1, 'conflicting_history_pins')
        return registered[keys[0]]
    for path in (*HISTORY,*sorted(paths)):
        expected = inherited(path)
        raw = read(path, expected)
        reader = csv.DictReader(io.StringIO(raw.decode('utf-8-sig')), strict=True)
        require(reader.fieldnames and len(reader.fieldnames)==len(set(reader.fieldnames))
                and {'FoodCode','Image'} <= set(reader.fieldnames), 'history_identity_headers_required')
        for row in reader:
            require(None not in row and all(v is not None for v in row.values()), 'rectangular_history_required')
            code_image(row['FoodCode'],row['Image'])
    require(len(legacy['sources']) == 4 and {s['path'] for s in legacy['sources']} == set(LEGACY_MANIFESTS),
            'fixed_legacy_sources_required')
    for source in legacy['sources']:
        path=source['path']; expected=inherited(path,repo.parent)
        if 'sha256' in source:
            read(path, source['sha256'], repo.parent)
            require(expected is None or expected == source['sha256'], 'legacy_historical_pin_changed')
        else: unresolved.append({'source_path':path,'reason':'legacy_source_unresolved'})
    for row in legacy['private_identities']:
        require(row['source_path'] in LEGACY_MANIFESTS, 'unregistered_legacy_identity_source')
        if row['dataset'] == 'asa24':
            roles['history']['images'].add(row['image_basename'])
            if row.get('reference_food_code'): code_image(row['reference_food_code'],row['image_basename'])
    for role, rows in (('core',old['dev']),('validation',old['validation'])):
        for row in rows:
            roles[role]['images'].add(row['image_path'].rsplit('/',1)[-1])
            roles[role]['hashes'].add(row['image_sha256'])
            match=re.fullmatch(r'asa24-([0-9]{8})-.+',row['sample_id'])
            require(match is not None, 'asa_sample_code_required')
            roles[role]['codes'].add(match[1])
    for (root,path), raw in held.items():
        require(bounded_read(root,path) == raw, 'asa_role_source_changed_during_capture')
    return {'roleanchors':roles, 'historical_pairs':pairs, 'source_hashes':sources,
        'currentmanifestbinding':{'core':deepcopy(core),'validation':deepcopy(val)},
        'originalmanifestbinding':{'core':deepcopy(old['dev']),'validation':deepcopy(old['validation'])},
        'unresolved_sources':unresolved, 'unknowncounts':{'unresolved_source_pins':len(unresolved)},
        'role_inventory_complete':False, 'source_association_complete':False,
        'pending':['F_to_O_core_only_caller_registration','training_and_retired_source_code_only_inventory',
                   'RGB_anchors_supplied_by_separate_authenticated_content_graph'],
        'source_corpus_is_not_prior_api_exposure':True, 'validation_labels_or_images_opened':False,
        'candidate_eligibility_evaluated':False, 'grants_sampling_download_or_inference':False,'api_calls':0}


def load_asa_role_sources(capture, development, legacy):
    return _load_at(REPO,capture,development,legacy)
