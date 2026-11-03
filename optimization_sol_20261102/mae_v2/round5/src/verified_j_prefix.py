"""Pure projection of an ALREADY verified, completed J continuation.

``extract_prefixes(verified_base, assets)`` performs no I/O, verification run,
provider construction or inference. The caller must obtain ``verified_base``
from continuation.runner.base(verify_only=True) and verify the supplied assets
against that same context. A dictionary claiming verification is not a seal.
The production adapter, not this function, enforces the fixed 84-query cohort.

assets contains the five original context.assets fields plus ``queries`` and
``gallery_entries`` (context.queries and context.entries). Paths must already
be absolute canonical paths. No paths are resolved, opened or image-hashed.

Only the four upstream stage results are projected. Description/rerank raw
answers remain in the parent archive; their complete stage hashes are retained
here instead. The arbitrary parent binding is also represented ONLY by its
ArtifactStore fingerprint (whose canonical JSON includes a final newline).
Old estimates, predictions, query labels/folds and whole-record audit fields
are never copied. Support ingredient grams come only from external TRAIN assets.

The selected four supports describe the PARENT selection, not a new candidate
policy. A future registered candidate may use only description/vector and make
a different support selection. This return value is an orchestration/audit
object, never a model message: a future estimator must explicitly whitelist
the inputs its registered method needs. Vectors and retrieval cosine/rank/group
metadata are useful to offline selection/audit, not required by a final vision
prompt; no new selection strategy is implemented here.
"""
from __future__ import annotations

from copy import deepcopy
import math
from pathlib import Path

from opt_pipeline import TARGETS, _number, _object
from round4.src import catalog_estimator, pipeline, retrieval, vision_stages
from round4.src.artifacts import fingerprint

VERSION = "verified-j-prefix-r5.1"
UPSTREAM = ("description", "embedding", "retrieval", "rerank")
ASSET_KEYS = pipeline.ASSET_KEYS | {"queries", "gallery_entries"}
VERIFIED_KEYS = {"status", "n", "records", "binding", "completion_sha256",
                 "provider_constructed", "validation_opened"}


class PrefixError(ValueError):
    """Fixed-message input mismatch; never a nutritional/model fallback."""


def _require(condition, code):
    if not condition:
        raise PrefixError(code)


def _path(value):
    _require(isinstance(value, (str, Path)) and bool(str(value)), "invalid_image_path")
    path = Path(value)
    _require(path.is_absolute() and ".." not in path.parts, "canonical_absolute_path_required")
    return str(path)


