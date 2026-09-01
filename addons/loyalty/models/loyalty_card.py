from collections import defaultdict
from uuid import uuid4

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError
from odoo.tools import format_amount


class LoyaltyCard(models.Model):
    _name = "loyalty.card"
    _inherit = ["mixin.mail.thread"]
    _description = "Loyalty Coupon"
    _rec_name = "code"

    @api.model
    def _generate_code(self):
        """Barcode identifiable codes."""
        return "044" + str(uuid4())[7:-18]

    @api.depends("program_id", "code")
    def _compute_display_name(self):
        for card in self:
            card.display_name = f"{card.program_id.name}: {card.code}"

    program_id = fields.Many2one(
        comodel_name="loyalty.program",
        # Required: a card with no program has no company, no currency and no point
        # name, and its display name read "False: 044f-d2de-4011".
        required=True,
        ondelete="restrict",
        index="btree_not_null",
        default=lambda self: self.env.context.get("active_id", None),
    )
    program_type = fields.Selection(related="program_id.program_type")
    # TODO probably isn't useful to store this company_id anymore
    company_id = fields.Many2one(
        related="program_id.company_id", store=True, precompute=True
    )
    currency_id = fields.Many2one(related="program_id.currency_id")
    # Reserved for this partner if non-empty
    partner_id = fields.Many2one(comodel_name="res.partner", index=True)
    points = fields.Float(tracking=True)
    point_name = fields.Char(related="program_id.portal_point_name", readonly=True)
    points_display = fields.Char(compute="_compute_points_display")

    code = fields.Char(required=True, default=lambda self: self._generate_code())
    expiration_date = fields.Date()

    use_count = fields.Integer(compute="_compute_use_count")
    active = fields.Boolean(default=True)
    history_ids = fields.One2many(
        comodel_name="loyalty.history",
        inverse_name="card_id",
        readonly=True,
    )

    _card_code_unique = models.Constraint(
        "UNIQUE(code)",
        "A coupon/loyalty card must have a unique code.",
    )

    @api.constrains("code")
    def _check_code(self):
        # Prevent a coupon from sharing its code with a program trigger
        if self.env["loyalty.rule"].search_count(
            [("mode", "=", "with_code"), ("code", "in", self.mapped("code"))], limit=1
        ):
            raise ValidationError(
                _("A trigger with the same code as one of your coupon already exists.")
            )

    @api.constrains("active", "partner_id", "program_id")
    def _check_one_loyalty_card_per_partner(self):
        """A customer's points on a loyalty program belong on a single card.

        `sale_loyalty` resolves a nominative program to its card with a
        `search(..., limit=1)`, so a second active card for the same customer and
        program holds points that nothing can ever spend. `base.partner.merge`
        already drains and archives the extra cards a merge produces; this is what
        stops the state being created in the first place.
        """
        concerned = self.filtered(
            lambda card: (
                card.active and card.partner_id and card.program_type == "loyalty"
            )
        )
        if not concerned:
            return
        # One `_read_group` and not a `search_count` per card: cards are created in
        # batches by `sale_loyalty` and by the Point of Sale, and a per-record query
        # there is the cost `_send_creation_communication` exists to avoid.
        pairs = {(card.partner_id.id, card.program_id.id) for card in concerned}
        for partner, program, _count in self.env["loyalty.card"]._read_group(
            domain=[
                ("active", "=", True),
                ("partner_id", "in", concerned.partner_id.ids),
                ("program_id", "in", concerned.program_id.ids),
            ],
            groupby=["partner_id", "program_id"],
            aggregates=["__count"],
            having=[("__count", ">", 1)],
        ):
            # The domain is a cross product of the two id lists, so it can also
            # group a pair nobody here touched.
            if (partner.id, program.id) in pairs:
                raise ValidationError(
                    _(
                        "%(partner)s already holds a card for %(program)s. A customer"
                        " keeps one loyalty card per program, so that the points are"
                        " all in one place -- archive the old card first.",
                        partner=partner.display_name,
                        program=program.display_name,
                    )
                )

    @api.constrains("expiration_date", "program_id")
    def _check_expiration_date(self):
        # A constraint and not an onchange: the onchange this replaces guarded the
        # form alone, and let `create`/`write`/an import set the date anyway.
        for card in self:
            if card.program_type == "loyalty" and card.expiration_date:
                raise ValidationError(
                    _("Expiration date cannot be set on a loyalty card.")
                )

    @api.depends("points", "point_name")
    def _compute_points_display(self):
        for card in self:
            card.points_display = card._format_points(card.points)

    def _format_points(self, points):
        self.check_singleton()
        if (
            self.program_id.currency_id
            and self.point_name == self.program_id.currency_id.symbol
        ):
            return format_amount(self.env, points, self.program_id.currency_id)
        if points == int(points):
            return f"{int(points)} {self.point_name or ''}"
        return f"{points:.2f} {self.point_name or ''}"

    def _compute_use_count(self):
        """Count the order lines this card has paid for. Zero without a channel.

        Overridden by `sale_loyalty` and `pos_loyalty`, both with a `_read_group`;
        see `loyalty.program._compute_total_order_count` for what that costs.
        """
        self.use_count = 0

    def _get_default_template(self):
        self.check_singleton()
        return self.program_id.communication_plan_ids.filtered(
            lambda m: m.trigger == "create"
        ).mail_template_id[:1]

    def _get_mail_author(self):
        self.check_singleton()
        return (
            (self.env.user._is_internal() and self.env.user)
            or self.company_id
            or self.env.company
        ).partner_id

    def _get_signature(self):
        """To be overridden."""
        self.check_singleton()

    def _has_source_order(self):
        return False

    def action_coupon_send(self):
        """Open the email composer preloaded with `_get_default_template`."""
        self.check_singleton()
        default_template = self._get_default_template()
        compose_form = self.env.ref("mail.email_compose_message_wizard_form", False)
        ctx = {
            "default_model": "loyalty.card",
            "default_res_ids": self.ids,
            "default_template_id": default_template and default_template.id,
            "default_composition_mode": "comment",
            "default_email_layout_xmlid": "mail.mail_notification_light",
            "force_email": True,
        }
        return {
            "name": _("Compose Email"),
            "type": "ir.actions.act_window",
            "view_mode": "form",
            "res_model": "mail.compose.message",
            "views": [(compose_form.id, "form")],
            "view_id": compose_form.id,
            "target": "new",
            "context": ctx,
        }

    def _plans_per_program(self, trigger):
        """Return the communication plans of each program of these coupons.

        :param str trigger: the `loyalty.mail.trigger` to keep
        :rtype: dict[loyalty.program, loyalty.mail]
        """
        return {
            program: program.communication_plan_ids.filtered(
                lambda plan: plan.trigger == trigger
            )
            for program in self.program_id
        }

    def _send_creation_communication(self, force_send=False):
        """Send the 'At Creation' communication plans of the given coupons, if any.

        One `send_mail_batch` per (template, author) rather than one `send_mail` per
        coupon: the coupon-generation wizard's whole purpose is bulk, and a mail per
        coupon measured about seven queries each.
        """
        if self.env.context.get("loyalty_no_mail", False) or self.env.context.get(
            "action_no_send_mail", False
        ):
            return
        # Ideally one plan per program, but multiple is supported
        plans_per_program = self._plans_per_program("create")
        if not any(plans_per_program.values()):
            return
        # `_mail_get_customer` is `check_singleton`; the batch behind it is not.
        customers = self._mail_get_partners()
        coupons_per_sender = defaultdict(list)
        for coupon in self:
            if not plans_per_program[coupon.program_id] or not customers.get(coupon.id):
                continue
            for plan in plans_per_program[coupon.program_id]:
                template = plan.mail_template_id
                # A template with no `email_from` needs an author to be sent at all,
                # and the author falls back to the coupon's own company -- so the
                # coupons are grouped by the author they each resolve to.
                author = (
                    self.env["res.partner"]
                    if template.email_from
                    else coupon._get_mail_author()
                )
                coupons_per_sender[template, author].append(coupon.id)
        for (template, author), coupon_ids in coupons_per_sender.items():
            template.send_mail_batch(
                coupon_ids,
                force_send=force_send,
                email_layout_xmlid="mail.mail_notification_light",
                email_values={
                    "author_id": author.id,
                    "email_from": author.email_formatted,
                }
                if author
                else {},
            )

    def _send_points_reach_communication(self, points_changes):
        """Send the 'When Reaching' communication plans for the given coupons.

        When a coupon passes several milestones, only the highest one reached is sent.
        """
        if self.env.context.get("loyalty_no_mail", False):
            return
        milestones_per_program = {
            program: plans.sorted("points", reverse=True)
            for program, plans in self._plans_per_program("points_reach").items()
        }
        if not any(milestones_per_program.values()):
            return
        customers = self._mail_get_partners()
        coupons_per_milestone = defaultdict(list)
        for coupon in self:
            # Skip cards without milestone, customer or partner, and those that
            # gained no points
            if (
                not milestones_per_program[coupon.program_id]
                or not coupon.partner_id
                or not customers.get(coupon.id)
            ):
                continue
            change = points_changes[coupon]
            if change["old"] >= change["new"]:
                continue
            for milestone in milestones_per_program[coupon.program_id]:
                if change["old"] < milestone.points <= change["new"]:
                    coupons_per_milestone[milestone].append(coupon.id)
                    break
        for milestone, coupon_ids in coupons_per_milestone.items():
            milestone.mail_template_id.send_mail_batch(
                coupon_ids, email_layout_xmlid="mail.mail_notification_light"
            )

    # What `res.partner._compute_count_active_cards` searches on. Changing any of
    # them changes some partner's count.
    _PARTNER_COUNT_FIELDS = frozenset(
        {
            "active",
            "expiration_date",
            "partner_id",
            "points",
            "program_id",
        }
    )

    def _invalidate_partner_card_count(self):
        """Drop the cached `res.partner.loyalty_card_count`.

        The count is a search, so it has no `@api.depends` to declare and nothing
        invalidates it: a card created or spent in a transaction was invisible to
        every later read of the count in that same transaction. Invalidated for the
        whole model rather than for `self.partner_id`, because the count rolls a
        partner's children up into it and the ancestors are not known here.

        The field is not stored, so this drops cache entries and issues no query.
        """
        self.env["res.partner"].invalidate_model(["loyalty_card_count"])

    @api.model_create_multi
    def create(self, vals_list):
        res = super().create(vals_list)
        res._invalidate_partner_card_count()
        res._send_creation_communication()
        return res

    def write(self, vals):
        track_points = (
            not self.env.context.get("loyalty_no_mail", False) and "points" in vals
        )
        if track_points:
            points_before = {coupon: coupon.points for coupon in self}
        res = super().write(vals)
        if not self._PARTNER_COUNT_FIELDS.isdisjoint(vals):
            self._invalidate_partner_card_count()
        if track_points:
            points_changes = {
                coupon: {"old": points_before[coupon], "new": coupon.points}
                for coupon in self
            }
            self._send_points_reach_communication(points_changes)
        return res

    def unlink(self):
        partner_count_affected = bool(self.partner_id)
        res = super().unlink()
        if partner_count_affected:
            self._invalidate_partner_card_count()
        return res

    def action_loyalty_update_balance(self):
        return {
            "name": _("Update Balance"),
            "type": "ir.actions.act_window",
            "view_mode": "form",
            "res_model": "loyalty.card.update.balance",
            "target": "new",
            "context": {
                "default_card_id": self.id,
            },
        }
