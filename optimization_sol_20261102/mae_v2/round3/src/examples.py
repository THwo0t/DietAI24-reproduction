"""Pure, label-blind G support selection from frozen raw C leaf embeddings.

No files, labels, images, APIs, learned parameters, or random state are read.
Callers provide the development rows, completed raw C records, and the frozen
FNDDS code/vector arrays. Returned IDs are private adapter inputs, not reports.
"""
from __future__ import annotations

import math
from collections.abc import Mapping, Sequence

import numpy as np

TARGETS = ("weight", "energy", "fat", "carbs", "protein")


class SelectionError(ValueError):
    """Stable failures that never disclose row IDs, labels, or vector values."""


def _fail(code):
    raise SelectionError(code)


def _number(value):
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, (int, float, np.integer, np.floating)):
        _fail("invalid_nonnegative_number")
    try:
        result = float(value)
    except (ValueError, OverflowError):
        _fail("invalid_nonnegative_number")
    if not math.isfinite(result) or result < 0:
        _fail("invalid_nonnegative_number")
    return result


def _index_rows(rows):
    if not isinstance(rows, Sequence) or not rows:
        _fail("development_rows_required")
    result = {}
    for row in rows:
        if not isinstance(row, Mapping) or row.get("dataset") != "nutrition5k" or row.get("split") != "dev":
            _fail("nutrition5k_development_rows_required")
        sid, group, fold = row.get("sample_id"), row.get("group_id"), row.get("fold")
        if not isinstance(sid, str) or not sid or sid in result:
            _fail("invalid_or_duplicate_sample_id")
        if not isinstance(group, str) or not group or type(fold) is not int or fold not in range(5):
            _fail("invalid_group_or_fold")
        result[sid] = row
    return result


def _vectors(codes, vectors):
    if not isinstance(codes, Sequence) or isinstance(codes, (str, bytes)) or not codes:
        _fail("embedding_codes_required")
    if any(not isinstance(code, str) or not code for code in codes) or len(set(codes)) != len(codes):
        _fail("invalid_or_duplicate_embedding_code")
    try:
        array = np.asarray(vectors)
    except (TypeError, ValueError):
        _fail("invalid_embedding_array")
    if array.ndim != 2 or array.shape[0] != len(codes) or not array.shape[1] or array.dtype.kind not in "fiu":
        _fail("invalid_embedding_shape_or_type")
    array = np.asarray(array, dtype=np.float64)
    if not np.isfinite(array).all() or np.any(np.max(np.abs(array), axis=1) == 0):
        _fail("nonfinite_or_zero_embedding")
    return {code: i for i, code in enumerate(codes)}, array


def build_features(rows, raw_predictions, codes, vectors):
    """Return unit feature vectors keyed by row ID, using code and grams only.

    For leaves j, feature = L2_normalize(sum_j grams_j * embedding(code_j)
    / sum_j grams_j). Frozen embedding vectors are used as supplied; no new
    embeddings, per-row reference quantities, or calibrated C grams are used.
    Leaf order cannot change summation order: duplicate codes are aggregated and
    then summed in sorted code order. All rows must have a complete raw vector.
    """
    indexed = _index_rows(rows)
    if not isinstance(raw_predictions, Sequence):
        _fail("raw_prediction_records_required")
    code_index, array = _vectors(codes, vectors)
    records = {}
    for record in raw_predictions:
        if not isinstance(record, Mapping):
            _fail("invalid_raw_prediction_record")
        sid = record.get("sample_id")
        if not isinstance(sid, str) or sid not in indexed or sid in records:
            _fail("unexpected_or_duplicate_raw_prediction")
        row = indexed[sid]
        if type(record.get("fold")) is not int or any(record.get(k) != row[k] for k in ("dataset", "group_id", "fold")):
            _fail("raw_prediction_row_binding_mismatch")
        pred = record.get("raw_prediction")
        if not isinstance(pred, Mapping) or set(pred) != set(TARGETS):
            _fail("complete_raw_prediction_required")
        values = {t: _number(pred[t]) for t in TARGETS}
        if values["weight"] <= 0:
            _fail("positive_raw_weight_required")
        leaves = record.get("raw_leaves")
        if not isinstance(leaves, list) or not leaves:
            _fail("raw_C_leaves_required")
        code_grams = {}
        for leaf in leaves:
            if not isinstance(leaf, Mapping):
                _fail("invalid_raw_C_leaf")
            code = leaf.get("code")
            if not isinstance(code, str) or code not in code_index:
                _fail("leaf_code_missing_from_frozen_embeddings")
            grams = _number(leaf.get("grams"))
            code_grams.setdefault(code, []).append(grams)
        try:
            # Sorting mass values also keeps duplicate-code leaf order irrelevant.
            masses = {code: math.fsum(sorted(g)) for code, g in code_grams.items()}
            total = math.fsum(masses.values())
        except OverflowError:
            _fail("invalid_total_leaf_mass")
        if not math.isfinite(total) or total <= 0:
            _fail("invalid_total_leaf_mass")
        feature = np.zeros(array.shape[1], dtype=np.float64)
        for code in sorted(masses):
            feature += (masses[code] / total) * array[code_index[code]]
        scale = float(np.max(np.abs(feature)))
        if not math.isfinite(scale) or scale == 0:
            _fail("nonfinite_or_zero_dish_feature")
        # Scaling before the norm avoids overflow without changing direction.
        feature = feature / scale
        feature = feature / np.linalg.norm(feature)
        if not np.isfinite(feature).all():
            _fail("nonfinite_or_zero_dish_feature")
        records[sid] = feature
    if set(records) != set(indexed):
        _fail("missing_raw_prediction_row")
    return records


def select_examples(rows, raw_predictions, codes, vectors, query_id, count=4):
    """Select exactly four nearest development examples from distinct groups.

    Excludes the query's entire fold AND its entire association group. Sorts by
    descending cosine then sample_id; among duplicate groups only the first row
    remains. Fewer than four eligible groups is an error, never a relaxed rule.
    Truth, errors, nutrient densities, images, and calibrated predictions are not
    accessed. Complete raw five-target vectors are validated but never ranked.
    """
    if type(count) is not int or count != 4:
        _fail("exactly_four_examples_required")
    indexed = _index_rows(rows)
    if not isinstance(query_id, str) or query_id not in indexed:
        _fail("query_row_missing")
    features = build_features(rows, raw_predictions, codes, vectors)
    query = indexed[query_id]
    ranked = []
    for sid, row in indexed.items():
        if row["fold"] == query["fold"] or row["group_id"] == query["group_id"]:
            continue
        cosine = float(np.dot(features[query_id], features[sid]))
        if not math.isfinite(cosine):
            _fail("nonfinite_cosine")
        ranked.append((-cosine, sid))
    result, used = [], set()
    for _, sid in sorted(ranked):
        group = indexed[sid]["group_id"]
        if group in used:
            continue
        result.append(sid)
        used.add(group)
        if len(result) == count:
            return result
    _fail("fewer_than_four_eligible_training_groups")
