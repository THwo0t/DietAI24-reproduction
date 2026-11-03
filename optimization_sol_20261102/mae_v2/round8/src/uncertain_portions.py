"""Dataset-blind physical-leaf alternatives and canonical FNDDS quantities."""
from copy import deepcopy
from fractions import Fraction
import json
import re

from opt_pipeline import ContractError, SYSTEM, TARGETS, NUTRIENTS, _code, _json, _number, _object, encode_image
from pipeline_v2 import ComponentPipeline, _digest, _flatten, _parse_layout, _positive

VERSION = "uncertain-portions-N.1"
REPAIR = ('Correct FORMAT only to satisfy the original contract. Preserve visual interpretation. '
          'Do not reconsider accuracy. Return only the requested JSON. Contract error: ')
LEADING = re.compile(r"^\s*(\d+(?:\.\d+)?(?:[ -]\d+/\d+)?|\d+/\d+|\.\d+)\s+(.+)$")
UNIT_WORDS = {
    "cups": "cup", "tablespoons": "tablespoon", "tbsp": "tablespoon",
    "teaspoons": "teaspoon", "tsp": "teaspoon", "pieces": "piece", "slices": "slice",
    "patties": "patty", "eggs": "egg", "muffins": "muffin", "rolls": "roll",
    "buns": "bun", "sandwiches": "sandwich", "tortillas": "tortilla",
    "biscuits": "biscuit", "cookies": "cookie", "fillets": "fillet",
    "drumsticks": "drumstick", "wings": "wing", "breasts": "breast", "thighs": "thigh",
    "links": "link", "meatballs": "meatball", "pancakes": "pancake", "waffles": "waffle",
    "scoops": "scoop"}


def positive_fraction(text):
    try:
        parts = re.split(r"[ -]", text)
        number = Fraction(parts[0]) + Fraction(parts[1]) if len(parts) == 2 else Fraction(text)
        _positive(float(number))
    except (ValueError, ZeroDivisionError, OverflowError):
        raise ContractError("invalid_catalog_unit_quantity") from None
    return number


def canonical_options(options, code):
    """Input is the unchanged old usable-unit filter, never ASA legal options."""
    code = _code(code)
    groups = {}
    for option in options:
        match = LEADING.fullmatch(option["description"])
        if match is None:
            raise ContractError("catalog_unit_prefix_missing")
        quantity = positive_fraction(match[1])
        tail = " ".join(match[2].lower().split())
        head = re.match(r"[a-z]+", tail)
        if head is None:
            raise ContractError("catalog_unit_word_missing")
        word = UNIT_WORDS.get(head[0], head[0])
        label = "1 " + word + tail[len(head[0]):]
        try:
            grams = _positive(float(Fraction(str(option["grams"])) / quantity))
        except (ValueError, ZeroDivisionError, OverflowError):
            raise ContractError("catalog_unit_conversion_invalid") from None
        source = {"option_id": option["option_id"], "description": option["description"],
            "grams": _positive(option["grams"]), "quantity_numerator": quantity.numerator,
            "quantity_denominator": quantity.denominator}
        groups.setdefault(label, {}).setdefault(grams, []).append(source)
    units, conflicts = [], []
    for label, weights in groups.items():
        if len(weights) != 1:
            conflicts.append({"description": label, "different_weights": len(weights),
                "excluded_source_option_ids": sorted(s["option_id"] for rows in weights.values() for s in rows)})
            continue
        grams, sources = next(iter(weights.items()))
        sources.sort(key=lambda row: row["option_id"])
        family = next((i for i, name in enumerate(("cup", "tablespoon", "teaspoon"))
                       if re.match(r"^1 " + name + r"\b", label)), 3)
        units.append({"unit_id": "u" + _digest({"code": code, "label": label, "grams": grams})[:24],
            "description": label, "grams_per_unit": grams, "sources": sources, "family": family})
    units.sort(key=lambda row: (row["family"], row["description"], row["grams_per_unit"], row["sources"][0]["option_id"]))
    return {"units": units[:12], "conflicts": sorted(conflicts, key=lambda row: row["description"]),
            "available_before_cap": len(units)}


