#!/usr/bin/env python3
"""Post-score development diagnostics; never inference, selection or acceptance.

This helper is outside the frozen scientific modules. It refuses partial runs,
uses the existing scoring output, and exports aggregate contributions only.
"""
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import sys

sys.dont_write_bytecode = True
BASE = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(BASE), str(BASE / "src"), str(BASE / "round7/src")]

from opt_provider import ROOT, fingerprint, sha
from round4.src.artifacts import ArtifactStore, decode
from context_m import ROUND, source_pins
from run_m import record_name
from scoring_m import adapt_asa

TARGETS = ("weight", "energy", "fat", "carbs", "protein")
SCOPE = "posthoc_development_diagnostic_not_selection_or_acceptance"


def require(ok, message):
    if not ok:
        raise ValueError(message)


def vector(value):
    require(isinstance(value, dict) and set(value) == set(TARGETS), "five_targets_required")
    require(all(type(v) in (int, float) and math.isfinite(v) and v >= 0
                for v in value.values()), "invalid_target_value")
    return value


def close(a, b):
    return a is None and b is None or (type(a) in (int, float) and type(b) in (int, float)
        and math.isfinite(a) and math.isfinite(b) and math.isclose(a, b, rel_tol=1e-12, abs_tol=1e-9))


def errors(rows, labels, predictions, saved_stats=None):
    """All supplied rows stay in the denominator, including fallback records."""
    require(len({r["sample_id"] for r in rows}) == len(rows), "duplicate_diagnostic_row")
    values = {}
    for row in rows:
        sid = row["sample_id"]
        values[sid] = (vector(predictions[sid]), vector(labels[sid]["truth"]))
    n = len(rows)
    result = {"n": n, "groups": len({r["group_id"] for r in rows}), "targets": {}}
    require(saved_stats is None or saved_stats["n"] == n, "scored_population_changed")
    for target in TARGETS:
        signed = {r["sample_id"]: values[r["sample_id"]][0][target] - values[r["sample_id"]][1][target]
                  for r in rows}
        absolute = {sid: abs(v) for sid, v in signed.items()}
        total = sum(absolute.values())
        reference_mean = sum(values[r["sample_id"]][1][target] / n for r in rows) if n else None
        mae = sum(v / n for v in absolute.values()) if n else None
        per_unit = mae / reference_mean if reference_mean and mae is not None else None
        if saved_stats is not None:
            saved = saved_stats["metrics"][target]
            require(all(close(value, saved[key]) for key, value in
                        [("mae", mae), ("reference_mean", reference_mean), ("per_unit", per_unit)]),
                    "point_statistics_differ_from_existing_score")
        grouped = {}
        for row in rows:
            grouped[row["group_id"]] = grouped.get(row["group_id"], 0) + absolute[row["sample_id"]]

        def contributions(index, counts):
            ordered = sorted(index, key=lambda key: (-index[key], key))
            return {str(k): {"selected_n": min(k, len(ordered)), "population_n": len(ordered),
                            "absolute_error_sum": sum(index[s] for s in ordered[:k]),
                            "fraction_of_all_absolute_error": sum(index[s] for s in ordered[:k]) / total if total else None}
                    for k in counts}

        result["targets"][target] = {"mae": mae, "per_unit": per_unit,
            "reference_mean": reference_mean, "absolute_error_sum": total,
            "sum_signed_error": sum(signed.values()),
            "mean_signed_error": sum(signed.values()) / n if n else None,
            "over_n": sum(v > 0 for v in signed.values()),
            "under_n": sum(v < 0 for v in signed.values()),
            "equal_n": sum(v == 0 for v in signed.values()),
            "positive_error_sum": sum(v for v in signed.values() if v > 0),
            "negative_error_magnitude_sum": -sum(v for v in signed.values() if v < 0),
            "top_rows": contributions(absolute, (1, 5, 10)),
            "top_groups": contributions(grouped, (1, 5))}
    return result


def paired(rows, labels, baseline, candidate):
    result = {"n": len(rows), "direction": "M_absolute_error_minus_M0_absolute_error", "targets": {}}
    for target in TARGETS:
        deltas = [abs(vector(candidate[r["sample_id"]])[target] - labels[r["sample_id"]]["truth"][target])
                  - abs(vector(baseline[r["sample_id"]])[target] - labels[r["sample_id"]]["truth"][target])
                  for r in rows]
        result["targets"][target] = {"improved_n": sum(v < 0 for v in deltas),
            "worsened_n": sum(v > 0 for v in deltas), "equal_n": sum(v == 0 for v in deltas),
            "sum_absolute_error_difference": sum(deltas),
            "mae_difference": sum(deltas) / len(deltas) if deltas else None}
    return result


