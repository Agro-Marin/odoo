from odoo import fields, models


class ResPartner(models.Model):
    _inherit = 'res.partner'

    loyalty_card_count = fields.Integer(
        string="Active loyalty cards",
        compute='_compute_count_active_cards',
        compute_sudo=True,
        groups='base.group_user')

    def _compute_count_active_cards(self):
        """Count each partner's usable cards, those of its children included.

        Not invalidated by anything: the count is a search, so it has no
        `@api.depends` to declare. A card created or spent in the same transaction
        is only reflected after `invalidate_recordset(['loyalty_card_count'])`.
        """
        loyalty_groups = self.env['loyalty.card']._read_group(
            domain=[
                '|', ('company_id', '=', False), ('company_id', 'in', self.env.companies.ids),
                ('partner_id', 'in', self.with_context(active_test=False)._search([('id', 'child_of', self.ids)])),
                ('points', '>', 0),
                ('program_id.active', '=', True),
                '|',
                    ('expiration_date', '>=', fields.Date.context_today(self)),
                    ('expiration_date', '=', False),
            ],
            groupby=['partner_id'],
            aggregates=['__count'],
        )
        self.loyalty_card_count = 0
        counted = {partner.id: partner for partner in self}
        for partner, count in loyalty_groups:
            # A card of a child company/contact counts for every ancestor asked about.
            while partner:
                ancestor = counted.get(partner.id)
                if ancestor is not None:
                    ancestor.loyalty_card_count += count
                partner = partner.parent_id

    def action_view_loyalty_cards(self):
        """Open the cards of these partners and of their children."""
        action = self.env['ir.actions.act_window']._get_action_dict_by_xml_id('loyalty.loyalty_card_action')
        all_child = self.with_context(active_test=False).search([('id', 'child_of', self.ids)])
        action['domain'] = [('partner_id', 'in', all_child.ids)]
        action['context'] = {'search_default_active': True, 'create': False}
        return action
