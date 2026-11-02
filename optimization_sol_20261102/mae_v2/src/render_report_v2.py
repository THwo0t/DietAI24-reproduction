#!/usr/bin/env python3
"""Convert a report Markdown file to a restrained, editable DOCX.

Run with the bundled Python runtime, after the caller's artifact-operation
marker. This module neither runs inference nor reads any study inputs other
than the supplied Markdown. It does not render PDF or claim visual acceptance.

Supported Markdown: ATX headings, paragraphs, ordered/unordered lists, quotes,
pipe tables, fenced code, inline code, emphasis, links and URL autolinks. Unknown
syntax remains literal. Ragged tables fail rather than silently losing cells.
Code paths receive invisible Unicode break opportunities; removing U+200B
recovers their original text. Hyperlink destinations remain unchanged.

The first level-one heading is a title on the first content page, not a cover.
Letter portrait, 11 pt body, black headings, proportionate table columns,
light-gray borders, repeating headers and a page-number field are fixed.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass, field
import html
from pathlib import Path
import re
from typing import Any

try:
    from docx import Document
    from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT, WD_TABLE_ALIGNMENT
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.opc.constants import RELATIONSHIP_TYPE
    from docx.shared import Inches, Pt, RGBColor, Twips
    from docx.text.run import Run
except ModuleNotFoundError:
    Document = None


RENDERER_VERSION = "report-docx-v2.2"
BODY_FONT = "Calibri"
CODE_FONT = "Consolas"
BREAK = "\u200b"
CONTENT_TWIPS = 10080  # Letter minus 0.75-inch left and right margins.


@dataclass
class Block:
    kind: str
    text: str = ""
    level: int = 0
    marker: str = ""
    rows: list[list[str]] = field(default_factory=list)
    alignment: list[str | None] = field(default_factory=list)


@dataclass
class Span:
    text: str
    bold: bool = False
    italic: bool = False
    code: bool = False
    target: str | None = None


def split_table_row(line: str) -> list[str]:
    """Split on unescaped pipes outside matching inline-code delimiters."""
    line = line.strip()
    cells, current, ticks, i = [], [], 0, 0
    while i < len(line):
        char = line[i]
        if char == "\\" and i + 1 < len(line):
            current.extend(line[i:i + 2])
            i += 2
            continue
        if char == "`":
            end = i + 1
            while end < len(line) and line[end] == "`":
                end += 1
            size = end - i
            if ticks == 0:
                ticks = size
            elif ticks == size:
                ticks = 0
            current.append(line[i:end])
            i = end
            continue
        if char == "|" and ticks == 0:
            cells.append("".join(current).strip())
            current = []
        else:
            current.append(char)
        i += 1
    cells.append("".join(current).strip())
    if line.startswith("|"):
        cells = cells[1:]
    if line.endswith("|") and cells[-1] == "":
        cells = cells[:-1]
    return cells


def _table_alignment(line: str) -> list[str | None] | None:
    cells = split_table_row(line)
    if not cells or not all(re.fullmatch(r":?-{3,}:?", c) for c in cells):
        return None
    return ["center" if c.startswith(":") and c.endswith(":") else
            "left" if c.startswith(":") else "right" if c.endswith(":") else None
            for c in cells]


def parse_markdown(markdown: str) -> list[Block]:
    """Parse the report's Markdown without filesystem or document writes."""
    lines = markdown.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    blocks, i = [], 0
    while i < len(lines):
        line = lines[i]
        if not line.strip():
            i += 1
            continue
        fence = re.match(r"^ {0,3}(`{3,}|~{3,})(.*)$", line)
        if fence:
            mark, contents = fence.group(1), []
            i += 1
            while i < len(lines) and not re.fullmatch(r" {0,3}" + re.escape(mark[0]) +
                                                    "{" + str(len(mark)) + r",}\s*", lines[i]):
                contents.append(lines[i])
                i += 1
            if i == len(lines):
                raise ValueError("Unclosed Markdown code fence")
            blocks.append(Block("code", "\n".join(contents)))
            i += 1
            continue
        heading = re.match(r"^ {0,3}(#{1,6})\s+(.+?)\s*$", line)
        if heading:
            contents = re.sub(r"\s+#+\s*$", "", heading.group(2))
            blocks.append(Block("heading", contents, len(heading.group(1))))
            i += 1
            continue
        alignment = _table_alignment(lines[i + 1]) if i + 1 < len(lines) else None
        if alignment is not None and "|" in line:
            rows = [split_table_row(line)]
            if len(rows[0]) != len(alignment):
                raise ValueError("Markdown table header and delimiter widths differ")
            i += 2
            while i < len(lines) and lines[i].strip() and "|" in lines[i]:
                row = split_table_row(lines[i])
                if len(row) != len(alignment):
                    raise ValueError("Markdown table row width differs from its header")
                rows.append(row)
                i += 1
            blocks.append(Block("table", rows=rows, alignment=alignment))
            continue
        item = re.match(r"^(\s*)([-+*]|\d+[.)])\s+(.+)$", line)
        if item:
            level = len(item.group(1).expandtabs(4)) // 2
            marker = "•" if item.group(2) in "-+*" else item.group(2)
            text = item.group(3)
            i += 1
            while i < len(lines) and lines[i].strip() and re.match(r"^\s{2,}\S", lines[i]) and not re.match(r"^\s*([-+*]|\d+[.)])\s", lines[i]):
                text += "\n" + lines[i].strip()
                i += 1
            blocks.append(Block("list", text, level, marker))
            continue
        if re.match(r"^\s{0,3}>\s?", line):
            quote = []
            while i < len(lines) and re.match(r"^\s{0,3}>\s?", lines[i]):
                quote.append(re.sub(r"^\s{0,3}>\s?", "", lines[i]))
                i += 1
            blocks.append(Block("quote", "\n".join(quote)))
            continue
        contents = [line]
        i += 1
        while i < len(lines) and lines[i].strip():
            if re.match(r"^\s{0,3}(#{1,6}\s|`{3,}|~{3,}|>\s?)", lines[i]) or re.match(r"^\s*([-+*]|\d+[.)])\s", lines[i]):
                break
            if i + 1 < len(lines) and _table_alignment(lines[i + 1]) is not None and "|" in lines[i]:
                break
            contents.append(lines[i])
            i += 1
        blocks.append(Block("paragraph", "\n".join(contents)))
    return blocks


