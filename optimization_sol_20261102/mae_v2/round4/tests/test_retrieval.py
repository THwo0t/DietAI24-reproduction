"""Pure synthetic cosine/group/hash isolation tests; no real data or API."""
from copy import deepcopy
from dataclasses import replace
import hashlib
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import retrieval as r


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def entry(sid, group=None):
    return {"train_id": sid, "screening_group_id": group or "g_" + sid,
            "image_sha256": digest("bytes:" + sid), "rgb_sha256": digest("pixels:" + sid)}


def vector(x=1., y=0.):
    v = np.zeros(r.DIMENSIONS)
    v[:2] = x, y
    return v


def fixture(n=16):
    entries = [entry(f"t{i:02}") for i in range(n)]
    vectors = {row["train_id"]: vector() for row in entries}
    exclusions = {key: set() for key in r.EXCLUSION_KEYS}
    return entries, vectors, exclusions


class RetrievalTests(unittest.TestCase):
    def test_cosine_before_id_and_group_dedup_before_top_twelve(self):
        rows, vectors, exclusions = fixture(13)
        rows[0]["screening_group_id"] = "many"
        vectors["t00"] = vector(0., 1.)
        # More than k high-scoring images in one group must not fill top k.
        for i in range(20):
            member = entry(f"a{i:02}", "many")
            rows.append(member)
            vectors[member["train_id"]] = vector(1., 0.1 if i else 0.)
        result = r.retrieve(r.build_index(rows, vectors), vector(), exclusions)
        self.assertEqual([e["train_id"] for e in result], ["a00"] + [f"t{i:02}" for i in range(1, 12)])
        self.assertEqual(len({e["screening_group_id"] for e in result}), 12)
        self.assertEqual([e["rank"] for e in result], list(range(1, 13)))
        self.assertEqual(result, r.retrieve(r.build_index(rows[::-1], dict(reversed(list(vectors.items())))),
                                           vector(), exclusions))

    def test_each_opaque_exclusion_channel_blocks_entire_associated_group(self):
        rows, vectors, exclusions = fixture(17)
        rows.append(entry("alternate", rows[0]["screening_group_id"]))
        vectors["alternate"] = vector()
        channels = {"train_ids": rows[0]["train_id"], "screening_group_ids": rows[0]["screening_group_id"],
                    "image_sha256": rows[0]["image_sha256"], "rgb_sha256": rows[0]["rgb_sha256"]}
        index = r.build_index(rows, vectors)
        for channel, value in channels.items():
            denied = deepcopy(exclusions)
            denied[channel].add(value)
            with self.subTest(channel=channel):
                result = r.retrieve(index, vector(), denied)
                self.assertNotIn(rows[0]["screening_group_id"], {e["screening_group_id"] for e in result})
                self.assertNotIn("alternate", {e["train_id"] for e in result})

    def test_fixed_k_and_insufficient_groups_fail_without_relaxation(self):
        rows, vectors, exclusions = fixture(12)
        index = r.build_index(rows, vectors)
        for k in (0, 4, 11, 13, True, 12.):
            with self.subTest(k=k), self.assertRaisesRegex(r.RetrievalError, "exactly_twelve"):
                r.retrieve(index, vector(), exclusions, k=k)
        exclusions["train_ids"].add(rows[0]["train_id"])
        with self.assertRaisesRegex(r.RetrievalError, "fewer_than_twelve"):
            r.retrieve(index, vector(), exclusions)

    def test_all_vectors_validated_even_for_excluded_rows(self):
        rows, vectors, exclusions = fixture()
        exclusions["train_ids"].add(rows[-1]["train_id"])
        bad = vector(); bad[-1] = float("nan")
        vectors[rows[-1]["train_id"]] = bad
        with self.assertRaisesRegex(r.RetrievalError, "nonfinite"):
            r.build_index(rows, vectors)

    def test_wrong_dimension_nonfinite_zero_bool_and_nonnumeric_vectors_rejected(self):
        rows, vectors, exclusions = fixture()
        index = r.build_index(rows, vectors)
        bad = [np.ones(3071), np.ones((1, 3072)), np.zeros(3072),
               np.full(3072, np.nan), np.full(3072, np.inf), np.ones(3072, dtype=bool),
               [True] + [0.] * 3071, ["1"] * 3072, [10**1000] + [0.] * 3071]
        for value in bad:
            with self.subTest(shape=np.shape(value)):
                with self.assertRaises(r.RetrievalError):
                    r.retrieve(index, value, exclusions)
                altered = dict(vectors); altered[rows[-1]["train_id"]] = value
                with self.assertRaises(r.RetrievalError):
                    r.build_index(rows, altered)

    def test_missing_extra_vectors_rows_fields_and_duplicate_images_rejected(self):
        rows, vectors, _ = fixture()
        for change in ("missing", "extra"):
            altered = dict(vectors)
            if change == "missing":
                altered.pop(rows[0]["train_id"])
            else:
                altered["new"] = vector()
            with self.assertRaisesRegex(r.RetrievalError, "population"):
                r.build_index(rows, altered)
        bad_rows = []
        for field in ("image_sha256", "rgb_sha256", "train_id"):
            altered = deepcopy(rows); altered[0][field] = altered[1][field]; bad_rows.append(altered)
        for field in ("truth", "image_path", "fold", "label"):
            altered = deepcopy(rows); altered[0][field] = "SENTINEL_TRUTH"; bad_rows.append(altered)
        altered = deepcopy(rows); del altered[0]["rgb_sha256"]; bad_rows.append(altered)
        altered = deepcopy(rows); altered[0]["image_sha256"] = "invalid"; bad_rows.append(altered)
        for value in bad_rows:
            with self.assertRaises(r.RetrievalError):
                r.build_index(value, vectors)

    def test_explicit_exclusions_reject_unknown_fields_bad_types_and_hashes(self):
        rows, vectors, exclusions = fixture()
        index = r.build_index(rows, vectors)
        bad = [{}, None, {**exclusions, "query_truth": "SENTINEL_TRUTH"},
               {**exclusions, "train_ids": "t00"}, {**exclusions, "image_sha256": ["bad"]},
               {**exclusions, "screening_group_ids": [True]}]
        for value in bad:
            with self.subTest(value=value), self.assertRaises(r.RetrievalError):
                r.retrieve(index, vector(), value)

    def test_index_copy_normalization_and_no_input_or_output_alias_mutation(self):
        rows, vectors, exclusions = fixture()
        vectors[rows[0]["train_id"]] = vector(1e308, 1e308)
        before_rows, before_vectors = deepcopy(rows), deepcopy(vectors)
        index = r.build_index(rows, vectors)
        self.assertFalse(index.vectors.flags.writeable)
        self.assertEqual(rows, before_rows)
        for key in vectors:
            np.testing.assert_array_equal(vectors[key], before_vectors[key])
        baseline = r.retrieve(index, vector(), exclusions)
        rows[0]["screening_group_id"] = "changed"
        vectors[rows[0]["train_id"]][:] = 0
        changed_result = r.retrieve(index, vector(), exclusions)
        self.assertEqual(baseline, changed_result)
        changed_result[0]["train_id"] = "changed_output"
        self.assertEqual(baseline, r.retrieve(index, vector(), exclusions))

    def test_supplied_index_is_revalidated_and_corruption_rejected(self):
        rows, vectors, exclusions = fixture()
        index = r.build_index(rows, vectors)
        corrupt = index.vectors.copy(); corrupt[-1, 0] = np.nan
        with self.assertRaises(r.RetrievalError):
            r.retrieve(replace(index, vectors=corrupt), vector(), exclusions)
        with self.assertRaises(r.RetrievalError):
            r.retrieve(replace(index, version="different"), vector(), exclusions)
        with self.assertRaises(r.RetrievalError):
            r.retrieve(replace(index, vectors=index.vectors[:-1]), vector(), exclusions)

    def test_cosine_normalizes_query_and_gallery_without_files_or_network(self):
        rows, vectors, exclusions = fixture()
        vectors["t00"] = vector(3., 4.)
        with patch("builtins.open", side_effect=AssertionError("file access")), patch("socket.socket", side_effect=AssertionError("network access")):
            index = r.build_index(rows, vectors)
            result = r.retrieve(index, vector(6., 8.), exclusions)
        self.assertEqual(result[0]["train_id"], "t00")
        self.assertAlmostEqual(result[0]["cosine"], 1.0)
        self.assertAlmostEqual(result[1]["cosine"], .6)
        self.assertEqual(set(result[0]), r.ENTRY_KEYS | {"rank", "cosine"})


if __name__ == "__main__":
    unittest.main()
