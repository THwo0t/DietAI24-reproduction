"""Offline synthetic checks; no provider, files containing labels, or holdout."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import metrics_v2 as m
import opt_metrics as scoring


def vector(weight=100):
    return {"weight": weight, "energy": weight * 2, "fat": weight * .1,
            "carbs": weight * .2, "protein": weight * .1}


def fixture(n=10, dataset="nutrition5k", ratio=1.0, hits=None):
    rows, labels, preds = [], {}, []
    for i in range(n):
        sid = f"{dataset}_{i}"
        code = "12345678"
        rows.append({"sample_id": sid, "dataset": dataset, "group_id": f"g{i}",
                     "fold": i % 2, "split": "dev"})
        labels[sid] = {"truth": vector(), "food_code": code, "split": "dev", "size": "medium"}
        value = vector(100 * ratio)
        p = {"sample_id": sid, "dataset": dataset, "group_id": f"g{i}", "fold": i % 2,
             "final_codes": [], "primary_code": None, "raw_prediction": deepcopy(value),
             "prediction": deepcopy(value), "native_complete": True, "fallback": False}
        if dataset == "asa24":
            exact = hits is None or i < hits
            p.update(final_codes=[code] if exact else [], primary_code=code if exact else None,
                     conditional={"code": code, "prediction": deepcopy(value), "continuous_grams": 100 * ratio,
                                  "option_id": "100", "fallback": False} if exact else None,
                     e2e={"code": code, "prediction": deepcopy(value), "option_id": "100", "fallback": False})
        preds.append(p)
    return rows, labels, preds


OPTIONS = {"12345678": [{"option_id": str(w), "grams": w} for w in [50, 100, 150]]}
DENSITIES = {"12345678": {"energy": 200, "fat": 10, "carbs": 20, "protein": 10}}


def candidate(name, dataset, error=1.0, hits=15, calls=10, order=0):
    rows, labels, preds = fixture(99 if dataset == "asa24" else 10, dataset, hits=hits)
    metrics = m.evaluate(rows, labels, preds)
    for key, thresholds in m.THRESHOLDS[dataset].items():
        metric = metrics["datasets"][dataset]["primary"]["metrics"][key]
        for stat, limit in zip(("mae", "per_unit"), thresholds):
            metric[stat] = error * limit
    return {"name": name, "metrics": metrics, "estimated_chat_calls": calls, "registration_index": order}


class ScoringTests(unittest.TestCase):
    def test_exact_integer_floor_and_recognition_denominator(self):
        self.assertEqual((m.minimum_exact_n(99), m.minimum_exact_n(78)), (15, 12))
        for n, hits, expected in [(99, 15, True), (99, 14, False), (78, 12, True), (78, 11, False)]:
            result = m.evaluate(*fixture(n, "asa24", hits=hits))
            ds = result["datasets"]["asa24"]
            self.assertEqual(ds["n"], n)
            self.assertEqual(result["recognition_pass"], expected)
            self.assertEqual(ds["exact_rate"], hits / n)

    def test_twenty_thresholds_unchanged(self):
        self.assertEqual(m.THRESHOLDS["asa24"]["protein"], (1.794, .3029))
        self.assertEqual(m.THRESHOLDS["nutrition5k"]["weight"], (58.63, .2028))
        ar, al, ap = fixture(2, "asa24")
        nr, nl, np = fixture(2)
        out = m.evaluate(ar + nr, {**al, **nl}, ap + np)
        self.assertEqual((out["passed_checks"], out["total_checks"]), (20, 20))
        self.assertTrue(out["joint_pass"])

    def test_per_unit_is_ratio_of_means_not_mape(self):
        rows, labels, preds = fixture(2)
        labels[rows[0]["sample_id"]]["truth"] = vector(1)
        labels[rows[1]["sample_id"]]["truth"] = vector(100)
        preds[0]["prediction"] = vector(2)
        preds[1]["prediction"] = vector(90)
        v = m.evaluate(rows, labels, preds)["datasets"]["nutrition5k"]["primary"]["metrics"]["weight"]
        self.assertAlmostEqual(v["mae"], 5.5)
        self.assertAlmostEqual(v["per_unit"], 5.5 / 50.5)
        self.assertNotAlmostEqual(v["per_unit"], .55)

    def test_zero_mean_is_undefined_and_missing_never_disappears(self):
        rows, labels, preds = fixture(2)
        for label in labels.values():
            label["truth"] = vector(0)
        out = m.evaluate(rows, labels, preds)
        self.assertIsNone(out["datasets"]["nutrition5k"]["primary"]["metrics"]["weight"]["per_unit"])
        with self.assertRaises(ValueError):
            m.evaluate(rows, labels, preds[:-1])
        preds[0]["prediction"] = None
        with self.assertRaises(ValueError):
            m.evaluate(rows, labels, preds)

    def test_missing_exact_branch_invalidates_population(self):
        rows, labels, preds = fixture(2, "asa24")
        preds[0]["conditional"] = None
        ds = m.evaluate(rows, labels, preds)["datasets"]["asa24"]
        self.assertEqual(ds["primary"]["n"], 2)
        self.assertEqual(ds["conditional_missing_n"], 1)
        self.assertIsNone(ds["primary"]["metrics"]["weight"]["mae"])

    def test_cluster_bootstrap_has_10000_draws_and_preserves_empty_exact(self):
        rows, labels, preds = fixture(2, "asa24", hits=1)
        out = m.evaluate(rows, labels, preds, bootstrap=True)
        boot = out["datasets"]["asa24"]["bootstrap"]
        self.assertEqual((boot["replicates"], boot["group_count"]), (10000, 2))
        self.assertGreater(boot["empty_exact_replicates"], 0)
        self.assertEqual(boot["intervals"]["weight.mae"]["valid_replicates"], 10000 - boot["empty_exact_replicates"])
        self.assertEqual(boot["unit"], "manifest_group_id")

    def test_bootstrap_zero_groups_has_explicit_absent_intervals_without_sampling(self):
        before = m.evaluate([], {}, [])
        with patch.object(scoring.random, "Random", side_effect=AssertionError("must not sample zero groups")):
            after = m.evaluate([], {}, [], bootstrap=100)
        for dataset in scoring.DATASETS:
            boot = after["datasets"][dataset].pop("bootstrap")
            self.assertEqual((boot["group_count"], boot["replicates"], boot["requested_replicates"]), (0, 0, 100))
            self.assertEqual(boot["reason"], "fewer_than_two_groups")
            self.assertIsNone(boot["empty_exact_fraction"])
            for interval in boot["intervals"].values():
                self.assertEqual(interval, {"low": None, "high": None, "valid_replicates": 0})
        self.assertEqual(after, before)

    def test_bootstrap_single_group_suppresses_nutrient_and_recognition_intervals(self):
        for dataset in scoring.DATASETS:
            rows, labels, preds = fixture(3, dataset, ratio=1.1)
            for row in rows:
                row["group_id"] = "one_group"
            before = m.evaluate(rows, labels, preds)
            with patch.object(scoring.random, "Random", side_effect=AssertionError("must not sample one group")):
                after = m.evaluate(rows, labels, preds, bootstrap=100)
            boot = after["datasets"][dataset]["bootstrap"]
            self.assertEqual((boot["group_count"], boot["replicates"]), (1, 0))
            self.assertEqual(boot["reason"], "fewer_than_two_groups")
            self.assertEqual(len(boot["intervals"]), 12 if dataset == "asa24" else 10)
            self.assertIsNone(boot["empty_exact_replicates"])
            for interval in boot["intervals"].values():
                self.assertEqual(interval, {"low": None, "high": None, "valid_replicates": 0})
            for scored_dataset in scoring.DATASETS:
                after["datasets"][scored_dataset].pop("bootstrap")
            self.assertEqual(after, before)
            self.assertAlmostEqual(after["datasets"][dataset]["primary"]["metrics"]["weight"]["mae"], 10)

    def test_bootstrap_resamples_whole_association_groups(self):
        rows, labels, preds = fixture(4)
        for i, row in enumerate(rows):
            row["group_id"] = f"plate{i // 2}"
            preds[i]["prediction"] = vector(100 if i % 2 == 0 else 300)
        boot = m.evaluate(rows, labels, preds, bootstrap=100)["datasets"]["nutrition5k"]["bootstrap"]
        self.assertEqual(boot["group_count"], 2)
        self.assertNotIn("reason", boot)
        self.assertNotIn("requested_replicates", boot)
        self.assertEqual(boot["intervals"]["weight.mae"]["low"], 100)
        self.assertEqual(boot["intervals"]["weight.mae"]["high"], 100)

    def test_fallback_rows_are_scored(self):
        rows, labels, preds = fixture(2)
        preds[1].update(fallback=True, native_complete=False, prediction=vector(300))
        ds = m.evaluate(rows, labels, preds)["datasets"]["nutrition5k"]
        self.assertEqual(ds["primary"]["n"], 2)
        self.assertEqual(ds["native_subset"]["n"], 1)
        self.assertEqual(ds["primary"]["metrics"]["weight"]["mae"], 100)

    def test_complete_subset_includes_repairs_and_method_fallback_is_separate(self):
        rows, labels, preds = fixture(3)
        preds[0].update(native_complete=False, repair_used=True)
        preds[1].update(method_fallback=True)
        preds[2].update(fallback=True, native_complete=False)
        ds = m.evaluate(rows, labels, preds)["datasets"]["nutrition5k"]
        self.assertEqual((ds["complete_n"], ds["complete_subset"]["n"]), (2, 2))
        self.assertEqual((ds["native_subset"]["n"], ds["enhancement_native_n"]), (0, 0))
        self.assertEqual((ds["repair_success_n"], ds["method_fallback_n"], ds["fallback_n"]), (1, 1, 1))


class SelectionTests(unittest.TestCase):
    def test_asa_floor_then_mae_not_hit_count(self):
        invalid = candidate("invalid", "asa24", .01, hits=14, order=0)
        best = candidate("best", "asa24", .5, hits=15, order=1)
        more_hits = candidate("more_hits", "asa24", .8, hits=30, order=2)
        self.assertEqual(m.select_candidate([more_hits, invalid, best], "asa24")["name"], "best")
        self.assertIsNone(m.select_candidate([invalid], "asa24"))

    def test_cost_and_registered_order_are_stable_under_reverse_input(self):
        a = candidate("A", "nutrition5k", .5, calls=2, order=0)
        b = candidate("B", "nutrition5k", .5, calls=1, order=1)
        c = candidate("C", "nutrition5k", .5, calls=1, order=2)
        for candidates in ([a, b, c], [c, b, a]):
            self.assertEqual(m.select_candidate(candidates, "nutrition5k")["name"], "B")
        self.assertEqual(m.select_candidate([b, c], "nutrition5k", registered_order=["C", "B"])["name"], "C")

    def test_reject_calibrated_candidate_and_missing_registry(self):
        c = candidate("A", "nutrition5k")
        c["calibration_enabled"] = True
        with self.assertRaises(ValueError):
            m.select_candidate([c], "nutrition5k")
        c.pop("calibration_enabled")
        c.pop("registration_index")
        with self.assertRaises(ValueError):
            m.select_candidate([c], "nutrition5k")

    def test_profile_selection_accepts_retained_calibration_and_skips_other_dataset(self):
        n5 = candidate("A", "nutrition5k", error=.4, order=1)
        n5["calibration_enabled"] = True
        asa = candidate("ASA", "asa24", error=.3, order=2)
        asa["metrics"]["datasets"].pop("nutrition5k")
        baseline = candidate("baseline", "nutrition5k", error=.8, order=0)
        profile = m.select_profile([asa, n5, baseline], "nutrition5k")
        self.assertEqual(profile["name"], "A")
        self.assertTrue(profile["calibration_enabled"])
        # N5-only has a zero-row ASA entry because evaluate retains both schemas.
        self.assertEqual(m.select_profile([asa, n5, baseline], "asa24")["name"], "ASA")
        with self.assertRaises(ValueError):
            m.select_candidate([asa, n5, baseline], "nutrition5k")
        self.assertEqual(m.select_candidate([asa, n5, baseline], "asa24")["name"], "ASA")

    def test_profile_collection_requires_global_unique_names_and_registrations(self):
        n5 = candidate("A", "nutrition5k", order=0)
        asa = candidate("ASA", "asa24", order=1)
        duplicate = deepcopy(asa)
        duplicate["name"] = "A"
        with self.assertRaises(ValueError):
            m.select_profile([n5, duplicate], "nutrition5k")
        asa["registration_index"] = 0
        with self.assertRaises(ValueError):
            m.select_profile([n5, asa], "nutrition5k")

    def test_calibration_gate_preserves_passing_checks(self):
        raw = candidate("raw", "nutrition5k", 2)["metrics"]
        calibrated = deepcopy(raw)
        for v in calibrated["datasets"]["nutrition5k"]["primary"]["metrics"].values():
            v["mae"] *= .8
            v["per_unit"] *= .8
        self.assertTrue(m.calibration_improves(raw, calibrated, "nutrition5k"))
        raw["datasets"]["nutrition5k"]["primary"]["metrics"]["weight"]["mae"] = 58
        calibrated["datasets"]["nutrition5k"]["primary"]["metrics"]["weight"]["mae"] = 59
        self.assertFalse(m.calibration_improves(raw, calibrated, "nutrition5k"))
        self.assertFalse(m.calibration_improves(raw, raw, "nutrition5k"))


class CalibrationTests(unittest.TestCase):
    def test_factor_grid_and_shrinkage(self):
        rows, labels, preds = fixture(6, ratio=.8)
        fit = m.fit_mass(rows, labels, preds, "nutrition5k")
        self.assertEqual(fit["raw_factor"], 1.25)
        self.assertEqual(fit["mass_factor"], 1.125)
        for p in preds:
            p["raw_prediction"] = p["prediction"] = vector(125)
        fit = m.fit_mass(rows, labels, preds, "nutrition5k")
        self.assertEqual((fit["raw_factor"], fit["mass_factor"]), (.8, .9))

    def test_fit_uses_all_ten_targets_and_millistep_grid(self):
        rows, labels, preds = fixture(6)
        for label in labels.values():
            label["truth"]["protein"] = 20
        # Weight alone is already exact, but protein is the limiting target.
        self.assertEqual(m.fit_mass(rows, labels, preds, "nutrition5k")["raw_factor"], 1.25)
        rows, labels, preds = fixture(6, ratio=1 / 1.037)
        fit = m.fit_mass(rows, labels, preds, "nutrition5k")
        self.assertEqual(fit["raw_factor"], 1.037)
        self.assertAlmostEqual(fit["mass_factor"], 1.0185)

    def test_legacy_entrypoints_cannot_fit_independent_nutrient_factors(self):
        rows, labels, preds = fixture(6, ratio=.8)
        factors = scoring.fit_n5(rows, labels, preds)
        self.assertEqual(set(factors.values()), {1.125})
        factors["protein"] = 1
        with self.assertRaises(ValueError):
            scoring.apply_n5(vector(), factors)

    def test_five_groups_required_not_five_rows(self):
        rows, labels, preds = fixture(6, ratio=.8)
        for row in rows:
            row["group_id"], row["fold"] = "one_plate", 0
        fit = m.fit_mass(rows, labels, preds, "nutrition5k")
        self.assertEqual((fit["eligible_groups"], fit["mass_factor"]), (1, 1))

    def test_fallback_excluded_from_fit_and_group_count(self):
        rows, labels, preds = fixture(6, ratio=.8)
        preds[-1].update(fallback=True, native_complete=False, raw_prediction=vector(10000), prediction=vector(10000))
        fit = m.fit_mass(rows, labels, preds, "nutrition5k")
        self.assertEqual((fit["eligible_n"], fit["eligible_groups"], fit["raw_factor"]), (5, 5, 1.25))
        preds[-2]["fallback"] = True
        self.assertEqual(m.fit_mass(rows, labels, preds, "nutrition5k")["mass_factor"], 1)

    def test_split_and_group_leak_rejected(self):
        rows, labels, preds = fixture()
        rows[1]["group_id"] = rows[0]["group_id"]
        with self.assertRaises(ValueError):
            m.crossvalidate(rows, labels, preds)
        rows, labels, preds = fixture()
        rows[0]["split"] = "validation"
        with self.assertRaises(ValueError):
            m.fit_final(rows, labels, preds, dataset="nutrition5k")
        rows[0]["split"] = "dev"
        labels[rows[0]["sample_id"]]["sealed"] = True
        with self.assertRaises(ValueError):
            m.crossvalidate(rows, labels, preds)
        labels[rows[0]["sample_id"]].pop("sealed")
        rows[0].pop("split")
        with self.assertRaises(ValueError):
            m.fit_final(rows, labels, preds, dataset="nutrition5k")

    def test_oof_fits_receive_only_training_labels_and_holdout_change_does_not_affect_fold(self):
        rows, labels, preds = fixture(12, ratio=.8)
        real_fit = m.fit_final
        def spy(train, supplied_labels, *args, **kwargs):
            self.assertEqual(set(supplied_labels), {r["sample_id"] for r in train})
            return real_fit(train, supplied_labels, *args, **kwargs)
        with patch.object(m, "fit_final", side_effect=spy):
            first = m.crossvalidate(rows, labels, preds, calibrate=True)
        altered = deepcopy(labels)
        for row in rows:
            if row["fold"] == 0:
                altered[row["sample_id"]]["truth"] = vector(10000)
        second = m.crossvalidate(rows, altered, preds, calibrate=True)
        self.assertEqual(first["fold_parameters"][0], second["fold_parameters"][0])
        for original, changed, row in zip(first["predictions"], second["predictions"], rows):
            if row["fold"] == 0:
                self.assertEqual(original["prediction"], changed["prediction"])

    def test_oof_fallback_recomputed_from_training_fold(self):
        rows, labels, preds = fixture(6)
        for row in rows:
            labels[row["sample_id"]]["truth"] = vector(1000 if row["fold"] == 0 else 20)
        preds[0].update(fallback=True, prediction=vector(9999))
        output = m.crossvalidate(rows, labels, preds, calibrate=False)
        self.assertEqual(output["predictions"][0]["prediction"], vector(20))
        self.assertEqual(output["predictions"][0]["mass_factor"], 1)

    def test_fewshot_reference_cannot_be_calibrated(self):
        rows, labels, preds = fixture(12)
        preds[0]["example_sources"] = [{"sample_id": "other"}]
        with self.assertRaises(ValueError):
            m.crossvalidate(rows, labels, preds, calibrate=True)
        with self.assertRaises(ValueError):
            m.fit_final(rows, labels, preds, dataset="nutrition5k")
        out = m.compare_calibration(rows, labels, preds, dataset="nutrition5k")
        self.assertFalse(out["calibration_enabled"])
        self.assertEqual(out["calibration_reason"], "fewshot_calibration_forbidden")

    def test_calibration_comparison_retains_only_one_mass_factor(self):
        rows, labels, preds = fixture(12, ratio=.8)
        output = m.compare_calibration(rows, labels, preds, dataset="nutrition5k")
        self.assertTrue(output["calibration_enabled"])
        self.assertEqual(output["selected_parameters"]["mass_factor"], 1.125)
        self.assertEqual(output["predictions"][0]["prediction"], vector(90))

    def test_asa_factor_maps_to_legal_option_never_scales_final_option(self):
        rows, labels, preds = fixture(10, "asa24", ratio=1.2)
        for label in labels.values():
            label["truth"] = vector(150)
        params = m.fit_final(rows, labels, preds, OPTIONS, DENSITIES, dataset="asa24")
        self.assertGreater(params["mass_factor"], 1)
        output = m.apply_parameters(preds[0], params, OPTIONS, DENSITIES)
        self.assertIn(output["conditional"]["prediction"]["weight"], (50, 100, 150))
        # Shrinking a fitted continuous factor can undo a discrete option jump.
        # The retain-calibration gate, not an after-the-fact re-fit, handles it.
        self.assertEqual(output["conditional"]["prediction"], vector(100))
        params["mass_factor"] = 1.125
        self.assertEqual(m.apply_parameters(preds[0], params, OPTIONS, DENSITIES)["conditional"]["prediction"], vector(150))
        self.assertEqual(output["e2e"], preds[0]["e2e"])

    def test_asa_failed_exact_is_retained_with_legal_median(self):
        rows, labels, preds = fixture(4, "asa24")
        preds[0]["conditional"] = None
        output = m.crossvalidate(rows, labels, preds, OPTIONS, DENSITIES)
        self.assertEqual(output["metrics"]["datasets"]["asa24"]["primary"]["n"], 4)
        self.assertTrue(output["predictions"][0]["conditional"]["fallback"])
        self.assertEqual(output["predictions"][0]["conditional"]["prediction"], vector())


class MassAccountingTests(unittest.TestCase):
    def record(self):
        _, _, preds = fixture(1)
        p = preds[0]
        leaves = [{"component_id": "a", "item_id": "a", "parent_id": "plate", "grams": 40,
                   "density": deepcopy(DENSITIES["12345678"])},
                  {"component_id": "b", "item_id": "b", "parent_id": "plate", "grams": 60,
                   "density": deepcopy(DENSITIES["12345678"])}]
        p["portion_result"] = {"raw_leaves": leaves, "parents": [{"parent_id": "plate", "grams": 100}]}
        return p

    def test_leaf_parent_nutrient_conservation_and_no_double_application(self):
        pred = self.record()
        before = deepcopy(pred)
        calibrated = m.apply_mass(pred, 1.125)
        self.assertEqual(pred, before)
        self.assertEqual(calibrated["prediction"], vector(112.5))
        self.assertEqual(sum(r["grams"] for r in calibrated["calibrated_leaves"]), 112.5)
        self.assertEqual(calibrated["calibrated_parents"][0]["grams"], 112.5)
        again = m.apply_mass(calibrated, 1.125)
        self.assertEqual(again["prediction"], calibrated["prediction"])

    def test_reject_inconsistent_leaf_or_parent_totals_and_duplicate_leaf(self):
        pred = self.record()
        pred["raw_prediction"]["protein"] += 1
        with self.assertRaises(ValueError):
            m.apply_mass(pred, 1)
        pred = self.record()
        pred["portion_result"]["parents"][0]["grams"] = 101
        with self.assertRaises(ValueError):
            m.apply_mass(pred, 1)
        pred = self.record()
        pred["portion_result"]["raw_leaves"][1]["component_id"] = "a"
        with self.assertRaises(ValueError):
            m.apply_mass(pred, 1)

    def test_fallback_never_scaled_and_invalid_factor_rejected(self):
        pred = self.record()
        pred["fallback"] = True
        self.assertEqual(m.apply_mass(pred, 1.125)["prediction"], pred["prediction"])
        for factor in (.8, 1.25, float("nan"), True):
            with self.assertRaises(ValueError):
                m.apply_mass(pred, factor)

    def test_legacy_portions_without_any_density_use_raw_vector_equivalent(self):
        pred = self.record()
        leaves = pred["portion_result"].pop("raw_leaves")
        for leaf in leaves:
            leaf.pop("density")
        pred["portion_result"]["portions"] = leaves
        calibrated = m.apply_mass(pred, 1.125)
        self.assertEqual(calibrated["prediction"], vector(112.5))
        self.assertEqual(calibrated["mass_calibration_representation"], "equivalent_raw_vector_scaling")
        self.assertNotIn("calibrated_leaves", calibrated)

    def test_partially_populated_leaf_densities_fail_closed(self):
        pred = self.record()
        pred["portion_result"]["raw_leaves"][0].pop("density")
        with self.assertRaises(ValueError):
            m.apply_mass(pred, 1.125)

    def test_zero_mass_leaf_is_not_a_successful_component_prediction(self):
        pred = self.record()
        pred["portion_result"]["raw_leaves"][0]["grams"] = 0
        with self.assertRaises(ValueError):
            m.apply_mass(pred, 1)


if __name__ == "__main__":
    unittest.main()
