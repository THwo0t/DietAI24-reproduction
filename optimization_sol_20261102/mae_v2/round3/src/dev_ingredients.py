#!/usr/bin/env python3
"""Isolated, development-supervised Nutrition5k ingredient catalog preparation.

Nothing runs on import. Actual extraction requires an explicit --extract flag
and separate authorization. Only the fixed dev manifest/freeze and two original
cafe CSVs are opened; no image, dish label, validation or provider module is used.
The original CSVs mix splits: unmatched physical lines are never decoded or CSV
parsed. They are only streamed and hashed. Only a matching first field authorizes
parsing the remainder. This adapter expects the source's one-line-per-dish form.

Private per-image ingredients must never be passed to inference. Only the
separate held-out-fold-excluded ingredient catalog is eligible for a future,
explicitly registered supervised-domain experiment; this is not the FNDDS method.
"""
from __future__ import annotations

import argparse
from contextlib import ExitStack
import csv
from decimal import Decimal, InvalidOperation
import hashlib
import io
import json
import math
import os
from pathlib import Path
import re
import sys
import tempfile

sys.dont_write_bytecode = True
ROUND = Path(__file__).resolve().parents[1]
V2 = ROUND.parent
REPO = V2.parents[1]
MANIFEST = V2 / 'data/cohorts/dev.jsonl'
FREEZE = V2 / 'data/cohorts/dev_freeze.json'
SOURCES = tuple(REPO / 'Nutrition5k/metadata' / name for name in
                ('dish_metadata_cafe1.csv', 'dish_metadata_cafe2.csv'))
OUTPUT = ROUND / 'data/dev_ingredients.json'
CATALOG_DIR = ROUND / 'data/train_catalogs'
SUMMARY = ROUND / 'data/dev_ingredients_summary.json'
DISH = re.compile(r'dish_[0-9]{10}\Z')
INGREDIENT = re.compile(r'ingr_[0-9]{10}\Z')
NUTRIENTS = ('energy', 'fat', 'carbs', 'protein')
SCOPE = 'development_supervised_ingredients_private_not_inference_input'
CATALOG_SCOPE = 'training_fold_only_domain_catalog_not_original_fndds'
SCHEMA = 1
# Fixed before accessing actual ingredient rows. These allow decimal export
# roundoff, not distinct recipes under one ID. A conflict fails closed.
DENSITY_ABS_TOL = Decimal('0.001')
DENSITY_REL_TOL = Decimal('0.0001')


class IngredientError(RuntimeError):
    """Stable error codes only: no IDs, names or nutrient values in exceptions."""


def fail(code):
    raise IngredientError(code)


def encoded(value):
    return (json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + '\n').encode()


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def number(value):
    if isinstance(value, bool):
        fail('invalid_nonnegative_number')
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        fail('invalid_nonnegative_number')
    if not result.is_finite() or result < 0:
        fail('invalid_nonnegative_number')
    try:
        finite = math.isfinite(float(result))
    except (ValueError, OverflowError):
        finite = False
    if not finite:
        fail('invalid_nonnegative_number')
    return result


def name_value(value):
    if not isinstance(value, str):
        fail('ingredient_name_required')
    name = ' '.join(value.split())
    if not name or len(name) > 512 or any(ord(c) < 32 or ord(c) == 127 for c in value):
        fail('ingredient_name_required')
    return name


def active_development(manifest, *, expected_n=None, expected_groups=None):
    """Derive dish IDs only from fixed development sample IDs, never images."""
    active, sample_ids, group_fold = {}, set(), {}
    for row in manifest:
        if row.get('dataset') != 'nutrition5k':
            continue
        if row.get('split') != 'dev' or any(row.get(k) for k in ('sealed', 'validation', 'is_validation')):
            fail('development_only_manifest_required')
        if any(k in row and str(row[k]).lower() not in {'dev', 'development'} for k in ('partition', 'cohort')):
            fail('development_only_manifest_required')
        sid, group, fold = row.get('sample_id'), row.get('group_id'), row.get('fold')
        if not isinstance(sid, str) or not sid.startswith('nutrition5k-'):
            fail('invalid_development_sample_id')
        dish = sid[len('nutrition5k-'):]
        if not DISH.fullmatch(dish) or sid in sample_ids or dish in active:
            fail('duplicate_or_invalid_development_id')
        if not isinstance(group, str) or not group or type(fold) is not int or fold not in range(5):
            fail('invalid_group_or_fold')
        if group in group_fold and group_fold[group] != fold:
            fail('group_spans_folds')
        group_fold[group] = fold
        sample_ids.add(sid)
        active[dish] = {'sample_id': sid, 'dish_id': dish, 'group_id': group,
                        'fold': fold, 'split': 'dev'}
    if not active:
        fail('empty_development_population')
    if expected_n is not None and len(active) != expected_n:
        fail('development_count_changed')
    if expected_groups is not None and len(group_fold) != expected_groups:
        fail('development_group_count_changed')
    return active


