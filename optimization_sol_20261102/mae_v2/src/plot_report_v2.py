#!/usr/bin/env python3
"""Optional publication figure from one completed aggregate report JSON only.

No inference modules, predictions, labels, referenced source paths or credentials
are opened. The pure transform recomputes ratios and pass decisions from the
full-precision primary metric and registered cap. Missing metrics stay missing.
The scope must be completed development or verified completed formal validation;
development selection is never labeled independent validation.

Plotting uses ReportLab (available in the bundled document runtime) for a vector
PDF and Poppler's pdftoppm on stdin for the matching 300-dpi PNG. Neither plotting
dependency is required by the portable inference demo. There is no network or
package installation. The helper does not edit Markdown or DOCX reports.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
import shutil
import subprocess


DATASETS = ("asa24", "nutrition5k")
TARGETS = ("weight", "energy", "fat", "carbs", "protein")
STATISTICS = ("mae", "per_unit")
TARGET_LABELS = {"weight": "Weight", "energy": "Energy", "fat": "Total fat",
                 "carbs": "Carbohydrate", "protein": "Protein"}
REPORT_SCOPE = "aggregate_only_report_not_an_independent_code_or_provenance_review"
FINAL_DEVELOPMENT_STATES = {"ready_for_review", "development_targets_not_met"}
OUTPUT_STEM = "DietAI24_MAE_v2_Ratios"


@dataclass(frozen=True)
class Point:
    dataset: str
    target: str
    statistic: str
    value: float | None
    cap: float
    ratio: float | None
    passes: bool | None

    @property
    def label(self):
        return TARGET_LABELS[self.target] + (" / abs." if self.statistic == "mae" else " / unit")


@dataclass(frozen=True)
class Panel:
    dataset: str
    total_n: int | None
    primary_n: int | None
    points: tuple[Point, ...]


@dataclass(frozen=True)
class FigureData:
    scope: str
    scope_label: str
    caveat: str
    panels: tuple[Panel, ...]


def _number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return value if math.isfinite(value) and value >= 0 else None


def _count(value):
    value = _number(value)
    return int(value) if value is not None and int(value) == value else None


def _mapping(value):
    return value if isinstance(value, dict) else {}


def prepare_plot(snapshot, scope="auto") -> FigureData:
    """Pure projection of 20 primary aggregate metrics, never their stored flags."""
    if not isinstance(snapshot, dict) or snapshot.get("schema_version") != 2 or snapshot.get("scope") != REPORT_SCOPE:
        raise ValueError("Expected a v2 aggregate report snapshot")
    if snapshot.get("issues"):
        raise ValueError("Resolve aggregate integrity issues before publishing a figure")
    if scope not in {"auto", "development", "formal"}:
        raise ValueError("Scope must be auto, development, or formal")
    development, formal = _mapping(snapshot.get("development")), _mapping(snapshot.get("validation"))
    if scope == "auto":
        if formal.get("status") == "completed":
            scope = "formal"
        elif formal.get("status") in {None, "not_run_or_not_completed"}:
            scope = "development"
        else:
            raise ValueError("Partial or inconsistent formal results cannot be silently replaced by development results")
    if scope == "formal":
        if formal.get("status") != "completed" or formal.get("aggregate_integrity_verified") is not True:
            raise ValueError("Formal plotting requires verified completed formal aggregates")
        selected = _mapping(_mapping(formal.get("metrics")).get("optimized"))
        label = "Completed formal validation - optimized arm"
        caveat = "Frozen formal population; ASA24 is Exact-conditioned, not an end-to-end nutrient task."
    else:
        if development.get("status") not in FINAL_DEVELOPMENT_STATES:
            raise ValueError("Development selection must be finished before plotting results")
        selected = _mapping(development.get("metrics"))
        label = "Completed development - selected out-of-fold estimates"
        caveat = "Selection-exposed development estimates; this is not independent formal validation."
    panels = []
    for dataset in DATASETS:
        source = _mapping(_mapping(selected.get("datasets")).get(dataset))
        primary = _mapping(source.get("primary"))
        metrics = _mapping(primary.get("metrics"))
        points = []
        for target in TARGETS:
            entry = _mapping(metrics.get(target))
            limits = _mapping(_mapping(snapshot.get("thresholds")).get(dataset))
            limits = _mapping(limits.get(target))
            for statistic in STATISTICS:
                cap = _number(limits.get(statistic))
                if cap is None or cap <= 0:
                    raise ValueError(f"Missing or invalid registered cap: {dataset}/{target}/{statistic}")
                declared = entry.get("threshold_" + statistic)
                if declared is not None and (_number(declared) is None or declared != cap):
                    raise ValueError(f"Conflicting registered cap: {dataset}/{target}/{statistic}")
                value = _number(entry.get(statistic))
                ratio = value / cap if value is not None else None
                if ratio is not None and not math.isfinite(ratio):
                    raise ValueError("MAE-to-cap ratio is not finite")
                points.append(Point(dataset, target, statistic, value, cap, ratio,
                                    value <= cap if value is not None else None))
        panels.append(Panel(dataset, _count(source.get("n")), _count(primary.get("n")), tuple(points)))
    return FigureData(scope, label, caveat, tuple(panels))


def ratio_label(point: Point) -> str:
    if point.ratio is None:
        return "missing"
    value = f"{point.ratio:.3g}"
    # A rounded label must never make an above-cap point look exactly on cap.
    if value == "1" and point.value != point.cap:
        return "<1" if point.passes else ">1"
    return value


def shared_axis(data: FigureData):
    """Use the same zero-based, unclipped linear ratio scale in both panels."""
    maximum = max([1.0] + [p.ratio for panel in data.panels for p in panel.points if p.ratio is not None])
    goal = maximum * 1.12
    raw_step = goal / 4
    magnitude = 10 ** math.floor(math.log10(raw_step))
    step = next(scale * magnitude for scale in (1, 2, 2.5, 5, 10) if scale * magnitude >= raw_step)
    upper = math.ceil(goal / step) * step
    return upper, tuple(i * step for i in range(round(upper / step) + 1))


def build_drawing(data: FigureData, source_sha256=""):
    """Build a vector chart in memory, without reading or writing report data."""
    try:
        from reportlab.graphics.shapes import Circle, Drawing, Line, Rect, String
        from reportlab.lib.colors import HexColor
        from reportlab import __file__ as reportlab_file
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
    except ModuleNotFoundError as exc:
        raise RuntimeError("Optional figure generation requires ReportLab; use the bundled workspace Python runtime") from exc
    # Embed the redistributable fonts shipped with ReportLab. Standard PDF
    # Helvetica substitution can distort character spacing across platforms.
    font_directory = Path(reportlab_file).resolve().parent / "fonts"
    for name, filename in (("ReportFigureSans", "Vera.ttf"), ("ReportFigureSansBold", "VeraBd.ttf")):
        if name not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont(name, str(font_directory / filename)))
    width, height = 540, 390
    drawing = Drawing(width, height)
    black, muted, grid = map(HexColor, ("#171717", "#5E6671", "#DFE3E8"))
    below, above = map(HexColor, ("#247BA0", "#C4511D"))
    drawing.add(Rect(0, 0, width, height, fillColor=HexColor("#FFFFFF"), strokeColor=None))

    def text(x, y, value, size=8.5, bold=False, color=black, anchor="start"):
        drawing.add(String(x, y, value, fontName="ReportFigureSansBold" if bold else "ReportFigureSans",
                           fontSize=size, fillColor=color, textAnchor=anchor))

    text(20, 369, "Selected primary MAE relative to registered caps", 14, True)
    text(20, 351, data.scope_label, 9.5)
    upper, ticks = shared_axis(data)
    for panel_index, panel in enumerate(data.panels):
        left = 20 + panel_index * 264
        plot_left, plot_width = left + 79, 126
        plot_bottom, plot_top = 107, 296
        title = "ASA24" if panel.dataset == "asa24" else "Nutrition5k"
        text(left, 326, ("A  " if panel_index == 0 else "B  ") + title, 11, True)
        n = "missing" if panel.primary_n is None else str(panel.primary_n)
        if panel.dataset == "asa24":
            total = "missing" if panel.total_n is None else str(panel.total_n)
            text(left, 312, f"Exact-conditioned; primary n={n}, total n={total}", 8, color=muted)
        else:
            text(left, 312, f"All-image primary MAE; n={n}", 8, color=muted)
        for tick in ticks:
            x = plot_left + plot_width * tick / upper
            drawing.add(Line(x, plot_bottom, x, plot_top, strokeColor=grid, strokeWidth=0.5))
            text(x, 94, f"{tick:g}", 8, color=muted, anchor="middle")
        cap_x = plot_left + plot_width / upper
        drawing.add(Line(cap_x, plot_bottom, cap_x, plot_top, strokeColor=black,
                         strokeWidth=1, strokeDashArray=[3, 2]))
        for index, point in enumerate(panel.points):
            y = 287 - index * 19
            text(plot_left - 6, y - 2.8, point.label, 8, anchor="end")
            if point.ratio is None:
                text(plot_left + 3, y - 2.8, "missing", 8, color=muted)
                continue
            x = plot_left + plot_width * point.ratio / upper
            color = below if point.passes else above
            drawing.add(Line(plot_left, y, x, y, strokeColor=color, strokeWidth=1.25))
            drawing.add(Circle(x, y, 2.7, fillColor=color, strokeColor=HexColor("#FFFFFF"), strokeWidth=0.5))
            text(plot_left + plot_width + 8, y - 2.8, ratio_label(point), 8, color=color)
        text(plot_left + plot_width / 2, 78, "MAE / cap (lower is better)", 8, anchor="middle")
        passed = sum(p.passes is True for p in panel.points)
        missing = sum(p.ratio is None for p in panel.points)
        text(left, 61, f"{passed}/10 within cap; {missing} missing", 8.5, True)
    drawing.add(Circle(23, 43, 2.7, fillColor=below, strokeColor=None))
    text(30, 40, "At or below cap", 8)
    drawing.add(Circle(127, 43, 2.7, fillColor=above, strokeColor=None))
    text(134, 40, "Above cap", 8)
    drawing.add(Line(204, 43, 218, 43, strokeColor=black, strokeWidth=1, strokeDashArray=[3, 2]))
    text(224, 40, "Cap = 1; decisions use unrounded values", 8)
    text(20, 26, data.caveat, 7.5, color=muted)
    text(20, 14, "Abs. = absolute MAE; unit = per-unit MAE. Recognition and uncertainty intervals are separate.", 7.5, color=muted)
    if source_sha256:
        text(20, 3, "Aggregate SHA-256: " + source_sha256, 6.5, color=muted)
    return drawing


def pdf_bytes(data: FigureData, source_sha256="") -> bytes:
    from reportlab.graphics import renderPDF
    return renderPDF.drawToString(build_drawing(data, source_sha256))


def rasterize_pdf(pdf: bytes, dpi=300, executable="pdftoppm") -> bytes:
    if isinstance(dpi, bool) or not isinstance(dpi, int) or not 72 <= dpi <= 600:
        raise ValueError("PNG resolution must be an integer from 72 to 600 dpi")
    program = shutil.which(executable)
    if program is None:
        raise RuntimeError("Optional PNG generation requires Poppler pdftoppm on PATH")
    result = subprocess.run([program, "-singlefile", "-png", "-r", str(dpi)],
                            input=pdf, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            check=True, timeout=60)
    if not result.stdout.startswith(b"\x89PNG\r\n\x1a\n"):
        raise RuntimeError("Rasterizer did not return a PNG")
    return result.stdout


def create_plot(snapshot_path, output_prefix=None, scope="auto", dpi=300):
    """Read only the explicit snapshot; all source_sha256 paths remain inert."""
    source = Path(snapshot_path)
    blob = source.read_bytes()
    snapshot = json.loads(blob, parse_constant=lambda _: (_ for _ in ()).throw(ValueError("Nonfinite JSON aggregate")))
    data = prepare_plot(snapshot, scope)
    digest = hashlib.sha256(blob).hexdigest()
    prefix = Path(output_prefix) if output_prefix is not None else source.with_name(OUTPUT_STEM)
    if prefix.suffix:
        raise ValueError("Output prefix must not have a filename extension")
    outputs = [prefix.with_suffix(".pdf"), prefix.with_suffix(".png")]
    if any(p.resolve() == source.resolve() or p.is_symlink() for p in outputs):
        raise ValueError("Figure outputs cannot replace the input or a symlink")
    vector = pdf_bytes(data, digest)
    raster = rasterize_pdf(vector, dpi)
    prefix.parent.mkdir(parents=True, exist_ok=True)
    for path, content in zip(outputs, (vector, raster)):
        path.write_bytes(content)
    return {"pdf": str(outputs[0]), "png": str(outputs[1]), "scope": data.scope,
            "scope_label": data.scope_label, "source_sha256": digest,
            "within_cap": {p.dataset: sum(x.passes is True for x in p.points) for p in data.panels},
            "missing": {p.dataset: sum(x.ratio is None for x in p.points) for p in data.panels}}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("snapshot", type=Path, help="Completed aggregate report JSON")
    parser.add_argument("--output-prefix", type=Path, help="Optional path without extension")
    parser.add_argument("--scope", choices=("auto", "development", "formal"), default="auto")
    parser.add_argument("--dpi", type=int, default=300)
    args = parser.parse_args(argv)
    print(json.dumps(create_plot(args.snapshot, args.output_prefix, args.scope, args.dpi), indent=2))


if __name__ == "__main__":
    main()
