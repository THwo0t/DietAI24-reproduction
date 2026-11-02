"""Pure synthetic support-selection checks: no private data or API use."""
from copy import deepcopy
import inspect
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from examples import SelectionError, build_features, select_examples


def fixture():
    rows = [{"sample_id": sid, "dataset": "nutrition5k", "split": "dev",
             "group_id": group, "fold": fold}
            for sid, group, fold in [("q", "qg", 0), ("a", "ag", 1),
                                    ("b", "bg", 2), ("c", "cg", 3), ("d", "dg", 4),
                                    ("e", "eg", 1), ("samefold", "fg", 0),
                                    ("samegroup", "qg", 2), ("a_duplicate", "ag", 1)]]
    predictions = [{**{k: r[k] for k in ("sample_id", "dataset", "group_id", "fold")},
                    "raw_prediction": {"weight": 10., "energy": 3., "fat": 1., "carbs": 1., "protein": 1.},
                    "raw_leaves": [{"code": "11111111", "grams": 10.}]}
                   for r in rows]
    return rows, predictions, ["11111111", "22222222"], np.array([[1., 0.], [0., 1.]])


class ExampleSelectorTests(unittest.TestCase):
    def test_excludes_query_fold_and_group_selects_distinct_groups(self):
        rows, preds, codes, vectors = fixture()
        result = select_examples(rows, preds, codes, vectors, "q")
        self.assertEqual(result, ["a", "b", "c", "d"])
        by_id = {r["sample_id"]: r for r in rows}
        self.assertEqual(len({by_id[s]["group_id"] for s in result}), 4)
        self.assertTrue(all(by_id[s]["fold"] != 0 and by_id[s]["group_id"] != "qg" for s in result))

    def test_ties_stable_under_row_and_prediction_reordering(self):
        rows, preds, codes, vectors = fixture()
        first = select_examples(rows, preds, codes, vectors, "q")
        self.assertEqual(first, select_examples(rows[::-1], preds[::-1], codes, vectors, "q"))

    def test_cosine_ranks_before_id_and_one_per_group(self):
        rows, preds, codes, vectors = fixture()
        for p in preds:
            if p["sample_id"] in ("a", "b"):
                p["raw_leaves"][0]["code"] = "22222222"
        # The duplicate of a wins its group by cosine; b is worse than e.
        self.assertEqual(select_examples(rows, preds, codes, vectors, "q"), ["a_duplicate", "c", "d", "e"])

    def test_mass_weighted_mean_uses_raw_leaves(self):
        rows, preds, codes, vectors = fixture()
        preds[0]["raw_leaves"] = [{"code": codes[0], "grams": 3.}, {"code": codes[1], "grams": 4.}]
        preds[0]["calibrated_leaves"] = [{"code": codes[0], "grams": 900.}]
        features = build_features(rows, preds, codes, vectors)
        np.testing.assert_allclose(features["q"], [.6, .8], atol=1e-15)

    def test_changed_labels_errors_and_valid_raw_values_cannot_change_ranking(self):
        rows, preds, codes, vectors = fixture()
        first = select_examples(rows, preds, codes, vectors, "q")
        for r, p in zip(rows, preds):
            r["truth"] = {"weight": float("nan")}
            r["label"] = object()
            p["truth"] = object()
            p["error"] = -99999
            p["prediction"] = {"weight": float("nan")}
            p["raw_prediction"]["energy"] = 999999.
        self.assertEqual(first, select_examples(rows, preds, codes, vectors, "q"))
        self.assertNotIn("labels", inspect.signature(select_examples).parameters)

    def test_no_input_mutation(self):
        args = fixture()
        rows, preds, codes, vectors = deepcopy(args)
        select_examples(*args, "q")
        self.assertEqual(args[0], rows)
        self.assertEqual(args[1], preds)
        self.assertEqual(args[2], codes)
        np.testing.assert_array_equal(args[3], vectors)

    def test_count_is_fixed_four(self):
        for value in (0, 3, 5, True, 4.0):
            with self.subTest(value=value), self.assertRaises(SelectionError):
                select_examples(*fixture(), "q", count=value)

    def test_missing_query_or_prediction_fails(self):
        with self.assertRaisesRegex(SelectionError, "query_row_missing"):
            select_examples(*fixture(), "absent")
        rows, preds, codes, vectors = fixture()
        with self.assertRaisesRegex(SelectionError, "missing_raw_prediction_row"):
            select_examples(rows, preds[:-1], codes, vectors, "q")

    def test_fewer_than_four_groups_fails_without_relaxing(self):
        rows, preds, codes, vectors = fixture()
        for r, p in zip(rows, preds):
            if r["sample_id"] in ("d", "e"):
                r["fold"] = p["fold"] = 0
        with self.assertRaisesRegex(SelectionError, "fewer_than_four_eligible_training_groups"):
            select_examples(rows, preds, codes, vectors, "q")

    def test_duplicate_rows_and_prediction_binding_rejected(self):
        rows, preds, codes, vectors = fixture()
        with self.assertRaises(SelectionError):
            select_examples(rows + [rows[0]], preds, codes, vectors, "q")
        with self.assertRaises(SelectionError):
            select_examples(rows, preds + [preds[0]], codes, vectors, "q")
        preds[0]["group_id"] = "wrong"
        with self.assertRaisesRegex(SelectionError, "raw_prediction_row_binding_mismatch"):
            select_examples(rows, preds, codes, vectors, "q")

    def test_bad_vectors_and_code_inventory_rejected(self):
        rows, preds, codes, _ = fixture()
        for vectors in (np.eye(3), np.ones(2), np.zeros((2, 2)), [[1., 0.], [0., float("nan")]], [[1., 0.], [float("inf"), 1.]], [["x", "y"], ["a", "b"]]):
            with self.subTest(vectors=str(vectors)), self.assertRaises(SelectionError):
                select_examples(rows, preds, codes, vectors, "q")
        with self.assertRaises(SelectionError):
            select_examples(rows, preds, [codes[0], codes[0]], np.eye(2), "q")

    def test_bad_leaf_code_mass_or_zero_total_rejected(self):
        for alteration in ({"code": "99999999"}, {"grams": float("nan")}, {"grams": float("inf")}, {"grams": -1}, {"grams": True}, {"grams": 0}, {"grams": "10"}, {"grams": 10**1000}):
            rows, preds, codes, vectors = fixture()
            preds[1]["raw_leaves"][0].update(alteration)
            with self.subTest(alteration=alteration), self.assertRaises(SelectionError):
                select_examples(rows, preds, codes, vectors, "q")

    def test_complete_raw_prediction_required_even_for_excluded_rows(self):
        for change in ("missing", "nan", "zero_weight"):
            rows, preds, codes, vectors = fixture()
            pred = preds[-2]["raw_prediction"]  # excluded same-group row
            if change == "missing":
                del pred["protein"]
            elif change == "nan":
                pred["protein"] = float("nan")
            else:
                pred["weight"] = 0
            with self.subTest(change=change), self.assertRaises(SelectionError):
                select_examples(rows, preds, codes, vectors, "q")

    def test_validation_rows_and_cancelling_feature_rejected(self):
        rows, preds, codes, vectors = fixture()
        rows[-1]["split"] = "val"
        with self.assertRaisesRegex(SelectionError, "nutrition5k_development_rows_required"):
            select_examples(rows, preds, codes, vectors, "q")
        rows, preds, codes, vectors = fixture()
        vectors[1] = [-1, 0]
        preds[0]["raw_leaves"] = [{"code": c, "grams": 1.} for c in codes]
        with self.assertRaisesRegex(SelectionError, "nonfinite_or_zero_dish_feature"):
            select_examples(rows, preds, codes, vectors, "q")

    def test_no_file_or_network_access_during_selection(self):
        args = fixture()
        with patch("builtins.open", side_effect=AssertionError("file access")), patch("socket.socket", side_effect=AssertionError("network access")):
            self.assertEqual(select_examples(*args, "q"), ["a", "b", "c", "d"])


if __name__ == "__main__":
    unittest.main()
