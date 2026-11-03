"""Pure K component-specific training support selection.

Only explicit embeddings, opaque exclusion metadata and training ingredient
masses are accepted. No I/O, providers, query labels or prediction generation.
The caller orders the major query groups (production uses its four largest
boxes), projects hypotheses to IDs, and supplies the registered J fill order.
"""
from __future__ import annotations

from collections.abc import Mapping
import hashlib
import json
import math
from numbers import Real

import numpy as np

from round4.src import retrieval

VERSION = 'component-training-supports-r5-k.1'
DOMINANCE = 0.25
MAX_SUPPORTS = 8


class SupportError(ValueError):
    """Safe fixed-code contract error, without private input values."""


def require(condition, code):
    if not condition:
        raise SupportError(code)


def _hash(value):
    raw = json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False,
                     separators=(',', ':')).encode()
    return hashlib.sha256(raw).hexdigest()


def _sum(values):
    try:
        result = math.fsum(values)
    except (OverflowError, ValueError):
        raise SupportError('nonfinite_training_mass_sum') from None
    require(math.isfinite(result) and result > 0, 'positive_training_mass_sum_required')
    return result


def _training(supports, ids, catalog):
    require(isinstance(supports, Mapping) and set(supports) == set(ids), 'support_population_changed')
    masses, canonical = {}, {}
    for sid in sorted(ids):
        items = supports[sid]
        require(isinstance(items, (list, tuple)) and bool(items), 'positive_training_ingredients_required')
        grouped, copied = {}, []
        for item in items:
            require(isinstance(item, Mapping) and set(item) == {'ingredient_id', 'grams'},
                    'unexpected_training_ingredient_fields')
            code = retrieval._identifier(item['ingredient_id'])
            grams = item['grams']
            require(code in catalog, 'training_id_absent_from_catalog')
            require(isinstance(grams, Real) and not isinstance(grams, (bool, np.bool_))
                    and math.isfinite(grams) and grams > 0, 'finite_positive_training_grams_required')
            grouped.setdefault(code, []).append(float(grams))
            copied.append({'ingredient_id': code, 'grams': float(grams)})
        per_id = {code: _sum(values) for code, values in grouped.items()}
        total = _sum([item['grams'] for item in copied])
        masses[sid] = {code: grams / total for code, grams in per_id.items()}
        # Bind the actual item list, including duplicate entries and its order.
        canonical[sid] = copied
    return masses, canonical


def _groups(query_groups, catalog):
    require(isinstance(query_groups, (list, tuple)) and 1 <= len(query_groups) <= 8,
            'one_through_eight_ordered_query_groups_required')
    result, seen = [], set()
    for group in query_groups:
        require(isinstance(group, Mapping) and set(group) == {'group_id', 'hypotheses'},
                'unexpected_query_group_fields')
        identifier = retrieval._identifier(group['group_id'])
        require(identifier not in seen, 'duplicate_query_group_id')
        seen.add(identifier)
        hypotheses = group['hypotheses']
        require(isinstance(hypotheses, (list, tuple)) and len(hypotheses) <= 2,
                'zero_through_two_ordered_hypotheses_required')
        hypotheses = [retrieval._identifier(code) for code in hypotheses]
        require(len(hypotheses) == len(set(hypotheses)) and set(hypotheses) <= catalog,
                'duplicate_or_non_catalog_hypothesis')
        result.append({'group_id': identifier, 'hypotheses': hypotheses})
    return result


