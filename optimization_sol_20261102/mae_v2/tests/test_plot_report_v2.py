"""Synthetic aggregate-only tests; no labels, study outputs or plot files read."""
import copy
import importlib.util
import io
import json
from pathlib import Path
import shutil
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import plot_report_v2 as plot


def snapshot():
    score = {"datasets": {}}
    limits = {}
    for dataset, count in (("asa24", 99), ("nutrition5k", 84)):
        limits[dataset] = {target: {"mae": 10.0, "per_unit": 0.2} for target in plot.TARGETS}
        score["datasets"][dataset] = {"n": count, "primary": {"n": 16 if dataset == "asa24" else count,
            "metrics": {target: {"mae": 5.0, "per_unit": 0.3, "threshold_mae": 10.0,
                                  "threshold_per_unit": 0.2} for target in plot.TARGETS}}}
    return {"schema_version": 2, "scope": plot.REPORT_SCOPE, "issues": [], "thresholds": limits,
            "development": {"status": "development_targets_not_met", "metrics": score},
            "validation": {"status": "not_run_or_not_completed", "metrics": None},
            "source_sha256": {"must-not-be-opened/labels.json": "ignored provenance"}}


class AggregateTransformTests(unittest.TestCase):
    def test_exact_twenty_fixed_order_primary_metrics(self):
        data = plot.prepare_plot(snapshot())
        self.assertEqual(data.scope, "development")
        self.assertIn("not independent", data.caveat)
        self.assertEqual([p.dataset for p in data.panels], ["asa24", "nutrition5k"])
        for panel in data.panels:
            self.assertEqual(len(panel.points), 10)
            self.assertEqual([(p.target, p.statistic) for p in panel.points],
                             [(key, stat) for key in plot.TARGETS for stat in plot.STATISTICS])
            self.assertEqual(panel.points[0].ratio, 0.5)
            self.assertAlmostEqual(panel.points[1].ratio, 1.5)
            self.assertEqual(sum(p.passes is True for p in panel.points), 5)
        self.assertEqual((data.panels[0].primary_n, data.panels[0].total_n), (16, 99))

    def test_unrounded_decisions_ignore_stored_pass_and_ratio(self):
        raw = snapshot()
        metric = raw["development"]["metrics"]["datasets"]["asa24"]["primary"]["metrics"]["weight"]
        metric.update(mae=10.0000000001, pass_mae=True, ratio_to_threshold=0)
        point = plot.prepare_plot(raw).panels[0].points[0]
        self.assertFalse(point.passes)
        self.assertGreater(point.ratio, 1)
        self.assertEqual(plot.ratio_label(point), ">1")
        metric["mae"] = 9.9999999999
        point = plot.prepare_plot(raw).panels[0].points[0]
        self.assertTrue(point.passes)
        self.assertEqual(plot.ratio_label(point), "<1")
        metric["mae"] = 10.0
        self.assertEqual(plot.ratio_label(plot.prepare_plot(raw).panels[0].points[0]), "1")

    def test_missing_and_invalid_metrics_are_missing_never_zero(self):
        for value in (None, True, "0.1", -1, float("nan"), float("inf")):
            with self.subTest(value=value):
                raw = snapshot()
                raw["development"]["metrics"]["datasets"]["asa24"]["primary"]["metrics"]["weight"]["mae"] = value
                point = plot.prepare_plot(raw).panels[0].points[0]
                self.assertIsNone(point.ratio)
                self.assertIsNone(point.passes)
                self.assertEqual(plot.ratio_label(point), "missing")

    def test_missing_dataset_still_has_ten_explicit_missing_positions(self):
        raw = snapshot()
        del raw["development"]["metrics"]["datasets"]["nutrition5k"]
        panel = plot.prepare_plot(raw).panels[1]
        self.assertEqual(len(panel.points), 10)
        self.assertTrue(all(p.ratio is None for p in panel.points))
        self.assertIsNone(panel.primary_n)

    def test_zero_is_a_real_passing_point(self):
        raw = snapshot()
        raw["development"]["metrics"]["datasets"]["asa24"]["primary"]["metrics"]["weight"]["mae"] = 0
        point = plot.prepare_plot(raw).panels[0].points[0]
        self.assertEqual(point.ratio, 0)
        self.assertTrue(point.passes)
        self.assertEqual(plot.ratio_label(point), "0")

    def test_running_development_and_wrong_schema_are_rejected(self):
        for status in ("development_in_progress", "development_not_started", "failed", "completed"):
            raw = snapshot()
            raw["development"]["status"] = status
            with self.subTest(status=status), self.assertRaisesRegex(ValueError, "finished"):
                plot.prepare_plot(raw)
        raw = snapshot()
        raw["scope"] = "raw_predictions"
        with self.assertRaisesRegex(ValueError, "aggregate report"):
            plot.prepare_plot(raw)

    def test_formal_uses_optimized_arm_and_requires_verification(self):
        raw = snapshot()
        formal_score = copy.deepcopy(raw["development"]["metrics"])
        formal_score["datasets"]["nutrition5k"]["n"] = 200
        formal_score["datasets"]["nutrition5k"]["primary"]["n"] = 200
        raw["validation"] = {"status": "completed", "aggregate_integrity_verified": True,
                             "metrics": {"baseline": {}, "optimized": formal_score}}
        result = plot.prepare_plot(raw)
        self.assertEqual(result.scope, "formal")
        self.assertIn("formal validation", result.scope_label)
        self.assertEqual(result.panels[1].primary_n, 200)
        raw["validation"]["aggregate_integrity_verified"] = False
        with self.assertRaisesRegex(ValueError, "verified completed"):
            plot.prepare_plot(raw)

    def test_partial_formal_is_not_silently_swapped_for_development(self):
        raw = snapshot()
        raw["validation"]["status"] = "partial_aggregates_without_completion"
        with self.assertRaisesRegex(ValueError, "silently"):
            plot.prepare_plot(raw)
        self.assertEqual(plot.prepare_plot(raw, "development").scope, "development")

    def test_integrity_issues_and_inconsistent_caps_stop_plotting(self):
        raw = snapshot()
        raw["issues"] = ["inconsistent population"]
        with self.assertRaisesRegex(ValueError, "integrity"):
            plot.prepare_plot(raw)
        raw = snapshot()
        raw["thresholds"]["asa24"]["weight"]["mae"] = 0
        with self.assertRaisesRegex(ValueError, "invalid registered cap"):
            plot.prepare_plot(raw)
        raw = snapshot()
        raw["development"]["metrics"]["datasets"]["asa24"]["primary"]["metrics"]["weight"]["threshold_mae"] = 11
        with self.assertRaisesRegex(ValueError, "Conflicting"):
            plot.prepare_plot(raw)

    def test_shared_axis_is_zero_based_and_never_clips_data_or_cap(self):
        data = plot.prepare_plot(snapshot())
        upper, ticks = plot.shared_axis(data)
        self.assertEqual(ticks[0], 0)
        self.assertGreater(upper, max(p.ratio for panel in data.panels for p in panel.points))
        self.assertGreater(upper, 1)
        self.assertEqual(ticks[-1], upper)

    def test_read_boundary_opens_only_supplied_snapshot(self):
        blob = json.dumps(snapshot()).encode()
        with patch.object(Path, "read_bytes", return_value=blob) as read, \
             patch.object(Path, "write_bytes") as write, patch.object(Path, "mkdir"), \
             patch.object(plot, "pdf_bytes", return_value=b"PDF") as vector, \
             patch.object(plot, "rasterize_pdf", return_value=b"PNG"):
            receipt = plot.create_plot("synthetic-report.json")
        read.assert_called_once_with()
        self.assertEqual(write.call_count, 2)
        vector.assert_called_once()
        self.assertEqual(receipt["scope"], "development")
        self.assertEqual(len(receipt["source_sha256"]), 64)
        self.assertEqual(receipt["within_cap"], {"asa24": 5, "nutrition5k": 5})

    def test_running_snapshot_never_renders_or_writes(self):
        raw = snapshot()
        raw["development"]["status"] = "development_in_progress"
        with patch.object(Path, "read_bytes", return_value=json.dumps(raw).encode()), \
             patch.object(Path, "write_bytes") as write, patch.object(plot, "pdf_bytes") as vector:
            with self.assertRaisesRegex(ValueError, "finished"):
                plot.create_plot("synthetic-report.json")
        write.assert_not_called()
        vector.assert_not_called()


