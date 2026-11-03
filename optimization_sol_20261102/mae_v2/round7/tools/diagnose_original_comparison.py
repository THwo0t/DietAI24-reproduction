"""Prediction-only historical audit. Never use its results to select a method.

Reads explicit prediction columns from the two original formal runs. Reuses
only AST-extracted pure historical parser functions, without importing their
inference/config modules. No query labels, images, credentials or API clients.
"""
from __future__ import annotations

import ast
from contextlib import redirect_stdout
from fractions import Fraction
import hashlib
from io import StringIO
import json
from pathlib import Path
import re

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[4]
OUT = ROOT / "optimization_sol_20261102/mae_v2/round7/diagnostics/original_comparison"
NUTRIENTS = ["Energy (kcal)", "Total Fat (g)", "Carbohydrate (g)", "Protein (g)"]
CHAIN = ["dish_id", "GPTFoodDescription", "GPTFoodCode", "GPTCandidateCodes"]
PORTION = CHAIN + ["GPTFoodNames", "GPTAmount", "GPTAmountReason"]
PREDICTIONS = PORTION + ["FoodCodeError", "WeightError", "IngredientNum", "GPTWeight", *NUTRIENTS]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def parsers():
    scope = {"re": re, "np": np, "pd": pd, "Fraction": Fraction, "GRAMS": ("g", "gram", "grams")}
    chosen = {
        "rag_portion_size.py": {"CODE_LIST", "parse_food_codes", "parse_amount", "food_name", "food_items", "food_names"},
        "nutrient_estimate.py": {"NUMBER", "NUMBER_ANSWER", "parse_portion_amount"},
        "nutrient_estimate_mix.py": {"parse_food_items", "match_food_codes", "match_food_codes_na"},
    }
    hashes = {}
    for filename, names in chosen.items():
        path = ROOT / "code" / filename
        tree = ast.parse(path.read_text())
        selected, found = [], set()
        for node in tree.body:
            name = node.name if isinstance(node, ast.FunctionDef) else (
                node.targets[0].id if isinstance(node, ast.Assign) and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name) else None)
            if name in names:
                if isinstance(node, ast.FunctionDef) and node.decorator_list:
                    raise ValueError("unexpected parser decorator")
                selected.append(node)
                found.add(name)
        if found != names:
            raise ValueError("historical parser extraction incomplete")
        exec(compile(ast.Module(body=selected, type_ignores=[]), str(path), "exec"), scope)
        hashes[str(path.relative_to(ROOT))] = sha(path)
    return scope, hashes


def prediction_tables(run):
    tables, hashes = [], {}
    for filename, columns in [("nutrition5k_food_codes.csv", CHAIN),
                              ("nutrition5k_portion.csv", PORTION),
                              ("nutrition5k_nutrition.csv", PREDICTIONS)]:
        path = ROOT / "runs" / run / filename
        table = pd.read_csv(path, usecols=columns).set_index("dish_id").sort_index()
        if not table.index.is_unique or len(table) != 150:
            raise ValueError("unexpected historical population")
        tables.append(table)
        hashes[str(path.relative_to(ROOT))] = sha(path)
    for earlier in tables[:2]:
        pd.testing.assert_frame_equal(earlier, tables[2][earlier.columns], check_dtype=False, check_exact=True)
    return tables[2], hashes


