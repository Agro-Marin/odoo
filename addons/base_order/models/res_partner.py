from odoo import models
from odoo.fields import Domain


class ResPartner(models.Model):
    _inherit = "res.partner"

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
