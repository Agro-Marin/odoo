# Part of Odoo. See LICENSE file for full copyright and licensing details.


from odoo import api, models


class BasePartnerMergeAutomaticWizard(models.TransientModel):
    _inherit = "base.partner.merge.automatic.wizard"

    @api.model
    def _update_foreign_keys(self, src_partners, dst_partner):
        # Case 1: there is a visitor for both src and dst partners.
        # Need to merge visitors before `super` to avoid SQL partner_id unique
        # constraint to raise as it will change partner_id of the visitor
        # record(s) to the `dst_partner` which already exists.
        dst_visitor = dst_partner.visitor_ids and dst_partner.visitor_ids[0]
        if dst_visitor:
            for visitor in src_partners.visitor_ids:
                visitor._merge_visitor(dst_visitor)

        super()._update_foreign_keys(src_partners, dst_partner)

        # Case 2: there is a visitor only for src_partners.
        # Need to fix the "de-sync" values between `access_token` and
        # `partner_id`.
        # Compare as text, not `access_token::int`: a still-desynced row can
        # hold a 32-char hex token (the exact case this repairs), and casting
        # that to int raises `invalid input syntax for integer`, aborting the
        # whole merge. Text comparison catches the hex desync too.
        self.env.cr.execute(
            """
            UPDATE website_visitor
               SET access_token = partner_id::text
             WHERE partner_id::text != access_token
               AND partner_id = %s;
        """,
            (dst_partner.id,),
        )
