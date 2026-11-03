"""Synthetic-only prefix projection; no images, files, labels or API reads."""
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
from round4.src import pipeline, retrieval, vision_stages
from round4.src.artifacts import fingerprint
from round5.src import verified_j_prefix as prefix

CODE = "ingr_0000000001"
SENTINEL = "QUERY_TRUTH_OR_OLD_ESTIMATE_MUST_NOT_BE_FORWARDED"
DESCRIPTION = json.dumps({"scene": "one foreground serving", "foods": [
    {"appearance": "pale rough pieces with visible fat marbling", "placement": "centre"}],
    "scale_cues": [], "uncertainties": []})


def sha(text):
    return hashlib.sha256(text.encode()).hexdigest()


def vector(value=0.0):
    return [1.0, value] + [0.0] * (retrieval.DIMENSIONS - 2)


def description(repair=False, failed=False):
    if failed:
        try:
            vision_stages._parse_description("bad")
        except ContractError as error:
            failure = str(error)
        return {"raw_outputs": ["bad", "bad"], "parsed": None, "embedding_text": None,
                "repair_used": True, "failure": failure}
    parsed, text = vision_stages._parse_description(DESCRIPTION)
    return {"raw_outputs": (["bad"] if repair else []) + [DESCRIPTION], "parsed": parsed,
            "embedding_text": text, "repair_used": repair, "failure": None}


def rerank(repair=False, failed=False):
    if failed:
        try:
            vision_stages._parse_rerank("bad")
        except ContractError as error:
            failure = str(error)
        return {"raw_outputs": ["bad", "bad"], "selected_ids": None,
                "repair_used": True, "failure": failure}
    ids = ["c4", "c2", "c1", "c3"]
    return {"raw_outputs": (["bad"] if repair else []) + [json.dumps({"selected_ids": ids})],
            "selected_ids": ids, "repair_used": repair, "failure": None}


def fixture(count=2):
    entries, vectors, supports = [], {}, {}
    for i in range(16):
        sid = f"train-{i:02d}"
        entries.append({"train_id": sid, "screening_group_id": "group-" + sid,
                        "image_sha256": sha(sid), "rgb_sha256": sha(sid + "pixels")})
        vectors[sid] = vector(i / 20)
        supports[sid] = {"image_path": f"/synthetic/training/{sid}.png",
                         "ingredients": [{"ingredient_id": CODE, "grams": 50 + i}]}
    gallery = retrieval.build_index(entries, vectors)
    assets = {"scope": "external_train_only", "training_sha256": sha("train-freeze"),
              "catalog": [{"ingredient_id": CODE, "name": "synthetic food", "density_per_100g":
                           {"energy": 120, "fat": 1, "carbs": 25, "protein": 3}}],
              "fallback": {"weight": 100, "energy": 120, "fat": 1, "carbs": 25, "protein": 3},
              "supports": supports, "gallery_entries": entries, "queries": []}
    records = {}
    for i in range(count):
        sid = f"query-{i:02d}"
        query = {"query_id": sid, "image_path": f"/synthetic/query/{sid}.png",
                 "image_sha256": sha(sid), "rgb_sha256": sha(sid + "pixels"),
                 "screening_group_id": "query-group-" + sid}
        assets["queries"].append(query)
        retrieved = retrieval.retrieve(gallery, vector(), {"train_ids": [sid],
            "screening_group_ids": [query["screening_group_id"]],
            "image_sha256": [query["image_sha256"]], "rgb_sha256": [query["rgb_sha256"]]})
        ranked = rerank()
        ids = [retrieved[int(cid[1:]) - 1]["train_id"] for cid in ranked["selected_ids"]]
        records[sid] = {"sample_id": sid, "query_id": sid, "method": pipeline.METHOD_VERSION,
            "stages": {"description": description(), "embedding": {"vector": vector()},
                       "retrieval": retrieved, "rerank": ranked,
                       "estimate": {"not_needed_by_projection": SENTINEL}},
            "audit": {"training_sha256": assets["training_sha256"],
                      "gallery_sha256": sha("normalized-gallery"),
                      "selected_candidate_ids": ranked["selected_ids"], "selected_train_ids": ids},
            "prediction": {"hidden": SENTINEL}, "raw_prediction": {"hidden": SENTINEL},
            "truth": SENTINEL, "fold": 4, "repair_used": False, "fallback": False,
            "method_fallback": False, "failure": None}
    verified = {"status": "base_verified", "n": count, "records": records,
                "binding": {"phase": "development_base", "query_count": count,
                            "training_freeze_sha256": assets["training_sha256"],
                            "gallery_completion_sha256": sha("gallery-completion"),
                            "service_continuation": {"registration_sha256": sha("registration")}},
                "completion_sha256": sha("base-completion"),
                "provider_constructed": False, "validation_opened": False}
    return verified, assets


