from __future__ import annotations

import logging
from functools import cache

from rapidocr import RapidOCR

from odoo.libs.documents import EXPENSIVE, TEXT, BaseReader, register_reader

from odoo.addons.extract.tools import PAGE_BREAK, PAGED

_logger = logging.getLogger(__name__)


@cache
def _get_engine() -> RapidOCR:
    """Built once and kept: construction loads the PP-OCR weights off disk."""
    return RapidOCR()


def read_page(image: bytes) -> str:
    return "\n".join(_get_engine()(image).txts or ())


class OcrText(BaseReader):
    """The text a document has no characters for, recognised off its pages.

    Registered at `EXPENSIVE`, which is the whole of how it stays off the
    common path. Two things follow from the cost alone, and neither is written
    here: a document is derived only up to the ceiling its caller set, so
    recognition waits to be asked for; and a costlier reader runs only where
    every cheaper one answered nothing, so a PDF carrying a text layer never
    renders a page and one carrying none does.
    """

    name = "rapidocr_text"
    mimetypes = PAGED
    yields = (TEXT,)
    cost = EXPENSIVE

    def read(self, document):
        pages = document.images
        if not pages:
            return ""
        text = PAGE_BREAK.join(read_page(page) for page in pages).strip()
        if text:
            _logger.info(
                "%r had no text of its own; %d characters were read from its pages",
                document.name,
                len(text),
            )
        return text


register_reader(OcrText())
