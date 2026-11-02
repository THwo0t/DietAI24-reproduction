"""Pure round-four orchestration tests: fake services and no real image reads."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "src")]
from opt_pipeline import ContractError
from opt_provider import ProviderStop
from round4.src import pipeline, retrieval

CODE = "ingr_0000000001"
DENSITY = {"energy": 120, "fat": 1, "carbs": 25, "protein": 3}
DESCRIPTION = json.dumps({"scene": "one foreground serving",
    "foods": [{"appearance": "rough pale pieces", "placement": "at centre"}],
    "scale_cues": [], "uncertainties": []})
RERANK = json.dumps({"selected_ids": ["c4", "c2", "c1", "c3"]})
ESTIMATE = json.dumps({"items": [{"item_id": "i1", "description": "visible portion",
    "grams": 150, "ingredient_id": CODE, "estimated_density": None}]})


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def vector(a=1.0, b=0.0):
    return [a, b] + [0.0] * (retrieval.DIMENSIONS - 2)


def context(count=16):
    entries, vectors, supports = [], {}, {}
    for index in range(count):
        sid = f"PRIVATE_TRAIN_{index:02d}"
        entries.append({"train_id": sid, "screening_group_id": f"PRIVATE_GROUP_{index:02d}",
                        "image_sha256": digest(sid), "rgb_sha256": digest(sid + "pixels")})
        vectors[sid] = vector(1, index / 20)
        supports[sid] = {"image_path": Path(f"PRIVATE_SUPPORT_PATH_{index:02d}.png"),
                         "ingredients": [{"ingredient_id": CODE, "grams": 50 + index}]}
    query = {"query_id": "PRIVATE_QUERY_ID", "image_path": Path("PRIVATE_QUERY_PATH.png"),
             "image_sha256": digest("query"), "rgb_sha256": digest("querypixels"),
             "screening_group_id": "PRIVATE_QUERY_GROUP"}
    assets = {"scope": "external_train_only", "training_sha256": digest("externaltrain"),
              "catalog": [{"ingredient_id": CODE, "name": "synthetic food",
                           "density_per_100g": deepcopy(DENSITY)}],
              "fallback": {"weight": 222, "energy": 333, "fat": 4, "carbs": 55, "protein": 6},
              "supports": supports}
    return query, assets, retrieval.build_index(entries, vectors)


class FakeProvider:
    def __init__(self, outputs=None, embedding=None):
        self.outputs = list([DESCRIPTION, RERANK, ESTIMATE] if outputs is None else outputs)
        self.embedding = [vector()] if embedding is None else embedding
        self.requests, self.embeddings = [], []

    def chat(self, messages, **kwargs):
        self.requests.append({"messages": deepcopy(messages), **kwargs})
        if not self.outputs:
            raise AssertionError("unexpected chat call")
        value = self.outputs.pop(0)
        if isinstance(value, BaseException):
            raise value
        return value

    def embed(self, texts):
        self.embeddings.append(deepcopy(texts))
        if isinstance(self.embedding, BaseException):
            raise self.embedding
        return deepcopy(self.embedding)


class MemoryRunner:
    """Synthetic persistence exercising the public validator on fresh/cache."""
    def __init__(self):
        self.raw, self.inputs, self.calls, self.validations = {}, {}, [], 0

    def __call__(self, name, inputs, call, validator):
        key = (name, pipeline.fingerprint(inputs))
        self.inputs[name.rsplit(":", 1)[-1]] = deepcopy(inputs)
        if key not in self.raw:
            self.raw[key] = deepcopy(call())
            self.calls.append(name)
        self.validations += 1
        return validator(deepcopy(self.raw[key]))


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.patches = [patch.object(module, "encode_image", return_value="data:image/png;base64,SYNTHETIC")
                        for module in (pipeline.vision, pipeline.estimator)]
        self.encoders = [item.start() for item in self.patches]
        for item in self.patches:
            self.addCleanup(item.stop)

    def call(self, provider=None, inputs=None, runner=None):
        provider = provider or FakeProvider()
        inputs = context() if inputs is None else inputs
        return pipeline.infer(provider, *inputs, stage_runner=runner), provider

    def test_full_route_three_chats_one_embed_exact_payload_boundaries_and_totals(self):
        query, assets, gallery = context()
        before = deepcopy((query, assets))
        result, provider = self.call(inputs=(query, assets, gallery))
        self.assertEqual(result["prediction"], {"weight": 150, "energy": 180,
            "fat": 1.5, "carbs": 37.5, "protein": 4.5})
        self.assertEqual(result["raw_prediction"], result["prediction"])
        self.assertEqual(result["raw_leaves"], [{"item_id": "i1", "ingredient_id": CODE,
            "grams": 150, "density": DENSITY}])
        self.assertTrue(result["native_complete"])
        self.assertFalse(result["fallback"] or result["method_fallback"] or result["repair_used"])
        self.assertIsNone(result["failure"])
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["audit"]["selected_train_ids"],
                         [f"PRIVATE_TRAIN_{i:02d}" for i in (3, 1, 0, 2)])
        self.assertEqual(len(provider.embeddings), 1)
        self.assertEqual(provider.embeddings[0], [result["stages"]["description"]["embedding_text"]])
        self.assertEqual([r["max_completion_tokens"] for r in provider.requests], [4096, 4096, 8192])
        counts = [sum(block["type"] == "image_url" for msg in r["messages"]
                      if isinstance(msg["content"], list) for block in msg["content"])
                  for r in provider.requests]
        self.assertEqual(counts, [1, 13, 5])
        for request in provider.requests:
            serialized = json.dumps(request)
            self.assertNotIn("PRIVATE_", serialized)
            self.assertNotIn("training_sha256", serialized)
            self.assertNotIn("image_path", serialized)
        for request in provider.requests[:2]:
            self.assertNotIn(CODE, json.dumps(request))
            self.assertNotIn("reference_totals", json.dumps(request))
        self.assertIn("reference_totals", json.dumps(provider.requests[2]))
        self.assertEqual((query, assets), before)
        json.dumps(result, allow_nan=False)

    def test_gallery_helper_returns_vector_and_cannot_hide_failed_member(self):
        query, _, _ = context()
        image = {"image_id": query["query_id"], **{k: query[k] for k in pipeline.IMAGE_KEYS - {"image_id"}}}
        provider = FakeProvider([DESCRIPTION])
        result = pipeline.describe_and_embed(provider, image)
        self.assertEqual(result["embedding"], {"vector": vector()})
        self.assertIsNone(result["failure"])
        provider = FakeProvider(["bad", "bad"])
        failed = pipeline.describe_and_embed(provider, image)
        self.assertIsNone(failed["embedding"])
        self.assertIsNotNone(failed["failure"])
        self.assertEqual(provider.embeddings, [])
        self.assertNotIn("prediction", failed)

    def test_description_failure_returns_only_fixed_training_median(self):
        query, assets, gallery = context()
        result, provider = self.call(FakeProvider(["", "not json"]), (query, assets, gallery))
        self.assertEqual(result["prediction"], assets["fallback"])
        self.assertIsNone(result["raw_prediction"])
        self.assertEqual(result["raw_leaves"], [])
        self.assertTrue(result["fallback"] and result["repair_used"])
        self.assertFalse(result["native_complete"] or result["method_fallback"])
        self.assertEqual(set(result["stages"]), {"description"})
        self.assertEqual(provider.embeddings, [])
        self.assertEqual(result["audit"]["selected_train_ids"], [])
        self.assertEqual(result["audit"]["whole_fallback_source"],
                         "fixed_external_training_official_target_medians")

    def test_rerank_failure_uses_exact_retrieval_top_four_and_keeps_final_estimate(self):
        result, provider = self.call(FakeProvider([DESCRIPTION, "bad", "bad", ESTIMATE]))
        self.assertTrue(result["method_fallback"] and result["repair_used"])
        self.assertFalse(result["fallback"] or result["native_complete"])
        self.assertEqual(result["status"], "method_fallback")
        self.assertIsNone(result["failure"])
        self.assertEqual(result["audit"]["selected_candidate_ids"], ["c1", "c2", "c3", "c4"])
        self.assertTrue(result["audit"]["method_fallback_reason"].startswith("rerank:"))
        self.assertEqual(result["prediction"], result["raw_prediction"])
        self.assertEqual(len(provider.requests), 4)

    def test_estimate_failure_preserves_audit_and_uses_whole_training_fallback(self):
        result, _ = self.call(FakeProvider([DESCRIPTION, RERANK, "bad", "bad"]))
        self.assertEqual(result["prediction"], context()[1]["fallback"])
        self.assertEqual(result["items"], [])
        self.assertEqual(result["raw_leaves"], [])
        self.assertIsNone(result["raw_prediction"])
        self.assertTrue(result["fallback"])
        self.assertFalse(result["native_complete"])
        self.assertTrue(result["failure"].startswith("estimate:"))
        self.assertEqual(result["audit"]["unknown_count"], None)
        self.assertEqual(len(result["audit"]["selected_train_ids"]), 4)

    def test_successful_single_repair_is_complete_but_not_native(self):
        for outputs in (["bad", DESCRIPTION, RERANK, ESTIMATE],
                        [DESCRIPTION, "bad", RERANK, ESTIMATE],
                        [DESCRIPTION, RERANK, "bad", ESTIMATE]):
            with self.subTest(outputs=outputs):
                result, provider = self.call(FakeProvider(outputs))
                self.assertTrue(result["repair_used"])
                self.assertFalse(result["native_complete"] or result["fallback"] or result["method_fallback"])
                self.assertEqual(result["status"], "ok")
                self.assertEqual(len(provider.requests), 4)

    def test_provider_faults_at_all_stages_propagate_without_fallback(self):
        for error in (ProviderStop("route mismatch"), RuntimeError("service unavailable")):
            for outputs in ([error], ["bad", error], [DESCRIPTION, error],
                            [DESCRIPTION, "bad", error], [DESCRIPTION, RERANK, error],
                            [DESCRIPTION, RERANK, "bad", error]):
                with self.subTest(error=type(error), outputs=outputs):
                    with self.assertRaises(type(error)) as caught:
                        self.call(FakeProvider(outputs))
                    self.assertIs(caught.exception, error)
            with self.assertRaises(type(error)) as caught:
                self.call(FakeProvider([DESCRIPTION], embedding=error))
            self.assertIs(caught.exception, error)

    def test_invalid_official_embedding_is_integrity_error_not_accuracy_fallback(self):
        for embedding in ([], [vector(), vector()], [[0.0] * retrieval.DIMENSIONS],
                          [[1, 2]], [[float("nan")] + vector()[1:]], [tuple(vector())]):
            with self.subTest(embedding=str(embedding)[:30]):
                provider = FakeProvider([DESCRIPTION], embedding=embedding)
                with self.assertRaises(ValueError):
                    self.call(provider)
                self.assertEqual(len(provider.requests), 1)

    def test_invalid_context_fails_before_encoding_or_model_calls(self):
        cases = []
        query, assets, gallery = context(); query["truth"] = {"weight": 999}; cases.append((query, assets, gallery))
        query, assets, gallery = context(); assets["scope"] = "old_dev_trainfold"; cases.append((query, assets, gallery))
        query, assets, gallery = context(); assets["query_labels"] = {}; cases.append((query, assets, gallery))
        query, assets, gallery = context(); assets["supports"].pop("PRIVATE_TRAIN_00"); cases.append((query, assets, gallery))
        query, assets, gallery = context(); assets["supports"]["extra"] = {}; cases.append((query, assets, gallery))
        query, assets, gallery = context(); assets["fallback"]["fat"] = -1; cases.append((query, assets, gallery))
        query, assets, gallery = context(); assets["fallback"]["weight"] = 0; cases.append((query, assets, gallery))
        query, assets, gallery = context(); query["image_path"] = assets["supports"]["PRIVATE_TRAIN_00"]["image_path"]; cases.append((query, assets, gallery))
        for grams in (0, True, float("inf"), -1):
            query, assets, gallery = context()
            assets["supports"]["PRIVATE_TRAIN_00"]["ingredients"][0]["grams"] = grams
            cases.append((query, assets, gallery))
        query, assets, gallery = context()
        assets["supports"]["PRIVATE_TRAIN_00"]["ingredients"][0]["ingredient_id"] = "ingr_9999999999"
        cases.append((query, assets, gallery))
        query, assets, gallery = context()
        assets["supports"]["PRIVATE_TRAIN_00"]["ingredients"] = [
            {"ingredient_id": CODE, "grams": 1e308}, {"ingredient_id": CODE, "grams": 1e308}]
        cases.append((query, assets, gallery))
        for index, inputs in enumerate(cases):
            provider = FakeProvider()
            with self.subTest(case=index), self.assertRaises(ValueError):
                self.call(provider, inputs)
            self.assertEqual(provider.requests, [])
            self.assertEqual(provider.embeddings, [])
        for encoder in self.encoders:
            encoder.assert_not_called()

    def test_query_opaque_hash_and_group_exclusions_apply_before_any_calls(self):
        query, assets, gallery = context()
        query["image_sha256"] = gallery.entries[0].image_sha256
        query["rgb_sha256"] = gallery.entries[1].rgb_sha256
        query["screening_group_id"] = gallery.entries[2].screening_group_id
        result, _ = self.call(inputs=(query, assets, gallery))
        ids = [r["train_id"] for r in result["stages"]["retrieval"]]
        self.assertEqual(ids[0], "PRIVATE_TRAIN_03")
        self.assertEqual(len(ids), 12)
        query, assets, gallery = context(12)
        query["screening_group_id"] = gallery.entries[0].screening_group_id
        provider = FakeProvider()
        with self.assertRaisesRegex(retrieval.RetrievalError, "fewer_than_twelve"):
            self.call(provider, (query, assets, gallery))
        self.assertEqual(provider.requests, [])

    def test_cache_replay_has_no_calls_and_caches_terminal_format_failure(self):
        for outputs in ([DESCRIPTION, RERANK, ESTIMATE], ["bad", "bad"],
                        [DESCRIPTION, "bad", "bad", ESTIMATE]):
            with self.subTest(outputs=outputs):
                cache = MemoryRunner()
                first, _ = self.call(FakeProvider(outputs), runner=cache)
                provider = FakeProvider([])
                second, _ = self.call(provider, runner=cache)
                self.assertEqual(first, second)
                self.assertEqual(provider.requests + provider.embeddings, [])
                self.assertEqual(cache.validations, 2 * len(cache.calls))
                json.dumps(cache.inputs, allow_nan=False)

    def test_cached_tampering_and_impossible_attempt_history_are_rejected(self):
        cache = MemoryRunner(); self.call(runner=cache)
        for suffix, mutation in (
            ("estimate", lambda r: r["prediction"].update(weight=999)),
            ("rerank", lambda r: r.update(selected_ids=["c1", "c2", "c3", "c4"])),
            ("description", lambda r: r.update(raw_outputs=[DESCRIPTION, DESCRIPTION], repair_used=True)),
        ):
            changed = deepcopy(cache)
            key = next(key for key in changed.raw if key[0].endswith(":" + suffix))
            mutation(changed.raw[key])
            with self.subTest(stage=suffix), self.assertRaises(pipeline.PipelineError):
                self.call(FakeProvider([]), runner=changed)
        # Even an injected runner returning unchecked data is revalidated.
        def corrupt(name, inputs, call, validator):
            result = call()
            if name.endswith(":description"):
                result["parsed"]["scene"] = "tampered"
            return result
        with self.assertRaises(pipeline.PipelineError):
            self.call(runner=corrupt)

    def test_training_labels_change_only_estimation_dependencies(self):
        inputs = context(); first = MemoryRunner(); self.call(inputs=inputs, runner=first)
        query, assets, gallery = context()
        assets["training_sha256"] = digest("differentexternaltrain")
        assets["supports"]["PRIVATE_TRAIN_00"]["ingredients"][0]["grams"] = 999
        assets["catalog"][0]["density_per_100g"]["fat"] = 2
        second = MemoryRunner(); self.call(inputs=(query, assets, gallery), runner=second)
        for name in ("description", "embedding", "retrieval", "rerank"):
            self.assertEqual(first.inputs[name], second.inputs[name])
        self.assertNotEqual(first.inputs["estimate"], second.inputs["estimate"])
        for name in ("description", "embedding", "retrieval", "rerank"):
            self.assertNotIn("ingredients", json.dumps(first.inputs[name]))


if __name__ == "__main__":
    unittest.main()
