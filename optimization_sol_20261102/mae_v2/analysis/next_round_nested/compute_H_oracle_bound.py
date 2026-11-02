"""Completed-H development oracle diagnostic; never a deployable calibration.

For every original fold and target independently, use that fold's own truth to
choose the minimum-MAE multiplier from the registered shrunk grid. This leaks
held-out truth deliberately and allows five unrelated target multipliers. It
therefore bounds below any one-shared-mass-factor-per-fold method on the same H
predictions and grid, including a strictly nested training-only calibration.
It does not bound a changed estimator, gallery, density, or factor domain.

Only completed H artifacts and the frozen development manifest/labels are read.
No images, validation files, inference driver, provider, or network are used.
Outputs are aggregates only; oracle row predictions remain in memory.
Run with --self-test for synthetic checks only, or without arguments to write
the fixed diagnostic JSON (same-content reruns allowed, differing overwrite
refused). Source and run artifacts are never modified.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
RUN = "round3/runs/H/"
FINAL_FILES = ("records_sealed.json", "predictions.json", "metrics.json",
               "usage.json", "binding.json", "example_assignments.json")
OUTPUT = "analysis/next_round_nested/H_oracle_bound.json"
KEYS = ("weight", "energy", "fat", "carbs", "protein")
GRID = tuple(range(800, 1251))


def fingerprint(value):
    encoded = json.dumps(value, sort_keys=True, ensure_ascii=False,
                         allow_nan=False, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def applied_factor(grid_integer):
    return 1.0 + 0.5 * (grid_integer / 1000.0 - 1.0)


def best_factor(predictions, truths):
    """Exhaustive independent target oracle; tie: closest to 1, then smaller."""
    if not predictions or len(predictions) != len(truths):
        raise ValueError("Oracle requires equal nonempty vectors")
    if any(isinstance(x, bool) or not isinstance(x, (int, float))
           or not math.isfinite(x) or x < 0 for x in [*predictions, *truths]):
        raise ValueError("Oracle values must be finite nonnegative numbers")

    def loss(integer):
        factor = applied_factor(integer)
        return math.fsum(abs(factor * p - y) for p, y in zip(predictions, truths))

    integer = min(GRID, key=lambda x: (loss(x), abs(x - 1000), x))
    return {"unshrunk_factor": integer / 1000.0,
            "applied_factor": applied_factor(integer),
            "fold_mae": loss(integer) / len(predictions)}


class Inputs:
    def __init__(self, root):
        self.root = root
        self.hashes = {}

    def read(self, relative):
        path = self.root / relative
        if path.is_symlink() or path.resolve() != path or not path.is_file():
            raise ValueError("Input must be a regular in-root file")
        raw = path.read_bytes()
        self.hashes[relative] = hashlib.sha256(raw).hexdigest()
        return raw

    def json(self, relative):
        return json.loads(self.read(relative))

    def require_hash(self, relative, expected):
        self.read(relative)
        if self.hashes[relative] != expected:
            raise ValueError("Bound input hash differs: " + relative)

    def unchanged(self):
        before = dict(self.hashes)
        for relative, expected in before.items():
            self.require_hash(relative, expected)


def load_completed(root):
    inputs = Inputs(root)
    # This first read is a hard gate: partial predictions/labels are not read.
    completion = inputs.json(RUN + "completion.json")
    if (completion.get("candidate") != "H" or completion.get("n") != 84
            or completion.get("groups") != 78
            or completion.get("validation_opened") is not False
            or set(completion.get("artifact_sha256", {})) != set(FINAL_FILES)):
        raise ValueError("H must have a complete 84-row/78-group completion marker")
    for name in FINAL_FILES:
        inputs.require_hash(RUN + name, completion["artifact_sha256"][name])
    binding = inputs.json(RUN + "binding.json")
    if (completion["binding_sha256"] != fingerprint(binding)
            or binding.get("candidate") != "H"
            or binding.get("validation_access") is not False):
        raise ValueError("H completion binding differs")
    for name in ("data/cohorts/dev.jsonl", "data/cohorts/dev_labels.json",
                 "data/cohorts/dev_freeze.json", "src/opt_metrics.py"):
        inputs.require_hash(name, binding["input_sha256"][name])
    freeze = inputs.json("data/cohorts/dev_freeze.json")
    for name in ("data/cohorts/dev.jsonl", "data/cohorts/dev_labels.json"):
        if inputs.hashes[name] != freeze["artifacts"][name]:
            raise ValueError("Development freeze differs")
    all_rows = [json.loads(line) for line in inputs.read("data/cohorts/dev.jsonl").splitlines()]
    rows = [r for r in all_rows if r["dataset"] == "nutrition5k"]
    if (len(all_rows) != 183 or len(rows) != 84
            or len({r["sample_id"] for r in rows}) != 84
            or len({r["group_id"] for r in rows}) != 78
            or {r["fold"] for r in rows} != set(range(5))
            or any(r.get("split") != "dev" for r in all_rows)
            or fingerprint(rows) != binding["manifest_sha256"]):
        raise ValueError("Frozen development population differs")
    group_folds = {}
    for row in rows:
        if group_folds.setdefault(row["group_id"], row["fold"]) != row["fold"]:
            raise ValueError("One group crosses folds")
    seal = inputs.json(RUN + "records_sealed.json")
    assignments = inputs.json(RUN + "example_assignments.json")
    if (set(seal) != {r["sample_id"] for r in rows}
            or set(assignments) != set(seal)
            or fingerprint(assignments) != binding["example_assignments_sha256"]):
        raise ValueError("H external seal or assignment population differs")
    names = {fingerprint(r["sample_id"])[:24] + ".json" for r in rows}
    if {p.name for p in (root / RUN / "records").iterdir()} != names:
        raise ValueError("H record file inventory differs")
    records = []
    for row in rows:
        sid = row["sample_id"]
        name = RUN + "records/" + fingerprint(sid)[:24] + ".json"
        inputs.require_hash(name, seal[sid])
        envelope = inputs.json(name)
        record = envelope["record"]
        if (set(envelope) != {"binding_sha256", "record_sha256", "record"}
                or envelope["binding_sha256"] != fingerprint(binding)
                or envelope["record_sha256"] != fingerprint(record)
                or any(record.get(k) != row[k] for k in ("sample_id", "dataset", "group_id", "fold"))
                or record.get("example_assignment_sha256") != fingerprint(assignments[sid])
                or fingerprint(record.get("example_proof")) != fingerprint(assignments[sid])):
            raise ValueError("H record envelope or assignment differs")
        records.append(record)
    if fingerprint(inputs.json(RUN + "predictions.json")) != fingerprint(records):
        raise ValueError("H aggregate differs from externally sealed records")
    labels = inputs.json("data/cohorts/dev_labels.json")
    return inputs, rows, labels, records


def build_diagnostic(root=ROOT):
    inputs, rows, labels, records = load_completed(root)
    sys.path.insert(0, str(root / "src"))
    import opt_metrics

    actual = opt_metrics.evaluate(rows, labels, records, bootstrap=0)["datasets"]["nutrition5k"]
    saved = inputs.json(RUN + "metrics.json")
    if (saved.get("candidate") != "H" or saved.get("validation_opened") is not False
            or saved.get("calibration_applied") is not False
            or saved.get("nutrition5k") != actual):
        raise ValueError("H full-population metrics do not reproduce exactly")
    oracle_records = deepcopy(records)
    fold_results = []
    for fold in range(5):
        indices = [i for i, row in enumerate(rows) if row["fold"] == fold]
        results = {}
        for key in KEYS:
            results[key] = best_factor(
                [records[i]["prediction"][key] for i in indices],
                [labels[rows[i]["sample_id"]]["truth"][key] for i in indices])
            for i in indices:
                oracle_records[i]["prediction"][key] *= results[key]["applied_factor"]
        fold_results.append({"fold": fold, "n": len(indices),
                             "groups": len({rows[i]["group_id"] for i in indices}),
                             "target_oracles": results})
    oracle = opt_metrics.evaluate(rows, labels, oracle_records, bootstrap=0)["datasets"]["nutrition5k"]
    actual_metrics = actual["primary"]["metrics"]
    oracle_metrics = oracle["primary"]["metrics"]
    if any(oracle_metrics[k]["mae"] > actual_metrics[k]["mae"] + 1e-12 for k in KEYS):
        raise ValueError("Oracle worse than included identity factor")
    passed = lambda metrics: sum(int(metrics[k][field]) for k in KEYS
                                 for field in ("pass_mae", "pass_per_unit"))
    result = {
        "schema_version": 1,
        "scope": "development_optimistic_oracle_diagnostic_not_candidate_or_acceptance",
        "candidate_source": "H", "n": 84, "groups": 78,
        "fallback_n": actual["fallback_n"], "repair_success_n": actual["repair_success_n"],
        "oracle_uses_same_fold_truth": True,
        "target_factors_independent": True,
        "method": {
            "unshrunk_grid": {"minimum": 0.8, "maximum": 1.25, "step": 0.001, "count": 451},
            "shrinkage_toward_one": 0.5,
            "applied_grid": {"minimum": 0.9, "maximum": 1.125, "step": 0.0005, "count": 451},
            "optimization": "minimum sum absolute error separately for each original fold and target",
            "tie_break": "closest unshrunk factor to 1, then smaller factor",
            "aggregation": "all 84 rows; per-unit MAE divides by full-population truth mean",
            "acceptance_comparison": "full precision, no rounded pass decisions",
            "lower_bound_reason": "Each fold/target oracle searches a superset of any one shared mass factor per fold on the same grid and fixed H predictions.",
        },
        "actual_H": {"metrics": actual_metrics, "passed_checks": passed(actual_metrics), "total_checks": 10},
        "oracle_bound": {"metrics": oracle_metrics, "passed_checks": passed(oracle_metrics), "total_checks": 10},
        "fold_oracles": fold_results,
        "restricted_shared_mass_can_reach_all_10_on_fixed_H": False if passed(oracle_metrics) < 10 else None,
        "conclusion": ("Even independent target-wise same-fold oracles cannot pass all 10 checks. A nested training-only shared mass factor on this grid cannot do so on these fixed H predictions."
                       if passed(oracle_metrics) < 10 else
                       "The optimistic oracle passes; this does not establish that a shared training-only factor can pass."),
        "limitations": ["Not an actual calibrated candidate or unbiased estimate: held-out truth directly selects factors.",
                        "Independent target multipliers need not preserve item mass/nutrient consistency.",
                        "Does not exclude changed predictions, composition/densities, a wider factor grid, or sample-specific calibration."],
        "verification": {"completed_H_required_before_predictions_or_labels": True,
                         "externally_sealed_records_verified": 84,
                         "saved_full_population_metrics_match_exactly": True,
                         "images_opened": False, "validation_opened": False, "api_calls": 0,
                         "oracle_row_predictions_exported": False},
    }
    script = Path(__file__).resolve().relative_to(root).as_posix()
    inputs.read(script)
    result["input_sha256"] = {k: v for k, v in inputs.hashes.items() if not k.startswith(RUN + "records/")}
    inputs.unchanged()
    return result


def self_test():
    assert len(GRID) == 451 and applied_factor(800) == 0.9 and applied_factor(1250) == 1.125
    assert best_factor([100.0], [200.0])["applied_factor"] == 1.125
    assert best_factor([100.0], [1.0])["applied_factor"] == 0.9
    assert best_factor([100.0], [100.0])["applied_factor"] == 1.0
    assert best_factor([0.0], [12.0])["applied_factor"] == 1.0
    assert best_factor([100.0], [102.5])["applied_factor"] == 1.025
    # Independent target/fold factors strictly improve on any shared factor here.
    a = best_factor([100.0], [90.0])
    b = best_factor([100.0], [112.5])
    assert a["fold_mae"] == b["fold_mae"] == 0.0
    assert min(abs(100 * applied_factor(i) - 90) + abs(100 * applied_factor(i) - 112.5)
               for i in GRID) > 0
    for predictions, truths in (([], []), ([1], []), ([True], [1]), ([math.nan], [1]), ([-1], [1])):
        try:
            best_factor(predictions, truths)
        except ValueError:
            pass
        else:
            raise AssertionError("Invalid synthetic input accepted")
    print("PASS: synthetic grid, bounds, identity, ties, relaxation, and invalid-value checks")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return
    result = build_diagnostic()
    path = ROOT / OUTPUT
    payload = json.dumps(result, ensure_ascii=False, allow_nan=False, indent=2) + "\n"
    if path.exists():
        if path.is_symlink() or path.read_text() != payload:
            raise ValueError("Refusing to overwrite a different diagnostic")
    else:
        with path.open("x") as handle:
            handle.write(payload)
    print(json.dumps({"output": OUTPUT, "actual_mae": {k: result["actual_H"]["metrics"][k]["mae"] for k in KEYS},
                      "oracle_mae": {k: result["oracle_bound"]["metrics"][k]["mae"] for k in KEYS},
                      "oracle_passed_checks": result["oracle_bound"]["passed_checks"]}, allow_nan=False))


if __name__ == "__main__":
    main()
