"""The framework's own consumer: an attachment can be read.

The most general record that carries a document, and therefore the honest first
consumer of the mixin -- a model whose whole content is the document, with no
business fields to fill and nothing to predict. If the mixin needs anything an
attachment cannot provide, the mixin is wrong.

An attachment has no idea what kind of document it holds, so unlike a vendor
bill it names its type per record rather than per model. The selection comes
from the schema registry, so a module that registers a document type gets it
here without touching this file.
"""

from odoo import api, fields, models

from ..tools.schema import known_schemas
from ..tools.source import DocumentSource


class IrAttachment(models.Model):
    _name = "ir.attachment"
    _inherit = ["ir.attachment", "document.extract.mixin"]

    extract_document_type = fields.Selection(
        selection="_selection_extract_document_type",
        copy=False,
        help="Which kind of document this is. Determines the fields an "
        "extraction is expected to produce.",
    )

    @api.model
    def _selection_extract_document_type(self) -> list[tuple[str, str]]:
        return [(name, name.replace("_", " ").title()) for name in known_schemas()]

    def _get_extract_document_type(self) -> str:
        return self.extract_document_type or ""

    def _get_extract_source(self) -> DocumentSource | None:
        """An attachment is its own document; there is nothing to look up."""
        self.ensure_one()
        if not self.raw:
            return None
        return DocumentSource.of(self)