def physical_inputs(base, foods):
    parents = _parse_layout(json.dumps({"coverage_complete": True, "parents": base["parents"]}))["parents"]
    physical = _flatten(parents)
    banks = base["candidates"]
    expected = {leaf["component_id"] for leaf in physical}
    if set(banks) != expected or any(not isinstance(bank, list) or not 1 <= len(bank) <= 32
            or len(set(bank)) != len(bank) or any(_code(c) not in foods for c in bank) for bank in banks.values()):
        raise ContractError("N_invalid_upstream_bank")
    return parents, physical, banks


def materialize_identity(raw, base, foods):
    data = _object(_json(raw), {"items"})
    parents, physical, banks = physical_inputs(base, foods)
    expected = {leaf["component_id"] for leaf in physical}
    if not isinstance(data["items"], list) or len(data["items"]) != len(expected):
        raise ContractError("N_missing_or_extra_identity")
    chosen = {}
    for row in data["items"]:
        _object(row, {"component_id", "codes"})
        cid, codes = row["component_id"], row["codes"]
        if not isinstance(cid, str) or cid not in expected or cid in chosen:
            raise ContractError("N_invalid_identity_leaf")
        if not isinstance(codes, list) or not 1 <= len(codes) <= 3:
            raise ContractError("N_one_to_three_codes_required")
        checked = [_code(c) for c in codes]
        if len(set(checked)) != len(checked) or not set(checked) <= set(banks[cid]):
            raise ContractError("N_duplicate_or_foreign_identity_code")
        chosen[cid] = checked
    leaves = []
    for leaf in physical:
        codes = chosen[leaf["component_id"]]
        density = {k: _number(sum(_number(foods[c]["density"][k]) / len(codes) for c in codes)) for k in NUTRIENTS}
        leaves.append({**leaf, "primary_code": codes[0], "codes": list(codes), "mean_density": density})
    areas = {p["parent_id"]: (p["bbox"][2] - p["bbox"][0]) * (p["bbox"][3] - p["bbox"][1]) for p in parents}
    ordered_leaves = sorted(leaves, key=lambda leaf: (-areas[leaf["parent_id"]], leaf["parent_id"], leaf["component_id"]))
    ordered_codes = list(dict.fromkeys(codes[rank] for rank in range(3)
        for codes in [leaf["codes"] for leaf in ordered_leaves] if len(codes) > rank))
    result = {"status": "ok", "failure": None, "method_version": VERSION,
        "base_identity_sha256": _digest(base), "input_image_sha256": base["input_image_sha256"],
        "upstream_identity_repaired": bool(base.get("repaired")),
        "selection": [{"component_id": leaf["component_id"], "codes": chosen[leaf["component_id"]]} for leaf in physical],
        "parents": parents, "leaves": leaves, "candidates": deepcopy(banks),
        "retrieved_codes": list(dict.fromkeys(c for bank in banks.values() for c in bank)),
        "coding": {"ordered_codes": ordered_codes, "final_codes": ordered_codes[:3],
                   "primary_code": ordered_codes[0] if ordered_codes else None}}
    result["integrity"] = _digest(result)
    return result


def aggregate(identity, masses, stages, **extra):
    leaves = identity["leaves"]
    if set(masses) != {leaf["component_id"] for leaf in leaves}:
        raise ContractError("N_incomplete_physical_masses")
    totals, portions = dict.fromkeys(TARGETS, 0.0), []
    for leaf in leaves:
        grams = _positive(masses[leaf["component_id"]])
        totals["weight"] = _number(totals["weight"] + grams)
        # Densities are per100g. Divide first so a finite mathematical result
        # is not lost through an avoidable grams*density intermediate overflow.
        contribution = {k: _number(grams * (leaf["mean_density"][k] / 100)) for k in NUTRIENTS}
        for key, value in contribution.items():
            totals[key] = _number(totals[key] + value)
        portions.append({"component_id": leaf["component_id"], "parent_id": leaf["parent_id"],
            "grams": grams, "code": leaf["primary_code"], "codes": list(leaf["codes"]),
            "density": deepcopy(leaf["mean_density"]), "nutrient_contribution": contribution})
    return ComponentPipeline._result(stages, status="ok", failure=None, prediction=totals,
        raw_prediction=deepcopy(totals), raw_leaves=portions, portions=deepcopy(portions),
        method_version=VERSION, **extra)