def select_supports(query_vector, entries, vectors_by_id, supports, query_groups,
                    exclusions, *, catalog_ids, fill_train_ids=()):
    """Select up to eight distinct association groups in fixed group-major order.

    entries: J's train_id/screening_group_id/image_sha256/rgb_sha256 dictionaries.
    supports: train_id -> nonempty list of {ingredient_id, grams}, all grams > 0.
    query_groups: ordered {group_id, hypotheses: [catalog_id, ...]} dictionaries.
    exclusions: all four J exclusion sets, including empty sets explicitly.

    A hypothesis ranks every eligible positive-ID support by dominant>=.25,
    cosine, mass fraction, then ID. A different image from an already-used group
    is infeasible. Reuse occurs only when the highest feasible image is already
    selected. If that image is new and the budget is exhausted, report budget;
    do not downgrade to a lower-ranked trace-containing image to claim coverage.
    Fill order is explicit and never reranked using training labels.
    """
    require(isinstance(catalog_ids, (list, tuple, set, frozenset)) and bool(catalog_ids),
            'explicit_nonempty_catalog_ids_required')
    catalog_list = [retrieval._identifier(code) for code in catalog_ids]
    require(len(catalog_list) == len(set(catalog_list)), 'duplicate_catalog_id')
    catalog = set(catalog_list)
    index = retrieval.build_index(entries, vectors_by_id)
    query = retrieval._unit_vector(query_vector)
    denied = retrieval._exclusions(exclusions)
    by_id = {row.train_id: row for row in index.entries}
    fractions, canonical_supports = _training(supports, by_id, catalog)
    groups = _groups(query_groups, catalog)
    require(isinstance(fill_train_ids, (list, tuple)), 'explicit_ordered_fill_ids_required')
    fill = [retrieval._identifier(sid) for sid in fill_train_ids]
    require(set(fill) <= set(by_id), 'fill_id_absent_from_gallery')

    blocked = set(denied['screening_group_ids'])
    for row in index.entries:
        if (row.train_id in denied['train_ids'] or row.image_sha256 in denied['image_sha256']
                or row.rgb_sha256 in denied['rgb_sha256']):
            blocked.add(row.screening_group_id)
    eligible = [row.train_id for row in index.entries if row.screening_group_id not in blocked]
    cosine = {row.train_id: float(np.dot(query, vector)) for row, vector in zip(index.entries, index.vectors)}
    require(all(math.isfinite(value) for value in cosine.values()), 'nonfinite_support_cosine')

    selected, selected_set, used_groups, assignments = [], set(), set(), []
    def add(sid):
        selected.append(sid)
        selected_set.add(sid)
        used_groups.add(by_id[sid].screening_group_id)

    for group in groups:
        for h_index, code in enumerate(group['hypotheses']):
            ranked = sorted((sid for sid in eligible if code in fractions[sid]),
                key=lambda sid: (-(fractions[sid][code] >= DOMINANCE), -cosine[sid],
                                 -fractions[sid][code], sid))
            feasible = [sid for sid in ranked if sid in selected_set
                        or by_id[sid].screening_group_id not in used_groups]
            assignment = {'group_id': group['group_id'], 'hypothesis_index': h_index,
                'ingredient_id': code, 'status': None, 'covered': False, 'train_id': None,
                'dominant': None, 'ingredient_mass_fraction': None, 'cosine': None,
                'eligible_support_count': len(ranked), 'feasible_support_count': len(feasible)}
            if not ranked:
                assignment['status'] = 'unavailable'
            elif not feasible:
                assignment['status'] = 'group_conflict'
            else:
                sid = feasible[0]
                if sid not in selected_set and len(selected) == MAX_SUPPORTS:
                    assignment['status'] = 'budget'
                else:
                    assignment.update(status='reused' if sid in selected_set else 'selected',
                        covered=True, train_id=sid, dominant=fractions[sid][code] >= DOMINANCE,
                        ingredient_mass_fraction=fractions[sid][code], cosine=cosine[sid])
                    if sid not in selected_set:
                        add(sid)
            assignments.append(assignment)

    filled = []
    for sid in fill:
        if len(selected) == MAX_SUPPORTS:
            break
        if sid in selected_set or by_id[sid].screening_group_id in blocked | used_groups:
            continue
        add(sid)
        filled.append(sid)

    normalized_inputs = {
        'query_vector': np.asarray(query_vector, dtype=np.float64).tolist(),
        'entries': [vars(row) for row in index.entries],
        'vectors_by_id': {sid: np.asarray(vectors_by_id[sid], dtype=np.float64).tolist() for sid in sorted(by_id)},
        'supports': canonical_supports, 'query_groups': groups,
        'exclusions': {key: sorted(value) for key, value in denied.items()},
        'catalog_ids': sorted(catalog), 'fill_train_ids': fill}
    return {'selected_train_ids': selected, 'hypothesis_supports': assignments,
        'audit': {'version': VERSION, 'dominance_threshold': DOMINANCE, 'support_budget': MAX_SUPPORTS,
            'processing_order': 'group_order_then_hypothesis_order',
            'ranking': ['dominant_desc', 'cosine_desc', 'ingredient_mass_fraction_desc', 'train_id_asc'],
            'eligible_training_images': len(eligible),
            'eligible_training_groups': len({by_id[sid].screening_group_id for sid in eligible}),
            'selected_training_groups': len(used_groups), 'filled_train_ids': filled,
            'input_sha256': {key: _hash(value) for key, value in normalized_inputs.items()},
            'selection_sha256': _hash({'selected_train_ids': selected, 'hypothesis_supports': assignments})}}
