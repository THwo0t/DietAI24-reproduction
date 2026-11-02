"""New training-frame proposal from raw RGB records, with the frozen exclusions.

No download. No existing cohort change. Parse numeric values only for candidates
outside the complete blocked screening closure. All-zero nutrients remain an
exclusion; an individual zero nutrient is valid. No names/labels are persisted.
"""
from collections import Counter, defaultdict
import csv
from decimal import Decimal, InvalidOperation
import json
from pathlib import Path
import re
import sys

import audit_pool as a

INDEX_SHA256 = 'e0a57d390fced7b3d811900e3cfd634bfaced7b4f7c1b897c59b495aac4fc5f2'
QUALIFICATION = {
    'frame': 'All cached official overhead RGB objects that have frozen raw metadata; no requirement to occur in the archived deduplicated available-frame CSV.',
    'weight': 'finite and strictly positive',
    'nutrients': 'energy/fat/carbs/protein each finite and nonnegative; at least one strictly positive; individual zero values are valid',
    'positive_ingredient_mass': 'at least one finite positive ingredient mass, preserving the original positive-food evidence requirement',
    'exclusions': 'Unchanged complete frozen-component plus recipe and exact-local-image screening closure, including original dev100, current dev84, historical exposure, original and current val200, retired val and ambiguous components.',
    'selection': 'One image per every eligible screening group; fixed seed SHA256 ranking; no truth/error dependent ranking.',
}


def install_read_guard():
    """Accidental-access guard, not an OS filesystem sandbox claim."""
    def guard(event, args):
        if event != 'open' or not args or isinstance(args[0], int):
            return
        value = args[0]
        if isinstance(value, bytes):
            value = value.decode(errors='replace')
        if not isinstance(value, str):
            return
        path = Path(value).resolve()
        name = path.name.lower()
        forbidden = (name == '.env' or name.startswith('.env.') or name.startswith('labels.')
                     or name.endswith('_labels.json') or name.endswith('_labels.csv')
                     or any(part in ('.aws', '.ssh') for part in path.parts))
        a.require(not forbidden, 'forbidden_label_or_credential_access')
    sys.addaudithook(guard)


def qualify_rows(paths, allowed):
    eligible, reasons, observed = set(), Counter(), set()
    for path in paths:
        with Path(path).open(newline='', encoding='utf-8-sig') as stream:
            for row in csv.reader(stream):
                dish = row[0]
                if dish not in allowed:
                    continue
                a.require(dish not in observed, 'duplicate_candidate_metadata')
                observed.add(dish)
                try:
                    # Published raw columns: ID, calories, mass, fat, carbs, protein.
                    values = [Decimal(value) for value in row[1:6]]
                except (InvalidOperation, ValueError):
                    reasons['invalid_numeric_target'] += 1
                    continue
                if len(values) != 5 or not all(value.is_finite() and value >= 0 for value in values):
                    reasons['invalid_numeric_target'] += 1
                    continue
                energy, weight, fat, carbs, protein = values
                if weight <= 0:
                    reasons['nonpositive_weight'] += 1
                    continue
                if all(value == 0 for value in (energy, fat, carbs, protein)):
                    reasons['all_four_nutrients_zero'] += 1
                    continue
                start = 6 if len(row) == 6 or row[6].startswith('ingr_') else 7
                a.require((len(row) - start) % 7 == 0, 'invalid_candidate_ingredient_structure')
                # No ingredient names are retained. This preserves the old
                # positive-mass qualification without any group-specific fit.
                masses = [a.decimal_value(row[index + 2]) for index in range(start, len(row), 7)]
                if not any(mass > 0 for mass in masses):
                    reasons['no_positive_ingredient_mass'] += 1
                    continue
                eligible.add(dish)
    a.require(observed == allowed, 'candidate_missing_raw_metadata')
    return eligible, dict(reasons)


