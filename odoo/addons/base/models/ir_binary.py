import logging
import pathlib
from datetime import UTC, datetime
from mimetypes import guess_extension
from typing import Any

import werkzeug.http

from odoo import models
from odoo.exceptions import MissingError, UserError
from odoo.http import Stream, request
from odoo.libs.filesystem import (
    MIMETYPE_HEAD_SIZE,
    get_extension,
    guess_mimetype,
)
from odoo.tools import file_open, replace_exceptions
from odoo.tools.image import image_guess_size_from_field_name, image_process
from odoo.tools.misc import verify_limited_field_access_token

DEFAULT_PLACEHOLDER_PATH = "web/static/img/placeholder.png"
_logger = logging.getLogger(__name__)


class IrBinary(models.AbstractModel):
    _name = "ir.binary"
    _description = "File streaming helper model for controllers"

    def _get_record(
        self,
        xmlid: str | None = None,
        res_model: str = "ir.attachment",
        res_id: int | None = None,
        access_token: str | None = None,
        field_name: str | None = None,
    ) -> Any:
        record = None
        if xmlid:
            record = self.env.ref(xmlid, False)
        elif res_id is not None and res_model in self.env:
            record = self.env[res_model].browse(res_id).exists()
        if not record:
            raise MissingError(
                f"No record found for xmlid={xmlid}, res_model={res_model}, id={res_id}"
            )
        if access_token and verify_limited_field_access_token(
            record, field_name, access_token, scope="binary"
        ):
            return record.sudo()
        if record._can_return_content(field_name, access_token):
            return record.sudo()
        record.check_access("read")
        return record

    def _record_to_stream(self, record: Any, field_name: str) -> Stream:
        if record._name == "ir.attachment" and field_name in (
            "raw",
            "datas",
            "db_datas",
        ):
            return record._to_http_stream()

        field = record._fields[field_name]
        record._check_field_access(field, "read")

        if field.attachment:
            field_attachment = (
                self.env["ir.attachment"]
                .sudo()
                .search(
                    domain=[
                        ("res_model", "=", record._name),
                        ("res_id", "=", record.id),
                        ("res_field", "=", field_name),
                    ],
                    limit=1,
                )
            )
            if not field_attachment:
                raise MissingError(self.env._("The related attachment does not exist."))
            return field_attachment._to_http_stream()

        return Stream.from_binary_field(record, field_name)

    def _get_stream_from_record(
        self,
        record: Any,
        field_name: str = "raw",
        filename: str | None = None,
        filename_field: str = "name",
        mimetype: str | None = None,
        default_mimetype: str = "application/octet-stream",
    ) -> Stream:
        with replace_exceptions(
            ValueError,
            by=UserError(f"Expected singleton: {record}"),
        ):
            record.ensure_one()

        try:
            field = record._fields[field_name]
        except KeyError:
            raise UserError(f"Record has no field {field_name!r}.") from None
        if field.type != "binary":
            raise UserError(
                f"Field {field!r} is type {field.type!r} but "
                f"it is only possible to stream Binary or Image fields."
            )

        stream = self._record_to_stream(record, field_name)

        if stream.type in ("data", "path"):
            if mimetype:
                stream.mimetype = mimetype
            elif not stream.mimetype:
                if stream.type == "data":
                    head = stream.data[:MIMETYPE_HEAD_SIZE]
                else:
                    with pathlib.Path(stream.path).open("rb") as file:
                        head = file.read(MIMETYPE_HEAD_SIZE)
                stream.mimetype = guess_mimetype(head, default=default_mimetype)

            if filename:
                stream.download_name = filename
            elif filename_field in record:
                name_field = record._fields[filename_field]
                if "name" in filename_field or record.sudo(False)._has_field_access(
                    name_field, "read"
                ):
                    stream.download_name = record[filename_field]
            if not stream.download_name:
                stream.download_name = f"{record._table}-{record.id}-{field_name}"

            stream.download_name = stream.download_name.replace("\n", "_").replace(
                "\r", "_"
            )
            ext = get_extension(stream.download_name) or ""
            stream.download_name = stream.download_name.removesuffix(ext)[:100] + ext
            if (
                not get_extension(stream.download_name)
                and stream.mimetype != "application/octet-stream"
            ):
                stream.download_name += guess_extension(stream.mimetype) or ""

        return stream

    def _get_stream_image_from_record(
        self,
        record: Any,
        field_name: str = "raw",
        filename: str | None = None,
        filename_field: str = "name",
        mimetype: str | None = None,
        default_mimetype: str = "image/png",
        placeholder: str | None = None,
        width: int = 0,
        height: int = 0,
        crop: bool = False,
        quality: int = 0,
    ) -> Stream:
        stream = None
        try:
            stream = self._get_stream_from_record(
                record,
                field_name,
                filename,
                filename_field,
                mimetype,
                default_mimetype,
            )
        except (UserError, MissingError) as exc:
            if request and request.params.get("download"):
                raise
            _logger.debug(
                "Falling back to the image placeholder for %s.%s: %s",
                record._name,
                field_name,
                exc,
            )

        if not stream or stream.size == 0:
            if not placeholder:
                placeholder = record._get_placeholder_filename(field_name)
            stream = self._get_stream_placeholder(placeholder)

        if stream.type == "url":
            return stream
        if not stream.mimetype.startswith("image/"):
            stream.mimetype = "application/octet-stream"

        if (width, height) == (0, 0):
            width, height = image_guess_size_from_field_name(field_name)

        if isinstance(stream.etag, str):
            stream.etag += f"-{width}x{height}-crop={crop}-quality={quality}"

        modified = True
        if request:
            if isinstance(stream.last_modified, (int, float)):
                stream.last_modified = datetime.fromtimestamp(
                    stream.last_modified, tz=UTC
                )
            modified = werkzeug.http.is_resource_modified(
                request.httprequest.environ,
                etag=stream.etag if isinstance(stream.etag, str) else None,
                last_modified=stream.last_modified,
            )

        if modified and (width or height or crop):
            if stream.type == "path":
                data = pathlib.Path(stream.path).read_bytes()
                stream.type = "data"
                stream.path = None
                stream.data = data
            stream.data = image_process(
                stream.data,
                size=(width, height),
                crop=crop,
                quality=quality,
            )
            stream.size = len(stream.data)

        return stream

    def _get_stream_placeholder(self, path: str | None = None) -> Stream:
        if not path:
            path = DEFAULT_PLACEHOLDER_PATH
        return Stream.from_path(path, filter_ext=(".png", ".jpg"))

    def _get_placeholder_bytes(self, path: str | bool = False) -> bytes:
        if not path:
            path = DEFAULT_PLACEHOLDER_PATH
        with file_open(path, "rb", filter_ext=(".png", ".jpg")) as file:
            return file.read()
