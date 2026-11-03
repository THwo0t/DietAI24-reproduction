"""Exact, read-only M0 import for N; no label loader or service construction."""
from contextlib import redirect_stdout
from copy import deepcopy
from io import StringIO
import json
from pathlib import Path

from opt_provider import ROOT, fingerprint, sha
from round4.src.artifacts import ArtifactStore, decode, key_path
from context_m import runtime_context as m_context, source_pins as m_source_pins
from run_m import record_name, run as verify_m
from pipeline_v2 import ComponentPipeline, _digest

M = ROOT / "round7"
M_FREEZE_SHA256 = "b2d832529ed8453d2c5d9bebf645e8716f3d39185e0e3070e78cd4b3b486261b"


def require(ok, error):
    if not ok:
        raise ValueError(error)


def stage_raw(store, name):
    """Only after full parent replay/seal verification, never arbitrary paths."""
    value = store._json("stages/" + key_path(name) + "/result.json")
    require(set(value) == {"kind", "raw", "parsed"} and value["kind"] == "result"
            and value["raw"] == value["parsed"], "N_import_stage_envelope_changed")
    return deepcopy(value["parsed"])


def stage_value(store, name):
    envelope = stage_raw(store, name)
    require(set(envelope) == {"result", "request_refs"}, "N_import_scientific_envelope_changed")
    return deepcopy(envelope["result"])


def source_pair(store, row):
    name = record_name("M0", row)
    if row["dataset"] == "nutrition5k":
        old = stage_raw(store, name + "-historical")
        return old["identity"], old["portion"]
    return stage_value(store, name + "-identity"), stage_value(store, name + "-quantity")


def check_pair(pipeline, row, identity, portion, record):
    """Verify old code/gram join before deliberately revaluing it under N."""
    require(all(record[k] == row[k] for k in ("sample_id", "dataset", "group_id", "fold")),
            "N_import_record_population_changed")
    require(identity.get("status") == "ok" and portion.get("status") == "ok"
            and record.get("fallback") is False, "N_import_complete_M0_required")
    pipeline._checked_identity(ROOT / row["image_path"], identity)
    masses = pipeline._checked_base_masses(identity, portion)
    recomputed = pipeline._aggregate(identity, masses, [])["prediction"]
    require(recomputed == portion["prediction"] == record["prediction"] == record["raw_prediction"],
            "N_import_nutrition_or_mass_changed")
    require(identity["parents"] == record["parents"], "N_import_physical_parent_changed")
    return {"identity": deepcopy(identity), "portion": deepcopy(portion), "baseline_record": deepcopy(record),
            "identity_sha256": _digest(identity), "portion_sha256": _digest(portion)}


def prepare_imports():
    require(sha(M / "prepared/freeze.json") == M_FREEZE_SHA256, "N_wrong_M_freeze")
    for path in (M / "runs/development/completion.json", M / "runs/scoring/results.json",
                 M / "development_checkpoint.json", M / "launch/automatic_followup.json"):
        require(path.is_file() and path.resolve() == path, "N_complete_scored_M_required")
    follower = decode((M / "launch/automatic_followup.json").read_bytes())
    require(follower.get("status") == "development_scored", "N_M_follower_incomplete")
    ctx = m_context()
    with redirect_stdout(StringIO()):
        replay = verify_m(ctx, allow_paid=False)
    require(replay.get("completed_replay") is True and replay.get("provider_constructed") is False
            and replay.get("pairs") == 183, "N_M_zero_Provider_replay_failed")
    names = [record_name(p, r) for r in ctx.rows for p in ("M0", "M")] + ["service-proof"]
    store = ArtifactStore(M / "runs/development", ctx.binding, names,
                          verify_sources=ctx.verify_sources, root=M)
    records = store.verify_completed()
    catalog = ctx.catalog
    def forbidden(*args, **kwargs):
        raise AssertionError("N_upstream_import_must_not_infer")
    pipeline = ComponentPipeline(forbidden, forbidden, catalog, ctx.retriever)
    imported = {}
    for row in ctx.rows:
        sid, name = row["sample_id"], record_name("M0", row)
        identity, portion = source_pair(store, row)
        imported[sid] = check_pair(pipeline, row, identity, portion, records[name])
    require(store.verify_completed() == records and m_source_pins() == ctx.binding["source_files"],
            "N_M_changed_during_import")
    return {"schema_version": 1, "rows": deepcopy(ctx.rows), "records": imported,
        "fallbacks": deepcopy(ctx.fallbacks), "proof": {
            "M_freeze_sha256": M_FREEZE_SHA256,
            "M_completion_sha256": sha(M / "runs/development/completion.json"),
            "M_records_sha256": fingerprint(records),
            "M_service_proof_sha256": fingerprint(records["service-proof"]),
            "M_source_sha256": deepcopy(ctx.binding["source_files"]),
            "importer_sha256": sha(Path(__file__)), "catalog_sha256": ctx.binding["catalog_sha256"],
            "manifest_sha256": ctx.binding["manifest_sha256"],
            "rows_sha256": fingerprint(ctx.rows), "complete_images": 183,
            "M_replay_provider_constructed": False, "query_references_loaded": False,
            "validation_opened": False, "new_api_calls": 0}}


