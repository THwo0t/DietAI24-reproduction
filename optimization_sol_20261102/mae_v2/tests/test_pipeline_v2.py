"""Offline contract, accounting and bounded-request tests; no dataset files."""
import base64
from copy import deepcopy
from io import BytesIO
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image, PngImagePlugin

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from opt_pipeline import ContractError, Retriever
from pipeline_v2 import ComponentPipeline, _parse_layout, relation_hints

CODES = ["11111111", "22222222", "33333333", "44444444"]
CATALOG = {"foods": {
    CODES[0]: {"description": "chicken, cooked", "category": "Chicken", "density":
              {"energy": 200, "fat": 10, "carbs": 0, "protein": 25}},
    CODES[1]: {"description": "rice, cooked", "category": "Rice", "density":
              {"energy": 130, "fat": 1, "carbs": 28, "protein": 2.5}},
    CODES[2]: {"description": "rice with chicken", "category": "Mixed dishes", "density":
              {"energy": 150, "fat": 3, "carbs": 23, "protein": 8}},
    CODES[3]: {"description": "broccoli cooked", "category": "Vegetables", "density":
              {"energy": 35, "fat": .5, "carbs": 7, "protein": 3}},
}, "standard_options": {
    CODES[0]: [{"option_id": "half", "description": "1/2 cup, diced", "grams": 80},
               {"option_id": "serving", "description": "1 serving", "grams": 120},
               {"option_id": "quantity", "description": "Quantity not specified", "grams": 10},
               {"option_id": "guideline", "description": "Guideline amount", "grams": 100},
               {"option_id": "gram", "description": "1 g", "grams": 1}],
    CODES[3]: [{"option_id": "cup", "description": "1 cup chopped", "grams": 90}],
}, "standard_option_sources": {
    CODES[0]: {"half": [{"Food Code": CODES[0], "Portion Code": "101", "Subcode": "0"}]},
    CODES[3]: {"cup": [{"Food Code": CODES[3], "Portion Code": "102", "Subcode": "0"}]},
}, "standard_portion_source_sha256": "f" * 64}


def layout_data():
    return {"coverage_complete": True, "parents": [
        {"parent_id": "p1", "description": "chicken and rice", "bbox": [0, 0, .5, 1],
         "region_ids": ["r1"], "accounting": "components", "components": [
             {"component_id": "p1c1", "description": "cooked chicken", "broad_query": "chicken"},
             {"component_id": "p1c2", "description": "cooked rice", "broad_query": "rice"}]},
        {"parent_id": "p2", "description": "broccoli", "bbox": [.5, 0, 1, 1],
         "region_ids": ["r2"], "accounting": "composite", "components": [
             {"component_id": "p2c1", "description": "cooked broccoli", "broad_query": "vegetables"}]}]}


def selection(wrong=False):
    return {"items": [{"component_id": "p1c1", "primary_code": CODES[2] if wrong else CODES[0]},
                      {"component_id": "p1c2", "primary_code": CODES[1]},
                      {"component_id": "p2c1", "primary_code": CODES[3]}]}


def direct_masses():
    return {"parents": [
        {"parent_id": "p1", "grams": 100, "components": [
            {"component_id": "p1c1", "ratio": 1}, {"component_id": "p1c2", "ratio": 3}]},
        {"parent_id": "p2", "grams": 50, "components": [{"component_id": "p2c1", "ratio": 1}]}]}


def code_review(first=None):
    rows = [{**row, "action": "select", "query": None, "broad_query": None}
            for row in selection()["items"]]
    if first is not None:
        rows[0] = first
    return {"items": rows}


class Chat:
    def __init__(self, outputs):
        self.outputs = list(outputs)
        self.messages = []

    def __call__(self, messages):
        self.messages.append(deepcopy(messages))
        if not self.outputs:
            raise AssertionError("Unexpected additional model request")
        value = self.outputs.pop(0)
        if isinstance(value, BaseException):
            raise value
        return value if isinstance(value, str) else json.dumps(value)


