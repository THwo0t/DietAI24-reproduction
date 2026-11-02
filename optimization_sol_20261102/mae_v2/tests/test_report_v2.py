"""Aggregate-only report tests with synthetic files and no inference imports."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import report_v2 as report

LIMITS = {
    "asa24": ((64.22, .4524), (62.01, .2548), (2.34, .2262), (9.035, .2704), (1.794, .3029)),
    "nutrition5k": ((58.63, .2028), (88.66, .2561), (5.213, .2938), (7.774, .2756), (5.044, .2444)),
}


def paper_fixture():
    return {"datasets": {ds: {"metrics": {report.TARGET_NAMES[key]: {
        "threshold_per_dish": absolute, "threshold_per_unit": relative,
        "paper_per_dish": absolute / 1.3, "paper_per_unit": relative / 1.3}
        for key, (absolute, relative) in zip(report.KEYS, values)}} for ds, values in LIMITS.items()}}


def metrics_fixture(ratio=2, formal=False):
    datasets = {}
    for ds, thresholds in LIMITS.items():
        n = (78 if formal else 99) if ds == "asa24" else (200 if formal else 84)
        exact = (12 if formal else 15) if ds == "asa24" else None
        primary = {"n": exact if exact is not None else n, "available_n": exact if exact is not None else n,
                   "complete_population": True, "metrics": {key: {
                       "mae": a * ratio, "per_unit": b * ratio, "reference_mean": a / b,
                       "threshold_mae": a, "threshold_per_unit": b, "pass_mae": ratio <= 1, "pass_per_unit": ratio <= 1}
                   for key, (a, b) in zip(report.KEYS, thresholds)}}
        datasets[ds] = {"n": n, "groups": 23 if ds == "asa24" else (188 if formal else 78),
                        "primary": primary, "native_complete_n": n - 3, "complete_n": n - 1,
                        "repair_success_n": 2, "fallback_n": 1, "method_fallback_n": 1,
                        "hidden_sample_ids": ["MUST_NOT_ESCAPE"],
                        "bootstrap": {"replicates": 10000, "group_count": 23 if ds == "asa24" else 78,
                            "confidence": .95, "empty_exact_replicates": 2 if ds == "asa24" else None,
                            "intervals": {key + ".mae": {"low": a * ratio * .8, "high": a * ratio * 1.2,
                                                          "valid_replicates": 9998 if ds == "asa24" else 10000}
                                          for key, (a, _) in zip(report.KEYS, thresholds)}}}
        if exact is not None:
            datasets[ds].update(exact_n=exact, exact_groups=9, conditional_fallback_n=1, conditional_missing_n=0,
                                e2e={**deepcopy(primary), "n": n, "available_n": n})
    return {"datasets": datasets, "passed_checks": 20 if ratio <= 1 else 0,
            "joint_pass": ratio <= 1, "unknown_raw_response": "MUST_NOT_ESCAPE"}


class ReportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="dietai-v2-report-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.put("analysis/paper_targets.json", paper_fixture())
        self.put("config/experiment.json", {"version": 2, "bootstrap_resamples": 10000})
        self.put("config/candidates.json", {name: {} for name in "ABCDE"})
        counts = {"asa24_images": 99, "asa24_groups": 23, "nutrition5k_images": 84,
                  "nutrition5k_groups": 78, "nutrition5k_retired_counts": {"historical_component": 16}}
        self.put("data/cohorts/dev_freeze.json", {"counts": counts, "artifacts": {"MUST_NOT_ESCAPE": "private artifact"}})
        self.put("evidence/audit_summary.json", {"development": counts, "development_ready": True,
            "validation_ready": False, "validation": {"asa24_images": 78, "asa24_groups": 23,
                "nutrition5k_target_images": 200, "nutrition5k_groups": 188,
                "nutrition5k_retained_original_images": 142, "nutrition5k_retired_counts": {
                    "historical_component": 37, "original_development_component": 21},
                "nutrition5k_group_size_histogram": {"1": 177, "2": 10, "3": 1}, "nutrition5k_max_group_fraction": .015}})

    def put(self, name, value):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value) + "\n")

    def development(self, ratio=2):
        metric = metrics_fixture(ratio)
        candidate = {"name": "A", "metrics": metric, "registration_index": 3, "estimated_chat_calls": 3,
                     "calibration_enabled": True, "directory": "../../data/cohorts/sealed"}
        self.put("runs/development/candidates.json", [candidate])
        self.put("runs/development/A/metrics.json", metrics_fixture(ratio + .1))
        self.put("runs/development/A/status.json", {"status": "completed", "error": "MUST_NOT_ESCAPE"})
        self.put("runs/development/A/calibration-summary.json", {"raw_metrics": metrics_fixture(ratio + .1),
            "calibrated_metrics": metric, "calibration_enabled": True, "mass_factor": 1.1, "raw_factor": 1.2,
            "predictions": [{"must_not_copy": "MUST_NOT_ESCAPE"}]})
        self.put("runs/development/selection.json", {"profiles": {"asa24": candidate, "nutrition5k": candidate},
                                                     "metrics": metric})
        self.put("runs/development/completion.json", {"status": "development_targets_not_met" if ratio > 1 else "ready_for_review",
                                                       "registered_candidates_exhausted": ratio > 1})

    def test_unstarted_report_has_thresholds_but_no_invented_results(self):
        outcome = report.write_report(self.root)
        text = (self.root / report.OUTPUT_MARKDOWN).read_text()
        snapshot = json.loads((self.root / report.OUTPUT_SNAPSHOT).read_text())
        self.assertEqual(outcome["state"], "development_not_started")
        self.assertIsNone(snapshot["development"]["metrics"])
        self.assertIn("No selected predictions have been scored", text)
        self.assertNotIn("Completed formal arm", text)
        self.assertNotIn("MUST_NOT_ESCAPE", text + json.dumps(snapshot))
        self.assertGreaterEqual(outcome["word_count"], 1200)
        self.assertLessEqual(outcome["word_count"], 2500)

    def test_failed_development_reports_exact_gaps_and_both_recognition_floors(self):
        self.development()
        outcome = report.write_report(self.root)
        snapshot = json.loads((self.root / report.OUTPUT_SNAPSHOT).read_text())
        text = (self.root / report.OUTPUT_MARKDOWN).read_text()
        asa = snapshot["development"]["metrics"]["datasets"]["asa24"]
        self.assertTrue(asa["recognition_pass"])
        self.assertFalse(asa["former_recognition_pass"])
        check = next(c for c in snapshot["development"]["metrics"]["checks"]
                     if c["dataset"] == "nutrition5k" and c["target"] == "weight" and c["statistic"] == "mae")
        self.assertAlmostEqual(check["reduction_required"], 58.63)
        self.assertAlmostEqual(check["reduction_fraction"], .5)
        self.assertIn("**16 development images excluded**", text)
        self.assertIn("**58 original validation images retired**", text)
        self.assertIn("All-image E2E", text)
        self.assertNotIn("Completed formal arm", text)
        self.assertNotIn("MUST_NOT_ESCAPE", json.dumps(snapshot))
        self.assertLessEqual(outcome["word_count"], 2500)

    def test_formal_metrics_need_completion_and_both_complete_populations(self):
        self.development()
        self.put("runs/validation/metrics.json", {"baseline": metrics_fixture(1.2, True), "optimized": metrics_fixture(.9, True)})
        partial = report.build_snapshot(self.root)
        self.assertEqual(partial["validation"]["status"], "partial_aggregates_without_completion")
        self.assertNotIn("Completed formal arm", report.render_markdown(partial))
        self.put("runs/validation/completion.json", {"status": "completed", "joint_pass": True, "no_post_validation_tuning": True})
        finished = report.build_snapshot(self.root)
        self.assertEqual(finished["validation"]["status"], "completed")
        self.assertTrue(finished["validation"]["metrics"]["optimized"]["joint_pass"])
        self.assertIn("Completed formal arm", report.render_markdown(finished))
        outcome = report.write_report(self.root)
        self.assertLessEqual(outcome["word_count"], 2500)

    def test_formal_wrong_population_or_false_passing_count_cannot_establish_acceptance(self):
        bad = metrics_fixture(.9, True)
        bad["datasets"]["nutrition5k"]["n"] = 199
        self.put("runs/validation/metrics.json", {"baseline": metrics_fixture(1.2, True), "optimized": bad})
        self.put("runs/validation/completion.json", {"status": "completed", "joint_pass": True})
        snapshot = report.build_snapshot(self.root)
        self.assertEqual(snapshot["validation"]["status"], "aggregate_integrity_failed")
        self.assertIsNone(snapshot["validation"]["metrics"])
        bad = metrics_fixture(2, True)
        bad["passed_checks"] = 20
        self.put("runs/validation/metrics.json", {"baseline": metrics_fixture(1.2, True), "optimized": bad})
        snapshot = report.build_snapshot(self.root)
        self.assertEqual(snapshot["validation"]["status"], "aggregate_integrity_failed")
        self.assertTrue(any("passing count" in issue for issue in snapshot["issues"]))

    def test_allowlist_rejects_labels_logs_predictions_traversal_and_symlinks(self):
        reader = report.AggregateReader(self.root)
        for path in ("data/cohorts/dev_labels.json", "data/cohorts/sealed/validation_labels.json", ".env",
                     "runs/development/A/requests.jsonl", "runs/development/A/oof_predictions.json", "../v1/metrics.json"):
            with self.assertRaises(ValueError):
                reader.read(path)
        secret = self.root / "private.json"
        secret.write_text('{"sentinel":"MUST_NOT_ESCAPE"}')
        target = self.root / "runs/development/selection.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.symlink_to(secret)
        with self.assertRaises(ValueError):
            reader.read("runs/development/selection.json")

    def test_usage_preserves_reasoning_subset_and_unknown_chat_cost(self):
        self.put("runs/development/A/usage.json", {"providers": {"chat": {"requests": 2, "errors": 1,
            "prompt_tokens": 100, "completion_tokens": 40, "reasoning_tokens": 30, "total_tokens": 140},
            "embedding": {"requests": 1, "errors": 0, "prompt_tokens": 10, "completion_tokens": 0,
                          "reasoning_tokens": 0, "total_tokens": 10}}, "official_embedding_estimated_usd": .0000013,
            "third_party_cost_usd": 12345})
        usage = report.build_snapshot(self.root)["usage"]["development"]
        self.assertEqual(usage["providers"]["chat"]["total_tokens"], 140)
        self.assertEqual(usage["providers"]["chat"]["reasoning_tokens"], 30)
        self.assertIsNone(usage["third_party_cost_usd"])
        self.assertIsNone(usage["combined_actual_cost_usd"])

    def test_official_embedding_price_has_verified_source_and_is_not_an_invoice(self):
        self.put("evidence/official-embedding-price.json", {**report.OFFICIAL_EMBEDDING_PRICE,
            "ignored_extra_metadata": "MUST_NOT_ESCAPE"})
        snapshot = report.build_snapshot(self.root)
        price = snapshot["official_embedding_price"]
        self.assertEqual(price["model"], "text-embedding-3-large")
        self.assertEqual(price["route"], "https://api.openai.com/v1/embeddings")
        self.assertEqual(price["usd_per_million_input_tokens"], .13)
        self.assertEqual(price["verified_on"], "2026-11-02")
        self.assertFalse(price["third_party_chat_pricing_applicable"])
        self.assertIn("evidence/official-embedding-price.json", snapshot["source_sha256"])
        text = report.render_markdown(snapshot)
        self.assertIn("$0.13 per 1 million input tokens", text)
        self.assertIn("[official model documentation](" + price["source_url"] + ")", text)
        self.assertIn("token-based estimates, not invoices", text)
        self.assertIn("Third-party chat and combined actual cost remain unverified", text)
        self.assertNotIn("MUST_NOT_ESCAPE", json.dumps(snapshot))
        self.put("evidence/official-embedding-price.json", {**report.OFFICIAL_EMBEDDING_PRICE,
            "usd_per_million_input_tokens": .26})
        with self.assertRaisesRegex(ValueError, "price evidence differs"):
            report.build_snapshot(self.root)

    def test_imported_status_adds_no_invented_usage_and_run_totals_are_counted_once(self):
        self.put("runs/development/baseline/status.json", {
            "status": "completed", "historical_raw_import": True, "new_api_calls": 0})
        self.put("runs/development/A/usage.json", {"providers": {
            "chat": {"requests": 2, "errors": 0, "prompt_tokens": 100, "completion_tokens": 40,
                     "reasoning_tokens": 30, "total_tokens": 140},
            "embedding": {"requests": 1, "errors": 0, "prompt_tokens": 1000, "completion_tokens": 0,
                          "reasoning_tokens": 0, "total_tokens": 1000}},
            "official_embedding_estimated_usd": .00013})
        usage = report.build_snapshot(self.root)["usage"]["development"]
        self.assertEqual(usage["aggregate_run_count"], 1)
        self.assertEqual([r["run"] for r in usage["runs"]], ["A"])
        self.assertEqual(usage["providers"]["chat"]["total_tokens"], 140)
        self.assertAlmostEqual(usage["official_embedding_estimated_usd"], .00013)
        text = report.render_markdown(report.build_snapshot(self.root))
        self.assertIn("Usage covers provider-reported fields from newly logged v2 HTTP attempts; "
            "historical imports, reused cache, and original corpus creation are excluded. "
            "Lost responses or unavailable usage fields can undercount tokens, so these totals are not a billing total. "
            "Error counts record HTTP or connection failures, not all structured-output failures.", text)

    def test_generation_writes_only_report_artifacts(self):
        self.development()
        before = {str(p.relative_to(self.root)): hashlib.sha256(p.read_bytes()).hexdigest()
                  for p in self.root.rglob("*") if p.is_file()}
        report.write_report(self.root)
        for name, digest in before.items():
            self.assertEqual(hashlib.sha256((self.root / name).read_bytes()).hexdigest(), digest)
        after = {str(p.relative_to(self.root)) for p in self.root.rglob("*") if p.is_file()}
        self.assertEqual(after - before.keys(), {report.OUTPUT_MARKDOWN, report.OUTPUT_SNAPSHOT})

    def test_history_counts_and_running_candidate_are_explicit(self):
        old = metrics_fixture()
        old["datasets"]["asa24"]["exact_n"] = 17
        old["datasets"]["asa24"]["primary"]["n"] = 17
        old["datasets"]["nutrition5k"]["n"] = 100
        old["datasets"]["nutrition5k"]["primary"]["n"] = 100
        self.put("analysis/historical_summary.json", {"v1_development": old})
        self.put("runs/development/B/status.json", {"status": "running"})
        text = report.render_markdown(report.build_snapshot(self.root))
        self.assertIn("99 / 17", text)
        self.assertIn("100 / 100", text)
        self.assertIn("B | pending | running", text)

    def test_one_group_does_not_publish_a_degenerate_interval(self):
        self.development()
        selection = json.loads((self.root / "runs/development/selection.json").read_text())
        selection["metrics"]["datasets"]["nutrition5k"]["bootstrap"]["group_count"] = 1
        self.put("runs/development/selection.json", selection)
        projected = report.build_snapshot(self.root)["development"]["metrics"]["datasets"]["nutrition5k"]["bootstrap"]
        self.assertIsNone(projected["intervals"]["weight.mae"]["low"])
        self.assertEqual(projected["intervals"]["weight.mae"]["valid_replicates"], 0)

    def test_integer_format_preserves_zero_and_trailing_zero_digits(self):
        for n in (0, 10, 20, 100, 200, 10000):
            self.assertEqual(report.fmt(n, 0), str(n))
        self.assertEqual(report.fmt(1.200, 3), "1.2")
        self.assertEqual(report.fmt(-10, 0), "-10")

    def test_recognition_size_and_success_subset_metrics_are_projected(self):
        self.development()
        selection = json.loads((self.root / "runs/development/selection.json").read_text())
        asa = selection["metrics"]["datasets"]["asa24"]
        asa.update(first_rate=.1, retrieval_exact_rate=.8, average_final_code_count=2.2,
            by_size={size: {"n": 33, "exact_n": 5, "exact_rate": 5 / 33, "first_n": 3,
                           "first_rate": 3 / 33, "conditional": deepcopy(asa["primary"]),
                           "e2e": deepcopy(asa["e2e"]), "raw_response": "MUST_NOT_ESCAPE"}
                     for size in ("smallest", "medium", "largest")})
        n5 = selection["metrics"]["datasets"]["nutrition5k"]
        n5["native_subset"] = deepcopy(n5["primary"])
        n5["complete_subset"] = deepcopy(n5["primary"])
        self.put("runs/development/selection.json", selection)
        snapshot = report.build_snapshot(self.root)
        result = snapshot["development"]["metrics"]["datasets"]
        self.assertEqual(result["asa24"]["average_final_code_count"], 2.2)
        self.assertEqual(len(result["asa24"]["by_size"]["smallest"]["conditional"]["metrics"]), 5)
        self.assertIn("complete_subset", result["nutrition5k"])
        text = report.render_markdown(snapshot)
        self.assertIn("smallest", text)
        self.assertIn("Native subset", text)
        self.assertIn("First-code rate is 0.1", text)
        self.assertNotIn("MUST_NOT_ESCAPE", json.dumps(snapshot))
        for line in text.splitlines():
            if line.startswith("| "):
                self.assertLessEqual(line.count("|") - 1, 6)

    def diagnostics(self):
        primary = metrics_fixture()["datasets"]["nutrition5k"]["primary"]
        self.put("analysis/diagnostics_v2.json", {
            "median_baseline": {"score": primary},
            "same_population_comparison": {"n": 84, "baseline": primary, "selected": primary,
                "selected_mean_signed_error": dict.fromkeys(report.KEYS, -2),
                "paired_bootstrap": {"groups": 78, "replicates": 10000, "intervals": {
                    k + "." + stat: {"low": -10, "high": -1, "valid_replicates": 10000}
                    for k in report.KEYS for stat in ("mae", "per_unit")}}},
            "oracle_weight_diagnostic": {"uses_reference_weight": True, "not_a_model_or_acceptance_result": True,
                "population_n": 84, "scored_n": 84, "excluded_nonpositive_weight_n": 0, "score": primary},
            "predictions": ["MUST_NOT_ESCAPE"]})

    def test_diagnostics_require_completion_and_preserve_negative_paired_differences(self):
        self.diagnostics()
        early = report.build_snapshot(self.root)
        self.assertIsNone(early["diagnostics"])
        self.assertNotIn("analysis/diagnostics_v2.json", early["source_sha256"])
        self.development()
        snapshot = report.build_snapshot(self.root)
        diagnostic = snapshot["diagnostics"]
        self.assertEqual(diagnostic["same_population_comparison"]["paired_bootstrap"]["intervals"]["weight.mae"]["low"], -10)
        self.assertEqual(diagnostic["same_population_comparison"]["selected_mean_signed_error"]["fat"], -2)
        text = report.render_markdown(snapshot)
        self.assertIn("-10 to -1", text)
        self.assertIn("not a feasible model, candidate, or acceptance result", text)
        self.assertNotIn("MUST_NOT_ESCAPE", json.dumps(snapshot))
        self.assertLessEqual(len(re.findall(r"\b[\w]+(?:[-'][\w]+)*\b", text)), 3000)

    def test_wrong_diagnostic_population_is_not_shown_as_paired_comparison(self):
        self.development()
        self.diagnostics()
        path = self.root / "analysis/diagnostics_v2.json"
        diagnostic = json.loads(path.read_text())
        diagnostic["same_population_comparison"]["n"] = 100
        self.put("analysis/diagnostics_v2.json", diagnostic)
        snapshot = report.build_snapshot(self.root)
        self.assertIsNone(snapshot["diagnostics"])
        self.assertTrue(any("common image population" in issue for issue in snapshot["issues"]))

    def test_asa_common_exact_projection_is_explanatory_and_preserves_registered_scores(self):
        self.development()
        self.diagnostics()
        before = report.build_snapshot(self.root)["development"]["metrics"]
        path = self.root / "analysis/diagnostics_v2.json"
        diagnostic = json.loads(path.read_text())
        primary = deepcopy(metrics_fixture()["datasets"]["asa24"]["primary"])
        primary["n"] = primary["available_n"] = 12
        diagnostic["asa24_common_exact_comparison"] = {"diagnostic_only": True, "population_n": 99,
            "n": 12, "groups": 6, "baseline_exact_n": 17, "selected_exact_n": 15,
            "baseline_only_exact_n": 5, "selected_only_exact_n": 3,
            "baseline": primary, "selected": primary, "sample_ids": ["MUST_NOT_ESCAPE"],
            "paired_bootstrap": {"groups": 6, "replicates": 10000, "intervals": {
                k + "." + stat: {"low": -4, "high": -1, "valid_replicates": 10000}
                for k in report.KEYS for stat in ("mae", "per_unit")}}}
        self.put("analysis/diagnostics_v2.json", diagnostic)
        snapshot = report.build_snapshot(self.root)
        self.assertEqual(snapshot["development"]["metrics"], before)
        common = snapshot["diagnostics"]["asa24_common_exact_comparison"]
        self.assertEqual(common["baseline"]["n"], common["selected"]["n"])
        self.assertEqual(common["paired_bootstrap"]["intervals"]["fat.per_unit"]["low"], -4)
        text = report.render_markdown(snapshot)
        self.assertIn("same 12 images in 6 groups", text)
        self.assertIn("cannot influence selection or acceptance", text)
        self.assertNotIn("MUST_NOT_ESCAPE", json.dumps(snapshot))
        diagnostic["asa24_common_exact_comparison"]["groups"] = 1
        diagnostic["asa24_common_exact_comparison"]["paired_bootstrap"]["groups"] = 1
        self.put("analysis/diagnostics_v2.json", diagnostic)
        single = report.build_snapshot(self.root)["diagnostics"]["asa24_common_exact_comparison"]
        self.assertIsNone(single["paired_bootstrap"]["intervals"])
        diagnostic["asa24_common_exact_comparison"]["selected"] = {**primary, "n": 11}
        self.put("analysis/diagnostics_v2.json", diagnostic)
        invalid = report.build_snapshot(self.root)
        self.assertIsNone(invalid["diagnostics"]["asa24_common_exact_comparison"])
        self.assertTrue(any("common Exact diagnostic" in issue for issue in invalid["issues"]))

    def test_calibration_snapshot_keeps_all_raw_attempted_and_retained_metrics(self):
        self.development()
        snapshot = report.build_snapshot(self.root)
        candidate = snapshot["development"]["candidates"][0]
        for variant, ratio in (("raw_metrics", 2.1), ("calibrated_metrics", 2), ("retained_metrics", 2)):
            self.assertEqual(len(candidate[variant]["checks"]), 20)
            for check in candidate[variant]["checks"]:
                self.assertAlmostEqual(check["ratio_to_threshold"], ratio)
        text = report.render_markdown(snapshot)
        self.assertIn("Calibration comparison for A", text)
        self.assertIn("fold-specific fits", text)

    def test_incomplete_primary_population_cannot_establish_formal_acceptance(self):
        bad = metrics_fixture(.9, True)
        bad["datasets"]["nutrition5k"]["primary"]["available_n"] = 199
        self.put("runs/validation/metrics.json", {"baseline": metrics_fixture(1.2, True), "optimized": bad})
        self.put("runs/validation/completion.json", {"status": "completed", "joint_pass": True})
        snapshot = report.build_snapshot(self.root)
        self.assertEqual(snapshot["validation"]["status"], "aggregate_integrity_failed")
        self.assertIsNone(snapshot["validation"]["metrics"])


if __name__ == "__main__":
    unittest.main()