def verify_imports(bundle, catalog):
    """Runtime source/image/parent seal checks, without repeating old inference."""
    require(bundle.get("schema_version") == 1, "N_import_version_changed")
    proof, rows, imported = bundle["proof"], bundle["rows"], bundle["records"]
    require({k: proof[k] for k in ("complete_images", "M_replay_provider_constructed",
            "query_references_loaded", "validation_opened", "new_api_calls")} == {
            "complete_images": 183, "M_replay_provider_constructed": False,
            "query_references_loaded": False, "validation_opened": False, "new_api_calls": 0},
            "N_import_audit_claim_changed")
    require(sha(M / "prepared/freeze.json") == proof["M_freeze_sha256"] == M_FREEZE_SHA256,
            "N_import_frozen_M_changed")
    require(m_source_pins() == proof["M_source_sha256"] and sha(Path(__file__)) == proof["importer_sha256"],
            "N_import_source_changed")
    require(sha(ROOT / "data/catalog.json") == proof["catalog_sha256"]
            and sha(ROOT / "data/cohorts/dev.jsonl") == proof["manifest_sha256"]
            and fingerprint(rows) == proof["rows_sha256"], "N_import_assets_changed")
    actual_rows = [decode(line) for line in (ROOT / "data/cohorts/dev.jsonl").read_text().splitlines()]
    require(actual_rows == rows and len(rows) == 183 and len(imported) == 183
            and set(imported) == {r["sample_id"] for r in rows}, "N_import_population_changed")
    frozen = decode((M / "prepared/freeze.json").read_bytes())
    require(proof["M_source_sha256"] == frozen["source_files"], "N_import_unfrozen_M_sources")
    require(catalog == decode((ROOT / "data/catalog.json").read_bytes()), "N_import_caller_catalog_changed")
    names = [record_name(p, r) for r in rows for p in ("M0", "M")] + ["service-proof"]
    store = ArtifactStore(M / "runs/development", frozen, names,
        verify_sources=lambda: m_source_pins() == proof["M_source_sha256"], root=M)
    records = store.verify_completed()
    require(sha(M / "runs/development/completion.json") == proof["M_completion_sha256"]
            and fingerprint(records) == proof["M_records_sha256"]
            and fingerprint(records["service-proof"]) == proof["M_service_proof_sha256"],
            "N_parent_completed_records_changed")
    def forbidden(*args, **kwargs): raise AssertionError("N_import_verifier_must_not_infer")
    pipeline = ComponentPipeline(forbidden, forbidden, catalog, None)
    for row in rows:
        image = ROOT / row["image_path"]
        require(image.resolve() == image and sha(image) == row["image_sha256"], "N_import_image_changed")
        old = imported[row["sample_id"]]
        actual_identity, actual_portion = source_pair(store, row)
        require(old["identity"] == actual_identity and old["portion"] == actual_portion,
                "N_import_differs_from_actual_M0_stage")
        require(old["identity_sha256"] == _digest(old["identity"])
                and old["portion_sha256"] == _digest(old["portion"]), "N_import_value_changed")
        require(check_pair(pipeline, row, old["identity"], old["portion"],
                           records[record_name("M0", row)]) == old, "N_import_recomputation_changed")
    require(bundle["fallbacks"]["manifest_sha256"] == proof["manifest_sha256"]
            and bundle["fallbacks"] == decode((M / "prepared/fallbacks.json").read_bytes()),
            "N_frozen_other_fold_fallback_changed")
    return True
