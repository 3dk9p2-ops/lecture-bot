"""Extract ALL text and candidate figures from .docx / .pptx / .pdf.

Text keeps its order; every kept picture is replaced in the text by a marker like [IMAGE img_3]
so Gemini can decide where an important figure belongs.
"""
from __future__ import annotations

import hashlib
import io
import os
import re
from dataclasses import dataclass, field
from typing import Callable, Optional

MIN_SIDE = 110          # px: skip icons / bullets
MIN_AREA = 25_000       # px^2
MAX_SIDE = 1400         # px: downscale big figures
THUMB_SIDE = 512        # px: what Gemini looks at
MAX_REPEATS = 2         # a picture that appears more often is a logo/background
MARKER = re.compile(r"\[IMAGE (img_\d+)\]")


@dataclass
class Unit:
    label: str
    text: str


@dataclass
class ImageRef:
    id: str
    mime: str
    data: bytes
    thumb: bytes
    w: int
    h: int
    hits: int = 1


class ImageStore:
    def __init__(self):
        self.items: dict[str, ImageRef] = {}
        self._by_hash: dict[str, str] = {}

    def add(self, blob: bytes) -> Optional[str]:
        """Normalize a picture; returns its id (or None if unusable / too small)."""
        try:
            from PIL import Image
            im = Image.open(io.BytesIO(blob))
            im.load()
        except Exception:
            return None
        w, h = im.size
        if min(w, h) < MIN_SIDE or w * h < MIN_AREA:
            return None
        key = hashlib.sha1(blob).hexdigest()
        if key in self._by_hash:
            self.items[self._by_hash[key]].hits += 1
            return self._by_hash[key]
        has_alpha = im.mode in ("RGBA", "LA", "P") and "transparency" in im.info or im.mode in ("RGBA", "LA")
        if has_alpha:
            bg = Image.new("RGB", im.size, "white")
            im = im.convert("RGBA")
            bg.paste(im, mask=im.split()[-1])
            im = bg
        else:
            im = im.convert("RGB")
        big = im.copy()
        big.thumbnail((MAX_SIDE, MAX_SIDE))
        out = io.BytesIO()
        big.save(out, "JPEG", quality=88)
        small = im.copy()
        small.thumbnail((THUMB_SIDE, THUMB_SIDE))
        tout = io.BytesIO()
        small.save(tout, "JPEG", quality=70)
        iid = f"img_{len(self.items) + 1}"
        self.items[iid] = ImageRef(iid, "image/jpeg", out.getvalue(), tout.getvalue(), w, h)
        self._by_hash[key] = iid
        return iid

    def drop_repeated(self, units: list[Unit]):
        """Remove logos/backgrounds (same picture on many slides/pages) and their markers."""
        bad = {i for i, r in self.items.items() if r.hits > MAX_REPEATS}
        for i in bad:
            del self.items[i]
        for u in units:
            u.text = MARKER.sub(lambda m: "" if m.group(1) in bad else m.group(0), u.text)


@dataclass
class Extracted:
    units: list[Unit]
    images: dict[str, ImageRef] = field(default_factory=dict)


def _cell_text(c) -> str:
    return " ".join(c.text.split())


def _table_to_text(rows: list[list[str]]) -> str:
    return "\n".join(" | ".join(r) for r in rows if any(x.strip() for x in r))


# ---------------------------------------------------------------- DOCX
def extract_docx(path: str, store: ImageStore) -> list[Unit]:
    from docx import Document
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    doc = Document(path)
    units: list[Unit] = []
    state = {"label": "Introduction", "lines": []}
    blip_ns = "{http://schemas.openxmlformats.org/drawingml/2006/main}blip"
    embed = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}embed"

    def flush():
        txt = "\n".join(state["lines"]).strip()
        if txt:
            units.append(Unit(state["label"], txt))
        state["lines"] = []

    def pictures(el) -> list[str]:
        out = []
        for blip in el.iter(blip_ns):
            rid = blip.get(embed)
            part = doc.part.related_parts.get(rid) if rid else None
            if part is not None:
                iid = store.add(part.blob)
                if iid:
                    out.append(f"[IMAGE {iid}]")
        return out

    for child in doc.element.body.iterchildren():
        tag = child.tag.rsplit("}", 1)[-1]
        if tag == "p":
            p = Paragraph(child, doc)
            t = p.text.strip()
            style = (p.style.name if p.style is not None else "") or ""
            if t and style.lower().startswith(("heading", "title")):
                flush()
                state["label"] = t
                state["lines"].append(f"# {t}")
            elif t and "list" in style.lower():
                state["lines"].append(f"- {t}")
            elif t:
                state["lines"].append(t)
            state["lines"].extend(pictures(child))
        elif tag == "tbl":
            tb = Table(child, doc)
            rows = []
            for r in tb.rows:
                seen, cells = set(), []
                for c in r.cells:  # merged cells repeat; dedupe by element identity
                    if id(c._tc) in seen:
                        continue
                    seen.add(id(c._tc))
                    cells.append(_cell_text(c))
                rows.append(cells)
            state["lines"].append("[TABLE]\n" + _table_to_text(rows) + "\n[/TABLE]")
            state["lines"].extend(pictures(child))
    flush()
    return units


