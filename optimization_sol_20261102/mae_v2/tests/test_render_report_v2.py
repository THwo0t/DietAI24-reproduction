"""Synthetic-only parser and in-memory OOXML tests; never save a DOCX/PDF."""
from __future__ import annotations

from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import render_report_v2 as render


SYNTHETIC = """# DietAI24 synthetic report

Generated: synthetic-only timestamp

## 1. Scope

All **20 checks** and *two arms* remain visible. See [paper source](https://example.invalid/paper?id=1&section=2).
The `runs/development/asa-retrieval-portion/calibration-summary.json` path is retained.

## 2. Outcomes

| Candidate | Population | N | Error | Gate | Source |
| --- | --- | ---: | ---: | :---: | --- |
| A | Nutrition5k | 200 | 0.12500 | pass | [record](https://example.invalid/record) |
| examples-2 | ASA24 | 78 | 1.00000 | fail | `evidence/audit_summary.json` |

### Notes

- First bullet with **evidence**.
- Second bullet.
1. First numbered step.
2. Second numbered step.

> Quoted interpretation remains visible.

```text
one = 20
two = 200
```
"""


def visible(element):
    return "".join(element.itertext()) if render.Document is None else "".join(
        item.text or "" for item in element.iter(render.qn("w:t"))).replace(render.BREAK, "")


class MarkdownParsingTests(unittest.TestCase):
    def test_report_structure_and_every_table_field(self):
        blocks = render.parse_markdown(SYNTHETIC)
        self.assertEqual([b.text for b in blocks if b.kind == "heading"],
                         ["DietAI24 synthetic report", "1. Scope", "2. Outcomes", "Notes"])
        table = next(b for b in blocks if b.kind == "table")
        self.assertEqual(table.rows[0], ["Candidate", "Population", "N", "Error", "Gate", "Source"])
        self.assertEqual(len(table.rows), 3)
        self.assertEqual(table.rows[1][2:5], ["200", "0.12500", "pass"])
        self.assertEqual(table.rows[2][2:5], ["78", "1.00000", "fail"])
        self.assertEqual(table.alignment, [None, None, "right", "right", "center", None])
        self.assertEqual([b.marker for b in blocks if b.kind == "list"], ["•", "•", "1.", "2."])
        self.assertEqual(next(b.text for b in blocks if b.kind == "code"), "one = 20\ntwo = 200")

    def test_escaped_pipes_and_code_pipes_do_not_drop_cells(self):
        line = r"| a\|b | `c|d` | ``a`b|c`` | 0 |"
        self.assertEqual(render.split_table_row(line), [r"a\|b", "`c|d`", "``a`b|c``", "0"])
        self.assertEqual("".join(s.text for s in render.inline_spans(r"a\|b")), "a|b")

    def test_ragged_tables_raise_before_document_construction(self):
        for text in ("| a | b |\n| --- | --- |\n| 1 | 2 | 3 |",
                     "| a | b | c |\n| --- | --- |"):
            with self.subTest(text=text), self.assertRaisesRegex(ValueError, "width"):
                render.parse_markdown(text)

    def test_one_column_and_empty_cell_are_preserved(self):
        table = render.parse_markdown("| One |\n| --- |\n| |\n| zero |")
        self.assertEqual(table[0].rows, [["One"], [""], ["zero"]])

    def test_unknown_syntax_is_visible_and_code_fence_must_close(self):
        text = "Unknown <tag>literal</tag> and $x^2$."
        self.assertEqual(render.parse_markdown(text)[0].text, text)
        self.assertEqual("".join(s.text for s in render.inline_spans(text)), text)
        with self.assertRaisesRegex(ValueError, "Unclosed"):
            render.parse_markdown("```text\nnot closed")

    def test_heading_closing_marks_do_not_corrupt_literal_hash(self):
        blocks = render.parse_markdown("# C#\n\n## Heading ##")
        self.assertEqual([b.text for b in blocks], ["C#", "Heading"])

    def test_links_keep_destinations_and_formatted_labels(self):
        spans = render.inline_spans('[**Paper** source](https://example.invalid/a_(b)?x=1&amp;y=2 "Title")')
        self.assertEqual("".join(s.text for s in spans), "Paper source")
        self.assertTrue(spans[0].bold)
        self.assertEqual({s.target for s in spans}, {"https://example.invalid/a_(b)?x=1&y=2"})
        auto = render.inline_spans("<https://example.invalid/source>")[0]
        self.assertEqual(auto.target, auto.text)

    def test_underscores_and_code_keep_literal_content(self):
        spans = render.inline_spans("**complete_subset** uses `a_b/*literal*/file.json`.")
        self.assertEqual("".join(s.text for s in spans), "complete_subset uses a_b/*literal*/file.json.")
        self.assertEqual([s.text for s in spans if s.code], ["a_b/*literal*/file.json"])
        self.assertTrue(spans[0].bold)

    def test_hard_and_soft_breaks(self):
        spans = render.inline_spans("soft\nline  \nhard<br/>next\\\nlast")
        self.assertEqual("".join(s.text for s in spans), "soft line\nhard\nnext\nlast")

    def test_code_breaks_are_invisible_and_reversible(self):
        original = "/home/project/reports/" + "a" * 64 + "/file_name-v2.json"
        wrapped = render.wrap_code(original)
        self.assertIn(render.BREAK, wrapped)
        self.assertEqual(wrapped.replace(render.BREAK, ""), original)
        self.assertLessEqual(max(map(len, wrapped.split(render.BREAK))), 24)

    def test_widths_preserve_total_and_reflect_contents(self):
        rows = [["Detailed population", "N", "Error"], ["Nutrition5k development", "200", "0.125"]]
        widths = render.column_widths(rows)
        self.assertEqual(sum(widths), render.CONTENT_TWIPS)
        self.assertGreater(widths[0], widths[1])
        self.assertTrue(all(width > 0 for width in widths))


