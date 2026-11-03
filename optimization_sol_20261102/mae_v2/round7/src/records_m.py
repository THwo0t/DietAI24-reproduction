"""Label-free full-population record assembly; ASA options belong to scorer."""
from copy import deepcopy

from opt_pipeline import TARGETS, _number
from shared_accounting import coding_snapshot


def vector(value):
    if not isinstance(value, dict) or set(value) != set(TARGETS):
        raise ValueError("invalid_five_target_vector")
    return {k: _number(value[k]) for k in TARGETS}


def core_record(row, identity, portion, fallback, coding):
    if coding_snapshot(identity) != coding:
        raise ValueError("pre_portion_coding_changed")
    valid = portion.get("status") == "ok"
    prediction = vector(portion.get("prediction") if valid else fallback)
    leaves = deepcopy(portion.get("portions", [])) if valid else []
    if valid:
        expected = {leaf["component_id"]: leaf for leaf in identity["leaves"]}
        if len(leaves) != len(expected) or {p["component_id"] for p in leaves} != set(expected):
            raise ValueError("incomplete_portion_leaf_join")
        for leaf in leaves:
            original = expected[leaf["component_id"]]
            if leaf["code"] != original["primary_code"] or leaf["parent_id"] != original["parent_id"]:
                raise ValueError("portion_code_join_changed")
            _number(leaf["grams"])
    codes = coding["final_codes"] if row["dataset"] == "asa24" else coding["ordered_codes"]
    retrieved = deepcopy(identity.get("retrieved_codes", []))
    if not set(codes) <= set(retrieved):
        raise ValueError("coding_outside_retrieved_set")
    repaired = bool(identity.get("repaired") or portion.get("repaired"))
    return {**{k: row[k] for k in ("sample_id", "dataset", "group_id", "fold")},
        "coding": deepcopy(coding), "final_codes": list(codes),
        "primary_code": codes[0] if codes else None, "retrieved_codes": retrieved,
        "parents": deepcopy(identity.get("parents", [])), "items": deepcopy(identity.get("leaves", [])),
        "identity_status": identity.get("status"), "portion_status": portion.get("status"),
        "raw_prediction": vector(portion["prediction"]) if valid else None,
        "prediction": prediction, "raw_leaves": leaves,
        "fallback": not valid, "fallback_reason": portion.get("failure") if not valid else None,
        "native_complete": valid and not repaired, "repair_used": repaired,
        "conditional": None, "e2e": {"prediction": deepcopy(prediction), "fallback": not valid}}
