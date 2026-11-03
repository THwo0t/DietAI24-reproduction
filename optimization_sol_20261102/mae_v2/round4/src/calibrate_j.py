#!/usr/bin/env python3
"""One registered aggregate-only calibration of a sealed external-only J base.

No provider, image inference, model calls or validation access. The mandatory
base verifier can reread its bound images for integrity. Raw leaves and base
records are immutable; five independent corrections are not ingredient masses.
Predictions/fit audits are sealed before metrics and whole-profile selection.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import json
import math
import os
from pathlib import Path
import sys

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "src")]
from round4.src import score_dev as scorer
from round4.src.artifacts import ArtifactStore, canonical, decode, fingerprint

KEYS = scorer.metrics.KEYS
PROTOCOL = "round4/CALIBRATION_PROTOCOL.md"
PROTOCOL_SHA256 = "2f921d76f6f08ada8faa87648638fd17c4bff7d78aa0099bacb1318ce81d6e5b"
BASE_INTENT = "round4/runs/J/intent.json"
TRAIN_FREEZE = "round4/data/train/freeze.json"
CAL_OUTPUT = "round4/calibration/J"
SCORE_OUTPUT = "round4/scoring/J_calibration"
SOURCES = ("round4/src/calibrate_j.py", *scorer.SOURCE_NAMES)
METHOD = {"version": "J_aggregate_oof_calibration_r4.1", "raw_grid_minimum": .5,
          "raw_grid_maximum": 2.0, "raw_grid_step": .001, "shrinkage_toward_one": .5,
          "applied_minimum": .75, "applied_maximum": 1.5, "minimum_eligible_groups": 5,
          "training_objective": "per_target_equal_observation_absolute_error",
          "tie_break": ["distance_from_one", "smaller_raw_factor"],
          "whole_fallback": "exclude_from_fit_and_preserve_prediction",
          "scope": "aggregate_totals_only", "folds": 5}


class CalibrationError(ValueError):
    pass


def require(condition, code):
    if not condition:
        raise CalibrationError(code)


def _vector(value):
    require(isinstance(value, dict) and set(value) == set(KEYS), "complete_five_target_vector_required")
    result = {}
    for key in KEYS:
        x = value[key]
        require(not isinstance(x, bool) and isinstance(x, (int, float)), "numeric_target_required")
        try:
            x = float(x)
        except (OverflowError, ValueError):
            raise CalibrationError("finite_nonnegative_target_required") from None
        require(math.isfinite(x) and x >= 0, "finite_nonnegative_target_required")
        result[key] = x
    require(result["weight"] > 0, "positive_meal_weight_required")
    return result


def _rows(rows):
    require(isinstance(rows, list) and bool(rows), "nonempty_development_rows_required")
    indexed, groups = {}, {}
    for row in rows:
        require(isinstance(row, dict) and row.get("dataset") == "nutrition5k"
                and row.get("split") == "dev" and type(row.get("fold")) is int
                and row["fold"] in range(5), "development_nutrition5k_rows_required")
        sid, group = row.get("sample_id"), row.get("group_id")
        require(isinstance(sid, str) and sid and sid not in indexed
                and isinstance(group, str) and bool(group), "unique_ids_and_groups_required")
        require(group not in groups or groups[group] == row["fold"], "group_crosses_folds")
        indexed[sid], groups[group] = row, row["fold"]
    return {sid: indexed[sid] for sid in sorted(indexed)}


def _records(rows, records):
    require(isinstance(records, dict) and set(records) == set(rows), "raw_record_population_mismatch")
    for sid, row in rows.items():
        pred = records[sid]
        require(isinstance(pred, dict) and all(pred.get(key) == row[key]
                for key in ("sample_id", "dataset", "group_id", "fold")), "raw_record_metadata_mismatch")
        require(all(type(pred.get(key)) is bool for key in
                    ("fallback", "method_fallback", "repair_used", "native_complete")),
                "raw_record_flags_required")
        _vector(pred.get("prediction"))
        if pred["fallback"]:
            require(pred.get("raw_prediction") is None, "whole_fallback_cannot_have_raw_estimate")
        else:
            raw = _vector(pred.get("raw_prediction"))
            require(raw == _vector(pred["prediction"]), "only_uncalibrated_base_records_allowed")


def _labels(rows, labels):
    require(isinstance(labels, dict) and set(labels) == set(rows), "exact_training_label_population_required")
    scorer.metrics._training(list(rows.values()), labels)
    return {sid: _vector(labels[sid].get("truth")) for sid in rows}


def _loss(pairs, key, factor):
    try:
        value = math.fsum(abs(pred[key] * factor - truth[key]) for pred, truth in pairs)
    except OverflowError:
        raise CalibrationError("nonfinite_training_loss") from None
    require(math.isfinite(value), "nonfinite_training_loss")
    return value


def fit_profile(training_rows, training_labels, training_records):
    """Fit exactly the supplied training population; no held-out labels accepted.

    Public pure helper: caller must exclude the whole query fold/group first.
    Extra/missing label or prediction keys are rejected rather than ignored.
    """
    indexed = _rows(training_rows)
    _records(indexed, training_records)
    truths = _labels(indexed, training_labels)
    eligible = [sid for sid in indexed if not training_records[sid]["fallback"]]
    eligible_groups = sorted({indexed[sid]["group_id"] for sid in eligible})
    pairs = [(_vector(training_records[sid]["raw_prediction"]), truths[sid]) for sid in eligible]
    usable = len(eligible_groups) >= 5
    factors, applied, losses = {}, {}, {}
    for key in KEYS:
        raw_factor = 1.0
        if usable:
            best = min((_loss(pairs, key, integer / 1000), abs(integer - 1000), integer)
                       for integer in range(500, 2001))
            raw_factor = best[2] / 1000
        factor = 1 + .5 * (raw_factor - 1)
        factors[key], applied[key] = raw_factor, factor
        losses[key] = {"raw_mae": _loss(pairs, key, 1.0) / len(pairs) if pairs else None,
                       "unshrunk_training_mae": _loss(pairs, key, raw_factor) / len(pairs) if pairs else None,
                       "applied_training_mae": _loss(pairs, key, factor) / len(pairs) if pairs else None}
    return {"raw_factors": factors, "applied_factors": applied,
            "training_ids": list(indexed),
            "training_groups": sorted({row["group_id"] for row in indexed.values()}),
            "eligible_ids": eligible, "eligible_groups": eligible_groups,
            "eligible_n": len(eligible), "eligible_group_count": len(eligible_groups),
            "reason": "fitted" if usable else "fewer_than_five_eligible_training_groups",
            "target_training_losses": losses}


def apply_profile(record, applied_factors, *, heldout_fold):
    require(isinstance(applied_factors, dict) and set(applied_factors) == set(KEYS), "five_factors_required")
    factors = {}
    for key, value in applied_factors.items():
        require(not isinstance(value, bool) and isinstance(value, (int, float))
                and math.isfinite(value) and .75 <= value <= 1.5, "applied_factor_outside_registered_range")
        factors[key] = float(value)
    result = deepcopy(record)
    if result["fallback"]:
        applied = dict.fromkeys(KEYS, 1.0)
    else:
        raw = _vector(result["raw_prediction"])
        result["prediction"] = _vector({key: raw[key] * factors[key] for key in KEYS})
        applied = factors
    result["calibration"] = {"method": METHOD["version"], "scope": "aggregate_totals_only",
        "heldout_fold": heldout_fold, "applied_factors": applied,
        "whole_fallback_preserved": result["fallback"], "leaf_accounting_scope": "raw_prediction_only"}
    return result


def build_oof(rows, labels, records):
    """Five deterministic, group-isolated fits plus a separate future-use fit."""
    indexed = _rows(rows)
    require({row["fold"] for row in indexed.values()} == set(range(5)), "all_five_original_folds_required")
    _records(indexed, records)
    _labels(indexed, labels)
    out, folds = {}, {}
    for fold in range(5):
        heldout = [row for row in indexed.values() if row["fold"] == fold]
        groups = {row["group_id"] for row in heldout}
        train = [row for row in indexed.values() if row["fold"] != fold and row["group_id"] not in groups]
        require(bool(train), "empty_outer_training_population")
        train_ids = [row["sample_id"] for row in train]
        params = fit_profile(train, {sid: labels[sid] for sid in train_ids},
                             {sid: records[sid] for sid in train_ids})
        params.update(heldout_fold=fold, heldout_ids=[row["sample_id"] for row in heldout],
                      heldout_groups=sorted(groups))
        folds[str(fold)] = params
        for row in heldout:
            sid = row["sample_id"]
            out[sid] = apply_profile(records[sid], params["applied_factors"], heldout_fold=fold)
    require(set(out) == set(indexed), "oof_prediction_population_changed")
    final_fit = fit_profile(list(indexed.values()), labels, records)
    final_fit["usage"] = "future_unseen_inputs_only_never_this_oof_population"
    return {"records": {sid: out[sid] for sid in sorted(out)},
            "fit_audit": {"method": deepcopy(METHOD), "folds": folds, "final_training_fit": final_fit}}


def _ratios(value):
    checks = [check for check in value["checks"] if check["dataset"] == "nutrition5k"]
    wanted = {(key, statistic) for key in KEYS for statistic in ("mae", "per_unit")}
    require(len(checks) == 10 and {(c["target"], c["statistic"]) for c in checks} == wanted,
            "ten_complete_nutrition5k_checks_required")
    result, passes = {}, set()
    for check in checks:
        key = (check["target"], check["statistic"])
        value, threshold = check["value"], check["threshold"]
        expected = scorer.metrics.THRESHOLDS["nutrition5k"][key[0]][key[1] == "per_unit"]
        require(threshold == expected and (value is None or (not isinstance(value, bool)
                and isinstance(value, (int, float)) and math.isfinite(value) and value >= 0)),
                "finite_or_explicitly_undefined_registered_metric_required")
        require(type(check["pass"]) is bool and check["pass"] == (value is not None and value <= threshold),
                "metric_pass_flag_mismatch")
        result[key] = value / threshold if value is not None else None
        if check["pass"]:
            passes.add(key)
    ratios = list(result.values())
    undefined = sum(value is None for value in ratios)
    return {"worst_ratio": None if undefined else max(ratios),
            "mean_ratio": None if undefined else math.fsum(ratios) / 10,
            "undefined_checks": undefined,
            "passed_checks": len(passes)}, passes


def select_profile(raw_metrics, calibrated_metrics):
    raw, old_passes = _ratios(raw_metrics)
    calibrated, new_passes = _ratios(calibrated_metrics)
    regressions = old_passes - new_passes
    if raw["undefined_checks"] or calibrated["undefined_checks"]:
        selected, reason = "raw", "undefined_nutrition5k_check_prevents_selection"
    elif regressions:
        selected, reason = "raw", "calibration_crossed_a_previously_passed_cap"
    elif calibrated["worst_ratio"] < raw["worst_ratio"]:
        selected, reason = "calibrated", "strictly_lower_worst_ratio"
    elif (calibrated["worst_ratio"] == raw["worst_ratio"]
          and calibrated["mean_ratio"] < raw["mean_ratio"]):
        selected, reason = "calibrated", "equal_worst_and_strictly_lower_mean_ratio"
    else:
        selected, reason = "raw", "no_strict_lexicographic_improvement"
    return {"selected_profile": selected, "reason": reason, "raw": raw, "calibrated": calibrated,
            "regressed_raw_pass_checks": [{"target": target, "statistic": stat}
                                           for target, stat in sorted(regressions)],
            "scope": "one_whole_nutrition5k_profile_asa_unchanged"}


def _external_binding(reader, records):
    intent = decode(reader.read(BASE_INTENT))
    complete = decode(reader.read(scorer.BASE_COMPLETION))
    binding = intent.get("binding", {})
    require(intent.get("binding_sha256") == fingerprint(binding)
            and intent.get("expected_records") == sorted(records)
            and intent.get("expected_records_sha256") == fingerprint(sorted(records))
            and complete.get("run_binding_sha256") == fingerprint(intent)
            and complete.get("record_count") == 84, "base_external_seal_binding_mismatch")
    require(binding.get("phase") == "development_base"
            and binding.get("method_config") == scorer.run_base.context.METHOD_CONFIG
            and binding.get("query_count") == 84 and binding.get("query_groups") == 78,
            "registered_external_only_base_required")
    bound = binding.get("input_sha256", {})
    require(isinstance(bound, dict) and scorer.LABELS not in bound and scorer.PRESERVED not in bound
            and bound.get(scorer.MANIFEST) == scorer.PINNED_INPUTS[scorer.MANIFEST]
            and all(not name.endswith("labels.json") or name.startswith("round4/data/train/")
                    for name in bound), "development_labels_must_not_bind_base_inference")
    freeze = decode(reader.read(TRAIN_FREEZE))
    require(freeze.get("status") == "accepted_external_training_frozen"
            and binding.get("training_freeze_sha256") == reader.hashes[TRAIN_FREEZE]
            and bound.get(TRAIN_FREEZE) == reader.hashes[TRAIN_FREEZE]
            and binding.get("training_exclusion_binding") == freeze.get("binding")
            and bool(freeze.get("binding")), "independent_training_freeze_mismatch")
    return {"base_binding_sha256": fingerprint(binding),
            "training_freeze_sha256": reader.hashes[TRAIN_FREEZE],
            "training_exclusion_binding_sha256": fingerprint(freeze["binding"])}


def _seal(directory, binding, records, reader):
    store = ArtifactStore(ROOT / directory, binding, list(records),
                          verify_sources=reader.unchanged, root=ROOT / "round4")
    complete = (ROOT / directory / "completion.json").exists()
    if complete:
        require(fingerprint(store.verify_completed()) == fingerprint(records), "completed_calibration_recomputation_changed")
    else:
        store.finalize(records)
    return complete


def run():
    """Completed J only; called by root after inference, never during development."""
    records = scorer._verified_base()
    reader = scorer.Inputs(ROOT)
    reader.read(PROTOCOL)
    require(reader.hashes[PROTOCOL] == PROTOCOL_SHA256, "registered_calibration_protocol_changed")
    for name in SOURCES:
        reader.read(name)
    external = _external_binding(reader, records)
    rows = scorer._manifest(reader.read(scorer.MANIFEST))
    n5, raw_predictions, asa = scorer._predictions(rows, records, decode(reader.read(scorer.PRESERVED)))
    indexed = _rows(n5)
    _records(indexed, records)
    labels = decode(reader.read(scorer.LABELS))  # All seal/external/population gates precede labels.
    require(isinstance(labels, dict) and set(labels) == {row["sample_id"] for row in rows},
            "registered_development_label_population_required")
    scorer.metrics._training(rows, labels)
    derived = build_oof(n5, {sid: labels[sid] for sid in indexed}, records)
    require(fingerprint(scorer._verified_base()) == fingerprint(records), "base_changed_during_calibration")
    reader.unchanged()
    binding = {"schema_version": 1, "phase": "J_calibration_oof", "method": deepcopy(METHOD),
        "scope": "development_not_independent_validation", "validation_opened": False,
        "base_records_sha256": fingerprint(records), "external_training_proof": external,
        "input_sha256": dict(reader.hashes), "source_sha256": {name: reader.hashes[name] for name in SOURCES}}
    sealed = {**derived["records"], "fit_audit": derived["fit_audit"]}
    was_calibrated = _seal(CAL_OUTPUT, binding, sealed, reader)
    reader.read(CAL_OUTPUT + "/completion.json")  # Predictions/parameters sealed before any evaluator call.
    calibrated_predictions = [derived["records"][row["sample_id"]] for row in n5]
    raw = scorer._summary(rows, labels, n5, raw_predictions, asa)
    calibrated = scorer._summary(rows, labels, n5, calibrated_predictions, asa)
    calibrated.update(candidate="J_aggregate_calibration", calibration_applied=True)
    selection = select_profile(raw["joint_metrics_with_preserved_asa"],
                               calibrated["joint_metrics_with_preserved_asa"])
    summary = {"candidate": "J_aggregate_calibration", "scope": "development_not_independent_validation",
        "validation_opened": False, "calibration_applied": True, "raw": raw, "calibrated": calibrated,
        "bootstrap_scope": "conditional_on_fixed_oof_predictions_no_refitting_or_selection_uncertainty",
        "selection": selection,
        "selected_profile_calibration_applied": selection["selected_profile"] == "calibrated",
        "future_selected_profile_factors": (derived["fit_audit"]["final_training_fit"]["applied_factors"]
            if selection["selected_profile"] == "calibrated" else dict.fromkeys(KEYS, 1.0)),
        "future_factor_usage": "unseen_inputs_only_never_reported_oof_predictions"}
    reader.unchanged()
    score_binding = {**binding, "phase": "J_calibration_scoring",
        "bootstrap": scorer.BOOTSTRAP, "seed": scorer.SEED,
        "calibration_completion_sha256": reader.hashes[CAL_OUTPUT + "/completion.json"],
        "input_sha256": dict(reader.hashes)}
    was_scored = _seal(SCORE_OUTPUT, score_binding, {"metrics": summary}, reader)
    return {"status": "calibration_verified" if was_calibrated and was_scored else "calibration_complete",
            "metrics": summary, "provider_constructed": False, "validation_opened": False,
            "calibrated_output": CAL_OUTPUT, "scoring_output": SCORE_OUTPUT}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args(argv)
    os.umask(0o077)
    try:
        result = run()
        print(json.dumps({"status": result["status"], "scope": result["metrics"]["scope"],
            "selected_profile": result["metrics"]["selection"]["selected_profile"],
            "provider_constructed": False, "validation_opened": False,
            "calibrated_output": CAL_OUTPUT, "scoring_output": SCORE_OUTPUT}, sort_keys=True))
        return 0
    except Exception as error:
        print(json.dumps({"status": "stopped", "error_type": type(error).__name__}, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
