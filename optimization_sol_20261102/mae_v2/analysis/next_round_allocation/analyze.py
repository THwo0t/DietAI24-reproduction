#!/usr/bin/env python3
"""Dev-only, label-informed allocation diagnostics; never an inference candidate.

Reads exactly four existing development artifacts plus public aggregate caps.
No image, validation, F, .env, provider, network, or study-loader access.
Requires existing Python 3.10 / NumPy; no SciPy or new installation.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import platform
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent / "aggregate.json"
INPUTS = (
    "data/cohorts/dev.jsonl",
    "data/cohorts/dev_labels.json",
    "runs/development/C/predictions.json",
    "runs/development/selected_oof_predictions.json",
    "analysis/paper_targets.json",
)
TARGETS = ("weight", "energy", "fat", "carbs", "protein")
DISPLAY = ("Weight (g)", "Energy (kcal)", "Total Fat (g)", "Carbohydrate (g)", "Protein (g)")
MAX_ITER = 50000
CHECK_EVERY = 20
REL_GRAD_TOL = 1e-9
FEAS_TOL = 1e-10


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def project(v, lower=None, upper=None):
    """Euclidean projection onto nonnegative simplex or bounded simplex.

    The bounded case solves its piecewise-linear multiplier equation exactly
    between sorted breakpoints; there are no random choices or solver packages.
    """
    v = np.asarray(v, dtype=float)
    if lower is None:
        u = np.sort(v)[::-1]
        css = np.cumsum(u) - 1.0
        ix = np.flatnonzero(u - css / np.arange(1, len(v) + 1) > 0)
        theta = css[ix[-1]] / (ix[-1] + 1)
        return np.maximum(v - theta, 0.0)
    lo, hi = np.asarray(lower, float), np.asarray(upper, float)
    if lo.shape != v.shape or hi.shape != v.shape or np.any(lo > hi):
        raise ValueError("invalid projection bounds")
    if lo.sum() > 1 + FEAS_TOL or hi.sum() < 1 - FEAS_TOL:
        raise ValueError("infeasible projection bounds")
    knots = np.unique(np.r_[v - hi, v - lo])
    sums = np.clip(v[:, None] - knots, lo[:, None], hi[:, None]).sum(axis=0)
    equal = np.flatnonzero(np.abs(sums - 1.0) <= 1e-14)
    if len(equal):
        return np.clip(v - knots[equal[0]], lo, hi)
    above = np.flatnonzero(sums > 1.0)
    if not len(above) or above[-1] + 1 >= len(knots):
        raise ArithmeticError("bounded projection did not bracket sum")
    j = above[-1]
    t = knots[j] + (sums[j] - 1) * (knots[j + 1] - knots[j]) / (sums[j] - sums[j + 1])
    return np.clip(v - t, lo, hi)


def solve(B, y, initial, lower=None, upper=None):
    """Deterministic restarted FISTA for .5 ||B x-y||^2 on a simplex.

    Stop on normalized projected-gradient mapping, not just iterate movement.
    Every returned solution is a feasible witness; the status is reported.
    """
    B, y = np.asarray(B, float), np.asarray(y, float)
    p = lambda z: project(z, lower, upper)
    x = p(initial)
    z, t = x.copy(), 1.0
    H, b = B.T @ B, B.T @ y
    L = float(np.linalg.norm(B, 2) ** 2)
    scale = max(1.0, float(np.max(np.abs(b))))
    converged = False
    iteration = 0
    if L <= np.finfo(float).eps:
        converged = True
    else:
        for iteration in range(1, MAX_ITER + 1):
            new = p(z - (H @ z - b) / L)
            nt = (1 + np.sqrt(1 + 4 * t * t)) / 2
            # Adaptive gradient restart prevents long momentum oscillations.
            if float(np.dot(z - new, new - x)) > 0:
                nt, nz = 1.0, new.copy()
            else:
                nz = new + ((t - 1) / nt) * (new - x)
            x, z, t = new, nz, nt
            if iteration % CHECK_EVERY == 0 or iteration == MAX_ITER:
                residual = float(np.max(np.abs(x - p(x - (H @ x - b) / L))))
                if residual * L / scale <= REL_GRAD_TOL:
                    converged = True
                    break
    lo = np.zeros_like(x) if lower is None else lower
    hi = np.ones_like(x) if upper is None else upper
    violation = max(abs(float(x.sum()) - 1), float(np.maximum(lo - x, 0).max()), float(np.maximum(x - hi, 0).max()))
    if violation > FEAS_TOL or not np.isfinite(x).all():
        raise ArithmeticError("allocation is not feasible")
    grad = H @ x - b
    step = 0.0 if not L else float(np.max(np.abs(x - p(x - grad / L))))
    # Frank-Wolfe gap provides an independent simplex optimality certificate;
    # the box case minimizes the linear gradient by filling lowest gradients.
    vertex = np.array(lo, copy=True)
    remaining = 1.0 - float(vertex.sum())
    for k in np.argsort(grad, kind="stable"):
        delta = min(remaining, float(hi[k] - vertex[k]))
        vertex[k] += delta
        remaining -= delta
    gap = max(0.0, float(np.dot(grad, x - vertex)))
    return x, {
        "converged": converged, "iterations": iteration,
        "objective": float(0.5 * np.sum((B @ x - y) ** 2)),
        "simplex_and_bound_violation": violation,
        "projected_step_inf": step,
        "gradient_mapping_inf": step * L,
        "relative_gradient_mapping_inf": step * L / scale,
        "frank_wolfe_gap": gap,
        "lipschitz_constant": L,
    }


def score(pred, truth, caps, unit_caps):
    error = np.asarray(pred) - truth
    mae = np.mean(np.abs(error), axis=0)
    units = mae / np.mean(truth, axis=0)
    rows = {}
    for j, key in enumerate(TARGETS):
        # Strict comparison of full precision floats: no rounded acceptance.
        rows[key] = {
            "mae": float(mae[j]), "per_unit": float(units[j]),
            "mean_signed_error": float(np.mean(error[:, j])),
            "mae_cap": float(caps[j]), "per_unit_cap": float(unit_caps[j]),
            "mae_pass": bool(mae[j] < caps[j]),
            "per_unit_pass": bool(units[j] < unit_caps[j]),
        }
    return {"metrics": rows,
            "checks_passed_of_10": sum(int(r[k]) for r in rows.values() for k in ("mae_pass", "per_unit_pass")),
            "nutrient_checks_passed_of_8": sum(int(rows[t][k]) for t in TARGETS[1:] for k in ("mae_pass", "per_unit_pass"))}


def summarize_solver(rows):
    return {"solved_n": len(rows), "converged_n": sum(r["converged"] for r in rows),
            "max_iterations": max(r["iterations"] for r in rows),
            "total_iterations": sum(r["iterations"] for r in rows),
            **{key + "_max": max(r[key] for r in rows) for key in rows[0] if key not in ("converged", "iterations")},
            "objective_sum": sum(r["objective"] for r in rows)}


def grouped_folds(manifest):
    group_to_fold = {}
    for row in manifest:
        if row["group_id"] in group_to_fold and group_to_fold[row["group_id"]] != row["fold"]:
            raise ValueError("a component crosses development folds")
        group_to_fold[row["group_id"]] = row["fold"]
    if set(group_to_fold.values()) != set(range(5)):
        raise ValueError("expected existing five development folds")
    return np.array([r["fold"] for r in manifest]), len(group_to_fold)


def run():
    data = {name: (ROOT / name).read_bytes() for name in INPUTS}
    decoded = {name: json.loads(value) for name, value in data.items() if not name.endswith("jsonl")}
    manifest = [json.loads(line) for line in data[INPUTS[0]].splitlines() if line]
    manifest = sorted((r for r in manifest if r["dataset"] == "nutrition5k"), key=lambda r: r["sample_id"])
    if len(manifest) != 84 or any(r["split"] != "dev" for r in manifest):
        raise ValueError("expected the frozen 84-row development population")
    folds, groups = grouped_folds(manifest)
    labels = decoded[INPUTS[1]]
    raw_by_id = {r["sample_id"]: r for r in decoded[INPUTS[2]]}
    selected_by_id = {r["sample_id"]: r for r in decoded[INPUTS[3]] if r["dataset"] == "nutrition5k"}
    ids = [r["sample_id"] for r in manifest]
    if set(ids) != set(raw_by_id) or set(ids) != set(selected_by_id):
        raise ValueError("prediction population mismatch")
    raw, selected = [raw_by_id[i] for i in ids], [selected_by_id[i] for i in ids]
    for m, r, s in zip(manifest, raw, selected):
        if any(p[k] != m[k] for p in (r, s) for k in ("dataset", "group_id", "fold")):
            raise ValueError("prediction/fold binding mismatch")
        if r["raw_leaves"] != s["raw_leaves"] or r["raw_prediction"] != s["raw_prediction"]:
            raise ValueError("selected result does not retain the exact raw C leaves/vector")
    truth = np.array([[labels[i]["truth"][t] for t in TARGETS] for i in ids], float)
    if not np.isfinite(truth).all() or np.any(truth < 0) or np.any(truth[:, 0] <= 0):
        raise ValueError("invalid development truth")
    target_rows = decoded[INPUTS[4]]["datasets"]["nutrition5k"]["metrics"]
    caps = np.array([target_rows[t]["threshold_per_dish"] for t in DISPLAY])
    unit_caps = np.array([target_rows[t]["threshold_per_unit"] for t in DISPLAY])
    raw_pred = np.array([[r["raw_prediction"][t] for t in TARGETS] for r in raw])
    selected_pred = np.array([[r["prediction"][t] for t in TARGETS] for r in selected])
    densities, priors, codes = [], [], []
    feature = np.zeros((len(raw), 5, 9))
    max_raw_reaggregation_error = 0.0
    max_selected_share_difference = 0.0
    for i, (r, s) in enumerate(zip(raw, selected)):
        leaves = r["raw_leaves"]
        grams = np.array([x["grams"] for x in leaves], float)
        D = np.array([[x["density"][t] / 100 for x in leaves] for t in TARGETS[1:]], float)
        if not len(grams) or np.any(grams < 0) or grams.sum() <= 0 or not np.isfinite(D).all():
            raise ValueError("invalid raw C leaves")
        reaggregate = np.r_[grams.sum(), D @ grams]
        max_raw_reaggregation_error = max(max_raw_reaggregation_error, float(np.max(np.abs(reaggregate - raw_pred[i]))))
        selected_grams = np.array([x["grams"] for x in s["calibrated_leaves"]])
        max_selected_share_difference = max(max_selected_share_difference, float(np.max(np.abs(selected_grams / selected_grams.sum() - grams / grams.sum()))))
        densities.append(D)
        priors.append(grams / grams.sum())
        codes.extend(str(x["code"]) for x in leaves)
        for x in leaves:
            bucket = int(str(x["code"])[0]) - 1
            if bucket not in range(9):
                raise ValueError("invalid FNDDS prefix bucket")
            feature[i, :, bucket] += x["grams"] * np.r_[1., [x["density"][t] / 100 for t in TARGETS[1:]]]
    if max_raw_reaggregation_error > 1e-8 or max_selected_share_difference > 1e-12:
        raise ValueError("raw C arithmetic or scalar calibration assumption failed")

    scenarios = {}
    true_mass_only = np.array([np.r_[y[0], y[0] * (D @ x)] for y, D, x in zip(truth, densities, priors)])
    scenarios["selected_C_as_run"] = score(selected_pred, truth, caps, unit_caps)
    scenarios["raw_C_before_mass_calibration"] = score(raw_pred, truth, caps, unit_caps)
    scenarios["true_mass_only_preserve_raw_C_shares"] = score(true_mass_only, truth, caps, unit_caps)
    for name, mass, bounded in (
        ("oracle_true_mass_free_shares", truth[:, 0], False),
        ("oracle_true_mass_half_to_double_shares", truth[:, 0], True),
        ("oracle_selected_predicted_mass_free_shares", selected_pred[:, 0], False),
    ):
        pred, solver_rows, moves, zero_n = [], [], [], 0
        for i, (D, x0) in enumerate(zip(densities, priors)):
            lo, hi = (0.5 * x0, np.minimum(2 * x0, 1.0)) if bounded else (None, None)
            x, diag = solve(mass[i] * D / caps[1:, None], truth[i, 1:] / caps[1:], x0, lo, hi)
            pred.append(np.r_[mass[i], mass[i] * (D @ x)])
            solver_rows.append(diag)
            moves.append(float(0.5 * np.sum(np.abs(x - x0))))
            zero_n += int(np.sum(x <= 1e-12))
        scenarios[name] = {**score(pred, truth, caps, unit_caps),
                           "label_informed_diagnostic_not_candidate": True,
                           "solver": summarize_solver(solver_rows),
                           "share_mass_reassigned_mean": float(np.mean(moves)),
                           "share_mass_reassigned_median": float(np.median(moves)),
                           "zero_shares_at_1e_minus_12": zero_n}

    intervals = np.array([[y[0] * D.min(axis=1), y[0] * D.max(axis=1)] for y, D in zip(truth, densities)])
    below, above = truth[:, 1:] < intervals[:, 0], truth[:, 1:] > intervals[:, 1]
    distance = np.maximum(intervals[:, 0] - truth[:, 1:], 0) + np.maximum(truth[:, 1:] - intervals[:, 1], 0)
    bounds = {"any_nutrient_outside_current_support_interval_n": int(np.any(below | above, axis=1).sum()),
              "interpretation": "Coordinatewise optimistic lower bounds; different nutrients may require incompatible allocations. They cannot identify wrong density, wrong food code, omitted foods, or annotation differences separately.",
              "metrics": {t: {"outside_n": int((below | above)[:, j].sum()), "above_n": int(above[:, j].sum()), "below_n": int(below[:, j].sum()), "mae_lower_bound": float(distance[:, j].mean())} for j, t in enumerate(TARGETS[1:])}}

    # Post-selection exploratory group OOF fits: raw C features only. These are
    # diagnostics, not registered acceptance runs and not a nested search.
    scalar_pred = np.empty_like(raw_pred)
    bucket_pred = np.empty_like(raw_pred)
    scalar_params, bucket_params, bucket_iterations = {}, {}, {}
    for fold in range(5):
        train, held = folds != fold, folds == fold
        factors = []
        for j in range(5):
            valid = train & (raw_pred[:, j] > 0)
            ratio, weight = truth[valid, j] / raw_pred[valid, j], raw_pred[valid, j]
            order = np.argsort(ratio, kind="stable")
            k = np.searchsorted(np.cumsum(weight[order]), weight.sum() / 2)
            factors.append(float(np.clip(ratio[order[k]], .5, 2)))
        scalar_pred[held] = raw_pred[held] * factors
        scalar_params[str(fold)] = dict(zip(TARGETS, factors))
        # Fixed lambda=1, all five standardized targets, beta in [.5,2].
        A = (feature[train] / caps[None, :, None]).reshape(-1, 9) / np.sqrt(train.sum())
        y = (truth[train] / caps).reshape(-1) / np.sqrt(train.sum())
        H, b = A.T @ A + np.eye(9), A.T @ y + np.ones(9)
        L, beta = float(np.linalg.norm(H, 2)), np.ones(9)
        for iteration in range(1, 10001):
            updated = np.clip(beta - (H @ beta - b) / L, .5, 2)
            step = float(np.max(np.abs(updated - beta)))
            beta = updated
            if step < 1e-12:
                break
        bucket_pred[held] = np.einsum("ntb,b->nt", feature[held], beta)
        bucket_params[str(fold)] = {str(j + 1): float(v) for j, v in enumerate(beta)}
        bucket_iterations[str(fold)] = {"iterations": iteration, "projected_step_inf": float(np.max(np.abs(beta - np.clip(beta - (H @ beta - b) / L, .5, 2))))}

    result = {
        "schema_version": 1,
        "status": "post_selection_development_diagnostic_not_acceptance_or_achievable_performance",
        "source_sha256": {name: sha(value) for name, value in data.items()},
        "analysis_script_sha256": sha(Path(__file__).read_bytes()),
        "environment": {"python": platform.python_version(), "numpy": np.__version__, "scipy_installed": importlib.util.find_spec("scipy") is not None, "scipy_used": False, "randomness_used": False},
        "read_boundary": {"exact_input_allowlist": list(INPUTS), "images_read": False, "validation_read": False, "F_read": False, "credentials_read": False, "network_or_paid_calls": 0},
        "population": {"dataset": "nutrition5k", "n": len(ids), "association_groups": groups, "fold_rows": {str(k): int((folds == k).sum()) for k in range(5)}, "leaves": len(codes), "unique_codes": len(set(codes)), "reference_means": dict(zip(TARGETS, map(float, truth.mean(axis=0))))},
        "arithmetic_checks": {"raw_C_to_selected_raw_exact_match": True, "raw_leaf_reaggregation_max_abs_error": max_raw_reaggregation_error, "raw_vs_calibrated_share_max_abs_difference": max_selected_share_difference},
        "scoring": {"per_unit": "MAE / mean reference quantity on all 84 rows", "strict_pass_operator": "<", "rounding_before_comparison": False, "all_nutrient_checks": 8, "all_checks": 10},
        "solver_specification": {"objective": "0.5 * ||(W * D * x - reference_nutrients) / nutrient_MAE_caps||_2^2", "D": "four per-gram densities of exact raw C leaves", "constraints": "x>=0, sum(x)=1; bounded scenario additionally 0.5*x_C<=x<=min(2*x_C,1)", "algorithm": "deterministic FISTA with adaptive gradient restart, exact simplex/box-simplex projection", "max_iterations": MAX_ITER, "check_every": CHECK_EVERY, "relative_gradient_mapping_tolerance": REL_GRAD_TOL, "gradient_normalizer": "max(1, ||B.T*y||_infinity)", "feasibility_tolerance": FEAS_TOL, "zero_share_reporting_threshold": 1e-12, "initialization": "raw C normalized grams", "no_optimum_claim": "Returned feasible witnesses, with convergence and independent Frank-Wolfe-gap diagnostics; not a reachable model-performance promise."},
        "scenarios": scenarios,
        "support_interval_diagnostic": bounds,
        "exploratory_group_oof": {
            "status": "post_selection_exploration_not_registered_selection_or_acceptance",
            "heldout_truth_never_used_in_fit": True,
            "features": "raw uncalibrated C predictions/leaves; fixed archived group folds",
            "per_target_scalar": {**score(scalar_pred, truth, caps, unit_caps), "fit": "weighted-median truth/raw ratio on other folds, weights raw, factors clipped [0.5,2]", "parameters_by_fold": scalar_params},
            "first_code_digit_mass_scaling": {**score(bucket_pred, truth, caps, unit_caps), "fit": "0.5*sum(((X*beta-truth)/five_MAE_caps)^2)/n_train + 0.5*||beta-1||^2; beta in [0.5,2]^9; lambda=1", "prefixes_have_no_assumed_semantic_taxonomy": True, "parameters_by_fold": bucket_params, "convergence_by_fold": bucket_iterations},
        },
        "limitations": [
            "Every oracle uses each development dish's reference nutrient vector; true-mass scenarios additionally use its reference weight. These are prohibited at inference.",
            "The free-share oracle can assign zero to predicted components; this is not proof that such foods are false detections.",
            "Fixed C support cannot introduce omitted foods or fix code density errors. Aggregate labels do not identify these causes separately.",
            "The observed eight nutrient passes are label-conditioned feasible allocations, not a guarantee that F or a future model can reproduce them.",
            "The same 84-row development set has been reused for method exploration; fold separation does not remove post-selection optimism.",
        ],
    }
    if any((ROOT / name).read_bytes() != value for name, value in data.items()):
        raise RuntimeError("development inputs changed during analysis")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Recompute and compare saved aggregate without writing")
    args = parser.parse_args()
    result = run()
    payload = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n"
    if args.check:
        if OUT.read_text() != payload:
            raise SystemExit("aggregate reproducibility check failed")
    else:
        OUT.write_text(payload)
    print(json.dumps({"status": "reproduced" if args.check else "written", "output": str(OUT.relative_to(ROOT)), "sha256": sha(payload.encode()), "n": result["population"]["n"], "oracle_nutrient_passes": result["scenarios"]["oracle_true_mass_free_shares"]["nutrient_checks_passed_of_8"], "oracle_converged_n": result["scenarios"]["oracle_true_mass_free_shares"]["solver"]["converged_n"]}))


if __name__ == "__main__":
    main()
