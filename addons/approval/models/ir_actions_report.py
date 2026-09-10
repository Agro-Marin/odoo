from odoo import api, models

GATED_CONTEXT_KEY = "approval_report_gated"


class IrActionsReport(models.Model):
    _inherit = "ir.actions.report"

    def _check_report_approval(self, report_ref, res_ids) -> None:
        """Refuse to render records an approval binding on this report does not cover.

        Checked at every render entry point, not inside the rendering context: a PDF
        already stored as an attachment is returned without rendering again, so a
        check further in would let every reprint through. The context key keeps the
        PDF path, which can fall back to HTML, from being checked twice.
        """
        if self.env.context.get(GATED_CONTEXT_KEY) or not res_ids:
            return
        Binding = self.env["approval.binding"]
        if not Binding._enabled():
            return
        report = self._get_report(report_ref)
        bindings = Binding._bindings_for_action(report.id)
        if not bindings:
            return
        ids = [res_ids] if isinstance(res_ids, int) else list(res_ids)
        Binding._gate(
            self.env[report.model].browse(ids),
            bindings,
            report.name,
            lambda runnable: None,
        )

    def _render_qweb_pdf(self, report_ref, res_ids=None, data=None):
        self._check_report_approval(report_ref, res_ids)
        return super(
            IrActionsReport, self.with_context(**{GATED_CONTEXT_KEY: True})
        )._render_qweb_pdf(report_ref, res_ids=res_ids, data=data)

    @api.model
    def _render_qweb_html(self, report_ref, docids, data=None):
        self._check_report_approval(report_ref, docids)
        return super(
            IrActionsReport, self.with_context(**{GATED_CONTEXT_KEY: True})
        )._render_qweb_html(report_ref, docids, data=data)

    @api.model
    def _render_qweb_text(self, report_ref, docids, data=None):
        self._check_report_approval(report_ref, docids)
        return super(
            IrActionsReport, self.with_context(**{GATED_CONTEXT_KEY: True})
        )._render_qweb_text(report_ref, docids, data=data)