def parse_matched_row(raw, expected_dish):
    """Called only after first-column allowlisting. No raw content in failures."""
    try:
        text = raw.decode('utf-8-sig')
        parsed = list(csv.reader(io.StringIO(text, newline=''), strict=True))
    except (UnicodeError, csv.Error):
        fail('matched_csv_invalid')
    if len(parsed) != 1:
        fail('matched_csv_requires_single_record')
    row = parsed[0]
    if len(row) < 13 or row[0] != expected_dish:
        fail('matched_csv_schema_invalid')
    start, declared = 6, None
    if not row[6].startswith('ingr_'):
        if not re.fullmatch(r'[0-9]+', row[6]):
            fail('ingredient_structure_invalid')
        declared, start = int(row[6]), 7
    if (len(row) - start) % 7:
        fail('ingredient_structure_invalid')
    count = (len(row) - start) // 7
    if count <= 0 or (declared is not None and count != declared):
        fail('ingredient_count_invalid')
    # Published layout: six dish fields then ID, name, mass, calories, fat,
    # carbohydrate, protein per ingredient. Only matched development rows enter
    # numeric conversion. Dish totals are not required or exported by this adapter.
    ingredients = []
    for offset in range(start, len(row), 7):
        identifier, label, grams_raw, *amounts_raw = row[offset:offset + 7]
        if not INGREDIENT.fullmatch(identifier):
            fail('ingredient_id_invalid')
        label = name_value(label)
        grams = number(grams_raw)
        amounts = {k: number(v) for k, v in zip(NUTRIENTS, amounts_raw)}
        if grams == 0 and any(amounts.values()):
            fail('zero_mass_with_nonzero_nutrients')
        density = {k: float(v * 100 / grams) for k, v in amounts.items()} if grams else None
        if density is not None and any(not math.isfinite(v) for v in density.values()):
            fail('invalid_density')
        ingredients.append({'ingredient_id': identifier, 'name': label,
                            'grams': float(grams),
                            'nutrients': {k: float(v) for k, v in amounts.items()},
                            'density_per_100g': density})
    if not any(i['grams'] > 0 for i in ingredients):
        fail('matched_dish_has_no_positive_ingredients')
    return ingredients


def extract_streams(streams, active):
    """Streams contain bytes; unmatched tails are neither decoded nor parsed.

    Reading a raw line and feeding its bytes to SHA256 is unavoidable for streaming
    the mixed file. No names, quantities, counts or nutrient summaries from any
    unmatched row are retained. A malformed/un-decodable unmatched tail is skipped.
    """
    allowed = {dish.encode('ascii'): dish for dish in active}
    records, source_hashes = {}, {}
    for source_name, stream in streams:
        if source_name in source_hashes:
            fail('duplicate_source_name')
        digest = hashlib.sha256()
        for index, raw in enumerate(stream):
            if not isinstance(raw, bytes):
                fail('binary_metadata_stream_required')
            digest.update(raw)
            # Lexical first-column comparison happens before any CSV or UTF-8
            # operation on the remainder. Published IDs are unquoted ASCII.
            first = raw.split(b',', 1)[0]
            if index == 0:
                first = first.removeprefix(b'\xef\xbb\xbf')
            if first not in allowed:
                continue
            dish = allowed[first]
            if dish in records:
                fail('duplicate_matched_development_dish')
            records[dish] = {**active[dish], 'ingredients': parse_matched_row(raw, dish)}
        source_hashes[source_name] = digest.hexdigest()
    if set(records) != set(active):
        fail('development_dishes_missing_from_sources')
    return {'schema_version': SCHEMA, 'scope': SCOPE,
            'source_sha256': source_hashes,
            'records': [records[dish] for dish in sorted(records)]}


def close_density(left, right):
    return abs(left - right) <= DENSITY_ABS_TOL + DENSITY_REL_TOL * max(abs(left), abs(right))