@unittest.skipUnless(importlib.util.find_spec("reportlab"), "Use bundled Python for optional plotting tests")
class InMemoryDrawingTests(unittest.TestCase):
    def test_two_panels_and_missing_text_exist_in_vector_drawing(self):
        raw = snapshot()
        raw["development"]["metrics"]["datasets"]["asa24"]["primary"]["metrics"]["weight"]["mae"] = None
        drawing = plot.build_drawing(plot.prepare_plot(raw), "a" * 64)
        texts = [getattr(item, "text", "") for item in drawing.contents]
        self.assertIn("A  ASA24", texts)
        self.assertIn("B  Nutrition5k", texts)
        self.assertIn("missing", texts)
        self.assertIn("4/10 within cap; 1 missing", texts)
        self.assertIn("Cap = 1; decisions use unrounded values", texts)
        self.assertEqual(sum(t == "Weight / abs." for t in texts), 2)
        self.assertEqual(sum(t == "Protein / unit" for t in texts), 2)

    @unittest.skipUnless(shutil.which("pdftoppm") and importlib.util.find_spec("PIL"), "Optional Poppler/Pillow smoke check")
    def test_pdf_and_png_render_in_memory_without_files(self):
        from PIL import Image
        vector = plot.pdf_bytes(plot.prepare_plot(snapshot()))
        self.assertTrue(vector.startswith(b"%PDF"))
        self.assertIn(b"/FontFile2", vector)
        png = plot.rasterize_pdf(vector, dpi=72)
        raster = Image.open(io.BytesIO(png))
        self.assertEqual(raster.size, (540, 390))


if __name__ == "__main__":
    unittest.main()