def audit_row(row, p, density):
    raw_codes = row["GPTFoodCode"]
    parsed = p["food_items"](raw_codes)
    with redirect_stdout(StringIO()) as warnings:
        weights = p["parse_food_items"](row["GPTAmount"])
    normalized = ({p["food_name"](key).lower(): value for key, value in weights.items()}
                  if isinstance(weights, dict) else {})
    expected_names = p["food_names"](raw_codes)
    if not ((pd.isna(expected_names) and pd.isna(row["GPTFoodNames"]))
            or expected_names == row["GPTFoodNames"]):
        raise ValueError("saved portion input names changed")
    items, totals, total_weight = [], np.zeros(4), None
    weight_error, code_error, contributions = 0, 0, 0
    for name, codes in parsed:
        grams = normalized.get(name.lower(), np.nan)
        valid_codes = [code for code in codes if code in density]
        item_density = np.nanmean([density[c] for c in valid_codes], axis=0) if valid_codes else None
        if pd.isna(grams):
            weight_error += 1
        else:
            total_weight = grams if total_weight is None else total_weight + grams
            if item_density is None:
                code_error += 1
            else:
                totals += item_density * grams / 100
                contributions += 1
        items.append({"name": name, "selected_codes": codes, "valid_codes": valid_codes,
            "grams": None if pd.isna(grams) else float(grams),
            "density_per_100g": None if item_density is None else item_density.tolist(),
            "code_error_masked_by_missing_grams": bool(pd.isna(grams) and not valid_codes)})
    if pd.isna(raw_codes):
        expected_counts = [np.nan, np.nan, 0]
    elif not isinstance(weights, dict):
        expected_counts = [0, len(parsed), len(parsed)]
    else:
        expected_counts = [code_error, weight_error, len(parsed)]
    np.testing.assert_allclose(row[["FoodCodeError", "WeightError", "IngredientNum"]].to_numpy(dtype=float),
                               expected_counts, equal_nan=True, rtol=0, atol=0)
    np.testing.assert_allclose(float(row["GPTWeight"]), np.nan if total_weight is None else total_weight,
                               equal_nan=True, rtol=1e-12, atol=1e-9)
    expected_nutrition = totals if contributions else np.full(4, np.nan)
    np.testing.assert_allclose(row[NUTRIENTS].to_numpy(dtype=float), expected_nutrition,
                               equal_nan=True, rtol=1e-10, atol=1e-8)
    # Candidate lists are stored as Python list literals, never eval'd as code.
    candidate_text = row["GPTCandidateCodes"]
    candidates = [] if pd.isna(candidate_text) else ast.literal_eval(candidate_text)
    if not isinstance(candidates, list) or any(isinstance(c, bool) or not isinstance(c, (int, str)) for c in candidates):
        raise ValueError("invalid saved candidate list")
    selected = sorted({c for _, codes in parsed for c in codes})
    candidate_set = {int(c) for c in candidates}
    complete = row["IngredientNum"] > 0 and row["WeightError"] == 0 and row["FoodCodeError"] == 0
    return {"complete": bool(complete), "description_chars": 0 if pd.isna(row["GPTFoodDescription"])
            else len(row["GPTFoodDescription"]), "item_count": len(parsed),
            "items_with_multiple_selected_codes": sum(len(codes) > 1 for _, codes in parsed),
            "candidate_count": len(candidate_set), "selected_codes": selected,
            "selected_codes_outside_saved_candidates": [c for c in selected if c not in candidate_set],
            "missing_gram_items": sum(item["grams"] is None for item in items),
            "parser_warning_lines": len(warnings.getvalue().splitlines()),
            "prediction": {"weight": total_weight, **dict(zip(NUTRIENTS, expected_nutrition.tolist()))},
            "items": items}