def build_fold_catalog(private, manifest, heldout_fold):
    """Return a pooled training-only catalog without any dish-to-food mapping."""
    if type(heldout_fold) is not int or heldout_fold not in range(5):
        fail('invalid_heldout_fold')
    active = active_development(manifest)
    if private.get('schema_version') != SCHEMA or private.get('scope') != SCOPE:
        fail('private_development_schema_required')
    records = private.get('records')
    if not isinstance(records, list) or len(records) != len(active):
        fail('private_population_mismatch')
    seen = set()
    for row in records:
        dish = row.get('dish_id')
        if dish not in active or dish in seen or any(row.get(k) != v for k, v in active[dish].items()):
            fail('private_manifest_binding_mismatch')
        seen.add(dish)
    excluded_groups = {r['group_id'] for r in active.values() if r['fold'] == heldout_fold}
    if not excluded_groups:
        fail('empty_heldout_fold')
    train = [r for r in records if r['group_id'] not in excluded_groups]
    if not train or any(r['fold'] == heldout_fold for r in train):
        fail('invalid_training_partition')
    catalog, zero_count = {}, 0
    # All ingredient content, including ID/name consistency checks, is inspected
    # AFTER group exclusion. Held-out labels cannot change a training catalog.
    for row in train:
        ingredients = row.get('ingredients')
        if not isinstance(ingredients, list) or not ingredients:
            fail('training_ingredients_required')
        for item in ingredients:
            identifier = item.get('ingredient_id')
            if not isinstance(identifier, str) or not INGREDIENT.fullmatch(identifier):
                fail('ingredient_id_invalid')
            label = name_value(item.get('name'))
            grams = number(item.get('grams'))
            values = item.get('nutrients')
            if not isinstance(values, dict) or set(values) != set(NUTRIENTS):
                fail('ingredient_nutrients_required')
            amounts = {k: number(values[k]) for k in NUTRIENTS}
            if not grams:
                if any(amounts.values()):
                    fail('zero_mass_with_nonzero_nutrients')
                zero_count += 1
                continue
            # Re-derive from reference grams; never trust an edited cached density.
            density = {k: 100 * v / grams for k, v in amounts.items()}
            if identifier not in catalog:
                catalog[identifier] = {'name': label, 'reference_density': density,
                    'mass': Decimal(0), 'nutrients': dict.fromkeys(NUTRIENTS, Decimal(0)),
                    'dishes': set(), 'groups': set()}
            entry = catalog[identifier]
            if entry['name'].casefold() != label.casefold():
                fail('training_ingredient_name_conflict')
            if any(not close_density(entry['reference_density'][k], density[k]) for k in NUTRIENTS):
                fail('training_ingredient_density_conflict')
            entry['mass'] += grams
            for k in NUTRIENTS:
                entry['nutrients'][k] += amounts[k]
            entry['dishes'].add(row['dish_id'])
            entry['groups'].add(row['group_id'])
    if not catalog:
        fail('empty_training_catalog')
    ingredients = []
    for identifier, entry in sorted(catalog.items()):
        density = {k: float(100 * entry['nutrients'][k] / entry['mass']) for k in NUTRIENTS}
        if any(not math.isfinite(v) for v in density.values()):
            fail('invalid_density')
        ingredients.append({'ingredient_id': identifier, 'name': entry['name'],
                            'density_per_100g': density,
                            'supporting_dish_count': len(entry['dishes']),
                            'supporting_group_count': len(entry['groups'])})
    return {'schema_version': SCHEMA, 'scope': CATALOG_SCOPE,
            'heldout_fold': heldout_fold, 'training_dish_count': len(train),
            'training_group_count': len({r['group_id'] for r in train}),
            'excluded_group_count': len(excluded_groups),
            'zero_mass_training_ingredient_count': zero_count,
            'density_consistency': {'absolute_tolerance': str(DENSITY_ABS_TOL),
                'relative_tolerance': str(DENSITY_REL_TOL),
                'method': 'per_training_ID_consistency_then_mass_weighted_pooling'},
            'ingredients': ingredients}


def safe_existing(path):
    if path.is_symlink() or path.resolve() != path:
        fail('symlink_or_noncanonical_path')
    if not path.is_file():
        fail('required_source_missing')
    return path


