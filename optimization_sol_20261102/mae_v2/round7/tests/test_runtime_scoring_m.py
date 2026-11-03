"""Synthetic negative paths for M; no credentials, dataset files or network."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import httpx

BASE = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(BASE), str(BASE / "src"), str(BASE / "round7/src")]
import opt_provider as original
from opt_provider import CHAT_MODEL, EMBED_MODEL, ProviderStop, fingerprint
from historical_m import embedding_payload, imported_embedding
from runtime_m import MProvider, durable_json
from service_m import NAMESPACE, DIRECTORY, spec, paths, audit_state, verify_ref, Replay
from scoring_m import adapt_asa, select, tolerance


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "mae_v2"
        self.root.mkdir()
        self.patcher = patch.object(original, "ROOT", self.root)
        self.patcher.start(); self.addCleanup(self.patcher.stop)
        self.keys = ("chat-private-fixture-credential", "embed-private-fixture-credential")
        self.calls = []
        self.imports = {"entries": {}, "source_files": {}}
        self.vector = [1.] + [0.] * 3071

    def provider(self, handler=None):
        def serve(request):
            self.calls.append(request)
            role = "chat" if request.url.path.endswith("completions") else "embedding"
            self.assertEqual(request.headers["authorization"], "Bearer " + self.keys[0 if role == "chat" else 1])
            if handler is not None: return handler(request)
            body = {"model": CHAT_MODEL, "choices": [{"message": {"content": "{}"}, "finish_reason": "stop"}]} if role == "chat" else {
                "model": EMBED_MODEL, "data": [{"embedding": self.vector}]}
            return httpx.Response(200, json=body)
        provider = MProvider(self.imports, root=self.root, allow_paid=True, keys=self.keys,
                             transport=httpx.MockTransport(serve), sleep=lambda _: None)
        self.addCleanup(provider.close)
        return provider

    @staticmethod
    def payload():
        return {"model": CHAT_MODEL, "temperature": 1, "max_completion_tokens": 8192,
                "messages": [{"role": "user", "content": "synthetic text"}]}

    def test_dual_credentials_payload_models_and_cache_hits(self):
        provider = self.provider()
        self.assertEqual(provider.chat(self.payload()["messages"]), "{}")
        self.assertEqual(provider.embed(["rice"]), [self.vector])
        self.assertEqual(provider.embed(["rice"]), [self.vector])
        self.assertEqual(provider.chat(self.payload()["messages"]), "{}")
        self.assertEqual(len(self.calls), 2)
        state = audit_state(self.root, allow_incomplete=False)
        self.assertEqual(state["counts"]["chat"]["logged_transmissions"], 1)
        self.assertEqual(state["counts"]["embedding"]["logged_transmissions"], 1)
        self.assertEqual(provider.client.timeout.read, 600)

    def test_exact_embedding_text_and_budget_parameters(self):
        self.assertNotEqual(spec("embedding", embedding_payload("rice"))[0], spec("embedding", embedding_payload("rice "))[0])
        for payload in [{**self.payload(), "max_completion_tokens": 4096},
                        {**self.payload(), "temperature": 0}]:
            with self.assertRaises(ValueError): spec("chat", payload)

    def test_timeout_budget_remains_exhausted_on_reconstruction(self):
        provider = self.provider(lambda request: (_ for _ in ()).throw(httpx.ReadTimeout("fixture")))
        with self.assertRaises(ProviderStop): provider.chat(self.payload()["messages"])
        self.assertEqual(len(self.calls), 3)
        with self.assertRaisesRegex(ValueError, "exhausted"):
            self.provider()
        self.assertEqual(len(self.calls), 3)

    def test_unlogged_reservations_count_and_resume_does_not_reset(self):
        h, _, _ = spec("chat", self.payload())
        counter, _ = paths(self.root, "chat", h)
        durable_json(counter, {"request_hash": h, "attempts": 2, "last_reserved": "fixture", "namespace": NAMESPACE})
        provider = self.provider()
        provider.chat(self.payload()["messages"])
        state = audit_state(self.root, allow_incomplete=False)["counts"]["chat"]
        self.assertEqual(state["reserved_attempts"], 3)
        self.assertEqual(state["logged_transmissions"], 1)
        self.assertEqual(state["unlogged_reservations"], 2)

    def test_unknown_parent_or_current_embedding_state_blocks_no_copy(self):
        h, _, _ = spec("embedding", embedding_payload("rice"))
        path = self.root.parent / "runtime_cache/responses/embedding" / (h + ".json")
        path.parent.mkdir(parents=True)
        path.write_text("{}")
        provider = self.provider()
        with self.assertRaisesRegex(ProviderStop, "unregistered"):
            provider.embed(["rice"])
        self.assertEqual(len(self.calls), 0)
        self.assertFalse((self.root / "runtime_cache/responses/embedding" / path.name).exists())

    def test_model_mismatch_and_invalid_vectors_stop_batches(self):
        provider = self.provider(lambda r: httpx.Response(200, json={"model": "wrong"}))
        with self.assertRaises(ProviderStop): provider.chat(self.payload()["messages"])
        self.assertEqual(len(self.calls), 1)
        with self.assertRaisesRegex(ValueError, "model_changed"): audit_state(self.root)

    def reject_vector(self, vector):
        self.vector = vector
        provider = self.provider()
        with self.assertRaises(ProviderStop): provider.embed(["fixture"])

    def test_3071_vector_never_cached(self): self.reject_vector([1.] * 3071)
    def test_boolean_vector_never_cached(self): self.reject_vector([True] * 3072)
    def test_zero_vector_never_cached(self): self.reject_vector([0.] * 3072)

    def test_response_redaction_preserves_json(self):
        secret = self.keys[0]
        content = json.dumps({"explanation": secret, "truncated": secret[:12] + "..."})
        provider = self.provider(lambda r: httpx.Response(200, json={"model": CHAT_MODEL,
            "choices": [{"message": {"content": content}, "finish_reason": "stop"}]}))
        answer = json.loads(provider.chat(self.payload()["messages"]))
        self.assertEqual(answer, {"explanation": "[REDACTED]", "truncated": "[REDACTED]"})

    def test_replay_checks_spec_order_and_requires_counter_and_log(self):
        provider = self.provider()
        value = provider.chat(self.payload()["messages"])
        h, _, _ = spec("chat", self.payload())
        ref = {"role": "chat", "request_hash": h, "value_hash": fingerprint(value),
               "status": "returned", "origin": "new_M", "cache_present_before": False}
        replay = Replay(self.root, self.imports, [ref])
        self.assertEqual(replay.chat(self.payload()["messages"]), value)
        replay.finish()
        self.assertEqual(len(self.calls), 1)
        changed = deepcopy(self.payload()["messages"]); changed[0]["content"] += " "
        with self.assertRaisesRegex(ValueError, "payload_or_order"):
            Replay(self.root, self.imports, [ref]).chat(changed)
        counter, _ = paths(self.root, "chat", h)
        counter.unlink()
        with self.assertRaisesRegex(ValueError, "counter_missing"):
            verify_ref(self.root, self.imports, ref)

    def test_orphan_cache_is_not_ignored(self):
        provider = self.provider()
        provider.chat(self.payload()["messages"])
        (self.root / DIRECTORY / "requests.jsonl").unlink()
        with self.assertRaisesRegex(ValueError, "without_final_log"):
            audit_state(self.root)

    def tamper_cache_value(self, role):
        provider = self.provider()
        payload = self.payload() if role == "chat" else embedding_payload("fixture")
        provider._request(role, payload)
        h, _, _ = spec(role, payload)
        _, cache = paths(self.root, role, h)
        saved = json.loads(cache.read_text())
        saved["value"] = "changed response" if role == "chat" else [2.] + [0.] * 3071
        saved["value_hash"] = fingerprint(saved["value"])
        cache.write_text(json.dumps(saved))
        # Counter and successful log remain intact: a self-checksum alone must
        # not allow this replacement, including a well-formed different vector.
        with self.assertRaisesRegex(ValueError, "log_return_value_changed"):
            audit_state(self.root)

    def test_R7_G_1_recomputed_chat_cache_checksum_is_rejected(self): self.tamper_cache_value("chat")
    def test_R7_G_1_recomputed_vector_cache_checksum_is_rejected(self): self.tamper_cache_value("embedding")


class AdapterTests(unittest.TestCase):
    def test_exact_failed_portion_remains_scored_with_legal_median(self):
        code = "11111111"
        rows = [{"sample_id": "a", "dataset": "asa24"}]
        labels = {"a": {"food_code": code}}
        base = {"sample_id": "a", "dataset": "asa24", "final_codes": [code], "fallback": True, "raw_leaves": []}
        catalog = {"asa_options": {code: [{"option_id": "z", "grams": 30}, {"option_id": "a", "grams": 10}]},
                   "foods": {code: {"density": {"energy": 100, "fat": 2, "carbs": 20, "protein": 4}}}}
        out = adapt_asa(rows, labels, [base], catalog)[0]
        self.assertTrue(out["conditional"]["fallback"])
        self.assertEqual(out["conditional"]["prediction"]["weight"], 10)
        self.assertEqual(base["raw_leaves"], [])
        base.update(fallback=False, raw_leaves=[{"code": code, "grams": 5}, {"code": code, "grams": 15}])
        out = adapt_asa(rows, labels, [base], catalog)[0]
        self.assertEqual(out["conditional"]["continuous_grams"], 20)
        self.assertEqual(out["conditional"]["option_id"], "a")

    @staticmethod
    def metrics():
        checks = [{"dataset": ds, "target": target, "statistic": st, "value": .5, "threshold": 1}
                  for ds in ["asa24", "nutrition5k"] for target in ["weight", "energy", "fat", "carbs", "protein"]
                  for st in ["mae", "per_unit"]]
        return {"checks": checks, "passed_checks": 20,
                "datasets": {"asa24": {"n": 99, "exact_n": 15, "exact_groups": 5}}}

    def test_two_exceptions_per_dataset_not_cross_compensated(self):
        scores = self.metrics()
        for i in [0, 1, 10, 11]: scores["checks"][i]["value"] = 1.01
        scores["passed_checks"] = 16
        accepted = tolerance(scores)
        self.assertTrue(accepted["accepted"])
        self.assertEqual(accepted["failed_checks"], {"asa24": 2, "nutrition5k": 2})
        self.assertFalse(accepted["strict20_pass"])
        scores["checks"][2]["value"] = 1.01
        self.assertFalse(tolerance(scores)["accepted"])

    def test_undefined_and_integer_coverage_guards(self):
        for value in [None, float("nan"), float("inf"), -1, True]:
            scores = self.metrics(); scores["checks"][0]["value"] = value
            self.assertFalse(tolerance(scores)["accepted"])
        scores = self.metrics()
        self.assertEqual(tolerance(scores)["recognition_floor_n"], 15)
        self.assertEqual(tolerance(scores)["original18_target_n"], 18)
        for exact, groups in [(14, 5), (15, 4)]:
            scores["datasets"]["asa24"].update(exact_n=exact, exact_groups=groups)
            self.assertFalse(tolerance(scores)["accepted"])

    def test_one_profile_for_both_datasets_tie_retains_M0(self):
        result = {"tolerance": tolerance(self.metrics())}
        self.assertEqual(select({"M": result, "M0": result})["selected"], "M0")


if __name__ == "__main__": unittest.main()
