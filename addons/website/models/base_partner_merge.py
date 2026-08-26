
from odoo import api, models


class BasePartnerMergeAutomaticWizard(models.TransientModel):
    _inherit = "base.partner.merge.automatic.wizard"

    @api.model
    def _update_foreign_keys(self, src_partners, dst_partner):
        dst_visitor = dst_partner.visitor_ids and dst_partner.visitor_ids[0]
        if dst_visitor:
            for visitor in src_partners.visitor_ids:
                visitor._merge_visitor(dst_visitor)

        super()._update_foreign_keys(src_partners, dst_partner)

        self.env.cr.execute(
            """
            UPDATE website_visitor
               SET access_token = partner_id::text
             WHERE partner_id::text != access_token
               AND partner_id = %s;
        """,
            (dst_partner.id,),
        )
