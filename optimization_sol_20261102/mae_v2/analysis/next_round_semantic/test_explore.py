"""Synthetic tests of production isolation/median code; no private data or API."""
from copy import deepcopy
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch

import numpy as np

spec = importlib.util.spec_from_file_location("semantic_explore", Path(__file__).with_name("explore.py"))
e = importlib.util.module_from_spec(spec)
spec.loader.exec_module(e)


def row(sid, fold, group=None):
    return {"sample_id": sid, "dataset": "nutrition5k", "split": "dev",
            "group_id": group or sid + "_g", "fold": fold}


def vec(weight=100., energy=100., fat=10., carbs=20., protein=30.):
    return dict(zip(e.KEYS, (weight, energy, fat, carbs, protein)))


def fixture():
    rows = [row(f"s{i:02}", i % 5) for i in range(25)]
    labels = {r["sample_id"]: {"truth": vec(100. + i, 200. + i * 2, 5. + i, 10. + i, 15. + i)}
              for i, r in enumerate(rows)}
    raw = [{**{k: r[k] for k in ("sample_id", "dataset", "group_id", "fold")},
            "raw_prediction": vec(200. + i),
            "raw_leaves": [{"code": "11111111", "grams": 25. + i},
                           {"code": "22222222", "grams": 5.}]} for i, r in enumerate(rows)]
    features = e.build_features(rows, raw, ["11111111", "22222222"], np.eye(2))
    return rows, features, raw, labels


