"""Synthetic image/fake-provider tests; no real image, label, API or validation."""
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
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "round4/src")]
import vision_stages as stages
from opt_pipeline import ContractError
from opt_provider import ProviderStop


def description(**updates):
    value = {"scene": "one foreground serving", "foods": [
        {"appearance": "pale rough clustered pieces", "placement": "near the centre"}],
        "scale_cues": ["a visible spoon"], "uncertainties": []}
    value.update(updates)
    return value


def desc_answer(**updates):
    return json.dumps(description(**updates))


def rank_answer(ids=None, **updates):
    return json.dumps({"selected_ids": ["c12", "c2", "c5", "c1"] if ids is None else ids, **updates})


def candidates():
    return [{"candidate_id": f"c{i}", "image_path": Path(f"PRIVATE_FILE_ID_{i}.png")} for i in range(1, 13)]


class FakeProvider:
    def __init__(self, *outputs):
        self.outputs, self.requests = list(outputs), []

    def chat(self, messages, **kwargs):
        self.requests.append({"messages": deepcopy(messages), **kwargs})
        if not self.outputs:
            raise AssertionError("Unregistered additional call")
        value = self.outputs.pop(0)
        if isinstance(value, BaseException):
            raise value
        return value


class VisionStageTests(unittest.TestCase):
    def describe(self, *outputs):
        provider = FakeProvider(*outputs)
        with patch.object(stages, "encode_image", return_value="data:image/png;base64,synthetic") as encoder:
            result = stages.describe(provider, "PRIVATE_QUERY_DATASET_ID.png")
        return result, provider, encoder

    def rerank(self, *outputs, supplied=None):
        provider = FakeProvider(*outputs)
        pictures = [f"data:image/png;base64,synthetic-{i}" for i in range(13)]
        with patch.object(stages, "encode_image", side_effect=pictures) as encoder:
            result = stages.rerank(provider, "PRIVATE_QUERY_DATASET_ID.png",
                                   candidates() if supplied is None else supplied)
        return result, provider, encoder

    def test_description_single_image_schema_and_canonical_embedding_without_metadata(self):
        raw = desc_answer()
        result, provider, encoder = self.describe(raw)
        self.assertEqual(result["raw_outputs"], [raw])
        self.assertEqual(result["parsed"], description())
        self.assertEqual(json.loads(result["embedding_text"]), description())
        self.assertEqual(result["embedding_text"], stages.embedding_text(description()))
        self.assertFalse(result["repair_used"])
        self.assertIsNone(result["failure"])
        self.assertEqual(len(provider.requests), 1)
        self.assertEqual(provider.requests[0]["max_completion_tokens"], 4096)
        self.assertEqual(encoder.call_count, 1)
        self.assertEqual(encoder.call_args.args[1], "native")
        payload = json.dumps(provider.requests)
        self.assertNotIn("PRIVATE_", payload)
        self.assertNotIn("ingr_", payload)
        self.assertNotIn('"grams":', payload)
        self.assertNotIn('"nutrients":', payload)
        self.assertNotIn("SENTINEL_QUERY_TRUTH", payload)

    def test_description_exactly_one_repair_preserves_both_raw_outputs(self):
        malformed = '{"scene":NaN}'
        repaired = desc_answer(scene="a single visible serving")
        result, provider, encoder = self.describe(malformed, repaired)
        self.assertEqual(result["raw_outputs"], [malformed, repaired])
        self.assertTrue(result["repair_used"])
        self.assertIsNone(result["failure"])
        self.assertEqual(len(provider.requests), 2)
        self.assertEqual(encoder.call_count, 1)
        second = provider.requests[1]
        self.assertEqual(second["messages"][-2], {"role": "assistant", "content": malformed})
        self.assertIn("FORMAT only", second["messages"][-1]["content"])
        self.assertIn("invalid_number", second["messages"][-1]["content"])
        self.assertEqual(second["max_completion_tokens"], 4096)

    def test_description_bad_json_empty_nan_duplicates_and_fields_fail_after_two(self):
        invalid = ["", "not JSON", "{}", "[]", '{"scene":NaN}',
                   '{"scene":"a","scene":"b"}', desc_answer(foods=[]),
                   desc_answer(foods=[description()["foods"][0]] * 21),
                   desc_answer(scene=True), desc_answer(scene=" "),
                   desc_answer(scale_cues="spoon"), desc_answer(uncertainties=["unclear"] * 9),
                   desc_answer(query_truth="SENTINEL_QUERY_TRUTH"),
                   desc_answer(foods=[{"appearance": "rough", "placement": "centre", "grams": 80}])]
        for raw in invalid:
            with self.subTest(raw=raw):
                result, provider, _ = self.describe(raw, raw, desc_answer())
                self.assertIsNone(result["parsed"])
                self.assertIsNone(result["embedding_text"])
                self.assertIsNotNone(result["failure"])
                self.assertEqual(result["raw_outputs"], [raw, raw])
                self.assertEqual(len(provider.requests), 2)
                self.assertEqual(len(provider.outputs), 1)

    def test_description_rejects_obvious_quantity_nutrition_code_or_path_text(self):
        for text in ("200 g white pieces", "protein 12 grams", "energy 500 kcal", "fat: 12", "1e2 g",
                     "code 12345678", "ingr_0000000001", "/home/private/image.png",
                     "source=https://example.invalid/a", "C:\\private\\image.jpg"):
            with self.subTest(text=text):
                raw = desc_answer(scene=text)
                result, _, _ = self.describe(raw, raw)
                self.assertEqual(result["failure"], "nonappearance_quantity_or_identifier")

    def test_legal_food_appearance_words_are_not_treated_as_nutrient_estimates(self):
        raw = desc_answer(foods=[{"appearance": "visible fat marbling and glossy surfaces",
                                 "placement": "near the centre"}],
                          uncertainties=["uncertain protein identity"])
        result, provider, _ = self.describe(raw)
        self.assertIsNone(result["failure"])
        self.assertEqual(len(provider.requests), 1)
        self.assertIn("fat marbling", result["embedding_text"])

    def test_text_bounds_no_silent_truncation_and_canonical_order(self):
        too_long = desc_answer(scene="x" * 301)
        oversized = desc_answer(scene="x" * 300, foods=[
            {"appearance": "a" * 300, "placement": "b" * 300}] * 20)
        for raw, code in ((too_long, "invalid_short_appearance_text"),
                          (oversized, "appearance_embedding_text_too_long")):
            result, _, _ = self.describe(raw, raw)
            self.assertEqual(result["failure"], code)
            self.assertEqual(result["raw_outputs"], [raw, raw])
        reverse = dict(reversed(list(description().items())))
        self.assertEqual(stages.embedding_text(reverse), stages.embedding_text(description()))
        with self.assertRaises(ContractError):
            stages.embedding_text({**description(), "labels": "SENTINEL_QUERY_TRUTH"})

    def test_rerank_thirteen_images_only_temporary_ids_and_exact_four(self):
        supplied = candidates()[::-1]
        result, provider, encoder = self.rerank(rank_answer(), supplied=supplied)
        self.assertEqual(result["selected_ids"], ["c12", "c2", "c5", "c1"])
        self.assertIsNone(result["failure"])
        request = provider.requests[0]
        self.assertEqual(request["max_completion_tokens"], 4096)
        content = request["messages"][1]["content"]
        self.assertEqual(sum(b["type"] == "image_url" for b in content), 13)
        self.assertEqual([b["text"] for b in content if b.get("text", "").startswith("Candidate ")],
                         [f"Candidate c{i}" for i in range(1, 13)])
        self.assertTrue(all(call.args[1] == "native" for call in encoder.call_args_list))
        self.assertEqual([call.args[0].name for call in encoder.call_args_list],
                         ["PRIVATE_QUERY_DATASET_ID.png"] + [f"PRIVATE_FILE_ID_{i}.png" for i in range(1, 13)])
        payload = json.dumps(request)
        for sentinel in ("PRIVATE_", "screening_group_id", "train_id", "SENTINEL_QUERY_TRUTH", '"grams":', '"cosine":'):
            self.assertNotIn(sentinel, payload)

    def test_rerank_repair_and_terminal_failure_do_not_choose_fallback(self):
        first = rank_answer(["c1", "c1", "c2", "c3"])
        result, provider, encoder = self.rerank(first, rank_answer())
        self.assertTrue(result["repair_used"])
        self.assertEqual(result["raw_outputs"], [first, rank_answer()])
        self.assertEqual(encoder.call_count, 13)
        self.assertEqual(provider.requests[1]["messages"][-2]["content"], first)
        for raw in ("", "{}", '{"selected_ids":NaN}', '{"selected_ids":[],"selected_ids":[]}',
                    rank_answer(["c0", "c2", "c3", "c4"]), rank_answer(["c13", "c2", "c3", "c4"]),
                    rank_answer([True, "c2", "c3", "c4"]), rank_answer(["c1"]), first,
                    rank_answer(explanation="SENTINEL_QUERY_TRUTH")):
            with self.subTest(raw=raw):
                failed, fake, _ = self.rerank(raw, raw, rank_answer())
                self.assertIsNone(failed["selected_ids"])
                self.assertIsNotNone(failed["failure"])
                self.assertEqual(failed["raw_outputs"], [raw, raw])
                self.assertEqual(len(fake.requests), 2)

    def test_rerank_boundary_rejects_metadata_bad_ids_and_duplicate_paths_before_io(self):
        invalid = [candidates()[:-1]]
        for key, value in (("query_truth", "SENTINEL_QUERY_TRUTH"), ("cosine", .9),
                           ("ingredients", []), ("train_id", "private")):
            bad = candidates(); bad[0][key] = value; invalid.append(bad)
        for field, value in (("candidate_id", "c2"), ("candidate_id", "private_id"),
                             ("image_path", "PRIVATE_QUERY_DATASET_ID.png"),
                             ("image_path", candidates()[1]["image_path"]), ("image_path", None)):
            bad = candidates(); bad[0][field] = value; invalid.append(bad)
        for bad in invalid:
            provider = FakeProvider(rank_answer())
            with self.subTest(candidate=bad[0]), patch.object(stages, "encode_image") as encoder:
                with self.assertRaises(ContractError):
                    stages.rerank(provider, "PRIVATE_QUERY_DATASET_ID.png", bad)
                encoder.assert_not_called()
                self.assertEqual(provider.requests, [])

    def test_provider_stop_and_other_exceptions_propagate_on_both_attempts(self):
        for invoke, valid in ((self.describe, desc_answer()), (self.rerank, rank_answer())):
            for exception in (ProviderStop("synthetic stop"), RuntimeError("synthetic failure")):
                with self.subTest(stage=invoke.__name__, error=type(exception).__name__):
                    with self.assertRaises(type(exception)):
                        invoke(exception, valid)
                    with self.assertRaises(type(exception)):
                        invoke("", exception, valid)

    def test_native_synthetic_image_retains_aspect_and_strips_filename_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "PRIVATE_FILE_SENTINEL.png"
            info = PngImagePlugin.PngInfo()
            info.add_text("Reference", "SENTINEL_QUERY_TRUTH")
            Image.new("RGB", (2048, 512), "white").save(path, pnginfo=info)
            provider = FakeProvider(desc_answer())
            stages.describe(provider, path)
            content = provider.requests[0]["messages"][1]["content"]
            url = next(b["image_url"]["url"] for b in content if b["type"] == "image_url")
            raw = base64.b64decode(url.split(",", 1)[1])
            with Image.open(BytesIO(raw)) as encoded:
                self.assertEqual(encoded.size, (1024, 256))
                self.assertEqual(encoded.mode, "RGB")
                self.assertEqual(encoded.info, {})
            self.assertNotIn(b"SENTINEL_QUERY_TRUTH", raw)
            self.assertNotIn("PRIVATE_FILE_SENTINEL", json.dumps(provider.requests))
            Image.new("RGB", (40, 20), "white").save(path)
            provider = FakeProvider(desc_answer())
            stages.describe(provider, path)
            url = provider.requests[0]["messages"][1]["content"][1]["image_url"]["url"]
            with Image.open(BytesIO(base64.b64decode(url.split(",", 1)[1]))) as encoded:
                self.assertEqual(encoded.size, (40, 20))


if __name__ == "__main__":
    unittest.main()