def private_write(path, raw):
    """Immutable 0600 files under a 0700 directory; never overwrite a result."""
    if path.is_symlink() or path.resolve() != path:
        fail('unsafe_output_path')
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(path.parent, 0o700)
    if path.exists():
        if not path.is_file() or path.read_bytes() != raw:
            fail('existing_private_artifact_conflict')
        if path.stat().st_mode & 0o077:
            fail('unsafe_existing_private_permissions')
        return
    fd, temp = tempfile.mkstemp(prefix='.dev-ingredients-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as handle:
            handle.write(raw)
        os.chmod(temp, 0o600)
        os.link(temp, path)
    finally:
        Path(temp).unlink(missing_ok=True)


def prepare_registered():
    """Operational fixed-path extraction. Caller must separately authorize it."""
    manifest_raw = safe_existing(MANIFEST).read_bytes()
    freeze_raw = safe_existing(FREEZE).read_bytes()
    try:
        manifest = [json.loads(line) for line in manifest_raw.splitlines() if line]
        freeze = json.loads(freeze_raw)
    except (ValueError, UnicodeError):
        fail('development_manifest_or_freeze_invalid')
    if freeze.get('artifacts', {}).get('data/cohorts/dev.jsonl') != sha(manifest_raw):
        fail('development_manifest_freeze_mismatch')
    active = active_development(manifest, expected_n=84, expected_groups=78)
    if {r['fold'] for r in active.values()} != set(range(5)):
        fail('development_fold_population_changed')
    with ExitStack() as stack:
        streams = [(path.name, stack.enter_context(safe_existing(path).open('rb'))) for path in SOURCES]
        private = extract_streams(streams, active)
    private['provenance'] = {'manifest_sha256': sha(manifest_raw), 'dev_freeze_sha256': sha(freeze_raw),
                             'adapter_sha256': sha(Path(__file__).read_bytes()),
                             'original_fndds_method': False, 'inference_registered': False}
    catalogs = {fold: build_fold_catalog(private, manifest, fold) for fold in range(5)}
    # Compute every partition before writing anything. A density/name conflict
    # stops preparation without a partial directory being used by an experiment.
    payloads = {OUTPUT: encoded(private), **{CATALOG_DIR / f'fold_{f}.json': encoded(c) for f, c in catalogs.items()}}
    if MANIFEST.read_bytes() != manifest_raw or FREEZE.read_bytes() != freeze_raw:
        fail('development_inputs_changed_during_preparation')
    summary = {'schema_version': SCHEMA, 'status': 'prepared_not_registered_for_inference',
               'scope': 'development_supervised_domain_catalog_not_original_fndds',
               'development_dish_count': len(active), 'development_group_count': 78,
               'matched_ingredient_occurrence_count': sum(len(r['ingredients']) for r in private['records']),
               'source_sha256': private['source_sha256'],
               'manifest_sha256': sha(manifest_raw), 'dev_freeze_sha256': sha(freeze_raw),
               'adapter_sha256': private['provenance']['adapter_sha256'],
               'private_artifact_sha256': sha(payloads[OUTPUT]),
               'folds': {str(f): {k: c[k] for k in ('training_dish_count', 'training_group_count',
                         'excluded_group_count', 'zero_mass_training_ingredient_count')} |
                         {'catalog_ingredient_count': len(c['ingredients']),
                          'catalog_sha256': sha(payloads[CATALOG_DIR / f'fold_{f}.json'])}
                         for f, c in catalogs.items()},
               'api_calls': 0, 'images_opened': 0, 'validation_files_opened': False,
               'unmatched_rows_numerically_parsed': 0,
               'unmatched_rows_csv_parsed': 0,
               'shared_metadata_byte_streaming': True}
    payloads[SUMMARY] = encoded(summary)
    for path, raw in payloads.items():
        if path.exists() and (path.is_symlink() or not path.is_file() or path.read_bytes() != raw):
            fail('existing_private_artifact_conflict')
    for path, raw in payloads.items():
        private_write(path, raw)
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--extract', action='store_true', help='Run only after explicit authorization; creates private dev-only artifacts')
    args = parser.parse_args(argv)
    if not args.extract:
        print(json.dumps({'status': 'not_extracted', 'explicit_extract_flag_required': True,
                          'api_calls': 0, 'source_data_opened': False}))
        return 0
    try:
        summary = prepare_registered()
    except IngredientError as error:
        print(json.dumps({'status': 'blocked', 'error_code': str(error)}))
        return 2
    except (OSError, ValueError, TypeError, KeyError):
        # Never print traceback, source path, raw record, IDs, names or values.
        print(json.dumps({'status': 'blocked', 'error_code': 'preparation_io_or_schema_failure'}))
        return 2
    print(json.dumps(summary, sort_keys=True, allow_nan=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
