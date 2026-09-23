from odoo import api, models

from . import approval_trace as trace


class IrActionsReport(models.Model):
    _inherit = "ir.actions.report"

    def _check_report_approval(self, report_ref, res_ids):
        """Refuse to render records an approval binding on this report does not cover.

        Checked at every render entry point, not inside the rendering context: a PDF
        already stored as an attachment is returned without rendering again, so a
        check further in would let every reprint through. A render that passed is
        admitted for its records while it runs, so the PDF path, which can fall back
        to HTML, is not checked twice; the admission is the server's, never the
        context's, which the report route takes from the client.

        Returns the records the render is admitted for, or None when nothing gates it.
        """
        if not res_ids:
            return None
        Binding = self.env["approval.binding"]
        if not Binding._enabled():
            return None
        report = self._get_report(report_ref)
        bindings = Binding._bindings_for_action(report.id)
        if not bindings:
            return None
        ids = [res_ids] if isinstance(res_ids, int) else list(res_ids)
        records = self.env[report.model].browse(ids)
        operation = self._get_report_admission(report)
        if set(ids) <= Binding._get_admitted_ids(records, operation):
            return None
        trace.BINDING.event(
            "report_render",
            report=report.id,
            model=report.model,
            records=ids,
            bindings=bindings.ids,
        )
        Binding._gate(records, bindings, report.name, lambda runnable: None)
        return records

    @api.model
    def _get_report_admission(self, report):
        return f"report:{report.id}"

    def _render_admitted(self, report_ref, res_ids, render):
        records = self._check_report_approval(report_ref, res_ids)
        if records is None:
            return render()
        operation = self._get_report_admission(self._get_report(report_ref))
        return self.env["approval.binding"]._run_admitted(
            records, operation, lambda admitted: render()
        )

    def _render_qweb_pdf(self, report_ref, res_ids=None, data=None):
        return self._render_admitted(
            report_ref,
            res_ids,
            lambda: super(IrActionsReport, self)._render_qweb_pdf(
                report_ref, res_ids=res_ids, data=data
            ),
        )

    @api.model
    def _render_qweb_html(self, report_ref, docids, data=None):
        return self._render_admitted(
            report_ref,
            docids,
            lambda: super(IrActionsReport, self)._render_qweb_html(
                report_ref, docids, data=data
            ),
        )

    @api.model
    def _render_qweb_text(self, report_ref, docids, data=None):
        return self._render_admitted(
            report_ref,
            docids,
            lambda: super(IrActionsReport, self)._render_qweb_text(
                report_ref, docids, data=data
            ),
        )
