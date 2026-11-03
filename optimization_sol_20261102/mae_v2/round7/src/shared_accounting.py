"""Dataset-independent M accounting; no labels, options or sample metadata.

Preserves the original C layout/child retrieval/quantity implementations. M adds
one whole-food retrieval per decomposed parent and an exclusive joint route/code
choice. Dataset-specific fallback and scoring belong outside this module.
"""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
import json

from opt_pipeline import ContractError, _code, _json, _object, encode_image
from pipeline_v2 import ComponentPipeline, _digest, _flatten, _image_hash, _parse_layout

METHOD_VERSION = "shared-accounting-M.1"
IDENTITY_CONFIG = {"image_mode": "native", "candidate_cap": 32,
                   "crop_review": False, "portion_mode": "direct"}
QUANTITY_CONFIG = {**IDENTITY_CONFIG, "portion_mode": "total_ratio"}


def fuse_whole_rankings(dense_codes, lexical_codes):
    """One text, two top-12 rankings, RRF60, at most 24 unique codes."""
    score = Counter()
    for ranking in (dense_codes, lexical_codes):
        if not isinstance(ranking, list) or len(ranking) > 12:
            raise ContractError("invalid_whole_ranking")
        checked = [_code(code) for code in ranking]
        if len(set(checked)) != len(checked):
            raise ContractError("invalid_whole_ranking")
        for rank, code in enumerate(checked, 1):
            score[code] += 1.0 / (60 + rank)
    result = sorted(score, key=lambda code: (-score[code], code))[:24]
    if not result:
        raise ContractError("empty_whole_candidates")
    return result


def _parents(layout):
    if not isinstance(layout, dict) or layout.get("status") != "ok":
        raise ContractError("missing_complete_layout")
    parsed = _parse_layout(json.dumps({"coverage_complete": layout.get("coverage_complete"),
                                      "parents": layout.get("parents")}))
    if not parsed["coverage_complete"]:
        raise ContractError("incomplete_visible_coverage")
    return parsed["parents"]


def _bank(codes, cap):
    if not isinstance(codes, list) or not 1 <= len(codes) <= cap:
        raise ContractError("invalid_branch_candidates")
    checked = [_code(code) for code in codes]
    if len(set(checked)) != len(checked):
        raise ContractError("duplicate_branch_candidate")
    return checked


def validate_child_banks(parents, child_banks):
    if (not isinstance(child_banks, dict)
            or set(child_banks) != {c["component_id"] for p in parents for c in p["components"]}):
        raise ContractError("branch_bank_keys_mismatch")
    for bank in child_banks.values():
        _bank(bank, 32)


def validate_banks(parents, child_banks, whole_banks):
    validate_child_banks(parents, child_banks)
    if (not isinstance(whole_banks, dict)
            or set(whole_banks) != {p["parent_id"] for p in parents if p["accounting"] == "components"}):
        raise ContractError("branch_bank_keys_mismatch")
    for bank in whole_banks.values():
        _bank(bank, 24)


def build_joint_context(initial_layout, child_banks, whole_banks, candidate_rows):
    """One deduplicated catalog table; model cannot supply geometry or new food."""
    parents = _parents(initial_layout)
    validate_banks(parents, child_banks, whole_banks)
    codes = list(dict.fromkeys(code for bank in [*child_banks.values(), *whole_banks.values()]
                               for code in bank))
    table = candidate_rows(codes)
    if (not isinstance(table, list) or len(table) != len(codes)
            or [row.get("code") for row in table] != codes):
        raise ContractError("candidate_projection_mismatch")
    return {"parents": [{"parent_id": p["parent_id"], "description": p["description"],
        "initial_accounting": p["accounting"], "bbox": deepcopy(p["bbox"]),
        "region_ids": list(p["region_ids"]),
        "children": [{"component_id": c["component_id"], "description": c["description"],
                      "candidate_codes": list(child_banks[c["component_id"]])}
                     for c in p["components"]],
        "whole_candidate_codes": list(whole_banks.get(p["parent_id"], []))}
        for p in parents], "catalog": table}


