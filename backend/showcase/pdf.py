"""Minimal vector PDF writer for the synthetic demonstration documents (no third-party dependency).

Every page carries a red "SAMPLE - NOT FOR MANUFACTURING" banner, a diagonal SAMPLE watermark and a footer that
states the document is synthetic. Text uses the standard Helvetica fonts with WinAnsi (cp1252) encoding.
"""
from __future__ import annotations

import zlib

A4 = (595.28, 841.89)
A4_LANDSCAPE = (841.89, 595.28)
BANNER = "SAMPLE — NOT FOR MANUFACTURING"
REPLACE = {"≥": ">=", "≤": "<=", "–": "-", "−": "-", " ": " ", "→": "->", "…": "..."}


def _enc(s: str) -> bytes:
    for k, v in REPLACE.items():
        s = s.replace(k, v)
    b = s.encode("cp1252", "replace")
    return b.replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)")


def text_width(s: str, size: float, bold: bool = False) -> float:
    """Approximate Helvetica advance width (good enough for wrapping and right alignment)."""
    narrow, wide = set("il.,:;'|!()[]1 "), set("MWmw@%")
    total = 0.0
    for ch in s:
        total += 0.28 if ch in narrow else 0.83 if ch in wide else 0.67 if ch.isupper() else 0.54
    return total * size * (1.05 if bold else 1.0)


def wrap(s: str, width: float, size: float) -> list[str]:
    lines, cur = [], ""
    for word in s.split():
        cand = f"{cur} {word}".strip()
        if text_width(cand, size) <= width or not cur:
            cur = cand
        else:
            lines.append(cur)
            cur = word
    return lines + ([cur] if cur else [])


class Page:
    def __init__(self, size):
        self.w, self.h = size
        self.ops: list[bytes] = []

    def _op(self, s: str | bytes):
        self.ops.append(s.encode("latin-1") if isinstance(s, str) else s)

    def text(self, x, y, s, size=10, bold=False, color=(0, 0, 0), angle=0.0):
        font = "F2" if bold else "F1"
        r, g, b = color
        if angle:
            import math

            c, sn = math.cos(math.radians(angle)), math.sin(math.radians(angle))
            tm = f"{c:.4f} {sn:.4f} {-sn:.4f} {c:.4f} {x:.2f} {y:.2f} Tm"
        else:
            tm = f"1 0 0 1 {x:.2f} {y:.2f} Tm"
        self._op(f"BT {r:.3f} {g:.3f} {b:.3f} rg /{font} {size} Tf {tm} (".encode() + _enc(str(s)) + b") Tj ET")

    def text_right(self, x, y, s, size=10, bold=False, color=(0, 0, 0)):
        self.text(x - text_width(str(s), size, bold), y, s, size, bold, color)

    def paragraph(self, x, y, s, width, size=10, leading=None, bold=False) -> float:
        leading = leading or size * 1.35
        for line in wrap(str(s), width, size):
            self.text(x, y, line, size, bold)
            y -= leading
        return y

    def line(self, x1, y1, x2, y2, width=0.6, color=(0, 0, 0), dash=None):
        r, g, b = color
        d = f"[{dash} {dash}] 0 d " if dash else "[] 0 d "
        self._op(f"{d}{r:.3f} {g:.3f} {b:.3f} RG {width} w {x1:.2f} {y1:.2f} m {x2:.2f} {y2:.2f} l S")

    def polyline(self, pts, width=0.5, color=(0, 0, 0)):
        if len(pts) < 2:
            return
        r, g, b = color
        path = " ".join(f"{x:.2f} {y:.2f} {'m' if i == 0 else 'l'}" for i, (x, y) in enumerate(pts))
        self._op(f"[] 0 d {r:.3f} {g:.3f} {b:.3f} RG {width} w 1 J 1 j {path} S")

    def rect(self, x, y, w, h, fill=None, stroke=(0, 0, 0), width=0.6):
        ops = []
        if fill:
            ops.append(f"{fill[0]:.3f} {fill[1]:.3f} {fill[2]:.3f} rg")
        if stroke:
            ops.append(f"[] 0 d {stroke[0]:.3f} {stroke[1]:.3f} {stroke[2]:.3f} RG {width} w")
        paint = "B" if fill and stroke else "f" if fill else "S"
        ops.append(f"{x:.2f} {y:.2f} {w:.2f} {h:.2f} re {paint}")
        self._op(" ".join(ops))

    def table(self, x, y, widths, rows, size=8.5, header=True, pad=3.5, min_row=14) -> float:
        """Draw a grid table; cells wrap. Returns the y below the table."""
        for ri, row in enumerate(rows):
            cells = [wrap(str(c), w - 2 * pad, size) or [""] for c, w in zip(row, widths)]
            rh = max(min_row, max(len(c) for c in cells) * size * 1.25 + 2 * pad)
            is_head = header and ri == 0
            cx = x
            for lines, w in zip(cells, widths):
                self.rect(cx, y - rh, w, rh, fill=(0.88, 0.91, 0.95) if is_head else None, stroke=(0.45, 0.48, 0.52), width=0.5)
                ty = y - pad - size
                for ln in lines:
                    self.text(cx + pad, ty, ln, size, bold=is_head)
                    ty -= size * 1.25
                cx += w
            y -= rh
        return y


