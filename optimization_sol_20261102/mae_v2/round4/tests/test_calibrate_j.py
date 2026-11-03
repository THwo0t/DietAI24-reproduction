"""Synthetic hand arithmetic, isolation adversaries and immutable calibration."""
from copy import deepcopy
import json
from pathlib import Path
import shutil
import sys
import unittest
from unittest.mock import patch

V2 = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(V2), str(V2 / "src"), str(Path(__file__).resolve().parent)]
from round4.src import calibrate_j as cal
from round4.src.artifacts import ArtifactStore, ArtifactError, canonical, fingerprint
import test_score_dev as score_tests


def fixture(n=20):
    rows, labels, records = [], {}, {}
    for index in range(n):
        sid = f"synthetic-{index:03d}"
        row = {"sample_id": sid, "dataset": "nutrition5k", "split": "dev",
               "fold": index % 5, "group_id": f"group-{index:03d}"}
        vector = {"weight": 100, "energy": 200, "fat": 10, "carbs": 20, "protein": 5}
        rows.append(row); labels[sid] = {"truth": deepcopy(vector), "split": "dev"}
        records[sid] = {key: row[key] for key in ("sample_id", "dataset", "group_id", "fold")}
        records[sid].update(prediction=deepcopy(vector), raw_prediction=deepcopy(vector),
            fallback=False, method_fallback=False, repair_used=False, native_complete=True,
            raw_leaves=[{"item_id": "i1", "grams": 100,
                         "density": {"energy": 200, "fat": 10, "carbs": 20, "protein": 5}}])
    return rows, labels, records


def checks(ratios):
    result = []
    for (target, caps), values in zip(cal.scorer.metrics.THRESHOLDS["nutrition5k"].items(),
                                     zip(ratios[::2], ratios[1::2])):
        for statistic, cap, ratio in zip(("mae", "per_unit"), caps, values):
            value = cap * ratio
            result.append({"dataset": "nutrition5k", "target": target, "statistic": statistic,
                           "threshold": cap, "value": value, "pass": value <= cap})
    return {"checks": result}