@unittest.skipIf(render.Document is None, "Use bundled Python for python-docx OOXML checks")
class InMemoryDocumentTests(unittest.TestCase):
    def setUp(self):
        self.doc = render.build_document(SYNTHETIC)

    def test_content_and_order_are_retained(self):
        text = visible(self.doc.element)
        for value in ("DietAI24 synthetic report", "20 checks", "two arms", "paper source",
                      "runs/development/asa-retrieval-portion/calibration-summary.json",
                      "200", "0.12500", "78", "1.00000", "First bullet with evidence.",
                      "1. First numbered step.", "2. Second numbered step.",
                      "Quoted interpretation remains visible.", "one = 20", "two = 200"):
            self.assertIn(value, text)
        self.assertLess(text.index("1. Scope"), text.index("2. Outcomes"))
        table = self.doc.tables[0]
        source = next(b for b in render.parse_markdown(SYNTHETIC) if b.kind == "table")
        for actual, expected in zip(table.rows, source.rows):
            for cell, raw in zip(actual.cells, expected):
                self.assertEqual(visible(cell._tc), "".join(s.text for s in render.inline_spans(raw)))

    def test_letter_portrait_and_body_size(self):
        section = self.doc.sections[0]
        self.assertEqual(section.page_width.inches, 8.5)
        self.assertEqual(section.page_height.inches, 11)
        self.assertEqual(section.left_margin.inches, 0.75)
        self.assertEqual(section.right_margin.inches, 0.75)
        self.assertEqual(self.doc.styles["Normal"].font.size.pt, 11)
        self.assertEqual(self.doc.styles["Normal"].font.color.rgb, render.RGBColor(0, 0, 0))

    def test_headings_black_without_theme_color_or_decorative_border(self):
        for name in ["Title", "Subtitle"] + [f"Heading {i}" for i in range(1, 10)]:
            with self.subTest(name=name):
                style = self.doc.styles[name]
                self.assertEqual(style.font.color.rgb, render.RGBColor(0, 0, 0))
                self.assertIsNone(style.font.color.theme_color)
                self.assertEqual(len(style.element.findall(".//" + render.qn("w:pBdr"))), 0)
        self.assertEqual(self.doc.paragraphs[0].style.name, "Title")
        self.assertEqual(len(self.doc.element.findall(".//" + render.qn("w:br"))), 1)  # code line break only

    def test_hyperlinks_are_real_relationships_with_exact_targets(self):
        relationships = [rel.target_ref for rel in self.doc.part.rels.values()
                         if rel.reltype == render.RELATIONSHIP_TYPE.HYPERLINK]
        self.assertEqual(set(relationships), {"https://example.invalid/paper?id=1&section=2",
                                              "https://example.invalid/record"})
        self.assertEqual(len(self.doc.element.findall(".//" + render.qn("w:hyperlink"))), 2)

    def test_table_widths_borders_repeat_header_and_no_fixed_heights(self):
        table = self.doc.tables[0]
        self.assertFalse(table.autofit)
        self.assertEqual(sum(column.width.twips for column in table.columns), render.CONTENT_TWIPS)
        self.assertGreater(len({column.width.twips for column in table.columns}), 1)
        self.assertEqual(len(table.rows[0]._tr.findall(".//" + render.qn("w:tblHeader"))), 1)
        self.assertEqual(len(table.rows[1]._tr.findall(".//" + render.qn("w:tblHeader"))), 0)
        self.assertEqual(len(table._tbl.findall(".//" + render.qn("w:trHeight"))), 0)
        borders = table._tbl.tblPr.find(render.qn("w:tblBorders"))
        self.assertEqual(len(borders), 6)
        self.assertTrue(all(e.get(render.qn("w:color")) == "D9D9D9" for e in borders))
        self.assertTrue(all(r.font.size.pt == 10 for row in table.rows for cell in row.cells
                            for p in cell.paragraphs for r in p.runs))
        self.assertEqual(table.rows[1].cells[2].paragraphs[0].alignment, render.WD_ALIGN_PARAGRAPH.RIGHT)
        self.assertEqual(table.rows[1].cells[4].paragraphs[0].alignment, render.WD_ALIGN_PARAGRAPH.CENTER)

    def test_page_number_is_a_field_and_fields_are_updated(self):
        footer = self.doc.sections[0].footer
        instructions = footer._element.findall(".//" + render.qn("w:instrText"))
        self.assertEqual([i.text.strip() for i in instructions], ["PAGE"])
        fields = footer._element.findall(".//" + render.qn("w:fldChar"))
        self.assertEqual([f.get(render.qn("w:fldCharType")) for f in fields], ["begin", "separate", "end"])
        self.assertEqual(self.doc.settings.element.find(render.qn("w:updateFields")).get(render.qn("w:val")), "true")

    def test_adjacent_tables_have_one_exact_six_point_separator(self):
        table = "| Key | N |\n| --- | --- |\n| first | 20 |"
        doc = render.build_document(table + "\n\n" + table)
        children = list(doc.element.body)
        self.assertEqual([c.tag for c in children[:-1]],
                         [render.qn("w:tbl"), render.qn("w:p"), render.qn("w:tbl")])
        gap = doc.paragraphs[0]
        self.assertEqual(gap.text, "")
        self.assertEqual(gap.paragraph_format.line_spacing.pt, 6)
        spacing = gap._p.pPr.find(render.qn("w:spacing"))
        self.assertEqual(spacing.get(render.qn("w:lineRule")), "exact")
        self.assertEqual(gap.paragraph_format.space_before.pt, 0)
        self.assertEqual(gap.paragraph_format.space_after.pt, 0)
        self.assertTrue(gap.paragraph_format.keep_with_next)
        self.assertFalse(gap.paragraph_format.widow_control)
        self.assertEqual(len(doc.paragraphs), 1)  # No trailing spacer.

    def test_table_to_prose_has_gap_and_heading_keeps_larger_spacing(self):
        table = "| Key | N |\n| --- | --- |\n| first | 20 |"
        doc = render.build_document(table + "\n\nBody immediately after table.\n\n" +
                                    table + "\n\n## Next section")
        self.assertEqual([p.text for p in doc.paragraphs],
                         ["Body immediately after table.", "Next section"])
        self.assertEqual(doc.paragraphs[0].paragraph_format.space_before.pt, 6)
        self.assertEqual(doc.paragraphs[1].paragraph_format.space_before.pt, 12)
        self.assertEqual(doc.styles["Normal"].font.size.pt, 11)
        self.assertTrue(all(run.font.size.pt == 10 for table in doc.tables for row in table.rows
                            for cell in row.cells for paragraph in cell.paragraphs for run in paragraph.runs))

    def test_conversion_uses_only_supplied_markdown_and_mocked_save(self):
        source, destination = Path("synthetic-report.md"), Path("synthetic-report.docx")
        with patch.object(Path, "read_text", return_value=SYNTHETIC) as read, \
             patch.object(Path, "mkdir") as mkdir, \
             patch("docx.document.Document.save") as save:
            result = render.convert_file(source, destination)
        read.assert_called_once_with(encoding="utf-8-sig")
        mkdir.assert_called_once()
        save.assert_called_once_with(str(destination))
        self.assertEqual(result, destination)

    def test_bad_table_does_not_save_or_create_output_directory(self):
        with patch.object(Path, "read_text", return_value="| a | b |\n| --- | --- |\n| x |"), \
             patch.object(Path, "mkdir") as mkdir, \
             patch("docx.document.Document.save") as save:
            with self.assertRaisesRegex(ValueError, "width"):
                render.convert_file("synthetic.md", "synthetic.docx")
        mkdir.assert_not_called()
        save.assert_not_called()


class CommandLineTests(unittest.TestCase):
    def test_cli_passes_both_paths_without_reading_study_data(self):
        with patch.object(render, "convert_file", return_value=Path("output.docx")) as convert, \
             patch("builtins.print"):
            render.main(["input.md", "output.docx"])
        convert.assert_called_once_with(Path("input.md"), Path("output.docx"))

    def test_reject_source_overwrite_and_wrong_extension_before_read(self):
        for source, destination in (("same.md", "same.md"), ("in.md", "out.pdf")):
            with self.subTest(destination=destination), patch.object(Path, "read_text") as read:
                with self.assertRaises(ValueError):
                    render.convert_file(source, destination)
                read.assert_not_called()


if __name__ == "__main__":
    unittest.main()
