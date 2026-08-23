#!/usr/bin/env python
"""Convert the Project Vaani SDLC markdown documents to DOCX.

pandoc is not available on this machine, so this uses python-docx directly.
Handles the subset of markdown actually used in docs/voice-platform/:
headings, tables, fenced code, lists, checkboxes, blockquotes, rules,
and inline bold / italic / code.

Telugu text is preserved by setting an East-Asian + complex-script font
(Nirmala UI) on every run, which is what Word needs to render Devanagari
and Telugu glyphs instead of boxes.

Usage:
    python tools/md_to_docx.py                 # convert all docs
    python tools/md_to_docx.py 01-feasibility-study.md
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.shared import Pt, RGBColor, Inches

DOCS = Path(__file__).resolve().parent.parent / "docs" / "voice-platform"

BODY_FONT = "Calibri"
MONO_FONT = "Consolas"
# Nirmala UI ships with Windows and covers Telugu; without an explicit
# complex-script font Word renders Telugu as tofu boxes.
INDIC_FONT = "Nirmala UI"

ACCENT = RGBColor(0x1F, 0x4E, 0x79)
MUTED = RGBColor(0x5A, 0x5A, 0x5A)
CODE_BG_SHADE = "F2F2F2"


# --------------------------------------------------------------------------
# low-level helpers
# --------------------------------------------------------------------------
def _set_fonts(run, name: str) -> None:
    """Apply a font to latin, east-asian and complex-script slots."""
    run.font.name = name
    rpr = run._element.get_or_add_rPr()
    rfonts = rpr.find(qn("w:rFonts"))
    if rfonts is None:
        rfonts = rpr.makeelement(qn("w:rFonts"), {})
        rpr.append(rfonts)
    for slot in ("w:ascii", "w:hAnsi", "w:eastAsia", "w:cs"):
        rfonts.set(qn(slot), name)


def _shade(element, hex_fill: str) -> None:
    pr = element._element.get_or_add_tcPr() if hasattr(element._element, "get_or_add_tcPr") \
        else element._element.get_or_add_pPr()
    shd = pr.makeelement(qn("w:shd"), {})
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), hex_fill)
    pr.append(shd)


INLINE = re.compile(
    r"(\*\*.+?\*\*)"     # bold
    r"|(`[^`]+`)"        # inline code
    r"|(\*[^*]+\*)"      # italic
)


def add_inline(paragraph, text: str, *, base_bold=False, size=None) -> None:
    """Render inline markdown (bold / italic / code) into a paragraph."""
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)  # flatten links
    for part in filter(None, INLINE.split(text)):
        if part.startswith("**") and part.endswith("**") and len(part) > 4:
            run = paragraph.add_run(part[2:-2])
            run.bold = True
            _set_fonts(run, INDIC_FONT)
        elif part.startswith("`") and part.endswith("`") and len(part) > 2:
            run = paragraph.add_run(part[1:-1])
            _set_fonts(run, MONO_FONT)
            run.font.size = Pt(9)
            run.font.color.rgb = RGBColor(0xA3, 0x1D, 0x1D)
        elif part.startswith("*") and part.endswith("*") and len(part) > 2:
            run = paragraph.add_run(part[1:-1])
            run.italic = True
            _set_fonts(run, INDIC_FONT)
        else:
            run = paragraph.add_run(part)
            _set_fonts(run, INDIC_FONT)
        if base_bold:
            run.bold = True
        if size:
            run.font.size = Pt(size)


def split_row(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def is_divider(line: str) -> bool:
    return bool(re.fullmatch(r"\|[\s:|-]+\|", line.strip()))


# --------------------------------------------------------------------------
# block builders
# --------------------------------------------------------------------------
def add_table(doc: Document, rows: list[list[str]]) -> None:
    if not rows:
        return
    cols = max(len(r) for r in rows)
    table = doc.add_table(rows=0, cols=cols)
    table.style = "Table Grid"
    table.alignment = WD_TABLE_ALIGNMENT.CENTER

    for i, row in enumerate(rows):
        cells = table.add_row().cells
        for j in range(cols):
            para = cells[j].paragraphs[0]
            para.paragraph_format.space_before = Pt(2)
            para.paragraph_format.space_after = Pt(2)
            value = row[j] if j < len(row) else ""
            add_inline(para, value, base_bold=(i == 0), size=9)
            if i == 0:
                _shade(cells[j], "DCE6F1")


def add_code(doc: Document, lines: list[str]) -> None:
    for line in lines:
        p = doc.add_paragraph()
        p.paragraph_format.space_after = Pt(0)
        p.paragraph_format.space_before = Pt(0)
        p.paragraph_format.left_indent = Inches(0.25)
        _shade(p, CODE_BG_SHADE)
        run = p.add_run(line if line else " ")
        _set_fonts(run, MONO_FONT)
        run.font.size = Pt(8)


def add_quote(doc: Document, lines: list[str]) -> None:
    p = doc.add_paragraph()
    p.paragraph_format.left_indent = Inches(0.3)
    p.paragraph_format.space_before = Pt(6)
    p.paragraph_format.space_after = Pt(6)
    add_inline(p, " ".join(lines))
    for run in p.runs:
        run.italic = True
        run.font.color.rgb = MUTED


# --------------------------------------------------------------------------
# main conversion
# --------------------------------------------------------------------------
def convert(md_path: Path) -> Path:
    lines = md_path.read_text(encoding="utf-8").splitlines()
    doc = Document()

    style = doc.styles["Normal"]
    style.font.name = BODY_FONT
    style.font.size = Pt(10.5)

    i = 0
    table_buf: list[list[str]] = []
    quote_buf: list[str] = []

    def flush() -> None:
        nonlocal table_buf, quote_buf
        if table_buf:
            add_table(doc, table_buf)
            doc.add_paragraph()
            table_buf = []
        if quote_buf:
            add_quote(doc, quote_buf)
            quote_buf = []

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # fenced code
        if stripped.startswith("```"):
            flush()
            i += 1
            block: list[str] = []
            while i < len(lines) and not lines[i].strip().startswith("```"):
                block.append(lines[i])
                i += 1
            add_code(doc, block)
            doc.add_paragraph()
            i += 1
            continue

        # tables
        if stripped.startswith("|"):
            if is_divider(stripped):
                i += 1
                continue
            quote_buf and flush()
            table_buf.append(split_row(stripped))
            i += 1
            continue
        elif table_buf:
            flush()

        # blockquote
        if stripped.startswith(">"):
            quote_buf.append(stripped.lstrip(">").strip())
            i += 1
            continue
        elif quote_buf:
            flush()

        # headings
        if stripped.startswith("#"):
            level = len(stripped) - len(stripped.lstrip("#"))
            text = stripped[level:].strip()
            if level == 1:
                h = doc.add_heading(level=0)
                add_inline(h, text)
                for r in h.runs:
                    r.font.color.rgb = ACCENT
            else:
                h = doc.add_heading(level=min(level - 1, 4))
                add_inline(h, text)
                for r in h.runs:
                    r.font.color.rgb = ACCENT
            i += 1
            continue

        # horizontal rule
        if stripped in {"---", "***", "___"}:
            p = doc.add_paragraph()
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            run = p.add_run("─" * 40)
            run.font.color.rgb = RGBColor(0xC0, 0xC0, 0xC0)
            i += 1
            continue

        # checkbox
        m = re.match(r"^\s*-\s*\[( |x|X)\]\s+(.*)$", line)
        if m:
            p = doc.add_paragraph(style="List Bullet")
            mark = "☑ " if m.group(1).lower() == "x" else "☐ "
            add_inline(p, mark + m.group(2))
            i += 1
            continue

        # bullets
        m = re.match(r"^(\s*)[-*+]\s+(.*)$", line)
        if m:
            p = doc.add_paragraph(style="List Bullet")
            if len(m.group(1)) >= 2:
                p.paragraph_format.left_indent = Inches(0.6)
            add_inline(p, m.group(2))
            i += 1
            continue

        # numbered
        m = re.match(r"^(\s*)\d+[.)]\s+(.*)$", line)
        if m:
            p = doc.add_paragraph(style="List Number")
            add_inline(p, m.group(2))
            i += 1
            continue

        # blank
        if not stripped:
            i += 1
            continue

        # plain paragraph
        p = doc.add_paragraph()
        p.paragraph_format.space_after = Pt(6)
        add_inline(p, stripped)
        i += 1

    flush()

    out = md_path.with_suffix(".docx")
    doc.save(out)
    return out


def main() -> int:
    targets = sys.argv[1:]
    files = ([DOCS / t for t in targets] if targets
             else sorted(DOCS.glob("*.md")))
    if not files:
        print(f"no markdown found in {DOCS}")
        return 1
    locked: list[str] = []
    for f in files:
        if not f.exists():
            print(f"missing: {f}")
            continue
        try:
            out = convert(f)
        except PermissionError:
            # Word holds an exclusive lock on an open .docx.
            locked.append(f.with_suffix(".docx").name)
            print(f"{f.name}  ->  SKIPPED (target open in Word)")
            continue
        print(f"{f.name}  ->  {out.name}  ({out.stat().st_size:,} bytes)")

    if locked:
        print("\nClose these in Word and re-run to refresh them:")
        for name in locked:
            print(f"  - {name}")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
