"""External-training catalogue contract tests using only synthetic fixtures."""
import base64
from copy import deepcopy
from io import BytesIO
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image, PngImagePlugin

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))
from round4.src import catalog_estimator as estimator
from opt_pipeline import ContractError
from opt_provider import ProviderStop

CODE1, CODE2 = "ingr_0000000001", "ingr_0000000002"
CATALOG = [
    {"ingredient_id": CODE1, "name": "synthetic cooked grain",
     "density_per_100g": {"energy": 120, "fat": 1, "carbs": 25, "protein": 3}},
    {"ingredient_id": CODE2, "name": "synthetic cooked protein",
     "density_per_100g": {"energy": 200, "fat": 10, "carbs": 0, "protein": 25}},
]


def examples():
    return [{"image_path": Path(f"support_PRIVATE_ID_{index}.png"),
             "ingredients": [{"ingredient_id": CODE1, "grams": 100},
                             {"ingredient_id": CODE2, "grams": 50}]} for index in range(4)]


def item(identifier="i1", **updates):
    value = {"item_id": identifier, "description": "visible food", "grams": 100,
             "ingredient_id": CODE1, "estimated_density": None}
    value.update(updates)
    return value


def answer(*items):
    return json.dumps({"items": list(items or [item()])})


class FakeProvider:
    def __init__(self, *outputs):
        self.outputs, self.requests = list(outputs), []

    def chat(self, messages, **kwargs):
        self.requests.append({"messages": deepcopy(messages), **kwargs})
        if not self.outputs:
            raise AssertionError("Unexpected additional model call")
        value = self.outputs.pop(0)
        if isinstance(value, BaseException):
            raise value
        return value


