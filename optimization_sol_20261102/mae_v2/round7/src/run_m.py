#!/usr/bin/env python3
"""Prepare, freeze, run, verify and score the paired common M development study."""
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor, as_completed
import argparse
import json
from pathlib import Path
import sys
import threading

BASE = Path(__file__).resolve().parents[2]
sys.dont_write_bytecode = True
sys.path[:0] = [str(BASE), str(BASE / "src"), str(BASE / "round7/src")]

from opt_provider import ROOT, fingerprint, sha
from opt_pipeline import encode_image
from round4.src.artifacts import ArtifactStore, key_path
from context_m import ROUND, PREPARED, assets, freeze, load, manifest, prepare, runtime_context, write_once
from historical_m import checked_path, verify_imported_c
from records_m import core_record
from runtime_m import LazyTrace
from service_m import Replay, audit_state, completion_proof, logs
from shared_accounting import SharedAccountingPipeline, IDENTITY_CONFIG, QUANTITY_CONFIG, coding_snapshot


def event(**value): print(json.dumps(value, allow_nan=False), flush=True)


def record_name(profile, row):
    return profile + "-" + fingerprint(row["sample_id"])[:32]


def run(ctx, allow_paid=False):
    names = [record_name(p, r) for r in ctx.rows for p in ["M0", "M"]] + ["service-proof"]
    store = ArtifactStore(ROUND / "runs/development", ctx.binding, names,
                          verify_sources=ctx.verify_sources, root=ROUND)
    complete = (store.directory / "completion.json").is_file()
    saved = store.verify_completed() if complete else None
    if not complete: store.initialize()
    audit_state(ROOT, allow_incomplete=not complete)
    lazy = LazyTrace(ctx.embeddings, allow_paid=allow_paid)
    records, refs = {}, {}
    guard = threading.Lock()

    def cached_stage(name, inputs, call, validator):
        if complete:
            # Whole-run inventory was checked once above. This private helper
            # is frozen with ArtifactStore and performs read-only per-stage
            # intent/seal/reparse checks without O(stages^2) inventory scans.
            return store._cached("stages/" + key_path(name), store._stage_intent(name, inputs), validator)
        return store.stage_runner(name, inputs, call, validator)

    def scientific_stage(name, image, inputs, call):
        def pipeline(chat, embed):
            return SharedAccountingPipeline(chat, embed, ctx.catalog, ctx.retriever)
        def invoke():
            cursor = lazy.mark()
            with lazy.expect(encode_image(image, "native")):
                result = call(pipeline(lazy.chat, lazy.embed))
            return {"result": result, "request_refs": lazy.since(cursor)}
        def validate(envelope):
            if set(envelope) != {"result", "request_refs"}: raise ValueError("M_stage_envelope_changed")
            replay = Replay(ROOT, ctx.embeddings, envelope["request_refs"])
            result = call(pipeline(replay.chat, replay.embed))
            replay.finish()
            if result != envelope["result"]: raise ValueError("M_stage_scientific_reparse_changed")
            return envelope
        envelope = cached_stage(name, inputs, invoke, validate)
        with guard: refs[name] = deepcopy(envelope["request_refs"])
        return envelope["result"]

    def fixed(name, inputs, value):
        def validate(saved_value):
            if saved_value != value: raise ValueError("M_fixed_stage_changed")
            return saved_value
        return cached_stage(name, inputs, lambda: deepcopy(value), validate)

    def coding_stage(profile, row, identity):
        name = record_name(profile, row) + "-coding"
        return fixed(name, {"identity_hash": fingerprint(identity)}, coding_snapshot(identity))

    def one(row):
        image = checked_path(ROOT, row["image_path"])
        inputs = {"image_sha256": row["image_sha256"], "row_sha256": fingerprint(row)}
        fallback = ctx.fallbacks["vectors"][row["dataset"]][str(row["fold"])]
        base_name = record_name("M0", row)
        if row["dataset"] == "nutrition5k":
            imported = ctx.imported["records"][row["sample_id"]]
            identity, portion = imported["identity"], imported["portion"]
            fixed(base_name + "-historical", inputs, imported)
            coding = coding_stage("M0", row, identity)
        else:
            layout = scientific_stage(base_name + "-layout", image, inputs, lambda p: p.layout(image))
            identity = scientific_stage(base_name + "-identity", image,
                {**inputs, "layout_hash": fingerprint(layout)},
                lambda p: p.identify(image, IDENTITY_CONFIG, layout=layout))
            coding = coding_stage("M0", row, identity)  # must precede quantity
            portion = scientific_stage(base_name + "-quantity", image,
                {**inputs, "identity_hash": fingerprint(identity), "coding_hash": fingerprint(coding)},
                lambda p: p.portion(image, identity, QUANTITY_CONFIG))
        base_record = core_record(row, identity, portion, fallback, coding)
        fixed(base_name + "-record", inputs, base_record)
        base_layout = identity.get("layout_result")
        if base_layout is None: raise ValueError("M_shared_layout_missing")
        m_name = record_name("M", row)
        m_identity = scientific_stage(m_name + "-identity", image,
            {**inputs, "layout_hash": fingerprint(base_layout), "child_banks_hash": fingerprint(identity.get("candidates", {}))},
            lambda p: p.identify_candidate(image, base_layout, identity.get("candidates", {})))
        m_coding = coding_stage("M", row, m_identity)
        m_portion = scientific_stage(m_name + "-quantity", image,
            {**inputs, "identity_hash": fingerprint(m_identity), "coding_hash": fingerprint(m_coding)},
            lambda p: p.portion_candidate(image, m_identity))
        m_record = core_record(row, m_identity, m_portion, fallback, m_coding)
        fixed(m_name + "-record", inputs, m_record)
        with guard:
            records[base_name], records[m_name] = base_record, m_record
            event(completed_pairs=len(records) // 2, total_pairs=len(ctx.rows), dataset=row["dataset"])

    try:
        if complete:
            for row in ctx.rows: one(row)
        else:
            with ThreadPoolExecutor(max_workers=2) as pool:
                futures = [pool.submit(one, row) for row in ctx.rows]
                try:
                    for future in as_completed(futures): future.result()
                except BaseException:
                    for future in futures: future.cancel()
                    raise
        verify_imported_c(ROOT, ctx.imported, [r for r in ctx.rows if r["dataset"] == "nutrition5k"])
        proof = completion_proof(ROOT, ctx.embeddings, refs)
        fixed("completion-service-proof", {"stage_refs_hash": fingerprint(refs)}, proof)
        records["service-proof"] = proof
        ctx.verify_sources()
        if complete:
            if saved != records: raise ValueError("M_completed_records_changed")
            store.verify_completed()
        else:
            store.finalize(records)
        return {"status": "completed", "pairs": len(ctx.rows), "completed_replay": complete,
                "provider_constructed": lazy.provider is not None, "service_counts": proof["counts"]}
    finally: lazy.close()


def score_completed():
    # Scoring is a separate phase, entered only after the entire paired run seals.
    from cohorts_v2 import load_dev
    from diagnostics_v2 import asa24_exact_intersection
    from scoring_m import score, select
    ctx = runtime_context()
    names = [record_name(p, r) for r in ctx.rows for p in ["M0", "M"]] + ["service-proof"]
    store = ArtifactStore(ROUND / "runs/development", ctx.binding, names,
                          verify_sources=ctx.verify_sources, root=ROUND)
    records = store.verify_completed()
    rows, labels = load_dev()
    if rows != ctx.rows or sha(ROOT / "data/cohorts/dev_labels.json") != ctx.fallbacks["labels_sha256"]:
        raise ValueError("M_score_references_changed")
    results = {p: score(rows, labels, [records[record_name(p, r)] for r in rows], ctx.catalog) for p in ["M0", "M"]}
    common = asa24_exact_intersection(rows, labels, results["M0"]["predictions"], results["M"]["predictions"],
                                     draws=10000, seed=20261102)
    selection = select(results)
    from opt_metrics import evaluate
    median_rows = []
    for row in rows:
        fallback = ctx.fallbacks["vectors"][row["dataset"]][str(row["fold"])]
        median_rows.append({"sample_id": row["sample_id"], "dataset": row["dataset"],
            "prediction": fallback, "final_codes": [], "primary_code": None,
            "native_complete": False, "fallback": True,
            "e2e": {"prediction": fallback, "fallback": True}, "conditional": None})
    medians = evaluate(rows, labels, median_rows)["datasets"]
    token_usage = {}
    for role in ["chat", "embedding"]:
        history = logs(ROOT, role)
        totals = {k: sum((r.get("usage") or {}).get(k, 0) or 0 for r in history)
                  for k in ["prompt_tokens", "completion_tokens", "total_tokens"]}
        totals.update(transmissions=len(history), errors=sum(r.get("status") != 200 for r in history),
            reasoning_tokens=sum(((r.get("usage") or {}).get("completion_tokens_details") or {}).get("reasoning_tokens", 0) or 0 for r in history))
        token_usage[role] = totals
    output = {"arms": {p: {k: v for k, v in result.items() if k != "predictions"} for p, result in results.items()},
        "selection": selection, "common_exact": common, "service_proof": records["service-proof"],
        "pure_median_baseline": {"asa24_e2e": medians["asa24"]["e2e"], "nutrition5k": medians["nutrition5k"]["primary"]},
        "new_service_usage": token_usage,
        "cost_notice": "Money unverified; requests/tokens only. Reasoning is included in completion. Imported historical work is separate.",
        "scope": "development only; original test and sealed validation not used to select this method"}
    write_once(ROUND / "runs/scoring/results.json", output)
    write_once(ROUND / "development_checkpoint.json", {k: v for k, v in output.items() if k != "service_proof"})
    return {"selection": selection, "failed_checks": {p: r["tolerance"]["failed_checks"] for p, r in results.items()}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=["prepare", "freeze", "preflight", "base", "verify", "score"])
    parser.add_argument("--allow-paid", action="store_true")
    args = parser.parse_args()
    if args.phase == "prepare": result = prepare()
    elif args.phase == "freeze": result = {"freeze_hash": fingerprint(freeze())}
    elif args.phase == "preflight":
        ctx = runtime_context()
        result = {"rows": len(ctx.rows), "raw_c_import": len(ctx.imported["records"]),
                  "service": audit_state(ROOT), "paid_requests": 0, "labels_loaded": False}
    elif args.phase == "base":
        if not args.allow_paid and not (ROUND / "runs/development/completion.json").is_file():
            raise ValueError("M_explicit_allow_paid_required")
        result = run(runtime_context(), allow_paid=args.allow_paid)
    elif args.phase == "verify":
        if not (ROUND / "runs/development/completion.json").is_file(): raise ValueError("M_run_not_complete")
        result = run(runtime_context(), allow_paid=False)
    else: result = score_completed()
    event(**result)


if __name__ == "__main__":
    try: main()
    except BaseException as exc:
        event(status="stopped", error_type=type(exc).__name__)
        raise SystemExit(1)
