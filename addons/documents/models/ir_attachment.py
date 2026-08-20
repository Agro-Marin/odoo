import io
import logging
from collections import defaultdict
from typing import Any

from odoo import api, fields, models
from odoo.tools.pdf import OdooPdfFileReader, OdooPdfFileWriter

from odoo.addons.documents.tools import UserFolder

_logger = logging.getLogger(__name__)


class IrAttachment(models.Model):
    """Attachment model synchronizing linked documents."""

    _inherit = "ir.attachment"

    document_ids = fields.One2many(
        "documents.document", "attachment_id", export_string_translation=False
    )

    def _zip_detached_reader(self) -> Any:
        """Return a block generator for this content, usable without the ORM.

        Answers the one question the ZIP planner cannot resolve on its own: an
        attachment whose stream is a redirect may still be *readable* by Odoo,
        just not served by it. A storage layer that can fetch its own content
        returns ``callable(block_size) -> iterator[bytes]``, resolved here (with
        a cursor) and called later during streaming (without one) — so nothing
        it closes over may be a recordset or a cursor.

        ``None``, the default, means the bytes are genuinely unavailable and the
        entry is left out of the archive.
        """
        return None

    def get_documents_operation_add_destination(self) -> dict:
        """Return the default destination used when adding the attachment to documents."""
        self.ensure_one()
        return {
            "destination": UserFolder.MY,
            "display_name": self.env._("My Drive"),
        }

    @api.model
    def _pdf_split(
        self, new_files: list | None = None, open_files: list | None = None
    ) -> IrAttachment:
        """Create and return new pdf attachments based on existing data.

        :param new_files: the array that represents the new pdf
            structure::

                [{
                    'name': 'New File Name',
                    'new_pages': [{
                        'old_file_index': 7,
                        'old_page_number': 5,
                    }],
                }]
        :param open_files: array of open file objects.
        :returns: the new PDF attachments
        """
        vals_list = []
        pdf_from_files = [
            OdooPdfFileReader(open_file, strict=False) for open_file in open_files
        ]

        for new_file in new_files:
            output = OdooPdfFileWriter()
            used_pages_by_pdf = defaultdict(set)
            for page in new_file["new_pages"]:
                file_index = int(page["old_file_index"])
                page_index = int(page["old_page_number"]) - 1
                # Bounds-check the client-supplied indices: an out-of-range file
                # or page must be a clean 400 (the caller maps ValueError ->
                # BadRequest), not an opaque IndexError -> 500.
                if not 0 <= file_index < len(pdf_from_files):
                    raise ValueError(f"Invalid source file index {file_index}")
                input_pdf = pdf_from_files[file_index]
                if not 0 <= page_index < len(input_pdf.pages):
                    raise ValueError(f"Invalid page number {page['old_page_number']}")
                output.add_page(input_pdf.pages[page_index])
                used_pages_by_pdf[file_index].add(page_index)
                if len(used_pages_by_pdf[file_index]) != len(input_pdf.pages):
                    continue
                try:
                    for fname, fcontent in input_pdf.get_attachments():
                        output.add_attachment(name=fname, data=fcontent)
                except Exception:
                    _logger.warning(
                        "Impossible to add (all) attachments from pdf at index %i",
                        file_index,
                        exc_info=True,
                    )
            with io.BytesIO() as stream:
                output.write(stream)
                vals_list.append(
                    {
                        "name": new_file["name"] + ".pdf",
                        "raw": stream.getvalue(),
                    }
                )
        return self.create(vals_list)

    def _create_document(self, res_model: str | None, res_id: int | None) -> bool:
        """File the attachments in ``self``, all linked to one record, into Documents.

        The extension point bridge modules override to give their business model
        a Documents presence.

        The target is passed explicitly rather than read out of a create/write
        ``vals`` dict. Both callers already resolved it off the attachments
        themselves, because ``vals`` alone is routinely wrong: a link is often
        completed one key at a time (``write({"res_id": ...})`` on a row that
        already carries ``res_model``), and the dict then names only half the
        pair. Nothing but those two keys was ever read from it, so carrying the
        whole dict bought nothing and made a stale target expressible.

        :param res_model: model the attachments are linked to
        :param res_id: id of the record they are linked to
        :return: whether documents were created
        """
        # Special case for documents: bind, rather than file a copy of, an
        # attachment created straight onto a content-less document.
        if res_model == "documents.document" and res_id:
            document = self.env["documents.document"].search_fetch(
                [("id", "=", res_id)], []
            )
            if document and not document.attachment_id and document.type == "binary":
                document.attachment_id = self[0].id
            return False

        # Generic case for all other models
        model = self.env.get(res_model)
        if (
            model is None
            or not res_id
            or not issubclass(self.pool[res_model], self.pool["mixin.documents"])
        ):
            return False
        # Hoisted out of the loop: whether the model files its attachments at
        # all is a property of the record, not of the attachment, and the
        # override resolving it (`_get_document_folder`) searches.
        record = model.browse(res_id)
        if not record._check_create_documents():
            return False
        vals_list = [
            document_vals
            for attachment in self
            if not attachment.res_field
            and (document_vals := record._get_document_vals(attachment))
        ]
        if not vals_list:
            return False
        self.env["documents.document"].create(vals_list)
        return True

    @api.model_create_multi
    def create(self, vals_list: list[dict]) -> IrAttachment:
        """Create attachments and their related documents when relevant."""
        attachments = super().create(vals_list)
        # The context can indicate that these attachments are created from
        # documents, and therefore do not need a document to contain them. The
        # test is loop-invariant, so it is made once.
        if self.env.context.get("no_document"):
            return attachments
        # Grouped by target, the way `write` already does it. `_create_document`
        # takes a *recordset* and files it in a single `documents.document`
        # create, but it was called once per attachment -- so uploading fifteen
        # files onto one record paid fifteen folder resolutions and fifteen
        # creates for work the method does in one pass. The target is read off
        # each created row, not off its vals, since the two can differ (a
        # default, an inverse).
        to_document = attachments.filtered(lambda a: not a.res_field)
        for (res_model, res_id), grouped in to_document.grouped(
            lambda attachment: (attachment.res_model, attachment.res_id)
        ).items():
            grouped.sudo()._create_document(res_model, res_id)
        return attachments

    def write(self, vals: dict) -> bool:
        """Write attachment values and create related documents when relevant."""
        # `_create_document` runs in sudo and mutates *other* records (it fills
        # `documents.document.attachment_id`, and may create documents through
        # the mixin). It must therefore run **after** `super().write()`, which is
        # what authorizes the new `res_model`/`res_id` target: doing it first
        # applied a side effect on records the caller had not yet been cleared
        # for. The selection is still computed on the pre-write state, since
        # `a.res_field` would otherwise already reflect `vals`.
        if self.env.context.get("no_document"):
            return super().write(vals)
        to_document = self.filtered(
            lambda a: not (vals.get("res_field") or a.res_field)
        )
        result = super().write(vals)
        if not {"res_model", "res_id"} & vals.keys():
            # Nothing about the link changed, so nothing can become a document.
            # The old code called `_create_document(vals)` anyway; with neither
            # key present it resolved no model and returned immediately.
            return result
        # Resolve the target off each attachment the way `create` does, instead
        # of reading the caller's raw `vals`. A link is routinely completed one
        # key at a time -- `write({"res_id": record.id})` on an attachment that
        # already carries `res_model` -- and `vals` alone then says
        # `res_model=None`, so `_create_document` matched no mixin and the bridge
        # document was never created. Grouping keeps one call per distinct
        # target, which is what the method expects (it files a whole recordset
        # against a single `res_id`).
        for (res_model, res_id), attachments in to_document.grouped(
            lambda attachment: (attachment.res_model, attachment.res_id)
        ).items():
            attachments.sudo()._create_document(res_model, res_id)
        return result