class CatalogEstimatorTests(unittest.TestCase):
    def call(self, *outputs, catalog=None, supports=None):
        provider = FakeProvider(*outputs)
        with patch.object(estimator, "encode_image", return_value="data:image/png;base64,synthetic") as encode:
            result = estimator.infer(provider, "query_PRIVATE_ID.png",
                examples() if supports is None else supports, CATALOG if catalog is None else catalog)
        return result, provider, encode

    def test_inference_contract_matches_frozen_H_except_version_and_docstring(self):
        # Compare syntax without importing or executing any round-three driver.
        import ast
        old = ast.parse((ROOT / "round3/src/catalog_estimator.py").read_text())
        new = ast.parse(Path(estimator.__file__).read_text())
        def normalized(tree):
            tree.body.pop(0)  # Only module-level provenance text differs.
            for node in tree.body:
                if isinstance(node, ast.Assign) and any(
                        isinstance(target, ast.Name) and target.id == "METHOD_VERSION"
                        for target in node.targets):
                    node.value = ast.Constant("VERSION")
            return ast.dump(tree, include_attributes=False)
        self.assertEqual(normalized(old), normalized(new))
        self.assertEqual(estimator.METHOD_VERSION, "external-training-ingredient-catalog-r4.1")

    def test_known_nutrients_and_demonstration_totals_are_programmatically_computed(self):
        raw = answer(item(grams=150), item("i2", grams=50, ingredient_id=CODE2), item("i3", grams=50))
        result, provider, encode = self.call(raw)
        self.assertEqual(result["prediction"],
                         {"weight": 250, "energy": 340, "fat": 7, "carbs": 50, "protein": 18.5})
        self.assertEqual(result["raw_outputs"], [raw])
        self.assertEqual([row["ingredient_id"] for row in result["items"]], [CODE1, CODE2, CODE1])
        self.assertTrue(all(row["estimated_density"] is None for row in result["items"]))
        self.assertEqual(result["audit"]["unknown_count"], 0)
        self.assertEqual(result["audit"]["unknown_mass_fraction"], 0)
        self.assertEqual(len(provider.requests), 1)
        self.assertEqual(provider.requests[0]["max_completion_tokens"], 8192)
        self.assertEqual(encode.call_count, 5)
        text = provider.requests[0]["messages"][1]["content"][2]["text"]
        support = json.loads(text.split(": ", 1)[1])
        self.assertEqual(support["reference_totals"],
                         {"weight": 150, "energy": 220, "fat": 6, "carbs": 25, "protein": 15.5})

    def test_unknown_density_is_allowed_and_counted_by_mass(self):
        density = {"energy": 80, "fat": 2, "carbs": 10, "protein": 5}
        raw = answer(item(grams=150), item("i2", grams=50, ingredient_id=None, estimated_density=density))
        result, provider, _ = self.call(raw)
        self.assertEqual(result["prediction"],
                         {"weight": 200, "energy": 220, "fat": 2.5, "carbs": 42.5, "protein": 7})
        self.assertEqual(result["audit"]["unknown_count"], 1)
        self.assertEqual(result["audit"]["unknown_mass_fraction"], .25)
        self.assertEqual(len(provider.requests), 1)
        self.assertIn("Do not force an absent food", estimator.QUERY_PROMPT)

    def test_illegal_known_id_ambiguous_density_and_incomplete_unknown_fail(self):
        density = dict.fromkeys(estimator.NUTRIENTS, 1)
        invalid = [item(ingredient_id="ingr_9999999999"), item(ingredient_id=True),
                   item(estimated_density=density), item(estimated_density={}),
                   item(ingredient_id=None), item(ingredient_id=None, estimated_density={"energy": 1}),
                   item(ingredient_id=None, estimated_density={**density, "weight": 100})]
        for row in invalid:
            raw = answer(row)
            with self.subTest(row=row):
                result, provider, _ = self.call(raw, raw)
                self.assertIsNone(result["prediction"])
                self.assertIsNotNone(result["failure"])
                self.assertEqual(len(provider.requests), 2)

    def test_strict_response_shapes_counts_ids_and_description(self):
        invalid = ["", "null", "[]", '{"items":[]}', '{"items":[],"items":[]}',
                   answer(item(), item()), answer(item(identifier="i0")), answer(item(identifier="i21")),
                   answer(item(description=" ")), answer(item(description=True)),
                   answer(item(description="x" * 4001)),
                   json.dumps({"items": [item()], "totals": {"weight": 999}}),
                   answer(item(energy=999)), answer(*(item(f"i{i}") for i in range(1, 22))),
                   answer().replace('"grams": 100', '"grams": 100, "grams": 101')]
        for raw in invalid:
            with self.subTest(raw=raw[:120]):
                result, provider, _ = self.call(raw, raw, answer())
                self.assertIsNone(result["prediction"])
                self.assertEqual(result["items"], [])
                self.assertEqual(result["raw_outputs"], [raw, raw])
                self.assertEqual(len(provider.requests), 2)
        result, _, _ = self.call(answer(*(item(f"i{i}") for i in range(1, 21))))
        self.assertEqual(len(result["items"]), 20)

    def test_nonfinite_negative_and_bool_model_values_are_rejected(self):
        for value in (0, -1, True, False, "1", None, float("nan"), float("inf")):
            with self.subTest(grams=value):
                raw = answer(item(grams=value))
                self.assertIsNone(self.call(raw, raw)[0]["prediction"])
        for key in estimator.NUTRIENTS:
            for value in (-1, True, "1", None, float("nan"), float("inf")):
                with self.subTest(key=key, value=value):
                    density = {**dict.fromkeys(estimator.NUTRIENTS, 0), key: value}
                    raw = answer(item(ingredient_id=None, estimated_density=density))
                    self.assertIsNone(self.call(raw, raw)[0]["prediction"])
        zero = answer(item(ingredient_id=None, estimated_density=dict.fromkeys(estimator.NUTRIENTS, 0)))
        self.assertEqual(self.call(zero)[0]["prediction"]["energy"], 0)

    def test_catalog_metadata_invalid_entries_and_duplicate_ids_fail_before_reads(self):
        invalid = [None, {}, [], {"ingredients": CATALOG}, CATALOG + [CATALOG[0]]]
        for field, value in (("supporting_dish_count", 4), ("heldout_fold", 1), ("query_labels", {"weight": 1})):
            catalog = deepcopy(CATALOG); catalog[0][field] = value; invalid.append(catalog)
        for field, value in (("ingredient_id", "bad"), ("name", " "), ("name", True), ("density_per_100g", {})):
            catalog = deepcopy(CATALOG); catalog[0][field] = value; invalid.append(catalog)
        for value in (True, -1, float("nan"), float("inf")):
            catalog = deepcopy(CATALOG); catalog[0]["density_per_100g"]["fat"] = value; invalid.append(catalog)
        for catalog in invalid:
            provider = FakeProvider(answer())
            with self.subTest(catalog=str(catalog)[:100]), patch.object(estimator, "encode_image") as encode:
                with self.assertRaises(ContractError):
                    estimator.infer(provider, "query.png", examples(), catalog)
                encode.assert_not_called()
                self.assertEqual(provider.requests, [])

    def test_support_boundary_rejects_query_labels_unknown_ids_and_invalid_grams(self):
        invalid = [None, examples()[:3], examples() + examples()[:1]]
        for field in ("query_labels", "reference", "sample_id", "fold"):
            supports = examples(); supports[0][field] = "PRIVATE"; invalid.append(supports)
        supports = examples(); supports[0]["ingredients"] = []; invalid.append(supports)
        for field, value in (("ingredient_id", None), ("ingredient_id", "ingr_9999999999"),
                             ("grams", 0), ("grams", -1), ("grams", True), ("grams", float("inf")),
                             ("grams", float("nan")), ("grams", "1"), ("query_labels", {})):
            supports = examples(); supports[0]["ingredients"][0][field] = value; invalid.append(supports)
        for supports in invalid:
            provider = FakeProvider(answer())
            with self.subTest(supports=str(supports)[:100]), patch.object(estimator, "encode_image") as encode:
                with self.assertRaises(ContractError):
                    estimator.infer(provider, "query.png", supports, CATALOG)
                encode.assert_not_called()
                self.assertEqual(provider.requests, [])

    def test_paths_are_distinct_after_resolution_and_do_not_enter_prompt(self):
        for target in ("support", "query", "alias"):
            supports = examples()
            supports[1]["image_path"] = (supports[0]["image_path"] if target == "support" else
                                         "query.png" if target == "query" else
                                         Path("unused/../") / supports[0]["image_path"])
            with self.subTest(target=target), patch.object(estimator, "encode_image") as encode:
                with self.assertRaisesRegex(ContractError, "duplicate"):
                    estimator.infer(FakeProvider(answer()), "query.png", supports, CATALOG)
                encode.assert_not_called()
        _, provider, _ = self.call(answer())
        text = json.dumps(provider.requests)
        self.assertNotIn("PRIVATE_ID", text)
        self.assertNotIn("supporting_dish_count", text)
        self.assertNotIn("heldout_fold", text)
        self.assertNotIn("image_path", text)

    def test_repair_keeps_both_raw_answers_and_exactly_five_images(self):
        bad = answer(item(ingredient_id="ingr_9999999999"))
        result, provider, encode = self.call(bad, answer())
        self.assertEqual(result["raw_outputs"], [bad, answer()])
        self.assertTrue(result["repair_used"])
        self.assertIsNone(result["failure"])
        self.assertEqual(encode.call_count, 5)
        self.assertEqual(provider.requests[1]["messages"][-2], {"role": "assistant", "content": bad})
        self.assertIn("FORMAT only", provider.requests[1]["messages"][-1]["content"])
        for request in provider.requests:
            self.assertEqual(sum(block["type"] == "image_url" for msg in request["messages"]
                                 if isinstance(msg["content"], list) for block in msg["content"]), 5)

    def test_provider_faults_propagate_from_main_and_repair(self):
        for error in (ProviderStop("model route mismatch"), RuntimeError("connection failure")):
            for raw in ((error,), ("bad", error)):
                provider = FakeProvider(*raw)
                with patch.object(estimator, "encode_image", return_value="data:image/png;base64,synthetic"):
                    with self.assertRaises(type(error)) as caught:
                        estimator.infer(provider, "query.png", examples(), CATALOG)
                self.assertIs(caught.exception, error)
                self.assertEqual(len(provider.requests), len(raw))

    def test_macro_mass_and_unknown_mass_are_audit_only(self):
        raw = answer(item(ingredient_id=None,
                          estimated_density={"energy": 900, "fat": 70, "carbs": 70, "protein": 70}))
        result, provider, _ = self.call(raw)
        self.assertEqual(result["prediction"]["fat"], 70)
        self.assertEqual(result["audit"], {"unknown_count": 1, "unknown_mass_fraction": 1,
            "macro_mass_excess_items": ["i1"], "macro_mass_excess_total": True})
        self.assertEqual(len(provider.requests), 1)
        self.assertFalse(result["repair_used"])

    def test_overflow_is_explicit_and_inputs_are_not_mutated(self):
        raw = answer(item(grams=1e308), item("i2", grams=1e308))
        result, _, _ = self.call(raw, raw)
        self.assertIsNone(result["prediction"])
        supports, catalog = examples(), deepcopy(CATALOG)
        before = deepcopy((supports, catalog))
        self.call(answer(), catalog=catalog, supports=supports)
        self.assertEqual((supports, catalog), before)

    def test_five_synthetic_images_are_native_and_metadata_free(self):
        with tempfile.TemporaryDirectory(prefix="r4-catalog-synthetic-") as directory:
            paths = []
            for index in range(5):
                path = Path(directory) / f"PRIVATE_QUERY_OR_SUPPORT_{index}.png"
                metadata = PngImagePlugin.PngInfo()
                metadata.add_text("query_labels", "SENTINEL_QUERY_TRUTH")
                Image.new("RGB", (1500, 750) if index % 2 else (24, 12), (index, 100, 50)).save(path, pnginfo=metadata)
                paths.append(path)
            supports = examples()
            for support, path in zip(supports, paths):
                support["image_path"] = path
            provider = FakeProvider(answer())
            estimator.infer(provider, paths[-1], supports, CATALOG)
            serialized = json.dumps(provider.requests)
            self.assertNotIn("PRIVATE_QUERY_OR_SUPPORT", serialized)
            self.assertNotIn(directory, serialized)
            blocks = provider.requests[0]["messages"][1]["content"]
            self.assertEqual(blocks[-2]["text"], estimator.QUERY_PROMPT)
            images = [block for block in blocks if block["type"] == "image_url"]
            self.assertEqual(len(images), 5)
            for index, block in enumerate(images):
                data = base64.b64decode(block["image_url"]["url"].split(",", 1)[1])
                self.assertNotIn(b"SENTINEL_QUERY_TRUTH", data)
                with Image.open(BytesIO(data)) as image:
                    self.assertEqual(image.size, (1024, 512) if index % 2 else (24, 12))
                    self.assertEqual(image.info, {})


if __name__ == "__main__":
    unittest.main()
