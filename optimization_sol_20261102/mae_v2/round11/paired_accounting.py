"""Pure successful-stage algebra for preregistered O, Q, D and Q+D.

No I/O, provider, labels, calibration or failure substitution. A future runner
must first validate the full fixed identity/candidate snapshot, then supply its
items and the generic catalogue. This component is not a paid-run entry point;
failure policy, slots, exact imports and isolated ASA attachment remain pending.
"""
from copy import deepcopy
import hashlib
import json
import math
import re

NUTRIENTS = ('energy', 'fat', 'carbs', 'protein')
TARGETS = ('weight',) + NUTRIENTS
MAX_RESPONSE_BYTES = 32768


class PairContractError(ValueError):
    pass


def require(value, code):
    if not value:
        raise PairContractError(code)


def number(value, *, positive=False):
    require(type(value) in (int, float), 'numeric_value_required')
    try:
        result = float(value)
    except (OverflowError, ValueError):
        raise PairContractError('finite_number_required') from None
    require(math.isfinite(result) and (result > 0 if positive else result >= 0),
            'finite_positive_number_required' if positive else 'finite_nonnegative_number_required')
    return result


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
        allow_nan=False, separators=(',', ':')).encode()).hexdigest()


def obj(value, keys):
    require(isinstance(value, dict) and set(value) == set(keys), 'exact_object_fields_required')
    return value


def response(raw):
    require(isinstance(raw, str) and len(raw.encode()) <= MAX_RESPONSE_BYTES, 'bounded_json_response_required')
    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, 'duplicate_json_key')
            result[key] = value
        return result
    def nonfinite(_):
        raise PairContractError('nonfinite_json')
    try:
        return json.loads(raw, object_pairs_hook=unique, parse_constant=nonfinite)
    except (json.JSONDecodeError, UnicodeError, RecursionError):
        raise PairContractError('invalid_json_response') from None


def checked_items(items):
    require(isinstance(items, list) and 1 <= len(items) <= 20, 'bounded_fixed_items_required')
    regions = set()
    for index, item in enumerate(items, 1):
        obj(item, ('item_id', 'description', 'broad_query', 'region_ids', 'primary_code', 'alternative_codes'))
        require(item['item_id'] == 'i' + str(index), 'fixed_consecutive_item_order_required')
        require(all(isinstance(item[key], str) and item[key].strip() for key in ('description', 'broad_query')),
                'fixed_item_text_required')
        local = item['region_ids']
        require(isinstance(local, list) and local and all(isinstance(v, str) and re.fullmatch(r'r[1-9]\d*', v) for v in local)
                and len(set(local)) == len(local) and not regions.intersection(local), 'disjoint_fixed_regions_required')
        regions.update(local)
        require(isinstance(item['alternative_codes'], list) and len(item['alternative_codes']) <= 2,
                'bounded_fixed_code_set_required')
        codes = [item['primary_code']] + item['alternative_codes']
        require(all(isinstance(code, str) and re.fullmatch(r'[0-9]{8}', code) for code in codes)
                and len(set(codes)) == len(codes), 'unique_fixed_eight_digit_codes_required')
    return deepcopy(items)


def contexts(items, foods):
    items = checked_items(items)
    quantity, density = [], []
    for item in items:
        codes = [item['primary_code']] + item['alternative_codes']
        require(all(code in foods and isinstance(foods[code]['description'], str)
                    and foods[code]['description'].strip() for code in codes), 'fixed_catalogue_codes_required')
        common = {key: deepcopy(item[key]) for key in ('item_id', 'description', 'region_ids')}
        quantity.append({**common, 'mass_context_code': item['primary_code'],
                         'selected_food': foods[item['primary_code']]['description']})
        density.append({**common, 'fixed_codes': [
            {'code': code, 'description': foods[code]['description']} for code in codes]})
    return quantity, density


def quantity_prompt(items, foods):
    context, _ = contexts(items, foods)
    return ('Estimate the whole cooked edible mass and relative edible MASS shares of the fixed physical foods '
        'in this image. Ratios describe mass, not pixel area. Use uncertain visible scale cues; do not assume '
        'a plate diameter. Do not add, remove or split foods, count alternative identities as extra portions, '
        'or invent hidden ingredients. Return each fixed item ID exactly once. Return only a JSON object '
        'with exactly total_grams (a strictly positive finite number) and items (an array of objects '
        'with exactly item_id and ratio, where ratio is a strictly positive finite number). '
        'Generic food descriptions identify the fixed foods; they are not image reference labels. Fixed items: '
        + json.dumps(context, allow_nan=False))


def density_prompt(items, foods):
    _, context = contexts(items, foods)
    return ('For each fixed physical food, choose the ONE code whose food identity and preparation state '
        'best match visible evidence in this image. Choose only from that item\'s fixed_codes. These are '
        'alternative identities of one physical serving. Do not add foods or codes, infer hidden ingredients, '
        'or estimate grams or portions. Return only a JSON object with exactly items, an array of '
        'objects with exactly item_id and density_code. Return every fixed item ID exactly once. Fixed items: '
        + json.dumps(context, allow_nan=False))


