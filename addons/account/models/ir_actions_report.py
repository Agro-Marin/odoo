from collections import OrderedDict
from zlib import error as zlib_error

import lxml.html

from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools import pdf


class IrActionsReport(models.Model):
    _inherit = "ir.actions.report"

    is_invoice_report = fields.Boolean(
        string="Invoice report",
        copy=True,
    )

    def _render_qweb_pdf_prepare_streams(self, report_ref, data, res_ids=None):
        # Custom behavior for 'account.report_original_vendor_bill'.
        if (
            self._get_report(report_ref).report_name
            != "account.report_original_vendor_bill"
        ):
            return super()._render_qweb_pdf_prepare_streams(
                report_ref, data, res_ids=res_ids
            )

        invoices = self.env["account.move"].browse(res_ids)
        original_attachments = invoices.message_main_attachment_id
        if not original_attachments:
            raise UserError(
                _(
                    "No original purchase document could be found for any of the selected purchase documents."
                )
            )

        collected_streams = OrderedDict()
        for invoice in invoices:
            attachment = self._prepare_local_attachments(
                invoice.message_main_attachment_id.sudo()
            )
            if attachment:
                stream = pdf.to_pdf_stream(attachment)
                if stream and attachment.res_model:
                    record = self.env[attachment.res_model].browse(attachment.res_id)
                    try:
                        stream = pdf.add_banner(stream, record.name or "", logo=True)
                    except (
                        ValueError,
                        pdf.PdfReadError,
                        TypeError,
                        zlib_error,
                        NotImplementedError,
                        pdf.DependencyError,
                        ArithmeticError,
                    ):
                        record._message_log(
                            body=_(
                                "There was an error when trying to add the banner to the original PDF.\n"
                                "Please make sure the source file is valid."
                            )
                        )
                collected_streams[invoice.id] = {
                    "stream": stream,
                    "attachment": attachment,
                }
        return collected_streams

    def _is_invoice_report(self, report_ref):
        report = self._get_report(report_ref)
        return (
            report.is_invoice_report and report.model == "account.move"
        ) or report.report_name == "account.report_invoice"

    def _get_splitted_report(self, report_ref, content, report_type):
        if report_type == "html":
            # In test mode, _pre_render_qweb_pdf returns raw HTML bytes.
            # Parse article elements to map each record ID to its HTML chunk.
            report = self._get_report(report_ref)
            root = lxml.html.fromstring(
                content, parser=lxml.html.HTMLParser(encoding="utf-8")
            )
            # Standard class matching (space-separated CSS classes).
            articles = root.xpath(
                "//div[contains(concat(' ', normalize-space(@class), ' '), ' article ')]"
            )
            if not articles:
                # WORKAROUND: QWeb t-att-class with dict expressions renders
                # the raw Python dict string as the class attribute value
                # (e.g. "{'article': True, 'o_report_layout': True}") instead
                # of converting it to space-separated CSS classes like the JS
                # implementation does.
                #
                # Root cause: ir_qweb._post_processing_att does not handle dict
                # values for the 'class' attribute — it should convert
                # truthy-valued keys to CSS class strings.
                #
                # TODO: Fix QWeb _post_processing_att to convert dict class
                # values to "key1 key2 ..." strings, then remove this fallback.
                articles = root.xpath("//div[contains(@class, \"'article'\")]")
            result = {}
            for article in articles:
                if article.get("data-oe-model") == report.model:
                    res_id = int(article.get("data-oe-id", 0))
                    result[res_id] = lxml.html.tostring(article)
            if not result and articles:
                # Articles found but data-oe-model doesn't match —
                # use data-oe-id directly if available.
                for article in articles:
                    res_id = int(article.get("data-oe-id", 0))
                    if res_id:
                        result[res_id] = lxml.html.tostring(article)
            if not result:
                # Fallback: single document without article markers
                result[False] = (
                    content if isinstance(content, bytes) else content.encode()
                )
            return result
        elif report_type == "pdf":
            pdf_dict = {
                res_id: stream["stream"].getvalue()
                for res_id, stream in content.items()
            }
            for stream in content.values():
                stream["stream"].close()
            return pdf_dict
        return None

    def _pre_render_qweb_pdf(self, report_ref, res_ids=None, data=None):
        # Check for reports only available for invoices.
        # + append context data with the display_name_in_footer parameter
        if self._is_invoice_report(report_ref):
            invoices = self.env["account.move"].browse(res_ids)
            if (
                self.env["ir.config_parameter"]
                .sudo()
                .get_param("account.display_name_in_footer")
            ):
                data = (data and dict(data)) or {}
                data.update({"display_name_in_footer": True})
            if any(x.move_type == "entry" for x in invoices):
                raise UserError(_("Only invoices could be printed."))

        return super()._pre_render_qweb_pdf(report_ref, res_ids=res_ids, data=data)

    @api.ondelete(at_uninstall=False)
    def _unlink_except_master_tags(self):
        master_xmlids = [
            "account_invoices",
            "action_account_original_vendor_bill",
            "account_invoices_without_payment",
            "action_report_journal",
            "action_report_payment_receipt",
            "action_report_account_statement",
            "action_report_account_hash_integrity",
        ]
        for master_xmlid in master_xmlids:
            master_report = self.env.ref(
                f"account.{master_xmlid}", raise_if_not_found=False
            )
            if master_report and master_report in self:
                raise UserError(
                    _(
                        "You cannot delete this report (%s), it is used by the accounting PDF generation engine.",
                        master_report.name,
                    )
                )

    def _get_rendering_context(self, report, docids, data):
        data = super()._get_rendering_context(report, docids, data)
        if self.env.context.get("proforma_invoice"):
            data["proforma"] = True
        return data
