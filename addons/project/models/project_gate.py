"""Gate reviews with go/no-go criteria tied to milestones.

Evidence basis: Flyvbjerg — 'Projects don't just go wrong; they start
wrong.' Standish — killing a doomed project early is good management.
Gate reviews force explicit go/no-go decisions at defined points.
"""

from odoo import api, fields, models
from odoo.exceptions import ValidationError


class ProjectGate(models.Model):
    """A formal review point in a project lifecycle with pass/fail criteria."""

    _name = "project.gate"
    _description = "Project Gate Review"
    _order = "sequence, id"
    _inherit = ["mail.thread"]

    name = fields.Char("Gate Name", required=True, tracking=True)
    project_id = fields.Many2one(
        "project.project",
        required=True,
        ondelete="cascade",
        index=True,
    )
    sequence = fields.Integer("Gate Order", default=10)
    milestone_id = fields.Many2one(
        "project.milestone",
        string="Trigger Milestone",
        domain="[('project_id', '=', project_id)]",
        help="Review is triggered when this milestone is reached.",
    )
    criterion_ids = fields.One2many(
        "project.gate.criterion",
        "gate_id",
        string="Review Criteria",
    )
    state = fields.Selection(
        [
            ("pending", "Pending"),
            ("passed", "Passed"),
            ("failed", "Failed"),
            ("deferred", "Deferred"),
        ],
        default="pending",
        required=True,
        tracking=True,
    )
    review_date = fields.Date("Review Date", tracking=True)
    reviewer_ids = fields.Many2many(
        "res.users",
        string="Reviewers",
    )
    decision_notes = fields.Html("Decision Notes")
    kill_criteria = fields.Html(
        "Kill Criteria",
        help="Pre-defined conditions under which the project should be cancelled.",
    )
    criteria_met_count = fields.Integer(
        "Criteria Met",
        compute="_compute_criteria_counts",
        export_string_translation=False,
    )
    criteria_total_count = fields.Integer(
        "Total Criteria",
        compute="_compute_criteria_counts",
        export_string_translation=False,
    )

    @api.depends("criterion_ids", "criterion_ids.met")
    def _compute_criteria_counts(self) -> None:
        """Count total and met criteria per gate."""
        for gate in self:
            gate.criteria_total_count = len(gate.criterion_ids)
            gate.criteria_met_count = len(gate.criterion_ids.filtered("met"))

    @api.constrains("milestone_id", "project_id")
    def _check_milestone_project(self) -> None:
        """The trigger milestone must belong to the gate's own project.

        The form view scopes milestone_id via a domain, but ORM create/write
        and imports bypass domains, so enforce cross-project consistency here.
        """
        for gate in self:
            if gate.milestone_id and gate.milestone_id.project_id != gate.project_id:
                raise ValidationError(
                    self.env._(
                        "The trigger milestone of gate %(gate)s must belong to "
                        "its project (%(project)s).",
                        gate=gate.name,
                        project=gate.project_id.display_name,
                    )
                )


class ProjectGateCriterion(models.Model):
    """A single evaluable criterion within a gate review."""

    _name = "project.gate.criterion"
    _description = "Gate Review Criterion"
    _order = "sequence, id"

    gate_id = fields.Many2one(
        "project.gate",
        required=True,
        ondelete="cascade",
        index=True,
    )
    name = fields.Char("Criterion", required=True)
    sequence = fields.Integer(default=10)
    met = fields.Boolean("Met", default=False)
    evidence = fields.Text("Evidence")
