#!/usr/bin/env python3
"""Score sealed K, preserving ASA and comparing one whole profile with raw J.

The completed K verifier runs before any label reader exists. The raw J branch
comes only from the pinned, fully verified prior scoring seal; no old evaluator,
calibration fit, inference or service retry is invoked. Repeat scoring verifies
its existing seal before labels, recomputes, and performs no artifact writes.
All 84 Nutrition5k rows, including explicit training fallbacks, remain scored.
Selection uses the ten Nutrition5k cap ratios; unchanged ASA supplies the joint
20-check gate. This is development selection, not independent validation.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sys

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "src")]
from round4.src import score_dev as scorer
from round4.src.artifacts import ArtifactStore, canonical, decode, fingerprint

BASE_OUTPUT = "round5/runs/K"
BASE_INTENT = BASE_OUTPUT + "/intent.json"
BASE_COMPLETION = BASE_OUTPUT + "/completion.json"
OUTPUT = "round5/scoring/K"
BASELINE_OUTPUT = "round4/scoring/J_service_continuation_calibration"
BASELINE_COMPLETION = BASELINE_OUTPUT + "/completion.json"
TRAIN_FREEZE = "round4/data/train/freeze.json"
SOURCE_NAMES = ("round5/src/score_component.py", "round5/tests/test_score_component.py",
                *scorer.SOURCE_NAMES)
PINNED_INPUTS = {**scorer.PINNED_INPUTS,
    BASELINE_COMPLETION: "95d30a709bafaf05e128b91f2ca31180dc4f1f14cff4ad5667953a02a155d768",
    "round4/src/score_dev.py": "0e84e173f11da66c13f822e69d8babff0e894c91c1dd8b6767fc2fd76180ae34",
    "round4/src/artifacts.py": "c80f55cfeeeca87d670f0e517e540c07a1206dd7fd2e902f3e2d403c6254653c"}
SCOPE = "development_not_independent_validation"
summarize = scorer._summary


class ScoreError(ValueError):
    """Fixed safe error; never an accuracy or service-failure fallback."""


def require(condition, code):
    if not condition:
        raise ScoreError(code)


class Inputs:
    def __init__(self, root):
        self.root, self.hashes = Path(root), {}
        require(self.root.is_dir() and self.root.resolve() == self.root, "noncanonical_scoring_root")

    def read(self, relative):
        path = self.root / relative
        require(not Path(relative).is_absolute() and ".." not in Path(relative).parts
                and path.resolve() == path and path.is_file(), "unsafe_or_missing_scoring_input")
        raw = path.read_bytes()
        sha = hashlib.sha256(raw).hexdigest()
        require(relative not in PINNED_INPUTS or sha == PINNED_INPUTS[relative], "pinned_scoring_input_changed")
        require(relative not in self.hashes or sha == self.hashes[relative], "scoring_input_changed")
        self.hashes[relative] = sha
        return raw

    def unchanged(self):
        for name in tuple(self.hashes):
            self.read(name)


def verified_base():
    from round5.src import run_component
    return run_component.base(verify_only=True)


def driver_contract():
    from round5.src import run_component
    return {"sources": run_component.SOURCES, "method_config": run_component.METHOD_CONFIG,
            "protocol": run_component.PROTOCOL, "protocol_sha256": run_component.PROTOCOL_SHA256,
            "parent_completion_sha256": run_component.PARENT_COMPLETION_SHA256}


def _verified():
    value = verified_base()
    require(isinstance(value, dict) and value.get("status") == "base_verified"
            and type(value.get("n")) is int and value["n"] == 84
            and value.get("provider_constructed") is False
            and value.get("validation_opened") is False,
            "completed_zero_provider_K_verification_required")
    require(isinstance(value.get("records"), dict) and len(value["records"]) == 84
            and isinstance(value.get("binding"), dict)
            and isinstance(value.get("completion_sha256"), str)
            and re.fullmatch("[0-9a-f]{64}", value["completion_sha256"]), "complete_K_binding_required")
    return decode(canonical({key: value[key] for key in ("records", "binding", "completion_sha256")}))


def _external_binding(reader, verified):
    contract = driver_contract()
    intent = decode(reader.read(BASE_INTENT))
    complete = decode(reader.read(BASE_COMPLETION))
    binding, records = verified["binding"], verified["records"]
    require(intent.get("binding") == binding and intent.get("binding_sha256") == fingerprint(binding)
            and intent.get("expected_records") == sorted(records)
            and intent.get("expected_records_sha256") == fingerprint(sorted(records))
            and complete.get("run_binding_sha256") == fingerprint(intent)
            and complete.get("record_count") == 84
            and reader.hashes[BASE_COMPLETION] == verified["completion_sha256"], "K_external_seal_mismatch")
    require(binding.get("phase") == "development_component_base"
            and binding.get("method_config") == contract["method_config"]
            and binding["method_config"].get("candidate") == "K"
            and binding["method_config"].get("calibration") is None
            and binding.get("query_count") == 84 and binding.get("query_groups") == 78,
            "registered_uncalibrated_K_binding_required")
    bound = binding.get("input_sha256", {})
    require(isinstance(bound, dict) and bound.get(scorer.MANIFEST) == PINNED_INPUTS[scorer.MANIFEST]
            and scorer.LABELS not in bound and scorer.PRESERVED not in bound
            and all(not name.endswith("labels.json") or name.startswith("round4/data/train/") for name in bound),
            "query_labels_cannot_bind_K_inference")
    for name in contract["sources"]:
        reader.read(name)
        require(bound.get(name) == reader.hashes[name], "K_bound_source_changed")
    require(reader.hashes[contract["protocol"]] == contract["protocol_sha256"], "K_protocol_changed")
    freeze = decode(reader.read(TRAIN_FREEZE))
    require(freeze.get("status") == "accepted_external_training_frozen"
            and bool(freeze.get("binding")) and binding.get("training_exclusion_binding") == freeze["binding"]
            and bound.get(TRAIN_FREEZE) == reader.hashes[TRAIN_FREEZE]
            and binding.get("training_freeze_sha256") == reader.hashes[TRAIN_FREEZE],
            "external_training_release_changed")
    parent = binding.get("parent_provenance", {})
    require(isinstance(parent, dict)
            and parent.get("parent_completion_sha256") == contract["parent_completion_sha256"]
            and parent.get("training_freeze_sha256") == reader.hashes[TRAIN_FREEZE], "frozen_J_parent_changed")
    return {"base_binding_sha256": fingerprint(binding), "parent_provenance": deepcopy(parent),
            "training_freeze_sha256": reader.hashes[TRAIN_FREEZE],
            "component_source_sha256": {name: reader.hashes[name] for name in contract["sources"]}}


def _baseline(reader):
    """Read-only verified aggregate; never call the old evaluator or read its labels."""
    reader.read(BASELINE_COMPLETION)  # Fixed external completion pin, not self-certified contents.
    intent = decode(reader.read(BASELINE_OUTPUT + "/intent.json"))
    require(isinstance(intent, dict) and isinstance(intent.get("binding"), dict)
            and intent.get("expected_records") == ["metrics"], "raw_J_scoring_intent_changed")
    store = ArtifactStore(ROOT / BASELINE_OUTPUT, intent["binding"], ["metrics"],
                          verify_sources=reader.unchanged, root=ROOT / "round4")
    saved = store.verify_completed()
    raw = saved.get("metrics", {}).get("raw")
    require(isinstance(raw, dict) and raw.get("candidate") == "J_service_continuation"
            and raw.get("scope") == SCOPE and raw.get("validation_opened") is False
            and raw.get("calibration_applied") is False, "sealed_uncalibrated_raw_J_required")
    _ratios(raw["joint_metrics_with_preserved_asa"])
    require(raw.get("nutrition5k") == raw["joint_metrics_with_preserved_asa"]["datasets"]["nutrition5k"],
            "raw_J_nutrition5k_summary_mismatch")
    return deepcopy(raw), store


def _ratios(value, *, dataset=None):
    checks = value.get("checks", [])
    wanted = {(d, target, statistic) for d in scorer.metrics.THRESHOLDS
              for target in scorer.metrics.KEYS for statistic in ("mae", "per_unit")}
    require(isinstance(checks, list) and len(checks) == 20
            and {(c["dataset"], c["target"], c["statistic"]) for c in checks} == wanted,
            "all_twenty_registered_checks_required")
    ratios, passes = [], set()
    for check in checks:
        key = (check["dataset"], check["target"], check["statistic"])
        cap = scorer.metrics.THRESHOLDS[key[0]][key[1]][key[2] == "per_unit"]
        amount = check["value"]
        require(check["threshold"] == cap and (amount is None or (type(amount) in (int, float)
                and math.isfinite(amount) and amount >= 0)), "invalid_registered_metric_value")
        passed = amount is not None and amount <= cap
        require(type(check["pass"]) is bool and check["pass"] == passed, "metric_pass_mismatch")
        if dataset is None or key[0] == dataset:
            ratios.append(None if amount is None else amount / cap)
            if passed:
                passes.add(key)
    undefined = sum(value is None for value in ratios)
    return {"check_count": len(ratios), "undefined_checks": undefined, "passed_checks": len(passes),
            "worst_ratio": None if undefined else max(ratios),
            "mean_ratio": None if undefined else math.fsum(ratios) / len(ratios)}, passes


def compare_raw_j(raw_joint, k_joint):
    """One whole N5 profile; full precision, strict improvement, ties keep J."""
    raw, old_passes = _ratios(raw_joint, dataset="nutrition5k")
    candidate, new_passes = _ratios(k_joint, dataset="nutrition5k")
    require(raw_joint["datasets"]["asa24"] == k_joint["datasets"]["asa24"]
            and [c for c in raw_joint["checks"] if c["dataset"] == "asa24"]
            == [c for c in k_joint["checks"] if c["dataset"] == "asa24"], "preserved_ASA_metrics_changed")
    regressions = old_passes - new_passes
    selected, reason = "J", "no_strict_lexicographic_improvement"
    if raw["undefined_checks"] or candidate["undefined_checks"]:
        reason = "undefined_N5_check_prevents_selection"
    elif regressions:
        reason = "K_crossed_a_previously_passed_cap"
    elif candidate["worst_ratio"] < raw["worst_ratio"]:
        selected, reason = "K", "strictly_lower_worst_ratio"
    elif candidate["worst_ratio"] == raw["worst_ratio"] and candidate["mean_ratio"] < raw["mean_ratio"]:
        selected, reason = "K", "equal_worst_and_strictly_lower_mean_ratio"
    return {"scope": "whole_nutrition5k_profile_10_ratios_ASA_fixed", "selected_candidate": selected,
            "reason": reason, "raw_j": raw, "K": candidate,
            "raw_j_joint": _ratios(raw_joint)[0], "K_joint": _ratios(k_joint)[0],
            "regressed_raw_J_pass_checks": [{"target": key[1], "statistic": key[2]} for key in sorted(regressions)]}


def score():
    verified = _verified()  # No reader or label access before full base replay.
    reader = Inputs(ROOT)
    for name in SOURCE_NAMES:
        reader.read(name)
    external = _external_binding(reader, verified)
    baseline, baseline_store = _baseline(reader)
    rows = scorer._manifest(reader.read(scorer.MANIFEST))
    n5, predictions, asa = scorer._predictions(rows, verified["records"], decode(reader.read(scorer.PRESERVED)))
    # Known label digest permits checking an existing output seal BEFORE opening
    # labels. The subsequent read must match it; no fabricated target is used.
    binding = {"schema_version": 1, "candidate": "K", "phase": "development_component_scoring",
               "scope": SCOPE, "calibration_applied": False, "validation_opened": False,
               "bootstrap": scorer.BOOTSTRAP, "seed": scorer.SEED,
               "base_completion_sha256": verified["completion_sha256"],
               "base_records_sha256": fingerprint(verified["records"]), "external_training_proof": external,
               "raw_J_scoring_completion_sha256": reader.hashes[BASELINE_COMPLETION],
               "source_sha256": {name: reader.hashes[name] for name in SOURCE_NAMES},
               "input_sha256": {**reader.hashes, scorer.LABELS: PINNED_INPUTS[scorer.LABELS]}}
    store = ArtifactStore(ROOT / OUTPUT, binding, ["metrics"], verify_sources=reader.unchanged, root=ROOT / "round5")
    saved = store.verify_completed() if (ROOT / OUTPUT / "completion.json").exists() else None
    labels = decode(reader.read(scorer.LABELS))
    require(isinstance(labels, dict) and set(labels) == {row["sample_id"] for row in rows},
            "registered_development_label_population_required")
    scorer.metrics._training(rows, labels)
    summary = summarize(rows, labels, n5, predictions, asa)
    summary.update(candidate="K", scope=SCOPE, validation_opened=False, calibration_applied=False,
                   raw_j=baseline, comparison_to_raw_j=compare_raw_j(
                       baseline["joint_metrics_with_preserved_asa"], summary["joint_metrics_with_preserved_asa"]),
                   bootstrap_scope="descriptive_fixed_development_predictions_no_refitting_or_selection_uncertainty")
    require(fingerprint(_verified()) == fingerprint(verified), "K_changed_during_scoring")
    baseline_store.verify_completed()
    reader.unchanged()
    if saved is not None:
        require(fingerprint(saved) == fingerprint({"metrics": summary}), "recomputed_K_metrics_differ_from_seal")
        status = "component_scoring_verified"
    else:
        store.finalize({"metrics": summary})
        status = "component_scoring_complete"
    require(fingerprint(store.verify_completed()) == fingerprint({"metrics": summary}), "K_scoring_seal_mismatch")
    return {"status": status, "metrics": summary, "output": OUTPUT,
            "provider_constructed": False, "validation_opened": False}


def main(argv=None):
    argparse.ArgumentParser(description=__doc__).parse_args(argv)
    os.umask(0o077)
    try:
        result = score()
        print(json.dumps({key: value for key, value in result.items() if key != "metrics"} | {
            "scope": SCOPE, "selected_candidate": result["metrics"]["comparison_to_raw_j"]["selected_candidate"],
            "nutrition5k_passed_checks": result["metrics"]["nutrition5k_passed_checks"],
            "joint_passed_checks": result["metrics"]["joint_metrics_with_preserved_asa"]["passed_checks"]},
            sort_keys=True, allow_nan=False))
        return 0
    except BaseException as error:
        if isinstance(error, (KeyboardInterrupt, SystemExit)):
            raise
        print(json.dumps({"status": "stopped", "error_type": type(error).__name__}, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
