from typing import Any

from odoo import api, fields, models


class IrDemo_Failure(models.TransientModel):
    """Stores modules for which we could not install demo data"""

    _name = "ir.demo_failure"
    _description = "Demo failure"

    module_id = fields.Many2one("ir.module.module", required=True, string="Module")
    # Holds a full multi-line traceback.format_exc(); Text (not Char) so it
    # renders readably and is semantically correct for long, multi-line text.
    error = fields.Text(string="Error")
    # Orphan-row contract (latent IDEMOF-L1): rows are created with wizard_id
    # unset by odoo.modules.loading.load_demo and must survive as orphans until
    # the base.demo_failure_action server action collects them via
    # search([('wizard_id', '=', False)]) and links them with Command.set.
    # Both models are TransientModel, so _transient_vacuum may unlink rows older
    # than transient_age_limit; if the autovacuum cron fires between a slow demo
    # load and the dialog opening, failures can silently vanish and the count
    # under-reports. Low probability in the normal force-demo flow (rows are
    # minutes old). Recommended fix is a design change (link to the wizard
    # immediately, exclude these rows from vacuum within the force-demo
    # transaction, or make the model non-transient) — not applied here to keep
    # model semantics unchanged.
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
        """Count the demo-installation failures linked to each wizard."""
        for r in self:
            r.failures_count = len(r.failure_ids)

    def done(self) -> dict[str, Any]:
        """Dismiss the dialog and advance the module install/config todo chain."""
        return self.env["ir.module.module"]._next_todo_action()