class VerifiedPrefixTests(unittest.TestCase):
    def test_projection_is_pure_json_and_does_not_mutate_or_alias_inputs(self):
        verified, assets = fixture()
        before = deepcopy((verified, assets))
        with patch("builtins.open", side_effect=AssertionError("no file I/O")), \
             patch.object(Path, "read_bytes", side_effect=AssertionError("no file I/O")), \
             patch.object(Path, "resolve", side_effect=AssertionError("no filesystem resolution")), \
             patch.object(vision_stages, "encode_image", side_effect=AssertionError("no images")):
            result = prefix.extract_prefixes(verified, assets)
        self.assertEqual((verified, assets), before)
        self.assertEqual(result["n"], 2)
        item = result["prefixes"]["query-00"]
        self.assertEqual(set(item["stages"]), set(prefix.UPSTREAM))
        self.assertEqual(item["selected_train_ids"], ["train-03", "train-01", "train-00", "train-02"])
        self.assertEqual(len(item["candidate_images"]), 12)
        self.assertEqual(item["candidate_images"][3]["candidate_id"], "c4")
        self.assertEqual(item["selected_supports"][0], assets["supports"]["train-03"])
        self.assertNotIn(SENTINEL, json.dumps(result, allow_nan=False))
        self.assertNotIn("raw_outputs", json.dumps(result))
        self.assertNotIn("estimate", item["provenance"]["stage_sha256"])
        self.assertEqual(item["provenance"]["stage_sha256"]["rerank"],
                         fingerprint(verified["records"]["query-00"]["stages"]["rerank"]))
        item["selected_supports"][0]["ingredients"][0]["grams"] = 9999
        item["stages"]["embedding"]["vector"][0] = 9
        self.assertEqual((verified, assets), before)

    def test_binding_is_only_a_hash_even_if_it_contains_private_metadata(self):
        verified, assets = fixture(1)
        verified["binding"]["query_labels"] = {"truth": SENTINEL}
        result = prefix.extract_prefixes(verified, assets)
        self.assertNotIn(SENTINEL, json.dumps(result))
        self.assertNotIn("query_labels", json.dumps(result))
        self.assertEqual(result["provenance"]["parent_binding_sha256"], fingerprint(verified["binding"]))

    def test_old_estimate_and_whole_record_failure_flags_have_no_effect(self):
        verified, assets = fixture(1)
        expected = prefix.extract_prefixes(verified, assets)
        record = verified["records"]["query-00"]
        record.update(repair_used=True, fallback=True, method_fallback=True,
                      failure=SENTINEL, prediction=SENTINEL, raw_prediction=SENTINEL)
        record["stages"]["estimate"] = {"raw_outputs": [SENTINEL], "failure": SENTINEL}
        record["audit"]["arbitrary_old_estimate_audit"] = SENTINEL
        self.assertEqual(prefix.extract_prefixes(verified, assets), expected)

    def test_description_and_rerank_repairs_are_preserved_without_forwarding_raw(self):
        for stage in ("description", "rerank"):
            with self.subTest(stage=stage):
                verified, assets = fixture(1)
                verified["records"]["query-00"]["stages"][stage] = globals()[stage](repair=True)
                item = prefix.extract_prefixes(verified, assets)["prefixes"]["query-00"]
                self.assertTrue(item["repair_used"])
                self.assertFalse(item["fallback"] or item["method_fallback"])
                self.assertNotIn("raw_outputs", item["stages"][stage])

    def test_failed_description_is_terminal_no_downstream_stage_or_selected_support(self):
        verified, assets = fixture(1)
        verified["records"]["query-00"]["stages"] = {"description": description(failed=True)}
        item = prefix.extract_prefixes(verified, assets)["prefixes"]["query-00"]
        self.assertTrue(item["repair_used"] and item["fallback"])
        self.assertFalse(item["method_fallback"])
        self.assertTrue(item["failure"].startswith("description:"))
        self.assertEqual(item["selected_supports"], [])
        self.assertTrue(all(item["stages"][key] is None for key in prefix.UPSTREAM[1:]))
        verified["records"]["query-00"]["stages"]["embedding"] = {"vector": vector()}
        with self.assertRaises(ValueError):
            prefix.extract_prefixes(verified, assets)

    def test_failed_rerank_retains_parent_top_four_without_call_or_reselection(self):
        verified, assets = fixture(1)
        record = verified["records"]["query-00"]
        record["stages"]["rerank"] = rerank(failed=True)
        record["audit"]["selected_candidate_ids"] = ["c1", "c2", "c3", "c4"]
        record["audit"]["selected_train_ids"] = [f"train-{i:02d}" for i in range(4)]
        item = prefix.extract_prefixes(verified, assets)["prefixes"]["query-00"]
        self.assertTrue(item["repair_used"] and item["method_fallback"])
        self.assertFalse(item["fallback"])
        self.assertIsNone(item["failure"])
        self.assertEqual(item["selected_candidate_ids"], ["c1", "c2", "c3", "c4"])
        self.assertTrue(item["method_fallback_reason"].startswith("rerank:"))

    def test_selected_ids_must_match_replayed_parent_mapping(self):
        verified, assets = fixture(1)
        verified["records"]["query-00"]["audit"]["selected_train_ids"].reverse()
        with self.assertRaisesRegex(prefix.PrefixError, "parent_selection"):
            prefix.extract_prefixes(verified, assets)

    def test_incomplete_nonreadonly_and_changed_population_rejected(self):
        mutations = [lambda v: v.update(status="base_complete_unscored"),
                     lambda v: v.update(provider_constructed=True),
                     lambda v: v.update(validation_opened=True), lambda v: v.update(n=True),
                     lambda v: v["records"].pop("query-01"),
                     lambda v: v["binding"].update(query_count=84),
                     lambda v: v["binding"].update(training_freeze_sha256=sha("other")),
                     lambda v: v.update(completion_sha256="invalid")]
        for mutate in mutations:
            with self.subTest(mutation=mutate):
                verified, assets = fixture()
                mutate(verified)
                with self.assertRaises(ValueError):
                    prefix.extract_prefixes(verified, assets)

    def test_exact_asset_schemas_reject_query_truth_and_support_extra_fields(self):
        mutations = [lambda a: a["queries"][0].update(truth=SENTINEL),
                     lambda a: a["supports"]["train-00"].update(reference=SENTINEL),
                     lambda a: a["gallery_entries"][0].update(query_labels=SENTINEL),
                     lambda a: a.update(labels=SENTINEL),
                     lambda a: a.update(scope="development_training_fold"),
                     lambda a: a["supports"].pop("train-00")]
        for mutate in mutations:
            with self.subTest(mutation=mutate):
                verified, assets = fixture(1)
                mutate(assets)
                with self.assertRaises(ValueError):
                    prefix.extract_prefixes(verified, assets)

    def test_support_grams_known_id_and_distinct_query_path_validated(self):
        mutations = [lambda a: a["supports"]["train-00"]["ingredients"][0].update(grams=0),
                     lambda a: a["supports"]["train-00"]["ingredients"][0].update(grams=float("nan")),
                     lambda a: a["supports"]["train-00"]["ingredients"][0].update(ingredient_id="unknown"),
                     lambda a: a["queries"][0].update(image_path=a["supports"]["train-00"]["image_path"])]
        for mutate in mutations:
            with self.subTest(mutation=mutate):
                verified, assets = fixture(1)
                mutate(assets)
                with self.assertRaises(ValueError):
                    prefix.extract_prefixes(verified, assets)

    def test_retrieval_image_order_rank_and_group_tampering_rejected(self):
        mutations = [lambda rows: rows[0].update(image_sha256=sha("wrong")),
                     lambda rows: rows.reverse(), lambda rows: rows[0].update(rank=True),
                     lambda rows: rows[0].update(cosine=float("nan")),
                     lambda rows: rows.__setitem__(1, deepcopy(rows[0]))]
        for mutate in mutations:
            with self.subTest(mutation=mutate):
                verified, assets = fixture(1)
                mutate(verified["records"]["query-00"]["stages"]["retrieval"])
                with self.assertRaises(ValueError):
                    prefix.extract_prefixes(verified, assets)

    def test_hash_exclusion_blocks_whole_association_group(self):
        verified, assets = fixture(1)
        # Exclude a non-retrieved image: its group also contains retrieved train-00.
        assets["gallery_entries"][15]["screening_group_id"] = assets["gallery_entries"][0]["screening_group_id"]
        assets["queries"][0]["rgb_sha256"] = assets["gallery_entries"][15]["rgb_sha256"]
        with self.assertRaisesRegex(prefix.PrefixError, "excluded_group"):
            prefix.extract_prefixes(verified, assets)

    def test_stage_raw_and_parsed_drift_and_embedding_faults_rejected(self):
        mutations = [lambda stages: stages["description"]["parsed"].update(scene="changed"),
                     lambda stages: stages["rerank"]["selected_ids"].reverse(),
                     lambda stages: stages["embedding"].update(vector=[1.0]),
                     lambda stages: stages["embedding"]["vector"].__setitem__(0, True),
                     lambda stages: stages.pop("retrieval")]
        for mutate in mutations:
            with self.subTest(mutation=mutate):
                verified, assets = fixture(1)
                mutate(verified["records"]["query-00"]["stages"])
                with self.assertRaises(ValueError):
                    prefix.extract_prefixes(verified, assets)

    def test_no_84_constant_and_deterministic_query_order(self):
        verified, assets = fixture(3)
        expected = prefix.extract_prefixes(verified, assets)
        verified["records"] = dict(reversed(list(verified["records"].items())))
        assets["queries"].reverse()
        self.assertEqual(prefix.extract_prefixes(verified, assets), expected)
        self.assertEqual(list(expected["prefixes"]), ["query-00", "query-01", "query-02"])


if __name__ == "__main__":
    unittest.main()