def parse_joint_choice(raw, initial_layout, child_banks, whole_banks):
    parents = _parents(initial_layout)
    validate_banks(parents, child_banks, whole_banks)
    data = _object(_json(raw), {"parents"})
    if not isinstance(data["parents"], list) or len(data["parents"]) != len(parents):
        raise ContractError("missing_or_extra_joint_parent")
    expected, choices = {p["parent_id"]: p for p in parents}, {}
    for row in data["parents"]:
        _object(row, {"parent_id", "route", "whole_code", "children"})
        pid, route = row["parent_id"], row["route"]
        if not isinstance(pid, str) or pid not in expected or pid in choices:
            raise ContractError("invalid_joint_parent")
        if not isinstance(row["children"], list):
            raise ContractError("invalid_joint_children")
        if route == "whole":
            if expected[pid]["accounting"] != "components" or row["children"]:
                raise ContractError("invalid_whole_route")
            code = _code(row["whole_code"])
            if code not in whole_banks[pid]:
                raise ContractError("whole_code_outside_branch")
            choices[pid] = {"route": route, "codes": {pid + "c1": code}}
        elif route == "keep_children":
            if row["whole_code"] is not None:
                raise ContractError("simultaneous_whole_and_children")
            child_ids = {c["component_id"] for c in expected[pid]["components"]}
            selected = {}
            if len(row["children"]) != len(child_ids):
                raise ContractError("missing_or_extra_joint_child")
            for child in row["children"]:
                _object(child, {"component_id", "code"})
                cid = child["component_id"]
                if not isinstance(cid, str) or cid not in child_ids or cid in selected:
                    raise ContractError("invalid_joint_child")
                code = _code(child["code"])
                if code not in child_banks[cid]:
                    raise ContractError("child_code_outside_branch")
                selected[cid] = code
            choices[pid] = {"route": route, "codes": selected}
        else:
            raise ContractError("invalid_joint_route")

    final_parents, candidates, entities = [], {}, []
    for original in parents:
        parent = deepcopy(original)
        pid, choice = parent["parent_id"], choices[parent["parent_id"]]
        if choice["route"] == "whole":
            parent["accounting"] = "composite"
            parent["components"] = [{"component_id": pid + "c1",
                "description": parent["description"], "broad_query": parent["description"]}]
        for child in parent["components"]:
            cid = child["component_id"]
            collapsed = choice["route"] == "whole"
            candidates[cid] = deepcopy(whole_banks[pid] if collapsed else child_banks[cid])
            entities.append({"parent_id": pid, "initial_accounting": original["accounting"],
                "final_accounting": parent["accounting"], "route": choice["route"],
                "entity_id": pid + ":whole" if collapsed else cid,
                "legacy_component_id": cid,
                "replaced_child_ids": [c["component_id"] for c in original["components"]] if collapsed else [],
                "selected_code": choice["codes"][cid],
                "candidate_branch": pid + ":whole" if collapsed else cid})
        final_parents.append(parent)
    # Apply the original limits and ownership rules to the reconstructed tree.
    final_parents = _parse_layout(json.dumps({"coverage_complete": True, "parents": final_parents}))["parents"]
    leaves = _flatten(final_parents)
    for leaf in leaves:
        leaf.update(primary_code=choices[leaf["parent_id"]]["codes"][leaf["component_id"]],
                    alternative_codes=[])
    return {"parents": final_parents, "leaves": leaves, "items": deepcopy(leaves),
            "candidates": candidates, "entities": entities}


def coding_snapshot(identity):
    """Freeze the coding denominator before any quantity estimate can fail."""
    if not isinstance(identity, dict) or identity.get("status") != "ok":
        return {"ordered_codes": [], "final_codes": [], "primary_code": None, "ranked_leaf_ids": []}
    parents = _parse_layout(json.dumps({"coverage_complete": True, "parents": identity.get("parents")}))["parents"]
    expected = {c["component_id"] for p in parents for c in p["components"]}
    supplied = identity.get("leaves")
    if not isinstance(supplied, list) or len(supplied) != len(expected):
        raise ContractError("coding_leaf_mismatch")
    leaves = {}
    for leaf in supplied:
        cid = leaf.get("component_id") if isinstance(leaf, dict) else None
        if not isinstance(cid, str) or cid not in expected or cid in leaves:
            raise ContractError("coding_leaf_mismatch")
        leaves[cid] = _code(leaf.get("primary_code"))
    ranked = []
    for parent in sorted(parents, key=lambda p: (-((p["bbox"][2] - p["bbox"][0]) *
            (p["bbox"][3] - p["bbox"][1])), p["parent_id"])):
        ranked.extend(sorted(c["component_id"] for c in parent["components"]))
    ordered = list(dict.fromkeys(leaves[cid] for cid in ranked))
    return {"ordered_codes": ordered, "final_codes": ordered[:3],
            "primary_code": ordered[0] if ordered else None, "ranked_leaf_ids": ranked}


