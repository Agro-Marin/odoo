from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from odoo.libs.documents import (
    BARCODES,
    IMAGES,
    TEXT,
    TEXT_MAX_CHARS,
    BaseReader,
    register_reader,
)

_logger = logging.getLogger(__name__)

PAGE_BREAK = "\n--PAGE--\n"

RASTER_DPI = 200
RASTER_FALLBACK_DPI = (150, 110, 72)
RASTER_MAX_BYTES = 20 * 1024 * 1024
RASTER_MAX_PAGES = 1

OCR_MIN_CHARS = 8

PDF = frozenset({"application/pdf"})
IMAGE_MIMETYPES = frozenset(
    {"image/png", "image/jpeg", "image/jpg", "image/webp", "image/gif", "image/bmp"}
)
XML_MIMETYPES = frozenset({"application/xml", "text/xml"})
PAGED = PDF | IMAGE_MIMETYPES


_TEXT_READERS: list[Callable[[bytes], str]] = []
_BARCODE_READERS: list[Callable[[bytes], list[str]]] = []


def register_text_reader(reader: Callable[[bytes], str]) -> None:
    _TEXT_READERS.append(reader)


def known_text_readers() -> tuple[str, ...]:
    return tuple(getattr(r, "__name__", repr(r)) for r in _TEXT_READERS)


def register_barcode_reader(reader: Callable[[bytes], list[str]]) -> None:
    _BARCODE_READERS.append(reader)


def known_barcode_readers() -> tuple[str, ...]:
    return tuple(getattr(r, "__name__", repr(r)) for r in _BARCODE_READERS)


def page_count(document: Any) -> int:
    if document.mimetype not in PDF:
        return 1 if document.mimetype in IMAGE_MIMETYPES else 0
    try:
        import pymupdf

        with pymupdf.open(stream=document.data, filetype="pdf") as doc:
            return doc.page_count
    except Exception as e:
        _logger.debug("Could not count pages of %r: %s", document.name, e)
        return 0


def _clamp(text: str, name: str) -> str:
    if len(text) <= TEXT_MAX_CHARS:
        return text
    _logger.warning(
        "%r yields %d characters of text; using the first %d and dropping %d",
        name,
        len(text),
        TEXT_MAX_CHARS,
        len(text) - TEXT_MAX_CHARS,
    )
    return text[:TEXT_MAX_CHARS]


def _render(page, name: str) -> bytes:
    dpi = RASTER_DPI
    png = page.get_pixmap(dpi=dpi).tobytes("png")
    for lower in RASTER_FALLBACK_DPI:
        if len(png) <= RASTER_MAX_BYTES:
            break
        _logger.info(
            "%r rendered to %.1f MB at %d dpi, over budget; retrying at %d",
            name,
            len(png) / (1024 * 1024),
            dpi,
            lower,
        )
        dpi = lower
        png = page.get_pixmap(dpi=dpi).tobytes("png")
    return png


def _ocr_text(document: Any) -> str:
    if not document.options.get("allow_ocr") or not _TEXT_READERS:
        return ""
    pages = document.images
    if not pages:
        return ""
    for reader in _TEXT_READERS:
        try:
            text = PAGE_BREAK.join(reader(page) for page in pages).strip()
        except Exception as e:
            _logger.warning("OCR reader %r failed on %r: %s", reader, document.name, e)
            continue
        if text:
            _logger.info(
                "%r had no text of its own; %d characters were read from its pages",
                document.name,
                len(text),
            )
            return text
    return ""


class _PdfText(BaseReader):
    name = "pdf_text"
    mimetypes = PDF
    yields = (TEXT,)

    def read(self, document):
        text = ""
        try:
            import pymupdf

            with pymupdf.open(stream=document.data, filetype="pdf") as doc:
                text = PAGE_BREAK.join(page.get_text() for page in doc).strip()
        except Exception as e:
            _logger.debug("Could not read the text layer of %r: %s", document.name, e)
        if len(text) < OCR_MIN_CHARS:
            text = _ocr_text(document)
        return _clamp(text, document.name)


class _ImageText(BaseReader):
    name = "image_text"
    mimetypes = IMAGE_MIMETYPES
    yields = (TEXT,)

    def read(self, document):
        return _clamp(_ocr_text(document), document.name)


class _XmlText(BaseReader):
    name = "xml_text"
    mimetypes = XML_MIMETYPES
    yields = (TEXT,)

    def read(self, document):
        tree = document.tree
        if tree is None:
            return ""
        return _clamp(
            "\n".join(t.strip() for t in tree.itertext() if t.strip()), document.name
        )


class _Pages(BaseReader):
    name = "pages"
    mimetypes = PAGED
    yields = (IMAGES,)

    def provides(self, document):
        return document.mimetype in PAGED

    def read(self, document):
        if document.mimetype in IMAGE_MIMETYPES:
            return [document.data]
        try:
            import pymupdf

            with pymupdf.open(stream=document.data, filetype="pdf") as doc:
                if not doc.page_count:
                    return []
                if doc.page_count > RASTER_MAX_PAGES:
                    _logger.warning(
                        "%r has %d pages; rendering the first %d. Pages beyond "
                        "that are not extracted from",
                        document.name,
                        doc.page_count,
                        RASTER_MAX_PAGES,
                    )
                return [
                    _render(doc[n], document.name)
                    for n in range(min(doc.page_count, RASTER_MAX_PAGES))
                ]
        except Exception as e:
            _logger.warning("Could not render %r: %s", document.name, e)
            return []


class _Barcodes(BaseReader):
    name = "barcodes"
    mimetypes = PAGED
    yields = (BARCODES,)

    def read(self, document):
        if not _BARCODE_READERS:
            return []
        pages = document.images
        if not pages:
            return []
        found: list[str] = []
        for reader in _BARCODE_READERS:
            for page in pages:
                try:
                    found.extend(reader(page))
                except Exception as e:
                    _logger.warning(
                        "Barcode reader %r failed on %r: %s", reader, document.name, e
                    )
        return list(dict.fromkeys(found))


register_reader(_PdfText())
register_reader(_ImageText())
register_reader(_XmlText())
register_reader(_Pages())
register_reader(_Barcodes())
