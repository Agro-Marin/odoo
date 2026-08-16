"""One document, several representations, each derived at most once.

Every extraction strategy needs the document in some shape: a regex needs
text, a vision model needs pixels, a CFDI parser needs a tree. Left to
themselves, strategies each derive their own shape from the raw bytes, and
the derivations multiply -- a utility bill in this workspace was measured
being opened and text-extracted twice in one dispatch, once by the code that
identified its provider and once by the parser that ran next.

``DocumentSource`` is where that stops. It holds the bytes, derives each
representation on first access, keeps it, and hands the same object to every
strategy. A strategy never sees bytes and never chooses a library.

Deliberately a plain class rather than an Odoo model: it has no table, no
records and no ``_inherit`` chain, and the framework's own registries
(``schema``, ``extractors``) are plain Python for the same reason. Format
support is extended by registering a reader, not by inheriting a model.

A scan can be given text
------------------------
``text`` falls back to a registered OCR reader when a document has pages but no
characters. That is deliberately here and not in a strategy: OCR does not
extract fields, it makes text out of pixels, which is what this class is for.
Putting it here means every strategy that needs text -- a provider's regex
template, a language model, anything registered later -- starts working on
scanned documents without knowing OCR happened.

It is opt-in per document, because it is the one derivation that costs real
time. A caller that cannot afford it, which is any synchronous posting path,
leaves ``allow_ocr`` alone and sees a scan as a document with no text. A queued
caller sets it and pays.
"""

from __future__ import annotations

import base64
import json
import logging
from collections.abc import Callable
from typing import Any

_logger = logging.getLogger(__name__)

PDF_MAGIC = b"%PDF-"
PAGE_BREAK = "\n--PAGE--\n"

TEXT_MAX_CHARS = 60_000
RASTER_DPI = 200
RASTER_FALLBACK_DPI = (150, 110, 72)
RASTER_MAX_BYTES = 20 * 1024 * 1024
RASTER_MAX_PAGES = 1

OCR_MIN_CHARS = 8

TEXT = "text"
IMAGES = "images"
TREE = "tree"
DATA = "data"
BARCODES = "barcodes"

REPRESENTATIONS = (TEXT, IMAGES, TREE, DATA, BARCODES)

_IMAGE_MIMETYPES = frozenset(
    {"image/png", "image/jpeg", "image/jpg", "image/webp", "image/gif", "image/bmp"}
)
_XML_MIMETYPES = frozenset({"application/xml", "text/xml"})
_JSON_MIMETYPES = frozenset({"application/json", "text/json"})


# OCR readers, in the order they are tried. A reader takes one page's image
# bytes and returns its text. Registered by whichever module ships an engine, so
# the framework depends on none of them.
_TEXT_READERS: list[Callable[[bytes], str]] = []


def register_text_reader(reader: Callable[[bytes], str]) -> None:
    """Offer an OCR engine to every document that has pages but no text."""
    _TEXT_READERS.append(reader)


def known_text_readers() -> tuple[str, ...]:
    return tuple(getattr(r, "__name__", repr(r)) for r in _TEXT_READERS)


_BARCODE_READERS: list[Callable[[bytes], list[str]]] = []


def register_barcode_reader(reader: Callable[[bytes], list[str]]) -> None:
    _BARCODE_READERS.append(reader)


def known_barcode_readers() -> tuple[str, ...]:
    return tuple(getattr(r, "__name__", repr(r)) for r in _BARCODE_READERS)