def _assets(assets):
    _object(assets, ASSET_KEYS)
    _require(assets["scope"] == "external_train_only", "external_training_assets_required")
    training_sha = retrieval._hash(assets["training_sha256"])
    catalog = catalog_estimator._catalog(assets["catalog"])
    _object(assets["fallback"], set(TARGETS))
    fallback = {key: _number(assets["fallback"][key]) for key in TARGETS}
    _require(fallback["weight"] > 0, "positive_training_fallback_required")
    rows = assets["gallery_entries"]
    _require(isinstance(rows, list) and len(rows) >= retrieval.TOP_K, "training_gallery_required")
    entries, images, pixels = {}, set(), set()
    for row in rows:
        _object(row, retrieval.ENTRY_KEYS)
        sid = retrieval._identifier(row["train_id"])
        entry = {"train_id": sid, "screening_group_id": retrieval._identifier(row["screening_group_id"]),
                 "image_sha256": retrieval._hash(row["image_sha256"]),
                 "rgb_sha256": retrieval._hash(row["rgb_sha256"])}
        _require(sid not in entries and entry["image_sha256"] not in images
                 and entry["rgb_sha256"] not in pixels, "duplicate_training_image_or_id")
        entries[sid] = entry
        images.add(entry["image_sha256"])
        pixels.add(entry["rgb_sha256"])
    supports = assets["supports"]
    _require(isinstance(supports, dict) and set(supports) == set(entries),
             "support_gallery_population_mismatch")
    normalized, paths = {}, set()
    for sid in sorted(supports):
        support = _object(supports[sid], {"image_path", "ingredients"})
        path = _path(support["image_path"])
        _require(path not in paths, "duplicate_training_image_path")
        paths.add(path)
        ingredients = support["ingredients"]
        _require(isinstance(ingredients, list) and bool(ingredients), "positive_support_ingredients_required")
        clean, amounts = [], []
        for item in ingredients:
            _object(item, {"ingredient_id", "grams"})
            identifier = item["ingredient_id"]
            _require(isinstance(identifier, str) and identifier in catalog, "unknown_support_ingredient")
            grams = catalog_estimator._positive(item["grams"])
            clean.append({"ingredient_id": identifier, "grams": grams})
            amounts.append(catalog_estimator._amounts(grams, catalog[identifier]["density_per_100g"]))
        catalog_estimator._total(amounts)
        normalized[sid] = {"image_path": path, "ingredients": clean}
    rows = assets["queries"]
    _require(isinstance(rows, list) and bool(rows), "query_metadata_required")
    queries = {}
    for row in rows:
        _object(row, pipeline.QUERY_KEYS)
        sid = retrieval._identifier(row["query_id"])
        _require(sid not in queries, "duplicate_query_id")
        query = {"query_id": sid, "image_path": _path(row["image_path"]),
                 "image_sha256": retrieval._hash(row["image_sha256"]),
                 "rgb_sha256": retrieval._hash(row["rgb_sha256"]),
                 "screening_group_id": retrieval._identifier(row["screening_group_id"])}
        _require(query["image_path"] not in paths, "query_path_is_training_support")
        queries[sid] = query
    return training_sha, entries, normalized, queries


def _retrieved(value, query, entries):
    _require(isinstance(value, list) and len(value) == retrieval.TOP_K, "exactly_twelve_retrieved_required")
    blocked = {query["screening_group_id"]}
    for row in entries.values():
        if (row["train_id"] == query["query_id"] or row["image_sha256"] == query["image_sha256"]
                or row["rgb_sha256"] == query["rgb_sha256"]):
            blocked.add(row["screening_group_id"])
    groups, ids, keys, result = set(), set(), [], []
    for rank, row in enumerate(value, 1):
        _object(row, retrieval.ENTRY_KEYS | {"rank", "cosine"})
        sid = row["train_id"]
        _require(isinstance(sid, str) and sid in entries, "retrieved_id_not_in_training")
        metadata = {key: row[key] for key in retrieval.ENTRY_KEYS}
        _require(metadata == entries[sid], "retrieved_image_or_group_changed")
        group = row["screening_group_id"]
        _require(sid not in ids and group not in groups and group not in blocked,
                 "retrieved_duplicate_or_excluded_group")
        cosine = row["cosine"]
        _require(type(row["rank"]) is int and row["rank"] == rank
                 and type(cosine) in (int, float) and math.isfinite(cosine)
                 and abs(cosine) <= 1 + 1e-12, "invalid_retrieval_rank_or_cosine")
        ids.add(sid)
        groups.add(group)
        keys.append((-cosine, sid))
        result.append(deepcopy(row))
    _require(keys == sorted(keys), "retrieval_order_changed")
    # Exact cosine/top-k recomputation belongs to the completed parent verifier;
    # this projection deliberately does not load any training vector bank.
    return result


