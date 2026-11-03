"""Fixed training identity projection; never open labels, ingredients or images.

All proposed candidates remain protected, including historical quarantine. This
is source identity evidence, not actual API exposure, eligibility or permission.
"""
from collections import Counter
from copy import deepcopy
from pathlib import Path
import re

import n5_sources
from source_census import REPO, PREFIX, bounded_read, decode, sha, require

MANIFEST = PREFIX + 'round4/data/train/manifest.jsonl'
TRAIN = 'round4/data/train'
FIELDS = {'sample_id', 'dataset', 'split', 'group_id', 'original_component_id',
          'recipe_sha256', 'image_path', 'image_sha256', 'rgb_sha256'}
DISH = re.compile(r'dish_[0-9]{10}\Z')
REASONS = {'protected_bytes_sha256', 'protected_rgb_sha256',
    'candidate_collision_bytes_sha256', 'candidate_collision_rgb_sha256',
    'quarantined_screening_component'}


def _projection(n5, audit, freeze, raw, *, expected_count):
    require(freeze.get('schema_version') == 1 and freeze.get('status') ==
            'accepted_external_training_frozen', 'authenticated_training_freeze_required')
    pins = n5['source_hashes']
    for field, slot in (('proposal_sha256', 'training_proposal'),
                        ('private_audit_index_sha256', 'index')):
        require(audit.get(field) == freeze['binding'].get(field) == pins[slot],
                'training_identity_binding_changed')
    require(audit.get('schema_version') == 1, 'training_audit_schema_required')
    proposals = [r['dish_id'] for r in n5['train_entries']]
    require(len(proposals) == expected_count and len(set(proposals)) == expected_count
            and all(isinstance(d, str) and DISH.fullmatch(d) for d in proposals),
            'complete_unique_training_proposal_required')
    pixels = {}
    for row in n5['train_pixels']:
        dish = row['dish_id']
        require(dish in proposals and dish not in pixels, 'unique_training_pixels_required')
        require(all(isinstance(row[k], str) and n5_sources.HEX.fullmatch(row[k])
                    for k in ('bytes_sha256', 'rgb_sha256')), 'training_pixel_hash_required')
        pixels[dish] = row
    require(set(pixels) == set(proposals), 'complete_training_pixels_required')
    index = n5['index']; candidates = {}
    for row in audit['candidate_audit']:
        dish = row['dish_id']; reasons = row['quarantine_reasons']
        require(dish in pixels and dish not in candidates, 'unique_training_audit_identity_required')
        require(all(row[k] == pixels[dish][k] for k in ('bytes_sha256', 'rgb_sha256')),
                'training_audit_pixels_changed')
        require(isinstance(reasons, list) and all(isinstance(r, str) and r in REASONS for r in reasons)
                and len(set(reasons)) == len(reasons), 'registered_training_quarantine_required')
        require(isinstance(row['screening_component_id'], str) and row['screening_component_id']
                and row['screening_component_id'] == index['screening_components'][dish]
                and isinstance(index['original_components'][dish], str)
                and index['original_components'][dish]
                and n5_sources.HEX.fullmatch(index['recipe_sha256'][dish]),
                'training_component_recipe_identity_required')
        candidates[dish] = {'dish_id': dish, 'sample_id': 'nutrition5k-' + dish,
            'screening_component_id': row['screening_component_id'],
            'original_component_id': index['original_components'][dish],
            'recipe_sha256': index['recipe_sha256'][dish],
            'bytes_sha256': row['bytes_sha256'], 'rgb_sha256': row['rgb_sha256'],
            'quarantine_reasons': deepcopy(reasons), 'protected_training_proposal': True}
    require(set(candidates) == set(proposals)
            and audit.get('complete_candidate_count') == expected_count,
            'complete_training_audit_required')
    accepted = {}
    for line in raw.splitlines():
        require(bool(line), 'nonempty_training_manifest_row_required')
        row = decode(line)
        require(isinstance(row, dict) and set(row) == FIELDS,
                'identity_only_training_manifest_required')
        sample = row['sample_id']
        require(isinstance(sample, str) and sample.startswith('nutrition5k-')
                and row['dataset'] == 'nutrition5k' and row['split'] == 'train',
                'training_manifest_identity_required')
        dish = sample.removeprefix('nutrition5k-')
        require(dish in candidates and dish not in accepted, 'unique_accepted_training_identity_required')
        old = candidates[dish]
        require(not old['quarantine_reasons']
                and row['group_id'] == old['screening_component_id']
                and row['original_component_id'] == old['original_component_id']
                and row['recipe_sha256'] == old['recipe_sha256']
                and row['image_sha256'] == old['bytes_sha256']
                and row['rgb_sha256'] == old['rgb_sha256']
                and row['image_path'] == TRAIN + '/images/' + old['bytes_sha256'] + '.png'
                and freeze['artifacts'].get('images/' + old['bytes_sha256'] + '.png')
                    == old['bytes_sha256'], 'accepted_training_binding_changed')
        accepted[dish] = deepcopy(row)
    require(set(accepted) == {d for d,r in candidates.items() if not r['quarantine_reasons']},
            'accepted_training_manifest_incomplete')
    require(len({r['image_sha256'] for r in accepted.values()}) == len(accepted)
            == len({r['rgb_sha256'] for r in accepted.values()}), 'accepted_training_pixel_collision')
    counts = {'accepted_images': len(accepted),
        'accepted_groups': len({r['group_id'] for r in accepted.values()}),
        'quarantined_images': expected_count - len(accepted)}
    require(all(type(audit.get(k)) is int and type(freeze.get(k)) is int
                and audit[k] == freeze[k] == v for k,v in counts.items()),
            'training_identity_counts_changed')
    require(dict(Counter(r for c in candidates.values() for r in c['quarantine_reasons']))
            == audit.get('quarantine_reason_counts_overlapping'), 'training_quarantine_counts_changed')
    return {'protected_proposals_private': [candidates[d] for d in sorted(candidates)],
        'accepted_manifest_private': [accepted[d] for d in sorted(accepted)],
        'counts': {'protected_training_proposals': expected_count, **counts},
        'actual_api_exposure_complete': False, 'candidate_eligibility_evaluated': False,
        'source_association_complete': False, 'grants_sampling_download_or_inference': False,
        'labels_or_ingredients_or_images_opened': False, 'new_samples_selected': 0,
        'new_downloads': 0, 'api_calls': 0}


