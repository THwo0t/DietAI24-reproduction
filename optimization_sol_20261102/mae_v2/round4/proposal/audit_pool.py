"""Offline, blind proposal screening; never prepare or modify existing cohorts.

Raw CSV names are consumed only to reproduce the archived recipe fingerprint.
Validation numeric fields and label files are never interpreted or opened.
Existing RGB files are decoded only into exact hashes. No images, names, target
values, or row identifiers are emitted to stdout or the public summary.
"""
from __future__ import annotations

from collections import Counter, defaultdict
import csv
from decimal import Decimal, InvalidOperation
import hashlib
import io
import json
import os
from pathlib import Path
import re
import sys

from PIL import Image

HERE = Path(__file__).resolve().parent
V2 = HERE.parents[1]
REPO = V2.parents[1]
SEED = 'dietai24-mae-v2-round4-train600-20261103'
TARGET = 600
MAX_IMAGE_BYTES = 5_000_000
BASE_URL = 'https://storage.googleapis.com/nutrition5k_dataset/nutrition5k_dataset/imagery/realsense_overhead'
DISH = re.compile(r'dish_[0-9]{10}\Z')
INGREDIENT = re.compile(r'ingr_[0-9]{10}\Z')
HEX = re.compile(r'[0-9a-f]{64}\Z')
# Captured before any proposal work. These existing artifacts are never rewritten.
FROZEN = {
    'data/freeze/source_snapshot.json': '2b933e6434b78116646f47adfe8544ed9fc5fbb174b9f85422cccdeddc4b7c05',
    'data/freeze/final_source_snapshot.json': 'bea5ad2910a6637c0a80671145a02ce803fdeb936f1b7da1d071218bb03e1e4d',
    'data/freeze/validation_freeze.json': 'ff40c572ecc457e331d1e720ba17c7960cffeaf312add66ee94f9ba64bd4a82b',
    'data/cohorts/dev_freeze.json': 'a5f5edbb6082e4c70a1bf6eccfcd2e11be1b3b1f5de5ac12e3bcc3a38f6c2681',
}


class AuditError(RuntimeError):
    """Only a fixed, non-sensitive error code may reach the terminal."""


def require(condition, code):
    if not condition:
        raise AuditError(code)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def canonical(value):
    return (json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + '\n').encode()


def file_hash(path):
    value = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1 << 20), b''):
            value.update(block)
    return value.hexdigest()


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, 'duplicate_json_key')
        result[key] = value
    return result


def read_json(path):
    return json.loads(Path(path).read_text(), object_pairs_hook=unique_object)


def safe_child(base, relative):
    relative = Path(relative)
    require(not relative.is_absolute() and '..' not in relative.parts,
            'unsafe_relative_path')
    path = Path(base) / relative
    require(not path.is_symlink() and path.resolve().is_relative_to(Path(base).resolve()),
            'unsafe_relative_path')
    return path


def recipe_fingerprint(row):
    """Inspect structural IDs/names only. No float/Decimal access to labels."""
    require(len(row) >= 6 and DISH.fullmatch(row[0]), 'invalid_metadata_structure')
    start, declared = 6, None
    if len(row) > 6 and not row[6].startswith('ingr_'):
        require(row[6].isdigit(), 'invalid_ingredient_count')
        declared, start = int(row[6]), 7
    require((len(row) - start) % 7 == 0, 'invalid_ingredient_structure')
    offsets = range(start, len(row), 7)
    require(declared is None or declared == len(offsets), 'ingredient_count_mismatch')
    require(all(INGREDIENT.fullmatch(row[index]) for index in offsets),
            'invalid_ingredient_id')
    # Preserve precisely the original fingerprint, including repeated/zero-mass
    # ingredient names. The temporary list is never persisted or returned.
    return digest(', '.join(sorted(row[index + 1] for index in offsets)).encode())


def recipe_map(paths):
    recipes = {}
    for path in paths:
        with Path(path).open(newline='', encoding='utf-8-sig') as stream:
            for row in csv.reader(stream):
                fingerprint = recipe_fingerprint(row)
                require(row[0] not in recipes, 'duplicate_raw_dish')
                recipes[row[0]] = fingerprint
    return recipes


