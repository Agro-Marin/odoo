from odoo import models
from odoo.fields import Domain


class ResPartner(models.Model):
    """Partner-side helpers shared by the order types.

    sale and purchase each hang an order count and an application-statistics
    tile off ``res.partner``. Neither piece is order-type specific beyond the
    model, the field and the group, so both live here and the concrete modules
    supply those three.
    """

    _inherit = "res.partner"

    def _compute_order_count(self, order_model, count_field, group, domain=None):
        """Fill ``count_field`` with this partner's order count.

        Orders booked on a *child* contact count towards every ancestor present
        in ``self``, which is why the totals are accumulated by climbing
        ``parent_id`` instead of being read straight off the group-by.

        The count is left at 0 for users outside ``group`` rather than being
        computed and hidden: the field is group-restricted, and computing it
        would query orders the user cannot read anyway.

        :param str order_model: model to count (``sale.order``, ``purchase.order``)
        :param str count_field: Integer field on ``res.partner`` to fill
        :param str group: group the user must hold for a non-zero count
        :param domain: extra domain restricting which orders are counted
        """
        self[count_field] = 0
        if not self.env.user.has_group(group):
            return

        # retrieve all children partners and prefetch 'parent_id' on them
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
        """Append one order-count tile to the partner's application statistics.

        Callers pass their own already-translated ``label`` so the term is
        extracted in the module that owns it.
        """
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
