"""Pure independent-gallery cosine retrieval with opaque exclusion metadata.

No files, images, labels, providers, embedding services or random state are
accessed. All 3,072-dimensional vectors are supplied by the caller. Rank by
descending cosine then stable train ID, retain each group's highest-ranked
member and select exactly twelve groups. Excluding a train ID or image hash
also excludes that entry's entire association group, not just that one image.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import math
import re

import numpy as np

METHOD_VERSION = "external-gallery-cosine-r4.1"
DIMENSIONS, TOP_K = 3072, 12
ENTRY_KEYS = {"train_id", "screening_group_id", "image_sha256", "rgb_sha256"}
EXCLUSION_KEYS = {"train_ids", "screening_group_ids", "image_sha256", "rgb_sha256"}
SHA256 = re.compile(r"[0-9a-f]{64}\Z")


class RetrievalError(ValueError):
    """Deterministic errors without private metadata or vector values."""


@dataclass(frozen=True)
class GalleryEntry:
    train_id: str
    screening_group_id: str
    image_sha256: str
    rgb_sha256: str


@dataclass(frozen=True)
class GalleryIndex:
    entries: tuple[GalleryEntry, ...]
    vectors: np.ndarray
    version: str = METHOD_VERSION


def _identifier(value):
    if not isinstance(value, str) or not value or value != value.strip() or len(value) > 256:
        raise RetrievalError("invalid_opaque_identifier")
    return value


def _hash(value):
    if not isinstance(value, str) or SHA256.fullmatch(value) is None:
        raise RetrievalError("invalid_image_hash")
    return value


def _unit_vector(value):
    if isinstance(value, (list, tuple)) and any(isinstance(v, (bool, np.bool_)) for v in value):
        raise RetrievalError("invalid_embedding_type")
    try:
        array = np.asarray(value)
    except (TypeError, ValueError, OverflowError):
        raise RetrievalError("invalid_embedding_type") from None
    if array.shape != (DIMENSIONS,) or array.dtype.kind not in "fiu":
        raise RetrievalError("invalid_embedding_shape_or_type")
    try:
        array = np.array(array, dtype=np.float64, copy=True)
    except (TypeError, ValueError, OverflowError):
        raise RetrievalError("invalid_embedding_type") from None
    if not np.isfinite(array).all():
        raise RetrievalError("nonfinite_embedding")
    scale = float(np.max(np.abs(array)))
    if scale == 0:
        raise RetrievalError("zero_embedding")
    array /= scale
    array /= np.linalg.norm(array)
    if not np.isfinite(array).all():
        raise RetrievalError("nonfinite_embedding")
    return array


def build_index(entries, vectors_by_id):
    """Validate all rows, copy/normalize supplied vectors; no omitted members.

    entries have exactly train_id, screening_group_id, image_sha256 and
    rgb_sha256. vectors_by_id must have exactly those IDs. Multiple distinct
    images per group are allowed; duplicate image/RGB hashes are rejected.
    Returned arrays are read-only and input mutation cannot change the index.
    """
    if (not isinstance(entries, Sequence) or isinstance(entries, (str, bytes))
            or not entries or not isinstance(vectors_by_id, Mapping)):
        raise RetrievalError("nonempty_gallery_entries_and_vector_mapping_required")
    indexed, images, pixels = {}, set(), set()
    for row in entries:
        if not isinstance(row, Mapping) or set(row) != ENTRY_KEYS:
            raise RetrievalError("unexpected_gallery_fields")
        sid, group = _identifier(row["train_id"]), _identifier(row["screening_group_id"])
        image_hash, rgb_hash = _hash(row["image_sha256"]), _hash(row["rgb_sha256"])
        if sid in indexed or image_hash in images or rgb_hash in pixels:
            raise RetrievalError("duplicate_gallery_id_or_image")
        images.add(image_hash)
        pixels.add(rgb_hash)
        indexed[sid] = GalleryEntry(sid, group, image_hash, rgb_hash)
    if set(vectors_by_id) != set(indexed):
        raise RetrievalError("embedding_population_mismatch")
    ordered = tuple(indexed[sid] for sid in sorted(indexed))
    vectors = np.stack([_unit_vector(vectors_by_id[row.train_id]) for row in ordered])
    vectors.setflags(write=False)
    return GalleryIndex(ordered, vectors)


def _exclusions(value):
    if not isinstance(value, Mapping) or set(value) != EXCLUSION_KEYS:
        raise RetrievalError("explicit_complete_exclusions_required")
    result = {}
    for key in EXCLUSION_KEYS:
        values = value[key]
        if not isinstance(values, (list, tuple, set, frozenset)):
            raise RetrievalError("exclusion_collections_required")
        validate = _hash if key in {"image_sha256", "rgb_sha256"} else _identifier
        result[key] = {validate(item) for item in values}
    return result


def retrieve(index, query_vector, exclusions, k=TOP_K):
    """Return 12 fresh metadata dicts plus rank/cosine, with no file paths.

    exclusions has all four collection keys: train_ids, screening_group_ids,
    image_sha256, rgb_sha256. Empty collections are valid; the caller must
    include the query hashes and all opaque exclusion-proof identifiers.
    """
    if type(k) is not int or k != TOP_K:
        raise RetrievalError("exactly_twelve_neighbors_required")
    if not isinstance(index, GalleryIndex) or index.version != METHOD_VERSION:
        raise RetrievalError("invalid_gallery_index")
    if (not isinstance(index.entries, tuple) or not index.entries
            or any(not isinstance(row, GalleryEntry) for row in index.entries)
            or not isinstance(index.vectors, np.ndarray)
            or index.vectors.shape != (len(index.entries), DIMENSIONS)):
        raise RetrievalError("invalid_gallery_index")
    # Revalidate a supplied/deserialized index rather than trusting construction.
    checked = build_index([vars(row) for row in index.entries],
                          {row.train_id: index.vectors[i] for i, row in enumerate(index.entries)})
    query = _unit_vector(query_vector)
    denied = _exclusions(exclusions)
    blocked_groups = set(denied["screening_group_ids"])
    for row in checked.entries:
        if (row.train_id in denied["train_ids"] or row.image_sha256 in denied["image_sha256"]
                or row.rgb_sha256 in denied["rgb_sha256"]):
            blocked_groups.add(row.screening_group_id)
    ranked = []
    for row, value in zip(checked.entries, checked.vectors):
        if row.screening_group_id in blocked_groups:
            continue
        cosine = float(np.dot(query, value))
        if not math.isfinite(cosine):
            raise RetrievalError("nonfinite_cosine")
        ranked.append((-cosine, row.train_id, row))
    result, used_groups = [], set()
    for negative_cosine, _, row in sorted(ranked):
        if row.screening_group_id in used_groups:
            continue
        used_groups.add(row.screening_group_id)
        result.append({**vars(row), "rank": len(result) + 1, "cosine": -negative_cosine})
        if len(result) == TOP_K:
            return result
    raise RetrievalError("fewer_than_twelve_eligible_training_groups")
