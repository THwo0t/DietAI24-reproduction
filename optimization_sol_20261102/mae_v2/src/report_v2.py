#!/usr/bin/env python3
"""Render an aggregate-only English v2 report without importing inference code."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
NAMES = ("baseline", "asa-retrieval-portion", "examples-2", "A", "B", "C", "D", "E")
VALIDATION_RUNS = ("baseline", "optimized-asa24", "optimized-nutrition5k", "optimized-nutrition5k-base")
KEYS = ("weight", "energy", "fat", "carbs", "protein")
DATASETS = ("asa24", "nutrition5k")
TARGET_NAMES = dict(zip(KEYS, ("Weight (g)", "Energy (kcal)", "Total Fat (g)", "Carbohydrate (g)", "Protein (g)")))
OUTPUT_MARKDOWN = "reports/DietAI24_MAE_v2_Report.md"
OUTPUT_SNAPSHOT = "reports/DietAI24_MAE_v2_Report.json"
OFFICIAL_EMBEDDING_PRICE = {
    "model": "text-embedding-3-large", "route": "https://api.openai.com/v1/embeddings",
    "verified_on": "2026-11-02", "usd_per_million_input_tokens": 0.13,
    "source_url": "https://developers.openai.com/api/docs/models/text-embedding-3-large",
    "source_title": "OpenAI text-embedding-3-large model documentation",
    "cost_classification": "estimate_not_invoice", "third_party_chat_pricing_applicable": False,
}
FIXED_INPUTS = {
    "config/experiment.json", "config/candidates.json", "analysis/paper_targets.json",
    "analysis/historical_summary.json", "analysis/diagnostics_v2.json", "data/cohorts/dev_freeze.json",
    "evidence/audit_summary.json", "evidence/preparation_summary.json", "evidence/official-embedding-price.json",
    "runs/development/candidates.json", "runs/development/selection.json",
    "runs/development/completion.json", "runs/development/round2_decision.json",
    "runs/validation/metrics.json", "runs/validation/completion.json",
}
ALLOWED_INPUTS = FIXED_INPUTS | {
    f"runs/development/{name}/{kind}.json" for name in (*NAMES, "reference-identities")
    for kind in ("metrics", "status", "usage", "calibration-summary")
} | {f"runs/validation/{name}/{kind}.json" for name in VALIDATION_RUNS for kind in ("status", "usage")}


class AggregateReader:
    """Exact file allowlist, no globbing, symlinks, credentials or row records."""
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.hashes, self.missing = {}, []

    def read(self, relative, required=False):
        if relative not in ALLOWED_INPUTS:
            raise ValueError("Report input is not on the aggregate allowlist")
        path = self.root / relative
        if path.resolve() != path or self.root not in path.resolve().parents:
            raise ValueError("Report inputs cannot use symlinks or escape the study root")
        if not path.is_file():
            if required:
                raise ValueError("A required aggregate report input is missing")
            self.missing.append(relative)
            return None
        blob = path.read_bytes()
        value = json.loads(blob, parse_constant=lambda _: (_ for _ in ()).throw(ValueError("Nonfinite JSON aggregate")))
        self.hashes[relative] = hashlib.sha256(blob).hexdigest()
        return value


def number(value, integer=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
        return None
    if integer and int(value) != value:
        return None
    return int(value) if integer else value


def nsum(values):
    values = [number(v) for v in values]
    return sum(v for v in values if v is not None)


def signed_number(value):
    return value if not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value) else None


def project_score(value):
    if not isinstance(value, dict):
        return None
    return {"n": number(value.get("n"), True), "available_n": number(value.get("available_n"), True),
            "metrics": {key: {stat: number(value.get("metrics", {}).get(key, {}).get(stat))
                              for stat in ("mae", "per_unit", "reference_mean")} for key in KEYS}}


def project_common_exact(source):
    if not isinstance(source, dict):
        return None
    result = {"diagnostic_only": source.get("diagnostic_only") is True,
              **{k: number(source.get(k), True) for k in ("population_n", "n", "groups", "baseline_exact_n",
                  "selected_exact_n", "baseline_only_exact_n", "selected_only_exact_n")},
              "baseline": project_score(source.get("baseline")), "selected": project_score(source.get("selected"))}
    boot = source.get("paired_bootstrap") or {}
    intervals = None
    complete = all((result.get(arm) or {}).get("available_n") == result["n"] for arm in ("baseline", "selected"))
    if (result["groups"] or 0) >= 2 and complete and isinstance(boot.get("intervals"), dict):
        intervals = {key: {"low": signed_number(boot["intervals"].get(key, {}).get("low")),
                           "high": signed_number(boot["intervals"].get(key, {}).get("high")),
                           "valid_replicates": number(boot["intervals"].get(key, {}).get("valid_replicates"), True)}
                     for key in (k + "." + stat for k in KEYS for stat in ("mae", "per_unit"))}
    result["paired_bootstrap"] = {"groups": number(boot.get("groups"), True),
        "replicates": number(boot.get("replicates"), True), "intervals": intervals,
        "reason": boot.get("reason") if boot.get("reason") in (
            "fewer_than_two_groups", "missing_conditional_prediction_on_fixed_intersection") else None}
    return result


def project_diagnostics(raw):
    if not isinstance(raw, dict):
        return None
    comparison = raw.get("same_population_comparison", {})
    boot = comparison.get("paired_bootstrap", {})
    oracle = raw.get("oracle_weight_diagnostic", {})
    intervals = {}
    for key in (k + "." + stat for k in KEYS for stat in ("mae", "per_unit")):
        interval = (boot.get("intervals") or {}).get(key, {})
        intervals[key] = {"low": signed_number(interval.get("low")), "high": signed_number(interval.get("high")),
                          "valid_replicates": number(interval.get("valid_replicates"), True)}
        if (number(boot.get("groups"), True) or 0) < 2:
            intervals[key] = {"low": None, "high": None, "valid_replicates": 0}
    return {"asa24_common_exact_comparison": project_common_exact(raw.get("asa24_common_exact_comparison")),
            "median_baseline": {"score": project_score(raw.get("median_baseline", {}).get("score"))},
            "same_population_comparison": {"n": number(comparison.get("n"), True),
                "baseline": project_score(comparison.get("baseline")), "selected": project_score(comparison.get("selected")),
                "selected_mean_signed_error": {k: signed_number(comparison.get("selected_mean_signed_error", {}).get(k)) for k in KEYS},
                "paired_bootstrap": {"groups": number(boot.get("groups"), True), "replicates": number(boot.get("replicates"), True),
                                     "intervals": intervals}},
            "oracle_weight_diagnostic": {"uses_reference_weight": oracle.get("uses_reference_weight") is True,
                "not_a_model_or_acceptance_result": oracle.get("not_a_model_or_acceptance_result") is True,
                **{k: number(oracle.get(k), True) for k in ("population_n", "scored_n", "excluded_nonpositive_weight_n")},
                "score": project_score(oracle.get("score"))}}


def limits_from(paper):
    limits = {}
    for ds in DATASETS:
        limits[ds] = {}
        for key, name in TARGET_NAMES.items():
            entry = paper["datasets"][ds]["metrics"][name]
            limits[ds][key] = {"mae": entry["threshold_per_dish"], "per_unit": entry["threshold_per_unit"],
                               "paper_mae": entry["paper_per_dish"], "paper_per_unit": entry["paper_per_unit"]}
            if any(number(v) is None or v <= 0 for v in limits[ds][key].values()):
                raise ValueError("Paper thresholds must be positive finite numbers")
    return limits


def project_metrics(raw, limits, issues, scope):
    if not isinstance(raw, dict) or not isinstance(raw.get("datasets"), dict):
        return None
    out = {"datasets": {}, "checks": []}
    count_fields = ("n", "groups", "exact_n", "exact_groups", "first_n", "retrieval_exact_n", "native_complete_n",
                    "complete_n", "fallback_n", "repair_success_n", "method_fallback_n", "enhancement_native_n",
                    "conditional_fallback_n", "conditional_missing_n", "e2e_fallback_n")
    for ds in DATASETS:
        source = raw["datasets"].get(ds)
        if not isinstance(source, dict):
            continue
        data = {k: number(source.get(k), integer=True) for k in count_fields}
        for branch in ("primary", "e2e", "native_subset", "complete_subset"):
            value = source.get(branch)
            if not isinstance(value, dict):
                continue
            data[branch] = {"n": number(value.get("n"), integer=True),
                            "available_n": number(value.get("available_n"), integer=True), "metrics": {}}
            for key in KEYS:
                metric = value.get("metrics", {}).get(key, {})
                entry = {"reference_mean": number(metric.get("reference_mean"))}
                for statistic in ("mae", "per_unit"):
                    actual = number(metric.get(statistic))
                    if metric.get(statistic) is not None and actual is None:
                        issues.append(f"{scope}: {ds}/{key}/{statistic} is not a finite nonnegative aggregate")
                    threshold = limits[ds][key][statistic]
                    entry.update({statistic: actual, "threshold_" + statistic: threshold,
                                  "pass_" + statistic: actual is not None and actual <= threshold})
                    stored = metric.get("threshold_" + statistic)
                    if stored is not None and stored != threshold:
                        issues.append(f"{scope}: {ds}/{key}/{statistic} stored threshold differs from registered limit")
                    if branch == "primary":
                        out["checks"].append({"dataset": ds, "target": key, "statistic": statistic,
                            "value": actual, "threshold": threshold, "pass": entry["pass_" + statistic],
                            "ratio_to_threshold": actual / threshold if actual is not None else None,
                            "reduction_required": max(0, actual - threshold) if actual is not None else None,
                            "reduction_fraction": max(0, 1 - threshold / actual) if actual else (0 if actual == 0 else None)})
                data[branch]["metrics"][key] = entry
        n, hits = data.get("n"), data.get("exact_n")
        for field in ("native_complete_n", "complete_n", "fallback_n", "repair_success_n", "method_fallback_n"):
            count = data.get(field)
            data[field.removesuffix("_n") + "_rate"] = count / n if n and count is not None else None
        if ds == "asa24":
            valid = n is not None and n > 0 and hits is not None and hits <= n
            data.update(exact_rate=hits / n if valid else None,
                        minimum_exact_n=(15 * n + 99) // 100 if n else None,
                        former_minimum_exact_n=(18 * n + 99) // 100 if n else None,
                        recognition_pass=bool(valid and hits >= (15 * n + 99) // 100),
                        former_recognition_pass=bool(valid and hits >= (18 * n + 99) // 100))
            data.update({k: number(source.get(k)) for k in ("first_rate", "retrieval_exact_rate", "average_final_code_count")})
            data["by_size"] = {}
            for size, sized in source.get("by_size", {}).items():
                if size not in ("smallest", "medium", "largest"):
                    continue
                data["by_size"][size] = {**{k: number(sized.get(k), True) for k in ("n", "exact_n", "first_n")},
                    **{k: number(sized.get(k)) for k in ("exact_rate", "first_rate")},
                    "conditional": project_score(sized.get("conditional")), "e2e": project_score(sized.get("e2e"))}
            if "primary" in data and data["primary"]["n"] != hits:
                issues.append(f"{scope}: ASA24 Exact and primary populations differ")
        elif "primary" in data and data["primary"]["n"] != n:
            issues.append(f"{scope}: Nutrition5k primary population does not include every row")
        if "primary" in data and data["primary"].get("available_n") != data["primary"].get("n"):
            issues.append(f"{scope}: primary predictions do not cover the full scored population")
        boot = source.get("bootstrap")
        if isinstance(boot, dict):
            data["bootstrap"] = {"replicates": number(boot.get("replicates"), True),
                                 "confidence": number(boot.get("confidence")),
                                 "group_count": number(boot.get("group_count", data["groups"]), True),
                                 "empty_exact_replicates": number(boot.get("empty_exact_replicates"), True), "intervals": {}}
            for key in [f"{k}.{s}" for k in KEYS for s in ("mae", "per_unit")] + ["exact_rate", "first_rate"]:
                interval = boot.get("intervals", {}).get(key)
                if isinstance(interval, dict):
                    data["bootstrap"]["intervals"][key] = {
                        k: number(interval.get(k), integer=k == "valid_replicates")
                        for k in ("low", "high", "valid_replicates")}
                    if (data["bootstrap"]["group_count"] or 0) < 2:
                        data["bootstrap"]["intervals"][key] = {"low": None, "high": None, "valid_replicates": 0}
        out["datasets"][ds] = data
    out["passed_checks"] = sum(c["pass"] for c in out["checks"])
    out["total_checks"] = 20
    out["all_mae_pass"] = len(out["checks"]) == 20 and out["passed_checks"] == 20
    out["recognition_pass"] = out["datasets"].get("asa24", {}).get("recognition_pass", False)
    out["joint_pass"] = out["all_mae_pass"] and out["recognition_pass"]
    reported = number(raw.get("passed_checks"), True)
    if reported is not None and reported != out["passed_checks"]:
        issues.append(f"{scope}: reported passing count differs from recalculated aggregate values")
    return out


def counts_only(raw):
    if not isinstance(raw, dict):
        return {}
    allowed = ("asa24_images", "asa24_groups", "nutrition5k_images", "nutrition5k_groups",
               "nutrition5k_target_images", "nutrition5k_retained_original_images", "nutrition5k_max_group_fraction")
    out = {k: number(raw.get(k)) for k in allowed if k in raw}
    for key in ("nutrition5k_retired_counts", "nutrition5k_group_size_histogram"):
        value = raw.get(key)
        if isinstance(value, dict):
            out[key] = {k: number(v, True) for k, v in value.items()
                        if re.fullmatch(r"[a-z0-9_]+", k) and number(v, True) is not None}
    return out


def aggregate_usage(reader, phase, names):
    runs, totals = [], {role: dict.fromkeys(("requests", "errors", "prompt_tokens", "completion_tokens", "reasoning_tokens", "total_tokens"), 0)
                        for role in ("chat", "embedding")}
    estimated, available = 0.0, 0
    for name in names:
        saved = reader.read(f"runs/{phase}/{name}/usage.json")
        if not isinstance(saved, dict):
            continue
        providers = {}
        for role, target in totals.items():
            providers[role] = {}
            for key in target:
                value = number(saved.get("providers", {}).get(role, {}).get(key), True)
                providers[role][key] = value
                target[key] += value or 0
        value = number(saved.get("official_embedding_estimated_usd"))
        if value is not None:
            estimated += value
            available += 1
        runs.append({"run": name, "providers": providers, "official_embedding_estimated_usd": value})
    return {"runs": runs, "providers": totals, "aggregate_run_count": len(runs),
            "official_embedding_estimated_usd": estimated if available else None,
            "third_party_cost_usd": None, "combined_actual_cost_usd": None}


def build_snapshot(root=ROOT):
    reader = AggregateReader(root)
    issues = []
    paper = reader.read("analysis/paper_targets.json", required=True)
    limits = limits_from(paper)
    experiment = reader.read("config/experiment.json") or {}
    registry = reader.read("config/candidates.json") or {}
    if any(name not in ("A", "B", "C", "D", "E") for name in registry):
        raise ValueError("Unregistered component candidate in report configuration")
    freeze = reader.read("data/cohorts/dev_freeze.json") or {}
    audit = reader.read("evidence/audit_summary.json") or {}
    prepared = reader.read("evidence/preparation_summary.json")
    latest = prepared or audit
    cohorts = {"development": counts_only(freeze.get("counts") or latest.get("development", {})),
               "validation": counts_only(latest.get("validation", {})),
               "validation_ready": latest.get("validation_ready") is True,
               "development_ready": latest.get("development_ready") is True}
    history = reader.read("analysis/historical_summary.json") or {}
    historical = {"v1_development": project_metrics(history.get("v1_development"), limits, issues, "historical v1"),
                  "archived_sol": {}}
    historical_pass = 0
    for ds, source in history.get("historical_sol", {}).items():
        if ds not in DATASETS or not isinstance(source, dict):
            continue
        projected = {"total_records": number(source.get("total_records"), True),
                     "evaluated_records": number(source.get("evaluated_records"), True), "metrics": {}}
        for key, label in TARGET_NAMES.items():
            metric = source.get("metrics", {}).get(label, {})
            projected["metrics"][key] = {"mae": number(metric.get("historical_sol_per_dish")),
                                          "per_unit": number(metric.get("historical_sol_per_unit"))}
            for stat, actual in projected["metrics"][key].items():
                historical_pass += actual is not None and actual <= limits[ds][key][stat]
        historical["archived_sol"][ds] = projected
    historical["archived_sol_passed_checks"] = historical_pass if len(historical["archived_sol"]) == 2 else None
    saved_candidates = reader.read("runs/development/candidates.json") or []
    if not isinstance(saved_candidates, list):
        raise ValueError("Candidate aggregate must be a list")
    by_name = {}
    for candidate in saved_candidates:
        name = candidate.get("name")
        if name not in NAMES or name in by_name:
            raise ValueError("Unknown or duplicated report candidate")
        by_name[name] = candidate
    selection = reader.read("runs/development/selection.json") or {}
    for profile in selection.get("profiles", {}).values():
        name = profile.get("name")
        if name not in NAMES:
            raise ValueError("Selected profile is unregistered")
        by_name.setdefault(name, profile)
    candidates = []
    for name in NAMES:
        status = reader.read(f"runs/development/{name}/status.json") or {}
        raw = reader.read(f"runs/development/{name}/metrics.json")
        calibration = reader.read(f"runs/development/{name}/calibration-summary.json") or {}
        saved = by_name.get(name, {})
        raw = raw or calibration.get("raw_metrics")
        retained = saved.get("metrics") or (calibration.get("calibrated_metrics") if calibration.get("calibration_enabled") else raw)
        if not (status or raw or saved or calibration):
            continue
        candidates.append({"name": name, "status": status.get("status") if status.get("status") in
                           ("running", "completed", "interrupted", "failed") else "aggregate_available",
                           "raw_metrics": project_metrics(raw, limits, issues, name + " raw"),
                           "retained_metrics": project_metrics(retained, limits, issues, name + " retained"),
                           "calibration_enabled": bool(saved.get("calibration_enabled", saved.get("calibrated", calibration.get("calibration_enabled", False)))),
                           "mass_factor": number(calibration.get("mass_factor")), "raw_factor": number(calibration.get("raw_factor")),
                           "estimated_chat_calls": number(saved.get("estimated_chat_calls")),
                           "calibrated_metrics": project_metrics(calibration.get("calibrated_metrics"), limits, issues, name + " calibration comparison")})
    completion = reader.read("runs/development/completion.json") or {}
    diagnostics = project_diagnostics(reader.read("analysis/diagnostics_v2.json")) if completion.get("status") in (
        "ready_for_review", "development_targets_not_met") else None
    if diagnostics:
        comparison = diagnostics["same_population_comparison"]
        expected_n = cohorts["development"].get("nutrition5k_images")
        if any(n != expected_n for n in (comparison.get("n"), (comparison.get("baseline") or {}).get("n"),
               (comparison.get("selected") or {}).get("n"), (diagnostics["median_baseline"].get("score") or {}).get("n"))):
            issues.append("development diagnostics: common image population differs from the development freeze")
            diagnostics = None
    selected = project_metrics(selection.get("metrics"), limits, issues, "selected development")
    if diagnostics and diagnostics.get("asa24_common_exact_comparison"):
        common = diagnostics["asa24_common_exact_comparison"]
        population, n, groups = common.get("population_n"), common.get("n"), common.get("groups")
        counts = [common.get(k) for k in ("baseline_exact_n", "selected_exact_n")]
        valid = (common["diagnostic_only"] and population is not None
                 and population == cohorts["development"].get("asa24_images")
                 and n is not None and groups is not None and 0 <= groups <= n <= population
                 and (groups == 0) == (n == 0)
                 and all(v is not None and n <= v <= population for v in counts)
                 and common["baseline_only_exact_n"] == common["baseline_exact_n"] - n
                 and common["selected_only_exact_n"] == common["selected_exact_n"] - n
                 and all((common.get(arm) or {}).get("n") == n for arm in ("baseline", "selected"))
                 and common["paired_bootstrap"]["groups"] == groups)
        if selected and common["selected_exact_n"] != selected["datasets"].get("asa24", {}).get("exact_n"):
            valid = False
        if not valid:
            issues.append("ASA24 common Exact diagnostic: population or diagnostic scope is inconsistent")
            diagnostics["asa24_common_exact_comparison"] = None
    profiles = {ds: value["name"] for ds, value in selection.get("profiles", {}).items() if ds in DATASETS}
    decision = reader.read("runs/development/round2_decision.json") or {}
    dev = {"status": completion.get("status") if completion.get("status") in ("ready_for_review", "development_targets_not_met")
           else ("development_in_progress" if candidates or selection else "development_not_started"),
           "metrics": selected, "profiles": profiles, "candidates": candidates,
           "registered_candidates_exhausted": completion.get("registered_candidates_exhausted") is True,
           "expansion": {k: decision.get(k) is True for k in ("D", "E")}}
    formal_completion = reader.read("runs/validation/completion.json") or {}
    formal_saved = reader.read("runs/validation/metrics.json")
    formal = {"status": "not_run_or_not_completed", "metrics": None, "aggregate_integrity_verified": False}
    if formal_saved is not None and formal_completion.get("status") != "completed":
        formal["status"] = "partial_aggregates_without_completion"
    elif formal_completion.get("status") == "completed":
        before = len(issues)
        metrics = {arm: project_metrics((formal_saved or {}).get(arm), limits, issues, "formal " + arm)
                   for arm in ("baseline", "optimized")}
        expected = {"asa24": cohorts["validation"].get("asa24_images", 78), "nutrition5k": 200}
        for arm, values in metrics.items():
            if values is None or len(values["checks"]) != 20:
                issues.append(f"formal {arm}: a complete twenty-check aggregate is missing")
                continue
            for ds, n in expected.items():
                if values["datasets"].get(ds, {}).get("n") != n:
                    issues.append(f"formal {arm}: registered {ds} image population differs")
                expected_groups = cohorts["validation"].get(ds + "_groups")
                if expected_groups is not None and values["datasets"].get(ds, {}).get("groups") != expected_groups:
                    issues.append(f"formal {arm}: registered {ds} association-group count differs")
        if metrics["optimized"] and formal_completion.get("joint_pass") != metrics["optimized"]["joint_pass"]:
            issues.append("formal completion outcome differs from recalculated aggregates")
        valid = len(issues) == before
        formal.update(status="completed" if valid else "aggregate_integrity_failed", metrics=metrics if valid else None,
                      aggregate_integrity_verified=valid,
                      no_post_validation_tuning=formal_completion.get("no_post_validation_tuning") is True)
    usage = {"development": aggregate_usage(reader, "development", (*NAMES, "reference-identities")),
             "validation": aggregate_usage(reader, "validation", VALIDATION_RUNS)}
    price_evidence = reader.read("evidence/official-embedding-price.json")
    if price_evidence is not None and any(price_evidence.get(k) != v for k, v in OFFICIAL_EMBEDDING_PRICE.items()):
        raise ValueError("Embedding price evidence differs from the verified report attribution")
    return {"schema_version": 2, "generated_utc": datetime.now(timezone.utc).isoformat(),
            "scope": "aggregate_only_report_not_an_independent_code_or_provenance_review",
            "state": formal["status"] if formal["status"] != "not_run_or_not_completed" else dev["status"],
            "thresholds": limits, "cohorts": cohorts, "history": historical, "development": dev,
            "validation": formal, "usage": usage, "issues": issues, "diagnostics": diagnostics,
            "official_embedding_price": dict(OFFICIAL_EMBEDDING_PRICE),
            "configuration": {k: experiment.get(k) for k in ("version", "temperature", "legacy_completion_tokens",
                "component_completion_tokens", "bootstrap_resamples", "asa24_minimum_exact_rate", "former_asa24_minimum_exact_rate")},
            "source_sha256": reader.hashes, "missing_aggregate_inputs": reader.missing,
            "read_policy": "Exact aggregate allowlist; no labels, sealed data, images, row predictions, raw requests, credentials, or inference imports."}


def fmt(value, precision=3):
    if value is None:
        return "not available"
    value = f"{value:.{precision}f}"
    return value.rstrip("0").rstrip(".") if "." in value else value


def table(headers, rows):
    def cell(value):
        return str(value).replace("|", "\\|").replace("\n", " ")
    return "\n".join(["| " + " | ".join(map(cell, headers)) + " |",
                      "| " + " | ".join("---" for _ in headers) + " |"] +
                     ["| " + " | ".join(map(cell, row)) + " |" for row in rows])


def ratio_summary(metrics, dataset):
    if not metrics:
        return None, None
    checks = [c for c in metrics["checks"] if c["dataset"] == dataset]
    ratios = [c["ratio_to_threshold"] for c in checks]
    return (sum(c["pass"] for c in checks), max(ratios) if ratios and all(v is not None for v in ratios) else None)


def pair(metric):
    metric = metric or {}
    return f"{fmt(metric.get('mae'))} / {fmt(metric.get('per_unit'), 4)}"


def score_metric(score, key):
    return (score or {}).get("metrics", {}).get(key, {})


def count_rate(count, total):
    return f"{fmt(count, 0)} ({fmt(100 * count / total, 1)}%)" if total and count is not None else fmt(count, 0)


def oracle_mass_explanation(oracle, limits):
    """Interpret complete aggregate diagnostics without fitting or causal claims."""
    score = oracle.get("score") or {}
    n = number(oracle.get("scored_n"), True)
    weight = score_metric(score, "weight")
    if (not oracle.get("uses_reference_weight") or not oracle.get("not_a_model_or_acceptance_result")
            or not n or score.get("n") != n or score.get("available_n") != n
            or any(number(weight.get(stat)) is None or weight[stat] > 1e-9 for stat in ("mae", "per_unit"))):
        return ""
    failures = []
    for key in KEYS[1:]:
        metric = score_metric(score, key)
        if any(number(metric.get(stat)) is None for stat in ("mae", "per_unit")):
            return ""
        failures.append([metric[stat] > limits[key][stat] for stat in ("mae", "per_unit")])
    failed = sum(any(pair) for pair in failures)
    if not failed:
        return ""
    result = ("All four nutrient targets still fail both fixed MAE limits" if all(all(pair) for pair in failures)
              else f"{failed}/4 nutrient targets still fail at least one fixed MAE limit")
    return (result + " despite effectively perfect total mass. Correcting total mass alone is insufficient for these predictions. "
        "Food-code choice, component shares and food-table or annotation mismatch are hypotheses, not established causes.")


def checkpoint_one_disclosures():
    """Fixed disclosures from the completed project review, not new input reads."""
    return ["### Checkpoint-one execution findings",
        "These findings preserve the as-run results and original protocol; details and evidence are in `AS_RUN_DEVIATIONS.md` and `REVIEW.md`.",
        "**R-M2-2-1.** ASA24 retained archived v1 folds: 17/23 groups (69/99 images) differ from the registered v2 seed. "
        "Nutrition5k has zero mismatches. Retaining old ASA folds and applying the v2 seed are different policies.",
        "**R-M2-3-1.** B's extra crop tie-breakers changed 10 sets and 40 orders among 84 layouts. Future code follows "
        "uncertainty/mixed/other tiers then parent ID. Selected C uses A identities without crops, so its inference is unaffected. "
        "Corrected B was not rerun; its counterfactual score and winner remain unknown.",
        "**R-M2-3-2.** Prompts contain code, official description, nutrient density and inferred hints; official category is not an explicit field. "
        "Disclosure resolves this finding; no category field or new prompt variant was introduced.",
        "**R-M2-4-1.** Zero/one-group bootstrap now returns absent intervals and a reason. Offline recalculation reproduced the complete "
        "saved development metric object, including every actual 10,000-draw interval; point estimates are unchanged.",
        "**R-M2-5-1 (optional P3).** Retaining sanitized non-stop partial text is deferred: the completed run had zero successful "
        "non-stop responses, so this branch lost no observed response text."]


def friendly(value):
    return {"development_in_progress": "in progress", "development_not_started": "not started",
            "ready_for_review": "gates met; review pending",
            "development_targets_not_met": "registered development targets not met",
            "not_run_or_not_completed": "not run or not completed",
            "partial_aggregates_without_completion": "partial aggregates without completion",
            "aggregate_integrity_failed": "aggregate consistency checks failed"}.get(value, value.replace("_", " "))


def render_markdown(snapshot):
    s = snapshot
    dev, formal, cohorts = s["development"], s["validation"], s["cohorts"]
    selected = formal["metrics"]["optimized"] if formal["status"] == "completed" else dev["metrics"]
    scope = "completed formal validation" if formal["status"] == "completed" else "selected development OOF"
    dc, vc = cohorts["development"], cohorts["validation"]
    parts = ["# DietAI24 MAE first optimization", "Version 2. Generated " + s["generated_utc"][:10] + " UTC",
        "## Scope and outcome",
        f"Development status: **{friendly(dev['status'])}**. Formal validation: **{friendly(formal['status'])}**. "
        "This study tests whether component-level food identification and portion estimation can bring all twenty MAE measures within 1.3 times the published values.",
        (f"The {scope} output passes **{selected['passed_checks']}/20 MAE checks**. The 15% ASA24 recognition gate "
         f"{'passes' if selected['recognition_pass'] else 'fails'}; the joint requirement "
         f"{'is met' if selected['joint_pass'] else 'is not met'} in this scope." if selected else
         "No complete selected metric aggregate is available. Missing results are not interpreted as zero error or as acceptance."),
        "The original GPT-4 Turbo service was unavailable in the historical reproduction setup, motivating a substitute-model comparison. "
        "That comparison, the archived Sol checkpoint, v1 development, and this Sol optimization are separate stages. "
        "The service limitation refers to the reproduction setup; historical results retain their original methods and populations.",
        "## Cohorts and association audit",
        table(["Population", "Images", "Association groups"], [
            ["ASA24 development", fmt(dc.get("asa24_images"), 0), fmt(dc.get("asa24_groups"), 0)],
            ["Nutrition5k development", fmt(dc.get("nutrition5k_images"), 0), fmt(dc.get("nutrition5k_groups"), 0)],
            ["ASA24 validation", fmt(vc.get("asa24_images"), 0), fmt(vc.get("asa24_groups"), 0)],
            ["Nutrition5k validation target", fmt(vc.get("nutrition5k_target_images", 200), 0), fmt(vc.get("nutrition5k_groups"), 0)]]),
        f"The audit records **{fmt(nsum(dc.get('nutrition5k_retired_counts', {}).values()), 0)} development images excluded** and "
        f"**{fmt(nsum(vc.get('nutrition5k_retired_counts', {}).values()), 0)} original validation images retired**; "
        f"{fmt(vc.get('nutrition5k_retained_original_images'), 0)} original validation images remain. Preparation is "
        f"{'complete' if cohorts['validation_ready'] else 'pending'}. Retired validation images do not become training data. Replacement ordering is fixed, not selected by prediction error.",
        "Identical-image and compatible incremental-scan links define conservative association components; ambiguous components are quarantined. "
        "Matching complete ingredient sets missed plates that acquired additional ingredients. Five development folds now preserve retained components. "
        "An association group is not a verified independent physical plate or a precise effective sample size. "
        f"Validation group sizes are {json.dumps(vc.get('nutrition5k_group_size_histogram', {}), sort_keys=True)}, with largest group share "
        f"{fmt(vc.get('nutrition5k_max_group_fraction'), 4)}. Counts come from approved freeze/audit summaries.",
        "## Outcomes and registered methods",
        "Twenty checks cover weight, energy, fat, carbohydrate, and protein: absolute MAE and per-unit MAE on each dataset. "
        "Per-unit MAE divides absolute MAE by the reference mean of the scored population; it is not mean per-image percentage error. "
        "Limits remain 1.3 times the paper values; full precision determines passing. All tables using paired values show **absolute MAE / per-unit MAE**. "
        "Weight and nutrients use grams, energy uses kcal, and per-unit values are fractions.",
        "ASA24 primary MAE conditions on Exact recognition. Only then does its isolated adapter supply the correct food code and complete legal-option catalogue, never target size, option, grams, or nutrients. "
        "Recognition includes all images with at most three distinct final codes. Conditional errors and all-image E2E errors measure different tasks; changing Exact membership can change difficulty. "
        "The paper does not establish an identical conditional population. Nutrition5k primary scoring includes every active image and whole-dish fallback; undefined values fail.",
        "The single RGB image retains aspect ratio, longest side at most 1024, without upscaling; ASA24 preserves square256 processing. "
        "Nutrition5k uses positive component masses and one accounting path per parent: either its composite leaf or its children. FNDDS per-100 g densities convert leaf grams into nutrients; parent totals are not added again.",
        "A estimates component masses. B reuses A's layout with up to four same-image crops. C keeps the better raw A/B identities and estimates whole-plate mass with nested shares. "
        "Conditional extensions D (code review at fixed mass) and E (standard-unit portions) independently reuse the same first-round raw winner. They never form a D-to-E chain. "
        "These dependent branches do not identify isolated causal effects of every factor.",
        "Selection enforces ASA24 feasibility, then orders worst metric/limit ratio, mean ratio, expected main chat count, and registration. "
        "Only each round's raw winner receives a calibration comparison. One mass multiplier searches .800–1.250 at .001 intervals, then shrinks halfway to one. "
        "At least five eligible training groups are required; fallback predictions are excluded from fitting. Other-fold statistics supply all OOF fallbacks and multipliers. "
        "Nutrition5k reaggregates scaled leaves; ASA24 remaps continuous grams to a legal option without scaling that final option. Calibration requires strict worst-ratio improvement without losing any passing check.",
        "## Development candidates and historical context"]
    rows = []
    pending = []
    for c in dev["candidates"]:
        visible = False
        for ds in DATASETS:
            n = (c["retained_metrics"] or c["raw_metrics"] or {}).get("datasets", {}).get(ds, {}).get("n", 0)
            if not n:
                continue
            visible = True
            raw, retained = ratio_summary(c["raw_metrics"], ds), ratio_summary(c["retained_metrics"], ds)
            rows.append([c["name"], ds, n, f"{fmt(raw[0], 0)} / {fmt(raw[1])}",
                         f"{fmt(retained[0], 0)} / {fmt(retained[1])}", "yes" if c["calibration_enabled"] else "no"])
        if not visible:
            pending.append([c["name"], "pending", friendly(c["status"])])
    if rows:
        parts += ["Raw and retained cells show passing checks out of ten / worst threshold ratio.",
                  table(["Candidate", "Dataset", "N", "Raw", "Retained", "Calibration"], rows)]
    else:
        parts.append("Candidate metrics are not yet available. Absence does not establish passing or failure.")
    if pending:
        parts.append(table(["Candidate", "Metrics", "Run state"], pending))
    for c in dev["candidates"]:
        if not c["calibrated_metrics"]:
            continue
        for ds, data in c["calibrated_metrics"]["datasets"].items():
            if not data.get("n"):
                continue
            raw = (c["raw_metrics"] or {}).get("datasets", {}).get(ds, {}).get("primary")
            parts += [f"Calibration comparison for {c['name']} on {ds}: "
                      f"{'retained' if c['calibration_enabled'] else 'rejected'}; final fitted factor {fmt(c['mass_factor'], 4)}. "
                      "OOF comparison uses fold-specific fits; the final scalar is not applied retrospectively to OOF rows.",
                      table(["Target", "Raw", "Calibration attempt"], [[TARGET_NAMES[k], pair(score_metric(raw, k)),
                             pair(score_metric(data.get("primary"), k))] for k in KEYS])]
    hist, v1 = s["history"], s["history"].get("v1_development")
    archive, old = hist["archived_sol"], (v1 or {}).get("datasets", {})
    if archive or v1:
        parts.append(table(["Historical stage", "ASA24 total / scored", "Nutrition5k total / scored", "Pass / 20"], [
            ["Archived Sol", f"{fmt(archive.get('asa24', {}).get('total_records'), 0)} / {fmt(archive.get('asa24', {}).get('evaluated_records'), 0)}",
             f"{fmt(archive.get('nutrition5k', {}).get('total_records'), 0)} / {fmt(archive.get('nutrition5k', {}).get('evaluated_records'), 0)}", fmt(hist.get("archived_sol_passed_checks"), 0)],
            ["v1 development", f"{fmt(old.get('asa24', {}).get('n'), 0)} / {fmt(old.get('asa24', {}).get('exact_n'), 0)}",
             f"{fmt(old.get('nutrition5k', {}).get('n'), 0)} / {fmt(old.get('nutrition5k', {}).get('primary', {}).get('n'), 0)}", fmt(v1.get("passed_checks") if v1 else None, 0)]]))
    parts.append("The earlier 100-image Nutrition5k development set differs from the revised cohort, so historical changes are not paired improvements. "
        "The current example-assisted reference uses current training folds and remains uncalibrated to avoid indirect held-out-label dependence. "
        "Winner selection and calibration reuse development evidence: selected OOF scores are optimistic for the complete selection procedure. "
        "A smaller Exact subset alone does not establish improvement.")
    parts += ["## Paper reference and selected results",
        f"Selected values concern **{scope}**. Paper values and registered caps are shown together; historical columns retain their original populations."]
    for ds in DATASETS:
        parts.append("### " + ("ASA24" if ds == "asa24" else "Nutrition5k"))
        data = (selected or {}).get("datasets", {}).get(ds, {})
        parts.append(table(["Target", "Paper", "Cap", "Archived Sol", "v1", "Selected"], [
            [TARGET_NAMES[k], pair({"mae": v["paper_mae"], "per_unit": v["paper_per_unit"]}), pair(v),
             pair(archive.get(ds, {}).get("metrics", {}).get(k)), pair(score_metric(old.get(ds, {}).get("primary"), k)),
             pair(score_metric(data.get("primary"), k))] for k, v in s["thresholds"][ds].items()]))
    if not selected:
        parts.append("No selected predictions have been scored in the available aggregates. Thresholds are registered limits, not result values.")
    else:
        failed = [c for c in selected["checks"] if not c["pass"]]
        if failed:
            parts.append("The following decreases are required to reach the caps; percentages divide the gap by current error.")
            parts.append(table(["Dataset and target", "Measure", "Current", "Cap", "Decrease", "% reduction"], [
                [c["dataset"] + " " + c["target"], "absolute" if c["statistic"] == "mae" else "per unit", fmt(c["value"], 5),
                 fmt(c["threshold"], 5), fmt(c["reduction_required"], 5), fmt(c["reduction_fraction"] * 100, 1) if c["reduction_fraction"] is not None else "undefined"] for c in failed]))
        parts.append("Each status cell below reports absolute MAE / per-unit MAE, covering all twenty registered checks.")
        parts.append(table(["Target", "ASA24 status", "Nutrition5k status"], [
            [TARGET_NAMES[k]] + [" / ".join(
                "pass" if selected["datasets"].get(ds, {}).get("primary", {}).get("metrics", {}).get(k, {}).get("pass_" + stat) else "fail"
                for stat in ("mae", "per_unit")) for ds in DATASETS] for k in KEYS]))
        asa = selected["datasets"].get("asa24", {})
        parts.append(f"ASA24 Exact is {fmt(asa.get('exact_n'), 0)}/{fmt(asa.get('n'), 0)} ({fmt(asa.get('exact_rate'), 4)}). "
            f"The 15% minimum is {fmt(asa.get('minimum_exact_n'), 0)} ({'pass' if asa.get('recognition_pass') else 'fail'}); "
            f"the former 18% minimum is {fmt(asa.get('former_minimum_exact_n'), 0)} ({'pass' if asa.get('former_recognition_pass') else 'fail'}). "
            f"First-code rate is {fmt(asa.get('first_rate'), 4)}, retrieval Exact rate {fmt(asa.get('retrieval_exact_rate'), 4)}, "
            f"and mean final-code count {fmt(asa.get('average_final_code_count'))}.")
        sized = asa.get("by_size", {})
        if sized:
            parts.append(table(["ASA24 size", "N", "Exact", "Exact rate", "First rate"], [
                [size, fmt(d.get("n"), 0), fmt(d.get("exact_n"), 0), fmt(d.get("exact_rate"), 4), fmt(d.get("first_rate"), 4)] for size, d in sized.items()]))
        e2e = asa.get("e2e")
        if e2e or sized:
            parts.append(table(["ASA24 target", "All-image E2E"] + [size + " Exact" for size in sized], [
                [TARGET_NAMES[k], pair(score_metric(e2e, k))] + [pair(score_metric(d.get("conditional"), k)) for d in sized.values()] for k in KEYS]))
            parts.append("Size columns are Exact-conditioned MAEs within each size, whereas E2E includes every image.")
        parts.append(table(["Dataset", "All / primary N", "Groups / Exact"], [
            [ds, f"{fmt(d.get('n'), 0)} / {fmt(d.get('primary', {}).get('n'), 0)}",
             f"{fmt(d.get('groups'), 0)} / {fmt(d.get('exact_groups'), 0)}"] for ds, d in selected["datasets"].items()]))
        parts.append(table(["Dataset", "Native", "Complete", "Repaired", "Whole fallback", "Method fallback"], [
            [ds] + [count_rate(d.get(k), d.get("n")) for k in ("native_complete_n", "complete_n", "repair_success_n", "fallback_n", "method_fallback_n")]
            for ds, d in selected["datasets"].items()]))
        n5 = selected["datasets"].get("nutrition5k", {})
        if n5.get("native_subset") or n5.get("complete_subset"):
            parts.append(f"Nutrition5k native/complete subset sizes are {fmt((n5.get('native_subset') or {}).get('n'), 0)} / "
                         f"{fmt((n5.get('complete_subset') or {}).get('n'), 0)}.")
            parts.append(table(["Nutrition5k target", "Native subset", "Complete subset"], [[TARGET_NAMES[k],
                pair(score_metric(n5.get("native_subset"), k)), pair(score_metric(n5.get("complete_subset"), k))] for k in KEYS]))
        parts.append(f"ASA24 conditional fallback/missing counts are {fmt(asa.get('conditional_fallback_n'), 0)}/{fmt(asa.get('conditional_missing_n'), 0)}. "
            "Native excludes repairs and method fallback; complete includes repairs but excludes whole-dish fallback. Failed enhancements retain their base prediction as method fallback. "
            "Flags may overlap. Subset MAEs describe selected successful cases and cannot replace all-row primary errors.")
    parts.append("## Development diagnostics and uncertainty")
    diag = s.get("diagnostics")
    if diag:
        common = diag.get("asa24_common_exact_comparison")
        if common:
            parts.append(f"ASA24 common Exact diagnostic: both arms recognized the same {fmt(common['n'], 0)} images in "
                f"{fmt(common['groups'], 0)} groups, from {fmt(common['population_n'], 0)} development images "
                f"(baseline Exact {fmt(common['baseline_exact_n'], 0)}; selected Exact {fmt(common['selected_exact_n'], 0)}). "
                "This post-selection comparison holds image membership fixed; it cannot influence selection or acceptance and does not replace the registered scores on each arm's own Exact population.")
            common_intervals = common["paired_bootstrap"]["intervals"]
            parts.append(table(["ASA24 target", "Baseline option", "Selected option", "Paired MAE 95% CI"], [
                [TARGET_NAMES[k], pair(score_metric(common["baseline"], k)), pair(score_metric(common["selected"], k)),
                 (f"{fmt(common_intervals[k + '.mae']['low'])} to {fmt(common_intervals[k + '.mae']['high'])}"
                  if common_intervals else "not available")] for k in KEYS]))
            parts.append("Cells show absolute / per-unit MAE; paired differences are selected minus baseline. "
                "No interval is reported with fewer than two groups or missing conditional predictions; non-overlap produces no common-population estimate.")
        comp = diag["same_population_comparison"]
        boot = comp["paired_bootstrap"]
        parts.append(f"The following diagnostic compares the same {fmt(comp['n'], 0)} development images. The median baseline uses five target medians fitted only on other folds. "
            "Paired differences are selected minus original baseline: negative favors selected. Selection bias remains; this is not independent validation.")
        parts.append(table(["Target", "Baseline", "Selected", "Training medians", "Paired MAE 95% CI", "Signed bias"], [
            [TARGET_NAMES[k], pair(score_metric(comp["baseline"], k)), pair(score_metric(comp["selected"], k)),
             pair(score_metric(diag["median_baseline"]["score"], k)),
             f"{fmt(boot['intervals'][k + '.mae']['low'])} to {fmt(boot['intervals'][k + '.mae']['high'])}",
             fmt(comp["selected_mean_signed_error"][k])] for k in KEYS]))
        oracle = diag["oracle_weight_diagnostic"]
        if oracle["uses_reference_weight"] and oracle["not_a_model_or_acceptance_result"]:
            parts.append(f"The oracle diagnostic substitutes true total weight on {fmt(oracle['scored_n'], 0)}/{fmt(oracle['population_n'], 0)} images "
                f"({fmt(oracle['excluded_nonpositive_weight_n'], 0)} nonpositive-weight exclusions). Residual absolute nutrient MAEs are " +
                "; ".join(k + " " + fmt(score_metric(oracle["score"], k).get("mae")) for k in KEYS[1:]) +
                ". This uses reference labels after selection: it is not a feasible model, candidate, or acceptance result and does not identify the causal error source.")
            explanation = oracle_mass_explanation(oracle, s["thresholds"]["nutrition5k"])
            if explanation:
                parts.append(explanation)
    else:
        parts.append("Post-selection development diagnostics are unavailable. Median-baseline and reference-weight oracle results are not inferred from other metrics.")
    boots = [(ds, d.get("bootstrap")) for ds, d in (selected or {}).get("datasets", {}).items() if d.get("bootstrap")]
    if boots:
        parts.append(table(["Dataset", "Target", "MAE 95% interval", "Valid draws"], [[ds, k,
            f"{fmt(b['intervals'].get(k + '.mae', {}).get('low'))} to {fmt(b['intervals'].get(k + '.mae', {}).get('high'))}",
            fmt(b["intervals"].get(k + ".mae", {}).get("valid_replicates"), 0)] for ds, b in boots for k in KEYS]))
        parts.append("Draws / groups / empty Exact draws: " + "; ".join(f"{ds} {fmt(b.get('replicates'), 0)} / {fmt(b.get('group_count'), 0)} / "
                     f"{fmt(b.get('empty_exact_replicates'), 0)}" for ds, b in boots) + ".")
    parts.append("Uncertainty uses 10,000 association-group resamples and 95% intervals; fewer than two groups yields no interval. "
        "Point estimates gate acceptance. Marginal intervals are not paired-difference intervals. The snapshot retains per-unit intervals and valid/empty draw counts.")
    parts.append("## Formal validation")
    if formal["status"] == "completed":
        parts.append(table(["Completed formal arm", "MAE passes / 20", "ASA24 15%", "Joint outcome"], [[arm, m["passed_checks"],
            "pass" if m["recognition_pass"] else "fail", "pass" if m["joint_pass"] else "fail"] for arm, m in formal["metrics"].items()]))
        for ds in DATASETS:
            parts.append(table([ds + " target", "Baseline", "Optimized"], [[TARGET_NAMES[k]] + [
                pair(score_metric(m["datasets"][ds]["primary"], k)) for m in formal["metrics"].values()] for k in KEYS]))
        parts.append("Both arms and completion evidence pass aggregate population, threshold, and outcome checks. ASA24 Exact subsets can differ despite identical all-image cohorts. "
            "This consistency check is not independent provenance review; validation cannot be reused for independent acceptance after tuning on it.")
    else:
        parts.append("**No completed, internally consistent formal comparison is reported.** Development does not substitute for formal results. "
            "Passing development permits review and freezing; failed finite development keeps validation sealed. Partial aggregates do not establish acceptance.")
    parts += ["## Usage and deviations"]
    rows, tokens = [], []
    for phase, usage in s["usage"].items():
        for role, v in usage["providers"].items():
            label = phase + " " + role
            rows.append([label, usage["aggregate_run_count"], v["requests"], v["errors"]])
            tokens.append([label, v["prompt_tokens"], v["completion_tokens"], v["reasoning_tokens"], v["total_tokens"]])
    parts += [table(["Phase and provider", "Run aggregates", "Requests", "Errors"], rows),
              table(["Phase and provider", "Prompt", "Completion", "Reasoning subset", "Total"], tokens),
        "Usage covers provider-reported fields from newly logged v2 HTTP attempts; historical imports, reused cache, and original corpus creation are excluded. "
        "Lost responses or unavailable usage fields can undercount tokens, so these totals are not a billing total. "
        "Error counts record HTTP or connection failures, not all structured-output failures. "
        "Reasoning tokens are already inside completion tokens. Official embedding estimates are " +
        "; ".join(phase + " " + ("$" + fmt(u["official_embedding_estimated_usd"], 6) if u["official_embedding_estimated_usd"] is not None else "unavailable") for phase, u in s["usage"].items()) +
        ". The official OpenAI route uses text-embedding-3-large at $0.13 per 1 million input tokens, verified on 2026-11-02 "
        "against the [official model documentation](https://developers.openai.com/api/docs/models/text-embedding-3-large). "
        "These are token-based estimates, not invoices. Third-party chat and combined actual cost remain unverified; official model prices are not substituted for this route.",
        "Registered changes from the original study include substitute model/provider, revised groups/cohort, 15% recognition floor, single RGB, "
        "component accounting and finite calibration. Component/legacy token limits are 8192/4096. Inferred relationships are hypotheses. "
        "This is not exact original-backend replication; Linux tests do not verify Mac execution."]
    if dev["status"] in ("ready_for_review", "development_targets_not_met"):
        parts += checkpoint_one_disclosures()
    parts += [
        "The companion JSON preserves full-precision metrics, source hashes, and missing or inconsistent evidence. "
        "The portable package presents these saved results offline and supports an explicitly authorized two-image live demonstration. "
        "The live ASA24 demonstration is image-only E2E and does not reproduce the report's conditional task.",
        "## Sources",
        "Paper: [DietAI24, Communications Medicine 5, 458 (2025)](https://doi.org/10.1038/s43856-025-01159-0). "
        "Released method: [authors' repository](https://github.com/Runz96/DietAI24), v1.0-paper, local baseline `5946365`. "
        "Local method and limits: `PROTOCOL.md`, `analysis/paper_targets.json`. "
        "Cohorts: `data/cohorts/dev_freeze.json`, `evidence/audit_summary.json`, `evidence/preparation_summary.json`. "
        "Historical context: `analysis/historical_summary.json`. Development: `runs/development/selection.json`, `candidates.json`, `completion.json`, and registered run aggregate metrics, usage, and calibration summaries. "
        "Optional diagnostics: `analysis/diagnostics_v2.json`. Formal evidence, when present: `runs/validation/metrics.json`, `completion.json`. "
        "Official embedding price evidence: `evidence/official-embedding-price.json`. "
        "The companion snapshot lists exact paths and SHA-256 hashes actually read; listed optional evidence need not exist."]
    if s["issues"]:
        parts.append("Aggregate issues: " + "; ".join(s["issues"]) + ".")
    return "\n\n".join(parts) + "\n"

def write_report(root=ROOT):
    root = Path(root).resolve()
    snapshot = build_snapshot(root)
    markdown = render_markdown(snapshot)
    snapshot["report_word_count"] = len(re.findall(r"\b[\w]+(?:[-'][\w]+)*\b", markdown))
    output_dir = root / "reports"
    if output_dir.resolve() != output_dir:
        raise ValueError("Report destination cannot be a symlink")
    output_dir.mkdir(parents=True, exist_ok=True)
    for name, content in ((OUTPUT_MARKDOWN, markdown), (OUTPUT_SNAPSHOT, json.dumps(snapshot, indent=2, allow_nan=False) + "\n")):
        path = root / name
        if path.is_symlink():
            raise ValueError("Report output cannot overwrite a symlink")
        temporary = path.with_suffix(path.suffix + ".tmp")
        if temporary.is_symlink():
            raise ValueError("Report temporary output cannot be a symlink")
        temporary.write_text(content)
        temporary.replace(path)
    return {"markdown": str(root / OUTPUT_MARKDOWN), "snapshot": str(root / OUTPUT_SNAPSHOT),
            "state": snapshot["state"], "word_count": snapshot["report_word_count"], "issues": len(snapshot["issues"])}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args(argv)
    print(json.dumps(write_report(args.root), indent=2))


if __name__ == "__main__":
    main()
