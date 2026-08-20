import base64
import io
import logging
import typing
import zipfile
from typing import Any

from werkzeug.exceptions import NotFound, UnsupportedMediaType

from odoo import http
from odoo.exceptions import AccessError, UserError
from odoo.http import Response, content_disposition, request
from odoo.tools.misc import file_open
from odoo.tools.pdf import DependencyError, PdfReadError, extract_page

from odoo.addons.mail.controllers.thread import ThreadController
from odoo.addons.mail.controllers.utils import to_record_id, to_record_ids
from odoo.addons.mail.tools.discuss import Store, add_guest_to_context

if typing.TYPE_CHECKING:
    from odoo.addons.base.models.ir_attachment import IrAttachment

logger = logging.getLogger(__name__)

MAX_THUMBNAIL_B64_BYTES = 10 * 1024 * 1024

MAX_ZIP_ATTACHMENTS = 200

MAX_ZIP_BYTES = 512 * 1024 * 1024


class AttachmentController(ThreadController):
    def _raise_for_zip_size(self, written: int) -> None:
        if written > MAX_ZIP_BYTES:
            raise UserError(
                request.env._(
                    "These attachments are too large to download together. "
                    "Select fewer of them."
                )
            )

    def _make_zip(self, name: str, attachments: IrAttachment) -> Response:
        self._raise_for_zip_size(sum(attachments.mapped("file_size")))
        stream = io.BytesIO()
        written = 0
        with zipfile.ZipFile(stream, "w") as attachment_zip:
            for record in attachments:
                self._raise_for_zip_size(written + record.file_size)
                binary_stream = request.env["ir.binary"]._get_stream_from(record, "raw")
                if not binary_stream:
                    continue
                data = binary_stream.read()
                written += len(data)
                self._raise_for_zip_size(written)
                attachment_zip.writestr(
                    binary_stream.download_name,
                    data,
                    compress_type=zipfile.ZIP_DEFLATED,
                )

        content = stream.getvalue()
        headers = [
            ("Content-Type", "application/zip"),
            ("X-Content-Type-Options", "nosniff"),
            ("Content-Length", len(content)),
            ("Content-Disposition", content_disposition(name)),
        ]
        return request.make_response(content, headers)

    @http.route("/mail/attachment/upload", methods=["POST"], type="http", auth="public")
    @add_guest_to_context
    def mail_attachment_upload(
        self,
        ufile: Any,
        thread_id: int,
        thread_model: str,
        is_pending: bool | str = False,
        **kwargs,
    ) -> Response:
        thread = self._get_thread_with_access_for_post(
            thread_model, thread_id, **kwargs
        )
        if not thread:
            raise NotFound
        vals = {
            "res_id": thread.id,
            "res_model": thread_model,
        }
        if company := thread._mail_get_companies()[thread.id]:
            vals["company_id"] = company.id
        elif cids := request.cookies.get("cids"):
            active_company_ids = [int(cid) for cid in cids.split("-") if cid.isdigit()]
            if active_company_ids:
                user_company_id = request.env.user.company_id.id
                vals["company_id"] = (
                    user_company_id
                    if user_company_id in active_company_ids
                    else active_company_ids[0]
                )
        if is_pending and str(is_pending).lower() not in ("false", "0", ""):
            vals.update(
                {
                    "res_id": 0,
                    "res_model": "mail.compose.message",
                }
            )
        try:
            attachment = (
                request.env["ir.attachment"].sudo()._from_request_file(ufile, **vals)
            )
            attachment._post_add_create(**kwargs)
            res = {
                "data": {
                    "store_data": Store()
                    .add(
                        attachment,
                        extra_fields=request.env[
                            "ir.attachment"
                        ]._get_store_ownership_fields(),
                    )
                    .get_result(),
                    "attachment_id": attachment.id,
                }
            }
        except AccessError:
            res = {
                "error": request.env._(
                    "You are not allowed to upload an attachment here."
                )
            }
        return request.make_json_response(res)

    @http.route(
        "/mail/attachment/delete", methods=["POST"], type="jsonrpc", auth="public"
    )
    @add_guest_to_context
    def mail_attachment_delete(
        self, attachment_id: int, access_token: str | None = None
    ) -> None:
        attachment = (
            request.env["ir.attachment"].browse(to_record_id(attachment_id)).exists()
        )
        if not attachment or not attachment._has_attachments_ownership([access_token]):
            request.env.user._bus_send("ir.attachment/delete", {"id": attachment_id})
            raise NotFound
        message = (
            request.env["mail.message"]
            .sudo()
            .search([("attachment_ids", "in", attachment.ids)], limit=1)
        )
        attachment.sudo()._delete_and_notify(message)

    @http.route(["/mail/attachment/zip"], methods=["POST"], type="http", auth="public")
    @add_guest_to_context
    def mail_attachment_get_zip(self, file_ids: str, zip_name: str, **kw) -> Response:
        if not isinstance(file_ids, str):
            raise NotFound
        ids_list = to_record_ids(file_ids.split(",")) if file_ids else []
        if not ids_list or len(ids_list) > MAX_ZIP_ATTACHMENTS:
            raise NotFound
        attachments = request.env["ir.attachment"].browse(ids_list).exists()
        accessible = attachments._filtered_access("read")
        if not accessible:
            raise NotFound
        return self._make_zip(zip_name, accessible.sudo())

    @http.route(
        "/mail/attachment/pdf_first_page/<int:attachment_id>",
        auth="public",
        methods=["GET"],
        readonly=True,
        type="http",
    )
    @add_guest_to_context
    def mail_attachment_pdf_first_page(
        self, attachment_id: int, access_token: str | None = None
    ) -> Response:
        attachment = request.env["ir.attachment"].browse(attachment_id).exists()
        if not attachment or (
            not attachment.has_access("read")
            and not attachment._has_attachments_ownership([access_token])
        ):
            raise NotFound
        return self._get_pdf_first_page_response(attachment.sudo())

    @http.route(
        "/mail/attachment/update_thumbnail",
        auth="public",
        methods=["POST"],
        type="jsonrpc",
    )
    @add_guest_to_context
    def mail_attachment_update_thumbnail(
        self,
        attachment_id: int,
        thumbnail: str | None = None,
        access_token: str | None = None,
    ) -> None:
        attachment = (
            request.env["ir.attachment"].browse(to_record_id(attachment_id)).exists()
        )
        if not attachment or (
            not attachment.has_access("write")
            and not attachment._has_attachments_ownership([access_token])
        ):
            raise NotFound
        attachment_sudo = attachment.sudo()
        if attachment_sudo.mimetype != "application/pdf":
            raise UserError(request.env._("Only PDF files can have thumbnail."))
        if not thumbnail:
            with file_open("web/static/img/mimetypes/unknown.svg") as unknown_svg:
                thumbnail = base64.b64encode(unknown_svg.read().encode()).decode()
        else:
            if not isinstance(thumbnail, str):
                raise NotFound
            if len(thumbnail) > MAX_THUMBNAIL_B64_BYTES:
                raise UserError(request.env._("The thumbnail is too large."))
            try:
                base64.b64decode(thumbnail, validate=True)
            except ValueError:
                raise UserError(
                    request.env._("The thumbnail is not valid base64.")
                ) from None
        attachment_sudo.thumbnail = thumbnail
        Store(bus_channel=attachment_sudo).add(
            attachment_sudo, ["has_thumbnail"]
        ).bus_send()

    def _get_pdf_first_page_response(self, attachment: IrAttachment) -> Response:
        try:
            page_stream = extract_page(attachment, 0)
        except (PdfReadError, DependencyError, UnicodeDecodeError) as e:
            raise UnsupportedMediaType from e
        if not page_stream:
            raise UnsupportedMediaType
        content = page_stream.getvalue()
        headers = [
            ("Content-Type", "application/pdf"),
            ("X-Content-Type-Options", "nosniff"),
            ("Content-Length", len(content)),
        ]
        if attachment.name:
            headers.append(
                ("Content-Disposition", content_disposition(attachment.name))
            )
        return request.make_response(content, headers)
