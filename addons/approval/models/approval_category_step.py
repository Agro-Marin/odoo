from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.fields import Command


class ApprovalCategoryStep(models.Model):
    _name = "approval.category.step"
    _inherit = ["mixin.approval.domain"]
    _description = "Approval Step"
    _order = "category_id, sequence, id"

    category_id = fields.Many2one(
        comodel_name="approval.category",
        required=True,
        ondelete="cascade",
        index=True,
    )
    company_id = fields.Many2one(
        related="category_id.company_id",
        store=True,
        readonly=True,
        index=True,
    )
    sequence = fields.Integer(default=10)
    name = fields.Char(required=True, translate=True)
    active = fields.Boolean(default=True)
    minimum = fields.Integer(
        string="Approvals Needed",
        default=1,
        help="How many approvals from this step's pool complete it.",
    )
    member_ids = fields.One2many(
        comodel_name="approval.category.step.member",
        inverse_name="step_id",
        string="Members",
    )
    user_ids = fields.Many2many(
        comodel_name="res.users",
        string="Approvers",
        compute="_compute_user_ids",
        inverse="_inverse_user_ids",
        help="The step's current members, as an editable list. Delegated members are "
        "kept as they are when this list is edited.",
    )
    group_id = fields.Many2one(
        comodel_name="res.groups",
        string="Approval Group",
        help="Every member of this group may approve the step, together with the "
        "step's own members.",
    )
    exclusive = fields.Boolean(
        help="An approval that counts toward this step counts toward no other step "
        "of the same request, and the other way round: a user who decided an "
        "exclusive step decides nothing else on that request.",
    )
    notify_user_ids = fields.Many2many(
        comodel_name="res.users",
        relation="approval_step_notify_user_rel",
        column1="step_id",
        column2="user_id",
        string="Notify",
        help="Posted an internal note when an approver of this step decides.",
    )
    subject_model_id = fields.Many2one(
        comodel_name="ir.model",
        string="Source Model",
        ondelete="cascade",
        help="Model the condition reads. Required when a condition is set.",
    )
    subject_domain = fields.Char(
        string="Applies When",
        help="Domain on the request's source document. The step applies only to "
        "requests whose source document matches; empty means every request.",
    )

    def _domain_source_field(self) -> str:
        return "subject_domain"

    @api.constrains("minimum", "member_ids", "group_id", "user_ids")
    def _check_pool(self) -> None:
        for step in self:
            if step.minimum < 1:
                raise ValidationError(
                    self.env._(
                        "Step '%(step)s' needs at least one approval.", step=step.name
                    ),
                )
            if not step.member_ids and not step.group_id:
                raise ValidationError(
                    self.env._(
                        "Step '%(step)s' has nobody who could approve it: give it "
                        "members, an approval group, or both.",
                        step=step.name,
                    ),
                )

    @api.constrains("subject_domain", "subject_model_id")
    def _check_condition(self) -> None:
        for step in self.filtered("subject_domain"):
            model = step.subject_model_id and self.env.get(step.subject_model_id.model)
            if model is None or not step.subject_model_id:
                raise ValidationError(
                    self.env._(
                        "Step '%(step)s' has a condition, so it needs the source "
                        "model that condition reads.",
                        step=step.name,
                    ),
                )
            step._check_domain_against_model(model)

    @api.constrains("category_id")
    def _check_category_not_sequential(self) -> None:
        for step in self:
            if step.category_id.approve_sequentially:
                step.category_id._raise_steps_with_approver_sequence()

    @api.depends("member_ids.user_id", "member_ids.date_end")
    def _compute_user_ids(self) -> None:
        today = fields.Date.context_today(self)
        for step in self:
            step.user_ids = step.member_ids.filtered(
                lambda member: not member.date_end or member.date_end >= today
            ).user_id

    def _inverse_user_ids(self) -> None:
        for step in self:
            users = step.user_ids
            missing = users - step.member_ids.user_id
            if missing:
                step.member_ids = [
                    Command.create({"user_id": user.id}) for user in missing
                ]
            step.member_ids.filtered(
                lambda member, users=users: (
                    not member.delegated_by_id and member.user_id not in users
                )
            ).unlink()
        self._check_pool()

    def _get_member_user_ids(self) -> set[int]:
        self.check_singleton()
        today = fields.Date.context_today(self)
        return {
            member.user_id.id
            for member in self.member_ids
            if not member.date_end or member.date_end >= today
        }

    def _get_pool_user_ids(self) -> set[int]:
        """Who may approve this step today: valid members, and the group's users."""
        self.check_singleton()
        users = self._get_member_user_ids()
        if self.group_id:
            users.update(self.group_id.all_user_ids.ids)
        return users

    @api.ondelete(at_uninstall=False)
    def _unlink_except_step_holding_decisions(self) -> None:
        decided = (
            self.env["approval.approver"]
            .sudo()
            .search_count(
                [
                    ("step_ids", "in", self.ids),
                    ("state", "in", ("approved", "refused")),
                ],
                limit=1,
            )
        )
        if decided:
            raise UserError(
                self.env._(
                    "A step that holds decisions cannot be deleted. Archive it "
                    "instead, so the decisions keep the step they were given for."
                ),
            )

    def _is_applicable_to_request(self, request) -> bool:
        self.check_singleton()
        if not self.subject_domain:
            return True
        return self._is_applicable_to_document(request.get_source_document())

    def _is_applicable_to_document(self, document) -> bool:
        self.check_singleton()
        if not self.subject_domain:
            return True
        if (
            not document
            or not self.subject_model_id
            or document._name != self.subject_model_id.model
        ):
            return False
        domain = self._parse_domain_or_warn()
        if domain is None:
            return False
        return bool(document.exists().filtered_domain(domain))


class ApprovalCategoryStepMember(models.Model):
    _name = "approval.category.step.member"
    _description = "Approval Step Member"
    _order = "step_id, id"
    _rec_name = "user_id"

    _step_user_uniq = models.Constraint(
        "unique(step_id, user_id)",
        "A user is a member of a step only once.",
    )

    step_id = fields.Many2one(
        comodel_name="approval.category.step",
        required=True,
        ondelete="cascade",
        index=True,
    )
    company_id = fields.Many2one(
        related="step_id.company_id",
        store=True,
        readonly=True,
        index=True,
    )
    user_id = fields.Many2one(
        comodel_name="res.users",
        required=True,
        ondelete="cascade",
        index=True,
    )
    date_end = fields.Date(
        string="Valid Until",
        help="Last day this user may approve the step. Empty means no end, so a "
        "delegation until a date is a membership with an end date.",
    )
    delegated_by_id = fields.Many2one(
        comodel_name="res.users",
        string="Delegated By",
        help="Who handed over the right, when this membership is a delegation.",
    )