class PureCalibrationTests(unittest.TestCase):
    def test_hand_computed_five_factors_then_half_shrink(self):
        rows, labels, records = fixture(5)
        for label in labels.values():
            label["truth"] = {"weight": 200, "energy": 100, "fat": 10, "carbs": 24, "protein": 5.005}
        params = cal.fit_profile(rows, labels, records)
        self.assertEqual(params["raw_factors"], {"weight": 2, "energy": .5, "fat": 1,
                                                "carbs": 1.2, "protein": 1.001})
        self.assertEqual(params["applied_factors"], {"weight": 1.5, "energy": .75, "fat": 1,
                                                    "carbs": 1.1, "protein": 1.0005})
        self.assertEqual(params["target_training_losses"]["weight"],
                         {"raw_mae": 100, "unshrunk_training_mae": 0, "applied_training_mae": 50})
        result = cal.apply_profile(records[rows[0]["sample_id"]], params["applied_factors"], heldout_fold=0)
        self.assertEqual(result["prediction"]["weight"], 150)
        self.assertEqual(result["prediction"]["energy"], 150)
        self.assertAlmostEqual(result["prediction"]["carbs"], 22)

    def test_fewer_than_five_groups_identity_even_with_many_images(self):
        rows, labels, records = fixture(20)
        for index, row in enumerate(rows):
            row["group_id"], row["fold"] = f"group-{index % 4}", index % 4
            records[row["sample_id"]].update(group_id=row["group_id"], fold=row["fold"])
            labels[row["sample_id"]]["truth"]["weight"] = 1000
        params = cal.fit_profile(rows, labels, records)
        self.assertEqual(params["eligible_n"], 20)
        self.assertEqual(params["eligible_group_count"], 4)
        self.assertEqual(params["applied_factors"], dict.fromkeys(cal.KEYS, 1))
        self.assertEqual(params["reason"], "fewer_than_five_eligible_training_groups")

    def test_zero_predictor_and_flat_minimum_choose_one(self):
        rows, labels, records = fixture(5)
        for index, row in enumerate(rows):
            sid = row["sample_id"]
            records[sid]["prediction"]["fat"] = records[sid]["raw_prediction"]["fat"] = 0
            x, y = (100, 80) if index == 0 else ((100, 120) if index == 1 else (0, 0))
            records[sid]["prediction"]["energy"] = records[sid]["raw_prediction"]["energy"] = x
            labels[sid]["truth"]["energy"] = y
        params = cal.fit_profile(rows, labels, records)
        self.assertEqual(params["raw_factors"]["fat"], 1)
        self.assertEqual(params["raw_factors"]["energy"], 1)

    def test_both_grid_bounds_are_applied_before_shrink_without_clipping_answers(self):
        rows, labels, records = fixture(5)
        for label in labels.values():
            label["truth"]["weight"], label["truth"]["energy"] = 100000, 0
        params = cal.fit_profile(rows, labels, records)
        self.assertEqual(params["raw_factors"]["weight"], 2)
        self.assertEqual(params["raw_factors"]["energy"], .5)
        self.assertEqual(params["applied_factors"]["weight"], 1.5)
        self.assertEqual(params["applied_factors"]["energy"], .75)

    def test_fold_label_poison_cannot_change_own_fold_prediction_but_training_labels_can(self):
        rows, labels, records = fixture()
        clean = cal.build_oof(rows, labels, records)
        poisoned = deepcopy(labels)
        heldout_ids = [row["sample_id"] for row in rows if row["fold"] == 0]
        for sid in heldout_ids:
            poisoned[sid]["truth"] = dict.fromkeys(cal.KEYS, 999999)
        changed = cal.build_oof(rows, poisoned, records)
        self.assertEqual(clean["fit_audit"]["folds"]["0"], changed["fit_audit"]["folds"]["0"])
        for sid in heldout_ids:
            self.assertEqual(clean["records"][sid], changed["records"][sid])
        training_changed = deepcopy(labels)
        for row in rows:
            if row["fold"] != 0:
                training_changed[row["sample_id"]]["truth"]["weight"] = 200
        influenced = cal.build_oof(rows, training_changed, records)
        self.assertEqual(influenced["fit_audit"]["folds"]["0"]["raw_factors"]["weight"], 2)
        self.assertEqual(influenced["records"][heldout_ids[0]]["prediction"]["weight"], 150)

    def test_fitter_receives_only_training_label_keys_and_group_isolation(self):
        rows, labels, records = fixture()
        with patch.object(cal, "fit_profile", wraps=cal.fit_profile) as fit:
            result = cal.build_oof(rows, labels, records)
        self.assertEqual(fit.call_count, 6)
        for fold, call in enumerate(fit.call_args_list[:5]):
            supplied, scoped_labels, scoped_records = call.args
            ids = {row["sample_id"] for row in supplied}
            self.assertEqual(set(scoped_labels), ids)
            self.assertEqual(set(scoped_records), ids)
            self.assertTrue(all(row["fold"] != fold for row in supplied))
            audit = result["fit_audit"]["folds"][str(fold)]
            self.assertFalse(set(audit["training_groups"]) & set(audit["heldout_groups"]))
        rows[1]["group_id"] = rows[0]["group_id"]
        records[rows[1]["sample_id"]]["group_id"] = rows[0]["group_id"]
        with self.assertRaisesRegex(cal.CalibrationError, "group_crosses_folds"):
            cal.build_oof(rows, labels, records)

    def test_missing_extra_or_nonfinite_labels_and_records_fail_instead_of_dropping(self):
        for mutation in ("missing_label", "extra_label", "missing_record", "nan", "sealed", "zero_weight"):
            rows, labels, records = fixture()
            sid = rows[0]["sample_id"]
            if mutation == "missing_label": labels.pop(sid)
            elif mutation == "extra_label": labels["query_truth"] = labels[sid]
            elif mutation == "missing_record": records.pop(sid)
            elif mutation == "nan": labels[sid]["truth"]["fat"] = float("nan")
            elif mutation == "sealed": labels[sid]["sealed"] = True
            else: records[sid]["raw_prediction"]["weight"] = 0
            with self.subTest(case=mutation), self.assertRaises(ValueError):
                cal.build_oof(rows, labels, records)

    def test_repair_and_method_fallback_are_eligible_whole_fallback_unchanged(self):
        rows, labels, records = fixture()
        first, second, third = (row["sample_id"] for row in rows[:3])
        records[first].update(repair_used=True, native_complete=False)
        records[second].update(method_fallback=True, native_complete=False)
        records[third].update(fallback=True, raw_prediction=None, native_complete=False)
        before = deepcopy((rows, labels, records))
        result = cal.build_oof(rows, labels, records)
        audit = result["fit_audit"]["final_training_fit"]
        self.assertIn(first, audit["eligible_ids"]); self.assertIn(second, audit["eligible_ids"])
        self.assertNotIn(third, audit["eligible_ids"])
        self.assertEqual(result["records"][third]["prediction"], records[third]["prediction"])
        self.assertTrue(result["records"][third]["calibration"]["whole_fallback_preserved"])
        self.assertEqual(len(result["records"]), 20)
        for sid in records:
            self.assertEqual(result["records"][sid]["raw_leaves"], records[sid]["raw_leaves"])
            self.assertEqual(result["records"][sid]["raw_prediction"], records[sid]["raw_prediction"])
            self.assertEqual(result["records"][sid]["calibration"]["leaf_accounting_scope"], "raw_prediction_only")
        self.assertEqual((rows, labels, records), before)

    def test_final_all_data_fit_is_not_substituted_for_oof_parameters(self):
        rows, labels, records = fixture()
        for row in rows:
            if row["fold"] == 0:
                sid = row["sample_id"]
                records[sid]["prediction"]["weight"] = records[sid]["raw_prediction"]["weight"] = 10000
                labels[sid]["truth"]["weight"] = 20000
        result = cal.build_oof(rows, labels, records)
        self.assertEqual(result["fit_audit"]["final_training_fit"]["applied_factors"]["weight"], 1.5)
        self.assertEqual(result["fit_audit"]["folds"]["0"]["applied_factors"]["weight"], 1)
        for row in rows:
            pred = result["records"][row["sample_id"]]
            params = result["fit_audit"]["folds"][str(row["fold"])]
            self.assertEqual(pred["prediction"]["weight"],
                records[row["sample_id"]]["raw_prediction"]["weight"] * params["applied_factors"]["weight"])
        self.assertEqual(result["fit_audit"]["final_training_fit"]["usage"],
                         "future_unseen_inputs_only_never_this_oof_population")

    def test_whole_profile_selection_preserves_passes_and_uses_worst_then_mean(self):
        raw = checks([2] + [.5] * 9)
        self.assertEqual(cal.select_profile(raw, checks([1.5, 1.01] + [.4] * 8))["selected_profile"], "raw")
        self.assertEqual(cal.select_profile(raw, checks([1.5] + [.4] * 9))["selected_profile"], "calibrated")
        self.assertEqual(cal.select_profile(raw, checks([2.001] + [.1] * 9))["selected_profile"], "raw")
        self.assertEqual(cal.select_profile(raw, deepcopy(raw))["selected_profile"], "raw")
        result = cal.select_profile(checks([2] + [1.5] * 9), checks([2] + [1.4] * 9))
        self.assertEqual(result["selected_profile"], "calibrated")
        self.assertEqual(result["reason"], "equal_worst_and_strictly_lower_mean_ratio")
        malformed = checks([2] * 10); malformed["checks"][0]["pass"] = True
        with self.assertRaises(cal.CalibrationError):
            cal.select_profile(raw, malformed)

    def test_zero_reference_mean_is_undefined_never_zero_or_a_pass(self):
        rows, labels, records = fixture()
        for label in labels.values():
            label["truth"]["fat"] = 0
        derived = cal.build_oof(rows, labels, records)
        raw = cal.scorer.metrics.evaluate(rows, labels, list(records.values()), bootstrap=0)
        calibrated = cal.scorer.metrics.evaluate(rows, labels, list(derived["records"].values()), bootstrap=0)
        for value in (raw, calibrated):
            metric = value["datasets"]["nutrition5k"]["primary"]["metrics"]["fat"]
            self.assertIsNone(metric["per_unit"])
            self.assertFalse(metric["pass_per_unit"])
        selected = cal.select_profile(raw, calibrated)
        self.assertEqual(selected["selected_profile"], "raw")
        self.assertEqual(selected["raw"]["undefined_checks"], 1)
        self.assertIsNone(selected["raw"]["worst_ratio"])
        self.assertEqual(selected["reason"], "undefined_nutrition5k_check_prevents_selection")


