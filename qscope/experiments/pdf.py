"""A small, dependency-free PDF writer.

QScope can export research reports as PDF without pulling in a PDF library: this
module emits a valid PDF 1.4 document with the three standard fonts (Helvetica,
Helvetica-Bold, Courier) and vector primitives so charts stay sharp at any zoom.
Generated PDFs open in every reader and are printable; they are deliberately
simple (no fonts embedded beyond the standard 14, no compression) so the output is
auditable rather than opaque.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Sequence

PAGE_WIDTH = 595.28  # A4 in points
PAGE_HEIGHT = 841.89
MARGIN = 48.0

FONTS = {"regular": "F1", "bold": "F2", "mono": "F3"}


def _escape(text: str) -> str:
    """Escape a string for a PDF literal string."""
    out = []
    for ch in text:
        if ch in "()\\":
            out.append("\\" + ch)
        elif ord(ch) > 126 or ord(ch) < 32:
            # WinAnsi approximation: replace anything outside ASCII with a safe glyph
            # so the document stays valid even with unicode input.
            out.append("?" if ord(ch) < 128 else _ascii_fallback(ch))
        else:
            out.append(ch)
    return "".join(out)


_ASCII_FALLBACK = {
    "·": "-", "×": "x", "→": "->", "←": "<-", "≈": "~", "≤": "<=", "≥": ">=",
    "√": "sqrt", "⊗": "x", "π": "pi", "θ": "theta", "ψ": "psi", "⟨": "<", "⟩": ">",
    "²": "2", "³": "3", "—": "-", "–": "-", "…": "...", "†": "dag", "∝": "prop",
}


def _ascii_fallback(ch: str) -> str:
    if ch in _ASCII_FALLBACK:
        return _ASCII_FALLBACK[ch]
    import unicodedata

    decomposed = unicodedata.normalize("NFKD", ch)
    ascii_only = "".join(c for c in decomposed if ord(c) < 128)
    return ascii_only or "?"


@dataclass
class Page:
    """One PDF page with a content stream builder."""

    number: int
    content: list[str] = field(default_factory=list)
    width: float = PAGE_WIDTH
    height: float = PAGE_HEIGHT

    def text(
        self,
        x: float,
        y: float,
        text: str,
        *,
        size: float = 10.0,
        font: str = "regular",
        color: tuple[float, float, float] = (0.1, 0.1, 0.12),
        max_width: float | None = None,
    ) -> float:
        """Draw text at ``(x, y)`` (PDF units, origin bottom-left). Returns the y used."""
        for line in _wrap(text, size, max_width) if max_width else [text]:
            self.content.append(
                f"BT /{FONTS[font]} {size:.2f} Tf {color[0]:.3f} {color[1]:.3f} {color[2]:.3f} rg "
                f"{x:.2f} {y:.2f} Td ({_escape(line)}) Tj ET"
            )
            y -= size * 1.35
        return y

    def rect(
        self,
        x: float,
        y: float,
        width: float,
        height: float,
        *,
        fill: tuple[float, float, float] | None = None,
        stroke: tuple[float, float, float] | None = None,
        line_width: float = 0.6,
    ) -> None:
        ops = []
        if fill is not None:
            ops.append(f"{fill[0]:.3f} {fill[1]:.3f} {fill[2]:.3f} rg")
        if stroke is not None:
            ops.append(f"{stroke[0]:.3f} {stroke[1]:.3f} {stroke[2]:.3f} RG {line_width:.2f} w")
        ops.append(f"{x:.2f} {y:.2f} {width:.2f} {height:.2f} re")
        ops.append("B" if (fill is not None and stroke is not None) else "f" if fill is not None else "S")
        self.content.append(" ".join(ops))

    def line(
        self,
        x1: float,
        y1: float,
        x2: float,
        y2: float,
        *,
        color: tuple[float, float, float] = (0.5, 0.5, 0.55),
        width: float = 0.6,
    ) -> None:
        self.content.append(
            f"{color[0]:.3f} {color[1]:.3f} {color[2]:.3f} RG {width:.2f} w "
            f"{x1:.2f} {y1:.2f} m {x2:.2f} {y2:.2f} l S"
        )

    def polyline(
        self,
        points: Sequence[tuple[float, float]],
        *,
        color: tuple[float, float, float] = (0.2, 0.5, 0.9),
        width: float = 1.4,
        close: bool = False,
    ) -> None:
        if len(points) < 2:
            return
        parts = [f"{color[0]:.3f} {color[1]:.3f} {color[2]:.3f} RG {width:.2f} w"]
        parts.append(f"{points[0][0]:.2f} {points[0][1]:.2f} m")
        for x, y in points[1:]:
            parts.append(f"{x:.2f} {y:.2f} l")
        if close:
            parts.append("h")
        parts.append("S")
        self.content.append(" ".join(parts))

    def stream(self) -> bytes:
        return ("\n".join(self.content) + "\n").encode("latin-1", errors="replace")


def _wrap(text: str, size: float, max_width: float) -> list[str]:
    """Very small greedy word wrapper (Courier-independent estimate)."""
    per_char = size * 0.5
    limit = max(int(max_width / per_char), 8)
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if len(candidate) <= limit:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines or [""]


class PDFDocument:
    """Build a multi-page PDF document."""

    def __init__(self, title: str = "QScope report", author: str = "QScope") -> None:
        self.title = title
        self.author = author
        self.pages: list[Page] = []
        self._objects: list[bytes] = []

    # --------------------------------------------------------------- objects

    def _add(self, payload: bytes) -> int:
        self._objects.append(payload)
        return len(self._objects)

    # ----------------------------------------------------------------- pages

    def new_page(self) -> Page:
        page = Page(number=len(self.pages) + 1)
        self.pages.append(page)
        return page

    def to_bytes(self) -> bytes:
        if not self.pages:
            self.new_page()
        self._objects = []
        catalog_num = self._add(b"")  # placeholder, filled last
        pages_num = self._add(b"")
        font_regular = self._add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>")
        font_bold = self._add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>")
        font_mono = self._add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Courier /Encoding /WinAnsiEncoding >>")

        page_numbers: list[int] = []
        for page in self.pages:
            content = page.stream()
            content_num = self._add(
                b"<< /Length " + str(len(content)).encode() + b" >>\nstream\n" + content + b"\nendstream"
            )
            page_num = self._add(
                (
                    f"<< /Type /Page /Parent {pages_num} 0 R /MediaBox [0 0 {page.width:.2f} {page.height:.2f}] "
                    f"/Resources << /Font << /F1 {font_regular} 0 R /F2 {font_bold} 0 R /F3 {font_mono} 0 R >> >> "
                    f"/Contents {content_num} 0 R >>"
                ).encode()
            )
            page_numbers.append(page_num)

        self._objects[catalog_num - 1] = (
            f"<< /Type /Catalog /Pages {pages_num} 0 R >>".encode()
        )
        kids = " ".join(f"{n} 0 R" for n in page_numbers)
        self._objects[pages_num - 1] = (
            f"<< /Type /Pages /Kids [{kids}] /Count {len(page_numbers)} >>".encode()
        )

        info_num = self._add(
            f"<< /Title ({_escape(self.title)}) /Author ({_escape(self.author)}) "
            f"/Producer (QScope) /Creator (QScope) >>".encode()
        )

        out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
        offsets: list[int] = []
        for index, payload in enumerate(self._objects, start=1):
            offsets.append(len(out))
            out += f"{index} 0 obj\n".encode()
            out += payload
            out += b"\nendobj\n"
        xref_offset = len(out)
        out += f"xref\n0 {len(self._objects) + 1}\n".encode()
        out += b"0000000000 65535 f \n"
        for offset in offsets:
            out += f"{offset:010d} 00000 n \n".encode()
        out += (
            f"trailer\n<< /Size {len(self._objects) + 1} /Root {catalog_num} 0 R /Info {info_num} 0 R >>\n"
            f"startxref\n{xref_offset}\n%%EOF\n"
        ).encode()
        return bytes(out)

    def write(self, path: str) -> str:
        with open(path, "wb") as handle:
            handle.write(self.to_bytes())
        return path


__all__ = ["MARGIN", "PAGE_HEIGHT", "PAGE_WIDTH", "PDFDocument", "Page"]