def main():
    p, hashes = parsers()
    hashes[str(Path(__file__).resolve().relative_to(ROOT))] = sha(Path(__file__))
    path = ROOT / "FNDDS/2019-2020 FNDDS At A Glance - FNDDS Nutrient Values.xlsx"
    frame = pd.read_excel(path, sheet_name="FNDDS Nutrient Values", skiprows=1, usecols=["Food code", *NUTRIENTS])
    if not frame["Food code"].is_unique:
        raise ValueError("nonunique historical nutrient codes")
    density = {int(row["Food code"]): row[NUTRIENTS].to_numpy(dtype=float) for _, row in frame.iterrows()}
    hashes[str(path.relative_to(ROOT))] = sha(path)
    tables, configurations = [], []
    for run in ["test", "test-gpt-6.1-sol"]:
        table, paths = prediction_tables(run)
        tables.append(table)
        hashes.update(paths)
        config_path = ROOT / "runs" / run / "config.json"
        config = json.loads(config_path.read_text())
        if config["code_sha256"]["rag_portion_size.py"] != hashes["code/rag_portion_size.py"]:
            raise ValueError("historical food parser source differs from inference config")
        hashes[str(config_path.relative_to(ROOT))] = sha(config_path)
        configurations.append({key: config[key] for key in ["models", "temperature", "image_size", "split", "inputs_sha256"]})
    if any(configurations[0][key] != configurations[1][key] for key in ["image_size", "split", "inputs_sha256"]):
        raise ValueError("formal-run inputs differ")
    if not tables[0].index.equals(tables[1].index):
        raise ValueError("historical sample keys differ")
    rows = [{"dish_id": key, "gpt4o": audit_row(tables[0].loc[key], p, density),
             "sol": audit_row(tables[1].loc[key], p, density)} for key in tables[0].index]
    groups = {"common_complete": [], "4o_only_complete": [], "sol_only_complete": [], "neither_complete": []}
    for row in rows:
        a, b = row["gpt4o"]["complete"], row["sol"]["complete"]
        group = "common_complete" if a and b else "4o_only_complete" if a else "sol_only_complete" if b else "neither_complete"
        row["coverage_group"] = group
        groups[group].append(row)
    counts = {key: len(values) for key, values in groups.items()}
    if counts != {"common_complete": 79, "4o_only_complete": 7, "sol_only_complete": 39, "neither_complete": 25}:
        raise ValueError("archived coverage counts not reproduced")
    paired = groups["common_complete"]
    summary = {"purpose": "Historical prediction-chain description only; never select or tune a method with these test records.",
        "api_calls": 0, "query_labels_loaded": False, "validation_accessed": False,
        "source_sha256": hashes, "recomputed_rows": 300, "coverage_groups": counts,
        "replay_matches_archived_predictions": True,
        "prediction_columns_loaded": PREDICTIONS, "run_configurations": configurations,
        "own_complete_n": [86, 118], "common_complete_n": 79,
        "paired_prediction_features": {}, "predicted_nutrient_difference_decomposition": {}}
    for role in ["gpt4o", "sol"]:
        summary["paired_prediction_features"][role] = {key: float(np.mean([r[role][key] for r in paired]))
            for key in ["description_chars", "item_count", "items_with_multiple_selected_codes", "candidate_count"]}
        summary["paired_prediction_features"][role]["mean_predicted_weight_g"] = float(np.mean([
            r[role]["prediction"]["weight"] for r in paired]))
    summary["paired_changed_selected_code_set_n"] = sum(r["gpt4o"]["selected_codes"] != r["sol"]["selected_codes"] for r in paired)
    summary["paired_changed_item_count_n"] = sum(r["gpt4o"]["item_count"] != r["sol"]["item_count"] for r in paired)
    summary["all150_prediction_audit"] = {role: {
        "outside_candidate_rows": sum(bool(r[role]["selected_codes_outside_saved_candidates"]) for r in rows),
        "parser_warning_rows": sum(bool(r[role]["parser_warning_lines"]) for r in rows),
        "missing_gram_items": sum(r[role]["missing_gram_items"] for r in rows)} for role in ["gpt4o", "sol"]}
    for target in NUTRIENTS:
        terms = []
        for row in paired:
            a, b = row["gpt4o"]["prediction"], row["sol"]["prediction"]
            wa, wb = a["weight"], b["weight"]
            if wa <= 0 or wb <= 0:
                continue
            da, db = 100 * a[target] / wa, 100 * b[target] / wb
            mass = (wb - wa) * (db + da) / 200
            composition = (db - da) * (wb + wa) / 200
            np.testing.assert_allclose(mass + composition, b[target] - a[target], atol=1e-9, rtol=1e-12)
            terms.append([b[target] - a[target], mass, composition])
        summary["predicted_nutrient_difference_decomposition"][target] = {"n": len(terms),
            **dict(zip(["mean_sol_minus_4o", "mean_mass_term", "mean_effective_density_term"], np.mean(terms, axis=0).tolist()))}
    summary["decomposition_scope"] = ("Symmetric algebraic decomposition of PREDICTIONS, not MAE or causal effects. "
        "Effective density mixes code identity, selected-code averaging and item mass allocation. No query ground truth used.")
    # Confirm every source stayed unchanged; write only the separate private output.
    for relative, expected in hashes.items():
        if sha(ROOT / relative) != expected:
            raise ValueError("source changed during historical audit")
    def clean(value):
        if isinstance(value, dict): return {k: clean(v) for k, v in value.items()}
        if isinstance(value, list): return [clean(v) for v in value]
        if isinstance(value, (float, np.floating)) and not np.isfinite(value): return None
        return value
    OUT.mkdir(parents=True, exist_ok=True)
    OUT.chmod(0o700)
    for filename, value in [("aggregate.json", summary), ("private_prediction_chains.json", rows)]:
        path = OUT / filename
        path.write_text(json.dumps(clean(value), ensure_ascii=False, indent=2, allow_nan=False) + "\n")
        path.chmod(0o600)
    (OUT.parents[1] / "original_comparison_diagnostic.json").write_text(
        json.dumps(clean(summary), ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    print(json.dumps({"status": "ok", "recomputed_rows": 300, "coverage_groups": counts,
                      "output": str(OUT), "api_calls": 0, "query_labels_loaded": False}))


if __name__ == "__main__":
    main()