class _BoundTraining:
    def __init__(self, repo, reader, raw):
        self.repo, self.reader, self.raw = repo, reader, raw

    def revalidate(self):
        self.reader.revalidate()
        require(bounded_read(self.repo, MANIFEST) == self.raw, 'training_manifest_changed')


def _load_at(repo, *, expected_count=230):
    """Private synthetic-root hook; no caller-provided anchors or path inventory."""
    repo = Path(repo)
    require(repo.is_absolute() and repo.resolve() == repo, 'canonical_training_root_required')
    n5, reader = n5_sources.load_identity_sources(repo)
    reader.revalidate()
    # Consume only fixed reader slots; no recursive source or artifact chasing.
    freeze = decode(reader.bound['training_freeze'])
    audit = decode(reader.bound['training_audit'])
    raw = bounded_read(repo, MANIFEST)
    require(sha(raw) == freeze['artifacts']['manifest.jsonl'], 'training_manifest_hash_changed')
    result = _projection(n5, audit, freeze, raw, expected_count=expected_count)
    bound = _BoundTraining(repo, reader, raw)
    bound.revalidate()
    result['source_hashes'] = {n5_sources.PATHS[k]: v for k,v in n5['source_hashes'].items()}
    result['source_hashes'][MANIFEST] = sha(raw)
    return result, bound


def load_training_identity():
    """Return (private projection, bound reader) at fixed repository/230 proposals.

    n5_sources authenticates its fixed training-freeze anchor and source slots.
    Revalidate the returned reader immediately before and after consuming held
    identities. It never opens referenced image, label or ingredient paths.
    """
    return _load_at(REPO)
