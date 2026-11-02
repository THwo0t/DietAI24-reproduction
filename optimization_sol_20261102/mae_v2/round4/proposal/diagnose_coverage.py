"""Post-selection aggregate feasibility, never selection or a model result.

The exact download manifest is already fixed. Only selected training candidate
ingredient IDs/positive grams and the existing dev-only ingredient file are read.
No image, validation target, current prediction, or API is used here.
"""
from collections import defaultdict
import csv
from decimal import Decimal
import json
from pathlib import Path
import sys

import audit_pool as a
import propose_raw_rgb as p

PROPOSAL_SHA256 = 'eddf9a644114f5b4aecc4d906dbdec6ee0eaecd80b97e23743d9edf663e03eb0'
KEYS = ('weight', 'energy', 'fat', 'carbs', 'protein')


def coverage(records, catalog_for_row):
    total = {key: Decimal(0) for key in KEYS}
    covered = {key: Decimal(0) for key in KEYS}
    occurrences = matched = full = 0
    reference_ids, matched_ids = set(), set()
    for row in records:
        catalog = catalog_for_row(row)
        all_matched = True
        for item in row['ingredients']:
            grams = a.decimal_value(str(item['grams']))
            if grams <= 0:
                continue
            ingredient = item['ingredient_id']
            reference_ids.add(ingredient)
            occurrences += 1
            hit = ingredient in catalog
            matched += int(hit)
            all_matched &= hit
            if hit:
                matched_ids.add(ingredient)
            values = {'weight': grams, **{key: a.decimal_value(str(item['nutrients'][key]))
                                         for key in KEYS[1:]}}
            for key in KEYS:
                total[key] += values[key]
                if hit:
                    covered[key] += values[key]
        full += int(all_matched)
    return {'dishes': len(records), 'positive_ingredient_occurrences': occurrences,
        'covered_positive_ingredient_occurrences': matched,
        'positive_ingredient_occurrence_coverage': matched / occurrences if occurrences else None,
        'distinct_positive_reference_ingredient_ids': len(reference_ids),
        'covered_distinct_positive_reference_ingredient_ids': len(matched_ids),
        'all_positive_ingredients_covered_dishes': full,
        'dishes_with_missing_positive_ingredient': len(records) - full,
        'quantity_coverage': {key: float(covered[key] / total[key]) if total[key] else None for key in KEYS},
        'quantity_totals': {key: float(value) for key, value in total.items()},
        'covered_quantity_totals': {key: float(value) for key, value in covered.items()}}


def selected_catalog(paths, selected):
    ids, seen, occurrences = set(), set(), 0
    for path in paths:
        with Path(path).open(newline='', encoding='utf-8-sig') as stream:
            for row in csv.reader(stream):
                if row[0] not in selected:
                    continue
                a.require(row[0] not in seen, 'duplicate_selected_metadata')
                seen.add(row[0])
                start = 6 if len(row) == 6 or row[6].startswith('ingr_') else 7
                for offset in range(start, len(row), 7):
                    grams = a.decimal_value(row[offset + 2])
                    if grams > 0:
                        a.require(a.INGREDIENT.fullmatch(row[offset]), 'invalid_selected_ingredient_id')
                        ids.add(row[offset])
                        occurrences += 1
    a.require(seen == selected, 'selected_candidate_missing_metadata')
    return ids, occurrences


