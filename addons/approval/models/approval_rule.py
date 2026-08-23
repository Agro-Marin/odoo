import math

from odoo import api, fields, models
from odoo.exceptions import ValidationError

_FLOAT_EQ_ABS_TOL = 1e-6
_FLOAT_EQ_REL_TOL = 1e-9


class ApprovalRule(models.Model):
    _name = "approval.rule"
    _description = "Conditional Approval Rule"
    _inherit = ["mixin.approval.threshold"]
    _order = "category_id, sequence, id"

    name = fields.Char(required=True)
    active = fields.Boolean(default=True)
    sequence = fields.Integer(default=10)
    category_id = fields.Many2one(
        comodel_name="approval.category",
        required=True,
        ondelete="cascade",
        index=True,
    )

    condition_field = fields.Selection(
        selection=[
            ("amount", "Amount"),
            ("quantity", "Quantity"),
            ("date_range_days", "Date Range (Days)"),
            ("priority", "Priority"),
        ],
        required=True,
        help="Request field to evaluate",
    )
    operator = fields.Selection(
        selection=[
            ("gt", "Greater than"),
            ("gte", "Greater than or equal"),
            ("lt", "Less than"),
            ("lte", "Less than or equal"),
            ("eq", "Equal to"),
            ("neq", "Not equal to"),
            ("between", "Between"),
        ],
        required=True,
        string="Comparison",
    )
    threshold = fields.Float(
        required=True,
        help="Numeric threshold to compare against, and the lower bound "
        "(inclusive) when the comparison is 'Between'. "
        "For priority: 0=Low, 1=Normal, 2=High, 3=Urgent.",
    )
    threshold_max = fields.Float(
        string="Upper Bound (exclusive)",
        help="Only for the 'Between' comparison: the upper bound, exclusive. "
        "0 means unlimited, which is how the highest band is expressed.",
    )

    action_type = fields.Selection(
        selection=[
            ("add_approver", "Add Approver"),
            ("set_approvers", "Replace Approvers"),
            ("auto_approve", "Auto-Approve"),
            ("auto_refuse", "Auto-Refuse"),
        ],
        default="add_approver",
        required=True,
        help="Action to take when condition matches:\n"
        "• Add Approver: inject additional approvers into the workflow\n"
        "• Replace Approvers: these approvers instead of the category's, and "
        "this rule's Minimum Approval instead of the category's. The first "
        "matching rule by sequence wins. Skipped entirely when the category "
        "takes its approvers from a security group, which is where this "
        "differs from Add Approver\n"
        "• Auto-Approve: skip approval entirely (logged in audit trail)\n"
        "• Auto-Refuse: automatically refuse the request",
    )
    approval_minimum = fields.Integer(
        default=1,
        help="Only for 'Replace Approvers': the minimum number of approvals "
        "this band requires, overriding the category's.",
    )
    approver_ids = fields.Many2many(
        comodel_name="res.users",
        string="Add Approvers",
        help="Users to add as approvers when condition is met. "
        "Only used for 'Add Approver' action type.",
    )
    approver_required = fields.Boolean(
        default=True,
        help="Whether the added approvers are mandatory",
    )
    approver_sequence = fields.Integer(
        default=5,
        help="Approval order for added approvers (lower = earlier)",
    )

    _name_category_uniq = models.Constraint(
        "unique nulls not distinct (name, category_id, company_id)",
        "Rule name must be unique per category and company.",
    )

    _APPROVER_ACTIONS = ("add_approver", "set_approvers")

    @api.constrains("action_type", "approver_ids")
    def _check_approver_ids_required(self):
        for rule in self:
            if rule.action_type in self._APPROVER_ACTIONS and not rule.approver_ids:
                raise ValidationError(
                    self.env._(
                        "Approvers are required when the action is '%(action)s'.",
                        action=dict(
                            rule._fields["action_type"]._description_selection(
                                self.env,
                            ),
                        )[rule.action_type],
                    ),
                )

    @api.constrains("action_type", "approval_minimum", "approver_ids")
    def _check_approval_minimum(self):
        for rule in self:
            if rule.action_type != "set_approvers":
                continue
            if rule.approval_minimum < 1:
                raise ValidationError(
                    self.env._("Minimum Approval must be at least 1."),
                )
            if rule.approval_minimum > len(rule.approver_ids):
                raise ValidationError(
                    self.env._(
                        "Minimum Approval must not exceed the number of "
                        "approvers this rule sets (%(count)d).",
                        count=len(rule.approver_ids),
                    ),
                )

    @api.constrains("operator", "threshold", "threshold_max")
    def _check_range_bounds(self):
        for rule in self:
            if rule.operator != "between":
                continue
            if rule.threshold_max and rule.threshold_max <= rule.threshold:
                raise ValidationError(
                    self.env._(
                        "The upper bound must be greater than the lower one "
                        "(or 0 for unlimited).",
                    ),
                )

    @api.constrains(
        "category_id",
        "company_id",
        "condition_field",
        "operator",
        "threshold",
        "threshold_max",
        "action_type",
        "active",
    )
    def _check_replacement_overlap(self):
        replacements = self.filtered(lambda r: r.action_type == "set_approvers")
        if not replacements:
            return
        stored_peers = self.sudo().search(
            [
                ("category_id", "in", replacements.category_id.ids),
                (
                    "condition_field",
                    "in",
                    list(set(replacements.mapped("condition_field"))),
                ),
                ("action_type", "=", "set_approvers"),
                ("active", "=", True),
            ],
        )
        for rule in replacements:
            if not rule.active:
                continue
            peers = (stored_peers | self).filtered(
                lambda r, cur=rule: (
                    r.id != cur.id
                    and r.category_id == cur.category_id
                    and r.condition_field == cur.condition_field
                    and r.action_type == "set_approvers"
                    and r.active
                ),
            )
            for other in peers:
                if (
                    rule.company_id
                    and other.company_id
                    and rule.company_id != other.company_id
                ):
                    continue
                if rule._condition_overlaps(other):
                    raise ValidationError(
                        self.env._(
                            "'%(rule)s' and '%(other)s' both replace the "
                            "approvers on %(field)s and can match the same "
                            "value. Narrow their ranges: which one applied "
                            "would depend on sequence alone.",
                            rule=rule.name,
                            other=other.name,
                            field=rule.condition_field,
                        ),
                    )

    @api.constrains(
        "category_id",
        "company_id",
        "condition_field",
        "operator",
        "threshold",
        "action_type",
        "active",
    )
    def _check_auto_action_conflict(self):
        auto_types = ("auto_approve", "auto_refuse")
        stored_peers = (
            self.sudo().search(
                [
                    ("category_id", "in", self.category_id.ids),
                    (
                        "condition_field",
                        "in",
                        list(set(self.mapped("condition_field"))),
                    ),
                    ("action_type", "in", auto_types),
                    ("active", "=", True),
                ],
            )
            if self.category_id
            else self.browse()
        )
        for rule in self:
            if rule.action_type not in auto_types or not rule.active:
                continue
            peers = (stored_peers | self).filtered(
                lambda r, cur=rule: (
                    r.id != cur.id
                    and r.category_id == cur.category_id
                    and r.condition_field == cur.condition_field
                    and r.action_type in auto_types
                    and r.active
                ),
            )
            for other in peers:
                if other.action_type == rule.action_type:
                    continue
                if (
                    rule.company_id
                    and other.company_id
                    and rule.company_id != other.company_id
                ):
                    continue
                if rule._condition_overlaps(other):
                    raise ValidationError(
                        self.env._(
                            "Rule '%(rule)s' (auto-%(rule_action)s) and "
                            "'%(other)s' (auto-%(other_action)s) can both "
                            "match the same %(field)s value — one would "
                            "silently override the other depending on "
                            "sequence. Narrow the thresholds so their "
                            "ranges don't overlap.",
                            rule=rule.name,
                            rule_action=rule.action_type.removeprefix("auto_"),
                            other=other.name,
                            other_action=other.action_type.removeprefix("auto_"),
                            field=rule.condition_field,
                        ),
                    )

    @api.constrains("threshold", "condition_field")
    def _check_threshold(self):
        for rule in self:
            if rule.condition_field == "priority" and rule.threshold not in (
                0,
                1,
                2,
                3,
            ):
                raise ValidationError(
                    self.env._(
                        "Priority threshold must be 0 (Low), 1 (Normal), "
                        "2 (High), or 3 (Urgent)."
                    )
                )

    _CONDITION_FIELD_DEPENDS = {
        "amount": ("amount", "currency_id", "date"),
        "quantity": ("quantity",),
        "date_range_days": ("date_start", "date_end"),
        "priority": ("priority",),
    }

    @api.model
    def _get_fields_request_trigger(self) -> frozenset[str]:
        return frozenset(
            field
            for depends in self._CONDITION_FIELD_DEPENDS.values()
            for field in depends
        )

    def _evaluate(self, request) -> bool:
        self.ensure_one()
        value = self._get_field_value(request)
        if value is None:
            return False
        return self._compare(value, self.threshold)

    def _get_field_value(self, request) -> float | None:
        match self.condition_field:
            case "amount":
                return self._convert_request_amount(request)
            case "quantity":
                return request.quantity
            case "priority":
                return int(request.priority)
            case "date_range_days":
                if request.date_start and request.date_end:
                    delta = request.date_end - request.date_start
                    return delta.total_seconds() / 86400
                return None
            case _:
                return None

    def _compare(self, value: float, threshold: float) -> bool:
        self.ensure_one()
        op = self.operator
        if op == "gt":
            return value > threshold
        if op == "gte":
            return value >= threshold
        if op == "lt":
            return value < threshold
        if op == "lte":
            return value <= threshold
        if op == "eq":
            return math.isclose(
                value,
                threshold,
                rel_tol=_FLOAT_EQ_REL_TOL,
                abs_tol=_FLOAT_EQ_ABS_TOL,
            )
        if op == "neq":
            return not math.isclose(
                value,
                threshold,
                rel_tol=_FLOAT_EQ_REL_TOL,
                abs_tol=_FLOAT_EQ_ABS_TOL,
            )
        if op == "between":
            if value < threshold:
                return False
            return not (self.threshold_max and value >= self.threshold_max)
        raise ValidationError(
            self.env._(
                "Unknown operator '%(op)s' on approval rule '%(name)s'.",
                op=op,
                name=self.name,
            ),
        )

    def _condition_bounds(self) -> tuple[float, bool, float, bool] | None:
        self.ensure_one()
        t = self.threshold
        if self.operator == "gt":
            return (t, False, math.inf, True)
        if self.operator == "gte":
            return (t, True, math.inf, True)
        if self.operator == "lt":
            return (-math.inf, True, t, False)
        if self.operator == "lte":
            return (-math.inf, True, t, True)
        if self.operator == "eq":
            return (t, True, t, True)
        if self.operator == "between":
            return (t, True, self.threshold_max or math.inf, False)
        return None

    def _condition_overlaps(self, other) -> bool:
        self.ensure_one()
        other.ensure_one()
        bounds_a = self._condition_bounds()
        bounds_b = other._condition_bounds()
        if bounds_a is None or bounds_b is None:
            return True
        return self._intervals_overlap(bounds_a, bounds_b)

    def _get_approver_tuples(self) -> list[tuple[int, bool, int]]:
        self.ensure_one()
        return [
            (user.id, self.approver_required, self.approver_sequence)
            for user in self.approver_ids
        ]
