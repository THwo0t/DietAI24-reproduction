"""Reference-informed common-mass bounds, never a predictive calibration."""
from fractions import Fraction
from itertools import combinations
import math

import numpy as np
from scipy.optimize import linprog
from scipy.sparse import coo_matrix

TARGETS = ('weight', 'energy', 'fat', 'carbs', 'protein')
OPTIONS = {'primal_feasibility_tolerance': 1e-9,
           'dual_feasibility_tolerance': 1e-9, 'time_limit': 60.0}


def require(ok, message):
    if not ok:
        raise ValueError(message)


def point_metrics(truth, prediction, thresholds):
    """Same order of operations as frozen opt_metrics._stats."""
    n = len(truth)
    require(n > 0 and np.shape(truth) == np.shape(prediction) == (n, 5), 'five_vectors_required')
    require(np.isfinite(truth).all() and np.isfinite(prediction).all()
            and (truth >= 0).all() and (prediction >= 0).all(), 'invalid_five_vector')
    out = {}
    for k, name in enumerate(TARGETS):
        ref = sum(float(row[k]) / n for row in truth)
        mae = sum(abs(float(a[k]) - float(b[k])) / n for a, b in zip(prediction, truth))
        absolute, relative = thresholds[name]
        require(ref > 0 and absolute > 0 and relative > 0, 'positive_caps_and_means_required')
        out[name] = {'mae': mae, 'reference_mean': ref, 'per_unit': mae / ref,
                     'pass_mae': mae <= absolute, 'pass_per_unit': mae / ref <= relative}
    return {'n': n, 'metrics': out, 'failed_checks': sum(not v[k] for v in out.values()
             for k in ('pass_mae', 'pass_per_unit'))}