def run():
    index_path = a.HERE / 'private_audit_index.json'
    a.require(a.file_hash(index_path) == INDEX_SHA256, 'screening_index_changed')
    index = a.read_json(index_path)
    guards = {index_path: INDEX_SHA256}
    for name, expected in index['source_sha256'].items():
        path = Path(name)
        if not path.is_absolute():
            path = a.REPO / path
        a.require(a.file_hash(path) == expected, 'frozen_audit_source_changed')
        guards[path.resolve()] = expected
    for relative, expected in a.FROZEN.items():
        path = a.V2 / relative
        a.require(a.file_hash(path) == expected, 'original_freeze_changed')
        guards[path.resolve()] = expected
    inventory_path = a.REPO / 'Nutrition5k/metadata/realsense_overhead_objects.json'
    sizes = {}
    for item in a.read_json(inventory_path):
        match = re.fullmatch(r'nutrition5k_dataset/imagery/realsense_overhead/(dish_[0-9]{10})/rgb\.png', item['name'])
        if match:
            dish = match[1]
            a.require(dish not in sizes and str(item['size']).isdigit(), 'invalid_rgb_inventory')
            sizes[dish] = int(item['size'])
            a.require(0 < sizes[dish] <= a.MAX_IMAGE_BYTES, 'invalid_rgb_size')
    blocked = set(index['blocked_screening_components'])
    screening = index['screening_components']
    allowed = {dish for dish, group in screening.items() if group not in blocked} & sizes.keys()
    raw_paths = [a.REPO / 'Nutrition5k/metadata' / name for name in
                 ('dish_metadata_cafe1.csv', 'dish_metadata_cafe2.csv')]
    eligible, exclusions = qualify_rows(raw_paths, allowed)
    groups = {screening[dish] for dish in eligible}
    selected = a.fixed_selection(eligible, screening, target=len(groups))
    a.require(len(selected) == len(groups) > 0, 'no_eligible_training_group')
    a.require(len({index['recipe_sha256'][dish] for dish in selected}) == len(selected),
              'selected_recipe_collision')
    a.require(not {screening[dish] for dish in selected} & blocked, 'selected_excluded_component')
    local = {item['dish_id'] for item in index['known_image_fingerprints']}
    a.require(not local & eligible, 'unexpected_unexposed_local_candidate')
    available_path = a.REPO / 'Nutrition5k/metadata/dish_metadata_available.csv'
    with available_path.open(newline='', encoding='utf-8-sig') as stream:
        # IDs only: no numerical fields from this mixed protected source.
        archived_frame = {row['dish_id'] for row in csv.DictReader(stream)}
    entries = [{'dish_id': dish,
        'original_component_id': index['original_components'][dish],
        'screening_component_id': screening[dish],
        'recipe_sha256': index['recipe_sha256'][dish],
        'source_url': f'{a.BASE_URL}/{dish}/rgb.png',
        'planned_destination': 'round4/data/incoming/' + a.digest((a.SEED + '|incoming|' + dish).encode()) + '/rgb.png',
        'cached_object_bytes': sizes[dish], 'max_image_bytes': a.MAX_IMAGE_BYTES,
        'in_archived_available_frame': dish in archived_frame,
        'pixel_verification': 'pending_authorized_download'} for dish in selected]
    eligibility_index = {'schema_version': 1, 'private_audit_index_sha256': INDEX_SHA256,
        'qualification': QUALIFICATION, 'eligible_dish_ids': sorted(eligible),
        'eligible_group_sizes': dict(sorted(Counter(screening[dish] for dish in eligible).items()))}
    eligibility_bytes = a.canonical(eligibility_index)
    proposal = {'schema_version': 1, 'seed': a.SEED,
        'status': 'awaiting_new_download_authorization',
        'original_requested_images_and_groups': a.TARGET,
        'actual_images_and_screening_groups': len(selected),
        'qualification': QUALIFICATION,
        'private_audit_index_sha256': INDEX_SHA256,
        'private_eligibility_index_sha256': a.digest(eligibility_bytes),
        'original_frozen_hashes': a.FROZEN,
        'cached_object_inventory_sha256': a.file_hash(inventory_path),
        'entries': entries,
        'release_policy': 'Separately authorize this exact URL set and a total transfer budget before download. Then blind bytes/RGB dedup against all frozen excluded images and all candidate images. Quarantine affected complete screening components before training release. No automatic replacement beyond this manifest.',
        'independence_limit': 'Engineering component separation, not proof of distinct physical plates; undownloaded image pixels unverified.'}
    proposal_bytes = a.canonical(proposal)
    summary = {'schema_version': 1, 'status': proposal['status'], 'seed': a.SEED,
        'initial_600_group_target_feasible': False,
        'raw_rgb_unblocked_images_before_qualification': len(allowed),
        'raw_rgb_unblocked_groups_before_qualification': len({screening[dish] for dish in allowed}),
        'qualification': QUALIFICATION,
        'numeric_qualification_exclusions': exclusions,
        'eligible_images': len(eligible), 'eligible_screening_groups': len(groups),
        'eligible_images_outside_archived_available_frame': len(eligible - archived_frame),
        'selected_images': len(selected), 'selected_groups': len(groups),
        'selected_images_outside_archived_available_frame': len(set(selected) - archived_frame),
        'selected_already_local': 0, 'new_download_file_count': len(selected),
        'cached_download_byte_estimate': sum(sizes[dish] for dish in selected),
        'maximum_successful_payload_bytes': len(selected) * a.MAX_IMAGE_BYTES,
        'maximum_per_image_bytes': a.MAX_IMAGE_BYTES,
        'byte_estimate_basis': 'Sum of cached official object sizes, not a current network check or remote checksum. The payload ceiling is not authorization; retries consume a separately approved transfer budget.',
        'new_download_authorization_received': False, 'downloaded_images': 0,
        'source_freezes_unchanged': True, 'existing_cohorts_modified': False,
        'validation_label_files_opened': 0, 'validation_numeric_fields_interpreted': 0,
        'postdownload_blind_dedup_and_quarantine_required': True,
        'automatic_replacement_permitted': False,
        'physical_plate_independence_proved': False,
        'proposal_relative_path': 'round4/proposal/private_train_pool_proposal.json',
        'proposal_sha256': a.digest(proposal_bytes),
        'private_eligibility_index_sha256': a.digest(eligibility_bytes),
        'private_audit_index_sha256': INDEX_SHA256,
        'original_frozen_hashes': a.FROZEN,
        'auditor_source_sha256': a.file_hash(Path(__file__)),
        'blind_base_auditor_sha256': a.file_hash(a.HERE / 'audit_pool.py'),
        'frame_difference': 'The original available CSV is a restricted/deduplicated image frame. This new training proposal permits other raw official RGB records outside that CSV while preserving all component/recipe exclusions and positive-food/all-zero-nutrient safeguards. Original dev84/val200 eligibility and manifests remain immutable.',
    }
    for path, expected in guards.items():
        a.require(a.file_hash(path) == expected, 'source_changed_during_proposal')
    a.immutable_write(a.HERE / 'private_eligibility_index.json', eligibility_bytes, private=True)
    a.immutable_write(a.HERE / 'private_train_pool_proposal.json', proposal_bytes, private=True)
    a.immutable_write(a.HERE / 'raw_rgb_summary.json', a.canonical(summary))
    return summary


def main():
    install_read_guard()
    try:
        result = run()
    except a.AuditError as error:
        print(json.dumps({'status': 'blocked', 'error_code': str(error)}, sort_keys=True))
        return 2
    except Exception as error:
        print(json.dumps({'status': 'blocked', 'error_code': 'unexpected_' + type(error).__name__}, sort_keys=True))
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == '__main__':
    sys.exit(main())