def mass_density(rows, labels, predictions):
    """Symmetric vector-level error identity, not an ingredient or causal audit."""
    result = {"population_n": len(rows), "decomposable_n": 0, "nonpositive_weight_n": 0,
        "formula": "error=(Wp-Wt)*(Dp+Dt)/2+(Dp-Dt)*(Wp+Wt)/2", "targets": {}}
    terms = {k: [] for k in TARGETS if k != "weight"}
    for row in rows:
        sid = row["sample_id"]
        pred, truth = vector(predictions[sid]), vector(labels[sid]["truth"])
        wp, wt = pred["weight"], truth["weight"]
        if wp <= 0 or wt <= 0:
            result["nonpositive_weight_n"] += 1
            continue
        result["decomposable_n"] += 1
        for k in terms:
            dp, dt = pred[k] / wp, truth[k] / wt
            mass, density = (wp - wt) * (dp + dt) / 2, (dp - dt) * (wp + wt) / 2
            require(close(mass + density, pred[k] - truth[k]), "mass_density_identity_failed")
            terms[k].append((mass, density, mass + density - (pred[k] - truth[k])))
    for k, values in terms.items():
        result["targets"][k] = {"mass_signed_sum": sum(v[0] for v in values),
            "density_signed_sum": sum(v[1] for v in values),
            "mass_mean_absolute_on_decomposable_rows": sum(abs(v[0]) for v in values) / len(values) if values else None,
            "density_mean_absolute_on_decomposable_rows": sum(abs(v[1]) for v in values) / len(values) if values else None,
            "max_identity_residual": max((abs(v[2]) for v in values), default=None)}
    result["complete_population_decomposition"] = result["decomposable_n"] == len(rows) and bool(rows)
    return result


def require_scored(round_dir=None):
    """Check prerequisites before any development-label loader is imported."""
    round_dir = ROUND if round_dir is None else round_dir
    for relative in ("runs/development/completion.json", "runs/scoring/results.json",
                     "development_checkpoint.json", "launch/automatic_followup.json"):
        path = round_dir / relative
        require(path.is_file() and not path.is_symlink(), "complete_scored_batch_required")
    follower = decode((round_dir / "launch/automatic_followup.json").read_bytes())
    require(follower.get("status") == "development_scored", "offline_follower_not_finished")


def save_diagnostic(round_dir, binding, aggregate, verify_sources):
    """Use the existing private artifact store, including ancestor symlink checks."""
    store = ArtifactStore(round_dir / "diagnostics/completed_m", binding, ["aggregate"],
                          verify_sources=verify_sources, root=round_dir)
    if (store.directory / "completion.json").exists():
        require(store.verify_completed() == {"aggregate": aggregate}, "diagnostic_recomputation_changed")
    else:
        store.finalize({"aggregate": aggregate})
    require(store.verify_completed() == {"aggregate": aggregate}, "diagnostic_seal_changed")


