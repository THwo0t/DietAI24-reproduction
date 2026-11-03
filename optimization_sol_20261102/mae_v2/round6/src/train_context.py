"""Train-only L pilot loader and narrow, fold-local inference views.

Nothing executes on import. Production reads only the fixed external-training
release/gallery and explicitly named sources. Supervision is consumed locally
to construct five 184-group assets. Each query's selected fold view excludes
its entire held-out fold; its image may legitimately support another fold.
No unaggregated official target map survives. A separate scorer reopens the
scoring references after the complete paired seal.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import io
import math
from pathlib import Path
import statistics

from PIL import Image
from round4.src.artifacts import decode, fingerprint
from round4.src import catalog_estimator, retrieval
from round5.src import gram_prior

ROOT = Path(__file__).resolve().parents[2]
PROTOCOL = 'round6/PROTOCOL.md'
PROTOCOL_SHA256 = '7b2308a8e59486c8da5bd2afbf3de7910164427e795a87978adb329b4dcb38a7'
TRAIN = 'round4/data/train'
GALLERY = 'round4/runs/J_gallery'
TRAIN_FREEZE_SHA256 = '885f8d1a0573313e9e09771f3c38ec938b807e9ffcc9525d706867d3d0d081cb'
GALLERY_COMPLETION_SHA256 = '57d97d46b9e62a3933af23a1773bf91590b0532a8a99d60ab977ec7908805458'
PILOT_SEED = 'region-atlas-pilot-r6.1'
TARGETS = ('weight', 'energy', 'fat', 'carbs', 'protein')
SOURCES = (PROTOCOL, 'round6/src/train_context.py', 'round6/src/run_pilot.py',
    'round6/src/atlas_estimator.py', 'round6/src/runtime.py', 'round6/src/service_evidence.py',
    'round6/tests/test_train_context.py', 'round6/tests/test_run_pilot.py',
    'round6/tests/test_atlas_estimator.py', 'round6/tests/test_runtime.py',
    'round6/tests/test_service_evidence.py', 'round5/src/run_train_prior.py',
    'round5/src/gram_prior.py')
METHOD_CONFIG = {'candidate': 'L', 'method': 'region_atlas_training_pilot_r6.1',
    'namespace': 'region-atlas-pilot-r6-l.1', 'chat_model': 'gpt-6.1-sol',
    'temperature': 1, 'rerank_tokens': 4096, 'annotation_tokens': 4096,
    'estimate_tokens': 8192, 'format_repairs': 1, 'http_attempts': 3,
    'read_timeout_seconds': 600, 'max_workers': 2, 'retrieval_k': 12,
    'support_count': 4, 'max_crop_cards_per_support': 2, 'max_images': 13,
    'pilot_seed': PILOT_SEED, 'pilot_queries_per_fold': 5, 'fold_seed': gram_prior.VERSION,
    'calibration': None, 'new_embedding_requests': 0, 'initial_chat_ceiling': 175,
    'logical_chat_ceiling_with_repairs': 350, 'transmission_ceiling': 1050,
    'development_opened': False, 'validation_opened': False}


class ContextError(ValueError):
    """Fixed safe codes only, never include label values or paths."""


def require(condition, code):
    if not condition:
        raise ContextError(code)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def rgb_hash(raw):
    with Image.open(io.BytesIO(raw)) as image:
        image = image.convert('RGB')
        return digest(str(image.size).encode() + b'\0' + image.tobytes())


def pilot_groups(group_folds, per_fold=5):
    require(type(per_fold) is int and per_fold > 0 and set(group_folds.values()) == set(range(5)),
            'five_folds_and_positive_pilot_size_required')
    result = []
    for fold in range(5):
        groups = [g for g, value in group_folds.items() if value == fold]
        require(len(groups) >= per_fold, 'insufficient_groups_in_pilot_fold')
        groups.sort(key=lambda g: (digest((PILOT_SEED + '\0' + g).encode()), g))
        result.extend(groups[:per_fold])
    return result


def build_views(rows, ingredients, targets, vectors, *, per_fold=5, expected_n=230):
    """Pure supervision projection; returned query and index views contain no GT.

    rows have verified explicit image paths/hashes. ingredients retain original
    names and nutrient amounts. All supervised aggregation excludes each whole
    held-out fold, including catalogue identity/name vocabulary and fallback.
    """
    require(isinstance(rows, list) and len(rows) == expected_n, 'training_population_changed')
    ids = {row['sample_id'] for row in rows}
    require(len(ids) == expected_n and len({r['group_id'] for r in rows}) == expected_n,
            'one_unique_training_image_per_group_required')
    require(set(ingredients) == set(targets) == set(vectors) == ids, 'training_projection_population_changed')
    folds = gram_prior.assign_folds(r['group_id'] for r in rows)
    require(expected_n % 5 == 0 and all(sum(f == v for v in folds.values()) == expected_n // 5
                                    for f in range(5)), 'balanced_training_folds_required')
    selected = set(pilot_groups(folds, per_fold))
    normalized, truths = {}, {}
    for row in rows:
        sid = row['sample_id']
        projected = [{k: item[k] for k in ('ingredient_id', 'grams', 'nutrients')} for item in ingredients[sid]]
        normalized[sid] = gram_prior._ingredients(projected)
        truths[sid] = gram_prior._targets(targets[sid])
        retrieval._unit_vector(vectors[sid])
    fold_assets, fold_entries, fold_vectors, fold_annotation_names, audits = {}, {}, {}, {}, {}
    by_id = {r['sample_id']: r for r in rows}
    for fold in range(5):
        training = sorted(sid for sid, row in by_id.items() if folds[row['group_id']] != fold)
        heldout = sorted(sid for sid, row in by_id.items() if folds[row['group_id']] == fold)
        totals, names = {}, {}
        for sid in training:
            for item in ingredients[sid]:
                if item['grams'] <= 0:
                    continue
                identifier, name = item['ingredient_id'], item['name']
                require(isinstance(name, str) and bool(name.strip()), 'ingredient_name_required')
                require(identifier not in names or names[identifier].casefold() == name.casefold(),
                        'training_ingredient_name_conflict')
                names.setdefault(identifier, name)
            for identifier, item in normalized[sid].items():
                total = totals.setdefault(identifier, {'grams': [], **{k: [] for k in TARGETS[1:]}})
                total['grams'].append(item['grams'])
                for key in TARGETS[1:]:
                    total[key].append(item['nutrients'][key])
        catalog = [{'ingredient_id': identifier, 'name': names[identifier],
                    'density_per_100g': {key: 100 * math.fsum(totals[identifier][key]) /
                        math.fsum(totals[identifier]['grams']) for key in TARGETS[1:]}}
                   for identifier in sorted(totals)]
        catalog_estimator._catalog(catalog)
        supports = {sid: {'image_path': by_id[sid]['image_path'],
                         'ingredients': [{'ingredient_id': identifier, 'grams': item['grams']}
                             for identifier, item in sorted(normalized[sid].items())]}
                    for sid in training}
        fallback = {key: statistics.median(truths[sid][key] for sid in training) for key in TARGETS}
        assets = {'scope': 'external_train_only',
                  'training_sha256': fingerprint({'training_ids': training, 'catalog': catalog,
                                                  'supports': supports, 'fallback': fallback}),
                  'catalog': catalog, 'fallback': fallback, 'supports': supports}
        entries = [{'train_id': sid, 'screening_group_id': by_id[sid]['group_id'],
                    **{k: by_id[sid][k] for k in ('image_sha256', 'rgb_sha256')}} for sid in training]
        fold_assets[fold], fold_entries[fold] = assets, entries
        fold_vectors[fold] = {sid: deepcopy(vectors[sid]) for sid in training}
        # Annotation wording belongs to that support image's own recipe.
        # A fold's first occurrence can use a different capitalization for a
        # shared ingredient name; it must not create a second atlas payload.
        fold_annotation_names[fold] = {}
        for sid in training:
            own_names = {}
            for item in ingredients[sid]:
                if item['grams'] > 0:
                    own_names.setdefault(item['ingredient_id'], item['name'])
            fold_annotation_names[fold][sid] = [{'ingredient_id': identifier, 'name': own_names[identifier]}
                                              for identifier in sorted(own_names)]
        audits[str(fold)] = {'training_ids': training, 'heldout_ids': heldout,
                             'assets_sha256': fingerprint(assets), 'training_n': len(training)}
    queries = []
    pilot_rows = []
    for row in sorted(rows, key=lambda r: (folds[r['group_id']], r['sample_id'])):
        if row['group_id'] not in selected:
            continue
        queries.append({'query_id': row['sample_id'], 'image_path': row['image_path'],
                        'screening_group_id': row['group_id'],
                        **{k: row[k] for k in ('image_sha256', 'rgb_sha256')}})
        pilot_rows.append({'sample_id': row['sample_id'], 'group_id': row['group_id'],
                           'fold': folds[row['group_id']], 'dataset': 'nutrition5k', 'split': 'train_pilot'})
    require(len(queries) == 5 * per_fold, 'pilot_population_changed')
    return {'queries': queries, 'rows': pilot_rows, 'fold_assets': fold_assets,
            'fold_entries': fold_entries, 'fold_vectors': fold_vectors,
            'fold_annotation_names': fold_annotation_names,
            'query_vectors': {q['query_id']: deepcopy(vectors[q['query_id']]) for q in queries},
            'fold_audit': audits, 'group_folds': folds}


def load_context(base=ROOT):
    """Production preflight. Explicit training-only reads; no Provider exists."""
    from round5.src import run_train_prior as old_loader
    from round4.src.artifacts import ArtifactStore
    base = Path(base).resolve()
    data = old_loader.load_training(base)
    old_reader = data['reader']
    # The old loader's hard allowlist does not authorize new sources or images.
    # Extend a fresh reader with exactly the pinned manifest image paths below.
    manifest = [decode(line) for line in old_reader.read(TRAIN + '/manifest.jsonl').splitlines()]
    full_ingredients = old_reader.json(TRAIN + '/ingredients.json')['records']
    ingredient_by_id = {row['sample_id']: row['ingredients'] for row in full_ingredients}
    allowed = {*SOURCES, *(row['image_path'] for row in manifest)}
    class Reader:
        def __init__(self):
            self.hashes = dict(old_reader.hashes)
        def read(self, name, expected=None):
            require(name in allowed, 'input_path_not_allowlisted')
            path = base / name
            require(not Path(name).is_absolute() and '..' not in Path(name).parts
                    and path.resolve() == path and path.is_file(), 'unsafe_or_missing_input')
            raw = path.read_bytes()
            value = digest(raw)
            require(expected is None or value == expected, 'pinned_input_changed')
            require(name not in self.hashes or self.hashes[name] == value, 'bound_input_changed')
            self.hashes[name] = value
            return raw
        def unchanged(self, *, images=True):
            old_reader.unchanged()
            for name in allowed:
                if name in self.hashes and (images or not name.startswith(TRAIN + '/images/')):
                    self.read(name, self.hashes[name])
    reader = Reader()
    reader.read(PROTOCOL, PROTOCOL_SHA256)
    for name in SOURCES:
        reader.read(name)
    rows = []
    for row in manifest:
        raw = reader.read(row['image_path'], row['image_sha256'])
        require(rgb_hash(raw) == row['rgb_sha256'], 'training_rgb_changed')
        rows.append({**row, 'image_path': str(base / row['image_path'])})
    views = build_views(rows, ingredient_by_id, data['official_targets'], data['vectors_by_id'])
    gallery_intent = old_reader.json(GALLERY + '/intent.json')
    gallery_store = ArtifactStore(base / GALLERY, gallery_intent['binding'],
        [r['sample_id'] for r in rows], verify_sources=old_reader.unchanged, root=base / 'round4')
    # No official-target/global-ingredient map is retained. Other-fold views
    # may legitimately contain this query image's recipe as a support; the
    # coordinator selects exactly one fold view for each inference request.
    views.update(reader=reader, verify_quick=lambda: reader.unchanged(images=False),
                 verify_gallery=gallery_store.verify_completed)
    views['binding'] = {'schema_version': 1, 'phase': 'external_training_paired_pilot',
        'method_config': deepcopy(METHOD_CONFIG), 'training_freeze_sha256': TRAIN_FREEZE_SHA256,
        'gallery_completion_sha256': GALLERY_COMPLETION_SHA256,
        'training_exclusion_binding': data['binding'], 'query_count': 25, 'query_groups': 25,
        'pilot_rows': deepcopy(views['rows']), 'fold_audit_sha256': fingerprint(views['fold_audit']),
        'group_folds_sha256': fingerprint(views['group_folds']),
        'input_sha256': dict(reader.hashes), 'development_opened': False, 'validation_opened': False}
    reader.unchanged()
    return views
