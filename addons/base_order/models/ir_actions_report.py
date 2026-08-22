import io

from odoo import models
from odoo.tools.pdf import OdooPdfFileReader, OdooPdfFileWriter


class IrActionsReport(models.Model):
    _inherit = "ir.actions.report"

    def _get_order_edi_report_map(self):
        return {}

    def _render_qweb_pdf_prepare_streams(self, report_ref, data, res_ids=None):
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
        pdf_stream = collected_streams[order.id]["stream"]
        pdf_content = pdf_stream.getvalue()
        reader_buffer = io.BytesIO(pdf_content)
        reader = OdooPdfFileReader(reader_buffer, strict=False)
        writer = OdooPdfFileWriter()
        writer.clone_reader_document_root(reader)

        order_sudo = order.sudo()
        for builder in builders:
            xml_content = builder._export_order(order_sudo)

            writer.add_attachment(
                builder._export_invoice_filename(order),
                xml_content,
                subtype="text/xml",
            )

        pdf_stream.close()
        new_pdf_stream = io.BytesIO()
        writer.write(new_pdf_stream)
        reader_buffer.close()
        collected_streams[order.id]["stream"] = new_pdf_stream

        return collected_streams