class Document:
    """A multi-page synthetic document with a standard header, banner, watermark and footer on every page."""

    def __init__(self, title: str, doc_number: str, revision: str, organisation: str, part_label: str, size=A4):
        self.title, self.doc_number, self.revision = title, doc_number, revision
        self.organisation, self.part_label, self.size = organisation, part_label, size
        self.pages: list[Page] = []

    def new_page(self) -> tuple[Page, float]:
        """Add a page; returns it with the y coordinate where content may start."""
        p = Page(self.size)
        self.pages.append(p)
        w, h = p.w, p.h
        # watermark first, so content is drawn over it
        p.text(w * 0.16, h * 0.28, "SAMPLE", size=120, bold=True, color=(0.93, 0.93, 0.95), angle=35)
        p.rect(36, h - 30, w - 72, 18, fill=(0.70, 0.13, 0.13), stroke=None)
        p.text(44, h - 25, BANNER + "  ·  SYNTHETIC DEMONSTRATION DOCUMENT", size=9, bold=True, color=(1, 1, 1))
        p.text(36, h - 52, self.title, size=15, bold=True, color=(0.08, 0.16, 0.30))
        p.text(36, h - 67, f"{self.organisation}  ·  {self.part_label}", size=9, color=(0.30, 0.33, 0.38))
        p.text_right(w - 36, h - 52, f"Doc. {self.doc_number}", size=9, bold=True)
        p.text_right(w - 36, h - 65, f"Revision {self.revision}  ·  Status: DRAFT (not approved)", size=8.5)
        p.line(36, h - 74, w - 36, h - 74, width=0.8, color=(0.08, 0.16, 0.30))
        return p, h - 92

    def build(self, producer: str = "Digital Passport demonstration generator") -> bytes:
        total = len(self.pages)
        for i, p in enumerate(self.pages, 1):
            p.line(36, 40, p.w - 36, 40, width=0.5, color=(0.6, 0.6, 0.6))
            p.text(36, 28, "Synthetic content generated for software demonstration. Contains no real customer data, "
                           "test results, approvals or certifications.", size=7, color=(0.35, 0.35, 0.35))
            p.text_right(p.w - 36, 28, f"Page {i} of {total}", size=7.5)
        objs: list[bytes] = []

        def add(body: bytes) -> int:
            objs.append(body)
            return len(objs)

        catalog = add(b"")  # placeholder, filled below
        pages_id = add(b"")
        f1 = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>")
        f2 = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>")
        kids = []
        for p in self.pages:
            data = zlib.compress(b"\n".join(p.ops), 9)
            content = add(b"<< /Length %d /Filter /FlateDecode >>\nstream\n" % len(data) + data + b"\nendstream")
            kids.append(add(
                f"<< /Type /Page /Parent {pages_id} 0 R /MediaBox [0 0 {p.w:.2f} {p.h:.2f}] "
                f"/Resources << /Font << /F1 {f1} 0 R /F2 {f2} 0 R >> >> /Contents {content} 0 R >>".encode()))
        objs[catalog - 1] = f"<< /Type /Catalog /Pages {pages_id} 0 R >>".encode()
        objs[pages_id - 1] = (f"<< /Type /Pages /Count {len(kids)} /Kids [" + " ".join(f"{k} 0 R" for k in kids) + "] >>").encode()
        info = add(b"<< /Title (" + _enc(f"{self.title} - {self.part_label} (SAMPLE)") + b") /Producer (" + _enc(producer)
                   + b") /Subject (" + _enc(BANNER) + b") >>")
        out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
        offsets = []
        for n, body in enumerate(objs, 1):
            offsets.append(len(out))
            out += f"{n} 0 obj\n".encode() + body + b"\nendobj\n"
        xref = len(out)
        out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
        out += b"".join(f"{o:010d} 00000 n \n".encode() for o in offsets)
        out += f"trailer\n<< /Size {len(objs) + 1} /Root {catalog} 0 R /Info {info} 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
        return bytes(out)
