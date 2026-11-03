"""Hand-calculated diagnostic identities and partial-run refusal, no research I/O."""
from copy import deepcopy
import importlib.util
import json
import stat
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[1] / "tools/diagnose_completed_m.py"
spec = importlib.util.spec_from_file_location("completed_diagnostic", SOURCE)
diag = importlib.util.module_from_spec(spec)
spec.loader.exec_module(diag)


def values(number):
    return {k: number for k in diag.TARGETS}


def fixture(errors, groups=None):
    rows = [{"sample_id": str(i), "group_id": str(i) if groups is None else groups[i]}
            for i in range(len(errors))]
    labels = {r["sample_id"]: {"truth": values(20)} for r in rows}
    predictions = {str(i): values(20 + e) for i, e in enumerate(errors)}
    return rows, labels, predictions


class CompletedDiagnosticTests(unittest.TestCase):
    def test_absolute_error_and_top_share_are_not_signed_bias(self):
        rows, labels, predictions = fixture([8, -1, -1])
        stat = diag.errors(rows, labels, predictions)["targets"]["weight"]
        self.assertAlmostEqual(stat["mae"], 10 / 3)
        self.assertEqual(stat["mean_signed_error"], 2)
        self.assertEqual(stat["top_rows"]["1"]["fraction_of_all_absolute_error"], .8)
        self.assertAlmostEqual(stat["per_unit"], 1 / 6)
        self.assertEqual((stat["over_n"], stat["under_n"], stat["equal_n"]), (1, 2, 0))

    def test_group_errors_do_not_cancel(self):
        rows, labels, predictions = fixture([10, -10, 5], ["a", "a", "b"])
        stat = diag.errors(rows, labels, predictions)["targets"]["fat"]
        self.assertEqual(stat["top_groups"]["1"]["absolute_error_sum"], 20)
        self.assertEqual(stat["top_groups"]["1"]["fraction_of_all_absolute_error"], .8)
        self.assertEqual(stat["top_rows"]["10"]["selected_n"], 3)

    def test_score_mismatch_is_rejected(self):
        rows, labels, predictions = fixture([2, -4])
        saved = {"n": 2, "metrics": {k: {"mae": 3, "reference_mean": 20, "per_unit": .15}
                                    for k in diag.TARGETS}}
        diag.errors(rows, labels, predictions, saved)
        saved["metrics"]["energy"]["mae"] = 4
        with self.assertRaisesRegex(ValueError, "differ_from_existing_score"):
            diag.errors(rows, labels, predictions, saved)

    def test_invalid_values_and_duplicate_rows_never_disappear(self):
        rows, labels, predictions = fixture([0])
        for value in [float("nan"), float("inf"), -1, True]:
            bad = deepcopy(predictions)
            bad["0"]["fat"] = value
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "invalid_target_value"):
                diag.errors(rows, labels, bad)
        with self.assertRaisesRegex(ValueError, "duplicate"):
            diag.errors(rows + rows, labels, predictions)
        with self.assertRaises(KeyError):
            diag.errors(rows, labels, {})

    def test_empty_conditional_population_remains_undefined(self):
        result = diag.errors([], {}, {})
        self.assertEqual(result["n"], 0)
        self.assertIsNone(result["targets"]["weight"]["mae"])
        rows, labels, predictions = fixture([0])
        self.assertIsNone(diag.errors(rows, labels, predictions)["targets"]["weight"]
                          ["top_rows"]["1"]["fraction_of_all_absolute_error"])

    def test_paired_directions_keep_the_same_three_rows(self):
        rows, labels, baseline = fixture([8, -1, -1])
        candidate = {"0": values(24), "1": values(23), "2": values(19)}
        stat = diag.paired(rows, labels, baseline, candidate)["targets"]["energy"]
        self.assertEqual((stat["improved_n"], stat["worsened_n"], stat["equal_n"]), (1, 1, 1))
        self.assertEqual(stat["sum_absolute_error_difference"], -2)
        self.assertAlmostEqual(stat["mae_difference"], -2 / 3)

    def test_symmetric_mass_density_identity_does_not_sum_absolute_terms(self):
        rows = [{"sample_id": "a", "group_id": "g"}]
        truth, pred = values(200), values(300)
        truth["weight"], pred["weight"] = 100, 200
        result = diag.mass_density(rows, {"a": {"truth": truth}}, {"a": pred})
        stat = result["targets"]["energy"]
        self.assertEqual(stat["mass_signed_sum"], 175)
        self.assertEqual(stat["density_signed_sum"], -75)
        self.assertEqual(stat["max_identity_residual"], 0)
        self.assertTrue(result["complete_population_decomposition"])
        self.assertEqual(stat["mass_mean_absolute_on_decomposable_rows"] +
                         stat["density_mean_absolute_on_decomposable_rows"], 250)

    def test_zero_weight_stays_in_metrics_but_not_density_decomposition(self):
        rows, labels, predictions = fixture([0, 0])
        predictions["0"]["weight"] = 0
        result = diag.mass_density(rows, labels, predictions)
        self.assertEqual((result["population_n"], result["decomposable_n"], result["nonpositive_weight_n"]), (2, 1, 1))
        self.assertFalse(result["complete_population_decomposition"])
        self.assertEqual(diag.errors(rows, labels, predictions)["targets"]["weight"]["mae"], 10)

    def test_partial_batch_refuses_before_sources_or_labels(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            with patch.object(diag, "ROUND", path), patch.object(diag, "source_pins") as sources:
                with self.assertRaisesRegex(ValueError, "complete_scored_batch_required"):
                    diag.run()
                sources.assert_not_called()
            for relative in ("runs/development/completion.json", "runs/scoring/results.json",
                             "development_checkpoint.json", "launch/automatic_followup.json"):
                target = path / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(json.dumps({"status": "waiting_for_existing_base"}))
            with self.assertRaisesRegex(ValueError, "follower_not_finished"):
                diag.require_scored(path)
            (path / "launch/automatic_followup.json").write_text(json.dumps({"status": "development_scored"}))
            diag.require_scored(path)

    def test_R7_DIAG_1_output_directory_symlink_cannot_write_or_chmod_outside(self):
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory).resolve()
            root, outside = parent / "round7", parent / "outside"
            root.mkdir(); outside.mkdir(mode=0o755)
            original_mode = stat.S_IMODE(outside.stat().st_mode)
            (root / "diagnostics").symlink_to(outside, target_is_directory=True)
            with self.assertRaisesRegex(RuntimeError, "symlink"):
                diag.save_diagnostic(root, {"fixture": True}, {"value": 1}, lambda: True)
            self.assertEqual(stat.S_IMODE(outside.stat().st_mode), original_mode)
            self.assertEqual(list(outside.iterdir()), [])

    def test_R7_DIAG_1_existing_record_symlink_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory).resolve()
            root = parent / "round7"; root.mkdir()
            value = {"aggregate": "synthetic"}
            diag.save_diagnostic(root, {"fixture": True}, value, lambda: True)
            record = next((root / "diagnostics/completed_m/records").glob("*.json"))
            outside = parent / "outside.json"
            outside.write_text(record.read_text())
            original_mode = stat.S_IMODE(outside.stat().st_mode)
            original = outside.read_bytes()
            record.unlink(); record.symlink_to(outside)
            with self.assertRaisesRegex(RuntimeError, "symlink"):
                diag.save_diagnostic(root, {"fixture": True}, value, lambda: True)
            self.assertEqual(outside.read_bytes(), original)
            self.assertEqual(stat.S_IMODE(outside.stat().st_mode), original_mode)


if __name__ == "__main__":
    unittest.main()
