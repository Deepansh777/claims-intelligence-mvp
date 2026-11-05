"""Branded Word and PDF schema documentation, rendered from the LLM data dictionary.

The dictionary is the single source; this module only understands the markdown it uses:
headings, paragraphs, bullet/numbered lists, pipe tables, fenced code, **bold** and `code`.
"""

import datetime
import functools
import html
import io
import re
from pathlib import Path

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor
from fpdf import FPDF, FontFace

APP = Path(__file__).resolve().parents[1]
DICTIONARY = APP / "llm" / "data-dictionary.md"
LOGO = APP / "assets" / "logo.png"
SUBTITLE = "Schema documentation: raw, mart and ref"

DARK = (0x12, 0x31, 0x37)
ACCENT = (0x2F, 0x9D, 0x90)
MUTED = (0x68, 0x78, 0x7B)
SOFT = (0xD9, 0xF1, 0xED)
CANVAS = (0xF6, 0xF8, 0xF7)
LINE = (0xDB, 0xE5, 0xE3)

LIST_ITEM = re.compile(r"(\d+\.|[-*])\s+(.*)")
HEADING = re.compile(r"(#{1,6})\s+(.*)")
BLOCK_START = re.compile(r"#{1,6}\s|```|\||(\d+\.|[-*])\s|---\s*$")


def parse(md: str) -> list[tuple[str, object]]:
    lines, blocks, i = md.splitlines(), [], 0
    while i < len(lines):
        line = lines[i]
        if not line.strip():
            i += 1
        elif line.startswith("```"):
            end = next(
                (j for j in range(i + 1, len(lines)) if lines[j].startswith("```")), len(lines)
            )
            blocks.append(("code", "\n".join(lines[i + 1 : end])))
            i = end + 1
        elif m := HEADING.match(line):
            blocks.append(("heading", (len(m[1]), m[2].strip())))
            i += 1
        elif re.match(r"---\s*$", line):
            i += 1  # section rules: headings already separate sections
        elif line.startswith("|"):
            rows = []
            while i < len(lines) and lines[i].startswith("|"):
                cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
                if not all(re.fullmatch(r":?-+:?", c) for c in cells):
                    rows.append(cells)
                i += 1
            blocks.append(("table", rows))
        elif m := LIST_ITEM.match(line):
            ordered, items = m[1][0].isdigit(), []
            while i < len(lines) and (m := LIST_ITEM.match(lines[i])):
                items.append(m[2])
                i += 1
            blocks.append(("list", (ordered, items)))
        else:
            para = [line.strip()]
            i += 1
            while i < len(lines) and lines[i].strip() and not BLOCK_START.match(lines[i]):
                para.append(lines[i].strip())
                i += 1
            blocks.append(("para", " ".join(para)))
    return blocks


def runs(text: str) -> list[tuple[str, bool, bool]]:
    """Split inline markdown into (text, bold, code) runs; `code` may sit inside **bold**."""
    out = []
    for i, part in enumerate(re.split(r"\*\*(.+?)\*\*", text)):
        for j, piece in enumerate(re.split(r"`([^`]+)`", part)):
            if piece:
                out.append((piece, i % 2 == 1, j % 2 == 1))
    return out


def _source() -> tuple[str, list[tuple[str, object]], str]:
    blocks = parse(DICTIONARY.read_text(encoding="utf-8"))
    title = next(v[1] for k, v in blocks if k == "heading" and v[0] == 1)
    intro = next(v for k, v in blocks if k == "para")
    body = [b for b in blocks if b not in (("heading", (1, title)), ("para", intro))]
    return title, body, intro


def _today() -> str:
    return datetime.date.today().strftime("%d %B %Y").lstrip("0")


# ---- Word ----


def _shade(target, fill: tuple[int, int, int]) -> None:
    """Background fill for a table cell or a paragraph."""
    props = target._tc.get_or_add_tcPr() if hasattr(target, "_tc") else target._p.get_or_add_pPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:fill"), "".join(f"{c:02X}" for c in fill))
    props.append(shd)


def _field(paragraph, instruction: str) -> None:
    run = paragraph.add_run()
    for tag, text in (("begin", None), (None, instruction), ("separate", None), ("end", None)):
        if tag:
            el = OxmlElement("w:fldChar")
            el.set(qn("w:fldCharType"), tag)
        else:
            el = OxmlElement("w:instrText")
            el.set(qn("xml:space"), "preserve")
            el.text = text
        run._r.append(el)


def _add_runs(paragraph, text: str, size: float | None = None) -> None:
    for piece, bold, code in runs(text):
        r = paragraph.add_run(piece)
        r.bold = bold
        if code:
            r.font.name = "Consolas"
            r.font.color.rgb = RGBColor(*DARK)
        if size:
            r.font.size = Pt(size - (0.5 if code else 0))


