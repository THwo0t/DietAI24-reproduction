"""Offline, post-seal target adapters and same-profile dual-dataset selection."""
from copy import deepcopy
import math

from opt_metrics import evaluate, nearest_option, median_option, option_prediction


def adapt_asa(rows, labels, core_records, catalog):
    by_id = {p["sample_id"]: deepcopy(p) for p in core_records}
    if len(by_id) != len(core_records) or set(by_id) != {r["sample_id"] for r in rows}:
        raise ValueError("score_population_changed")
    for row in rows:
        pred, label = by_id[row["sample_id"]], labels[row["sample_id"]]
        if row["dataset"] != "asa24":
            continue
        code = label["food_code"]
        if code not in pred["final_codes"]:
            continue
        options, density = catalog["asa_options"][code], catalog["foods"][code]["density"]
        grams = None if pred["fallback"] else sum(p["grams"] for p in pred["raw_leaves"] if p["code"] == code)
        option = median_option(options) if grams is None else nearest_option(grams, options)
        pred["conditional"] = {"code": code, "option_id": option["option_id"],
            "continuous_grams": grams, "fallback": grams is None,
            "prediction": option_prediction(option, density)}
    return [by_id[row["sample_id"]] for row in rows]


def tolerance(scores):
    checks = scores["checks"]
    if len(checks) != 20 or len({(c["dataset"], c["target"], c["statistic"]) for c in checks}) != 20:
        raise ValueError("twenty_unique_checks_required")
    failed, defined, pairs = {}, {}, {}
    for ds in ("asa24", "nutrition5k"):
        selected = [c for c in checks if c["dataset"] == ds]
        if len(selected) != 10:
            raise ValueError("ten_checks_per_dataset_required")
        defined[ds] = all(type(c["value"]) in (int, float) and math.isfinite(c["value"])
                          and c["value"] >= 0 and type(c["threshold"]) in (int, float)
                          and math.isfinite(c["threshold"]) and c["threshold"] > 0 for c in selected)
        failed[ds] = sum(c["value"] > c["threshold"] for c in selected) if defined[ds] else None
        pairs[ds] = {k: all(c["value"] is not None and c["value"] <= c["threshold"]
                           for c in selected if c["target"] == k)
                     for k in ("weight", "energy", "fat", "carbs", "protein")}
    asa = scores["datasets"]["asa24"]
    floor15, target18 = (15 * asa["n"] + 99) // 100, (18 * asa["n"] + 99) // 100
    guards = asa["exact_n"] >= floor15 and asa["exact_groups"] >= 5 and asa["n"] > 0
    passed = all(defined.values()) and guards and all(n <= 2 for n in failed.values())
    ratios = [c["value"] / c["threshold"] for c in checks] if all(defined.values()) else []
    return {"accepted": passed, "defined": defined, "failed_checks": failed,
        "target_pairs_pass": pairs, "strict20_pass": scores["passed_checks"] == 20,
        "recognition_guard_pass": guards, "recognition_floor_n": floor15,
        "original18_target_n": target18, "original18_pass": asa["exact_n"] >= target18,
        "rank": [max(failed.values()), max(ratios), sum(failed.values()), sum(ratios) / 20]
                if ratios else None}


def score(rows, labels, records, catalog, bootstrap=10000):
    predictions = adapt_asa(rows, labels, records, catalog)
    result = evaluate(rows, labels, predictions, bootstrap=bootstrap, seed=20261102)
    return {"metrics": result, "tolerance": tolerance(result), "predictions": predictions}


def select(results):
    eligible = [name for name, r in results.items() if r["tolerance"]["recognition_guard_pass"]
                and r["tolerance"]["rank"] is not None]
    if not eligible:
        return {"selected": None, "accepted": False, "reason": "no_defined_guarded_profile"}
    name = min(eligible, key=lambda n: (*results[n]["tolerance"]["rank"], 0 if n == "M0" else 1))
    return {"selected": name, "accepted": results[name]["tolerance"]["accepted"],
            "reason": "one_shared_profile_ranked_on_both_datasets"}
