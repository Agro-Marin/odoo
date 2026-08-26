from odoo import api, fields, models
from odoo.exceptions import ValidationError


class ProjectRetrospective(models.Model):
    _name = "project.retrospective"
    _description = "Project Retrospective"
    _order = "date desc, id desc"
    _inherit = ["mixin.mail.thread"]

    name = fields.Char("Title", required=True, tracking=True)
    project_id = fields.Many2one(
        "project.project",
        required=True,
        ondelete="cascade",
        index=True,
    )
    date = fields.Date("Date", required=True, default=fields.Date.today)
    facilitator_id = fields.Many2one(
        "res.users",
        string="Facilitator",
        default=lambda self: self.env.user,
    )
    went_well = fields.Html(
        "What Went Well",
        help="Practices and decisions that should be repeated.",
    )
    to_improve = fields.Html(
        "What Needs Improvement",
        help="Areas where changes would improve outcomes.",
    )
    action_ids = fields.One2many(
        "project.retrospective.action",
        "retrospective_id",
        string="Action Items",
    )
    action_count = fields.Count(
        "action_ids",
        "Actions",
        export_string_translation=False,
    )
    open_action_count = fields.Integer(
        "Open Actions",
        compute="_compute_open_action_count",
        export_string_translation=False,
    )
    previous_id = fields.Many2one(
        "project.retrospective",
        string="Previous Retrospective",
        help="Link to the previous retrospective for action carry-forward.",
    )
    state = fields.Selection(
        [("draft", "Draft"), ("done", "Done")],
        default="draft",
        required=True,
        tracking=True,
    )

    @api.depends("action_ids.state")
    def _compute_open_action_count(self) -> None:
        for retro in self:
            retro.open_action_count = len(
                retro.action_ids.filtered(lambda a: a.state in ("open", "in_progress"))
            )

    @api.constrains("previous_id")
    def _check_previous_no_cycle(self) -> None:
        if self._has_cycle("previous_id"):
            raise ValidationError(
                self.env._(
                    "A retrospective cannot be its own predecessor "
                    "(circular 'Previous Retrospective' link)."
                )
            )

    def action_carry_forward(self) -> None:
        self.ensure_one()
        if not self.previous_id:
            return
        already_carried = set(self.action_ids.mapped("carried_from_id").ids)
        open_actions = self.previous_id.action_ids.filtered(
            lambda a: a.state in ("open", "in_progress") and a.id not in already_carried
        )
        for action in open_actions:
            action.copy(
                {
                    "retrospective_id": self.id,
                    "carried_from_id": action.id,
                }
            )


class ProjectRetrospectiveAction(models.Model):
    _name = "project.retrospective.action"
    _description = "Retrospective Action Item"
    _order = "state_order, due_date, id"

    name = fields.Char("Action", required=True)
    retrospective_id = fields.Many2one(
        "project.retrospective",
        required=True,
        ondelete="cascade",
        index=True,
    )
    project_id = fields.Many2one(
        related="retrospective_id.project_id",
        store=True,
        index=True,
    )
    owner_id = fields.Many2one(
        "res.users",
        string="Owner",
        required=True,
    )
    due_date = fields.Date("Due Date")
    state = fields.Selection(
        [
            ("open", "Open"),
            ("in_progress", "In Progress"),
            ("done", "Done"),
            ("dropped", "Dropped"),
        ],
        default="open",
        required=True,
    )
    state_order = fields.Integer(
        compute="_compute_state_order",
        store=True,
        export_string_translation=False,
        help="Sort key: outstanding actions first. Ordering by ``state`` "
        "directly sorts on the stored keys, which puts Done and Dropped "
        "above the open items this list exists to surface.",
    )
    resolution_note = fields.Text(
        "Resolution Note",
        help="How was this action resolved?",
    )
    carried_from_id = fields.Many2one(
        "project.retrospective.action",
        string="Carried From",
        help="If this action was carried forward from a previous retrospective.",
    )
    category = fields.Selection(
        [
            ("estimation", "Estimation"),
            ("scope", "Scope"),
            ("communication", "Communication"),
            ("technical", "Technical"),
            ("process", "Process"),
            ("team", "Team"),
            ("tooling", "Tooling"),
        ],
        string="Category",
    )

    _STATE_ORDER = {"open": 0, "in_progress": 1, "done": 2, "dropped": 3}

    @api.depends("state")
    def _compute_state_order(self) -> None:
        for action in self:
            action.state_order = self._STATE_ORDER.get(action.state, 99)
