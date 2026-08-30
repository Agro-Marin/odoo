from odoo.tests.common import tagged, users

from odoo.addons.crm.tests.test_crm_lead_merge import TestLeadMergeCommon


@tagged("lead_manage")
class TestLeadSaleMerge(TestLeadMergeCommon):
    @users("user_sales_manager")
    def test_merge_method_dependencies(self):
        TestLeadMergeCommon.merge_fields.append("order_ids")

        orders = (
            self.env["sale.order"]
            .sudo()
            .create(
                [
                    {
                        "partner_id": self.contact_1.id,
                        "opportunity_id": self.lead_w_partner_company.id,
                    },
                    {
                        "partner_id": self.contact_1.id,
                        "opportunity_id": self.lead_w_partner.id,
                    },
                ]
            )
        )
        self.assertEqual(self.lead_w_partner_company.order_ids, orders[0])
        self.assertEqual(self.lead_w_partner.order_ids, orders[1])

        leads = (
            self.env["crm.lead"]
            .browse(self.leads.ids)
            ._sort_by_confidence_level(reverse=True)
        )
        with self.assertLeadMerged(
            self.lead_w_contact, leads, name=self.lead_w_contact.name, order_ids=orders
        ):
            leads._merge_opportunity(auto_unlink=False, max_length=None)
