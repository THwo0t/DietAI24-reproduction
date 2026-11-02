#!/usr/bin/env python3
"""Score the sealed J development population; never infer, fit or select.

The first operation verifies the completed 84-query base run with zero provider
construction. Only then may this separate entry point read the pinned development
labels. All 84 Nutrition5k predictions (including explicit training fallbacks)
and all 99 preserved ASA24 predictions remain in their registered populations.
No calibration is fitted or applied to J; preserved ASA24 remains exactly as run.
Validation is never opened. The 10,000-draw group bootstrap is descriptive of
development performance, not independent validation or a configuration search.

A separate ArtifactStore seals the complete metric object. Repeated invocations
recompute from the same sealed inputs and compare without rewriting any artifact.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import sys

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "src")]
import opt_metrics as metrics
from round4.src import run_base
from round4.src.artifacts import ArtifactStore, canonical, decode, fingerprint

MANIFEST = "data/cohorts/dev.jsonl"
LABELS = "data/cohorts/dev_labels.json"
PRESERVED = "runs/development/selected_oof_predictions.json"
BASE_COMPLETION = "round4/runs/J/completion.json"
OUTPUT = "round4/scoring/J"
PINNED_INPUTS = {
    MANIFEST: "ec02c058653b5505b01abee882c8b04a4711ec93b0c08496b962c2faf1586fe9",
    LABELS: "b29dedc788c1facee28afd32c96fe22a897b6a220ddd786e43957ec9ef5b5849",
    PRESERVED: "91671dcd2b885cfeaf59544698bb0e84ad3579a2b2784c9aa98b4f3e0df434de",
    "src/opt_metrics.py": "15d71fd2c2379f7f723707cddfeb2e2868c0dd84b027edd12ef9185303a1e63e",
}
SOURCE_NAMES = ("round4/src/score_dev.py", "src/opt_metrics.py", "round4/src/artifacts.py")
BOOTSTRAP, SEED = 10000, 20261102
POPULATIONS = {"nutrition5k": (84, 78), "asa24": (99, 23)}


class ScoreError(ValueError):
    """Safe fixed-code failure, never containing labels or provider responses."""


def require(condition, code):
    if not condition:
        raise ScoreError(code)


class Inputs:
    """Snapshot explicit paths only; no directory discovery or validation I/O."""
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
        require(relative not in self.hashes or self.hashes[relative] == sha, "scoring_input_changed_during_read")
        self.hashes[relative] = sha
        return raw

    def unchanged(self):
        for relative in tuple(self.hashes):
            self.read(relative)


def _verified_base():
    value = run_base.base(verify_only=True)
    require(isinstance(value, dict) and value.get("status") == "base_verified"
            and type(value.get("n")) is int and value["n"] == 84
            and value.get("provider_constructed") is False and value.get("validation_opened") is False,
            "complete_zero_provider_base_verification_required")
    records = value.get("records")
    require(isinstance(records, dict) and len(records) == 84, "base_requires_all_84_records")
    # Check finite JSON before copying: no mutable alias to the driver's result.
    return decode(canonical(records))


def _manifest(raw):
    rows = [decode(line) for line in raw.splitlines()]
    require(len(rows) == 183 and all(isinstance(row, dict) for row in rows), "registered_183_rows_required")
    ids = [row.get("sample_id") for row in rows]
    require(all(isinstance(sid, str) and sid for sid in ids) and len(set(ids)) == 183,
            "manifest_ids_must_be_unique")
    require({row.get("dataset") for row in rows} == set(POPULATIONS), "unexpected_manifest_dataset")
    for dataset, (count, groups) in POPULATIONS.items():
        selected = [row for row in rows if row["dataset"] == dataset]
        require(len(selected) == count and all(isinstance(row.get("group_id"), str)
                and row["group_id"] for row in selected)
                and len({row["group_id"] for row in selected}) == groups,
                "registered_dataset_population_or_groups_changed")
        require(all(row.get("split") == "dev" and type(row.get("fold")) is int
                    and row["fold"] in range(5) for row in selected)
                and {row["fold"] for row in selected} == set(range(5)), "development_fold_provenance_changed")
        by_group = {}
        for row in selected:
            group, fold = row["group_id"], row["fold"]
            require(group not in by_group or by_group[group] == fold, "group_crosses_development_folds")
            by_group[group] = fold
    return rows


def _predictions(rows, records, preserved):
    n5 = [row for row in rows if row["dataset"] == "nutrition5k"]
    asa = [row for row in rows if row["dataset"] == "asa24"]
    require(set(records) == {row["sample_id"] for row in n5}, "base_prediction_population_changed")
    n5_predictions = []
    for row in n5:
        pred = records[row["sample_id"]]
        require(isinstance(pred, dict) and all(pred.get(key) == row[key]
                for key in ("sample_id", "dataset", "group_id", "fold")), "base_prediction_metadata_changed")
        require(pred.get("query_id") == row["sample_id"], "base_query_identity_changed")
        require(pred.get("prediction") is not None, "missing_scored_nutrition5k_prediction")
        require(all(type(pred.get(key)) is bool for key in
                    ("fallback", "method_fallback", "repair_used", "native_complete")),
                "base_prediction_state_must_be_boolean")
        n5_predictions.append(deepcopy(pred))
    require(isinstance(preserved, list) and all(isinstance(pred, dict) for pred in preserved),
            "preserved_prediction_list_required")
    asa_predictions = [pred for pred in preserved if pred.get("dataset") == "asa24"]
    asa_index = {pred.get("sample_id"): pred for pred in asa_predictions}
    require(len(asa_predictions) == 99 and len(asa_index) == 99
            and set(asa_index) == {row["sample_id"] for row in asa}, "preserved_asa_population_changed")
    for row in asa:
        pred = asa_index[row["sample_id"]]
        require(all(pred.get(key) == row[key] for key in ("sample_id", "dataset", "group_id", "fold")),
                "preserved_asa_metadata_changed")
    # Preserve ASA fields exactly. Its historical Nutrition5k predictions are
    # never imported into J, and no branch is reconstructed from reference labels.
    return n5, n5_predictions, deepcopy(asa_predictions)


def _summary(rows, labels, n5, n5_predictions, asa_predictions):
    n5_score = metrics.evaluate(n5, labels, n5_predictions, bootstrap=BOOTSTRAP, seed=SEED)
    joint = metrics.evaluate(rows, labels, asa_predictions + n5_predictions, bootstrap=BOOTSTRAP, seed=SEED)
    checks = [check for check in n5_score["checks"] if check["dataset"] == "nutrition5k"]
    return {"scope": "development_not_independent_validation", "candidate": "J",
            "validation_opened": False, "calibration_applied": False,
            "bootstrap_replicates": BOOTSTRAP, "bootstrap_seed": SEED,
            "populations": {dataset: {"n": count, "groups": groups}
                            for dataset, (count, groups) in POPULATIONS.items()},
            "nutrition5k": n5_score["datasets"]["nutrition5k"],
            "nutrition5k_checks": checks,
            "nutrition5k_passed_checks": sum(check["pass"] for check in checks),
            "joint_metrics_with_preserved_asa": joint,
            "nutrition5k_failure_audit": {
                "whole_fallback_n": sum(pred["fallback"] for pred in n5_predictions),
                "method_fallback_n": sum(pred["method_fallback"] for pred in n5_predictions),
                "repair_used_n": sum(pred["repair_used"] for pred in n5_predictions),
                "nonempty_failure_n": sum(pred.get("failure") is not None for pred in n5_predictions),
                "missing_prediction_n": 0}}


def score():
    """Verify -> read development labels -> recompute -> immutable metric seal."""
    records = _verified_base()  # Must precede even constructing the label reader.
    reader = Inputs(ROOT)
    for name in SOURCE_NAMES:
        reader.read(name)
    completion = decode(reader.read(BASE_COMPLETION))
    require(isinstance(completion, dict) and completion.get("record_count") == 84,
            "base_completion_population_changed")
    rows = _manifest(reader.read(MANIFEST))
    preserved = decode(reader.read(PRESERVED))
    n5, n5_predictions, asa_predictions = _predictions(rows, records, preserved)
    labels = decode(reader.read(LABELS))  # All base/population gates already passed.
    require(isinstance(labels, dict) and set(labels) == {row["sample_id"] for row in rows},
            "development_label_population_changed")
    metrics._training(rows, labels)  # Reject sealed provenance and cross-fold groups.
    summary = _summary(rows, labels, n5, n5_predictions, asa_predictions)
    require(fingerprint(_verified_base()) == fingerprint(records), "base_changed_during_scoring")
    reader.unchanged()
    binding = {"schema_version": 1, "candidate": "J", "phase": "development_scoring",
               "scope": summary["scope"], "bootstrap": BOOTSTRAP, "seed": SEED,
               "calibration_applied": False, "validation_opened": False,
               "base_completion_sha256": reader.hashes[BASE_COMPLETION],
               "base_records_sha256": fingerprint(records),
               "source_sha256": {name: reader.hashes[name] for name in SOURCE_NAMES},
               "input_sha256": dict(reader.hashes)}
    store = ArtifactStore(ROOT / OUTPUT, binding, ["metrics"],
                          verify_sources=reader.unchanged, root=ROOT / "round4")
    if (ROOT / OUTPUT / "completion.json").exists():
        saved = store.verify_completed()
        require(fingerprint(saved) == fingerprint({"metrics": summary}), "recomputed_metrics_differ_from_seal")
        status = "scoring_verified"
    else:
        store.finalize({"metrics": summary})
        status = "scoring_complete"
    return {"status": status, "metrics": summary, "provider_constructed": False,
            "validation_opened": False, "output": OUTPUT}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args(argv)
    os.umask(0o077)
    try:
        result = score()
        print(json.dumps({"status": result["status"], "candidate": "J", "output": OUTPUT,
                          "scope": result["metrics"]["scope"], "validation_opened": False,
                          "calibration_applied": False, "provider_constructed": False,
                          "nutrition5k_n": 84, "preserved_asa_n": 99,
                          "nutrition5k_passed_checks": result["metrics"]["nutrition5k_passed_checks"],
                          "joint_passed_checks": result["metrics"]["joint_metrics_with_preserved_asa"]["passed_checks"]},
                         sort_keys=True, allow_nan=False))
        return 0
    except Exception as error:
        print(json.dumps({"status": "stopped", "error_type": type(error).__name__}, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