def _prefix(record, query, entries, supports, training_sha):
    _require(isinstance(record, dict) and record.get("query_id") == query["query_id"]
             and record.get("sample_id") == query["query_id"]
             and record.get("method") == pipeline.METHOD_VERSION, "parent_record_identity_changed")
    stages = record.get("stages")
    _require(isinstance(stages, dict) and "description" in stages, "parent_prefix_missing")
    description = pipeline.validate_description_result(stages["description"])
    clean = {key: None for key in UPSTREAM}
    clean["description"] = {key: deepcopy(description[key]) for key in
                            ("parsed", "embedding_text", "repair_used", "failure")}
    stage_hashes = {"description": fingerprint(stages["description"])}
    out = {"query": deepcopy(query), "stages": clean, "candidate_images": [],
           "selected_candidate_ids": [], "selected_train_ids": [], "selected_supports": [],
           "repair_used": description["repair_used"], "method_fallback": False,
           "method_fallback_reason": None, "fallback": False, "failure": None,
           "provenance": {"stage_sha256": stage_hashes}}
    if description["failure"] is not None:
        _require(set(stages) == {"description"}, "stages_after_failed_description")
        out.update(fallback=True, failure="description:" + description["failure"])
        return out
    _require(set(stages) == set(UPSTREAM) | {"estimate"}, "completed_parent_stages_missing_or_extra")
    clean["embedding"] = pipeline.validate_embedding_result(stages["embedding"])
    clean["retrieval"] = _retrieved(stages["retrieval"], query, entries)
    rerank = pipeline.validate_rerank_result(stages["rerank"])
    clean["rerank"] = {key: deepcopy(rerank[key]) for key in ("selected_ids", "repair_used", "failure")}
    stage_hashes.update({key: fingerprint(stages[key]) for key in UPSTREAM[1:]})
    by_candidate = dict(zip(vision_stages.CANDIDATE_IDS, clean["retrieval"]))
    selected = (list(vision_stages.CANDIDATE_IDS[:4]) if rerank["failure"] is not None
                else list(rerank["selected_ids"]))
    ids = [by_candidate[key]["train_id"] for key in selected]
    audit = record.get("audit")
    _require(isinstance(audit, dict) and audit.get("training_sha256") == training_sha
             and audit.get("selected_candidate_ids") == selected
             and audit.get("selected_train_ids") == ids, "parent_selection_or_training_changed")
    out["provenance"]["gallery_sha256"] = retrieval._hash(audit.get("gallery_sha256"))
    out["candidate_images"] = [{"candidate_id": cid, **deepcopy(entries[row["train_id"]]),
                                "image_path": supports[row["train_id"]]["image_path"]}
                               for cid, row in by_candidate.items()]
    out["selected_candidate_ids"], out["selected_train_ids"] = selected, ids
    out["selected_supports"] = [deepcopy(supports[sid]) for sid in ids]
    out["repair_used"] |= rerank["repair_used"]
    if rerank["failure"] is not None:
        out.update(method_fallback=True, method_fallback_reason="rerank:" + rerank["failure"])
    return out


def extract_prefixes(verified_base, assets):
    """Return isolated upstream data; all population sizes are caller supplied.

    The output's support masses are external-training references, never query
    truths. Parent estimate success/repair/fallback has no effect on this output.
    A failed parent description stays a terminal prefix fallback; no later
    stage is synthesized. A failed rerank retains its original top-four choice.
    """
    _object(verified_base, VERIFIED_KEYS)
    _require(verified_base["status"] == "base_verified"
             and verified_base["provider_constructed"] is False
             and verified_base["validation_opened"] is False, "completed_readonly_verification_required")
    training_sha, entries, supports, queries = _assets(assets)
    records, binding = verified_base["records"], verified_base["binding"]
    _require(isinstance(records, dict) and set(records) == set(queries)
             and type(verified_base["n"]) is int and verified_base["n"] == len(records),
             "verified_query_population_mismatch")
    _require(isinstance(binding, dict) and binding.get("phase") == "development_base"
             and isinstance(binding.get("service_continuation"), dict)
             and binding.get("training_freeze_sha256") == training_sha
             and type(binding.get("query_count")) is int
             and binding["query_count"] == len(records), "parent_external_training_binding_changed")
    provenance = {"parent_completion_sha256": retrieval._hash(verified_base["completion_sha256"]),
                  "parent_binding_sha256": fingerprint(binding),
                  "training_freeze_sha256": training_sha,
                  "gallery_completion_sha256": retrieval._hash(binding.get("gallery_completion_sha256"))}
    prefixes = {sid: _prefix(records[sid], queries[sid], entries, supports, training_sha)
                for sid in sorted(records)}
    return {"version": VERSION, "n": len(prefixes), "provenance": provenance, "prefixes": prefixes}