class UncertainPortionPipeline(ComponentPipeline):
    def _stage(self, name, prompt, images, parser, stages):
        # Same fixed two-call parser rule as ComponentPipeline, with a durable
        # admission proof before the optional FORMAT-only request.
        images = [images] if isinstance(images, str) else (images or [])
        messages = [{"role": "system", "content": SYSTEM}, {"role": "user", "content":
            [{"type": "text", "text": prompt}] +
            [{"type": "image_url", "image_url": {"url": picture}} for picture in images]}]
        stage = {"stage": name, "attempts": [], "image_count": len(images)}
        stages.append(stage)
        for attempt in range(2):
            raw = self.chat(messages)
            entry = {"raw": raw, "valid": False}; stage["attempts"].append(entry)
            try:
                parsed = parser(raw)
            except ContractError as exc:
                entry["error"] = str(exc)
                if attempt == 0:
                    callback = getattr(self, "on_format_failure", None)
                    if callback is not None: callback(name, raw, str(exc))
                    messages += [{"role": "assistant", "content": raw},
                                 {"role": "user", "content": REPAIR + str(exc)}]
            else:
                entry["valid"] = True; stage["parsed"] = parsed
                return parsed
        return None

    def identify_uncertain(self, image, base):
        stages = []
        if base.get("status") != "ok":
            return self._result(stages, status="failed", failure="N_upstream_identity_failed", leaves=[],
                coding={"ordered_codes": [], "final_codes": [], "primary_code": None})
        _, leaves = self._checked_identity(image, base)
        physical_inputs(base, self.foods)  # Source defects never spend a format-repair call.
        codes = list(dict.fromkeys(c for bank in base["candidates"].values() for c in bank))
        context = {"items": [{"component_id": leaf["component_id"], "description": leaf["description"],
            "parent_description": leaf["parent_description"], "accounting": leaf["accounting"],
            "candidate_codes": base["candidates"][leaf["component_id"]]} for leaf in leaves],
            "catalog": [{"code": c, "description": self.foods[c]["description"],
                         "category": self.foods[c].get("category", "")} for c in codes]}
        prompt = ("Identify every fixed visible physical food from the RGB image. For each leaf return one to three "
            "distinct ranked candidate identity codes; first is primary. Use three when three entries plausibly "
            "describe that SAME visible food and preparation; use fewer when fewer are plausible. Alternatives "
            "are identities of ONE physical food, never extra ingredients or additional servings. Do not add, "
            "merge or split leaves. A component cannot become the entire mixed parent dish, and a composite "
            "cannot become just its oil or sauce. Preserve all listed leaves, visible preparation and uncertainty. "
            "Choose only that leaf's candidate codes. Do not estimate quantity or nutrients. Return ONLY JSON "
            '{"items":[{"component_id":"p1c1","codes":["12345678","23456789"]}]}. Context: ' + json.dumps(context))
        result = self._stage("N_identity", prompt, encode_image(image, "native"),
            lambda raw: materialize_identity(raw, base, self.foods), stages)
        if result is None:
            return self._result(stages, status="failed", failure="N_identity_contract", leaves=[],
                coding={"ordered_codes": [], "final_codes": [], "primary_code": None})
        return self._result(stages, **result)

    def checked_n(self, image, identity, base):
        self._checked_identity(image, base)
        expected = materialize_identity(json.dumps({"items": identity["selection"]}), base, self.foods)
        supplied = {k: v for k, v in identity.items() if k not in {"stages", "repaired"}}
        if supplied != expected:
            raise ContractError("N_identity_changed_before_quantity")
        return expected

    def density_portion(self, image, identity, base, old_portion):
        if identity.get("status") != "ok":
            return self._result([], status="failed", failure="N_identity_failed", prediction=None, raw_leaves=[])
        checked = self.checked_n(image, identity, base)
        if old_portion.get("status") != "ok":
            return self._result([], status="failed", failure="N_imported_quantity_failed", prediction=None, raw_leaves=[])
        masses = self._checked_base_masses(base, old_portion)
        try:
            return aggregate(checked, masses, [], method="N-density",
                             imported_quantity_repaired=bool(old_portion.get("repaired")))
        except ContractError:
            return self._result([], status="failed", failure="N_density_numeric_contract",
                                prediction=None, raw_leaves=[])

    def unit_context(self, identity):
        result = {}
        for leaf in identity["leaves"]:
            code = leaf["primary_code"]
            result[leaf["component_id"]] = canonical_options(self.usable_standard_options(code), code)
        return result

    @staticmethod
    def parse_quantities(raw, identity, context):
        data = _object(_json(raw), {"items"})
        expected = {leaf["component_id"] for leaf in identity["leaves"]}
        if set(context) != expected or not isinstance(data["items"], list) or len(data["items"]) != len(expected):
            raise ContractError("N_missing_or_extra_quantity")
        masses, choices = {}, []
        for row in data["items"]:
            _object(row, {"component_id", "mode", "unit_id", "quantity", "grams"})
            cid = row["component_id"]
            if not isinstance(cid, str) or cid not in expected or cid in masses:
                raise ContractError("N_invalid_quantity_leaf")
            options = context[cid]["units"]
            if options:
                if row["mode"] != "unit" or row["grams"] is not None:
                    raise ContractError("N_catalog_unit_required")
                if not isinstance(row["unit_id"], str):
                    raise ContractError("N_invalid_unit_id")
                unit = next((unit for unit in options if unit["unit_id"] == row["unit_id"]), None)
                if unit is None:
                    raise ContractError("N_unit_outside_primary_catalog")
                quantity = _positive(row["quantity"])
                grams = _positive(quantity * unit["grams_per_unit"])
                choices.append({"component_id": cid, "mode": "unit", "unit_id": unit["unit_id"],
                    "quantity": quantity, "grams": grams, "unit": deepcopy(unit)})
            else:
                if row["mode"] != "direct" or row["unit_id"] is not None or row["quantity"] is not None:
                    raise ContractError("N_direct_grams_only_without_unit")
                grams = _positive(row["grams"])
                choices.append({"component_id": cid, "mode": "direct", "grams": grams})
            masses[cid] = grams
        # Validation includes the COMPLETE vector in the same bounded parser
        # contract, so real total overflow receives format repair/atomic failure.
        aggregate(identity,masses,[])
        return {"masses": masses, "choices": sorted(choices, key=lambda row: row["component_id"])}

    def unit_portion(self, image, identity, base):
        if identity.get("status") != "ok":
            return self._result([], status="failed", failure="N_identity_failed", prediction=None, raw_leaves=[])
        checked = self.checked_n(image, identity, base)
        options = self.unit_context(checked)
        context = [{"component_id": leaf["component_id"], "description": leaf["description"],
            "parent_description": leaf["parent_description"], "primary_food": self.foods[leaf["primary_code"]]["description"],
            "mode": "unit" if options[leaf["component_id"]]["units"] else "direct",
            "units": [{"unit_id": u["unit_id"], "description": u["description"]}
                      for u in options[leaf["component_id"]]["units"]]} for leaf in checked["leaves"]]
        prompt = ("Estimate cooked edible quantities of EVERY listed fixed physical food from the RGB image. "
            "Do not change identity, add hidden oil/foods, omit leaves, or assume a measured plate diameter. "
            "Where mode=unit choose one listed canonical ONE-unit description and estimate its positive count "
            "or volume quantity. All units start with ONE: 1.5 cups means quantity=1.5, even if the original "
            "database recorded a half-cup portion. Program conversion supplies grams; do not output grams in "
            "unit mode. Where mode=direct (no usable physical catalog unit), estimate positive grams. Keep "
            "inactive fields null. Values must be finite and positive; zero must not remove visible food. "
            "Return each leaf once, ONLY JSON: "
            '{"items":[{"component_id":"p1c1","mode":"unit","unit_id":"u...","quantity":1.5,"grams":null},'
            '{"component_id":"p2c1","mode":"direct","unit_id":null,"quantity":null,"grams":75}]}. Context: ' + json.dumps(context))
        stages = []
        parsed = self._stage("N_units", prompt, encode_image(image, "native"),
            lambda raw: self.parse_quantities(raw, checked, options), stages)
        if parsed is None:
            return self._result(stages, status="failed", failure="N_quantity_contract", prediction=None, raw_leaves=[])
        return aggregate(checked, parsed["masses"], stages, method="N-units", unit_choices=parsed["choices"],
            unit_options=options, standard_portion_source_sha256=self.catalog.get("standard_portion_source_sha256"))