class SemanticTests(unittest.TestCase):
    def test_group_max_before_topk_and_crossfold_group_is_excluded(self):
        rows = [row("q", 0, "qg"), row("samefold", 0), row("samegroup", 2, "qg"),
                row("a_low", 1, "ag"), row("z_high", 1, "ag"), row("b", 2), row("c", 3)]
        # Enough leading duplicate-group members to break top-k-before-dedup.
        rows += [row(f"dup{i:02}", 1, "ag") for i in range(10)]
        features = {r["sample_id"]: np.array([1., 0.]) for r in rows}
        features["a_low"] = np.array([0., 1.])
        for r in rows:
            if r["sample_id"].startswith("dup"):
                features[r["sample_id"]] = np.array([.8, .6])
        expected = [("b", 1.), ("c", 1.), ("z_high", 1.)]
        self.assertEqual(e.rank_neighbors(rows, features, "q", 3), expected)
        self.assertEqual(e.rank_neighbors(rows[::-1], features, "q", 3), expected)
        with self.assertRaisesRegex(ValueError, "Insufficient"):
            e.rank_neighbors(rows, features, "q", 7)

    def test_full_heldout_truth_mutation_cannot_change_its_predictions(self):
        rows, features, raw, labels = fixture()
        original, isolation = e.predict_all(rows, features, raw, labels)
        changed = deepcopy(labels)
        for r in rows:
            if r["fold"] == 0:
                changed[r["sample_id"]]["truth"] = vec(1e8, 2e8, 3e8, 4e8, 5e8)
        altered, isolation2 = e.predict_all(rows, features, raw, changed)
        self.assertEqual(isolation, isolation2)
        for name, *_ in e.SPECS:
            for before, after in zip(original[name], altered[name]):
                if before["fold"] == 0:
                    self.assertEqual(before, after)
        # Positive control: changing actual training references affects estimates.
        changed = deepcopy(labels)
        for r in rows:
            if r["fold"] != 0:
                changed[r["sample_id"]]["truth"] = vec(1e5, 2e5, 3e4, 4e4, 5e4)
        affected, _ = e.predict_all(rows, features, raw, changed)
        for name, *_ in e.SPECS:
            self.assertNotEqual(original[name][0]["prediction"], affected[name][0]["prediction"])

    def test_narrow_boundary_rejects_query_labels_samefold_and_samegroup(self):
        rows, _, raw, labels = fixture()
        q, neighbors = rows[0], [rows[1], rows[2], rows[3]]
        train = {r["sample_id"]: labels[r["sample_id"]] for r in neighbors}
        e.predict_query(q, neighbors, train, raw[0]["raw_prediction"], "A", False)
        with self.assertRaisesRegex(ValueError, "isolated"):
            e.predict_query(q, neighbors, {**train, q["sample_id"]: labels[q["sample_id"]]}, raw[0]["raw_prediction"], "A", False)
        for field, value in (("fold", q["fold"]), ("group_id", q["group_id"]), ("group_id", neighbors[1]["group_id"])):
            altered = deepcopy(neighbors)
            altered[0][field] = value
            with self.subTest(field=field, value=value), self.assertRaisesRegex(ValueError, "isolated"):
                e.predict_query(q, altered, train, raw[0]["raw_prediction"], "B", True)

    def test_B_uses_median_individual_density_not_ratio_of_medians(self):
        q, neighbors = row("q", 0), [row("a", 1), row("b", 2), row("c", 3)]
        train = {r["sample_id"]: {"truth": vec(w, en, en, en, en)}
                 for r, w, en in zip(neighbors, (100., 200., 300.), (10., 1000., 60.))}
        raw = vec(400., 200., 20., 40., 60.)
        a = e.predict_query(q, neighbors, train, raw, "A", False)
        b = e.predict_query(q, neighbors, train, raw, "B", False)
        self.assertEqual(a, vec(200., 60., 60., 60., 60.))
        self.assertEqual(b, vec(200., 40., 40., 40., 40.))
        for family, base in (("A", a), ("B", b)):
            blended = e.predict_query(q, neighbors, train, raw, family, True)
            self.assertEqual(blended, {k: .5 * base[k] + .5 * raw[k] for k in e.KEYS})

    def test_invalid_training_row_and_missing_features_fail_not_drop(self):
        rows, features, raw, labels = fixture()
        neighbors = rows[1:4]
        for bad in (0., -1., float("nan"), float("inf"), True):
            train = {r["sample_id"]: deepcopy(labels[r["sample_id"]]) for r in neighbors}
            train[neighbors[0]["sample_id"]]["truth"]["weight"] = bad
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                e.predict_query(rows[0], neighbors, train, raw[0]["raw_prediction"], "A", False)
        del features[rows[-1]["sample_id"]]
        with self.assertRaisesRegex(ValueError, "Complete"):
            e.rank_neighbors(rows, features, rows[0]["sample_id"], 3)
        with self.assertRaisesRegex(ValueError, "Complete"):
            e.predict_all(rows, features, raw[:-1], labels)

    def test_fixed_12_full_population_no_io_and_raw_inputs_unmodified(self):
        rows, features, raw, labels = fixture()
        before = deepcopy((rows, raw, labels))
        with patch("builtins.open", side_effect=AssertionError("file access")), patch("socket.socket", side_effect=AssertionError("network access")):
            outputs, isolation = e.predict_all(rows, features, raw, labels)
        self.assertEqual(len(outputs), 12)
        self.assertTrue(all(len(records) == len(rows) for records in outputs.values()))
        self.assertEqual(set(outputs), {name for name, *_ in e.SPECS})
        self.assertEqual((rows, raw, labels), before)
        self.assertEqual(isolation["same_fold_neighbors"], 0)
        for k in e.KS:
            self.assertEqual(isolation["by_k"][str(k)]["distinct_groups_per_query"], k)

    def test_feature_build_and_rank_ignore_calibrated_vectors_and_truth(self):
        rows, features, raw, labels = fixture()
        baseline = e.rank_neighbors(rows, features, rows[0]["sample_id"], 7)
        for r, p in zip(rows, raw):
            r["truth"] = object()
            p["prediction"] = vec(9e8)
            p["calibrated_leaves"] = [{"code": "22222222", "grams": 9e8}]
            p["error"] = float("nan")
        altered = e.build_features(rows, raw, ["11111111", "22222222"], np.eye(2))
        self.assertEqual(e.rank_neighbors(rows, altered, rows[0]["sample_id"], 7), baseline)

    def test_scoring_full_denominator_and_per_unit_definition(self):
        rows = [row("a", 0), row("b", 1)]
        labels = {"a": {"truth": vec(10., 10.)}, "b": {"truth": vec(30., 30.)}}
        preds = [{**r, "prediction": vec(20., 20.), "final_codes": [], "primary_code": None} for r in rows]
        score = e.score(rows, labels, preds)
        self.assertEqual(score["n"], 2)
        self.assertEqual(score["metrics"]["weight"]["mae"], 10.)
        self.assertEqual(score["metrics"]["weight"]["per_unit"], .5)
        with self.assertRaises(ValueError):
            e.score(rows, labels, preds[:1])


if __name__ == "__main__":
    unittest.main()
