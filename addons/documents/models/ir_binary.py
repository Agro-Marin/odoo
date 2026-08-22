from os.path import splitext
from typing import Any

from odoo import models


class IrBinary(models.AbstractModel):

    _inherit = "ir.binary"

    def _record_to_stream(self, record: models.Model, field_name: str) -> Any:
        if record._name == "documents.document" and field_name in ("raw", "datas"):
            return super()._record_to_stream(record.attachment_id.sudo(), field_name)

        return super()._record_to_stream(record, field_name)

    def _get_stream_from_record(
        self,
        record: models.Model,
        field_name: str = "raw",
        filename: str | None = None,
        filename_field: str = "name",
        mimetype: str | None = None,
        default_mimetype: str = "application/octet-stream",
    ) -> Any:
        if (
            record._name == "documents.document"
            and filename is None
            and record.file_extension
        ):
            name, extension = splitext(record.name)  # noqa: PTH122
            if extension == f".{record.file_extension}":
                filename = record.name
            else:
                filename = f"{name}.{record.file_extension}"
        if (
            record._name in ("documents.document", "ir.attachment")
            and record.mimetype == "application/documents-email"
        ):
            mimetype = "text/plain"
        return super()._get_stream_from_record(
            record, field_name, filename, filename_field, mimetype, default_mimetype
        )