def run():
    proposal_path = a.HERE / 'private_train_pool_proposal.json'
    a.require(a.file_hash(proposal_path) == PROPOSAL_SHA256, 'fixed_proposal_changed')
    proposal = a.read_json(proposal_path)
    index_path = a.HERE / 'private_audit_index.json'
    a.require(a.file_hash(index_path) == p.INDEX_SHA256, 'fixed_screening_index_changed')
    index = a.read_json(index_path)
    selected = {entry['dish_id'] for entry in proposal['entries']}
    a.require(len(selected) == 230, 'fixed_selected_count_changed')
    a.require(not {index['screening_components'][dish] for dish in selected} &
              set(index['blocked_screening_components']), 'selected_blocked_component')
    raw_paths = [a.REPO / 'Nutrition5k/metadata' / name for name in
                 ('dish_metadata_cafe1.csv', 'dish_metadata_cafe2.csv')]
    guards = {proposal_path: PROPOSAL_SHA256, index_path: p.INDEX_SHA256}
    for path in raw_paths:
        expected = index['source_sha256'][str(path.relative_to(a.REPO))]
        a.require(a.file_hash(path) == expected, 'raw_metadata_changed')
        guards[path] = expected
    new_catalog, train_occurrences = selected_catalog(raw_paths, selected)
    dev_path = a.V2 / 'round3/data/dev_ingredients.json'
    baseline_path = a.V2 / 'analysis/next_round_catalog/aggregate.json'
    baseline = a.read_json(baseline_path)
    dev_sha = a.file_hash(dev_path)
    a.require(dev_sha == baseline['source_sha256']['round3/data/dev_ingredients.json'],
              'dev_ingredient_source_changed')
    guards[dev_path], guards[baseline_path] = dev_sha, a.file_hash(baseline_path)
    records = a.read_json(dev_path)['records']
    a.require(len(records) == 84 and len({row['group_id'] for row in records}) == 78,
              'development_population_changed')
    new_only = coverage(records, lambda row: new_catalog)
    # Separate, explicitly exploratory mixed-gallery design: for each query,
    # exclude its entire old-development fold AND group from the added gallery.
    def mixed_catalog(query):
        result = set(new_catalog)
        for other in records:
            if other['fold'] == query['fold'] or other['group_id'] == query['group_id']:
                continue
            result.update(item['ingredient_id'] for item in other['ingredients']
                          if a.decimal_value(str(item['grams'])) > 0)
        return result
    mixed = coverage(records, mixed_catalog)
    byfold = {str(fold): coverage([row for row in records if row['fold'] == fold], lambda row: new_catalog)
              for fold in range(5)}
    result = {'schema_version': 1, 'scope': 'Post-selection development-only feasibility; not a prediction or an acceptance result.',
        'fixed_training_candidate_images': len(selected),
        'fixed_training_candidate_screening_groups': len({index['screening_components'][dish] for dish in selected}),
        'training_positive_ingredient_occurrences': train_occurrences,
        'training_distinct_positive_ingredient_ids': len(new_catalog),
        'new_training_only': new_only,
        'new_training_only_by_dev_fold': byfold,
        'existing_H_outer_fold_training_catalog_reference': {
            'positive_mass_occurrence_coverage': baseline['overall']['positive_mass_occurrence_coverage'],
            'quantity_coverage': baseline['overall']['quantity_coverage'],
            'all_positive_ingredients_covered_dishes': baseline['overall']['all_positive_ingredients_covered_dishes']},
        'exploratory_new_training_plus_query_other_dev_folds': mixed,
        'limitations': [
            'Reference IDs/masses are used only for this post-selection diagnostic; no change to the fixed proposal or any query prediction.',
            'An ingredient being available in a catalog does not mean image inference identifies it or estimates its grams correctly.',
            'The 230 candidate images are not yet downloaded or pixel-deduplicated; future quarantine may reduce catalog coverage.',
            'Mixed-gallery results describe a possible separately registered OOF gallery. Every query fold/group must be excluded from its training labels, catalog/density, examples and any fitted prior; ordinary second-stage calibration on these OOF outputs can still leak outer-fold labels.'],
        'verification': {'api_calls': 0, 'images_read': 0, 'validation_label_files_opened': 0,
            'validation_numeric_fields_interpreted': 0, 'fixed_download_manifest_unchanged': True,
            'output_has_no_row_ids_or_ingredient_names_or_ingredient_ids': True,
            'independent_of_candidate_selection': True},
        'source_sha256': {
            'private_train_pool_proposal.json': PROPOSAL_SHA256,
            'private_audit_index.json': p.INDEX_SHA256,
            'round3/data/dev_ingredients.json': dev_sha,
            'analysis/next_round_catalog/aggregate.json': guards[baseline_path],
            'auditor_source': a.file_hash(Path(__file__))}}
    for path, expected in guards.items():
        a.require(a.file_hash(path) == expected, 'source_changed_during_coverage_diagnostic')
    a.immutable_write(a.HERE / 'coverage_diagnostic.json', a.canonical(result))
    return result


def main():
    p.install_read_guard()
    try:
        result = run()
    except a.AuditError as error:
        print(json.dumps({'status': 'blocked', 'error_code': str(error)}, sort_keys=True))
        return 2
    except Exception as error:
        print(json.dumps({'status': 'blocked', 'error_code': 'unexpected_' + type(error).__name__}, sort_keys=True))
        return 2
    # Aggregate summary only; detailed per-fold aggregates stay in the JSON.
    print(json.dumps({key: result[key] for key in (
        'fixed_training_candidate_images', 'training_distinct_positive_ingredient_ids',
        'new_training_only', 'existing_H_outer_fold_training_catalog_reference',
        'exploratory_new_training_plus_query_other_dev_folds', 'verification', 'source_sha256')}, sort_keys=True))
    return 0


if __name__ == '__main__':
    sys.exit(main())
