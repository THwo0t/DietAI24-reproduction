"""Synthetic contracts for the common M core; no research data or API."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import unittest

import numpy as np
from PIL import Image, PngImagePlugin

BASE = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(BASE / "src"), str(BASE / "round7/src")]
from opt_pipeline import ContractError, Retriever
from pipeline_v2 import ComponentPipeline
from shared_accounting import (IDENTITY_CONFIG, QUANTITY_CONFIG, SharedAccountingPipeline,
    build_joint_context, coding_snapshot, fuse_whole_rankings, parse_joint_choice)

C = ["11111111", "22222222", "33333333", "44444444"]
CATALOG = {"foods": {code: {"description": text, "category": category, "density":
    {"energy": 100 + i * 10, "fat": i + 1, "carbs": 20 - i, "protein": 5 + i}}
    for i, (code, text, category) in enumerate(zip(C,
        ["chicken cooked", "rice cooked", "rice with chicken", "broccoli cooked"],
        ["Chicken", "Rice", "Mixed dishes", "Vegetables"]))}}


def layout():
    return {"status": "ok", "coverage_complete": True, "parents": [
        {"parent_id": "p1", "description": "chicken rice dish", "bbox": [0, 0, .7, 1],
         "region_ids": ["r1"], "accounting": "components", "components": [
            {"component_id": "p1c1", "description": "chicken", "broad_query": "poultry"},
            {"component_id": "p1c2", "description": "rice", "broad_query": "grain"}]},
        {"parent_id": "p2", "description": "broccoli", "bbox": [.7, 0, 1, 1],
         "region_ids": ["r2"], "accounting": "composite", "components": [
            {"component_id": "p2c1", "description": "broccoli", "broad_query": "vegetables"}]}]}


def choice(collapse=True):
    return {"parents": [
        {"parent_id": "p1", "route": "whole" if collapse else "keep_children",
         "whole_code": C[2] if collapse else None, "children": [] if collapse else [
             {"component_id": "p1c1", "code": C[0]}, {"component_id": "p1c2", "code": C[1]}]},
        {"parent_id": "p2", "route": "keep_children", "whole_code": None,
         "children": [{"component_id": "p2c1", "code": C[3]}]}]}


CHILD = {"p1c1": [C[0]], "p1c2": [C[1]], "p2c1": [C[3]]}
WHOLE = {"p1": [C[2]]}


class SharedCoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.image = Path(self.temp.name) / "PRIVATE_SAMPLE_NEVER_SEND.png"
        info = PngImagePlugin.PngInfo()
        info.add_text("private", "PRIVATE_METADATA_NEVER_SEND")
        Image.new("RGB", (64, 48), (100, 200, 50)).save(self.image, pnginfo=info)
        self.messages, self.queries = [], []

    def pipeline(self, outputs):
        outputs = list(outputs)
        def chat(messages):
            self.messages.append(deepcopy(messages))
            if not outputs:
                raise AssertionError("unexpected request")
            item = outputs.pop(0)
            if isinstance(item, BaseException):
                raise item
            return item if isinstance(item, str) else json.dumps(item)
        def embed(texts):
            self.queries.append(deepcopy(texts))
            return [[1., 0.] for _ in texts]
        return SharedAccountingPipeline(chat, embed, deepcopy(CATALOG),
            Retriever(C, np.array([[1., 0.], [0., 1.], [.8, .2], [.2, .8]]), CATALOG))

    def saved_layout(self, pipeline):
        return pipeline.layout(self.image)

    def core(self, collapse=True, outputs=()):
        data = layout()
        data.pop("status")
        pipeline = self.pipeline([data, choice(collapse), *outputs])
        initial = self.saved_layout(pipeline)
        identity = pipeline.identify_candidate(self.image, initial, CHILD)
        return pipeline, initial, identity

    def test_single_query_rrf_and_code_tie(self):
        self.assertEqual(fuse_whole_rankings([C[1], C[0]], [C[0], C[1]]), C[:2])
        dense = [f"{i:08d}" for i in range(1, 13)]
        lexical = [f"{i:08d}" for i in range(13, 25)]
        self.assertEqual(len(fuse_whole_rankings(dense, lexical)), 24)

    def test_rrf_rejects_invalid_empty_or_duplicate_rankings(self):
        for a, b in [([], []), ([C[0], C[0]], []), ([{}], []), ([C[0]] * 13, []), ((), [])]:
            with self.subTest(a=a), self.assertRaises(ContractError):
                fuse_whole_rankings(a, b)

    def test_whole_has_distinct_entity_and_preserves_ownership(self):
        before = layout()
        result = parse_joint_choice(json.dumps(choice()), before, CHILD, WHOLE)
        self.assertEqual(before, layout())
        self.assertEqual(len(result["leaves"]), 2)
        self.assertEqual(result["parents"][0]["region_ids"], ["r1"])
        self.assertEqual(result["parents"][0]["bbox"], before["parents"][0]["bbox"])
        self.assertEqual(result["entities"][0]["entity_id"], "p1:whole")
        self.assertEqual(result["entities"][0]["replaced_child_ids"], ["p1c1", "p1c2"])
        self.assertEqual(result["candidates"]["p1c1"], [C[2]])
        self.assertEqual(result["leaves"][0]["description"], "chicken rice dish")
        self.assertNotIn("grams", result["leaves"][0])

    def test_keep_requires_every_original_child_once(self):
        result = parse_joint_choice(json.dumps(choice(False)), layout(), CHILD, WHOLE)
        self.assertEqual(len(result["leaves"]), 3)
        self.assertEqual(result["parents"], layout()["parents"])
        self.assertEqual([e["entity_id"] for e in result["entities"]], ["p1c1", "p1c2", "p2c1"])

    def test_invalid_routes_banks_codes_and_model_geometry_rejected(self):
        bad = []
        a = choice(); a["parents"][0]["children"] = [{"component_id": "p1c1", "code": C[0]}]; bad.append(a)
        a = choice(); a["parents"][1].update(route="whole", whole_code=C[3], children=[]); bad.append(a)
        a = choice(False); a["parents"][0]["children"].pop(); bad.append(a)
        a = choice(False); a["parents"][0]["children"][1] = deepcopy(a["parents"][0]["children"][0]); bad.append(a)
        a = choice(); a["parents"][0]["whole_code"] = C[0]; bad.append(a)
        a = choice(False); a["parents"][0]["children"][0]["code"] = C[2]; bad.append(a)
        a = choice(); a["parents"][0]["bbox"] = [0, 0, 1, 1]; bad.append(a)
        a = choice(); a["parents"].pop(); bad.append(a)
        a = choice(); a["parents"][1]["parent_id"] = "p1"; bad.append(a)
        a = choice(False); a["parents"][0]["whole_code"] = C[2]; bad.append(a)
        for item in bad:
            with self.subTest(item=item), self.assertRaises(ContractError):
                parse_joint_choice(json.dumps(item), layout(), CHILD, WHOLE)
        for child, whole in [({}, WHOLE), (CHILD, {}), (CHILD, {"p2": [C[3]]}),
                             ({**CHILD, "p1c1": [C[0], C[0]]}, WHOLE)]:
            with self.subTest(child=child), self.assertRaises(ContractError):
                parse_joint_choice(json.dumps(choice()), layout(), child, whole)

    def test_catalog_is_deduplicated_and_category_projection_unchanged(self):
        pipeline = self.pipeline([])
        children = {key: C[:] for key in CHILD}
        context = build_joint_context(layout(), children, {"p1": C[:]}, pipeline._candidates)
        self.assertEqual([row["code"] for row in context["catalog"]], C)
        self.assertTrue(all("category" not in row for row in context["catalog"]))
        self.assertTrue(all("relationship_hints" in row for row in context["catalog"]))
        self.assertEqual(context["catalog"][2]["relationship_hints"]["accounting_hint"], "likely_composite")

    def test_m_retrieves_parent_description_once_and_new_portion(self):
        mass = {"total_grams": 300, "parents": [
            {"parent_id": "p1", "ratio": 2, "components": [{"component_id": "p1c1", "ratio": 1}]},
            {"parent_id": "p2", "ratio": 1, "components": [{"component_id": "p2c1", "ratio": 1}]}]}
        pipeline, initial, identity = self.core(outputs=[mass])
        self.assertEqual(self.queries, [["chicken rice dish"]])
        self.assertEqual(identity["status"], "ok")
        snapshot = deepcopy(identity["coding"])
        result = pipeline.portion_candidate(self.image, identity)
        self.assertEqual(result["prediction"]["weight"], 300)
        self.assertEqual([p["grams"] for p in result["portions"]], [200, 100])
        self.assertEqual(result["prediction"]["energy"], 200 * 1.2 + 100 * 1.3)
        self.assertEqual(identity["coding"], snapshot)
        self.assertEqual(len(self.messages), 3)
        text = json.dumps(self.messages)
        for secret in [self.image.name, "PRIVATE_METADATA_NEVER_SEND", "asa_options", "sample_id", "dataset"]:
            self.assertNotIn(secret, text)
        self.assertIn("Estimate total plate grams", text)

    def test_quantity_failure_preserves_coding(self):
        pipeline, initial, identity = self.core(outputs=["{}", "{}"])
        before = deepcopy(identity)
        result = pipeline.portion_candidate(self.image, identity)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["failure"], "portion_contract")
        self.assertEqual(identity, before)
        self.assertEqual(identity["coding"]["final_codes"], [C[2], C[3]])
        self.assertEqual(len(self.messages), 4)

    def test_joint_contract_has_one_format_repair(self):
        data = layout(); data.pop("status")
        pipeline = self.pipeline([data, "{}", choice()])
        initial = pipeline.layout(self.image)
        identity = pipeline.identify_candidate(self.image, initial, CHILD)
        self.assertTrue(identity["repaired"])
        self.assertIn("FORMAT only", self.messages[-1][-1]["content"])
        self.assertEqual(len(self.messages), 3)

    def test_joint_failure_does_not_invent_identity(self):
        data = layout(); data.pop("status")
        pipeline = self.pipeline([data, "{}", "{}"])
        identity = pipeline.identify_candidate(self.image, pipeline.layout(self.image), CHILD)
        self.assertEqual(identity["status"], "failed")
        self.assertEqual(coding_snapshot(identity)["final_codes"], [])
        self.assertEqual(identity["leaves"], [])

    def test_invalid_layout_requires_no_retrieval_or_new_request(self):
        pipeline = self.pipeline([])
        failed = {"status": "failed", "failure": "incomplete_visible_coverage", "stages": []}
        result = pipeline.identify_candidate(self.image, failed, {})
        self.assertEqual(result["failure"], failed["failure"])
        self.assertEqual(self.messages, [])
        self.assertEqual(self.queries, [])

    def test_changed_image_and_identity_integrity_stop_before_portion(self):
        pipeline, initial, identity = self.core()
        variants = []
        for key in ["parents", "leaves", "entities", "coding", "child_banks"]:
            a = deepcopy(identity)
            if key == "parents": a[key][0]["bbox"][2] = .6
            elif key == "leaves": a[key][0]["grams"] = 1
            elif key == "entities": a[key][0]["entity_id"] = "p1c1"
            elif key == "coding": a[key]["final_codes"] = []
            else: a[key]["p1c1"] = [C[1]]
            variants.append(a)
        for item in variants:
            with self.subTest(item=item), self.assertRaises(ContractError):
                pipeline.portion_candidate(self.image, item)
        self.assertEqual(len(self.messages), 2)
        Image.new("RGB", (64, 48)).save(self.image)
        with self.assertRaisesRegex(ContractError, "layout_image_mismatch"):
            pipeline.identify_candidate(self.image, initial, CHILD)

    def test_baseline_inherits_original_identity_and_quantity_without_override(self):
        self.assertIs(SharedAccountingPipeline.identify, ComponentPipeline.identify)
        self.assertIs(SharedAccountingPipeline.portion, ComponentPipeline.portion)
        self.assertEqual(IDENTITY_CONFIG["portion_mode"], "direct")
        self.assertEqual(QUANTITY_CONFIG["portion_mode"], "total_ratio")

    def test_codes_rank_by_geometry_then_stable_final_id_and_deduplicate(self):
        parsed = parse_joint_choice(json.dumps(choice(False)), layout(), CHILD, WHOLE)
        parsed["status"] = "ok"
        parsed["leaves"] = list(reversed(parsed["leaves"]))
        snapshot = coding_snapshot(parsed)
        self.assertEqual(snapshot["ordered_codes"], [C[0], C[1], C[3]])
        self.assertEqual(snapshot["ranked_leaf_ids"], ["p1c1", "p1c2", "p2c1"])
        parsed["leaves"][0]["primary_code"] = C[0]
        self.assertEqual(coding_snapshot(parsed)["final_codes"], C[:2])
        parsed["parents"][0]["bbox"][2] = .1
        self.assertEqual(coding_snapshot(parsed)["ranked_leaf_ids"][0], "p2c1")

    def test_provider_failures_are_not_food_prediction_fallbacks(self):
        data = layout(); data.pop("status")
        pipeline = self.pipeline([data, RuntimeError("synthetic service stop")])
        initial = pipeline.layout(self.image)
        with self.assertRaisesRegex(RuntimeError, "synthetic service stop"):
            pipeline.identify_candidate(self.image, initial, CHILD)

    def test_invalid_child_bank_stops_before_paid_embedding_or_chat(self):
        data = layout(); data.pop("status")
        pipeline = self.pipeline([data])
        initial = pipeline.layout(self.image)
        with self.assertRaisesRegex(ContractError, "branch_bank_keys_mismatch"):
            pipeline.identify_candidate(self.image, initial, {})
        self.assertEqual(self.queries, [])
        self.assertEqual(len(self.messages), 1)

    def test_three_code_limit_does_not_delete_whole_serving_leaves(self):
        data = layout()
        data["parents"][0]["components"].append({"component_id": "p1c3", "description": "beans",
                                                 "broad_query": "cooked beans"})
        child = {**CHILD, "p1c3": [C[2]]}
        selected = choice(False)
        selected["parents"][0]["children"].append({"component_id": "p1c3", "code": C[2]})
        identity = {"status": "ok", **parse_joint_choice(json.dumps(selected), data, child, WHOLE)}
        snapshot = coding_snapshot(identity)
        self.assertEqual(snapshot["ordered_codes"], C)
        self.assertEqual(snapshot["final_codes"], C[:3])
        self.assertEqual(snapshot["primary_code"], C[0])
        self.assertEqual(len(identity["leaves"]), 4)

    def test_no_collapse_opportunity_still_gets_new_joint_selection(self):
        data = layout(); data.pop("status")
        data["parents"][0]["accounting"] = "composite"
        data["parents"][0]["components"] = data["parents"][0]["components"][:1]
        selected = choice(False)
        selected["parents"][0]["children"] = selected["parents"][0]["children"][:1]
        pipeline = self.pipeline([data, selected])
        identity = pipeline.identify_candidate(self.image, pipeline.layout(self.image),
                                               {key: value for key, value in CHILD.items() if key != "p1c2"})
        self.assertEqual(identity["status"], "ok")
        self.assertEqual(identity["whole_banks"], {})
        self.assertEqual(len(self.messages), 2)
        self.assertEqual(self.queries, [])


if __name__ == "__main__":
    unittest.main()
