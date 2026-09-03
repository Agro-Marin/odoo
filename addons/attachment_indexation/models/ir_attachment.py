import importlib.util
import io
import logging

from odoo import api, models
from odoo.libs.lru import LRU

from ..tools.readers import (
    clean_text_content,
    read_docx,
    read_opendoc,
    read_pptx,
    read_xlsx,
)

_logger = logging.getLogger(__name__)

if not (
    importlib.util.find_spec("pdfminer")
    and importlib.util.find_spec("pdfminer.high_level")
):
    _logger.warning(
        "Attachment indexation of PDF documents is unavailable because the 'pdfminer.six' Python library cannot be found on the system. "
        "You may install it from https://pypi.org/project/pdfminer.six/ (e.g. `pip3 install pdfminer.six`)"
    )

FTYPES = ["docx", "pptx", "xlsx", "opendoc", "pdf"]

# Direct mimetype -> ftype dispatch, so a recognized mimetype tries its own
# extractor first instead of always walking FTYPES in a fixed order (docx,
# pptx, xlsx... zip-based extractors all pay a wasted parse attempt on every
# non-docx zip before reaching their real one).
_MIMETYPE_TO_FTYPE = {
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": "pptx",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "xlsx",
    "application/vnd.oasis.opendocument.text": "opendoc",
    "application/vnd.oasis.opendocument.spreadsheet": "opendoc",
    "application/vnd.oasis.opendocument.presentation": "opendoc",
    "application/vnd.oasis.opendocument.graphics": "opendoc",
    "application/pdf": "pdf",
}


index_content_cache = LRU(1)


class IrAttachment(models.Model):
    _inherit = "ir.attachment"

    def _index_docx(self, bin_data):
        """Index Microsoft .docx documents"""
        return read_docx(bin_data, self._INDEX_MAX_BYTES)

    def _index_pptx(self, bin_data):
        """Index Microsoft .pptx documents"""
        return read_pptx(bin_data, self._INDEX_MAX_BYTES)

    def _index_xlsx(self, bin_data):
        """Index Microsoft .xlsx documents"""
        return read_xlsx(bin_data, self._INDEX_MAX_BYTES)

    def _index_opendoc(self, bin_data):
        """Index OpenDocument documents (.odt, .ods...)"""
        return read_opendoc(bin_data, self._INDEX_MAX_BYTES)

    def _index_pdf(self, bin_data):
        """Index PDF documents"""
        if not bin_data.startswith(b"%PDF-"):
            return ""
        try:
            if not importlib.util.find_spec("pdfminer.high_level"):
                return ""
            from pdfminer.converter import TextConverter
            from pdfminer.layout import LAParams
            from pdfminer.pdfinterp import (
                PDFPageInterpreter,
                PDFResourceManager,
            )
            from pdfminer.pdfpage import PDFPage

            logging.getLogger("pdfminer").setLevel(logging.CRITICAL)
        except ImportError:
            # warned already during init of module
            return ""
        f = io.BytesIO(bin_data)
        try:
            resource_manager = PDFResourceManager()
            # Setting boxes_flow triggers the _group_textboxes function,
            # used to group textboxes by distance, which helps sort them
            # better. In our case, we don't need to sort them this way,
            # so we can disable the feature to reduce the memory footprint
            # of the library and avoid memory issues on most PDF files.
            laparams = LAParams(detect_vertical=True, boxes_flow=None)

            with (
                io.StringIO() as content,
                TextConverter(resource_manager, content, laparams=laparams) as device,
            ):
                interpreter = PDFPageInterpreter(resource_manager, device)
                for page in PDFPage.get_pages(f):
                    interpreter.process_page(page)

                buf = content.getvalue()
            return clean_text_content(buf)
        except Exception:
            _logger.debug(
                "attachment_indexation: failed to index pdf content", exc_info=True
            )
            return ""

    @api.model
    def _index(self, bin_data, mimetype, checksum=None):
        if checksum:
            cached_content = index_content_cache.get(checksum)
            if cached_content:
                return cached_content
        res = False
        preferred = _MIMETYPE_TO_FTYPE.get(mimetype)
        ftypes = [preferred] if preferred else []
        ftypes += [ftype for ftype in FTYPES if ftype != preferred]
        for ftype in ftypes:
            buf = getattr(self, "_index_%s" % ftype)(bin_data)
            if buf:
                res = buf.replace("\x00", "")
                break

        res = res or super()._index(bin_data, mimetype, checksum=checksum)
        if checksum:
            index_content_cache[checksum] = res
        return res

    # Mimetypes whose extractors (see FTYPES) parse the WHOLE file: zip-based
    # office containers and PDF. The streaming create path must read these back
    # in full instead of the text-only prefix the base hook returns, otherwise a
    # streamed document larger than _INDEX_MAX_BYTES is parsed from a truncated
    # prefix and silently loses its index. This matches the buffered create
    # path, which already hands _index the full content.
    _INDEXED_DOC_MIMETYPES = frozenset(
        {
            "application/pdf",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "application/vnd.openxmlformats-officedocument.presentationml.presentation",
            "application/vnd.oasis.opendocument.text",
            "application/vnd.oasis.opendocument.spreadsheet",
            "application/vnd.oasis.opendocument.presentation",
            "application/vnd.oasis.opendocument.graphics",
        }
    )

    @api.model
    def _get_index_read_size(self, mimetype):
        # Read whole documents this backend parses; defer text/others to base
        # (bounded text prefix / skip), so unindexable media still streams flat.
        if mimetype in self._INDEXED_DOC_MIMETYPES:
            return None
        return super()._get_index_read_size(mimetype)

    def copy(self, default=None):
        # LRU(1) can only ever retain the last entry written to it: pre-warming
        # it one checksum at a time for a multi-record `self` evicts every
        # entry but the last before super().copy() ever reads it back. Grow
        # the cache to fit this batch (never shrink it back down) so every
        # checksum survives until it's consumed.
        index_content_cache.count = max(index_content_cache.count, len(self))
        for attachment in self:
            index_content_cache[attachment.checksum] = attachment.index_content
        return super().copy(default=default)