# ---------------------------------------------------------------- PPTX
def _shape_texts(shape, out: list[str], store: ImageStore):
    if shape.shape_type == 6 and hasattr(shape, "shapes"):  # group shape
        for s in shape.shapes:
            _shape_texts(s, out, store)
        return
    if shape.shape_type == 13:  # picture
        try:
            iid = store.add(shape.image.blob)
        except Exception:  # e.g. EMF/WMF, linked pictures
            iid = None
        if iid:
            out.append(f"[IMAGE {iid}]")
        return
    if getattr(shape, "has_table", False) and shape.has_table:
        rows = [[_cell_text(c) for c in r.cells] for r in shape.table.rows]
        out.append("[TABLE]\n" + _table_to_text(rows) + "\n[/TABLE]")
        return
    if getattr(shape, "has_text_frame", False) and shape.has_text_frame:
        for para in shape.text_frame.paragraphs:
            t = para.text.strip()
            if t:
                out.append(("  " * min(para.level, 3)) + "- " + t)


def extract_pptx(path: str, store: ImageStore) -> list[Unit]:
    from pptx import Presentation

    prs = Presentation(path)
    units = []
    for i, slide in enumerate(prs.slides, 1):
        parts: list[str] = []
        title = ""
        if slide.shapes.title is not None and slide.shapes.title.has_text_frame:
            title = slide.shapes.title.text_frame.text.strip()
        for shape in slide.shapes:
            _shape_texts(shape, parts, store)
        if slide.has_notes_slide and slide.notes_slide.notes_text_frame is not None:
            notes = slide.notes_slide.notes_text_frame.text.strip()
            if notes:
                parts.append("[SPEAKER NOTES] " + notes)
        body = "\n".join(parts).strip()
        if body:
            label = f"Slide {i}" + (f": {title}" if title else "")
            units.append(Unit(label, f"=== Slide {i}: {title} ===\n{body}"))
    return units


# ---------------------------------------------------------------- PDF
def extract_pdf(path: str, store: ImageStore, ocr: Optional[Callable[[bytes], str]] = None,
                progress: Optional[Callable[[str], None]] = None) -> list[Unit]:
    import fitz

    units = []
    with fitz.open(path) as pdf:
        for i, page in enumerate(pdf, 1):
            lines, markers = [], []
            for blk in page.get_text("dict", sort=True)["blocks"]:
                if blk["type"] == 0:
                    t = "\n".join("".join(s["text"] for s in ln["spans"]) for ln in blk["lines"]).strip()
                    if t:
                        lines.append(t)
                elif blk["type"] == 1 and blk.get("image"):
                    iid = store.add(blk["image"])
                    if iid:
                        lines.append(f"[IMAGE {iid}]")
                        markers.append(iid)
            txt = "\n".join(lines)
            text_only = MARKER.sub("", txt).strip()

            if len(text_only) < 25 and ocr is not None:  # scanned page -> OCR fallback
                if progress:
                    progress(f"OCR page {i}/{len(pdf)}...")
                png = page.get_pixmap(dpi=150).tobytes("png")  # input to OCR only
                try:
                    ocr_txt = (ocr(png) or "").strip()
                    if ocr_txt:
                        for iid in markers:           # the picture is the scan itself
                            store.items.pop(iid, None)
                        txt = ocr_txt
                except Exception:
                    pass
            elif not markers:                          # vector diagram (e.g. exported from PowerPoint)
                try:
                    rects = [d["rect"] for d in page.get_drawings() if d["rect"].width > 2 and d["rect"].height > 2]
                except Exception:
                    rects = []
                if len(rects) >= 40:
                    r = rects[0]
                    for x in rects[1:]:
                        r |= x
                    r &= page.rect
                    frac = (r.width * r.height) / (page.rect.width * page.rect.height)
                    if 0.10 < frac < 0.92:
                        png = page.get_pixmap(clip=r, dpi=130).tobytes("png")
                        iid = store.add(png)
                        if iid:
                            txt += f"\n[IMAGE {iid}]"
            if txt.strip():
                units.append(Unit(f"Page {i}", f"=== Page {i} ===\n{txt}"))
    return units


def extract_any(path: str, ocr=None, progress=None) -> Extracted:
    ext = os.path.splitext(path)[1].lower()
    store = ImageStore()
    if ext == ".docx":
        units = extract_docx(path, store)
    elif ext == ".pptx":
        units = extract_pptx(path, store)
    elif ext == ".pdf":
        units = extract_pdf(path, store, ocr, progress)
    else:
        raise ValueError(f"Unsupported file type: {ext}")
    if not units:
        raise ValueError("No readable text found in the file.")
    store.drop_repeated(units)
    return Extracted(units, store.items)


def chunk_units(units: list[Unit], max_chars: int) -> list[str]:
    """Group consecutive units in order; only split a unit if it alone exceeds max_chars."""
    chunks, cur, size = [], [], 0
    for u in units:
        pieces = [u.text]
        if len(u.text) > max_chars:
            pieces, buf = [], ""
            for line in u.text.splitlines(keepends=True):
                if len(buf) + len(line) > max_chars and buf:
                    pieces.append(buf)
                    buf = ""
                buf += line
            if buf:
                pieces.append(buf)
        for p in pieces:
            if size + len(p) > max_chars and cur:
                chunks.append("\n\n".join(cur))
                cur, size = [], 0
            cur.append(p)
            size += len(p)
    if cur:
        chunks.append("\n\n".join(cur))
    return chunks
