"""Pure external-training gallery orchestration with injected persistence.

Import as ``round4.src.pipeline`` with the v2 root and v2/src on sys.path.
No dataset discovery, label loading, provider construction or artifact writes.
Only vision stages read explicitly supplied images. The production loader must
verify their declared byte/RGB hashes and the external-training release before
calling this module; a scope string alone cannot establish that provenance.

``stage_runner(name, inputs, call, validator)`` is optional. ``call()`` returns
JSON-safe raw stage data. ``validator(raw)`` reparses/recomputes it and returns a
canonical result or raises on corruption. Expected format failure after one
repair is a valid terminal result, cached without retry; the pipeline applies
the registered fallback. Provider/integrity exceptions propagate unchanged.
The runner owns source hashes, immutable envelopes, locks and completion seals.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path

from opt_pipeline import ContractError, TARGETS, NUTRIENTS, _object, _number
from round4.src import catalog_estimator as estimator
from round4.src import retrieval, vision_stages as vision

METHOD_VERSION = "external-gallery-pipeline-r4.1"
ASSET_KEYS = {"scope", "training_sha256", "catalog", "fallback", "supports"}
QUERY_KEYS = {"query_id", "image_path", "image_sha256", "rgb_sha256", "screening_group_id"}
IMAGE_KEYS = {"image_id", "image_path", "image_sha256", "rgb_sha256"}


class PipelineError(ValueError):
    """Safe contract/integrity failure, never a model-accuracy fallback."""


def fingerprint(value):
    try:
        raw = json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False,
                         separators=(",", ":")).encode()
    except (TypeError, ValueError, OverflowError):
        raise PipelineError("stage_data_must_be_finite_json") from None
    return hashlib.sha256(raw).hexdigest()


def _same(value, expected):
    if fingerprint(value) != fingerprint(expected):
        raise PipelineError("stage_result_does_not_match_replayed_raw_output")
    return deepcopy(expected)


def _run(name, inputs, call, validator, runner):
    fingerprint(inputs)  # Reject unserializable dependencies before a call.
    if runner is None:
        value = call()
    else:
        if not callable(runner):
            raise PipelineError("stage_runner_must_be_callable")
        value = runner(name, deepcopy(inputs), call, validator)
    # Even a custom runner cannot bypass the same fresh/cache result validation.
    return validator(value)


def _replay(value, fields, parser):
    _object(value, fields)
    raw = value["raw_outputs"]
    if (not isinstance(raw, list) or len(raw) not in (1, 2)
            or any(not isinstance(text, str) for text in raw)
            or type(value["repair_used"]) is not bool):
        raise PipelineError("invalid_stage_raw_attempts")
    parsed, failure = None, None
    for index, text in enumerate(raw):
        try:
            parsed = parser(text)
        except ContractError as exc:
            failure = str(exc)
        else:
            if index != len(raw) - 1:
                raise PipelineError("successful_stage_cannot_have_extra_retry")
            failure = None
            break
    if failure is not None and len(raw) != 2:
        raise PipelineError("failed_stage_requires_exhausted_single_repair")
    return list(raw), parsed, len(raw) == 2, failure


def validate_description_result(value):
    raw, parsed, repair, failure = _replay(value,
        {"raw_outputs", "parsed", "embedding_text", "repair_used", "failure"}, vision._parse_description)
    expected = {"raw_outputs": raw, "parsed": parsed[0] if parsed is not None else None,
                "embedding_text": parsed[1] if parsed is not None else None,
                "repair_used": repair, "failure": failure}
    return _same(value, expected)


def validate_rerank_result(value):
    raw, parsed, repair, failure = _replay(value,
        {"raw_outputs", "selected_ids", "repair_used", "failure"}, vision._parse_rerank)
    return _same(value, {"raw_outputs": raw, "selected_ids": parsed,
                         "repair_used": repair, "failure": failure})


def validate_estimate_result(value, catalog):
    indexed = estimator._catalog(catalog)
    raw, parsed, repair, failure = _replay(value,
        {"raw_outputs", "items", "prediction", "repair_used", "failure", "audit"},
        lambda text: estimator._parse(text, indexed))
    if parsed is None:
        items, prediction = [], None
        audit = {"unknown_count": None, "unknown_mass_fraction": None,
                 "macro_mass_excess_items": [], "macro_mass_excess_total": None}
    else:
        items, prediction, audit = parsed
    return _same(value, {"raw_outputs": raw, "items": items, "prediction": prediction,
                         "repair_used": repair, "failure": failure, "audit": audit})


def validate_embedding_result(value):
    _object(value, {"vector"})
    if not isinstance(value["vector"], list):
        raise PipelineError("embedding_vector_must_be_a_json_list")
    retrieval._unit_vector(value["vector"])
    return {"vector": [float(v) for v in value["vector"]]}


def _image_metadata(image):
    _object(image, IMAGE_KEYS)
    return {"image_id": retrieval._identifier(image["image_id"]),
            "image_path": vision._path(image["image_path"]),
            "image_sha256": retrieval._hash(image["image_sha256"]),
            "rgb_sha256": retrieval._hash(image["rgb_sha256"])}


def _image_proof(image):
    return {key: image[key] for key in ("image_sha256", "rgb_sha256")}


def describe_and_embed(provider, image, *, stage_runner=None):
    """Independent gallery/query image function, with no labels or fallback.

    image has exactly image_id/image_path/image_sha256/rgb_sha256. The ID and
    declared hashes are private bookkeeping; only encoded pixels enter Sol.
    Return a failed descriptor with embedding=None; the gallery builder must
    block its seal instead of dropping that member. The query caller uses the
    registered whole-query training-median fallback for the same outcome.
    """
    image = _image_metadata(image)
    proof = _image_proof(image)
    prefix = "image-" + fingerprint(proof)[:24]
    descriptor = _run(prefix + ":description",
        {"method": vision.METHOD_VERSION, "image": proof},
        lambda: vision.describe(provider, image["image_path"]),
        validate_description_result, stage_runner)
    if descriptor["failure"] is not None:
        return {"description": descriptor, "embedding": None,
                "repair_used": descriptor["repair_used"], "failure": descriptor["failure"]}

    def embed():
        values = provider.embed([descriptor["embedding_text"]])
        if not isinstance(values, list) or len(values) != 1:
            raise PipelineError("exactly_one_official_embedding_required")
        return {"vector": values[0]}

    embedded = _run(prefix + ":embedding",
        {"embedding_model": "text-embedding-3-large", "dimensions": retrieval.DIMENSIONS,
         "embedding_text": descriptor["embedding_text"]}, embed, validate_embedding_result, stage_runner)
    return {"description": descriptor, "embedding": embedded,
            "repair_used": descriptor["repair_used"], "failure": None}


def _context(query, assets, gallery):
    _object(query, QUERY_KEYS)
    image = _image_metadata({"image_id": query["query_id"],
        **{key: query[key] for key in ("image_path", "image_sha256", "rgb_sha256")}})
    group = retrieval._identifier(query["screening_group_id"])
    _object(assets, ASSET_KEYS)
    if assets["scope"] != "external_train_only":
        raise PipelineError("only_external_training_assets_allowed")
    training_sha = retrieval._hash(assets["training_sha256"])
    indexed = estimator._catalog(assets["catalog"])
    catalog = list(indexed.values())
    _object(assets["fallback"], set(TARGETS))
    fallback = {key: _number(assets["fallback"][key]) for key in TARGETS}
    if fallback["weight"] <= 0:
        raise PipelineError("positive_external_training_fallback_mass_required")
    if not isinstance(gallery, retrieval.GalleryIndex):
        raise PipelineError("gallery_index_required")
    # Includes structural, population, dimension, hash and finite-vector checks.
    if not isinstance(gallery.entries, tuple) or not gallery.entries:
        raise PipelineError("nonempty_gallery_required")
    exclusions = {"train_ids": [image["image_id"]], "screening_group_ids": [group],
                  "image_sha256": [image["image_sha256"]], "rgb_sha256": [image["rgb_sha256"]]}
    retrieval.retrieve(gallery, [1.0] + [0.0] * (retrieval.DIMENSIONS - 1), exclusions)
    entries = {row.train_id: row for row in gallery.entries}
    supports = assets["supports"]
    if not isinstance(supports, dict) or set(supports) != set(entries):
        raise PipelineError("support_and_gallery_populations_must_match_exactly")
    normalized, paths = {}, set()
    for sid in sorted(supports):
        support = supports[sid]
        _object(support, {"image_path", "ingredients"})
        path = vision._path(support["image_path"])
        if path in paths:
            raise PipelineError("duplicate_training_image_path")
        paths.add(path)
        rows = support["ingredients"]
        if not isinstance(rows, list) or not rows:
            raise PipelineError("positive_training_support_ingredients_required")
        ingredients, amounts = [], []
        for row in rows:
            _object(row, {"ingredient_id", "grams"})
            identifier = row["ingredient_id"]
            if not isinstance(identifier, str) or identifier not in indexed:
                raise PipelineError("support_ingredient_absent_from_external_catalog")
            grams = estimator._positive(row["grams"])
            ingredients.append({"ingredient_id": identifier, "grams": grams})
            amounts.append(estimator._amounts(grams, indexed[identifier]["density_per_100g"]))
        estimator._total(amounts)  # Reject invalid support totals before any paid stage.
        normalized[sid] = {"image_path": path, "ingredients": ingredients}
    if image["image_path"] in paths:
        raise PipelineError("query_path_cannot_be_an_external_training_support")
    gallery_sha = fingerprint({"version": gallery.version,
        "entries": [vars(row) for row in gallery.entries], "vectors": gallery.vectors.tolist()})
    return image, exclusions, catalog, fallback, normalized, training_sha, gallery_sha


def _leaves(items, catalog):
    indexed = estimator._catalog(catalog)
    return [{"item_id": item["item_id"], "ingredient_id": item["ingredient_id"], "grams": item["grams"],
             "density": deepcopy(indexed[item["ingredient_id"]]["density_per_100g"]
                                  if item["ingredient_id"] is not None else item["estimated_density"])}
            for item in items]


def infer(provider, query, assets, gallery, *, stage_runner=None):
    """Describe -> official embed -> 12 groups -> visual four -> H contract.

    query: query_id/image_path/image_sha256/rgb_sha256/screening_group_id.
    assets: scope='external_train_only', training_sha256, canonical catalog,
    fallback five-vector, supports keyed by train_id with image_path and positive
    ingredient_id/grams pairs. gallery: retrieval.GalleryIndex. These narrow
    schemas reject query-label fields; no global loaders or dev folds are used.
    """
    image, exclusions, catalog, fallback, supports, train_sha, gallery_sha = _context(query, assets, gallery)
    stages = {}
    audit = {"training_sha256": train_sha, "gallery_sha256": gallery_sha,
             "selected_train_ids": [], "selected_candidate_ids": [],
             "method_fallback_reason": None, "whole_fallback_source": None}
    state = {"method": METHOD_VERSION, "query_id": image["image_id"], "prediction": None,
             "raw_prediction": None, "items": [], "raw_leaves": [], "fallback": False,
             "fallback_reason": None, "method_fallback": False, "native_complete": False,
             "repair_used": False, "failure": None, "status": "pending", "stages": stages, "audit": audit}

    def whole_fallback(stage, reason):
        state.update(prediction=deepcopy(fallback), fallback=True,
                     fallback_reason=stage + ":" + reason, failure=stage + ":" + reason, status="fallback")
        audit["whole_fallback_source"] = "fixed_external_training_official_target_medians"
        return state

    appearance = describe_and_embed(provider, {key: image[key] for key in IMAGE_KEYS}, stage_runner=stage_runner)
    stages["description"] = appearance["description"]
    state["repair_used"] = appearance["repair_used"]
    if appearance["failure"] is not None:
        return whole_fallback("description", appearance["failure"])
    stages["embedding"] = appearance["embedding"]
    vector = appearance["embedding"]["vector"]
    prefix = "query-" + fingerprint({"query_id": image["image_id"], **_image_proof(image)})[:24]
    expected_retrieval = lambda: retrieval.retrieve(gallery, vector, exclusions)
    retrieved = _run(prefix + ":retrieval",
        {"method": retrieval.METHOD_VERSION, "gallery_sha256": gallery_sha,
         "vector_sha256": fingerprint(vector), "exclusions": exclusions, "k": 12},
        expected_retrieval, lambda value: _same(value, expected_retrieval()), stage_runner)
    stages["retrieval"] = retrieved
    by_candidate = {candidate_id: row for candidate_id, row in zip(vision.CANDIDATE_IDS, retrieved)}
    candidates = [{"candidate_id": candidate_id, "image_path": supports[row["train_id"]]["image_path"]}
                  for candidate_id, row in by_candidate.items()]
    rerank_inputs = {"method": vision.METHOD_VERSION, "query": _image_proof(image),
        "candidates": [{"candidate_id": key, "image_sha256": row["image_sha256"], "rgb_sha256": row["rgb_sha256"]}
                       for key, row in by_candidate.items()]}
    reranked = _run(prefix + ":rerank", rerank_inputs,
        lambda: vision.rerank(provider, image["image_path"], candidates), validate_rerank_result, stage_runner)
    stages["rerank"] = reranked
    state["repair_used"] |= reranked["repair_used"]
    if reranked["failure"] is None:
        selected = reranked["selected_ids"]
    else:
        selected = list(vision.CANDIDATE_IDS[:4])
        state["method_fallback"] = True
        audit["method_fallback_reason"] = "rerank:" + reranked["failure"]
    selected_rows = [by_candidate[candidate] for candidate in selected]
    audit["selected_candidate_ids"] = list(selected)
    audit["selected_train_ids"] = [row["train_id"] for row in selected_rows]
    examples = [deepcopy(supports[row["train_id"]]) for row in selected_rows]
    estimate_inputs = {"method": estimator.METHOD_VERSION, "query": _image_proof(image),
        "training_sha256": train_sha, "catalog": catalog,
        "supports": [{"image_sha256": row["image_sha256"], "rgb_sha256": row["rgb_sha256"],
                      "ingredients": supports[row["train_id"]]["ingredients"]} for row in selected_rows]}
    estimated = _run(prefix + ":estimate", estimate_inputs,
        lambda: estimator.infer(provider, image["image_path"], examples, catalog),
        lambda value: validate_estimate_result(value, catalog), stage_runner)
    stages["estimate"] = estimated
    state["repair_used"] |= estimated["repair_used"]
    audit.update(deepcopy(estimated["audit"]))
    if estimated["failure"] is not None:
        return whole_fallback("estimate", estimated["failure"])
    state.update(prediction=deepcopy(estimated["prediction"]), raw_prediction=deepcopy(estimated["prediction"]),
                 items=deepcopy(estimated["items"]), raw_leaves=_leaves(estimated["items"], catalog),
                 native_complete=not state["repair_used"] and not state["method_fallback"],
                 status="method_fallback" if state["method_fallback"] else "ok")
    return state
