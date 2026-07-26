import base64
import io
import logging
from collections import defaultdict

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
                        "datas": base64.b64encode(stream.getvalue()),
                    }
                )
        return self.create(vals_list)

    def _create_document(self, vals: dict) -> bool:
        """Create documents for attachments linked to a documents-mixin business model.

        Implemented by bridge modules that create new documents if attachments are linked to
        their business models.

        :param vals: the create/write dictionary of ir attachment
        :return: True if new documents are created
        """
        # Special case for documents
        if vals.get("res_model") == "documents.document" and vals.get("res_id"):
            document = self.env["documents.document"].search_fetch(
                [("id", "=", vals["res_id"])], []
            )
            if document and not document.attachment_id and document.type == "binary":
                document.attachment_id = self[0].id
            return False

        # Generic case for all other models
        res_model = vals.get("res_model")
        res_id = vals.get("res_id")
        model = self.env.get(res_model)
        if (
            model is not None
            and res_id
            and issubclass(self.pool[res_model], self.pool["documents.mixin"])
        ):
            vals_list = [
                model.browse(res_id)._get_document_vals(attachment)
                for attachment in self
                if not attachment.res_field
                and model.browse(res_id)._check_create_documents()
            ]
            vals_list = [vals for vals in vals_list if vals]  # Remove empty values
            self.env["documents.document"].create(vals_list)
            return True
        return False

    @api.model_create_multi
    def create(self, vals_list: list[dict]) -> IrAttachment:
        """Create attachments and their related documents when relevant."""
        attachments = super().create(vals_list)
        for attachment, vals in zip(attachments, vals_list, strict=True):
            # the context can indicate that this new attachment is created from documents, and therefore
            # doesn't need a new document to contain it.
            if not self.env.context.get("no_document") and not attachment.res_field:
                attachment.sudo()._create_document(
                    dict(vals, res_model=attachment.res_model, res_id=attachment.res_id)
                )
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
        if not self.env.context.get("no_document"):
            to_document = self.filtered(
                lambda a: not (vals.get("res_field") or a.res_field)
            )
            result = super().write(vals)
            to_document.sudo()._create_document(vals)
            return result
        return super().write(vals)