def _matching_end(text: str, start: int, opening: str, closing: str) -> int | None:
    depth, i = 1, start + 1
    while i < len(text):
        if text[i] == "\\":
            i += 2
            continue
        if text[i] == opening:
            depth += 1
        elif text[i] == closing:
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return None


def _decode_entities(text: str) -> str:
    # html.unescape alone also accepts semicolon-free legacy entities, corrupting
    # ordinary URL query keys such as "&section=" into the section-sign glyph.
    return re.sub(r"&(?:#[xX][0-9a-fA-F]+|#\d+|[A-Za-z][A-Za-z0-9]+);",
                  lambda match: html.unescape(match.group()), text)


def inline_spans(text: str, *, bold=False, italic=False, target=None) -> list[Span]:
    """Interpret inline report syntax; keep unsupported constructs visible."""
    spans, pending, i = [], [], 0

    def flush():
        if pending:
            spans.append(Span(_decode_entities("".join(pending)), bold, italic, target=target))
            pending.clear()

    while i < len(text):
        if text[i] == "\\" and i + 1 < len(text) and text[i + 1] in r"\`*_{}[]()#+-.!|>":
            pending.append(text[i + 1])
            i += 2
            continue
        if text[i] == "`":
            match = re.match(r"`+", text[i:])
            delimiter = match.group()
            end = text.find(delimiter, i + len(delimiter))
            if end >= 0:
                flush()
                spans.append(Span(text[i + len(delimiter):end], bold, italic, True, target))
                i = end + len(delimiter)
                continue
        if text[i] == "[":
            label_end = _matching_end(text, i, "[", "]")
            if label_end is not None and text[label_end + 1:label_end + 2] == "(":
                url_end = _matching_end(text, label_end + 1, "(", ")")
                if url_end is not None:
                    destination = text[label_end + 2:url_end].strip()
                    # Optional Markdown link title is metadata, not label text.
                    found = re.fullmatch(r'<([^>]+)>(?:\s+[\'"].*[\'"])?|([^\s]+)(?:\s+[\'"].*[\'"])?', destination)
                    if found:
                        flush()
                        url = _decode_entities(found.group(1) or found.group(2))
                        spans.extend(inline_spans(text[i + 1:label_end], bold=bold, italic=italic, target=url))
                        i = url_end + 1
                        continue
        autolink = re.match(r"<(https?://[^>]+|mailto:[^>]+)>", text[i:])
        if autolink:
            flush()
            url = _decode_entities(autolink.group(1))
            spans.append(Span(url, bold, italic, target=url))
            i += len(autolink.group())
            continue
        hard_break = re.match(r"<br\s*/?>| {2,}\n|\\\n", text[i:], re.IGNORECASE)
        if hard_break:
            pending.append("\n")
            i += len(hard_break.group())
            continue
        handled = False
        for delimiter in ("**", "__", "*", "_"):
            if not text.startswith(delimiter, i):
                continue
            # Intraword underscores in statuses and paths are literal.
            if delimiter.startswith("_") and i and text[i - 1].isalnum():
                continue
            end = text.find(delimiter, i + len(delimiter))
            if end > i + len(delimiter) and not text[i + len(delimiter)].isspace() and not text[end - 1].isspace():
                flush()
                spans.extend(inline_spans(text[i + len(delimiter):end],
                    bold=bold or len(delimiter) == 2, italic=italic or len(delimiter) == 1, target=target))
                i = end + len(delimiter)
                handled = True
                break
        if handled:
            continue
        pending.append(" " if text[i] == "\n" else text[i])
        i += 1
    flush()
    return spans