def rows_by_id(rows, items, keys):
    require(isinstance(rows, list) and len(rows) == len(items), 'complete_item_rows_required')
    result = {}
    expected = {item['item_id'] for item in items}
    for row in rows:
        obj(row, keys)
        identifier = row['item_id']
        require(isinstance(identifier, str) and identifier in expected and identifier not in result,
                'known_unique_item_ids_required')
        result[identifier] = row
    return result


def parse_quantity(raw, items):
    items = checked_items(items)
    data = obj(response(raw), ('total_grams', 'items'))
    total = number(data['total_grams'], positive=True)
    by_id = rows_by_id(data['items'], items, ('item_id', 'ratio'))
    ratios = [number(by_id[item['item_id']]['ratio'], positive=True) for item in items]
    scale = max(ratios)
    scaled = [number(value / scale, positive=True) for value in ratios]
    denominator = number(math.fsum(scaled), positive=True)
    result = []
    for item, raw_ratio, value in zip(items, ratios, scaled):
        share = number(value / denominator, positive=True)
        result.append({'item_id': item['item_id'], 'ratio': raw_ratio, 'share': share,
                       'grams': number(total * share, positive=True)})
    require(math.isclose(math.fsum(row['share'] for row in result), 1, rel_tol=1e-12)
            and math.isclose(math.fsum(row['grams'] for row in result), total, rel_tol=1e-12),
            'quantity_conservation_failed')
    return {'total_grams': total, 'items': result}


def parse_density(raw, items):
    items = checked_items(items)
    data = obj(response(raw), ('items',))
    by_id = rows_by_id(data['items'], items, ('item_id', 'density_code'))
    result = []
    for item in items:
        code = by_id[item['item_id']]['density_code']
        require(isinstance(code, str) and code in [item['primary_code']] + item['alternative_codes'],
                'density_code_outside_fixed_final_set')
        result.append({'item_id': item['item_id'], 'density_code': code})
    return {'items': result}


def aggregate(items, foods, grams, density_codes=None):
    """Match O's ordered arithmetic; density changes cannot re-estimate mass."""
    totals, leaves = dict.fromkeys(TARGETS, 0.0), []
    for item in items:
        identifier = item['item_id']
        codes = [item['primary_code']] + item['alternative_codes']
        mass = number(grams[identifier], positive=True)
        selected = None if density_codes is None else density_codes[identifier]
        require(selected is None or selected in codes, 'density_code_outside_fixed_final_set')
        used = codes if selected is None else [selected]
        density = {key: number(sum(number(foods[code]['density'][key]) / len(used) for code in used))
                   for key in NUTRIENTS}
        contribution = {key: number(mass * (density[key] / 100)) for key in NUTRIENTS}
        totals['weight'] = number(totals['weight'] + mass)
        for key in NUTRIENTS:
            totals[key] = number(totals[key] + contribution[key])
        leaves.append({'item_id': identifier, 'mass_context_code': item['primary_code'],
            'original_final_codes': list(codes), 'density_code': selected, 'grams': mass,
            'density': density, 'nutrient_contribution': contribution})
    return {'prediction': totals, 'leaves': leaves}


def successful_profiles(items, foods, original_grams, quantity, density):
    """All stages must be valid. A runner must handle failed stages explicitly."""
    items = checked_items(items)
    contexts(items, foods)
    original = rows_by_id(original_grams, items, ('item_id', 'grams'))
    q_raw = {'total_grams': quantity['total_grams'], 'items': [
        {'item_id': row['item_id'], 'ratio': row['ratio']} for row in quantity['items']]}
    q = parse_quantity(json.dumps(q_raw, allow_nan=False), items)
    require(q == quantity, 'quantity_result_changed')
    d = parse_density(json.dumps(density, allow_nan=False), items)
    require(d == density, 'density_result_changed')
    o_mass = {key: number(row['grams'], positive=True) for key, row in original.items()}
    q_mass = {row['item_id']: row['grams'] for row in q['items']}
    d_codes = {row['item_id']: row['density_code'] for row in d['items']}
    result = {profile: aggregate(items, foods, masses, codes) for profile, masses, codes in (
        ('O', o_mass, None), ('Q', q_mass, None), ('D', o_mass, d_codes), ('Q+D', q_mass, d_codes))}
    for left, right in (('O', 'D'), ('Q', 'Q+D')):
        require(result[left]['prediction']['weight'] == result[right]['prediction']['weight']
                and [row['grams'] for row in result[left]['leaves']] == [row['grams'] for row in result[right]['leaves']],
                'paired_mass_manipulation_changed')
    return {'profiles': result, 'fixed_items_sha256': fingerprint(items),
            'quantity_sha256': fingerprint(q), 'density_sha256': fingerprint(d),
            'original_grams_sha256': fingerprint(original_grams)}
