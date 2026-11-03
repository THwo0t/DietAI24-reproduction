#!/usr/bin/env python3
"""Aggregate-only K posthoc diagnostics after complete base AND scoring seals.

Never call the scorer, fit parameters, select a profile, or construct a Provider.
The existing base verifier can reread bound images for integrity. This adapter
does not open images or traverse arbitrary paths found in an artifact binding.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import json
import os
from pathlib import Path
import sys

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "src")]
from round4.diagnostics import analyze_j as math_core
from round4.src.artifacts import ArtifactStore, decode, fingerprint
from round5.src import score_component as k_score

scorer = k_score.scorer
OUTPUT = "round5/diagnostics/results/K"
SCOPE = "posthoc_development_diagnostic_not_candidate_selection_or_acceptance"
INGREDIENTS = math_core.INGREDIENTS
INGREDIENTS_SHA256 = math_core.INGREDIENTS_SHA256
CATALOG = math_core.CATALOG
J_OUTPUT = math_core.OUTPUT
J_COMPLETION = J_OUTPUT + "/completion.json"
J_COMPLETION_SHA256 = "7212c0eaf8771aeedae85faa411268275aba98d5dce0c355a3877dc485452658"
J_BASE_SHA256 = "11fc4c720a3bd9c5b59cd5f3cca8fb291b0865e9ebc8e32e8643498d3ae22b1f"
MATH_PINS = {
    "round4/diagnostics/analyze_j.py": "bc6b09556dca481a0540ac12b2d61409a3ece1e5ffaef7fe93255b831fa16543",
    "src/opt_metrics.py": "15d71fd2c2379f7f723707cddfeb2e2868c0dd84b027edd12ef9185303a1e63e",
}
SOURCES = ("round5/tools/diagnose_k.py", "round5/tools/test_diagnose_k.py", *MATH_PINS)
DIAGNOSTIC_PROTOCOL = {
    "version": 1, "candidate": "K", "scope": SCOPE, "population_n": 84,
    "functions": ["analyze_j.true_weight_oracle", "analyze_j.decompose", "analyze_j.aggregate_decomposition"],
    "prerequisites": ["complete_zero_provider_K_base", "exact_K_scoring_seal", "pinned_J_diagnostic_seal"],
    "oracle": "all_rows_true_weight_divided_by_raw_predicted_weight; nonpositive_weight_is_invalid",
    "comparison": "descriptive_raw_K_vs_sealed_raw_J_aggregates; no_selection",
    "bootstrap_replicates": 0, "calibration_refitted": False,
}
Inputs = k_score.Inputs
verified_base = k_score._verified
DiagnosticError = math_core.DiagnosticError
require = math_core.require


def _completed_score(reader, verified):
    """Rebuild the existing score binding without opening its pinned labels."""
    for name in k_score.SOURCE_NAMES:
        reader.read(name)
    external = k_score._external_binding(reader, verified)
    baseline, baseline_store = k_score._baseline(reader)
    rows = scorer._manifest(reader.read(scorer.MANIFEST))
    n5, _, _ = scorer._predictions(rows, verified["records"], decode(reader.read(scorer.PRESERVED)))
    for record in verified["records"].values():
        math_core.vector(record["prediction"])  # Zero/NaN cannot silently drop a row.
    binding = {
        "schema_version": 1, "candidate": "K", "phase": "development_component_scoring",
        "scope": k_score.SCOPE, "calibration_applied": False, "validation_opened": False,
        "bootstrap": scorer.BOOTSTRAP, "seed": scorer.SEED,
        "base_completion_sha256": verified["completion_sha256"],
        "base_records_sha256": fingerprint(verified["records"]), "external_training_proof": external,
        "raw_J_scoring_completion_sha256": reader.hashes[k_score.BASELINE_COMPLETION],
        "source_sha256": {name: reader.hashes[name] for name in k_score.SOURCE_NAMES},
        "input_sha256": {**reader.hashes, scorer.LABELS: k_score.PINNED_INPUTS[scorer.LABELS]},
    }
    store = ArtifactStore(ROOT / k_score.OUTPUT, binding, ["metrics"],
                          verify_sources=reader.unchanged, root=ROOT / "round5")
    saved = store.verify_completed()["metrics"]  # Missing/partial completion fails here.
    reader.read(k_score.OUTPUT + "/completion.json")
    require(saved.get("candidate") == "K" and saved.get("scope") == k_score.SCOPE
            and saved.get("calibration_applied") is False and saved.get("validation_opened") is False
            and saved.get("raw_j") == baseline
            and saved["nutrition5k"]["primary"]["n"] == 84,
            "completed_raw_K_scoring_scope_changed")
    return rows, n5, saved, external, (store, baseline_store)


def _completed_j_diagnostic(reader, score, catalog_hash):
    reader.read(J_COMPLETION)
    require(reader.hashes[J_COMPLETION] == J_COMPLETION_SHA256, "pinned_J_diagnostic_completion_changed")
    intent = decode(reader.read(J_OUTPUT + "/intent.json"))
    binding = intent.get("binding", {})
    require(binding.get("phase") == "posthoc_service_continuation_diagnostic"
            and binding.get("scope") == SCOPE and binding.get("base_completion_sha256") == J_BASE_SHA256
            and binding.get("ingredient_source_sha256") == INGREDIENTS_SHA256
            and all(binding.get("input_sha256", {}).get(name) == sha for name, sha in MATH_PINS.items()),
            "pinned_J_diagnostic_provenance_changed")
    store = ArtifactStore(ROOT / J_OUTPUT, binding, ["aggregate"],
                          verify_sources=reader.unchanged, root=ROOT / "round4/diagnostics")
    saved = store.verify_completed()["aggregate"]
    require(saved.get("scope") == SCOPE and saved.get("candidate_source") == "J_service_continuation"
            and saved.get("n") == 84 and saved.get("groups") == 78
            and saved.get("training_catalog_sha256") == catalog_hash
            and saved.get("training_catalog_size") == math_core.CATALOG_SIZE
            and saved.get("validation_opened") is False and saved.get("new_profile_selected") is False
            and saved.get("raw_point_metrics") == score["raw_j"]["nutrition5k"]["primary"]["metrics"]
            and saved.get("decomposition", {}).get("population_n") == 84,
            "sealed_J_diagnostic_population_or_scope_changed")
    return saved, store


def mechanism_values(aggregate):
    """Fixed projections of existing aggregates, with explicit denominators."""
    value = aggregate["decomposition"]
    mass = value["mass_totals_on_decomposable_rows"]
    splits = value["omitted_reference_catalog_availability"]["totals_on_decomposable_rows"]
    available = mass.get("reference_g", 0) - splits.get("catalog_absent_reference_id_g", 0)
    rates = value["mass_micro_rates_on_decomposable_rows"]
    return {
        "population_n": value["population_n"], "decomposable_n": value["decomposable_n"],
        "whole_fallback_n": value["whole_fallback_n"],
        "available_id_reference_mass_fraction": mass["reference_mass_with_present_id_g"] / available if available > 0 else None,
        "present_id_all_reference_mass_fraction": rates["present_id_reference_mass_fraction"] if rates else None,
        "exact_id_overlap_reference_fraction": rates["exact_id_overlap_reference_fraction"] if rates else None,
        "shared_id_absolute_mass_error_g_per_population_row":
            (mass["shared_id_under_g"] + mass["shared_id_over_g"]) / value["population_n"] if mass else None,
        "shared_id_net_mass_error_mean_absolute_g":
            value["components_all_rows"]["weight"]["shared_id_mass"]["mean_absolute"] if mass else None,
        "true_weight_oracle_fat_mae": aggregate["true_weight_oracle_point_metrics"]["fat"]["mae"],
        "true_weight_oracle_protein_mae": aggregate["true_weight_oracle_point_metrics"]["protein"]["mae"],
    }


def run():
    verified = verified_base()  # Full K replay/service proof, before any reader exists.
    require(isinstance(verified.get("records"), dict) and len(verified["records"]) == 84,
            "all_84_base_records_required")
    reader = Inputs(ROOT)
    rows, n5, saved_score, proof, stores = _completed_score(reader, verified)
    for name in SOURCES:
        reader.read(name)
        require(name not in MATH_PINS or reader.hashes[name] == MATH_PINS[name], "original_math_source_changed")
    catalog_hash = verified["binding"].get("input_sha256", {}).get(CATALOG)
    catalog = decode(reader.read(CATALOG))
    require(reader.hashes[CATALOG] == catalog_hash, "base_bound_training_catalog_changed")
    catalog_ids = {item["ingredient_id"] for item in catalog["ingredients"]}
    require(catalog.get("schema_version") == 1
            and catalog.get("scope") == "accepted_external_training_only_domain_catalog"
            and len(catalog["ingredients"]) == len(catalog_ids) == math_core.CATALOG_SIZE,
            "bound_training_catalog_population_changed")
    old, old_store = _completed_j_diagnostic(reader, saved_score, catalog_hash)
    binding = {
        "phase": "posthoc_component_diagnostic", "candidate": "K", "scope": SCOPE,
        "diagnostic_protocol": DIAGNOSTIC_PROTOCOL, "diagnostic_protocol_sha256": fingerprint(DIAGNOSTIC_PROTOCOL),
        "source_sha256": {name: reader.hashes[name] for name in SOURCES},
        "external_training_proof": proof, "base_completion_sha256": verified["completion_sha256"],
        "base_records_sha256": fingerprint(verified["records"]),
        "input_sha256": {**reader.hashes, scorer.LABELS: k_score.PINNED_INPUTS[scorer.LABELS],
                         INGREDIENTS: INGREDIENTS_SHA256},
    }
    # Use round5 as the existing scope root; ArtifactStore creates private output
    # directories only on first finalize, never during read-only verification.
    store = ArtifactStore(ROOT / OUTPUT, binding, ["aggregate"],
                          verify_sources=reader.unchanged, root=ROOT / "round5")
    complete = (ROOT / OUTPUT / "completion.json").exists()
    saved = store.verify_completed() if complete else None
    labels = decode(reader.read(scorer.LABELS))
    require(isinstance(labels, dict) and set(labels) == {row["sample_id"] for row in rows},
            "pinned_development_label_population_changed")
    indexed = {row["sample_id"]: row for row in n5}
    labels = {sid: labels[sid] for sid in indexed}
    scorer.metrics._training(n5, labels)
    metadata = decode(reader.read(INGREDIENTS))
    require(reader.hashes[INGREDIENTS] == INGREDIENTS_SHA256, "pinned_development_ingredients_changed")
    reference = {row["sample_id"]: row for row in metadata["records"]}
    require(len(metadata["records"]) == len(reference) == 84 and set(reference) == set(indexed)
            and all(reference[sid].get("split") == "dev"
                    and all(reference[sid].get(key) == row[key] for key in ("group_id", "fold"))
                    for sid, row in indexed.items()), "development_ingredient_population_changed")
    records = verified["records"]
    oracle = math_core.true_weight_oracle(records, labels)
    def point(values):
        return scorer.metrics.evaluate(n5, labels, list(values.values()), bootstrap=0,
            seed=scorer.SEED)["datasets"]["nutrition5k"]["primary"]["metrics"]
    raw_point, oracle_point = point(records), point(oracle)
    require(raw_point == saved_score["nutrition5k"]["primary"]["metrics"],
            "raw_K_point_metrics_differ_from_completed_scoring")
    decomposition = math_core.aggregate_decomposition([
        math_core.decompose(records[sid], reference[sid]["ingredients"], labels[sid]["truth"], catalog_ids)
        for sid in indexed])
    result = {
        "schema_version": 1, "scope": SCOPE, "candidate_source": "K", "n": 84, "groups": 78,
        "training_catalog_size": len(catalog_ids), "training_catalog_sha256": catalog_hash,
        "raw_point_metrics": raw_point, "true_weight_oracle_point_metrics": oracle_point,
        "raw_J_point_metrics": deepcopy(old["raw_point_metrics"]), "decomposition": decomposition,
        "definitions": {
            "raw": "Unchanged K totals, including every whole fallback; no K calibration is applied.",
            "oracle": "All 84 query truths independently set true_weight/raw_predicted_weight; all five totals scale. Nondeployable, not calibration or an attainable bound; invalid weight rejects all rows.",
            "available_coverage": "Present exact-ID reference mass divided by reference mass with IDs available in the frozen training catalog, on decomposable rows only.",
            "overlap": "Sum of min(predicted grams, reference grams) by shared exact ID divided by reference mass on decomposable rows.",
            "shared_mass": "Sum of per-ID absolute gram errors on shared IDs, divided by all 84. Net-per-dish absolute shared-mass error is also shown; neither imputes fallback ingredients.",
            "omission": "Exact-ID absence is split into catalog-unavailable and available-but-unselected. Neither proves a visual omission; unknown items are never mapped to truth.",
            "identity": "Signed terms sum to prediction minus truth; absolute term means need not sum to MAE. Shared-density and mass terms are descriptive, not causal.",
        },
        "limitations": ["Development data were repeatedly reused and are not independent validation.",
            "Exact-ID agreement does not prove semantic, region or compound-food equivalence.",
            "Mass decomposition excludes whole fallbacks; oracle and raw metrics retain all 84.",
            "Comparisons on different decomposable subsets are descriptive and do not establish a mechanism.",
            "No candidate is selected, calibrated, accepted or promoted by this diagnostic."],
        "bootstrap_replicates": 0, "calibration_refitted": False, "new_profile_selected": False,
        "row_predictions_or_reference_rows_exported": False, "provider_constructed": False,
        "validation_opened": False, "api_calls": 0,
    }
    result["mechanism_comparison"] = {"raw_K": mechanism_values(result), "raw_J": mechanism_values(old),
        "comparison_is_descriptive_only": True, "selection_performed": False}
    require(fingerprint(verified_base()) == fingerprint(verified), "base_changed_during_diagnostic")
    for previous in (*stores, old_store):
        previous.verify_completed()
    reader.unchanged()
    if complete:
        require(saved == {"aggregate": result}, "diagnostic_recomputation_changed")
    else:
        store.finalize({"aggregate": result})
    require(store.verify_completed() == {"aggregate": result}, "diagnostic_seal_changed")
    return {"status": "diagnostic_verified" if complete else "diagnostic_complete", "output": OUTPUT,
            "aggregate": result}


def main(argv=None):
    os.umask(0o077)
    argparse.ArgumentParser(description=__doc__).parse_args(argv)
    try:
        result = run()
        print(json.dumps({"status": result["status"], "output": result["output"], "n": 84,
            "scope": SCOPE, "api_calls": 0}, sort_keys=True))
        return 0
    except Exception as error:
        print(json.dumps({"status": "invalid_diagnostic", "error_type": type(error).__name__,
            "required_population_n": 84, "dropped_rows": 0}, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