def wrap_code(text: str) -> str:
    """Add invisible opportunities after separators and inside long hashes."""
    separated = re.sub(r"([/\\_.-])", r"\1" + BREAK, text)
    return re.sub(r"[^\s" + BREAK + r"]{25,}",
                  lambda m: BREAK.join(m.group()[i:i + 24] for i in range(0, len(m.group()), 24)), separated)


def _set_font(font, size=None, name=BODY_FONT):
    font.name = name
    if size is not None:
        font.size = Pt(size)
    font.color.rgb = RGBColor(0, 0, 0)


def _property(parent, name: str, **attributes):
    element = parent.find(qn(name))
    if element is None:
        element = OxmlElement(name)
        parent.append(element)
    for key, value in attributes.items():
        element.set(qn("w:" + key), str(value))
    return element


def _append_spans(paragraph, text: str, size=None, code=False):
    spans = [Span(text, code=True)] if code else inline_spans(text)
    for span in spans:
        run = paragraph.add_run(wrap_code(span.text) if span.code else span.text)
        _set_font(run.font, size, CODE_FONT if span.code else BODY_FONT)
        if span.bold:
            run.bold = True
        if span.italic:
            run.italic = True
        if span.target:
            run.underline = True
            link = OxmlElement("w:hyperlink")
            link.set(qn("r:id"), paragraph.part.relate_to(span.target, RELATIONSHIP_TYPE.HYPERLINK, is_external=True))
            link.set(qn("w:history"), "1")
            paragraph._p.remove(run._r)
            link.append(run._r)
            paragraph._p.append(link)