def build_docx() -> bytes:
    title, body, intro = _source()
    doc = Document()
    sec = doc.sections[0]
    sec.left_margin = sec.right_margin = Inches(0.8)
    sec.top_margin = sec.bottom_margin = Inches(0.8)
    sec.different_first_page_header_footer = True

    normal = doc.styles["Normal"]
    normal.font.name = "Calibri"
    normal.font.size = Pt(10)
    for name, size in (("Heading 1", 16), ("Heading 2", 12.5)):
        style = doc.styles[name]
        style.font.name = "Calibri"
        style.font.size = Pt(size)
        style.font.color.rgb = RGBColor(*DARK)
        style.paragraph_format.keep_with_next = True

    header = sec.header.paragraphs[0]
    header.add_run().add_picture(str(LOGO), width=Inches(1.3))
    label = header.add_run(f"\t\t{title}")
    label.font.size = Pt(8)
    label.font.color.rgb = RGBColor(*MUTED)
    footer = sec.footer.paragraphs[0]
    footer.alignment = WD_ALIGN_PARAGRAPH.CENTER
    footer.add_run(f"{SUBTITLE}  ·  Generated {_today()}  ·  Page ").font.size = Pt(8)
    _field(footer, "PAGE")

    # Cover page
    for _ in range(6):
        doc.add_paragraph()
    cover = doc.add_paragraph()
    cover.alignment = WD_ALIGN_PARAGRAPH.CENTER
    cover.add_run().add_picture(str(LOGO), width=Inches(3.2))
    for text, size, color in ((title, 26, DARK), (SUBTITLE, 14, ACCENT), (_today(), 11, MUTED)):
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.paragraph_format.space_before = Pt(12)
        r = p.add_run(text)
        r.font.size = Pt(size)
        r.font.color.rgb = RGBColor(*color)
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_before = Pt(30)
    _add_runs(p, intro, 10)
    doc.add_paragraph().add_run().add_break(WD_BREAK.PAGE)

    for kind, value in body:
        if kind == "heading":
            level, text = value
            doc.add_heading(text.replace("`", ""), level=min(level - 1, 2))
        elif kind == "para":
            _add_runs(doc.add_paragraph(), value)
        elif kind == "list":
            ordered, items = value
            for item in items:
                _add_runs(
                    doc.add_paragraph(style="List Number" if ordered else "List Bullet"), item
                )
        elif kind == "code":
            p = doc.add_paragraph()
            _shade(p, CANVAS)
            for k, line in enumerate(value.split("\n")):
                if k:
                    p.add_run().add_break()
                r = p.add_run(line)
                r.font.name = "Consolas"
                r.font.size = Pt(8.5)
        elif kind == "table":
            table = doc.add_table(rows=len(value), cols=len(value[0]))
            table.style = "Table Grid"
            table.alignment = WD_TABLE_ALIGNMENT.CENTER
            for ri, row in enumerate(value):
                for ci, text in enumerate(row):
                    cell = table.cell(ri, ci)
                    _add_runs(cell.paragraphs[0], text, 8.5)
                    if ri == 0:
                        _shade(cell, SOFT)
                        for r in cell.paragraphs[0].runs:
                            r.bold = True
            header_row = table.rows[0]._tr.get_or_add_trPr()
            repeat = OxmlElement("w:tblHeader")
            repeat.set(qn("w:val"), "true")
            header_row.append(repeat)
            doc.add_paragraph()

    out = io.BytesIO()
    doc.save(out)
    return out.getvalue()


# ---- PDF ----

# Core PDF fonts are Windows-1252; map the few characters outside it, "?" for anything else.
PDF_SUBS = str.maketrans({"→": "->", "−": "-", "≥": ">=", "≤": "<=", "×": "x"})
HTML_STYLES = {
    "p": FontFace(family="Helvetica", size_pt=9.5),
    "code": FontFace(family="Courier", size_pt=9, color=DARK),
}


def _pdf_text(text: str) -> str:
    return text.translate(PDF_SUBS).encode("cp1252", "replace").decode("cp1252")


class _Pdf(FPDF):
    doc_title = ""

    def header(self) -> None:
        if self.page_no() == 1:
            return
        self.image(str(LOGO), x=self.l_margin, y=8, w=34)
        self.set_font("Helvetica", size=8)
        self.set_text_color(*MUTED)
        self.set_xy(self.l_margin, 10)
        self.cell(0, 4, _pdf_text(self.doc_title), align="R")
        self.set_draw_color(*LINE)
        self.line(self.l_margin, 17, self.w - self.r_margin, 17)
        self.set_y(22)

    def footer(self) -> None:
        if self.page_no() == 1:
            return
        self.set_y(-12)
        self.set_font("Helvetica", size=8)
        self.set_text_color(*MUTED)
        self.cell(
            0,
            5,
            f"{SUBTITLE}  -  Generated {_today()}  -  Page {self.page_no()} of {{nb}}",
            align="C",
        )