def run():
    require_scored()
    inputs = {}

    def read(relative):
        path = ROOT / relative
        require(path.resolve() == path and not path.is_symlink(), "diagnostic_symlink_rejected")
        raw = path.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        require(relative not in inputs or inputs[relative] == digest, "diagnostic_input_changed")
        inputs[relative] = digest
        return decode(raw)

    frozen = read("round7/prepared/freeze.json")
    require(source_pins() == frozen["source_files"], "frozen_sources_changed")
    require(sha(ROUND / "REVIEW.md") == frozen["review_sha256"], "frozen_review_changed")
    rows = [decode(line) for line in (ROOT / "data/cohorts/dev.jsonl").read_text().splitlines()]
    inputs["data/cohorts/dev.jsonl"] = sha(ROOT / "data/cohorts/dev.jsonl")
    require(inputs["data/cohorts/dev.jsonl"] == frozen["manifest_sha256"]
            and fingerprint(rows) == frozen["rows_sha256"], "manifest_changed")
    require(Counter(r["dataset"] for r in rows) == {"asa24": 99, "nutrition5k": 84}
            and len({r["sample_id"] for r in rows}) == 183, "both_full_populations_required")
    names = [record_name(p, r) for r in rows for p in ("M0", "M")] + ["service-proof"]
    store = ArtifactStore(ROUND / "runs/development", frozen, names,
        verify_sources=lambda: source_pins() == frozen["source_files"], root=ROUND)
    records = store.verify_completed()
    read("round7/runs/development/completion.json")
    score = read("round7/runs/scoring/results.json")
    checkpoint = read("round7/development_checkpoint.json")
    require(checkpoint == {k: v for k, v in score.items() if k != "service_proof"}
            and score["service_proof"] == records["service-proof"], "scoring_outputs_disagree")
    by_profile = {}
    for profile in ("M0", "M"):
        by_profile[profile] = [records[record_name(profile, row)] for row in rows]
        for row, record in zip(rows, by_profile[profile]):
            require(all(record[k] == row[k] for k in ("sample_id", "dataset", "group_id", "fold")),
                    "record_population_changed")
            vector(record["prediction"])
    # Labels are first read only after complete base and score prerequisites.
    fallbacks = read("round7/prepared/fallbacks.json")
    labels = read("data/cohorts/dev_labels.json")
    require(inputs["data/cohorts/dev_labels.json"] == fallbacks["labels_sha256"]
            and set(labels) == {r["sample_id"] for r in rows}, "development_labels_changed")
    catalog = read("data/catalog.json")
    require(inputs["data/catalog.json"] == frozen["catalog_sha256"], "catalog_changed")
    adapted = {p: {r["sample_id"]: r for r in adapt_asa(rows, labels, by_profile[p], catalog)}
               for p in by_profile}
    output = {"schema_version": 1, "scope": SCOPE, "arms": {},
        "existing_selection": score["selection"], "existing_common_exact": score["common_exact"],
        "new_service_usage": score["new_service_usage"], "api_calls": 0,
        "bootstrap_replicates": 0, "validation_opened": False,
        "new_profile_selected": False, "row_outputs_exported": False}
    for profile, index in adapted.items():
        arm = {}
        for dataset in ("asa24", "nutrition5k"):
            population = [r for r in rows if r["dataset"] == dataset]
            exact = [r for r in population if labels[r["sample_id"]]["food_code"] in index[r["sample_id"]]["final_codes"]] if dataset == "asa24" else population
            primary = {r["sample_id"]: index[r["sample_id"]]["conditional"]["prediction"] if dataset == "asa24"
                       else index[r["sample_id"]]["prediction"] for r in exact}
            full = {r["sample_id"]: index[r["sample_id"]]["prediction"] for r in population}
            saved = score["arms"][profile]["metrics"]["datasets"][dataset]
            arm[dataset] = {"primary": errors(exact, labels, primary, saved["primary"]),
                "full_serving": errors(population, labels, full, saved["e2e"] if dataset == "asa24" else saved["primary"]),
                "full_serving_mass_density_identity": mass_density(population, labels, full),
                "fallback_n": sum(index[r["sample_id"]]["fallback"] for r in population),
                "fallback_reasons": dict(Counter(index[r["sample_id"]]["fallback_reason"] or "none" for r in population)),
                "identity_status": dict(Counter(index[r["sample_id"]]["identity_status"] for r in population)),
                "portion_status": dict(Counter(index[r["sample_id"]]["portion_status"] for r in population)),
                "code_count_distribution": dict(Counter(str(len(index[r["sample_id"]]["final_codes"])) for r in population)),
                "fallback_error": errors([r for r in population if index[r["sample_id"]]["fallback"]], labels, full),
                "nonfallback_error": errors([r for r in population if not index[r["sample_id"]]["fallback"]], labels, full)}
        output["arms"][profile] = arm
    output["paired_full_serving"] = {ds: paired([r for r in rows if r["dataset"] == ds], labels,
        {sid: p["prediction"] for sid, p in adapted["M0"].items()},
        {sid: p["prediction"] for sid, p in adapted["M"].items()}) for ds in ("asa24", "nutrition5k")}
    cells = {k: [] for k in ("both", "M0_only", "M_only", "neither")}
    for row in [r for r in rows if r["dataset"] == "asa24"]:
        sid, code = row["sample_id"], labels[row["sample_id"]]["food_code"]
        a, b = (code in adapted[p][sid]["final_codes"] for p in ("M0", "M"))
        cells["both" if a and b else "M0_only" if a else "M_only" if b else "neither"].append(row)
    output["exact_membership"] = {k: {"n": len(v), "groups": len({r["group_id"] for r in v})} for k, v in cells.items()}
    output["paired_common_exact"] = paired(cells["both"], labels,
        {sid: (p.get("conditional") or {}).get("prediction") for sid, p in adapted["M0"].items()},
        {sid: (p.get("conditional") or {}).get("prediction") for sid, p in adapted["M"].items()})
    output["limitations"] = [
        "Repeated development selection is not independent validation; this diagnostic selects nothing.",
        "ASA conditional option and complete-serving E2E are distinct tasks with different denominators.",
        "Changed Exact populations cannot establish paired improvement; reuse existing common-Exact intervals.",
        "Mass/density terms describe whole-vector errors, not recognition, ingredient omission or causal contributions.",
        "Absolute term magnitudes need not add to MAE. Nonpositive weights stay in all metrics but cannot be decomposed.",
        "Fallbacks remain in all full-serving metrics. No ingredient-ID catalog, oracle or new confidence interval is introduced."]
    require(source_pins() == frozen["source_files"] and store.verify_completed() == records, "base_changed_during_diagnostic")
    require(all(sha(ROOT / p) == h for p, h in inputs.items()), "input_changed_during_diagnostic")
    output["input_sha256"] = inputs
    output["diagnostic_source_sha256"] = sha(Path(__file__))
    binding = {"scope": SCOPE, "input_sha256": inputs,
        "diagnostic_source_sha256": output["diagnostic_source_sha256"]}
    def unchanged():
        return (source_pins() == frozen["source_files"]
                and sha(Path(__file__)) == output["diagnostic_source_sha256"]
                and all(sha(ROOT / p) == h for p, h in inputs.items()))
    save_diagnostic(ROUND, binding, output, unchanged)
    return {"status": "completed_development_diagnostic", "api_calls": 0, "validation_opened": False}


if __name__ == "__main__":
    try:
        print(json.dumps(run(), allow_nan=False))
    except Exception as exc:
        print(json.dumps({"status": "diagnostic_refused", "error_type": type(exc).__name__}))
        raise SystemExit(1)
