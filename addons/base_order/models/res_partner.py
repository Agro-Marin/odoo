from odoo import api, fields, models
from odoo.fields import Domain

_DAYS_NO_ORDER_SENTINEL = 9999


class ResPartner(models.Model):
    _inherit = "res.partner"

    recent_orders_count = fields.Integer(
        string="Recent Orders",
        compute="_compute_recent_orders_count",
        help="Number of orders this partner placed within the order cycle "
        "configured on the company.",
    )
    days_since_last_order = fields.Integer(
        string="Days Since Last Order",
        compute="_compute_days_since_last_order",
        help="Number of days since this partner's last order.",
    )

    def _compute_order_count(self, order_model, count_field, group, domain=None):
        self[count_field] = 0
        if not self.env.user.has_group(group):
            return

        all_partners = self.with_context(active_test=False).search_fetch(
            [("id", "child_of", self.ids)],
            ["parent_id"],
        )
        order_groups = self.env[order_model]._read_group(
            domain=Domain.AND(
                [
                    domain or [],
                    [("partner_id", "in", all_partners.ids)],
                ],
            ),
            groupby=["partner_id"],
            aggregates=["__count"],
        )
        self_ids = set(self._ids)

        for partner, count in order_groups:
            while partner:
                if partner.id in self_ids:
                    partner[count_field] += count
                partner = partner.parent_id

    def _add_order_statistics(
        self,
        data_list,
        count_field,
        group,
        icon_class,
        label,
        tag_class,
    ):
        if not self.env.user.has_group(group):
            return data_list
        for partner in self.filtered(count_field):
            data_list[partner.id].append(
                {
                    "iconClass": icon_class,
                    "value": partner[count_field],
                    "label": label,
                    "tagClass": tag_class,
                },
            )
        return data_list

    @api.model
    def _get_order_activity_sources(self):
        return []

    def _get_order_activity_partners(self):
        return self

    def _get_domain_order_activity_scope(self):
        # The query runs sudoed so the figure is a property of the customer and
        # not of whoever opened the form: sale_order_personal_rule would
        # otherwise hand two salespeople two different counts for the same
        # customer, and hand the merge cron whatever its own user happens to
        # see. Sudo drops the multi-company rule with the rest, so the scope
        # the cycle is read from has to be restated here.
        return [("company_id", "=", self.env.company.id)]

    def _get_readable_order_activity_sources(self, sources):
        # res.partner is readable by every internal user, these two fields are
        # not group-gated, and sale.order is not readable below
        # group_sale_salesman -- so an ungated _read_group turns any full read
        # of a partner into an AccessError for, say, an HR-only user.
        return [
            (order_model, domain)
            for order_model, domain in sources
            if self.env[order_model].has_access("read")
        ]

    @api.depends_context("company", "uid")
    def _compute_recent_orders_count(self):
        self.recent_orders_count = 0
        partners = self._get_order_activity_partners()
        sources = self._get_readable_order_activity_sources(
            self._get_order_activity_sources(),
        )
        if not partners or not sources:
            return

        cutoff_date = self.env.company._get_order_cycle_cutoff_date()
        counts = {}
        # One query per registered order model, not per partner: the loop is
        # over the source list, whose length is the number of installed order
        # types. Each source carries its own model and domain, so one merged
        # query cannot express it.
        for order_model, domain in sources:
            order_groups = self.env[order_model].sudo()._read_group(  # pylint: disable=n-plus-one-query
                domain=Domain.AND(
                    [
                        domain,
                        self._get_domain_order_activity_scope(),
                        [
                            ("partner_id", "in", partners.ids),
                            ("date_order", ">=", cutoff_date),
                        ],
                    ],
                ),
                groupby=["partner_id"],
                aggregates=["__count"],
            )
            # Keyed by id, and assigned below on records of self: the groups
            # come back in the sudoed environment, whose cache key is not this
            # one, so writing the field on them lands in the wrong partition.
            for partner, count in order_groups:
                counts[partner.id] = counts.get(partner.id, 0) + count

        for partner in partners:
            partner.recent_orders_count = counts.get(partner.id, 0)

    @api.depends_context("company", "uid")
    def _compute_days_since_last_order(self):
        self.days_since_last_order = 0
        partners = self._get_order_activity_partners()
        sources = self._get_readable_order_activity_sources(
            self._get_order_activity_sources(),
        )
        if not partners or not sources:
            return

        last_dates = {}
        # One query per registered order model -- see _compute_recent_orders_count.
        for order_model, domain in sources:
            order_groups = self.env[order_model].sudo()._read_group(  # pylint: disable=n-plus-one-query
                domain=Domain.AND(
                    [
                        domain,
                        self._get_domain_order_activity_scope(),
                        [("partner_id", "in", partners.ids)],
                    ],
                ),
                groupby=["partner_id"],
                aggregates=["date_order:max"],
            )
            for partner, last_date in order_groups:
                previous = last_dates.get(partner.id)
                if previous is None or last_date > previous:
                    last_dates[partner.id] = last_date

        today = fields.Date.today()
        for partner in partners:
            last_date = last_dates.get(partner.id)
            partner.days_since_last_order = (
                (today - last_date.date()).days
                if last_date
                else _DAYS_NO_ORDER_SENTINEL
            )
