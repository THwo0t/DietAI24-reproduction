"""Hand-calculated mass/unit identities and source/structure negative paths."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import unittest

from PIL import Image

BASE = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(BASE), str(BASE / "src"), str(BASE / "round8/src")]
from opt_pipeline import ContractError
from opt_provider import ProviderStop
from pipeline_v2 import _flatten, _image_hash
from uncertain_portions import UncertainPortionPipeline, canonical_options, materialize_identity

A, B, C = "11111111", "22222222", "33333333"
CATALOG = {"foods": {
    A: {"description": "food A cooked", "category": "A", "density": {"energy": 100, "fat": 2, "carbs": 10, "protein": 5}},
    B: {"description": "food A alternative", "category": "A", "density": {"energy": 300, "fat": 6, "carbs": 30, "protein": 15}},
    C: {"description": "food C cooked", "category": "C", "density": {"energy": 200, "fat": 8, "carbs": 0, "protein": 20}}},
    "standard_options": {A: [{"option_id": "half", "description": "1/2 cup", "grams": 100},
                              {"option_id": "full", "description": "1 cup", "grams": 200},
                              {"option_id": "mixed", "description": "1 1/2 cups", "grams": 300}]},
    "standard_portion_source_sha256": "synthetic-source"}


class UncertainCoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.image = Path(self.temp.name) / "SYNTHETIC_PRIVATE_ID.png"
        Image.new("RGB", (48, 32), (100, 150, 200)).save(self.image)
        parents = [{"parent_id": "p1", "description": "two separate foods", "bbox": [0, 0, 1, 1],
            "region_ids": ["r1"], "accounting": "components", "components": [
                {"component_id": "p1c1", "description": "food A", "broad_query": "A"},
                {"component_id": "p1c2", "description": "food C", "broad_query": "C"}]}]
        self.base = {"status": "ok", "parents": parents,
            "leaves": [{**row, "primary_code": A if row["component_id"] == "p1c1" else C,
                        "alternative_codes": []} for row in _flatten(parents)],
            "candidates": {"p1c1": [A, B], "p1c2": [C]}, "input_image_sha256": _image_hash(self.image),
            "sample_id": "PRIVATE_METADATA_MUST_NOT_ENTER_PROMPT"}
        self.choice = {"items": [{"component_id": "p1c1", "codes": [A, B]},
                                  {"component_id": "p1c2", "codes": [C]}]}
        self.calls = []

    def pipeline(self, outputs):
        outputs = list(outputs)
        def chat(messages):
            self.calls.append(deepcopy(messages))
            if not outputs: raise AssertionError("unexpected_chat")
            out = outputs.pop(0)
            if isinstance(out, BaseException): raise out
            return out if isinstance(out, str) else json.dumps(out)
        def embed(_): raise AssertionError("N_batch_must_not_embed")
        return UncertainPortionPipeline(chat, embed, deepcopy(CATALOG), None)

    def identity(self, pipeline):
        return pipeline.identify_uncertain(self.image, self.base)

    def old_portion(self):
        return {"status": "ok", "repaired": False, "prediction": {"weight": 150}, "raw_leaves": [
            {"component_id": "p1c1", "code": A, "grams": 100},
            {"component_id": "p1c2", "code": C, "grams": 50}]}

    def test_alternative_densities_count_physical_mass_once(self):
        pipeline = self.pipeline([self.choice]); identity = self.identity(pipeline)
        portion = pipeline.density_portion(self.image, identity, self.base, self.old_portion())
        self.assertEqual(portion["prediction"], {"weight": 150, "energy": 300, "fat": 8, "carbs": 20, "protein": 20})
        self.assertEqual(len(portion["raw_leaves"]), 2)
        self.assertEqual(identity["coding"]["ordered_codes"], [A, C, B])

    def test_one_canonical_unit_preserves_fraction_provenance(self):
        units = canonical_options(CATALOG["standard_options"][A], A)
        self.assertEqual(len(units["units"]), 1)
        unit = units["units"][0]
        self.assertEqual((unit["description"], unit["grams_per_unit"]), ("1 cup", 200))
        self.assertEqual(len(unit["sources"]), 3)
        half = next(s for s in unit["sources"] if s["option_id"] == "half")
        self.assertEqual((half["quantity_numerator"], half["quantity_denominator"]), (1, 2))

    def test_mixed_hyphen_and_decimal_prefixes(self):
        for prefix in ["1-1/2", "1.5", "1 1/2"]:
            unit = canonical_options([{"option_id": "a", "description": prefix + " cups", "grams": 300}], A)["units"][0]
            self.assertEqual(unit["grams_per_unit"], 200)

    def test_conflicting_same_unit_is_excluded_without_averaging(self):
        options = deepcopy(CATALOG["standard_options"][A])
        options.append({"option_id": "conflict", "description": "1 cup", "grams": 180})
        result = canonical_options(options, A)
        self.assertEqual(result["units"], [])
        self.assertEqual(result["conflicts"][0]["different_weights"], 2)

    def quantity(self, unit):
        return {"items": [{"component_id": "p1c1", "mode": "unit", "unit_id": unit["unit_id"], "quantity": 1.5, "grams": None},
            {"component_id": "p1c2", "mode": "direct", "unit_id": None, "quantity": None, "grams": 75}]}

    def test_half_cup_source_and_one_point_five_cups_do_not_double_fraction(self):
        unit = canonical_options(CATALOG["standard_options"][A], A)["units"][0]
        pipeline = self.pipeline([self.choice, self.quantity(unit)]); identity = self.identity(pipeline)
        portion = pipeline.unit_portion(self.image, identity, self.base)
        self.assertEqual(portion["prediction"]["weight"], 375)
        self.assertEqual(portion["prediction"]["energy"], 750)
        self.assertEqual([c["mode"] for c in portion["unit_choices"]], ["unit", "direct"])

    def test_context_contains_no_query_metadata_or_numeric_nutrient_density(self):
        pipeline = self.pipeline([self.choice]); self.identity(pipeline)
        prompt = self.calls[0][1]["content"][0]["text"]
        self.assertNotIn("PRIVATE_METADATA", prompt)
        context = json.loads(prompt.split("Context: ", 1)[1])
        self.assertEqual(set(context["catalog"][0]), {"code", "description", "category"})

    def test_invalid_codes_missing_leaf_duplicates_and_extra_leaf_are_rejected(self):
        choices = []
        for codes in [[A, A], [A, B, C, A], ["99999999"], []]:
            choice = deepcopy(self.choice); choice["items"][0]["codes"] = codes; choices.append(choice)
        choices.extend([{"items": self.choice["items"][:1]}, {"items": self.choice["items"] * 2}])
        for choice in choices:
            with self.subTest(choice=choice), self.assertRaises(ContractError):
                materialize_identity(json.dumps(choice), self.base, CATALOG["foods"])

    def test_invalid_unused_candidate_bank_stops_before_paid_call(self):
        self.base["candidates"]["p1c1"].append("99999999")
        pipeline = self.pipeline([])
        with self.assertRaises(ContractError): self.identity(pipeline)
        self.assertEqual(self.calls, [])

    def test_one_missing_quantity_invalidates_entire_profile(self):
        bad = {"items": []}
        pipeline = self.pipeline([self.choice, bad, bad]); identity = self.identity(pipeline)
        coding = deepcopy(identity["coding"])
        portion = pipeline.unit_portion(self.image, identity, self.base)
        self.assertEqual(portion["status"], "failed")
        self.assertIsNone(portion["prediction"])
        self.assertEqual(portion["raw_leaves"], [])
        self.assertEqual(identity["coding"], coding)
        self.assertEqual(len(self.calls), 3)

    def test_unit_choice_and_numeric_negative_paths(self):
        unit = canonical_options(CATALOG["standard_options"][A], A)["units"][0]
        identity = materialize_identity(json.dumps(self.choice), self.base, CATALOG["foods"])
        pipeline = self.pipeline([]); context = pipeline.unit_context(identity)
        for value in [0, -1, True, float("nan"), float("inf"), 1e308]:
            bad = self.quantity(unit); bad["items"][0]["quantity"] = value
            with self.subTest(value=value), self.assertRaises(ContractError):
                pipeline.parse_quantities(json.dumps(bad), identity, context)
        for field, value in [("unit_id", "foreign"), ("grams", 100), ("mode", "direct")]:
            bad = self.quantity(unit); bad["items"][0][field] = value
            with self.subTest(field=field), self.assertRaises(ContractError):
                pipeline.parse_quantities(json.dumps(bad), identity, context)

    def test_large_finite_direct_mass_avoids_intermediate_density_overflow(self):
        unit = canonical_options(CATALOG['standard_options'][A],A)['units'][0]
        quantity = self.quantity(unit); quantity['items'][1]['grams'] = 1e306
        pipeline = self.pipeline([self.choice,quantity]); identity = self.identity(pipeline)
        portion = pipeline.unit_portion(self.image,identity,self.base)
        self.assertEqual(portion['status'],'ok')
        self.assertEqual(portion['prediction']['energy'],2e306)
        self.assertEqual(len(self.calls),2)

    def test_real_total_or_nutrient_overflow_repairs_once_then_fails_atomically(self):
        unit = canonical_options(CATALOG['standard_options'][A],A)['units'][0]
        for first,second in [(1e308,1e308),(1e307,1e308)]:
            with self.subTest(first=first):
                quantity = self.quantity(unit)
                quantity['items'][0]['quantity'] = first/200
                quantity['items'][1]['grams'] = second
                pipeline = self.pipeline([self.choice,quantity,quantity]); identity = self.identity(pipeline)
                coding = deepcopy(identity['coding'])
                portion = pipeline.unit_portion(self.image,identity,self.base)
                self.assertEqual(portion['status'],'failed'); self.assertIsNone(portion['prediction'])
                self.assertEqual(portion['raw_leaves'],[]); self.assertEqual(identity['coding'],coding)
                self.assertEqual(len(portion['stages'][0]['attempts']),2)

    def test_tampered_identity_or_upstream_cannot_attach_old_mass(self):
        pipeline = self.pipeline([self.choice]); identity = self.identity(pipeline)
        for mutate in [lambda v: v["leaves"][0]["codes"].reverse(),
                       lambda v: v["coding"]["final_codes"].reverse(),
                       lambda v: v["leaves"][0]["mean_density"].update(protein=0)]:
            bad = deepcopy(identity); mutate(bad)
            with self.assertRaises(ContractError):
                pipeline.density_portion(self.image, bad, self.base, self.old_portion())
        changed = deepcopy(self.base); changed["candidates"]["p1c1"].reverse()
        with self.assertRaises(ContractError):
            pipeline.density_portion(self.image, identity, changed, self.old_portion())

    def test_foreign_old_gram_join_and_missing_old_quantity_fail_closed(self):
        pipeline = self.pipeline([self.choice]); identity = self.identity(pipeline)
        old = self.old_portion(); old["raw_leaves"][0]["code"] = B
        with self.assertRaises(ContractError): pipeline.density_portion(self.image, identity, self.base, old)
        old = {"status": "failed"}
        result = pipeline.density_portion(self.image, identity, self.base, old)
        self.assertEqual(result["failure"], "N_imported_quantity_failed")

    def test_service_fault_propagates_without_format_repair(self):
        pipeline = self.pipeline([ProviderStop("synthetic_stop")])
        with self.assertRaises(ProviderStop): self.identity(pipeline)
        self.assertEqual(len(self.calls), 1)


if __name__ == "__main__": unittest.main()
