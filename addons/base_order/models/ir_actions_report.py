import io

from odoo import models
from odoo.tools.pdf import OdooPdfFileReader, OdooPdfFileWriter


class IrActionsReport(models.Model):
    _inherit = "ir.actions.report"

    # ------------------------------------------------------------
    # HELPER METHODS
    # ------------------------------------------------------------

    def _get_order_edi_report_map(self):
        """Map ``report_name`` -> order model for reports embedding EDI XML.

        Concrete order modules extend this with their own report names; the
        embedding itself is shared. Returning an empty mapping (the default)
        disables the whole feature, so a database without sale or purchase
        installed pays only a dict lookup per PDF render.
        """
        return {}

    def _render_qweb_pdf_prepare_streams(self, report_ref, data, res_ids=None):
        # EXTENDS base
        collected_streams = super()._render_qweb_pdf_prepare_streams(
            report_ref,
            data,
            res_ids=res_ids,
        )

        if not collected_streams or not res_ids or len(res_ids) != 1:
            return collected_streams

        report_map = self._get_order_edi_report_map()
        if not report_map:
            return collected_streams

        model_name = report_map.get(self._get_report(report_ref).report_name)
        if not model_name:
            return collected_streams

        order = self.env[model_name].browse(res_ids)
        builders = order._get_edi_builders()
        if not builders:
            return collected_streams

        return self._embed_order_edi_documents(collected_streams, order, builders)

    def _embed_order_edi_documents(self, collected_streams, order, builders):
        """Attach each builder's EDI XML to the rendered order PDF."""
        # Read pdf content.
        pdf_stream = collected_streams[order.id]["stream"]
        pdf_content = pdf_stream.getvalue()
        reader_buffer = io.BytesIO(pdf_content)
        reader = OdooPdfFileReader(reader_buffer, strict=False)
        writer = OdooPdfFileWriter()
        writer.clone_reader_document_root(reader)

        # Generate and attach EDI documents from each builder.
        # sudo(): the UBL export reaches fields the printing user may not be
        # able to read on their own — with account_intrastat installed,
        # account.edi.xml.ubl_bis3 reads product.intrastat_code_id, which needs
        # an Accounting group, so a Sales- or Purchase-only user printing an
        # order would otherwise hit an AccessError (opw-5976725). The order
        # itself is already access-checked by the render that produced
        # ``collected_streams``.
        order_sudo = order.sudo()
        for builder in builders:
            xml_content = builder._export_order(order_sudo)

            writer.add_attachment(
                builder._export_invoice_filename(order),  # works for a SO or PO
                xml_content,
                subtype="text/xml",
            )

        # Replace the current content.
        pdf_stream.close()
        new_pdf_stream = io.BytesIO()
        writer.write(new_pdf_stream)
        reader_buffer.close()
        collected_streams[order.id]["stream"] = new_pdf_stream

        return collected_streams
