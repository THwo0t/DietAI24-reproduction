"""I must differ from stable H only by its appended query visual checklist."""
import ast
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "round3/src"))
import catalog_estimator as baseline
import visual_estimator as candidate
from opt_pipeline import ContractError
from opt_provider import ProviderStop

CODE = "ingr_0000000001"
CATALOG = [{"ingredient_id": CODE, "name": "synthetic training food",
            "density_per_100g": {"energy": 120, "fat": 2, "carbs": 20, "protein": 5}}]


def supports():
    return [{"image_path": Path(f"PRIVATE_SUPPORT_{index}.png"),
             "ingredients": [{"ingredient_id": CODE, "grams": 80 + index}]} for index in range(4)]


def answer(**updates):
    item = {"item_id": "i1", "description": "visible food", "grams": 100,
            "ingredient_id": CODE, "estimated_density": None}
    item.update(updates)
    return json.dumps({"items": [item]})


class Provider:
    def __init__(self, outputs):
        self.outputs, self.requests = list(outputs), []

    def chat(self, messages, **kwargs):
        self.requests.append({"messages": deepcopy(messages), **kwargs})
        if not self.outputs:
            raise AssertionError("Unexpected extra request")
        value = self.outputs.pop(0)
        if isinstance(value, BaseException):
            raise value
        return value


class VisualEstimatorTests(unittest.TestCase):
    def invoke(self, module, outputs):
        provider = Provider(outputs)
        # Distinct deterministic pixels prove ordering, with no real image read.
        images = [f"data:image/png;base64,synthetic-{i}" for i in range(5)]
        with patch.object(module, "encode_image", side_effect=images) as encoder:
            result = module.infer(provider, "PRIVATE_QUERY.png", supports(), CATALOG)
        return result, provider.requests, encoder.call_args_list

    def assert_only_query_differs(self, old, new):
        self.assertEqual(len(old), len(new))
        for original, revised in zip(old, new):
            normalized = deepcopy(revised)
            changed = 0
            for message in normalized["messages"]:
                if isinstance(message["content"], list):
                    for block in message["content"]:
                        if block.get("text") == candidate.QUERY_PROMPT:
                            block["text"] = baseline.QUERY_PROMPT
                            changed += 1
            self.assertEqual(changed, 1)
            self.assertEqual(normalized, original)

    def test_success_requests_are_identical_except_one_query_text(self):
        before_prompt = baseline.QUERY_PROMPT
        old_result, old_requests, old_encoding = self.invoke(baseline, [answer()])
        new_result, new_requests, new_encoding = self.invoke(candidate, [answer()])
        self.assert_only_query_differs(old_requests, new_requests)
        self.assertEqual(old_result, new_result)
        self.assertEqual(old_encoding, new_encoding)
        self.assertEqual(baseline.QUERY_PROMPT, before_prompt)
        self.assertEqual(candidate.QUERY_PROMPT, baseline.QUERY_PROMPT + candidate.VISUAL_CHECKS)
        self.assertEqual(new_requests[0]["max_completion_tokens"], 8192)
        self.assertEqual(len(new_encoding), 5)
        self.assertTrue(all(call.args[1] == "native" for call in new_encoding))
        self.assertNotIn("PRIVATE_", json.dumps(new_requests))

    def test_repair_requests_and_results_remain_identical_except_query_text(self):
        values = [answer(ingredient_id="ingr_9999999999"), answer()]
        old_result, old_requests, _ = self.invoke(baseline, values)
        new_result, new_requests, calls = self.invoke(candidate, values)
        self.assert_only_query_differs(old_requests, new_requests)
        self.assertEqual(old_result, new_result)
        self.assertTrue(new_result["repair_used"])
        self.assertEqual(new_result["raw_outputs"], values)
        self.assertEqual(len(calls), 5)
        for request in new_requests:
            self.assertEqual(request["max_completion_tokens"], 8192)
            self.assertEqual(sum(block["type"] == "image_url" for message in request["messages"]
                                 if isinstance(message["content"], list) for block in message["content"]), 5)

    def test_failure_stops_after_one_repair_with_same_h_contract(self):
        values = ["bad", '{"items":[]}', answer()]
        old_result, old_requests, _ = self.invoke(baseline, values)
        new_result, new_requests, _ = self.invoke(candidate, values)
        self.assertEqual(old_result, new_result)
        self.assert_only_query_differs(old_requests, new_requests)
        self.assertIsNone(new_result["prediction"])
        self.assertEqual(len(new_requests), 2)

    def test_unknown_branch_and_macro_audit_stay_unchanged(self):
        values = [answer(ingredient_id=None,
                         estimated_density={"energy": 900, "fat": 70, "carbs": 70, "protein": 70})]
        old_result, _, _ = self.invoke(baseline, values)
        new_result, new_requests, _ = self.invoke(candidate, values)
        self.assertEqual(old_result, new_result)
        self.assertEqual(new_result["audit"]["unknown_count"], 1)
        self.assertTrue(new_result["audit"]["macro_mass_excess_total"])
        self.assertEqual(len(new_requests), 1)

    def test_all_function_bodies_are_structurally_identical_to_h(self):
        def functions(module):
            tree = ast.parse(Path(module.__file__).read_text())
            return {node.name: ast.dump(node, include_attributes=False) for node in tree.body
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
        self.assertEqual(functions(candidate), functions(baseline))
        self.assertEqual(hashlib.sha256(Path(baseline.__file__).read_bytes()).hexdigest(),
                         "60a45538807567b5f2312b60f29430dc81d193a04a5da2705e17005021f55dbd")

    def test_checklist_has_no_class_id_or_development_specific_exception(self):
        text = candidate.VISUAL_CHECKS.lower()
        forbidden = (r"\bingr_[0-9]+\b", r"\bdish_[0-9]+\b", r"\bfold\b", r"\bdev(?:elopment)?\b",
                     r"\b(?:egg|eggs|rice|cauliflower|chicken|beef|pork|tofu|broccoli|salmon)\b")
        for pattern in forbidden:
            self.assertIsNone(re.search(pattern, text), pattern)
        for phrase in ("neighboring or background", "pale or white color alone", "thickness",
                       "not a physical ruler", "unknown-ingredient branch"):
            self.assertIn(phrase, text)

    def test_invalid_inputs_still_fail_before_images_or_chat(self):
        invalid = supports()
        invalid[0]["query_labels"] = {"weight": 100}
        provider = Provider([answer()])
        with patch.object(candidate, "encode_image") as encoder:
            with self.assertRaises(ContractError):
                candidate.infer(provider, "query.png", invalid, CATALOG)
            encoder.assert_not_called()
        self.assertEqual(provider.requests, [])

    def test_provider_stop_propagates_without_silent_fallback(self):
        for values in ([ProviderStop("model stopped")], ["bad", ProviderStop("model stopped")]):
            provider = Provider(values)
            with patch.object(candidate, "encode_image", return_value="data:image/png;base64,synthetic"):
                with self.assertRaises(ProviderStop):
                    candidate.infer(provider, "query.png", supports(), CATALOG)
            self.assertEqual(len(provider.requests), len(values))


if __name__ == "__main__":
    unittest.main()