class SharedAccountingPipeline(ComponentPipeline):
    """M0 is inherited C; M changes only retrieval/accounting/identity choice."""

    def identify_candidate(self, image_path, initial_layout, child_banks):
        if not isinstance(initial_layout, dict):
            raise ContractError("missing_complete_layout")
        stages = deepcopy(initial_layout.get("stages", []))
        if initial_layout.get("status") != "ok":
            return self._result(stages, status="failed", failure=initial_layout.get("failure", "layout_failed"),
                parents=[], items=[], leaves=[], final_codes=[], selected_codes=[], retrieved_codes=[],
                candidates={}, layout_result=deepcopy(initial_layout), method_version=METHOD_VERSION)
        parents = self._checked_layout(image_path, initial_layout)
        validate_child_banks(parents, child_banks)
        if any(code not in self.foods for bank in child_banks.values() for code in bank):
            raise ContractError("candidate_outside_catalog")
        eligible = [p for p in parents if p["accounting"] == "components"]
        queries = [p["description"] for p in eligible]
        vectors = self.embed(queries) if queries else []
        if not isinstance(vectors, list) or len(vectors) != len(queries):
            raise ContractError("embedding_count_mismatch")
        whole_banks = {p["parent_id"]: fuse_whole_rankings(self.retriever.dense(vector, 12),
            self.retriever.lexical(text, 12)) for p, text, vector in zip(eligible, queries, vectors)}
        validate_banks(parents, child_banks, whole_banks)
        stages.append({"stage": "whole_retrieval", "attempts": [], "queries": queries,
            "codes_by_parent": deepcopy(whole_banks), "candidate_cap": 24})
        context = build_joint_context(initial_layout, child_banks, whole_banks, self._candidates)
        prompt = ("Choose a nutrient-accounting representation for every original parent region. "
            "Keep physical ownership and every parent fixed. For initial components choose either "
            "keep_children (one candidate code for EACH original child) or whole (ONE whole candidate "
            "covering that entire parent). Never count both a whole food and its ingredients. For initial "
            "composite you MUST keep_children; no splitting. Prefer the representation supported by the "
            "visible cooked dish and available catalogue descriptions. Do not add unseen oil, ingredients "
            "or sides. Catalogue density is generic data, never a nutrient target. Relationship hints are "
            "lexical hypotheses, not verified facts. Do not change quantities or output geometry. "
            "Return ONLY JSON with every parent exactly once, no extra fields: "
            '{"parents":[{"parent_id":"p1","route":"whole","whole_code":"12345678",'
            '"children":[]},{"parent_id":"p2","route":"keep_children","whole_code":null,'
            '"children":[{"component_id":"p2c1","code":"23456789"}]}]}. Context: ' +
            json.dumps(context))
        parsed = self._stage("joint_accounting", prompt, encode_image(image_path, "native"),
            lambda raw: parse_joint_choice(raw, initial_layout, child_banks, whole_banks), stages)
        retrieved = list(dict.fromkeys(c for bank in [*child_banks.values(), *whole_banks.values()] for c in bank))
        if parsed is None:
            return self._result(stages, status="failed", failure="joint_accounting_contract", parents=parents,
                leaves=[], items=[], candidates={}, final_codes=[], selected_codes=[], retrieved_codes=retrieved,
                layout_result=deepcopy(initial_layout), method_version=METHOD_VERSION)
        result = self._result(stages, status="ok", failure=None, **parsed,
            input_image_sha256=_image_hash(image_path), layout_result=deepcopy(initial_layout),
            child_banks=deepcopy(child_banks), whole_banks=deepcopy(whole_banks),
            accounting_inputs_hash=_digest({"layout": initial_layout,
                "child_banks": child_banks, "whole_banks": whole_banks}),
            retrieved_codes=retrieved, config=self.configuration(IDENTITY_CONFIG),
            pipeline_version=METHOD_VERSION, method_version=METHOD_VERSION)
        result["coding"] = coding_snapshot(result)
        result["final_codes"] = list(result["coding"]["ordered_codes"])
        result["selected_codes"] = list(result["final_codes"])
        return result

    def portion_candidate(self, image_path, identity):
        if identity.get("status") != "ok":
            return super().portion(image_path, identity, QUANTITY_CONFIG)
        # Rebuild from frozen route/code decisions; detect tampered geometry,
        # changed banks, replaced IDs or an old leaf mass attached to a whole.
        initial = identity.get("layout_result")
        self._checked_layout(image_path, initial)
        if identity.get("accounting_inputs_hash") != _digest({"layout": initial,
                "child_banks": identity.get("child_banks"), "whole_banks": identity.get("whole_banks")}):
            raise ContractError("accounting_inputs_changed")
        rows = []
        for p in identity.get("parents", []):
            entities = [e for e in identity.get("entities", []) if e["parent_id"] == p["parent_id"]]
            if not entities:
                raise ContractError("missing_accounting_entity")
            whole = entities[0]["route"] == "whole"
            rows.append({"parent_id": p["parent_id"], "route": entities[0]["route"],
                "whole_code": entities[0]["selected_code"] if whole else None,
                "children": [] if whole else [{"component_id": e["legacy_component_id"],
                    "code": e["selected_code"]} for e in entities]})
        rebuilt = parse_joint_choice(json.dumps({"parents": rows}), initial,
                                     identity.get("child_banks"), identity.get("whole_banks"))
        if any(identity.get(key) != value for key, value in rebuilt.items()):
            raise ContractError("accounting_identity_changed")
        if identity.get("coding") != coding_snapshot(identity):
            raise ContractError("coding_snapshot_changed")
        return super().portion(image_path, identity, QUANTITY_CONFIG)
