from __future__ import annotations

import io
import logging
from typing import Any

from odoo.libs.documents import CHILDREN, FREE, BaseReader, Document, register_reader

_logger = logging.getLogger(__name__)


class PdfEmbeddedFiles(BaseReader):
    name = "pdf_embedded_files"
    mimetypes = frozenset({"application/pdf"})
    yields = (CHILDREN,)
    cost = FREE

    def read(self, document: Any) -> list[Document]:
        from struct import error as StructError

        from .pdf import OdooPdfFileReader, PdfReadError

        with io.BytesIO(document.data) as buffer:
            try:
                reader = OdooPdfFileReader(buffer, strict=False)
            except Exception as e:
                _logger.info("Error when reading the pdf file %r: %s", document.name, e)
                return []
            try:
                embedded = list(reader.get_attachments())
            except (NotImplementedError, StructError, PdfReadError) as e:
                _logger.warning(
                    "Unable to access the attachments of %r. Tried to decrypt "
                    "it, but %s.",
                    document.name,
                    e,
                )
                return []
        return [
            Document(content, name=filename)
            for filename, content in embedded
            if content
        ]


register_reader(PdfEmbeddedFiles())
