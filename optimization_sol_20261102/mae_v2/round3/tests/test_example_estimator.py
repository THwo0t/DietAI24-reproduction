"""Pure G boundary tests: fake provider and temporary synthetic pixels only."""
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
sys.path.insert(0, str(ROOT / "round3/src"))
import example_estimator as estimator
from opt_pipeline import ContractError
from opt_provider import ProviderStop


def examples():
    return [{"image_path": Path("support_PRIVATE_ID_" + str(index) + ".png"),
             "reference": dict(zip(estimator.TARGETS, (100 + index, 80 + index, 2, 12, 5)))}
            for index in range(4)]


def answer(**updates):
    item = {"item_id": "i1", "description": "visible query food", "weight": 160,
            "energy": 220, "fat": 9, "carbs": 18, "protein": 12}
    item.update(updates)
    return json.dumps({"items": [item]})


class FakeProvider:
    def __init__(self, *outputs):
        self.outputs, self.requests = list(outputs), []

    def chat(self, messages, **kwargs):
        self.requests.append({"messages": deepcopy(messages), **kwargs})
        if not self.outputs:
            raise AssertionError("Unexpected extra request")
        result = self.outputs.pop(0)
        if isinstance(result, BaseException):
            raise result
        return result


class ExampleEstimatorTests(unittest.TestCase):
    def call(self, *outputs):
        provider = FakeProvider(*outputs)
        with patch.object(estimator, "encode_image", return_value="data:image/png;base64,synthetic") as encode:
            result = estimator.infer(provider, "query_PRIVATE_QUERY_ID.png", examples())
        return result, provider, encode

    def test_exactly_four_supports_precede_single_query_and_no_id_text(self):
        result, provider, encode = self.call(answer())
        self.assertEqual(result["prediction"]["weight"], 160)
        self.assertIsNone(result["failure"])
        self.assertEqual(len(provider.requests), 1)
        self.assertEqual(provider.requests[0]["max_completion_tokens"], 8192)
        self.assertEqual(encode.call_count, 5)
        self.assertTrue(all(call.args[1] == "native" for call in encode.call_args_list))
        self.assertEqual(encode.call_args_list[-1].args[0], Path("query_PRIVATE_QUERY_ID.png").resolve())
        blocks = provider.requests[0]["messages"][1]["content"]
        self.assertEqual(sum(block["type"] == "image_url" for block in blocks), 5)
        self.assertEqual(blocks[-2]["text"], estimator.QUERY_PROMPT)
        text = json.dumps(provider.requests)
        self.assertNotIn("PRIVATE", text)
        for index, support in enumerate(examples()):
            numeric = {key: float(value) for key, value in support["reference"].items()}
            self.assertTrue(blocks[1 + 2 * index]["text"].endswith(json.dumps(numeric)))
        self.assertIn("Do not copy", estimator.INTRODUCTION)

    def test_invalid_reference_objects_rejected_before_encoding_or_provider(self):
        invalid = [None, (), examples()[:3], examples() + examples()[:1]]
        extra = examples(); extra[0]["sample_id"] = "PRIVATE_ID"; invalid.append(extra)
        extra = examples(); extra[0]["query_labels"] = {"weight": 1}; invalid.append(extra)
        extra = examples(); extra[0]["reference"]["extra"] = 3; invalid.append(extra)
        missing = examples(); del missing[0]["reference"]["protein"]; invalid.append(missing)
        missing = examples(); del missing[0]["image_path"]; invalid.append(missing)
        for key in estimator.TARGETS:
            for value in (True, False, None, "1", -1, float("nan"), float("inf")):
                sample = examples(); sample[0]["reference"][key] = value; invalid.append(sample)
        zero = examples(); zero[0]["reference"]["weight"] = 0; invalid.append(zero)
        for sample in invalid:
            provider = FakeProvider(answer())
            with self.subTest(sample=str(sample)[:100]), patch.object(estimator, "encode_image") as encode:
                with self.assertRaises(ContractError):
                    estimator.infer(provider, "query.png", sample)
                encode.assert_not_called()
                self.assertEqual(provider.requests, [])

    def test_duplicate_support_query_and_normalized_path_aliases_are_rejected(self):
        for duplicate in ("support", "query", "alias"):
            sample = examples()
            if duplicate == "support":
                sample[1]["image_path"] = sample[0]["image_path"]
            elif duplicate == "query":
                sample[0]["image_path"] = "query.png"
            else:
                sample[1]["image_path"] = Path("unused/../") / sample[0]["image_path"]
            with self.subTest(duplicate=duplicate), patch.object(estimator, "encode_image") as encode:
                with self.assertRaisesRegex(ContractError, "duplicate"):
                    estimator.infer(FakeProvider(answer()), "query.png", sample)
                encode.assert_not_called()

    def test_one_repair_preserves_raw_and_never_adds_images(self):
        result, provider, encode = self.call("bad", answer())
        self.assertEqual(result["raw_outputs"], ["bad", answer()])
        self.assertTrue(result["repair_used"])
        self.assertEqual(encode.call_count, 5)
        self.assertEqual(provider.requests[1]["messages"][-2], {"role": "assistant", "content": "bad"})
        self.assertIn("FORMAT only", provider.requests[1]["messages"][-1]["content"])
        for request in provider.requests:
            self.assertEqual(sum(block["type"] == "image_url" for message in request["messages"]
                                 if isinstance(message["content"], list) for block in message["content"]), 5)

    def test_invalid_response_contracts_fail_without_third_request(self):
        invalid = ["", '{"items":[]}', answer(weight=0), answer(protein=-1),
                   answer(fat=True), answer(carbs=float("nan")),
                   '{"items":[],"items":[]}', json.dumps({"items": [json.loads(answer())["items"][0]] * 2})]
        for raw in invalid:
            with self.subTest(raw=raw):
                result, provider, _ = self.call(raw, raw, answer())
                self.assertIsNone(result["prediction"])
                self.assertIsNotNone(result["failure"])
                self.assertEqual(result["items"], [])
                self.assertEqual(result["raw_outputs"], [raw, raw])
                self.assertEqual(len(provider.requests), 2)

    def test_provider_faults_propagate_on_main_and_repair_calls(self):
        for error in (ProviderStop("model mismatch"), RuntimeError("transport")):
            for outputs in ((error,), ("bad", error)):
                provider = FakeProvider(*outputs)
                with patch.object(estimator, "encode_image", return_value="data:image/png;base64,synthetic"):
                    with self.assertRaises(type(error)) as caught:
                        estimator.infer(provider, "query.png", examples())
                self.assertIs(caught.exception, error)
                self.assertEqual(len(provider.requests), len(outputs))

    def test_macro_mass_is_only_audit_and_references_are_not_mutated(self):
        sample = examples()
        before = deepcopy(sample)
        provider = FakeProvider(answer(weight=10, fat=8, carbs=8, protein=8))
        with patch.object(estimator, "encode_image", return_value="data:image/png;base64,synthetic"):
            result = estimator.infer(provider, "query.png", sample)
        self.assertEqual(sample, before)
        self.assertTrue(result["audit"]["macro_mass_excess_total"])
        self.assertEqual(result["prediction"]["fat"], 8)
        self.assertFalse(result["repair_used"])
        self.assertEqual(len(provider.requests), 1)

    def test_all_five_real_synthetic_images_strip_metadata_and_preserve_native_bounds(self):
        with tempfile.TemporaryDirectory(prefix="r3-examples-synthetic-") as directory:
            paths = []
            for index in range(5):
                path = Path(directory) / ("PRIVATE_ID_" + str(index) + ".png")
                metadata = PngImagePlugin.PngInfo()
                metadata.add_text("query_truth", "SENTINEL_QUERY_TRUTH")
                size = (1600, 800) if index % 2 else (32, 16)
                Image.new("RGB", size, (index, 50, 100)).save(path, pnginfo=metadata)
                paths.append(path)
            sample = examples()
            for support, path in zip(sample, paths):
                support["image_path"] = path
            provider = FakeProvider(answer())
            estimator.infer(provider, paths[-1], sample)
            serialized = json.dumps(provider.requests)
            self.assertNotIn("PRIVATE_ID", serialized)
            self.assertNotIn(directory, serialized)
            images = [block for block in provider.requests[0]["messages"][1]["content"]
                      if block["type"] == "image_url"]
            self.assertEqual(len(images), 5)
            for index, block in enumerate(images):
                payload = base64.b64decode(block["image_url"]["url"].split(",", 1)[1])
                self.assertNotIn(b"SENTINEL_QUERY_TRUTH", payload)
                with Image.open(BytesIO(payload)) as image:
                    self.assertEqual(image.size, (1024, 512) if index % 2 else (32, 16))
                    self.assertEqual(image.info, {})


if __name__ == "__main__":
    unittest.main()
