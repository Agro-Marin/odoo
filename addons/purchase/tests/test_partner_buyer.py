from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestPartnerBuyerInheritance(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.buyer = cls.env["res.users"].create(
            {
                "name": "Buyer B",
                "login": "test_buyer_b",
                "group_ids": [
                    (4, cls.env.ref("base.group_user").id),
                    (4, cls.env.ref("purchase.group_purchase_user").id),
                ],
            },
        )
        cls.other_buyer = cls.env["res.users"].create(
            {"name": "Buyer C", "login": "test_buyer_c"},
        )
        cls.company_partner = cls.env["res.partner"].create(
            {
                "name": "Vendor Co",
                "is_company": True,
                "user_purchase_id": cls.buyer.id,
            },
        )

    def _contact(self, **kw):
        vals = {"name": "Contact", "parent_id": self.company_partner.id}
        vals.update(kw)
        return self.env["res.partner"].create(vals)

    def test_contact_inherits_the_company_buyer(self):
        self.assertEqual(self._contact().user_purchase_id, self.buyer)

    def test_contact_keeps_its_own_buyer(self):
        contact = self._contact(user_purchase_id=self.other_buyer.id)
        self.assertEqual(contact.user_purchase_id, self.other_buyer)

    def test_a_company_does_not_inherit(self):
        subsidiary = self._contact(name="Subsidiary", is_company=True)
        self.assertFalse(subsidiary.user_purchase_id)

    def test_inheritance_cascades_down_the_tree(self):
        contact = self._contact()
        grandchild = self._contact(name="Grandchild", parent_id=contact.id)
        self.assertEqual(grandchild.user_purchase_id, self.buyer)

    def test_reparenting_pulls_the_new_parents_buyer(self):
        orphan = self.env["res.partner"].create({"name": "Orphan"})
        self.assertFalse(orphan.user_purchase_id)

        orphan.parent_id = self.company_partner
        self.assertEqual(orphan.user_purchase_id, self.buyer)

    def test_buyer_is_tracked_like_the_salesperson(self):
        fields_ = self.env["res.partner"]._fields
        self.assertTrue(
            fields_["user_purchase_id"].tracking,
            "the buyer should be tracked, as the salesperson is",
        )
        self.assertTrue(fields_["user_id"].tracking, "guards the premise above")

    def test_raw_field_read_now_resolves_for_a_contact(self):
        contact = self._contact()
        automated = self.env["purchase.order"].create(
            {"partner_id": contact.id, "user_id": contact.user_purchase_id.id},
        )
        manual = self.env["purchase.order"].create({"partner_id": contact.id})

        self.assertEqual(automated.user_id, self.buyer)
        self.assertEqual(manual.user_id, self.buyer)
        self.assertEqual(
            self.env["purchase.order"].search_count(
                [
                    ("partner_id", "=", contact.id),
                    ("state", "=", "draft"),
                    ("user_id", "=", contact.user_purchase_id.id),
                ],
            ),
            2,
            "the rule's merge domain should now find the manual draft too",
        )
