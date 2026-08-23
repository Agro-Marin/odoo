from odoo import api, fields, models


class ApprovalCategoryApprover(models.Model):
    _name = "approval.category.approver"
    _description = "Approval Category Approver"
    _order = "sequence"
    _rec_name = "user_id"

    _category_user_uniq = models.Constraint(
        "unique(category_id, user_id)",
        "A user may not be in the approver list of a category multiple times.",
    )

    category_id = fields.Many2one(
        comodel_name="approval.category",
        string="Approval Category",
        required=True,
        ondelete="cascade",
    )
    company_id = fields.Many2one(
        related="category_id.company_id",
        store=True,
        readonly=True,
        index=True,
        help="Mirrors the category's company; scopes the "
        "multi-company ir.rule on this model.",
    )
    existing_user_ids = fields.Many2many(
        comodel_name="res.users",
        compute="_compute_existing_user_ids",
    )
    user_id = fields.Many2one(
        comodel_name="res.users",
        required=True,
        domain="[('id', 'not in', existing_user_ids)]",
        ondelete="cascade",
        index=True,
    )
    sequence = fields.Integer(default=10)
    required = fields.Boolean(default=False)

    @api.constrains("category_id", "user_id", "required")
    def _check_category_coherence(self):
        self.category_id._constrains_approval_minimum()

    @api.depends("category_id", "category_id.approver_ids.user_id")
    def _compute_existing_user_ids(self):
        for record in self:
            if record.category_id:
                record.existing_user_ids = record.category_id.approver_ids.user_id
            else:
                record.existing_user_ids = self.env["res.users"]