class PipelineV2Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.image = Path(self.temp.name) / "SECRET_SAMPLE_ID_NEVER_SEND.png"
        metadata = PngImagePlugin.PngInfo()
        metadata.add_text("sensitive", "DO_NOT_FORWARD")
        Image.new("RGB", (640, 480), (200, 40, 30)).save(self.image, pnginfo=metadata)
        self.embed_calls = []

    def pipeline(self, outputs, catalog=None):
        catalog = deepcopy(catalog or CATALOG)
        self.chat = Chat(outputs)
        def embed(texts):
            self.embed_calls.append(list(texts))
            return [[1, 0] for _ in texts]
        return ComponentPipeline(self.chat, embed, catalog,
            Retriever(CODES, np.asarray([[1, 0], [0, 1], [.8, .2], [.2, .8]]), catalog))

    def identified(self, wrong=False):
        pipeline = self.pipeline([layout_data(), selection(wrong), direct_masses()])
        identity = pipeline.identify(self.image, {})
        portion = pipeline.portion(self.image, identity, {})
        return pipeline, identity, portion

    def test_direct_mass_is_conserved_and_parent_never_double_counted(self):
        pipeline, identity, result = self.identified()
        self.assertEqual(result["status"], "ok")
        self.assertEqual([p["grams"] for p in result["portions"]], [25, 75, 50])
        self.assertEqual(result["prediction"]["weight"], 150)
        self.assertAlmostEqual(result["prediction"]["energy"], 25 * 2 + 75 * 1.3 + 50 * .35)
        self.assertEqual(sum(p["grams"] for p in result["parents"]), 150)
        self.assertEqual(result["raw_prediction"], result["prediction"])
        self.assertEqual(result["raw_leaves"], result["portions"])
        result["portions"][0]["grams"] = 999
        self.assertEqual(result["raw_leaves"][0]["grams"], 25)
        self.assertEqual(len(self.chat.messages), 3)
        self.assertEqual(len(identity["leaves"]), 3)

    def test_total_ratio_preserves_both_levels_of_mass(self):
        pipeline, identity, _ = self.identified()
        self.chat.outputs.append({"total_grams": 300, "parents": [
            {"parent_id": "p1", "ratio": 2, "components": [
                {"component_id": "p1c1", "ratio": 1e308}, {"component_id": "p1c2", "ratio": 1e308}]},
            {"parent_id": "p2", "ratio": 1, "components": [{"component_id": "p2c1", "ratio": 1}]}]})
        result = pipeline.portion(self.image, identity, {"portion_mode": "total_ratio"})
        self.assertEqual([p["grams"] for p in result["portions"]], [100, 100, 100])
        self.assertEqual(result["prediction"]["weight"], 300)
        self.assertEqual([p["grams"] for p in result["parents"]], [200, 100])

    def test_missing_mass_is_failure_not_zero_or_partial_prediction(self):
        pipeline, identity, _ = self.identified()
        bad = direct_masses()
        bad["parents"][0]["components"].pop()
        self.chat.outputs += [bad, bad]
        before = len(self.chat.messages)
        result = pipeline.portion(self.image, identity, {})
        self.assertEqual(result["status"], "failed")
        self.assertIsNone(result["prediction"])
        self.assertEqual(result["portions"], [])
        self.assertEqual(len(self.chat.messages) - before, 2)
        self.assertIn("FORMAT only", self.chat.messages[-1][-1]["content"])

    def test_layout_rejects_duplicate_regions_and_duplicate_or_extra_accounting(self):
        changes = []
        a = layout_data(); a["parents"][1]["region_ids"] = ["r1"]; changes.append(a)
        a = layout_data(); a["parents"][0]["accounting"] = "composite"; changes.append(a)
        a = layout_data(); a["parents"][0]["components"][1]["component_id"] = "p1c1"; changes.append(a)
        a = layout_data(); a["parents"][0]["bbox"] = [0, 0, 2, 1]; changes.append(a)
        a = layout_data(); a["parents"][0]["accounting"] = []; changes.append(a)
        a = layout_data(); a["reference_weight"] = 123; changes.append(a)
        for data in changes:
            with self.subTest(data=data), self.assertRaises(ContractError):
                _parse_layout(json.dumps(data))

    def test_incomplete_layout_stops_without_accuracy_retry(self):
        pipeline = self.pipeline([{"coverage_complete": False, "parents": []}])
        result = pipeline.identify(self.image, {})
        self.assertEqual(result["failure"], "incomplete_visible_coverage")
        self.assertEqual(len(self.chat.messages), 1)
        self.assertEqual(self.embed_calls, [])

    def test_limits_twenty_leaves_and_twelve_query_batches(self):
        data = {"coverage_complete": True, "parents": []}
        selected = {"items": []}
        for i in range(4):
            pid = f"p{i + 1}"
            children = [{"component_id": f"{pid}c{j + 1}", "description": f"visible food {i} {j}",
                         "broad_query": f"food category {i} {j}"} for j in range(5)]
            data["parents"].append({"parent_id": pid, "description": f"dish {i}", "bbox": [0, 0, 1, 1],
                "region_ids": [f"r{i + 1}"], "accounting": "components", "components": children})
            selected["items"] += [{"component_id": c["component_id"], "primary_code": CODES[0]} for c in children]
        pipeline = self.pipeline([data, selected])
        result = pipeline.identify(self.image, {})
        self.assertEqual(len(result["leaves"]), 20)
        self.assertEqual([len(c) for c in self.embed_calls], [12, 12, 12, 4])
        data["parents"][0]["components"].append({"component_id": "p1c6", "description": "extra food", "broad_query": "extra"})
        with self.assertRaisesRegex(ContractError, "too_many_leaves"):
            _parse_layout(json.dumps(data))

    def test_crop_review_reuses_original_layout_and_never_sends_source_metadata(self):
        pipeline = self.pipeline([layout_data(), layout_data(), selection()])
        saved = pipeline.layout(self.image)
        original = deepcopy(saved)
        result = pipeline.identify(self.image, {"crop_review": True}, layout=saved)
        self.assertEqual(saved, original)
        self.assertEqual(result["layout_result"], original)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(len(self.chat.messages), 3)
        blocks = self.chat.messages[1][1]["content"]
        images = [b["image_url"]["url"] for b in blocks if b["type"] == "image_url"]
        self.assertEqual(len(images), 3)
        self.assertEqual(result["crops"][0]["crop_id"], "crop_p1")
        self.assertEqual(result["crops"][0]["pixel_bounds"], [0, 0, 352, 480])
        self.assertEqual(result["crops"][0]["size"], [352, 480])
        for url in images:
            with Image.open(BytesIO(base64.b64decode(url.split(",")[1]))) as image:
                self.assertEqual(image.info, {})
                self.assertLessEqual(max(image.size), 1024)
        sent = json.dumps(self.chat.messages)
        self.assertNotIn(self.image.name, sent)
        self.assertNotIn("DO_NOT_FORWARD", sent)
        self.assertNotIn("data:image", json.dumps(result))

    def test_crop_review_cannot_change_parent_ownership(self):
        bad = layout_data()
        bad["parents"][0]["bbox"] = [0, 0, .7, 1]
        pipeline = self.pipeline([layout_data(), bad, bad])
        saved = pipeline.layout(self.image)
        result = pipeline.identify(self.image, {"crop_review": True}, layout=saved)
        self.assertEqual(result["failure"], "crop_review_contract")
        self.assertEqual(self.embed_calls, [])

    def test_crop_cap_and_native_maximum_do_not_upscale(self):
        pipeline = self.pipeline([])
        Image.new("RGB", (2400, 1200)).save(self.image)
        parents = [{"parent_id": f"p{i + 1}", "description": "food", "accounting": "composite",
                    "components": [{"description": "food"}], "bbox": [i / 8, 0, (i + 1) / 8, 1]}
                   for i in range(8)]
        images, crops = pipeline._images_and_crops(self.image, parents)
        self.assertEqual(len(images), 5)
        self.assertEqual(len(crops), 4)
        with Image.open(BytesIO(base64.b64decode(images[0].split(",")[1]))) as image:
            self.assertEqual(image.size, (1024, 512))
        self.assertTrue(all(max(crop["size"]) <= 1024 for crop in crops))
        again = pipeline._images_and_crops(self.image, parents)
        self.assertEqual((images, crops), again)

    def test_five_parent_crop_membership_ignores_protein_sauce_and_area(self):
        """R-M2-3-1: each old extra criterion promoted p5 and excluded p4."""
        pipeline = self.pipeline([])
        for extra_priority in ("protein", "sauce", "area"):
            parents = [{"parent_id": f"p{i + 1}", "description": "food", "accounting": "composite",
                        "components": [{"description": "food"}],
                        "bbox": [i / 8, 0, (i + 1) / 8, 1 / 8]} for i in range(5)]
            if extra_priority == "protein":
                parents[4]["description"] = "chicken"
            elif extra_priority == "sauce":
                parents[4]["description"] = "tomato sauce with dressing"
            else:
                parents[4]["bbox"] = [.5, .25, 1, .75]
            with self.subTest(removed_criterion=extra_priority):
                original = deepcopy(parents)
                images, crops = pipeline._images_and_crops(self.image, list(reversed(parents)))
                self.assertEqual([crop["parent_id"] for crop in crops], ["p1", "p2", "p3", "p4"])
                self.assertEqual({crop["parent_id"] for crop in crops}, {"p1", "p2", "p3", "p4"})
                self.assertEqual(len(images), 5)
                self.assertEqual(parents, original)
        self.assertEqual(self.chat.messages, [])
        self.assertEqual(self.embed_calls, [])

    def test_crop_priority_uses_exclusive_tiers_then_only_parent_id(self):
        pipeline = self.pipeline([])
        descriptions = ["chicken with sauce", "rice and beans", "uncertain vegetables",
                        "possibly rice and vegetables", "mixed chicken and rice", "vegetables"]
        parents = [{"parent_id": f"p{i + 1}", "description": description,
                    "accounting": "components" if i in (1, 3, 4) else "composite",
                    "components": [{"description": "food"}],
                    "bbox": [i / 8, 0, (i + 1) / 8, 1 / 8]}
                   for i, description in enumerate(descriptions)]
        # p3 and p4 are both uncertain: mixed accounting must not move p4 first.
        ordered = sorted(reversed(parents), key=pipeline._crop_priority)
        self.assertEqual([p["parent_id"] for p in ordered], ["p3", "p4", "p2", "p5", "p1", "p6"])
        _, crops = pipeline._images_and_crops(self.image, parents)
        self.assertEqual([c["parent_id"] for c in crops], ["p3", "p4", "p2", "p5"])

    def test_c_using_a_identity_never_calls_crop_selection(self):
        total = {"total_grams": 300, "parents": [
            {"parent_id": "p1", "ratio": 2, "components": [
                {"component_id": "p1c1", "ratio": 1}, {"component_id": "p1c2", "ratio": 3}]},
            {"parent_id": "p2", "ratio": 1, "components": [{"component_id": "p2c1", "ratio": 1}]}]}
        pipeline = self.pipeline([layout_data(), selection(), total])
        with patch.object(pipeline, "_images_and_crops", side_effect=AssertionError("Unexpected crop path")) as crops:
            identity = pipeline.identify(self.image, {"crop_review": False})
            result = pipeline.portion(self.image, identity, {"crop_review": False, "portion_mode": "total_ratio"})
        crops.assert_not_called()
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["prediction"]["weight"], 300)
        self.assertEqual([row["grams"] for row in result["portions"]], [50, 150, 100])

    def test_layout_cache_rejects_different_image(self):
        pipeline = self.pipeline([layout_data()])
        saved = pipeline.layout(self.image)
        Image.new("RGB", (100, 100)).save(self.image)
        with self.assertRaisesRegex(ContractError, "layout_image_mismatch"):
            pipeline.identify(self.image, {}, layout=saved)

    def test_candidate_selection_is_bounded_and_density_is_catalogue_only(self):
        bad = selection(); bad["items"][0]["primary_code"] = "99999999"
        pipeline = self.pipeline([layout_data(), bad, selection()])
        result = pipeline.identify(self.image, {})
        self.assertTrue(result["repaired"])
        text = self.chat.messages[1][1]["content"][0]["text"]
        self.assertIn("density_per_100g", text)
        self.assertIn("inferred_not_verified", text)
        with self.assertRaises(ContractError):
            pipeline.identify(self.image, {"candidate_cap": 64})

    def test_semantic_review_changes_only_code_and_density(self):
        pipeline, identity, base = self.identified(wrong=True)
        original_identity, original_base = deepcopy(identity), deepcopy(base)
        self.chat.outputs.append(code_review())
        updated, result = pipeline.review_codes(self.image, identity, base, {})
        self.assertEqual(identity, original_identity)
        self.assertEqual(base, original_base)
        self.assertEqual(updated["parents"], identity["parents"])
        self.assertEqual([r["grams"] for r in result["portions"]], [25, 75, 50])
        self.assertEqual(result["prediction"]["weight"], base["prediction"]["weight"])
        self.assertGreater(result["prediction"]["protein"], base["prediction"]["protein"])
        self.assertEqual(result["changed_codes"][0]["new_code"], CODES[0])

    def test_semantic_review_one_fresh_retrieval_replaces_candidates(self):
        pipeline, identity, base = self.identified(wrong=True)
        self.chat.outputs += [code_review({"component_id": "p1c1", "action": "retrieve", "primary_code": None,
                                          "query": "cooked chicken", "broad_query": "poultry"}),
                              {"items": [{"component_id": "p1c1", "primary_code": CODES[0]}]}]
        before_chat, before_embeddings = len(self.chat.messages), len(self.embed_calls)
        with patch.object(pipeline.retriever, "hybrid", return_value=[CODES[0]]) as hybrid:
            updated, result = pipeline.review_codes(self.image, identity, base, {})
        self.assertEqual(len(self.chat.messages) - before_chat, 2)
        self.assertEqual(len(self.embed_calls) - before_embeddings, 1)
        self.assertEqual(len(self.embed_calls[-1]), 2)
        self.assertEqual(hybrid.call_count, 1)
        self.assertEqual(updated["candidates"]["p1c1"], [CODES[0]])
        self.assertFalse(result["method_fallback"])
        names = [stage["stage"] for stage in result["stages"]]
        self.assertEqual(names[-3:], ["semantic_review", "semantic_retrieval_once", "semantic_final_select"])

    def test_semantic_review_final_failure_restores_entire_base(self):
        pipeline, identity, base = self.identified(wrong=True)
        self.chat.outputs += [code_review({"component_id": "p1c1", "action": "retrieve", "primary_code": None,
                                          "query": "chicken", "broad_query": "poultry"}),
                              {"items": []}, {"items": []}]
        updated, result = pipeline.review_codes(self.image, identity, base, {})
        self.assertEqual(updated, identity)
        self.assertEqual(result["prediction"], base["prediction"])
        self.assertEqual(result["portions"], base["portions"])
        self.assertTrue(result["method_fallback"])
        self.assertEqual(result["method_fallback_reason"], "final_selection_contract")

    def test_no_conflict_still_reviews_all_leaves_once_and_can_keep_codes(self):
        pipeline, identity, base = self.identified()
        self.chat.outputs.append(code_review())
        before = len(self.chat.messages)
        updated, result = pipeline.review_codes(self.image, identity, base, {})
        self.assertEqual(len(self.chat.messages), before + 1)
        self.assertEqual(result["semantic_conflicts"], [])
        self.assertEqual(result["changed_codes"], [])
        self.assertFalse(result["method_fallback"])
        self.assertEqual(result["prediction"], base["prediction"])
        self.assertEqual(updated["leaves"], identity["leaves"])
        text = self.chat.messages[-1][1]["content"][0]["text"]
        for leaf in identity["leaves"]:
            self.assertIn(leaf["component_id"], text)
        self.assertIn("Review EVERY selected food code", text)

    def test_review_omitting_unflagged_leaf_is_invalid(self):
        pipeline, identity, base = self.identified(wrong=True)
        partial = code_review()
        partial["items"].pop()
        self.chat.outputs += [partial, partial]
        _, result = pipeline.review_codes(self.image, identity, base, {})
        self.assertEqual(result["method_fallback_reason"], "review_contract")
        self.assertEqual(result["prediction"], base["prediction"])

    def test_atomic_single_leaf_can_still_conflict_with_whole_dish_code(self):
        pipeline = self.pipeline([])
        identity = {"leaves": [{"component_id": "p1c1", "description": "cooked chicken", "accounting": "composite",
                                "primary_code": CODES[2]}]}
        self.assertIn("ingredient_selected_as_composite", pipeline.semantic_conflicts(identity)[0]["reasons"])
        identity["leaves"][0]["description"] = "rice with chicken"
        self.assertEqual(pipeline.semantic_conflicts(identity), [])

    def test_malformed_semantic_action_is_bounded_format_failure(self):
        pipeline, identity, base = self.identified(wrong=True)
        malformed = code_review({"component_id": "p1c1", "action": [], "primary_code": None,
                                "query": None, "broad_query": None})
        self.chat.outputs += [malformed, malformed]
        before = len(self.chat.messages)
        unchanged, result = pipeline.review_codes(self.image, identity, base, {})
        self.assertEqual(len(self.chat.messages) - before, 2)
        self.assertEqual(unchanged, identity)
        self.assertEqual(result["prediction"], base["prediction"])
        self.assertEqual(result["method_fallback_reason"], "review_contract")

    def test_standard_units_use_complete_fractional_description_and_keep_missing_leaf(self):
        pipeline, identity, base = self.identified()
        self.chat.outputs.append({"items": [{"component_id": "p1c1", "option_id": "half", "count": 3},
                                             {"component_id": "p2c1", "option_id": "cup", "count": .5}]})
        result = pipeline.standard_portions(self.image, identity, base, {})
        self.assertEqual([r["grams"] for r in result["portions"]], [240, 75, 45])
        self.assertEqual(result["prediction"]["weight"], 360)
        self.assertEqual(result["parents"][0]["grams"], 315)
        self.assertEqual(result["catalog_retained_leaf_ids"], ["p1c2"])
        self.assertEqual([o["option_id"] for o in pipeline.usable_standard_options(CODES[0])], ["half"])
        self.assertEqual(base["prediction"]["weight"], 150)
        text = self.chat.messages[-1][1]["content"][0]["text"]
        self.assertNotIn("LabelUnit", text)
        self.assertNotIn("1 serving", text)
        self.assertEqual(result["standard_portion_source_sha256"], "f" * 64)
        self.assertEqual(result["option_choices"][0]["source_refs"],
                         CATALOG["standard_option_sources"][CODES[0]]["half"])
        self.assertEqual(result["option_choices"][0]["source_sha256"], "f" * 64)
        self.assertNotIn("source_refs", text)
        self.assertNotIn("Subcode", text)
        self.assertNotIn("Portion Code", text)
        self.assertNotIn("f" * 64, text)
        result["option_choices"][0]["source_refs"][0]["Subcode"] = "999"
        self.assertEqual(pipeline.catalog["standard_option_sources"][CODES[0]]["half"][0]["Subcode"], "0")

    def test_standard_failure_never_partially_replaces_mass(self):
        pipeline, identity, base = self.identified()
        invalid = {"items": [{"component_id": "p1c1", "option_id": "half", "count": 3},
                             {"component_id": "p2c1", "option_id": "made-up", "count": 1}]}
        self.chat.outputs += [invalid, invalid]
        result = pipeline.standard_portions(self.image, identity, base, {})
        self.assertTrue(result["method_fallback"])
        self.assertEqual(result["prediction"], base["prediction"])
        self.assertEqual(result["portions"], base["portions"])
        self.assertEqual(result["option_choices"], [])

    def test_standard_zero_count_cannot_remove_a_component(self):
        pipeline, identity, base = self.identified()
        invalid = {"items": [{"component_id": "p1c1", "option_id": "half", "count": 0},
                             {"component_id": "p2c1", "option_id": "cup", "count": 1}]}
        self.chat.outputs += [invalid, invalid]
        before = len(self.chat.messages)
        result = pipeline.standard_portions(self.image, identity, base, {})
        self.assertEqual(len(self.chat.messages) - before, 2)
        self.assertTrue(result["method_fallback"])
        self.assertEqual(result["portions"], base["portions"])

    def test_synthetic_catalogue_without_source_refs_keeps_empty_audit_list(self):
        pipeline, identity, base = self.identified()
        pipeline.catalog.pop("standard_option_sources")
        pipeline.catalog.pop("standard_portion_source_sha256")
        self.chat.outputs.append({"items": [{"component_id": "p1c1", "option_id": "half", "count": 1},
                                             {"component_id": "p2c1", "option_id": "cup", "count": 1}]})
        result = pipeline.standard_portions(self.image, identity, base, {})
        self.assertEqual([row["source_refs"] for row in result["option_choices"]], [[], []])
        self.assertIsNone(result["standard_portion_source_sha256"])

    def test_no_standard_catalogue_reuses_base_without_call(self):
        pipeline, identity, base = self.identified()
        pipeline.catalog["standard_options"] = {}
        before = len(self.chat.messages)
        result = pipeline.standard_portions(self.image, identity, base, {})
        self.assertEqual(len(self.chat.messages), before)
        self.assertEqual(result["prediction"], base["prediction"])
        self.assertEqual(result["method_fallback_reason"], "no_usable_standard_portion")

    def test_second_round_composition_is_rejected(self):
        pipeline, identity, base = self.identified()
        for method in ("semantic_review", "standard_portions"):
            modified = {**base, "method": method}
            with self.assertRaisesRegex(ContractError, "composition_forbidden"):
                pipeline.review_codes(self.image, identity, modified, {})
            with self.assertRaisesRegex(ContractError, "composition_forbidden"):
                pipeline.standard_portions(self.image, identity, modified, {})

    def test_nonfinite_negative_and_zero_ratio_outputs_fail(self):
        for value in (0, -1, float("inf"), True):
            bad = direct_masses(); bad["parents"][0]["grams"] = value
            with self.subTest(value=value), self.assertRaises(ContractError):
                ComponentPipeline._parse_masses(json.dumps(bad), layout_data()["parents"], "direct")
        bad = direct_masses()
        for row in bad["parents"][0]["components"]:
            row["ratio"] = 0
        with self.assertRaisesRegex(ContractError, "nonpositive_mass_or_ratio"):
            ComponentPipeline._parse_masses(json.dumps(bad), layout_data()["parents"], "direct")

    def test_zero_leaf_or_normalization_underflow_is_rejected(self):
        for ratio in (0, 5e-324):
            bad = direct_masses()
            bad["parents"][0]["components"][0]["ratio"] = ratio
            bad["parents"][0]["components"][1]["ratio"] = 1e308
            with self.subTest(ratio=ratio), self.assertRaisesRegex(ContractError, "nonpositive_mass_or_ratio"):
                ComponentPipeline._parse_masses(json.dumps(bad), layout_data()["parents"], "direct")
        pipeline, identity, _ = self.identified()
        with self.assertRaisesRegex(ContractError, "nonpositive_mass_or_ratio"):
            pipeline._aggregate(identity, {"p1c1": 0, "p1c2": 75, "p2c1": 50}, [])

    def test_total_or_parent_ratio_zero_cannot_erase_a_parent(self):
        raw = {"total_grams": 300, "parents": [
            {"parent_id": "p1", "ratio": 2, "components": [
                {"component_id": "p1c1", "ratio": 1}, {"component_id": "p1c2", "ratio": 1}]},
            {"parent_id": "p2", "ratio": 1, "components": [{"component_id": "p2c1", "ratio": 1}]}]}
        for field in ("total", "parent"):
            bad = deepcopy(raw)
            if field == "total":
                bad["total_grams"] = 0
            else:
                bad["parents"][0]["ratio"] = 0
            with self.subTest(field=field), self.assertRaisesRegex(ContractError, "nonpositive_mass_or_ratio"):
                ComponentPipeline._parse_masses(json.dumps(bad), layout_data()["parents"], "total_ratio")

    def test_provider_systemic_failure_propagates_without_fallback(self):
        class ProviderFailure(BaseException):
            pass
        pipeline = self.pipeline([ProviderFailure()])
        with self.assertRaises(ProviderFailure):
            pipeline.layout(self.image)
        self.assertEqual(len(self.chat.messages), 1)

    def test_dependency_keys_bind_config_catalogue_and_implementation(self):
        pipeline = self.pipeline([])
        original = pipeline.dependencies({})
        self.assertEqual(original, pipeline.dependencies({}))
        self.assertNotEqual(original["config_hash"], pipeline.dependencies({"crop_review": True})["config_hash"])
        pipeline.catalog["foods"][CODES[0]]["density"]["protein"] = 26
        self.assertNotEqual(original["catalog_hash"], pipeline.dependencies({})["catalog_hash"])
        self.assertEqual(len(original["implementation_hash"]), 64)
        self.assertTrue(relation_hints("rice with chicken")["inferred_not_verified"])


if __name__ == "__main__":
    unittest.main()
