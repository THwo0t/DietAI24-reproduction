"""Round-three F offline tests: synthetic images and fake providers only."""
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
sys.path.insert(0, str(ROOT / "round3" / "src"))
import direct_estimator as estimator
from opt_provider import ProviderStop


def item(identifier="i1", **values):
    result = {"item_id": identifier, "description": "cooked visible food",
              "weight": 120, "energy": 165, "fat": 3, "carbs": 22, "protein": 12}
    result.update(values)
    return result


def answer(*items):
    return json.dumps({"items": list(items or [item()])})


class FakeProvider:
    def __init__(self, *outputs):
        self.outputs, self.requests = list(outputs), []

    def chat(self, messages, **kwargs):
        self.requests.append({"messages": deepcopy(messages), **kwargs})
        if not self.outputs:
            raise AssertionError("Unexpected extra request")
        output = self.outputs.pop(0)
        if isinstance(output, BaseException):
            raise output
        return output


class DirectEstimatorTests(unittest.TestCase):
    def run_fake(self, *outputs):
        provider = FakeProvider(*outputs)
        with patch.object(estimator, "encode_image", return_value="data:image/png;base64,synthetic") as encode:
            result = estimator.infer(provider, "PRIVATE_FILE_ID.png")
        encode.assert_called_once_with("PRIVATE_FILE_ID.png", "native")
        return result, provider

    def test_program_sums_all_five_targets_and_retains_raw_answer(self):
        raw = answer(item(), item("i2", weight=80, energy=60, fat=1, carbs=10, protein=2))
        result, provider = self.run_fake(raw)
        self.assertEqual(result["prediction"],
                         {"weight": 200, "energy": 225, "fat": 4, "carbs": 32, "protein": 14})
        self.assertEqual(result["raw_outputs"], [raw])
        self.assertEqual(len(result["items"]), 2)
        self.assertFalse(result["repair_used"])
        self.assertIsNone(result["failure"])
        self.assertEqual(len(provider.requests), 1)
        self.assertEqual(provider.requests[0]["max_completion_tokens"], 8192)

    def test_only_one_contract_repair_preserves_both_raw_answers(self):
        first, second = "not JSON", answer()
        result, provider = self.run_fake(first, second)
        self.assertEqual(result["raw_outputs"], [first, second])
        self.assertTrue(result["repair_used"])
        self.assertIsNone(result["failure"])
        self.assertEqual(provider.requests[1]["messages"][-2], {"role": "assistant", "content": first})
        repair = provider.requests[1]["messages"][-1]["content"]
        self.assertIn("FORMAT only", repair)
        self.assertIn("invalid_json", repair)
        self.assertEqual(len(provider.requests), 2)

    def test_invalid_outputs_stop_after_one_repair_and_do_not_zero_fill(self):
        result, provider = self.run_fake("", '{"items":[]}', answer())
        self.assertEqual(result["raw_outputs"], ["", '{"items":[]}'])
        self.assertIsNone(result["prediction"])
        self.assertEqual(result["items"], [])
        self.assertEqual(result["failure"], "invalid_item_count")
        self.assertTrue(result["repair_used"])
        self.assertEqual(len(provider.requests), 2)
        self.assertEqual(provider.outputs, [answer()])

    def test_strict_json_contract_rejects_invalid_shapes_and_fields(self):
        missing = item()
        del missing["protein"]
        extra = item(totals={"weight": 120})
        invalid = [
            "null", "[]", '{"items":null}', '{"items":{}}', '{"items":[]}',
            json.dumps({"items": [missing]}), json.dumps({"items": [extra]}),
            json.dumps({"items": [item()], "totals": {"weight": 999}}),
            '{"items":[],"items":[]}',
            answer(item()).replace('"weight": 120', '"weight": 120, "weight": 121'),
            "```json\n" + answer() + "\n```",
        ]
        for raw in invalid:
            with self.subTest(raw=raw):
                result, provider = self.run_fake(raw, raw)
                self.assertIsNone(result["prediction"])
                self.assertIsNotNone(result["failure"])
                self.assertEqual(result["raw_outputs"], [raw, raw])
                self.assertEqual(len(provider.requests), 2)

    def test_rejects_nonfinite_negative_bool_and_numeric_strings(self):
        for key in estimator.TARGETS:
            for value in (-1, True, False, "1", None, float("nan"), float("inf"), -float("inf")):
                with self.subTest(key=key, value=value):
                    raw = answer(item(**{key: value}))
                    result, _ = self.run_fake(raw, raw)
                    self.assertIsNone(result["prediction"])
        for value in (0, -0.0):
            result, _ = self.run_fake(answer(item(weight=value)), answer(item(weight=value)))
            self.assertEqual(result["failure"], "nonpositive_item_weight")
        result, _ = self.run_fake(answer(item(energy=0, fat=0, carbs=0, protein=0)))
        self.assertIsNone(result["failure"])

    def test_ids_descriptions_and_item_limit(self):
        bad_items = [
            [item(), item()], [item(identifier="")], [item(identifier="i0")],
            [item(identifier="i21")], [item(identifier=True)],
            [item(description=" ")], [item(description=5)],
            [item(description="x" * 4001)], [item(f"i{i}") for i in range(1, 22)],
        ]
        for items in bad_items:
            with self.subTest(items=items[:2]):
                raw = answer(*items)
                result, _ = self.run_fake(raw, raw)
                self.assertIsNone(result["prediction"])
        result, provider = self.run_fake(answer(*(item(f"i{i}") for i in range(1, 21))))
        self.assertEqual(len(result["items"]), 20)
        self.assertEqual(result["prediction"]["weight"], 2400)
        self.assertEqual(len(provider.requests), 1)

    def test_sum_overflow_is_a_contract_failure(self):
        raw = answer(item(weight=1e308), item("i2", weight=1e308))
        result, _ = self.run_fake(raw, raw)
        self.assertEqual(result["failure"], "nonfinite_plate_total")
        self.assertIsNone(result["prediction"])

    def test_macro_mass_constraint_is_audit_only(self):
        raw = answer(item(weight=10, fat=8, carbs=8, protein=8))
        result, provider = self.run_fake(raw)
        self.assertEqual(result["prediction"]["weight"], 10)
        self.assertEqual(result["prediction"]["fat"], 8)
        self.assertEqual(result["audit"],
                         {"macro_mass_excess_items": ["i1"], "macro_mass_excess_total": True})
        self.assertFalse(result["repair_used"])
        self.assertEqual(len(provider.requests), 1)

    def test_item_macro_audit_is_independent_of_plate_total(self):
        result, _ = self.run_fake(answer(item(weight=10, fat=8, carbs=8, protein=8),
                                         item("i2", weight=200, fat=0, carbs=0, protein=0)))
        self.assertEqual(result["audit"]["macro_mass_excess_items"], ["i1"])
        self.assertFalse(result["audit"]["macro_mass_excess_total"])

    def test_provider_faults_propagate_without_repair(self):
        for error in (ProviderStop("model route mismatch"), RuntimeError("transport failure")):
            provider = FakeProvider(error, answer())
            with patch.object(estimator, "encode_image", return_value="data:image/png;base64,synthetic"):
                with self.assertRaises(type(error)) as caught:
                    estimator.infer(provider, "unused.png")
            self.assertIs(caught.exception, error)
            self.assertEqual(len(provider.requests), 1)

    def test_provider_fault_during_repair_propagates(self):
        error = ProviderStop("model stopped")
        provider = FakeProvider("bad json", error)
        with patch.object(estimator, "encode_image", return_value="data:image/png;base64,synthetic"):
            with self.assertRaises(ProviderStop) as caught:
                estimator.infer(provider, "unused.png")
        self.assertIs(caught.exception, error)
        self.assertEqual(len(provider.requests), 2)

    def test_request_contains_only_one_metadata_free_native_image(self):
        with tempfile.TemporaryDirectory(prefix="r3-direct-synthetic-") as directory:
            for size in ((1600, 800), (40, 20)):
                with self.subTest(size=size):
                    path = Path(directory) / "PRIVATE_FILE_ID_AND_DATASET.png"
                    metadata = PngImagePlugin.PngInfo()
                    metadata.add_text("truth", "SENTINEL_TRUTH_NEVER_SEND")
                    Image.new("RGB", size, (100, 200, 50)).save(path, pnginfo=metadata)
                    provider = FakeProvider(answer())
                    estimator.infer(provider, path)
                    request = provider.requests[0]
                    serialized = json.dumps(request)
                    for sentinel in ("PRIVATE_FILE_ID", "SENTINEL_TRUTH_NEVER_SEND", directory):
                        self.assertNotIn(sentinel, serialized)
                    messages = request["messages"]
                    self.assertEqual(messages[0]["content"], estimator.SYSTEM_PROMPT)
                    self.assertEqual(messages[1]["content"][0]["text"], estimator.PROMPT)
                    images = [block for msg in messages if isinstance(msg["content"], list)
                              for block in msg["content"] if block["type"] == "image_url"]
                    self.assertEqual(len(images), 1)
                    data = base64.b64decode(images[0]["image_url"]["url"].split(",", 1)[1])
                    self.assertNotIn(b"SENTINEL_TRUTH_NEVER_SEND", data)
                    with Image.open(BytesIO(data)) as encoded:
                        self.assertEqual(encoded.size, (1024, 512) if size[0] > 1024 else size)
                        self.assertEqual(encoded.info, {})


if __name__ == "__main__":
    unittest.main()