class Union:
    def __init__(self, nodes):
        self.parent = {node: node for node in nodes}

    def find(self, node):
        require(node in self.parent, 'unknown_graph_node')
        while self.parent[node] != node:
            self.parent[node] = self.parent[self.parent[node]]
            node = self.parent[node]
        return node

    def join(self, a, b):
        a, b = self.find(a), self.find(b)
        if a != b:
            self.parent[max(a, b)] = min(a, b)


def proposal_closure(mapping, recipes, fingerprints):
    """Extra screening only; never mutate original component IDs or folds."""
    require(set(mapping) == set(recipes), 'recipe_graph_universe_mismatch')
    graph = Union(set(mapping.values()))
    seen_recipe, seen_bytes, seen_rgb = {}, {}, {}
    for dish in sorted(mapping):
        key = recipes[dish]
        if key in seen_recipe:
            graph.join(mapping[dish], mapping[seen_recipe[key]])
        seen_recipe[key] = dish
    for item in fingerprints:
        require(item['dish_id'] in mapping, 'image_outside_frozen_graph')
        for field, seen in (('bytes_sha256', seen_bytes), ('rgb_sha256', seen_rgb)):
            key = item[field]
            if key in seen:
                graph.join(mapping[item['dish_id']], mapping[seen[key]])
            seen[key] = item['dish_id']
    members = defaultdict(list)
    for component in sorted(set(mapping.values())):
        members[graph.find(component)].append(component)
    names = {root: 'round4-screening-' + digest('\n'.join(groups).encode())
             for root, groups in members.items()}
    screening = {dish: names[graph.find(component)] for dish, component in mapping.items()}
    return screening, {names[root]: groups for root, groups in members.items()}


def candidate_eligibility(path, allowed):
    """Parse numeric values only after the complete exclusion closure."""
    accepted, frame, zero_nutrition = set(), set(), 0
    with Path(path).open(newline='', encoding='utf-8-sig') as stream:
        for row in csv.DictReader(stream):
            dish = row['dish_id']
            require(DISH.fullmatch(dish) and dish not in frame, 'invalid_available_frame')
            frame.add(dish)
            if dish not in allowed:
                continue  # Validation/historical fields are never converted.
            fields = ('total_mass', 'total_calories', 'total_fat', 'total_carbs', 'total_protein')
            values = [decimal_value(row[key]) for key in fields]
            if values[0] > 0 and all(value == 0 for value in values[1:]):
                zero_nutrition += 1
                continue
            accepted.add(dish)
    return accepted, frame, zero_nutrition


def decimal_value(value):
    try:
        result = Decimal(value)
    except (InvalidOperation, ValueError, TypeError):
        raise AuditError('invalid_candidate_numeric_field') from None
    require(result.is_finite() and result >= 0, 'invalid_candidate_numeric_field')
    return result


def positive_mass_ids(paths, allowed):
    positive = set()
    for path in paths:
        with Path(path).open(newline='', encoding='utf-8-sig') as stream:
            for row in csv.reader(stream):
                if row[0] not in allowed:
                    continue
                start = 6 if len(row) == 6 or row[6].startswith('ingr_') else 7
                if any(decimal_value(row[index + 2]) > 0 for index in range(start, len(row), 7)):
                    positive.add(row[0])
    return positive


def rgb_fingerprint(path, expected):
    payload = Path(path).read_bytes()
    require(digest(payload) == expected, 'frozen_image_hash_mismatch')
    with Image.open(io.BytesIO(payload)) as image:
        image.load()
        require(image.format in ('PNG', 'JPEG'), 'unsupported_image_format')
        rgb = image.convert('RGB')
        rgb_hash = digest(str(rgb.size).encode() + b'\0' + rgb.tobytes())
    return {'bytes_sha256': expected, 'rgb_sha256': rgb_hash, 'bytes': len(payload)}


def path_dish(path):
    for value in (path.stem, *reversed(path.parts[:-1])):
        match = re.match(r'(dish_[0-9]{10})(?:\Z|[_-])', value)
        if match:
            return match[1]
    return None


