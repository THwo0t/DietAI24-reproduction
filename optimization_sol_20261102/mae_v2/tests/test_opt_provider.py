"""MockTransport provider contracts; fictitious keys and no real .env reads."""

import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import opt_provider as provider

KEYS = ("sk-" + "chat-FAKEONLY0123456789abcdefghij", "sk-" + "embed-FAKEONLY9876543210zyxwvuts")
NON_SK_KEYS = ("vendorChat_FAKEONLYabcdefghijklmn1234", "officialEmbed_FAKEONLYzyxwvuts9876")
MESSAGES = [{"role": "user", "content": "synthetic offline test"}]


def chat_body(content='{"ok":true}', model=provider.CHAT_MODEL, finish="stop"):
    return {"model": model, "choices": [{"finish_reason": finish,
            "message": {"content": content}}],
            "usage": {"prompt_tokens": 8, "completion_tokens": 4, "total_tokens": 12,
                      "completion_tokens_details": {"reasoning_tokens": 2}}}


def embed_body(vector=None, model=provider.EMBED_MODEL):
    return {"model": model, "data": [{"embedding": vector if vector is not None else [0.5] * 3072}],
            "usage": {"prompt_tokens": 7, "total_tokens": 7}}


class ProviderTests(unittest.TestCase):
    def setUp(self):
        root = Path(__file__).resolve().parents[1]
        (root / "runtime_cache").mkdir(exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(prefix="provider-tests-", dir=root / "runtime_cache")
        self.root = Path(self.tmp.name)
        self.root_patch = patch.object(provider, "ROOT", self.root)
        self.root_patch.start()
        self.credential_patch = patch.object(provider, "read_credentials", side_effect=AssertionError("real credentials must not be read"))
        self.credential_mock = self.credential_patch.start()
        self.clients = []

    def tearDown(self):
        for client in self.clients:
            client.close()
        self.credential_patch.stop()
        self.root_patch.stop()
        self.tmp.cleanup()

    def client(self, handler, **kwargs):
        client = provider.Provider(self.root / kwargs.pop("directory", "run"), allow_paid=True,
                                   keys=kwargs.pop("keys", KEYS), transport=httpx.MockTransport(handler),
                                   sleep=lambda seconds: None, **kwargs)
        self.clients.append(client)
        return client

    def test_explicit_paid_flag_precedes_credentials_or_directory_creation(self):
        with self.assertRaises(provider.ProviderStop):
            provider.Provider(self.root / "must-not-exist")
        self.credential_mock.assert_not_called()
        self.assertFalse((self.root / "must-not-exist").exists())

    def test_fixed_provider_routing_and_payload_parameters(self):
        requests = []
        def handler(request):
            requests.append(request)
            return httpx.Response(200, json=chat_body() if request.url.host == "api.zicc.cc" else embed_body())
        client = self.client(handler)
        self.assertEqual(client.chat(MESSAGES), '{"ok":true}')
        self.assertEqual(len(client.embed(["cooked rice"])[0]), 3072)
        chat, embedding = requests
        self.assertEqual(str(chat.url), provider.CHAT_URL)
        self.assertEqual(chat.headers["Authorization"], "Bearer " + KEYS[0])
        self.assertNotIn(KEYS[1], str(chat.headers))
        payload = json.loads(chat.content)
        self.assertEqual(payload["model"], "gpt-6.1-sol")
        self.assertEqual(payload["temperature"], 1)
        self.assertEqual(payload["max_completion_tokens"], 4096)
        self.assertNotIn("max_tokens", payload)
        self.assertEqual(str(embedding.url), provider.EMBED_URL)
        self.assertEqual(embedding.headers["Authorization"], "Bearer " + KEYS[1])
        self.assertNotIn(KEYS[0], str(embedding.headers))
        self.assertEqual(json.loads(embedding.content), {"model": "text-embedding-3-large",
                         "input": ["cooked rice"], "encoding_format": "float"})

    def test_served_model_mismatch_stops_and_does_not_cache(self):
        client = self.client(lambda request: httpx.Response(200, json=chat_body(model="wrong-model")))
        with self.assertRaises(provider.ProviderStop):
            client.chat(MESSAGES)
        self.assertFalse(list((self.root / "runtime_cache/responses").rglob("*.json")))

    def test_embedding_wrong_model_stops(self):
        client = self.client(lambda request: httpx.Response(200, json=embed_body(model="other-embedding")))
        with self.assertRaises(provider.ProviderStop):
            client.embed(["rice"])

    def test_embeddings_validate_dimensions_numbers_and_nonzero(self):
        invalid = [[1.] * 3071, [1.] * 3073, [0.] * 3072,
                   [True] + [1.] * 3071, ["1"] + [1.] * 3071,
                   [float("nan")] + [1.] * 3071, [float("inf")] + [1.] * 3071]
        for index, vector in enumerate(invalid):
            with self.subTest(index=index):
                # JSON string deliberately permits invalid numeric constants
                # to verify that the adapter does not trust a provider body.
                body = json.dumps(embed_body(vector))
                client = self.client(lambda request, text=body: httpx.Response(200, text=text),
                                     directory=f"bad-embedding-{index}")
                with self.assertRaises(provider.ProviderStop):
                    client.embed([f"rice-{index}"])

    def test_no_corpus_or_empty_embedding_requests(self):
        calls = []
        client = self.client(lambda request: calls.append(request))
        for queries in ([], "rice", ["rice"] * 13, [""], ["x" * 12001], [None]):
            with self.assertRaises(provider.ProviderStop):
                client.embed(queries)
        self.assertEqual(calls, [])

    def test_response_cache_reuses_and_namespace_separates_chat(self):
        calls = []
        def handler(request):
            calls.append(request)
            return httpx.Response(200, json=chat_body() if request.url.host == "api.zicc.cc" else embed_body())
        first = self.client(handler, namespace="development")
        self.assertEqual(first.chat(MESSAGES), first.chat(MESSAGES))
        first.embed(["rice"])
        first.embed(["rice"])
        self.assertEqual(len(calls), 2)
        formal = self.client(handler, namespace="validation", directory="formal")
        formal.chat(MESSAGES)
        formal.embed(["rice"])
        self.assertEqual(len(calls), 3)
        self.assertEqual(provider.usage(self.root / "run")["providers"]["chat"]["requests"], 1)
        self.assertEqual(provider.usage(self.root / "formal")["providers"]["embedding"]["requests"], 0)

    def test_tampered_cache_provenance_stops_before_network(self):
        calls = []
        def handler(request):
            calls.append(request)
            return httpx.Response(200, json=chat_body())
        client = self.client(handler)
        client.chat(MESSAGES)
        path = next((self.root / "runtime_cache" / "responses" / "chat").glob("*.json"))
        value = json.loads(path.read_text())
        value["request_hash"] = "wrong"
        path.write_text(json.dumps(value))
        with self.assertRaises(provider.ProviderStop):
            client.chat(MESSAGES)
        self.assertEqual(len(calls), 1)

    def test_cache_content_checksum_and_embedding_shape_are_checked(self):
        calls = []
        def handler(request):
            calls.append(request)
            return httpx.Response(200, json=embed_body())
        client = self.client(handler)
        client.embed(["rice"])
        path = next((self.root / "runtime_cache" / "responses" / "embedding").glob("*.json"))
        saved = json.loads(path.read_text())
        saved["value"] = [1.]
        path.write_text(json.dumps(saved))
        with self.assertRaises(provider.ProviderStop):
            client.embed(["rice"])
        saved["value_hash"] = provider.fingerprint(saved["value"])
        path.write_text(json.dumps(saved))
        with self.assertRaises(provider.ProviderStop):
            client.embed(["rice"])
        self.assertEqual(len(calls), 1)

    def test_malformed_response_envelopes_stop_batch(self):
        bodies = [{"model": provider.CHAT_MODEL, "choices": ["invalid"]},
                  {"model": provider.CHAT_MODEL, "choices": [{"message": "invalid"}]},
                  {"model": provider.CHAT_MODEL, "choices": "invalid"},
                  {"model": provider.EMBED_MODEL, "data": ["invalid"]},
                  {"model": provider.EMBED_MODEL, "data": "invalid"}]
        for index, body in enumerate(bodies):
            client = self.client(lambda request, value=body: httpx.Response(200, json=value),
                                 directory=f"malformed-{index}")
            with self.assertRaises(provider.ProviderStop):
                if body["model"] == provider.CHAT_MODEL:
                    client.chat(MESSAGES)
                else:
                    client.embed(["rice"])

    def test_incomplete_chat_content_uses_repair_contract_without_api_retry(self):
        calls = []
        def handler(request):
            calls.append(request)
            return httpx.Response(200, json=chat_body(finish="length"))
        client = self.client(handler)
        self.assertEqual(client.chat(MESSAGES), "")
        self.assertEqual(len(calls), 1)

    def test_auth_redirect_and_client_errors_stop_without_retry(self):
        for status in (401, 403, 400, 404, 302):
            calls = []
            def handler(request):
                calls.append(request)
                return httpx.Response(status, headers={"Location": "https://example.org/"},
                                      json={"error": {"type": "rejected", "message": KEYS[0]}})
            client = self.client(handler, directory=f"status-{status}", namespace=f"status-{status}")
            with self.assertRaises(provider.ProviderStop):
                client.chat(MESSAGES)
            self.assertEqual(len(calls), 1)
            self.assertNotIn(KEYS[0], (self.root / f"status-{status}" / "requests.jsonl").read_text())

    def test_rate_limit_and_server_faults_stop_after_three_attempts(self):
        for status in (429, 500, 503):
            calls, sleeps = [], []
            def handler(request):
                calls.append(request)
                return httpx.Response(status, json={"error": {"type": "transient"}})
            client = self.client(handler, directory=f"status-{status}", namespace=f"status-{status}")
            client.sleep = sleeps.append
            with self.assertRaises(provider.ProviderStop):
                client.chat(MESSAGES)
            self.assertEqual(len(calls), 3)
            self.assertEqual(sleeps, [2, 8])
            usage = provider.usage(self.root / f"status-{status}")
            self.assertEqual(usage["providers"]["chat"]["errors"], 3)

    def test_transport_failure_stops_without_persisting_exception_message(self):
        calls = []
        def handler(request):
            calls.append(request)
            raise httpx.ConnectError("sensitive " + KEYS[0] + " " + KEYS[1], request=request)
        client = self.client(handler)
        with self.assertRaises(provider.ProviderStop):
            client.chat(MESSAGES)
        self.assertEqual(len(calls), 3)
        text = (self.root / "run" / "requests.jsonl").read_text()
        self.assertNotIn("sensitive", text)
        self.assertTrue(all(key not in text for key in KEYS))
        self.assertEqual(len(text.splitlines()), 3)

    def test_retry_can_recover_only_before_success_then_cache(self):
        calls = []
        def handler(request):
            calls.append(request)
            return httpx.Response(429, json={}) if len(calls) == 1 else httpx.Response(200, json=chat_body())
        client = self.client(handler)
        self.assertEqual(client.chat(MESSAGES), '{"ok":true}')
        self.assertEqual(client.chat(MESSAGES), '{"ok":true}')
        self.assertEqual(len(calls), 2)

    def test_full_masked_and_truncated_key_echoes_are_redacted_everywhere(self):
        echoes = [echo for key in KEYS for echo in (key, key[:8] + "..." + key[-4:],
                                                   key[:8] + "***" + key[-4:], key[:16] + "...")]
        content = json.dumps({"echoes": echoes})
        body = chat_body(content)
        body["usage"]["untrusted_echoes"] = echoes
        client = self.client(lambda request: httpx.Response(200, json=body))
        result = client.chat(MESSAGES)
        text = result + (self.root / "run" / "requests.jsonl").read_text()
        text += next((self.root / "runtime_cache" / "responses" / "chat").glob("*.json")).read_text()
        for echo in echoes:
            self.assertNotIn(echo, text)
        self.assertIn("[REDACTED]", text)
        self.assertIsInstance(json.loads(result), dict)

    def test_non_sk_credentials_are_redacted_through_transport_return_ledger_and_cache(self):
        echoes = [echo for key in NON_SK_KEYS for echo in (
            key, key[:8] + "..." + key[-4:], key[:8] + "***" + key[-4:],
            key[:8] + "...", key[:16] + "...", key[:-1] + "...",
            key[:16] + "…", key[:16] + "***")]
        business = {"food_code": "12345678", "grams": 1234, "energy": 9876.0,
                    "short_suffixes": [key[-4:] for key in NON_SK_KEYS],
                    "unmarked_prefixes": [key[:16] for key in NON_SK_KEYS],
                    "unrelated_descriptions": [key[:8] + "ordinary food..." for key in NON_SK_KEYS],
                    "flags": [True, False, None], "items": [{"item_id": "item-1", "grams": 42.5}]}
        nested = [{key[:16] + "...": {key[:8] + "..." + key[-4:]: key}}
                  for key in NON_SK_KEYS]
        payload = {"echoes": echoes, "nested": nested, "business": business}
        expected = {"echoes": ["[REDACTED]"] * len(echoes),
                    "nested": [{"[REDACTED]": {"[REDACTED]": "[REDACTED]"}}] * 2,
                    "business": business}
        calls = []
        def handler(request):
            calls.append(request)
            self.assertEqual(request.headers["Authorization"], "Bearer " + NON_SK_KEYS[0])
            body = chat_body(json.dumps(payload))
            body["usage"]["provider_note"] = payload
            return httpx.Response(200, json=body)
        client = self.client(handler, keys=NON_SK_KEYS)
        result = client.chat(MESSAGES)
        self.assertEqual(json.loads(result), expected)
        ledger_path = self.root / "run" / "requests.jsonl"
        ledger = json.loads(ledger_path.read_text())
        self.assertEqual(ledger["usage"]["provider_note"], expected)
        self.assertEqual(ledger["usage"]["total_tokens"], 12)
        cache_path = next((self.root / "runtime_cache" / "responses" / "chat").glob("*.json"))
        cached = json.loads(cache_path.read_text())
        self.assertEqual(cached["value"], result)
        self.assertEqual(cached["value_hash"], provider.fingerprint(result))
        for text in (result, ledger_path.read_text(), cache_path.read_text()):
            for echo in echoes:
                self.assertNotIn(echo, text)
                self.assertNotIn(json.dumps(echo)[1:-1], text)
        self.assertEqual(client.chat(MESSAGES), result)
        self.assertEqual(len(calls), 1)
        self.assertEqual(len(ledger_path.read_text().splitlines()), 1)
        self.credential_mock.assert_not_called()

    def test_known_prefix_truncation_markers_preserve_surrounding_business_text(self):
        for key in NON_SK_KEYS:
            for marker in ("...", "....", "…", "……", "\\u2026", "***"):
                with self.subTest(marker=marker):
                    value = f"Credential ({key[:16]}{marker}); serving 1234 g, code 9876."
                    self.assertEqual(provider.sanitize(value, NON_SK_KEYS),
                                     "Credential ([REDACTED]); serving 1234 g, code 9876.")
            self.assertEqual(provider.sanitize(key[:16] + ".", NON_SK_KEYS), key[:16] + ".")
            self.assertEqual(provider.sanitize(key[:16] + "..", NON_SK_KEYS), key[:16] + "..")

    def test_remote_image_rejected_before_any_request(self):
        calls = []
        client = self.client(lambda request: calls.append(request))
        for url in ("https://example.org/image.png", "http://127.0.0.1/private", "file:///tmp/image.png"):
            messages = [{"role": "user", "content": [{"type": "image_url", "image_url": {"url": url}}]}]
            with self.assertRaises(provider.ProviderStop):
                client.chat(messages)
        self.assertEqual(calls, [])

    def test_local_inline_image_is_forwarded(self):
        calls = []
        def handler(request):
            calls.append(request)
            return httpx.Response(200, json=chat_body())
        client = self.client(handler)
        messages = [{"role": "user", "content": [{"type": "image_url", "image_url": {"url": "data:image/png;base64,FAKE"}}]}]
        client.chat(messages)
        self.assertEqual(json.loads(calls[0].content)["messages"], messages)

    def test_usage_keeps_reasoning_inside_completion_and_estimates_official_only(self):
        client = self.client(lambda request: httpx.Response(200, json=chat_body() if request.url.host == "api.zicc.cc" else embed_body()))
        client.chat(MESSAGES)
        client.embed(["rice"])
        result = provider.usage(self.root / "run")
        self.assertEqual(result["providers"]["chat"]["total_tokens"], 12)
        self.assertEqual(result["providers"]["chat"]["completion_tokens"], 4)
        self.assertEqual(result["providers"]["chat"]["reasoning_tokens"], 2)
        self.assertIsNone(result["third_party_cost_usd"])
        self.assertEqual(result["official_embedding_estimated_usd"], 7 * .13 / 1e6)

    def test_output_scope_and_distinct_credentials(self):
        with self.assertRaises(ValueError):
            provider.Provider(self.root.parent / "outside-synthetic-root", allow_paid=True, keys=KEYS)
        with self.assertRaises(provider.ProviderStop):
            provider.Provider(self.root / "bad-keys", allow_paid=True, keys=(KEYS[0], KEYS[0]))


class CredentialConfigTests(unittest.TestCase):
    def test_authorized_fixed_bases_are_accepted_without_reading_env_file(self):
        values = {"OPENAI_BASE_URL": "https://api.zicc.cc/v1", "EMBEDDING_BASE_URL": "https://api.openai.com/v1",
                  "CHAT_MODEL": provider.CHAT_MODEL, "VISION_MODEL": provider.CHAT_MODEL,
                  "OPENAI_API_KEY": KEYS[0], "EMBEDDING_API_KEY": KEYS[1]}
        with patch("dotenv.dotenv_values", return_value=values) as read:
            self.assertEqual(provider.read_credentials(), KEYS)
            self.assertFalse(read.call_args.kwargs["interpolate"])

    def test_bad_provider_or_model_configuration_rejected(self):
        values = {"OPENAI_BASE_URL": "https://api.zicc.cc/v1", "EMBEDDING_BASE_URL": "https://api.openai.com/v1",
                  "CHAT_MODEL": provider.CHAT_MODEL, "VISION_MODEL": provider.CHAT_MODEL,
                  "OPENAI_API_KEY": KEYS[0], "EMBEDDING_API_KEY": KEYS[1]}
        for field in ("OPENAI_BASE_URL", "EMBEDDING_BASE_URL", "CHAT_MODEL", "VISION_MODEL"):
            bad = {**values, field: "different"}
            with patch("dotenv.dotenv_values", return_value=bad):
                with self.assertRaises(provider.ProviderStop):
                    provider.read_credentials()


if __name__ == "__main__":
    unittest.main()