def patterns(truth, thresholds):
    """Strict first, then all 45 retained-eight subsets; deduplicate equal caps."""
    n = len(truth)
    means = [sum(float(row[k]) / n for row in truth) for k in range(5)]
    checks = [v for k, name in enumerate(TARGETS)
              for v in (float(thresholds[name][0]), float(thresholds[name][1]) * means[k])]
    require(all(math.isfinite(v) and v > 0 for v in checks), 'invalid_effective_cap')
    seen = set()
    for keep in [(tuple(range(10)))] + list(combinations(range(10), 8)):
        caps = tuple(min((checks[j] for j in keep if j // 2 == k), default=None) for k in range(5))
        if caps in seen:
            continue
        seen.add(caps)
        yield {'retained_checks': list(keep), 'effective_caps': caps}


def problem(densities, fallbacks, truth, caps):
    """Every physical mass variable is shared across five output coordinates."""
    n = len(truth)
    require(n and len(densities) == len(fallbacks) == n and np.shape(truth) == (n, 5),
            'population_mismatch')
    active = [k for k, cap in enumerate(caps) if cap is not None]
    require(active and len(caps) == 5, 'retained_targets_required')
    starts, matrices, offsets, total = [], [], [], 0
    for density, fixed in zip(densities, fallbacks):
        matrix = np.asarray(density, dtype=float).reshape((-1, 5))
        require(np.isfinite(matrix).all() and (matrix >= 0).all(), 'invalid_density')
        require((len(matrix) > 0) != (fixed is not None), 'exactly_one_mass_or_fallback_required')
        if len(matrix):
            require((matrix[:, 0] == 1).all(), 'physical_mass_must_be_counted_once')
        offset = np.zeros(5) if fixed is None else np.asarray(fixed, dtype=float)
        require(offset.shape == (5,) and np.isfinite(offset).all() and (offset >= 0).all(),
                'invalid_fixed_fallback')
        starts.append(total); total += len(matrix); matrices.append(matrix); offsets.append(offset)
    require(np.isfinite(truth).all() and (truth >= 0).all(), 'invalid_truth')
    tindex = total + n * len(active)
    rr, cc, vv, bounds, pairs, coefficient_rows = [], [], [], [], [], []
    def add(entries, rhs):
        index = len(bounds)
        for col, value in entries:
            if value != 0:
                rr.append(index); cc.append(col); vv.append(float(value))
        bounds.append(float(rhs))
        return index
    for i in range(n):
        one_pairs, one_coeff = {}, []
        for a, k in enumerate(active):
            cap = caps[k]
            require(math.isfinite(cap) and cap > 0, 'invalid_cap')
            coefficients = [(starts[i] + j, float(d[k] / cap)) for j, d in enumerate(matrices[i])]
            e = total + i * len(active) + a
            rhs = float((truth[i, k] - offsets[i][k]) / cap)
            plus = add(coefficients + [(e, -1)], rhs)
            minus = add([(j, -v) for j, v in coefficients] + [(e, -1)], -rhs)
            one_pairs[k] = (plus, minus)
        for j in range(len(matrices[i])):
            one_coeff.append((starts[i] + j, [float(matrices[i][j, k] / caps[k]) for k in active]))
        pairs.append(one_pairs); coefficient_rows.append(one_coeff)
    budget_rows = {}
    q = float(1 / n)
    for a, k in enumerate(active):
        budget_rows[k] = add([(total + i * len(active) + a, q) for i in range(n)] + [(tindex, -1)], 0)
    A = coo_matrix((vv, (rr, cc)), shape=(len(bounds), tindex + 1)).tocsr()
    objective = np.zeros(tindex + 1); objective[tindex] = 1
    return {'A': A, 'b': np.asarray(bounds), 'c': objective, 'mass_n': total,
            'pairs': pairs, 'coefficient_rows': coefficient_rows, 'budget_rows': budget_rows,
            'q': q, 'matrices': matrices, 'offsets': offsets, 'starts': starts, 'active': active}


def exact_dual_certificate(lp, approximate):
    """Repair a dual and verify ALL columns using exact binary-float rationals."""
    A, b, c = lp['A'], lp['b'], lp['c']
    require(len(approximate) == A.shape[0] and np.isfinite(approximate).all(), 'invalid_dual')
    f = Fraction.from_float
    y = [min(Fraction(0), f(float(v))) for v in approximate]
    for pair, columns in zip(lp['pairs'], lp['coefficient_rows']):
        delta = Fraction(0)
        for _, values in columns:
            values = [f(v) for v in values]
            numerator = sum(v * (y[pair[k][0]] - y[pair[k][1]])
                            for k, v in zip(lp['active'], values))
            denominator = sum(values)
            require(denominator > 0 or numerator == 0, 'zero_density_dual_column')
            if numerator > 0:
                delta = max(delta, numerator / denominator)
        for plus, _ in pair.values():
            y[plus] -= delta
    q = f(lp['q'])
    for k, index in lp['budget_rows'].items():
        y[index] = -max(-y[p[k][0]] - y[p[k][1]] for p in lp['pairs']) / q
    total = -sum(y[index] for index in lp['budget_rows'].values())
    if total > 1:
        y = [v / total for v in y]
    transpose = [Fraction(0) for _ in c]
    coo = A.tocoo()
    for row, col, value in zip(coo.row, coo.col, coo.data):
        transpose[col] += f(float(value)) * y[row]
    require(all(v <= 0 for v in y) and all(v <= f(float(cost)) for v, cost in zip(transpose, c)),
            'exact_dual_feasibility_failed')
    lower = sum(f(float(value)) * multiplier for value, multiplier in zip(b, y))
    lower_float = float(lower)
    require(math.isfinite(lower_float), 'nonfinite_dual_bound')
    lower_float = math.nextafter(lower_float, -math.inf)
    return {'exact_binary_coefficient_dual_feasible': True, 'lower_bound': lower_float,
            'exceeds_one_with_margin': lower > Fraction(1000001, 1000000)}


def solve(densities, fallbacks, truth, caps, thresholds):
    lp = problem(densities, fallbacks, truth, caps)
    result = linprog(lp['c'], A_ub=lp['A'], b_ub=lp['b'], bounds=(0, None),
                     method='highs-ds', options=OPTIONS)
    summary = {'solver_status': int(result.status), 'solver_success': bool(result.success),
               'iterations': int(result.nit)}
    if not result.success or result.x is None or not np.isfinite(result.x).all():
        summary['classification'] = 'numerically_indeterminate'
        return summary, None
    x = result.x
    residual = max(0.0, float(np.max(lp['A'] @ x - lp['b'])))
    negative = max(0.0, float(-np.min(x)))
    summary.update(objective=float(result.fun), max_primal_violation=residual,
                   max_nonnegative_violation=negative)
    if residual > 1e-7 or negative > 1e-7:
        summary['classification'] = 'numerically_indeterminate'
        return summary, None
    masses = np.maximum(x[:lp['mass_n']], 0)
    prediction = np.asarray([offset + matrix.T @ masses[start:start + len(matrix)]
        for offset, matrix, start in zip(lp['offsets'], lp['matrices'], lp['starts'])])
    scores = point_metrics(truth, prediction, thresholds)
    summary['common_witness_scores'] = scores
    try:
        certificate = exact_dual_certificate(lp, result.ineqlin.marginals)
        summary['dual'] = certificate
        summary['primal_dual_gap'] = float(result.fun) - certificate['lower_bound']
    except (ValueError, OverflowError):
        summary['dual'] = {'exact_binary_coefficient_dual_feasible': False}
    summary['classification'] = ('shared_witness' if scores['failed_checks'] <= 2 else
        'verified_numerical_negative' if summary['dual'].get('exceeds_one_with_margin') else
        'numerically_indeterminate')
    return summary, {'masses': masses.tolist(), 'prediction': prediction.tolist()}


def analyze(densities, fallbacks, truth, thresholds):
    truth = np.asarray(truth, dtype=float)
    attempts, witness = [], None
    for spec in patterns(truth, thresholds):
        summary, values = solve(densities, fallbacks, truth, spec['effective_caps'], thresholds)
        summary['retained_checks'] = spec['retained_checks']
        summary['effective_caps'] = list(spec['effective_caps'])
        attempts.append(summary)
        if summary.get('common_witness_scores', {}).get('failed_checks', 10) <= 2:
            witness = values
            break
        if summary['classification'] == 'numerically_indeterminate':
            # Failure to certify one pattern prevents a universal negative.
            # Continue the finite list to retain a chance of a constructive witness.
            continue
    outcome = ('shared_witness' if witness is not None else 'verified_numerical_negative'
        if all(a['classification'] == 'verified_numerical_negative' for a in attempts)
        else 'numerically_indeterminate')
    return {'classification': outcome, 'population_n': len(truth),
            'fallback_n': sum(v is not None for v in fallbacks), 'attempted_unique_patterns': len(attempts),
            'attempts': attempts, 'reference_informed_oracle': True,
            'predictive_result': False}, witness