def manifest_rows(path):
    rows = [json.loads(line, object_pairs_hook=unique_object)
            for line in Path(path).read_text().splitlines() if line.strip()]
    keys = {'dataset', 'fold', 'group_id', 'image_path', 'image_sha256', 'sample_id', 'split'}
    require(all(set(row) == keys for row in rows), 'unexpected_manifest_fields')
    return [row for row in rows if row['dataset'] == 'nutrition5k']


def row_dish(row):
    dish = row['sample_id'].removeprefix('nutrition5k-')
    require(DISH.fullmatch(dish), 'invalid_manifest_identifier')
    return dish


def image_inventory(snapshot, sources, row_sets, incoming, v2, v1):
    inventory = {}

    def add(path, dish, expected):
        path = Path(path)
        require(not path.is_symlink() and path.is_file(), 'missing_or_linked_image')
        path = path.resolve()
        require(DISH.fullmatch(dish) and HEX.fullmatch(expected), 'invalid_image_record')
        entry = (dish, expected)
        require(path not in inventory or inventory[path] == entry, 'conflicting_image_record')
        inventory[path] = entry

    for name, expected in sources.items():
        path = Path(name)
        dish = path_dish(path)
        if dish and path.suffix.lower() in ('.png', '.jpg', '.jpeg'):
            add(path, dish, expected)
    for base, rows in row_sets:
        for row in rows:
            add(safe_child(base, row['image_path']), row_dish(row), row['image_sha256'])
    for item in incoming:
        path = safe_child(v2, item['destination'])
        require(str(path.resolve()) in sources, 'incoming_image_not_source_bound')
        add(path, item['dish_id'], sources[str(path.resolve())])
    for item in snapshot['legacy_image_inventory']:
        base = Path(item['root'])
        require(base.exists() == item['exists'], 'legacy_inventory_changed')
        count = 0
        if base.exists():
            for path in sorted(base.rglob('*')):
                if path.suffix.lower() not in ('.png', '.jpg', '.jpeg') or not path.is_file():
                    continue
                dish = path_dish(path)
                if dish:
                    count += 1
                    require(path.resolve() in inventory, 'legacy_inventory_unbound_image')
        require(count == item['images'], 'legacy_inventory_changed')
    return inventory


def fixed_selection(eligible, screening, target=TARGET):
    by_group = defaultdict(list)
    rank = lambda kind, value: digest((SEED + '|' + kind + '|' + value).encode())
    for dish in eligible:
        by_group[screening[dish]].append(dish)
    if len(by_group) < target:
        return []
    groups = sorted(by_group, key=lambda group: (rank('group', group), group))[:target]
    return [min(by_group[group], key=lambda dish: (rank('image', dish), dish)) for group in groups]


def immutable_write(path, payload, private=False):
    path = Path(path)
    require(path.parent.resolve() == HERE.resolve(), 'output_outside_proposal')
    require(not path.is_symlink(), 'unsafe_output_symlink')
    if path.exists():
        require(path.read_bytes() == payload, 'existing_proposal_output_changed')
        require(not private or not path.stat().st_mode & 0o077, 'private_permissions_changed')
        return
    with path.open('xb') as stream:
        os.chmod(path, 0o600 if private else 0o644)
        stream.write(payload)


