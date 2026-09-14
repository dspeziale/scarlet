"""Shared building blocks for the SCARLET PDF manuals.

Everything is typeset in PT Sans Narrow (PT Mono for commands), the fonts shipped under
``docs/assets/fonts`` with their OFL licence. The module owns the page furniture (cover,
running header, page numbers), the paragraph/table/code/callout styles and a tiny vector
diagram helper, so each manual script only describes its own content.

Build the manuals with ``python scripts/build_pdf_docs.py``.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    BaseDocTemplate,
    Flowable,
    Frame,
    KeepTogether,
    NextPageTemplate,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

ROOT = Path(__file__).resolve().parent.parent
FONT_DIR = ROOT / "docs" / "assets" / "fonts"
OUT_DIR = ROOT / "docs" / "pdf"

# --- brand ---------------------------------------------------------------------------------
RED = colors.HexColor("#b3172c")
DARK = colors.HexColor("#2c2f33")
INK = colors.HexColor("#1f2226")
MUTED = colors.HexColor("#6b7177")
RULE = colors.HexColor("#d5d8dc")
PANEL = colors.HexColor("#f4f5f7")
CODE_BG = colors.HexColor("#1e2124")
CODE_FG = colors.HexColor("#e6e6e6")
OK = colors.HexColor("#1d7a46")
WARN = colors.HexColor("#8a6100")
INFO = colors.HexColor("#1d4f7a")

PAGE = A4
MARGIN_X = 18 * mm
MARGIN_TOP = 22 * mm
MARGIN_BOTTOM = 18 * mm
CONTENT_WIDTH = PAGE[0] - 2 * MARGIN_X

#: Deve restare allineato a ``app.__copyright__``: un test lo verifica.
COPYRIGHT = "© 2024-26 DS Consulting"

BODY = "PTSansNarrow"
BOLD = "PTSansNarrow-Bold"
MONO = "PTMono"


def register_fonts() -> None:
    """Register the PT family. Raises if a font file is missing, rather than silently
    falling back to Helvetica and producing a document in the wrong typeface."""
    files = {
        BODY: "PT_Sans-Narrow-Web-Regular.ttf",
        BOLD: "PT_Sans-Narrow-Web-Bold.ttf",
        MONO: "PTMono-Regular.ttf",
    }
    for name, filename in files.items():
        path = FONT_DIR / filename
        if not path.exists():
            raise FileNotFoundError(f"missing font {path}; see docs/assets/fonts/README.md")
        pdfmetrics.registerFont(TTFont(name, str(path)))
    pdfmetrics.registerFontFamily(BODY, normal=BODY, bold=BOLD, italic=BODY, boldItalic=BOLD)


# Registered at import time: every ParagraphStyle below names the fonts, and reportlab
# resolves the family the moment a Paragraph is built.
register_fonts()


# --- styles ---------------------------------------------------------------------------------


def _style(name: str, **kwargs: Any) -> ParagraphStyle:
    base = {
        "fontName": BODY,
        "fontSize": 9.6,
        "leading": 13.2,
        "textColor": INK,
        "spaceAfter": 5,
        # senza questo reportlab compone i punti elenco in Helvetica e la incorpora nel PDF
        "bulletFontName": BODY,
        "bulletFontSize": 8.4,
    }
    base.update(kwargs)
    return ParagraphStyle(name, **base)


S = {
    "h1": _style(
        "h1", fontName=BOLD, fontSize=19, leading=22, textColor=RED, spaceBefore=2, spaceAfter=8
    ),
    "h2": _style(
        "h2", fontName=BOLD, fontSize=13.5, leading=16, textColor=DARK, spaceBefore=11, spaceAfter=5
    ),
    "h3": _style(
        "h3", fontName=BOLD, fontSize=10.8, leading=13, textColor=DARK, spaceBefore=8, spaceAfter=3
    ),
    "body": _style("body", alignment=TA_JUSTIFY),
    "lead": _style("lead", fontSize=11, leading=15, textColor=DARK, spaceAfter=7),
    "small": _style("small", fontSize=8.4, leading=11, textColor=MUTED),
    "bullet": _style("bullet", leftIndent=10, bulletIndent=2, spaceAfter=2.5),
    "cell": _style("cell", fontSize=8.6, leading=11, spaceAfter=0),
    "cellhead": _style(
        "cellhead", fontName=BOLD, fontSize=8.6, leading=11, textColor=colors.white, spaceAfter=0
    ),
    "cellmono": _style("cellmono", fontName=MONO, fontSize=7.6, leading=10.4, spaceAfter=0),
    "code": ParagraphStyle(
        "code", fontName=MONO, fontSize=8.1, leading=11.4, textColor=CODE_FG, spaceAfter=0
    ),
    "caption": _style(
        "caption", fontSize=8.2, leading=10.5, textColor=MUTED, alignment=TA_CENTER, spaceBefore=3
    ),
    "toc1": _style("toc1", fontName=BOLD, fontSize=10, leading=15, spaceAfter=0),
    "toc2": _style("toc2", fontSize=9.2, leading=13, leftIndent=12, textColor=DARK, spaceAfter=0),
    "coverTitle": _style(
        "coverTitle", fontName=BOLD, fontSize=34, leading=36, textColor=colors.white, spaceAfter=0
    ),
    "coverSub": _style(
        "coverSub", fontSize=14, leading=18, textColor=colors.HexColor("#f2d6da"), spaceAfter=0
    ),
    "coverMeta": _style(
        "coverMeta", fontSize=9.4, leading=14, textColor=colors.HexColor("#d9dade"), spaceAfter=0
    ),
}


# --- glyph safety ------------------------------------------------------------------------------


def _coverage(name: str) -> set[int]:
    return set(pdfmetrics.getFont(name).face.charToGlyph.keys())


# Running text can be set in regular or bold at any moment, so it must exist in both faces.
SUPPORTED_TEXT = _coverage(BODY) & _coverage(BOLD)
SUPPORTED_MONO = _coverage(MONO)
_TAG = re.compile(r"<[^>]+>")


def check(text: str, *, mono: bool = False) -> str:
    """Fail the build on a character the chosen face cannot draw.

    A missing glyph is not an error at render time: reportlab silently prints an empty box,
    which is easy to miss in a 17-page manual. Checking here turns it into a build failure
    naming the character and the string it came from.
    """
    covered = SUPPORTED_MONO if mono else SUPPORTED_TEXT
    plain = _TAG.sub("", text)
    missing = sorted({ch for ch in plain if ord(ch) not in covered and not ch.isspace()})
    if missing:
        names = ", ".join(f"{ch!r} (U+{ord(ch):04X})" for ch in missing)
        raise ValueError(f"carattere non disponibile nel font: {names} — in: {plain[:90]!r}")
    return text


# --- inline helpers ---------------------------------------------------------------------------


def esc(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def c(text: str) -> str:
    """Inline code fragment."""
    return f'<font face="{MONO}" size="8.2" color="#8a1020">{esc(text)}</font>'


def b(text: str) -> str:
    return f"<b>{text}</b>"


# --- flowables ---------------------------------------------------------------------------------


class Rule(Flowable):
    """A thin horizontal rule used to separate sections."""

    def __init__(
        self, width: float = CONTENT_WIDTH, color: colors.Color = RULE, thickness: float = 0.6
    ):
        super().__init__()
        self.width, self.color, self.thickness = width, color, thickness
        self.height = thickness

    def draw(self) -> None:
        self.canv.setStrokeColor(self.color)
        self.canv.setLineWidth(self.thickness)
        self.canv.line(0, 0, self.width, 0)


def para(text: str, style: str = "body") -> Paragraph:
    return Paragraph(check(text), S[style])


def h1(text: str, anchor: str | None = None) -> list[Flowable]:
    label = f'<a name="{anchor}"/>{check(text)}' if anchor else check(text)
    return [Paragraph(label, S["h1"]), Rule(color=RED, thickness=1.2), Spacer(1, 7)]


def h2(text: str) -> Paragraph:
    return Paragraph(check(text), S["h2"])


def h3(text: str) -> Paragraph:
    return Paragraph(check(text), S["h3"])


def bullets(items: Sequence[str], style: str = "bullet") -> list[Flowable]:
    return [Paragraph(check(item), S[style], bulletText="•") for item in items]


def numbered(items: Sequence[str], style: str = "bullet") -> list[Flowable]:
    return [Paragraph(check(item), S[style], bulletText=f"{i}.") for i, item in enumerate(items, 1)]


def table(
    rows: Sequence[Sequence[str]],
    widths: Sequence[float],
    *,
    header: bool = True,
    mono_cols: Sequence[int] = (),
    align_center: Sequence[int] = (),
    font_size: float | None = None,
) -> Table:
    """A table whose cells wrap: every cell is a Paragraph, so long commands never overflow."""
    body_style = (
        S["cell"]
        if font_size is None
        else _style("cell_x", fontSize=font_size, leading=font_size + 2.4, spaceAfter=0)
    )
    mono_style = (
        S["cellmono"]
        if font_size is None
        else _style(
            "mono_x", fontName=MONO, fontSize=font_size - 0.8, leading=font_size + 2.2, spaceAfter=0
        )
    )
    data = []
    for r, row in enumerate(rows):
        line = []
        for col, cell in enumerate(row):
            if header and r == 0:
                line.append(Paragraph(check(cell), S["cellhead"]))
            else:
                line.append(Paragraph(check(cell), mono_style if col in mono_cols else body_style))
        data.append(line)
    total = sum(widths)
    scaled = [w / total * CONTENT_WIDTH for w in widths]
    style = [
        ("GRID", (0, 0), (-1, -1), 0.4, RULE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("ROWBACKGROUNDS", (0, 1 if header else 0), (-1, -1), [colors.white, PANEL]),
    ]
    if header:
        style += [
            ("BACKGROUND", (0, 0), (-1, 0), DARK),
            ("LINEBELOW", (0, 0), (-1, 0), 0.8, DARK),
        ]
    for col in align_center:
        style.append(("ALIGN", (col, 0), (col, -1), "CENTER"))
    t = Table(data, colWidths=scaled, repeatRows=1 if header else 0)
    t.setStyle(TableStyle(style))
    return t


def code(lines: str | Sequence[str], *, title: str | None = None) -> Flowable:
    """A dark command block. Long lines are wrapped by the paragraph, never clipped."""
    text = lines if isinstance(lines, str) else "\n".join(lines)
    rendered = []
    for raw in text.split("\n"):
        indent = len(raw) - len(raw.lstrip(" "))
        body = esc(raw.strip("\n"))
        body = body.replace("  ", "&nbsp;&nbsp;")
        if not body.strip():
            body = "&nbsp;"
        colour = "#9aa4ad" if raw.lstrip().startswith("#") else None
        if colour:
            body = f'<font color="{colour}">{body}</font>'
        rendered.append(
            Paragraph(body, ParagraphStyle(f"c{indent}", parent=S["code"], leftIndent=0))
        )
    inner = Table([[r] for r in rendered], colWidths=[CONTENT_WIDTH - 12])
    inner.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), CODE_BG),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 1.6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 1.6),
            ]
        )
    )
    outer_rows = []
    if title:
        outer_rows.append(
            [
                Paragraph(
                    f'<font color="#ffffff">{esc(title)}</font>',
                    ParagraphStyle("ct", parent=S["code"], fontName=BODY, fontSize=8.4),
                )
            ]
        )
    outer_rows.append([inner])
    outer = Table(outer_rows, colWidths=[CONTENT_WIDTH])
    outer.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), CODE_BG),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ("LINEBEFORE", (0, 0), (0, -1), 2.4, RED),
            ]
        )
    )
    return outer


def callout(text: str, kind: str = "info", *, title: str | None = None) -> Flowable:
    palette = {
        "info": (INFO, colors.HexColor("#eaf1f8")),
        "warn": (WARN, colors.HexColor("#fdf4e3")),
        "danger": (RED, colors.HexColor("#fbeced")),
        "ok": (OK, colors.HexColor("#eaf5ee")),
    }
    accent, background = palette[kind]
    head = f'<font color="#{accent.hexval()[2:]}"><b>{title}</b></font><br/>' if title else ""
    inner = Paragraph(
        check(head + text), _style("callout_body", fontSize=9.1, leading=12.4, spaceAfter=0)
    )
    t = Table([[inner]], colWidths=[CONTENT_WIDTH])
    t.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), background),
                ("LINEBEFORE", (0, 0), (0, -1), 2.6, accent),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    return t


def caption(text: str) -> Paragraph:
    return Paragraph(check(text), S["caption"])


def together(items: Sequence[Flowable]) -> KeepTogether:
    return KeepTogether(list(items))


def space(height: float = 6) -> Spacer:
    return Spacer(1, height)


# --- diagrams ------------------------------------------------------------------------------------


@dataclass
class Box:
    """One node of a block diagram, in millimetres from the bottom-left of the drawing."""

    x: float
    y: float
    w: float
    h: float
    title: str
    lines: Sequence[str] = field(default_factory=tuple)
    fill: colors.Color = colors.white
    stroke: colors.Color = DARK
    text_color: colors.Color = INK
    title_size: float = 8.6
    line_size: float = 7.2
    dashed: bool = False
    radius: float = 1.6


class Diagram(Flowable):
    """A vector block diagram: boxes, arrows and free labels, sized in millimetres.

    Nothing here is a bitmap, so the drawing stays sharp at any zoom and the text is
    selectable and searchable in the PDF.
    """

    def __init__(
        self, width_mm: float, height_mm: float, *, background: colors.Color | None = None
    ):
        super().__init__()
        self.width = width_mm * mm
        self.height = height_mm * mm
        self.background = background
        self.boxes: list[Box] = []
        self.arrows: list[tuple] = []
        self.labels: list[tuple] = []
        self.rects: list[tuple] = []

    # -- authoring API
    def box(self, *args: Any, **kwargs: Any) -> Box:
        node = Box(*args, **kwargs)
        check(node.title)
        for line in node.lines:
            check(line)
        self.boxes.append(node)
        return node

    def group(
        self, x: float, y: float, w: float, h: float, label: str = "", *, color: colors.Color = RULE
    ) -> None:
        check(label)
        self.rects.append((x, y, w, h, label, color))

    def arrow(
        self,
        start: tuple[float, float],
        end: tuple[float, float],
        label: str = "",
        *,
        color: colors.Color = DARK,
        dashed: bool = False,
        label_dy: float = 1.4,
        double: bool = False,
        bend: tuple[float, float] | None = None,
    ) -> None:
        check(label)
        self.arrows.append((start, end, label, color, dashed, label_dy, double, bend))

    def label(
        self,
        x: float,
        y: float,
        text: str,
        *,
        size: float = 7.2,
        color: colors.Color = MUTED,
        anchor: str = "start",
        bold: bool = False,
    ) -> None:
        check(text)
        self.labels.append((x, y, text, size, color, anchor, bold))

    def text_block(
        self,
        x: float,
        top: float,
        width: float,
        text: str,
        *,
        size: float = 6.8,
        leading: float = 3.1,
        color: colors.Color = MUTED,
    ) -> float:
        """Free text wrapped on word boundaries inside a given width, in millimetres.

        ``label`` draws a single line; this one is for the annotations beside a diagram, which
        must break between words rather than mid-word. Returns the y of the last line drawn.
        """
        y = top
        for line in _wrap(check(text), BODY, size, width * mm):
            self.label(x, y, line, size=size, color=color)
            y -= leading
        return y

    # -- rendering
    def draw(self) -> None:
        canvas = self.canv
        if self.background:
            canvas.setFillColor(self.background)
            canvas.rect(0, 0, self.width, self.height, stroke=0, fill=1)
        for x, y, w, h, label, color in self.rects:
            canvas.setStrokeColor(color)
            canvas.setDash(2, 2)
            canvas.setLineWidth(0.7)
            canvas.roundRect(x * mm, y * mm, w * mm, h * mm, 2 * mm, stroke=1, fill=0)
            canvas.setDash()
            if label:
                canvas.setFillColor(MUTED)
                canvas.setFont(BOLD, 7.2)
                canvas.drawString(x * mm + 2 * mm, (y + h) * mm - 4.2 * mm, label)
        for node in self.boxes:
            canvas.setFillColor(node.fill)
            canvas.setStrokeColor(node.stroke)
            canvas.setLineWidth(0.9)
            if node.dashed:
                canvas.setDash(2.5, 2)
            canvas.roundRect(
                node.x * mm,
                node.y * mm,
                node.w * mm,
                node.h * mm,
                node.radius * mm,
                stroke=1,
                fill=1,
            )
            canvas.setDash()
            cx = (node.x + node.w / 2) * mm
            top = (node.y + node.h) * mm
            canvas.setFillColor(node.text_color)
            canvas.setFont(BOLD, node.title_size)
            title_y = top - (node.title_size + 2.6)
            if not node.lines:
                title_y = node.y * mm + (node.h * mm - node.title_size) / 2 + 0.6
            canvas.drawCentredString(cx, title_y, node.title)
            canvas.setFont(BODY, node.line_size)
            y = title_y - (node.line_size + 2.1)
            for line in node.lines:
                canvas.drawCentredString(cx, y, line)
                y -= node.line_size + 1.6
        for (sx, sy), (ex, ey), text, color, dashed, label_dy, double, bend in self.arrows:
            canvas.setStrokeColor(color)
            canvas.setFillColor(color)
            canvas.setLineWidth(0.9)
            if dashed:
                canvas.setDash(2.5, 2)
            path = [(sx * mm, sy * mm)]
            if bend:
                path.append((bend[0] * mm, bend[1] * mm))
            path.append((ex * mm, ey * mm))
            for (x1, y1), (x2, y2) in zip(path, path[1:], strict=False):
                canvas.line(x1, y1, x2, y2)
            canvas.setDash()
            self._head(path[-2], path[-1], color)
            if double:
                self._head(path[1], path[0], color)
            if text:
                mx = (path[-2][0] + path[-1][0]) / 2
                my = (path[-2][1] + path[-1][1]) / 2
                canvas.setFillColor(MUTED)
                canvas.setFont(BODY, 7)
                if abs(path[-1][0] - path[-2][0]) < 1 * mm:
                    # vertical arrow: sit the label beside the line, never across it
                    canvas.drawString(mx + 1.8 * mm, my + label_dy * mm, text)
                else:
                    canvas.drawCentredString(mx, my + label_dy * mm, text)
        for x, y, text, size, color, anchor, bold in self.labels:
            canvas.setFillColor(color)
            canvas.setFont(BOLD if bold else BODY, size)
            if anchor == "middle":
                canvas.drawCentredString(x * mm, y * mm, text)
            elif anchor == "end":
                canvas.drawRightString(x * mm, y * mm, text)
            else:
                canvas.drawString(x * mm, y * mm, text)

    def _head(
        self, start: tuple[float, float], end: tuple[float, float], color: colors.Color
    ) -> None:
        import math

        (x1, y1), (x2, y2) = start, end
        angle = math.atan2(y2 - y1, x2 - x1)
        size = 2.2 * mm
        p1 = (x2, y2)
        p2 = (x2 - size * math.cos(angle - math.pi / 7), y2 - size * math.sin(angle - math.pi / 7))
        p3 = (x2 - size * math.cos(angle + math.pi / 7), y2 - size * math.sin(angle + math.pi / 7))
        self.canv.setFillColor(color)
        path = self.canv.beginPath()
        path.moveTo(*p1)
        path.lineTo(*p2)
        path.lineTo(*p3)
        path.close()
        self.canv.drawPath(path, stroke=0, fill=1)


# --- document ---------------------------------------------------------------------------------


@dataclass
class DocMeta:
    title: str
    subtitle: str
    kicker: str
    version: str
    date: str
    audience: str
    summary: str
    filename: str
    highlights: Sequence[str] = ()


class Manual(BaseDocTemplate):
    """Cover page without furniture, then numbered pages with a running header."""

    def __init__(self, meta: DocMeta, path: Path):
        super().__init__(
            str(path),
            pagesize=PAGE,
            leftMargin=MARGIN_X,
            rightMargin=MARGIN_X,
            topMargin=MARGIN_TOP,
            bottomMargin=MARGIN_BOTTOM,
            title=" ".join(meta.title.split()),
            author="DS Consulting",
            subject=f"{meta.subtitle} — {COPYRIGHT}",
            creator="SCARLET documentation build (scripts/build_pdf_docs.py)",
        )
        self.meta = meta
        frame = Frame(
            MARGIN_X, MARGIN_BOTTOM, CONTENT_WIDTH, PAGE[1] - MARGIN_TOP - MARGIN_BOTTOM, id="body"
        )
        cover_frame = Frame(
            0,
            0,
            PAGE[0],
            PAGE[1],
            id="cover",
            leftPadding=0,
            rightPadding=0,
            topPadding=0,
            bottomPadding=0,
        )
        self.addPageTemplates(
            [
                PageTemplate(id="cover", frames=[cover_frame], onPage=self._cover),
                PageTemplate(id="body", frames=[frame], onPage=self._furniture),
            ]
        )

    def _cover(self, canvas, doc) -> None:
        canvas.saveState()
        canvas.setFillColor(DARK)
        canvas.rect(0, 0, PAGE[0], PAGE[1], stroke=0, fill=1)
        canvas.setFillColor(RED)
        canvas.rect(0, PAGE[1] - 118 * mm, PAGE[0], 118 * mm, stroke=0, fill=1)
        # logo mark
        canvas.setFillColor(colors.white)
        canvas.roundRect(MARGIN_X, PAGE[1] - 46 * mm, 16 * mm, 16 * mm, 3 * mm, stroke=0, fill=1)
        canvas.setFillColor(RED)
        canvas.setFont(BOLD, 20)
        canvas.drawCentredString(MARGIN_X + 8 * mm, PAGE[1] - 40.5 * mm, "S")
        canvas.setFillColor(colors.white)
        canvas.setFont(BOLD, 13)
        canvas.drawString(MARGIN_X + 21 * mm, PAGE[1] - 36 * mm, "SCARLET")
        canvas.setFont(BODY, 8.4)
        canvas.setFillColor(colors.HexColor("#f3c9ce"))
        canvas.drawString(
            MARGIN_X + 21 * mm,
            PAGE[1] - 41 * mm,
            "System Container Application Release, Lifecycle & Environment Tool",
        )

        canvas.setFont(BODY, 11)
        canvas.setFillColor(colors.HexColor("#f7dee2"))
        canvas.drawString(MARGIN_X, PAGE[1] - 66 * mm, self.meta.kicker.upper())
        text = canvas.beginText(MARGIN_X, PAGE[1] - 84 * mm)
        text.setFont(BOLD, 30)
        text.setFillColor(colors.white)
        text.setLeading(33)
        for line in self.meta.title.split("\n"):
            text.textLine(line)
        canvas.drawText(text)
        canvas.setFont(BODY, 13)
        canvas.setFillColor(colors.HexColor("#f7dee2"))
        canvas.drawString(MARGIN_X, PAGE[1] - 106 * mm, self.meta.subtitle)

        # summary block on the dark half
        text = canvas.beginText(MARGIN_X, PAGE[1] - 140 * mm)
        text.setFont(BODY, 10.4)
        text.setFillColor(colors.HexColor("#e7e9ec"))
        text.setLeading(14.5)
        for line in _wrap(self.meta.summary, BODY, 10.4, CONTENT_WIDTH):
            text.textLine(line)
        canvas.drawText(text)

        if self.meta.highlights:
            y = PAGE[1] - 168 * mm
            canvas.setFont(BOLD, 8.6)
            canvas.setFillColor(colors.HexColor("#9aa0a6"))
            canvas.drawString(MARGIN_X, y, "IN QUESTO DOCUMENTO")
            y -= 9 * mm
            for item in self.meta.highlights:
                canvas.setFillColor(RED)
                canvas.rect(MARGIN_X, y + 1.1 * mm, 1.6 * mm, 1.6 * mm, stroke=0, fill=1)
                canvas.setFont(BODY, 10)
                canvas.setFillColor(colors.HexColor("#e7e9ec"))
                lines = _wrap(item, BODY, 10, CONTENT_WIDTH - 8 * mm)
                for offset, line in enumerate(lines):
                    canvas.drawString(MARGIN_X + 6 * mm, y - offset * 4.6 * mm, line)
                y -= (len(lines) * 4.6 + 2.6) * mm

        canvas.setStrokeColor(colors.HexColor("#4a4e54"))
        canvas.setLineWidth(0.8)
        canvas.line(MARGIN_X, 46 * mm, PAGE[0] - MARGIN_X, 46 * mm)
        rows = [
            ("Destinatari", self.meta.audience),
            ("Versione", self.meta.version),
            ("Data", self.meta.date),
        ]
        y = 38 * mm
        for label, value in rows:
            canvas.setFont(BOLD, 8.6)
            canvas.setFillColor(colors.HexColor("#9aa0a6"))
            canvas.drawString(MARGIN_X, y, label.upper())
            canvas.setFont(BODY, 9.6)
            canvas.setFillColor(colors.white)
            canvas.drawString(MARGIN_X + 26 * mm, y, value)
            y -= 6.5 * mm
        canvas.setFont(BODY, 9)
        canvas.setFillColor(colors.HexColor("#9aa0a6"))
        canvas.drawString(MARGIN_X, 14 * mm, COPYRIGHT)
        canvas.drawRightString(PAGE[0] - MARGIN_X, 14 * mm, "Tutti i diritti riservati")
        canvas.restoreState()

    def _furniture(self, canvas, doc) -> None:
        canvas.saveState()
        canvas.setFont(BODY, 7.8)
        canvas.setFillColor(MUTED)
        canvas.drawString(MARGIN_X, PAGE[1] - 13 * mm, f"SCARLET · {self.meta.kicker}")
        canvas.drawRightString(PAGE[0] - MARGIN_X, PAGE[1] - 13 * mm, self.meta.version)
        canvas.setStrokeColor(RULE)
        canvas.setLineWidth(0.5)
        canvas.line(MARGIN_X, PAGE[1] - 15.5 * mm, PAGE[0] - MARGIN_X, PAGE[1] - 15.5 * mm)
        canvas.line(MARGIN_X, MARGIN_BOTTOM - 5 * mm, PAGE[0] - MARGIN_X, MARGIN_BOTTOM - 5 * mm)
        canvas.setFillColor(MUTED)
        canvas.drawString(MARGIN_X, MARGIN_BOTTOM - 9.5 * mm, self.meta.filename)
        canvas.drawCentredString(PAGE[0] / 2, MARGIN_BOTTOM - 9.5 * mm, COPYRIGHT)
        canvas.setFillColor(RED)
        canvas.setFont(BOLD, 8.6)
        canvas.drawRightString(PAGE[0] - MARGIN_X, MARGIN_BOTTOM - 9.5 * mm, str(doc.page - 1))
        canvas.restoreState()


def _wrap(text: str, font: str, size: float, width: float) -> list[str]:
    words, lines, current = text.split(), [], ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if pdfmetrics.stringWidth(candidate, font, size) <= width:
            current = candidate
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def toc(entries: Sequence[tuple[int, str, str]]) -> list[Flowable]:
    """Table of contents with internal links: (level, label, anchor)."""
    out: list[Flowable] = [Paragraph("Indice", S["h2"]), Rule(), space(4)]
    for level, label, anchor in entries:
        style = "toc1" if level == 1 else "toc2"
        out.append(Paragraph(f'<a href="#{anchor}" color="#1f2226">{label}</a>', S[style]))
    return out


def build(meta: DocMeta, story: Iterable[Flowable], *, out_dir: Path = OUT_DIR) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / meta.filename
    doc = Manual(meta, path)
    flow: list[Flowable] = [NextPageTemplate("body"), PageBreak()]
    flow.extend(story)
    doc.build(flow)
    return path


def section(title: str, anchor: str, *, first: bool = False) -> list[Flowable]:
    out: list[Flowable] = [] if first else [PageBreak()]
    out.extend(h1(title, anchor))
    return out