def _inline_html(text: str) -> str:
    parts = []
    for piece, bold, code in runs(_pdf_text(text)):
        piece = html.escape(piece)
        piece = f"<code>{piece}</code>" if code else piece
        parts.append(f"<b>{piece}</b>" if bold else piece)
    return "".join(parts)


def _write_html(pdf: FPDF, markup: str) -> None:
    # write_html wraps across bold/code fragments; per-fragment write() splits code mid-word.
    pdf.set_font("Helvetica", size=9.5)
    pdf.set_text_color(0x14, 0x22, 0x25)
    pdf.write_html(markup, tag_styles=HTML_STYLES, li_prefix_color=ACCENT, ul_bullet_char="\u2022")


def _col_widths(pdf: FPDF, rows: list[list[str]]) -> list[float]:
    """Each column fits its longest word; leftover width is shared by content length."""
    pdf.set_font("Helvetica", "B", 8)
    cols = range(len(rows[0]))
    need = [
        max(pdf.get_string_width(w) for r in rows for w in r[c].split() or [""]) + 4 for c in cols
    ]
    longest = [max(len(r[c]) for r in rows) or 1 for c in cols]
    extra = pdf.epw - sum(need)
    if extra < 0:
        return [pdf.epw * n / sum(longest) for n in longest]
    return [n + extra * n_chars / sum(longest) for n, n_chars in zip(need, longest, strict=True)]


def build_pdf() -> bytes:
    title, body, intro = _source()
    pdf = _Pdf(format="A4")
    pdf.core_fonts_encoding = "windows-1252"
    pdf.doc_title = title
    pdf.set_title(title)
    pdf.set_author("ProviDRs Care")
    pdf.set_margins(18, 22, 18)
    pdf.set_auto_page_break(True, margin=18)

    pdf.add_page()
    pdf.image(str(LOGO), x=(pdf.w - 110) / 2, y=80, w=110)
    pdf.set_y(115)
    for text, size, color, style in (
        (title, 24, DARK, "B"),
        (SUBTITLE, 14, ACCENT, ""),
        (_today(), 11, MUTED, ""),
    ):
        pdf.set_font("Helvetica", style, size)
        pdf.set_text_color(*color)
        pdf.cell(0, size * 0.6, _pdf_text(text), align="C", new_x="LMARGIN", new_y="NEXT")
        pdf.ln(4)
    pdf.ln(12)
    pdf.set_font("Helvetica", size=10)
    pdf.set_text_color(*MUTED)
    pdf.multi_cell(0, 5, _pdf_text(intro.replace("`", "")), align="C")

    pdf.add_page()
    for kind, value in body:
        if kind == "heading":
            level, text = value
            text = _pdf_text(text.replace("`", ""))
            if pdf.get_y() > pdf.h - 50:
                pdf.add_page()
            pdf.start_section(text, level=level - 2, strict=False)
            pdf.ln(4 if level > 2 else 6)
            pdf.set_font("Helvetica", "B", 15 if level == 2 else 11.5)
            pdf.set_text_color(*(DARK if level == 2 else ACCENT))
            pdf.multi_cell(0, 7, text, new_x="LMARGIN", new_y="NEXT")
            if level == 2:
                pdf.set_draw_color(*ACCENT)
                pdf.line(pdf.l_margin, pdf.get_y(), pdf.l_margin + 30, pdf.get_y())
            pdf.ln(2)
        elif kind == "para":
            _write_html(pdf, f"<p>{_inline_html(value)}</p>")
            pdf.ln(1.5)
        elif kind == "list":
            ordered, items = value
            tag = "ol" if ordered else "ul"
            _write_html(
                pdf, f"<{tag}>{''.join(f'<li>{_inline_html(i)}</li>' for i in items)}</{tag}>"
            )
        elif kind == "code":
            pdf.set_font("Courier", size=8)
            pdf.set_text_color(*DARK)
            pdf.set_fill_color(*CANVAS)
            pdf.multi_cell(0, 4, _pdf_text(value), fill=True, padding=3)
            pdf.ln(3)
        elif kind == "table":
            rows = [[_pdf_text(c.replace("`", "")) for c in r] for r in value]
            widths = _col_widths(pdf, rows)
            pdf.set_font("Helvetica", size=8)
            pdf.set_text_color(0x14, 0x22, 0x25)
            pdf.set_draw_color(*LINE)
            with pdf.table(
                col_widths=widths,
                headings_style=FontFace(emphasis="B", color=DARK, fill_color=SOFT),
                line_height=4,
                text_align="LEFT",
                markdown=True,
                padding=1.5,
            ) as table:
                for row in rows:
                    table.row(row)
            pdf.ln(4)

    return bytes(pdf.output())


@functools.cache
def _cached(fmt: str, mtime: float) -> bytes:
    return build_docx() if fmt == "docx" else build_pdf()


def render(fmt: str) -> bytes:
    """Rebuilt only when the dictionary file changes."""
    return _cached(fmt, DICTIONARY.stat().st_mtime)