def run():
    v2, repo, v1 = V2.resolve(), REPO.resolve(), V2.parent.resolve()
    guards = {}

    def bind(path, expected=None):
        path = Path(path).resolve()
        require(path.is_file() and not Path(path).is_symlink(), 'required_source_missing')
        value = file_hash(path)
        require(expected is None or value == expected, 'source_hash_mismatch')
        require(path not in guards or guards[path] == value, 'source_changed_during_audit')
        guards[path] = value
        return path

    for relative, expected in FROZEN.items():
        bind(v2 / relative, expected)
    original = read_json(v2 / 'data/freeze/source_snapshot.json')
    snapshot = read_json(v2 / 'data/freeze/final_source_snapshot.json')
    val_seal = read_json(v2 / 'data/freeze/validation_freeze.json')
    dev_seal = read_json(v2 / 'data/cohorts/dev_freeze.json')
    sources = snapshot['source_sha256']
    require(original['component_members'] == snapshot['component_members'], 'frozen_graph_changed')
    require(all(sources.get(path) == value for path, value in original['source_sha256'].items()),
            'original_source_snapshot_changed')
    bind(v2 / 'src/cohorts_v2.py', snapshot['preparer_sha256'])
    rules_path = bind(v2 / 'data/freeze/rules.json', val_seal['rules_sha256'])
    require(dev_seal['rules_sha256'] == val_seal['rules_sha256'], 'cohort_rule_seals_differ')
    proposal_path = bind(v2 / 'data/freeze/cohort_proposal.json', val_seal['proposal_sha256'])
    previous = read_json(proposal_path)
    require(canonical(previous['rules']) == rules_path.read_bytes(), 'proposal_rules_differ')
    mapping = {}
    for group, dishes in snapshot['component_members'].items():
        require(group == 'nutrition5k-v2-' + digest('\n'.join(sorted(dishes)).encode()),
                'invalid_frozen_component_digest')
        for dish in dishes:
            require(DISH.fullmatch(dish) and dish not in mapping, 'invalid_frozen_partition')
            mapping[dish] = group
    raw_paths = [repo / 'Nutrition5k/metadata' / name for name in
                 ('dish_metadata_cafe1.csv', 'dish_metadata_cafe2.csv')]
    available_path = repo / 'Nutrition5k/metadata/dish_metadata_available.csv'
    registry_path = v1 / 'data/freeze/exclusion_registry.json'
    v1_manifest = v1 / 'data/manifest.csv'
    v1_row_paths = [v1 / f'data/cohorts/{split}.jsonl' for split in ('dev', 'validation')]
    for path in [*raw_paths, available_path, registry_path, v1_manifest, *v1_row_paths]:
        require(str(path) in sources, 'missing_frozen_metadata_hash')
        bind(path, sources[str(path)])
    registry = read_json(registry_path)
    dev_path = bind(v2 / 'data/cohorts/dev.jsonl', dev_seal['artifacts']['data/cohorts/dev.jsonl'])
    val_relative = 'data/cohorts/sealed/validation.jsonl'
    val_path = bind(v2 / val_relative, val_seal['artifacts'][val_relative])
    old_dev, old_val = [manifest_rows(path) for path in v1_row_paths]
    dev, val = manifest_rows(dev_path), manifest_rows(val_path)
    require((len(old_dev), len(old_val), len(dev), len(val)) == (100, 200, 84, 200),
            'cohort_population_changed')
    for rows, seal in ((dev, dev_seal), (val, val_seal)):
        for row in rows:
            require(row['group_id'] == mapping[row_dish(row)], 'frozen_manifest_group_mismatch')
            require(seal['artifacts'].get(row['image_path']) == row['image_sha256'],
                    'manifest_image_not_sealed')
    require({row_dish(row) for row in dev} == set(snapshot['active_development_ids']),
            'active_development_mismatch')
    require({row_dish(row) for row in old_dev} == set(previous['original_development_exposure_ids']),
            'original_development_mismatch')
    require({row_dish(row) for row in val} == set(previous['selected_dish_ids']),
            'sealed_validation_mismatch')
    require({row_dish(row) for row in old_val} == set(previous['retained_original_dish_ids']) |
            set(previous['retired_validation_dish_ids']), 'original_validation_mismatch')
    recipes = recipe_map(raw_paths)
    require(set(recipes) == set(mapping), 'raw_graph_universe_changed')
    # Cross-check exact compatibility against all 300 archived recipe hashes.
    with v1_manifest.open(newline='', encoding='utf-8-sig') as stream:
        archived = list(csv.DictReader(stream))
    require(len(archived) == 300, 'archived_recipe_population_changed')
    require(all(recipes.get(row['dish_id']) == row['ingredient_group_sha256'] for row in archived),
            'archived_recipe_hash_mismatch')
    inventory = image_inventory(snapshot, sources, ((v1, old_dev), (v1, old_val),
                                 (v2, dev), (v2, val)), previous['downloads'], v2, v1)
    fingerprints, fingerprint_cache = [], {}
    for path, (dish, expected) in sorted(inventory.items()):
        bind(path, expected)
        if expected not in fingerprint_cache:
            fingerprint_cache[expected] = rgb_fingerprint(path, expected)
        fingerprints.append({'dish_id': dish, **fingerprint_cache[expected]})
    screening, members = proposal_closure(mapping, recipes, fingerprints)
    reason_ids = {
        'historical_exposure': set(snapshot['historical_exposure_ids']) |
                               set(registry['exposed_dish_ids']) | set(registry['local_dish_ids']),
        'original_development_100': {row_dish(row) for row in old_dev},
        'active_development_84': {row_dish(row) for row in dev},
        'original_validation_200_including_retired': {row_dish(row) for row in old_val},
        'current_validation_200': {row_dish(row) for row in val},
        'ambiguous_components': {dish for dish, group in mapping.items()
                                 if group in snapshot['ambiguous_component_ids']},
        'archived_exposed_recipe_hashes': {dish for dish, value in recipes.items()
                                          if value in set(registry['exposed_ingredient_group_sha256'])},
    }
    require(all(ids <= mapping.keys() for ids in reason_ids.values()), 'excluded_id_outside_graph')
    reason_groups = {reason: {screening[dish] for dish in ids} for reason, ids in reason_ids.items()}
    blocked = set().union(*reason_groups.values())
    allowed = {dish for dish in mapping if screening[dish] not in blocked}
    eligible, frame, zero_nutrition = candidate_eligibility(available_path, allowed)
    require(frame <= mapping.keys(), 'available_id_outside_frozen_graph')
    positive = positive_mass_ids(raw_paths, eligible)
    zero_mass = len(eligible - positive)
    eligible &= positive
    objects_path = bind(repo / 'Nutrition5k/metadata/realsense_overhead_objects.json')
    objects = read_json(objects_path)
    rgb_sizes = {}
    for item in objects:
        match = re.fullmatch(r'nutrition5k_dataset/imagery/realsense_overhead/(dish_[0-9]{10})/rgb\.png', item['name'])
        if not match:
            continue
        dish = match[1]
        require(dish not in rgb_sizes and str(item['size']).isdigit(), 'invalid_rgb_object_inventory')
        size = int(item['size'])
        require(0 < size <= MAX_IMAGE_BYTES, 'rgb_object_size_outside_bound')
        rgb_sizes[dish] = size
    missing_objects = len(eligible - rgb_sizes.keys())
    eligible &= rgb_sizes.keys()
    selected = fixed_selection(eligible, screening)
    local = {item['dish_id'] for item in fingerprints}
    selected_local = set(selected) & local
    selected_groups = {screening[dish] for dish in selected}
    require(not selected or len(selected) == len(selected_groups) == TARGET, 'invalid_fixed_selection')
    require(not selected_groups & blocked, 'selected_excluded_closure')
    require(len({recipes[dish] for dish in selected}) == len(selected), 'selected_recipe_collision')
    # Every local image in the frozen inventory should already be excluded.
    require(not local & eligible, 'unexpected_unexposed_local_candidate')
    immutable = {str(path.relative_to(repo)) if path.is_relative_to(repo) else str(path): value
                 for path, value in guards.items()}
    private_index = {'schema_version': 1, 'seed': SEED,
        'original_components': mapping, 'recipe_sha256': recipes,
        'screening_components': screening, 'screening_members': members,
        'blocked_screening_components': sorted(blocked),
        'known_image_fingerprints': fingerprints,
        'source_sha256': immutable}
    index_bytes = canonical(private_index)
    entries = [{'dish_id': dish, 'original_component_id': mapping[dish],
                'screening_component_id': screening[dish], 'recipe_sha256': recipes[dish],
                'source_url': f'{BASE_URL}/{dish}/rgb.png',
                'planned_destination': 'round4/data/incoming/' + digest((SEED + '|incoming|' + dish).encode()) + '/rgb.png',
                'cached_object_bytes': rgb_sizes[dish], 'max_image_bytes': MAX_IMAGE_BYTES,
                'pixel_verification': 'pending_authorized_download'} for dish in selected]
    proposal = {'schema_version': 1, 'seed': SEED, 'target_images': TARGET,
        'selection': 'one image per unblocked full proposal closure; SHA256 seed ranking; no labels/errors',
        'status': 'awaiting_new_download_authorization' if selected else 'insufficient_eligible_groups',
        'audit_index_sha256': digest(index_bytes), 'frozen_source_hashes': FROZEN,
        'cached_object_inventory_sha256': guards[objects_path],
        'entries': entries,
        'release_policy': 'After separately authorized download, blind exact bytes/RGB dedup against the complete excluded universe and all candidates; quarantine entire affected proposal components before training release. No automatic replacement or extra URL beyond the approved manifest.',
        'independence_limit': 'Distinct conservative engineering components, not certified physical plates. Undownloaded candidate pixels remain unverified.'}
    proposal_bytes = canonical(proposal)
    summary = {'schema_version': 1, 'status': proposal['status'], 'seed': SEED,
        'source_freezes_unchanged': True, 'no_download_or_api': True,
        'validation_numeric_fields_interpreted': 0, 'validation_label_files_opened': 0,
        'raw_scans': len(mapping), 'frozen_components': len(set(mapping.values())),
        'proposal_screening_components': len(members),
        'blocked_screening_components': len(blocked),
        'blocked_components_by_reason_overlapping': {key: len(value) for key, value in reason_groups.items()},
        'available_frame_images': len(frame), 'candidate_zero_nutrition_exclusions': zero_nutrition,
        'candidate_zero_positive_mass_exclusions': zero_mass,
        'candidate_missing_cached_rgb_objects': missing_objects,
        'eligible_images': len(eligible), 'eligible_screening_groups': len({screening[dish] for dish in eligible}),
        'eligible_images_already_local': len(local & eligible),
        'blind_image_file_locations_verified': len(inventory),
        'blind_image_unique_bytes_verified': len(fingerprint_cache),
        'blind_image_unique_rgb_verified': len({item['rgb_sha256'] for item in fingerprints}),
        'selected_images': len(selected), 'selected_groups': len(selected_groups),
        'selected_already_local': len(selected_local), 'new_download_file_count': len(selected) - len(selected_local),
        'cached_download_byte_estimate': sum(rgb_sizes[dish] for dish in selected if dish not in selected_local),
        'maximum_successful_payload_bytes': (len(selected) - len(selected_local)) * MAX_IMAGE_BYTES,
        'byte_estimate_basis': 'Sum of exact sizes in the existing cached official-object name/size inventory; no network revalidation and no remote content checksums.',
        'transfer_authorization': 'None. Retry bytes require a separately approved total transfer budget; the payload ceiling is not authorization.',
        'postdownload_pixel_dedup_required': True,
        'physical_plate_independence_proved': False,
        'original_frozen_hashes': FROZEN,
        'proposal_sha256': digest(proposal_bytes), 'private_audit_index_sha256': digest(index_bytes),
        'auditor_source_sha256': file_hash(Path(__file__)),
        'limitations': [proposal['independence_limit'],
            'Recipe fingerprints reproduce the archived sorted ingredient-name string; aliases/spelling differences may evade equality and common recipes may overmerge distinct plates.',
            'The frozen graph uses engineering 600-second/anchor rules and exact local pixels, not exhaustive visual or physical-plate identity.',
            'No candidate becomes training data until authorized download and blind dedup/quarantine complete; duplicates are not automatically replaced.']}
    # All source guards precede every output. No label file is part of this loop.
    for path, expected in guards.items():
        require(file_hash(path) == expected, 'source_changed_during_audit')
    immutable_write(HERE / 'private_audit_index.json', index_bytes, private=True)
    immutable_write(HERE / 'private_train600_proposal.json', proposal_bytes, private=True)
    immutable_write(HERE / 'summary.json', canonical(summary))
    return summary


def main():
    try:
        result = run()
    except AuditError as error:
        print(json.dumps({'status': 'blocked', 'error_code': str(error)}, sort_keys=True))
        return 2
    except Exception as error:
        print(json.dumps({'status': 'blocked', 'error_code': 'unexpected_' + type(error).__name__}, sort_keys=True))
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == '__main__':
    sys.exit(main())
