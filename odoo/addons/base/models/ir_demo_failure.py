from typing import Any

from odoo import api, fields, models


class IrDemo_Failure(models.TransientModel):
    """Stores modules for which we could not install demo data"""

    _name = "ir.demo_failure"
    _description = "Demo failure"

    module_id = fields.Many2one("ir.module.module", required=True, string="Module")
    # Full multi-line traceback.format_exc(); Text so long tracebacks render readably.
    error = fields.Text(string="Error")
    # Orphan-row contract (latent IDEMOF-L1): load_demo creates rows with wizard_id
    # unset; base.demo_failure_action later collects the orphans and links them.
    # Both models are transient, so _transient_vacuum can unlink rows older than
    # transient_age_limit — if the cron fires between a slow demo load and the dialog
    # opening, failures vanish and the count under-reports. Fix is a design change
    # (link immediately, exclude from vacuum, or make non-transient), not done here.
    wizard_id = fields.Many2one("ir.demo_failure.wizard")


class IrDemo_FailureWizard(models.TransientModel):
    """Dialog aggregating per-module demo-data installation failures."""

    _name = "ir.demo_failure.wizard"
    _description = "Demo Failure wizard"

    failure_ids = fields.One2many(
        "ir.demo_failure",
        "wizard_id",
        readonly=True,
        string="Demo Installation Failures",
    )
    failures_count = fields.Integer(compute="_compute_failures_count")

    @api.depends("failure_ids")
    def _compute_failures_count(self) -> None:
        for r in self:
            r.failures_count = len(r.failure_ids)

    def done(self) -> dict[str, Any]:
        """Dismiss the dialog and advance the module install/config todo chain."""
        return self.env["ir.module.module"]._next_todo_action()
