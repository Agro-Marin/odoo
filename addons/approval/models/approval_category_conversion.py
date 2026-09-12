from odoo import api, fields, models
from odoo.exceptions import UserError
from odoo.fields import Command

from . import approval_trace as trace

_BASE_SEQUENCE = 10

_COMPLEMENT = {
    "gt": "lte",
    "gte": "lt",
    "lt": "gte",
    "lte": "gt",
    "eq": "neq",
    "neq": "eq",
}


class ApprovalCategoryConversion(models.Model):
    """A flat category's routing rewritten as steps that route every request the same.

    What "the same" means is the routing contract in tests/test_routing_outcomes.py:
    the state, who could approve and who is asked, after every decision. The flat
    path counts approvals across all of a request's rows, so each translation keeps
    that count in one pool step, and gives every required approver a step of their
    own beside it. A configuration whose outcome steps cannot reproduce exactly is
    refused with its reason rather than approximated.
    """

    _inherit = "approval.category"

    steps_conversion_blockers = fields.Text(
        string="Why It Cannot Convert",
        compute="_compute_steps_conversion_blockers",
        help="What keeps this category's approvers and routing rules from being "
        "rewritten as steps that route every request the same. Empty when it can.",
    )

    @api.depends_context("lang")
    @api.depends(
        "step_ids",
        "approve_sequentially",
        "group_approval",
        "notify_pool_members",
        "company_id",
        "rule_ids.active",
        "rule_ids.action_type",
        "rule_ids.condition_type",
        "rule_ids.condition_field",
        "rule_ids.operator",
        "rule_ids.approver_required",
        "rule_ids.company_id",
        "rule_ids.currency_id",
    )
    def _compute_steps_conversion_blockers(self) -> None:
        for category in self:
            blockers = category._get_steps_conversion_blockers()
            category.steps_conversion_blockers = "\n".join(
                f"- {reason}" for reason in blockers
            )

    def _get_steps_conversion_blockers(self) -> list[str]:
        self.check_singleton()
        blockers = []
        rules = self._get_routing_rules()
        added = rules.filtered(lambda rule: rule.action_type == "add_approver")
        bands = rules.filtered(lambda rule: rule.action_type == "set_approvers")
        if self.step_ids:
            blockers.append(self.env._("The category already routes by steps."))
        if any(rules.mapped("company_id")) and any(
            rule.company_id != self.company_id for rule in rules
        ):
            blockers.append(
                self.env._(
                    "A routing rule is scoped to another company than the category; "
                    "steps take the category's company."
                )
            )
        if rules.filtered(lambda rule: rule.condition_type != "threshold"):
            blockers.append(
                self.env._(
                    "A routing rule reads the source document; its complement cannot "
                    "be expressed for requests that have none."
                )
            )
        if added.filtered(lambda rule: not rule.approver_required):
            blockers.append(
                self.env._("A rule adds optional approvers, which no step can pool.")
            )
        if len(added) > 1 and not self._are_rules_tiers(added):
            blockers.append(
                self.env._(
                    "Several rules add approvers, and they are not tiers: rules that "
                    "all compare the same figure, in the same currency, with "
                    "'greater than or equal'."
                )
            )
        if len(bands) > 1 and not self._are_rules_ranges(bands):
            blockers.append(
                self.env._(
                    "Several bands replace the approvers, and they are not ranges of "
                    "one figure: bands that compare the same figure, in the same "
                    "currency, with 'between', 'greater than or equal' or 'less than'."
                )
            )
        if added and bands:
            blockers.append(
                self.env._("A category both adds and replaces approvers by rule.")
            )
        if self.approve_sequentially and rules:
            blockers.append(self.env._("Sequential approvers with routing rules."))
        if self.group_approval == "exclusive":
            if added:
                blockers.append(
                    self.env._(
                        "A security group category counts rule approvers into the "
                        "group's quorum, which a group step cannot."
                    )
                )
            if self.notify_pool_members:
                blockers.append(
                    self.env._(
                        "A group step asks none of its members; this category asks "
                        "every member."
                    )
                )
            if self.approve_sequentially:
                blockers.append(self.env._("A security group has no order."))
        return blockers

    def _get_routing_rules(self):
        self.check_singleton()
        return self.rule_ids.filtered(
            lambda rule: (
                rule.active and rule.action_type in ("add_approver", "set_approvers")
            )
        )

    def _prepare_steps_from_flat_routing(self) -> list[dict]:
        self.check_singleton()
        if self.group_approval == "exclusive":
            return [
                self._prepare_conversion_step(
                    self.env._("Group"),
                    self.env["res.users"],
                    self.approval_minimum,
                    group_id=self.approver_group_id.id,
                )
            ]
        listed = [
            (approver.user_id, approver.required)
            for approver in self.approver_ids.sorted(lambda a: (a.sequence, a.id))
        ]
        if self.approve_sequentially:
            return [self._prepare_in_order_step(listed)]
        rules = self._get_routing_rules()
        band = rules.filtered(lambda rule: rule.action_type == "set_approvers")
        added = rules.filtered(lambda rule: rule.action_type == "add_approver")
        if band and self._are_rules_ranges(band):
            return self._prepare_ranged_band_steps(listed, band)
        if band:
            return self._prepare_pooled_steps(
                listed, self.approval_minimum, self._complement_condition(band)
            ) + self._prepare_pooled_steps(
                [(user, band.approver_required) for user in band.approver_ids],
                band.approval_minimum,
                self._rule_condition(band),
            )
        if len(added) > 1:
            return self._prepare_tiered_steps(listed, added)
        if added:
            with_rule = listed + [(user, True) for user in added.approver_ids]
            return self._prepare_pooled_steps(
                listed, self.approval_minimum, self._complement_condition(added)
            ) + self._prepare_pooled_steps(
                with_rule, self.approval_minimum, self._rule_condition(added)
            )
        return self._prepare_pooled_steps(listed, self.approval_minimum, {})

    @staticmethod
    def _are_rules_tiers(rules) -> bool:
        return (
            len(set(rules.mapped("condition_field"))) == 1
            and set(rules.mapped("operator")) == {"gte"}
            and len(rules.currency_id) <= 1
        )

    @staticmethod
    def _are_rules_ranges(rules) -> bool:
        return (
            len(set(rules.mapped("condition_field"))) == 1
            and set(rules.mapped("operator")) <= {"between", "gte", "lt"}
            and len(rules.currency_id) <= 1
        )

    @staticmethod
    def _rule_interval(rule) -> tuple[float, float]:
        infinity = float("inf")
        if rule.operator == "lt":
            return (-infinity, rule.threshold)
        if rule.operator == "between" and rule.threshold_max:
            return (rule.threshold, rule.threshold_max)
        return (rule.threshold, infinity)

    @staticmethod
    def _interval_condition(low: float, high: float) -> dict:
        infinity = float("inf")
        if low == -infinity:
            return {"operator": "lt", "threshold": high, "threshold_max": 0}
        if high == infinity:
            return {"operator": "gte", "threshold": low, "threshold_max": 0}
        return {"operator": "between", "threshold": low, "threshold_max": high}

    def _prepare_ranged_band_steps(self, listed, bands) -> list[dict]:
        """Each band's approvers over its own range; the category's own approvers over
        every range no band covers. Bands of one figure cannot overlap (the rule's
        constraint), so the ranges and the gaps between them never do either."""
        infinity = float("inf")
        first = bands[0]
        base = {
            "condition_field": first.condition_field,
            "currency_id": first.currency_id.id,
        }
        steps = []
        cursor = -infinity
        for band in bands.sorted(lambda rule: (self._rule_interval(rule), rule.id)):
            low, high = self._rule_interval(band)
            if cursor < low:
                steps += self._prepare_pooled_steps(
                    listed,
                    self.approval_minimum,
                    {**base, **self._interval_condition(cursor, low)},
                )
            steps += self._prepare_pooled_steps(
                [(user, band.approver_required) for user in band.approver_ids],
                band.approval_minimum,
                {**base, **self._interval_condition(low, high)},
            )
            cursor = high
        if cursor < infinity:
            steps += self._prepare_pooled_steps(
                listed,
                self.approval_minimum,
                {**base, **self._interval_condition(cursor, infinity)},
            )
        return steps

    def _prepare_tiered_steps(self, listed, added) -> list[dict]:
        """One pool per range of the figure, listing the approvers of every rule the
        range matches: the flat path counts their approvals toward the minimum."""
        tiers = added.sorted(lambda rule: (rule.threshold, rule.id))
        thresholds = sorted(set(tiers.mapped("threshold")))
        first = tiers[0]
        base = {
            "condition_field": first.condition_field,
            "currency_id": first.currency_id.id,
        }
        steps = self._prepare_pooled_steps(
            listed,
            self.approval_minimum,
            {**base, "operator": "lt", "threshold": thresholds[0], "threshold_max": 0},
        )
        for index, low in enumerate(thresholds):
            high = thresholds[index + 1] if index + 1 < len(thresholds) else 0
            matched = tiers.filtered(lambda rule, low=low: rule.threshold <= low)
            approvers = listed + [(user, True) for user in matched.approver_ids]
            steps += self._prepare_pooled_steps(
                approvers,
                self.approval_minimum,
                {
                    **base,
                    "operator": "between",
                    "threshold": low,
                    "threshold_max": high,
                },
            )
        return steps

    def _get_conversion_pool_source(self) -> dict:
        """Step values naming approvers every request of the category adds to its pool
        beyond the listed ones (an approver path, typically on the request itself)."""
        return {}

    def _get_conversion_required_sources(self) -> list[tuple[str, dict]]:
        """(name, step values) for each required approver a request adds beyond the
        listed ones, named by a path rather than a user."""
        return []

    def _prepare_pooled_steps(self, approvers, minimum, condition) -> list[dict]:
        users = self.env["res.users"]
        required = self.env["res.users"]
        for user, is_required in approvers:
            users |= user
            if is_required:
                required |= user
        steps = [
            self._prepare_conversion_step(
                self.env._("Required: %s", user.name), user, 1, **condition
            )
            for user in required
        ]
        steps += [
            self._prepare_conversion_step(
                name, self.env["res.users"], 1, **condition, **source
            )
            for name, source in self._get_conversion_required_sources()
        ]
        pool_source = self._get_conversion_pool_source()
        if (users or pool_source) and minimum > 0:
            steps.append(
                self._prepare_conversion_step(
                    self.env._("Approvers"), users, minimum, **condition, **pool_source
                )
            )
        return steps

    def _prepare_in_order_step(self, approvers) -> dict:
        last_required = max(
            (
                position
                for position, (_user, required) in enumerate(approvers, start=1)
                if required
            ),
            default=0,
        )
        users = self.env["res.users"]
        for user, _required in approvers:
            users |= user
        return self._prepare_conversion_step(
            self.env._("In order"),
            users,
            max(self.approval_minimum, last_required),
            in_order=True,
        )

    def _prepare_conversion_step(self, name, users, minimum, **vals) -> dict:
        return {
            "name": name,
            "sequence": _BASE_SEQUENCE,
            "minimum": minimum,
            "member_ids": [
                Command.create({"user_id": user.id, "sequence": 10 * position})
                for position, user in enumerate(users, start=1)
            ],
            **vals,
        }

    @staticmethod
    def _rule_condition(rule) -> dict:
        return {
            "condition_field": rule.condition_field,
            "operator": rule.operator,
            "threshold": rule.threshold,
            "threshold_max": rule.threshold_max,
            "currency_id": rule.currency_id.id,
        }

    @staticmethod
    def _complement_condition(rule) -> dict:
        operator = "lt" if rule.operator == "between" else _COMPLEMENT[rule.operator]
        return {
            "condition_field": rule.condition_field,
            "operator": operator,
            "threshold": rule.threshold,
            "threshold_max": 0,
            "currency_id": rule.currency_id.id,
        }

    def action_convert_routing_to_steps(self) -> None:
        for category in self:
            blockers = category._get_steps_conversion_blockers()
            if blockers:
                trace.REFUSAL.event(
                    "steps_conversion_blocked",
                    category=category.id,
                    blockers=len(blockers),
                )
                raise UserError(
                    self.env._(
                        "%(category)s cannot be converted to steps without changing "
                        "how its requests are routed:\n%(reasons)s",
                        category=category.display_name,
                        reasons="\n".join(f"- {reason}" for reason in blockers),
                    )
                )
            steps = category._prepare_steps_from_flat_routing()
            rules = category._get_routing_rules()
            trace.STEPS.note(
                "converted_from_flat",
                category=category.id,
                steps=len(steps),
                archived_rules=rules.ids,
                sequential=category.approve_sequentially,
                group=category.group_approval == "exclusive",
            )
            rules.write({"active": False})
            category.write(
                {
                    "approve_sequentially": False,
                    "step_ids": [Command.create(vals) for vals in steps],
                }
            )