def column_widths(rows: list[list[str]], total=CONTENT_TWIPS) -> list[int]:
    """Allocate width from visible content, with bounded pressure from prose."""
    count = len(rows[0])
    demands = []
    for column in range(count):
        texts = ["".join(s.text for s in inline_spans(row[column])) for row in rows]
        longest = max((len(word) for text in texts for word in text.split()), default=3)
        average = sum(min(len(t), 40) for t in texts) / max(1, len(texts))
        demands.append(max(5, min(longest, 15)) + min(average, 25) * 0.18)
    minimum = min(720, total // (count * 2))
    remaining = total - minimum * count
    widths = [minimum + int(remaining * d / sum(demands)) for d in demands]
    widths[-1] += total - sum(widths)
    return widths


def _cell_alignment(text: str, specified):
    if specified:
        return {"left": WD_ALIGN_PARAGRAPH.LEFT, "right": WD_ALIGN_PARAGRAPH.RIGHT,
                "center": WD_ALIGN_PARAGRAPH.CENTER}[specified]
    plain = "".join(s.text for s in inline_spans(text)).strip()
    if re.fullmatch(r"[+$−-]?[\d,.]+(?:%|\s*/\s*[\d,.]+)?", plain):
        return WD_ALIGN_PARAGRAPH.RIGHT
    if plain.lower() in {"yes", "no", "on", "off", "pass", "fail"}:
        return WD_ALIGN_PARAGRAPH.CENTER
    return WD_ALIGN_PARAGRAPH.LEFT


def _add_table(document, block):
    widths = column_widths(block.rows)
    table = document.add_table(rows=len(block.rows), cols=len(widths))
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = False
    properties = table._tbl.tblPr
    _property(properties, "w:tblW", w=CONTENT_TWIPS, type="dxa")
    borders = _property(properties, "w:tblBorders")
    for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
        _property(borders, "w:" + edge, val="single", sz=4, color="D9D9D9")
    margins = _property(properties, "w:tblCellMar")
    for edge, value in (("top", 65), ("bottom", 65), ("left", 75), ("right", 75)):
        _property(margins, "w:" + edge, w=value, type="dxa")
    for column, width in zip(table.columns, widths):
        column.width = Twips(width)
    font_size = 10 if len(widths) <= 6 else 9
    for row_index, (row, contents) in enumerate(zip(table.rows, block.rows)):
        props = row._tr.get_or_add_trPr()
        _property(props, "w:cantSplit")
        if row_index == 0:
            _property(props, "w:tblHeader")
        for index, (cell, text) in enumerate(zip(row.cells, contents)):
            cell.width = Twips(widths[index])
            cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
            paragraph = cell.paragraphs[0]
            paragraph.paragraph_format.space_after = Pt(0)
            paragraph.paragraph_format.space_before = Pt(0)
            paragraph.paragraph_format.line_spacing = 1.05
            paragraph.paragraph_format.keep_with_next = row_index == 0
            paragraph.alignment = _cell_alignment(text, block.alignment[index])
            _append_spans(paragraph, text, size=font_size)
            if row_index == 0:
                _property(cell._tc.get_or_add_tcPr(), "w:shd", fill="F2F2F2", val="clear")
                for element in paragraph._p.iter(qn("w:r")):
                    Run(element, paragraph).bold = True
    return table


def _table_gap(document):
    """Separate adjacent tables with one exactly 6 pt, content-free paragraph.

    A real paragraph also prevents Word from treating adjacent tables as one.
    Exact line height and zero paragraph spacing avoid a full body-text blank
    line; keeping it with the following table prevents a stranded separator.
    """
    paragraph = document.add_paragraph()
    paragraph.paragraph_format.line_spacing = Pt(6)
    paragraph.paragraph_format.space_before = Pt(0)
    paragraph.paragraph_format.space_after = Pt(0)
    paragraph.paragraph_format.keep_with_next = True
    paragraph.paragraph_format.widow_control = False


def _configure(document):
    section = document.sections[0]
    section.page_width, section.page_height = Inches(8.5), Inches(11)
    section.top_margin = section.bottom_margin = Inches(0.7)
    section.left_margin = section.right_margin = Inches(0.75)
    section.header_distance = section.footer_distance = Inches(0.3)
    normal = document.styles["Normal"]
    _set_font(normal.font, 11)
    normal.paragraph_format.line_spacing = 1.08
    normal.paragraph_format.space_after = Pt(6)
    normal.paragraph_format.widow_control = True
    for name, size in [("Title", 17), ("Subtitle", 11)] + [(f"Heading {i}", max(11, 14 - i)) for i in range(1, 10)]:
        style = document.styles[name]
        _set_font(style.font, size)
        style.font.bold = name != "Subtitle"
        style.paragraph_format.keep_with_next = True
        style.paragraph_format.space_before = Pt(0 if name == "Title" else 12)
        style.paragraph_format.space_after = Pt(6)
        properties = style.element.find(qn("w:pPr"))
        if properties is not None:
            for border in list(properties.findall(qn("w:pBdr"))):
                properties.remove(border)
    footer = section.footer.paragraphs[0]
    footer.alignment = WD_ALIGN_PARAGRAPH.CENTER
    footer.paragraph_format.space_after = Pt(0)
    page = footer.add_run()
    _set_font(page.font, 9)
    for tag, value in (("w:fldChar", "begin"), ("w:instrText", " PAGE "),
                       ("w:fldChar", "separate"), ("w:t", "1"), ("w:fldChar", "end")):
        element = OxmlElement(tag)
        if tag == "w:fldChar":
            element.set(qn("w:fldCharType"), value)
        else:
            element.text = value
            element.set(qn("xml:space"), "preserve")
        page._r.append(element)
    _property(document.settings.element, "w:updateFields", val="true")
    document.core_properties.author = ""
    document.core_properties.last_modified_by = ""
    document.core_properties.comments = ""
    document.core_properties.subject = "DietAI24 MAE optimization report"


def build_document(markdown: str) -> Any:
    """Build editable OOXML in memory; no output file or source access."""
    blocks = parse_markdown(markdown)
    if Document is None:
        raise RuntimeError("python-docx is required; use the Python runtime returned by the Codex workspace dependency loader")
    document = Document()
    _configure(document)
    title_used = False
    for index, block in enumerate(blocks):
        follows_table = index > 0 and blocks[index - 1].kind == "table"
        if block.kind == "table":
            if follows_table:
                _table_gap(document)
            _add_table(document, block)
            continue
        if block.kind == "heading":
            is_title = block.level == 1 and not title_used
            paragraph = document.add_paragraph(style="Title" if is_title else f"Heading {max(1, block.level - 1)}")
            if is_title:
                title_used = True
                document.core_properties.title = "".join(s.text for s in inline_spans(block.text))
        else:
            paragraph = document.add_paragraph()
        if follows_table:
            # Keep existing heading spacing when larger; prose needs an
            # explicit gap because a table has no paragraph space-after.
            inherited = paragraph.style.paragraph_format.space_before
            paragraph.paragraph_format.space_before = max(Pt(6), inherited or Pt(0))
        if block.kind == "list":
            paragraph.paragraph_format.left_indent = Inches(0.2 + 0.18 * min(block.level, 6))
            paragraph.paragraph_format.first_line_indent = Inches(-0.16)
            _append_spans(paragraph, block.marker + " ")
        elif block.kind == "quote":
            paragraph.paragraph_format.left_indent = Inches(0.25)
        elif block.kind == "code":
            paragraph.paragraph_format.left_indent = Inches(0.12)
            paragraph.paragraph_format.line_spacing = 1
        _append_spans(paragraph, block.text, size=9.5 if block.kind == "code" else None,
                      code=block.kind == "code")
    return document


def convert_file(markdown_path: str | Path, docx_path: str | Path) -> Path:
    """The only writing entry point; call only after the artifact marker."""
    source, destination = Path(markdown_path), Path(docx_path)
    if source.resolve() == destination.resolve():
        raise ValueError("Source and destination must differ")
    if destination.suffix.lower() != ".docx":
        raise ValueError("Output path must end in .docx")
    if destination.is_symlink():
        raise ValueError("Output cannot overwrite a symlink")
    document = build_document(source.read_text(encoding="utf-8-sig"))
    # Existing destination is untouched if parsing or document construction fails.
    destination.parent.mkdir(parents=True, exist_ok=True)
    document.save(str(destination))
    return destination


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("markdown", type=Path, help="Input report Markdown")
    parser.add_argument("docx", type=Path, help="Output DOCX; caller runs artifact marker first")
    args = parser.parse_args(argv)
    print(convert_file(args.markdown, args.docx))


if __name__ == "__main__":
    main()