class CompletedCalibrationTests(unittest.TestCase):
    def setUp(self):
        self.fixture = score_tests.ScoreDevTests(); self.fixture.setUp(); self.addCleanup(self.fixture.doCleanups)
        self.root = self.fixture.root
        for name in (cal.PROTOCOL, "round4/src/calibrate_j.py"):
            self.fixture.put(name, (V2 / name).read_bytes())
        freeze = {"status": "accepted_external_training_frozen", "binding": {"synthetic_exclusion_proof": 1}}
        self.fixture.put(cal.TRAIN_FREEZE, canonical(freeze))
        freeze_sha = score_tests.sha((self.root / cal.TRAIN_FREEZE).read_bytes())
        self.binding = {"phase": "development_base", "method_config": deepcopy(cal.scorer.run_base.context.METHOD_CONFIG),
            "query_count": 84, "query_groups": 78, "training_freeze_sha256": freeze_sha,
            "training_exclusion_binding": freeze["binding"], "input_sha256": {
                cal.TRAIN_FREEZE: freeze_sha, cal.scorer.MANIFEST: self.fixture.pins[cal.scorer.MANIFEST]}}
        # Replace only this test's invented setup before invoking the calibrator;
        # no real or already-executed calibration artifact is ever rewritten.
        self.reseal_synthetic_base(self.binding)
        patcher = patch.object(cal, "ROOT", self.root); patcher.start(); self.addCleanup(patcher.stop)

    def reseal_synthetic_base(self, binding):
        shutil.rmtree(self.root / "round4/runs/J")
        self.fixture.base_store = ArtifactStore(self.root / "round4/runs/J", binding,
            self.fixture.records, verify_sources=lambda: None, root=self.root / "round4")
        self.fixture.base_store.finalize(self.fixture.records)

    def test_prediction_seal_precedes_metrics_and_completed_rerun_is_read_only(self):
        evaluate = cal.scorer.metrics.evaluate
        def sealed_first(*args, **kwargs):
            self.assertTrue((self.root / cal.CAL_OUTPUT / "completion.json").is_file())
            return evaluate(*args, **kwargs)
        with patch.object(cal.scorer.metrics, "evaluate", sealed_first):
            first = cal.run()
        self.assertEqual(first["status"], "calibration_complete")
        self.assertEqual(first["metrics"]["selection"]["selected_profile"], "raw")
        self.assertEqual(first["metrics"]["bootstrap_scope"],
                         "conditional_on_fixed_oof_predictions_no_refitting_or_selection_uncertainty")
        self.assertEqual(first["metrics"]["raw"]["nutrition5k"]["primary"]["n"], 84)
        self.assertEqual(first["metrics"]["calibrated"]["nutrition5k"]["primary"]["n"], 84)
        self.assertEqual(first["metrics"]["raw"]["joint_metrics_with_preserved_asa"]["datasets"]["asa24"],
                         first["metrics"]["calibrated"]["joint_metrics_with_preserved_asa"]["datasets"]["asa24"])
        completion = json.loads((self.root / cal.CAL_OUTPUT / "completion.json").read_text())
        self.assertEqual(completion["record_count"], 85)
        before = self.fixture.snapshot()
        second = cal.run()
        self.assertEqual(second["status"], "calibration_verified")
        self.assertEqual(second["metrics"], first["metrics"])
        self.assertEqual(before, self.fixture.snapshot())

    def test_base_failure_prevents_labels_and_all_output(self):
        with patch.object(cal.scorer, "_verified_base", side_effect=ArtifactError("missing complete seal")):
            with self.assertRaises(ArtifactError): cal.run()
        self.assertEqual(self.fixture.reads, [])
        self.assertFalse((self.root / cal.CAL_OUTPUT).exists())

    def test_external_only_binding_gate_precedes_labels(self):
        variants = []
        binding = deepcopy(self.binding); binding["method_config"]["method"] = "hybrid_dev_gallery"; variants.append(binding)
        binding = deepcopy(self.binding); binding["input_sha256"][cal.scorer.LABELS] = "a" * 64; variants.append(binding)
        binding = deepcopy(self.binding); binding["training_freeze_sha256"] = "b" * 64; variants.append(binding)
        for binding in variants:
            # Fully self-consistent real ArtifactStore seal; rejection must be
            # scientific provenance validation, not merely a broken checksum.
            self.reseal_synthetic_base(binding); self.fixture.reads.clear()
            with self.assertRaises(cal.CalibrationError): cal.run()
            self.assertNotIn(cal.scorer.LABELS, self.fixture.reads)

    def test_whole_fallback_retains_full_84_scoring_denominator(self):
        sid = next(iter(self.fixture.records))
        self.fixture.records[sid].update(fallback=True, raw_prediction=None, native_complete=False,
                                        repair_used=True, failure="synthetic_contract_failure")
        self.reseal_synthetic_base(self.binding)
        result = cal.run()["metrics"]
        for name in ("raw", "calibrated"):
            self.assertEqual(result[name]["nutrition5k"]["primary"]["n"], 84)
            self.assertEqual(result[name]["nutrition5k"]["fallback_n"], 1)
            self.assertEqual(result[name]["nutrition5k"]["complete_subset"]["n"], 83)

    def test_protocol_drift_fails_before_labels(self):
        self.fixture.put(cal.PROTOCOL, b"changed protocol")
        with self.assertRaisesRegex(cal.CalibrationError, "registered_calibration_protocol_changed"):
            cal.run()
        self.assertNotIn(cal.scorer.LABELS, self.fixture.reads)

    def test_missing_record_or_label_fails_no_calibration_artifact(self):
        valid = self.fixture.verified_base(verify_only=True)
        valid["records"].pop(next(iter(valid["records"])))
        with patch.object(cal.scorer.run_base, "base", return_value=valid), self.assertRaises(ValueError):
            cal.run()
        self.assertNotIn(cal.scorer.LABELS, self.fixture.reads)
        labels = deepcopy(self.fixture.labels); labels.pop(next(iter(labels)))
        self.fixture.repin(cal.scorer.LABELS, canonical(labels))
        with self.assertRaises(cal.CalibrationError): cal.run()
        self.assertFalse((self.root / cal.CAL_OUTPUT).exists())

    def test_scoring_tamper_refused_without_rewriting_calibrated_predictions(self):
        cal.run(); before = self.fixture.snapshot()
        selector = cal.select_profile
        def changed(*args):
            value = selector(*args); value["reason"] = "tampered"; return value
        with patch.object(cal, "select_profile", changed), self.assertRaisesRegex(
                cal.CalibrationError, "completed_calibration_recomputation_changed"):
            cal.run()
        self.assertEqual(before, self.fixture.snapshot())


if __name__ == "__main__":
    unittest.main()