class DocumentSource:
    """A document and the representations that can be derived from it."""

    def __init__(
        self,
        data: bytes,
        mimetype: str = "",
        name: str = "",
        allow_ocr: bool = False,
    ) -> None:
        if not data:
            raise ValueError("A document source needs data.")
        self.data: bytes = data
        self.name: str = name
        self.mimetype: str = (mimetype or self._sniff_mimetype()).lower()
        self.allow_ocr: bool = allow_ocr
        self._derived: dict[str, Any] = {}

    # -- construction ------------------------------------------------

    @classmethod
    def of(cls, attachment) -> DocumentSource:
        """Build a source from an ``ir.attachment`` record."""
        attachment.ensure_one()
        return cls(attachment.raw, attachment.mimetype or "", attachment.name or "")

    @classmethod
    def of_bytes(
        cls, data: bytes | str, mimetype: str = "", name: str = ""
    ) -> DocumentSource:
        """Build a source from raw or base64 bytes."""
        if isinstance(data, str):
            raw = data.split(",", 1)[1] if data.startswith("data:") else data
            data = base64.b64decode(raw)
        return cls(data, mimetype, name)

    def _sniff_mimetype(self) -> str:
        head = self.data[:16]
        if head.startswith(PDF_MAGIC):
            return "application/pdf"
        if head.startswith(b"\x89PNG\r\n\x1a\n"):
            return "image/png"
        if head.startswith(b"\xff\xd8\xff"):
            return "image/jpeg"
        if head[:6] in (b"GIF87a", b"GIF89a"):
            return "image/gif"
        if head.startswith(b"BM"):
            return "image/bmp"
        if head.startswith(b"RIFF") and b"WEBP" in self.data[:16]:
            return "image/webp"
        stripped = self.data.lstrip()[:1]
        if stripped == b"<":
            return "application/xml"
        if stripped in (b"{", b"["):
            return "application/json"
        return "application/octet-stream"

    # -- representations ---------------------------------------------

    @property
    def is_pdf(self) -> bool:
        return self.mimetype == "application/pdf" or self.data.startswith(PDF_MAGIC)

    @property
    def is_image(self) -> bool:
        return self.mimetype in _IMAGE_MIMETYPES

    @property
    def text(self) -> str:
        """The document as text, empty when it has none to give."""
        return self._derive(TEXT, self._read_text)

    @property
    def images(self) -> list[bytes]:
        """The document as raster images, one per page for a PDF."""
        return self._derive(IMAGES, self._read_images)

    @property
    def tree(self):
        """The document as a parsed XML tree, or None."""
        return self._derive(TREE, self._read_tree)

    @property
    def data_dict(self) -> dict | list | None:
        """The document as decoded JSON, or None."""
        return self._derive(DATA, self._read_data)

    @property
    def barcodes(self) -> list[str]:
        return self._derive(BARCODES, self._read_barcodes)

    @property
    def page_count(self) -> int:
        if not self.is_pdf:
            return 1 if self.is_image else 0
        try:
            import pymupdf

            with pymupdf.open(stream=self.data, filetype="pdf") as doc:
                return doc.page_count
        except Exception as e:
            _logger.debug("Could not count pages of %r: %s", self.name, e)
            return 0

    def provides(self, representation: str) -> bool:
        """Whether this document can supply a representation, non-empty.

        The gate an extractor's ``needs`` is checked against, so that an XML
        strategy is never handed a scanned photograph. Cheap for everything
        but ``images``, which is answered from the mimetype rather than by
        rendering a page to find out.
        """
        if representation == IMAGES:
            return self.is_pdf or self.is_image
        if representation not in REPRESENTATIONS:
            raise ValueError(f"Unknown representation {representation!r}")
        return bool(
            getattr(self, {DATA: "data_dict"}.get(representation, representation))
        )

    def _derive(self, key: str, reader: Callable[[], Any]) -> Any:
        if key not in self._derived:
            self._derived[key] = reader()
        return self._derived[key]

    # -- readers ------------------------------------------------------

    def _read_text(self) -> str:
        if self.is_pdf:
            text = self._read_pdf_text()
            if len(text) < OCR_MIN_CHARS:
                text = self._read_ocr_text()
            return _clamp(text, self.name)
        if self.is_image:
            return _clamp(self._read_ocr_text(), self.name)
        if self.mimetype in _XML_MIMETYPES:
            tree = self.tree
            return _clamp(
                "\n".join(t.strip() for t in tree.itertext() if t.strip())
                if tree is not None
                else "",
                self.name,
            )
        if self.mimetype.startswith("text/") or self.mimetype in _JSON_MIMETYPES:
            return _clamp(self.data.decode("utf-8", errors="replace"), self.name)
        return ""

    def _read_pdf_text(self) -> str:
        try:
            import pymupdf

            with pymupdf.open(stream=self.data, filetype="pdf") as doc:
                return PAGE_BREAK.join(page.get_text() for page in doc).strip()
        except Exception as e:
            _logger.debug("Could not read the text layer of %r: %s", self.name, e)
            return ""

    def _read_images(self) -> list[bytes]:
        if self.is_image:
            return [self.data]
        if not self.is_pdf:
            return []
        try:
            import pymupdf

            with pymupdf.open(stream=self.data, filetype="pdf") as doc:
                if not doc.page_count:
                    return []
                if doc.page_count > RASTER_MAX_PAGES:
                    _logger.warning(
                        "%r has %d pages; rendering the first %d. Pages beyond "
                        "that are not extracted from",
                        self.name,
                        doc.page_count,
                        RASTER_MAX_PAGES,
                    )
                return [
                    _render(doc[n], self.name)
                    for n in range(min(doc.page_count, RASTER_MAX_PAGES))
                ]
        except Exception as e:
            _logger.warning("Could not render %r: %s", self.name, e)
            return []

    def _read_tree(self):
        if self.mimetype not in _XML_MIMETYPES and not self.data.lstrip().startswith(
            b"<"
        ):
            return None
        try:
            from lxml import etree

            parser = etree.XMLParser(resolve_entities=False, no_network=True)
            return etree.fromstring(self.data, parser=parser)
        except Exception as e:
            _logger.debug("Could not parse %r as XML: %s", self.name, e)
            return None

    def _read_data(self):
        if self.mimetype not in _JSON_MIMETYPES and self.data.lstrip()[:1] not in (
            b"{",
            b"[",
        ):
            return None
        try:
            return json.loads(self.data.decode("utf-8"))
        except Exception as e:
            _logger.debug("Could not parse %r as JSON: %s", self.name, e)
            return None

    def _read_barcodes(self) -> list[str]:
        if not _BARCODE_READERS:
            return []
        pages = self.images
        if not pages:
            return []
        found: list[str] = []
        for reader in _BARCODE_READERS:
            for page in pages:
                try:
                    found.extend(reader(page))
                except Exception as e:
                    _logger.warning(
                        "Barcode reader %r failed on %r: %s", reader, self.name, e
                    )
        return list(dict.fromkeys(found))

    def _read_ocr_text(self) -> str:
        """Make text out of the pages, if anyone can and the caller allows it."""
        if not self.allow_ocr or not _TEXT_READERS:
            return ""
        pages = self.images
        if not pages:
            return ""
        for reader in _TEXT_READERS:
            try:
                text = PAGE_BREAK.join(reader(page) for page in pages).strip()
            except Exception as e:
                _logger.warning("OCR reader %r failed on %r: %s", reader, self.name, e)
                continue
            if text:
                _logger.info(
                    "%r had no text of its own; %d characters were read from its pages",
                    self.name,
                    len(text),
                )
                return text
        return ""

    def __repr__(self) -> str:
        return f"<DocumentSource {self.name or '?'} {self.mimetype} {len(self.data)}B>"


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
    """Render one page, stepping the resolution down to fit the byte budget.

    A photographic scan renders to several times the size of its own PDF, so a
    fixed resolution either wastes bandwidth on line art or overruns the budget
    on a photograph -- and overrunning it produces an error about a size this
    code chose, not one the caller supplied.
    """
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
