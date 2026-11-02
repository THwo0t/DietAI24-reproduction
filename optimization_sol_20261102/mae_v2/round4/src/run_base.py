#!/usr/bin/env python3
"""Round-four acquisition-independent entry points; scoring is a separate step.

No data are downloaded here. The capability probe uses released training only.
Gallery and query phases additionally require the frozen method protocol. A
completed phase verifies existing artifacts without constructing a provider.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import deepcopy
import json
import os
from pathlib import Path
import re
import sys
import threading

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))
from opt_provider import Provider, ProviderStop
from round4.src.artifacts import ArtifactStore, TerminalStageError
from round4.src import context, pipeline, retrieval, vision_stages
from round4.src.trace_provider import TraceProvider
from round4.src.image_guard import ImageGuard, expected_images

NAMESPACE = "external-gallery-r4.1"
RUNS = "round4/runs"


class BatchInterrupted(RuntimeError):
    pass


def event(**value):
    print(json.dumps(value, sort_keys=True, allow_nan=False), flush=True)


def _verify_quick(ctx):
    hashes = ctx["reader"].hashes
    for name in (*context.SOURCE_NAMES, context.DEV_MANIFEST, context.TRAIN + "/freeze.json",
                 "round4/runs/capability/completion.json"):
        context.require(context.digest(context.safe_path(ROOT, name).read_bytes()) == hashes[name],
                        "bound_source_or_manifest_changed")


def _validate_refs(refs):
    context.require(isinstance(refs, list), "invalid_request_references")
    for row in refs:
        context.require(set(row) == {"role", "request_hash", "value_hash", "status", "cache_present_before"},
                        "invalid_request_reference_fields")
        context.require(row["role"] in ("chat", "embedding")
                        and isinstance(row["request_hash"], str)
                        and re.fullmatch(r"[0-9a-f]{64}", row["request_hash"])
                        and type(row["cache_present_before"]) is bool,
                        "invalid_request_reference")
        context.require(row["status"] == "returned" and isinstance(row["value_hash"], str)
                        and re.fullmatch(r"[0-9a-f]{64}", row["value_hash"]),
                        "unsuccessful_request_in_completed_stage")
    return deepcopy(refs)


def stage_runner(store, traced, payloads):
    """Keep request digests outside the scientific stage-result contract."""
    def run(name, inputs, call, validator):
        def invoke():
            mark = traced.mark()
            with traced.expect(expected_images(name, inputs, payloads)):
                result = call()
            return {"result": result, "request_refs": traced.refs_since(mark)}
        def validate(envelope):
            context.require(isinstance(envelope, dict) and set(envelope) == {"result", "request_refs"},
                            "invalid_traced_stage_envelope")
            return {"result": validator(envelope["result"]),
                    "request_refs": _validate_refs(envelope["request_refs"])}
        return store.stage_runner(name, inputs, invoke, validate)["result"]
    return run


def _provider(directory, allow_paid):
    return Provider(directory, allow_paid=allow_paid, namespace=NAMESPACE)


def _workers(value):
    context.require(type(value) is int and 1 <= value <= 4, "workers_must_be_one_through_four")


def _execute(rows, worker, workers):
    _workers(workers)
    out = {}
    stopped = threading.Event()
    def guarded(row):
        if stopped.is_set():
            raise BatchInterrupted("batch_stopped_before_queued_work")
        try:
            return worker(row)
        except BaseException:
            stopped.set()
            raise
    # Outstanding calls finish normally if another worker fails; their exact
    # successful stage responses stay resumable. Never convert batch failure
    # into whole-query nutritional fallbacks.
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(guarded, row): row for row in rows}
        try:
            for future in as_completed(futures):
                key, result = future.result()
                context.require(key not in out, "duplicate_worker_record")
                out[key] = result
                event(stage="progress", completed=len(out), expected=len(rows))
        except BaseException:
            for future in futures:
                future.cancel()
            raise
    return out


def _gallery_store(ctx):
    return ArtifactStore(ROOT / RUNS / "J_gallery",
        {**ctx["binding"], "phase": "gallery"}, [r["train_id"] for r in ctx["entries"]],
        verify_sources=lambda: _verify_quick(ctx), root=ROOT / "round4")


def _gallery_index(ctx, records):
    expected = {r["train_id"] for r in ctx["entries"]}
    context.require(set(records) == expected, "gallery_record_population_changed")
    vectors = {}
    for row in ctx["entries"]:
        record = records[row["train_id"]]
        context.require(record.get("metadata") == row, "gallery_metadata_changed")
        result = record["result"]
        context.require(result.get("failure") is None and result.get("embedding") is not None,
                        "incomplete_gallery_result")
        # Reparse persisted descriptions, rather than trusting only its JSON
        # shape or a vector's numeric validity.
        context.require(vision_stages.embedding_text(result["description"]["parsed"])
                        == result["description"]["embedding_text"], "gallery_description_changed")
        vectors[row["train_id"]] = result["embedding"]["vector"]
    return retrieval.build_index(ctx["entries"], vectors)


def gallery(*, allow_paid=False, workers=4):
    _workers(workers)
    ctx = context.load_context(ROOT)
    store = _gallery_store(ctx)
    if (ROOT / RUNS / "J_gallery" / "completion.json").exists():
        records = store.verify_completed()
        _gallery_index(ctx, records)
        return {"status": "gallery_verified", "n": len(records), "provider_constructed": False}
    context.require(allow_paid, "explicit_paid_flag_required")
    store.initialize()
    provider = _provider(ROOT / "round4/provider/J_gallery", allow_paid)
    traced = ImageGuard(TraceProvider(provider))
    runner = stage_runner(store, traced, ctx["payloads"])
    try:
        def work(row):
            train_id = row["train_id"]
            metadata = {"image_id": train_id, "image_path": ctx["assets"]["supports"][train_id]["image_path"],
                        "image_sha256": row["image_sha256"], "rgb_sha256": row["rgb_sha256"]}
            result = pipeline.describe_and_embed(traced, metadata, stage_runner=runner)
            if result["failure"] is not None:
                raise TerminalStageError("gallery_description_contract_failed")
            return train_id, {"metadata": row, "result": result}
        records = _execute(ctx["entries"], work, workers)
        _gallery_index(ctx, records)
        ctx["reader"].unchanged()
        store.finalize(records)
    finally:
        provider.close()
    return {"status": "gallery_complete", "n": len(records), "validation_opened": False}


def _base_store(ctx):
    gallery_store = _gallery_store(ctx)
    gallery_records = gallery_store.verify_completed()
    index = _gallery_index(ctx, gallery_records)
    complete = context.safe_path(ROOT, RUNS + "/J_gallery/completion.json").read_bytes()
    def verify():
        _verify_quick(ctx)
        context.require(context.safe_path(ROOT, RUNS + "/J_gallery/completion.json").read_bytes() == complete,
                        "gallery_completion_changed")
    ctx["verify_gallery"] = gallery_store.verify_completed
    store = ArtifactStore(ROOT / RUNS / "J",
        {**ctx["binding"], "phase": "development_base", "gallery_completion_sha256": context.digest(complete)},
        [r["sample_id"] for r in ctx["rows"]], verify_sources=verify, root=ROOT / "round4")
    return store, index


def base(*, allow_paid=False, workers=4, verify_only=False):
    _workers(workers)
    ctx = context.load_context(ROOT)
    store, index = _base_store(ctx)
    if (ROOT / RUNS / "J" / "completion.json").exists() or verify_only:
        records = store.verify_completed()
        return {"status": "base_verified", "n": len(records), "records": records,
                "provider_constructed": False, "validation_opened": False}
    context.require(allow_paid, "explicit_paid_flag_required")
    store.initialize()
    provider = _provider(ROOT / "round4/provider/J", allow_paid)
    traced = ImageGuard(TraceProvider(provider))
    runner = stage_runner(store, traced, ctx["payloads"])
    by_id = {r["sample_id"]: r for r in ctx["rows"]}
    try:
        def work(query):
            result = pipeline.infer(traced, query, ctx["assets"], index, stage_runner=runner)
            row = by_id[query["query_id"]]
            record = {k: row[k] for k in ("sample_id", "dataset", "group_id", "fold")}
            record.update(result)
            record.update({"final_codes": [], "primary_code": None})
            return row["sample_id"], record
        records = _execute(ctx["queries"], work, workers)
        ctx["reader"].unchanged()
        ctx["verify_gallery"]()
        store.finalize(records)
    finally:
        provider.close()
    return {"status": "base_complete_unscored", "n": len(records), "validation_opened": False}


def preflight():
    ctx = context.load_context(ROOT)
    return {"status": "offline_preflight_pass", "train_images": len(ctx["entries"]),
            "query_images": len(ctx["queries"]), "query_groups": context.DEV_GROUPS,
            "api_calls": 0, "validation_opened": False}


def main(argv=None):
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("preflight", "gallery", "base", "verify"))
    parser.add_argument("--allow-paid", action="store_true")
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args(argv)
    try:
        if args.phase == "preflight":
            result = preflight()
        elif args.phase == "gallery":
            result = gallery(allow_paid=args.allow_paid, workers=args.workers)
        else:
            result = base(allow_paid=args.allow_paid, workers=args.workers, verify_only=args.phase == "verify")
        event(**{k: v for k, v in result.items() if k != "records"})
        return 0
    except (Exception, ProviderStop) as error:
        # No third-party body, URL query, key, image path or reference label is
        # printed by the command boundary.
        event(status="stopped", error_type=type(error).__name__)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
