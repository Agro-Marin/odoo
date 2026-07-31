from os.path import splitext
from typing import Any

from odoo import models


class IrBinary(models.AbstractModel):
    """Binary streaming helper aware of documents records."""

    _inherit = "ir.binary"

    def _record_to_stream(self, record: models.Model, field_name: str) -> Any:
        # `raw`/`datas` only: those are the two content aliases
        # `documents.document` actually declares. `db_datas` was listed too, but
        # a document has no such field -- `_get_stream_from` resolves
        # `record._fields[field_name]` before calling this, so that name never
        # arrives here, it raises there. Naming it suggested a document can
        # stream its attachment's raw storage column, which it cannot.
        if record._name == "documents.document" and field_name in ("raw", "datas"):
            # Read access to document give implicit read access to the attachment
            return super()._record_to_stream(record.attachment_id.sudo(), field_name)

        return super()._record_to_stream(record, field_name)

    def _get_stream_from(
        self,
        record: models.Model,
        field_name: str = "raw",
        filename: str | None = None,
        filename_field: str = "name",
        mimetype: str | None = None,
        default_mimetype: str = "application/octet-stream",
    ) -> Any:
        # skip magic detection of the file extension when it is provided
        if (
            record._name == "documents.document"
            and filename is None
            and record.file_extension
        ):
            # record.name is a document display name, not a filesystem path, so
            # Path.stem/.suffix (which split on os.sep) would be incorrect here.
            name, extension = splitext(record.name)  # noqa: PTH122
            if extension == f".{record.file_extension}":
                filename = record.name
            else:
                filename = f"{name}.{record.file_extension}"
        if (
            record._name in ("documents.document", "ir.attachment")
            and record.mimetype == "application/documents-email"
        ):
            mimetype = "text/plain"  # changing the mimetype to render the document as plain text in the browser
        return super()._get_stream_from(
            record, field_name, filename, filename_field, mimetype, default_mimetype
        )
