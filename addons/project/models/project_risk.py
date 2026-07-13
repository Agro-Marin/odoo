"""Project risk register — structured risk management.

Evidence basis: PMI risk framework (most validated portion of PMBOK),
pre-mortem analysis (Klein: +30% cause identification), consistently
in top-5 critical success factors across meta-analyses.
"""

from odoo import api, fields, models


class ProjectRisk(models.Model):
    """A risk identified for a project, with probability x impact scoring."""

    _name = "project.risk"
    _description = "Project Risk"
    _order = "risk_score desc, id desc"
    _inherit = ["mail.thread"]

    name = fields.Char("Risk", required=True, tracking=True)
    description = fields.Html("Description")
    project_id = fields.Many2one(
        "project.project",
        required=True,
        ondelete="cascade",
        index=True,
    )
    task_id = fields.Many2one(
        "project.task",
        string="Related Task",
        index="btree_not_null",
        help="Optional link to a specific task affected by this risk.",
    )
    category = fields.Selection(
        [
            ("technical", "Technical"),
            ("organizational", "Organizational"),
            ("external", "External"),
            ("financial", "Financial"),
            ("schedule", "Schedule"),
        ],
        string="Category",
        default="technical",
        required=True,
        tracking=True,
    )
    probability = fields.Selection(
        [
            ("1", "Rare"),
            ("2", "Unlikely"),
            ("3", "Possible"),
            ("4", "Likely"),
            ("5", "Almost Certain"),
        ],
        string="Probability",
        default="3",
        required=True,
        tracking=True,
    )
    impact = fields.Selection(
        [
            ("1", "Negligible"),
            ("2", "Minor"),
            ("3", "Moderate"),
            ("4", "Major"),
            ("5", "Catastrophic"),
        ],
        string="Impact",
        default="3",
        required=True,
        tracking=True,
    )
    risk_score = fields.Integer(
        "Risk Score",
        compute="_compute_risk_score",
        store=True,
        help="Probability × Impact (1–25).",
    )
    risk_level = fields.Selection(
        [
            ("low", "Low"),
            ("medium", "Medium"),
            ("high", "High"),
            ("critical", "Critical"),
        ],
        string="Risk Level",
        compute="_compute_risk_score",
        store=True,
    )
    response_strategy = fields.Selection(
        [
            ("mitigate", "Mitigate"),
            ("transfer", "Transfer"),
            ("accept", "Accept"),
            ("avoid", "Avoid"),
            ("exploit", "Exploit"),
        ],
        string="Response Strategy",
        tracking=True,
    )
    response_plan = fields.Html("Response Plan")
    owner_id = fields.Many2one(
        "res.users",
        string="Risk Owner",
        tracking=True,
        help="Person responsible for monitoring and responding to this risk.",
    )
    state = fields.Selection(
        [
            ("identified", "Identified"),
            ("assessed", "Assessed"),
            ("mitigated", "Mitigated"),
            ("resolved", "Resolved"),
            ("accepted", "Accepted"),
        ],
        string="State",
        default="identified",
        required=True,
        tracking=True,
    )
    date_identified = fields.Date("Date Identified", default=fields.Date.today)
    date_resolved = fields.Date("Date Resolved")
    active = fields.Boolean(default=True)

    @api.depends("probability", "impact")
    def _compute_risk_score(self) -> None:
        """Compute risk score and derive risk level from the score."""
        for risk in self:
            score = int(risk.probability or 0) * int(risk.impact or 0)
            risk.risk_score = score
            if score >= 16:
                risk.risk_level = "critical"
            elif score >= 10:
                risk.risk_level = "high"
            elif score >= 5:
                risk.risk_level = "medium"
            else:
                risk.risk_level = "low"
