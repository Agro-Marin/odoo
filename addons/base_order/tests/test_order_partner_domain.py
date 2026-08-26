from odoo.fields import Command, Domain
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestOrderPartnerDomain(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Category = cls.env["res.partner.category"]
        cls.Partner = cls.env["res.partner"]
        cls.group = cls.env["res.groups"].create({"name": "Reserved Buyers"})
        cls.other_group = cls.env["res.groups"].create({"name": "Other Buyers"})
        cls.user = cls.env["res.users"].create(
            {
                "name": "Domain User",
                "login": "base_order_domain_user",
                "group_ids": [Command.set([cls.env.ref("base.group_user").id])],
            }
        )

    def _reserve(self, name, group, order_type="purchase", parent=None):
        return self.Category.create(
            {
                "name": name,
                "order_type": order_type,
                "parent_id": parent.id if parent else False,
                "group_ids": [Command.set(group.ids)] if group else False,
            }
        )

    def _tag(self, name, category):
        return self.Partner.create(
            {"name": name, "category_id": [Command.set(category.ids)]}
        )

    def _domain(self, model="purchase.order"):
        return self.env[model].with_user(self.user)._domain_partner_id()

    def test_unconfigured_scope_stays_open(self):
        self.assertEqual(self._domain(), Domain.TRUE)
        self.assertEqual(self._domain("sale.order"), Domain.TRUE)

    def test_reserved_scope_without_group_denies(self):
        self._reserve("Reserved", self.group)

        self.assertEqual(self._domain(), Domain.FALSE)

    def test_reserved_scope_with_group_allows_only_that_category(self):
        allowed = self._reserve("Allowed", self.group)
        denied = self._reserve("Denied", self.other_group)
        self.user.group_ids = [Command.link(self.group.id)]
        allowed_vendor = self._tag("Allowed Vendor", allowed)
        denied_vendor = self._tag("Denied Vendor", denied)
        untagged_vendor = self._tag("Untagged Vendor", self.Category)

        reachable = self.Partner.search(self._domain())

        self.assertIn(allowed_vendor, reachable)
        self.assertNotIn(denied_vendor, reachable)
        self.assertNotIn(untagged_vendor, reachable)

    def test_child_categories_are_reachable(self):
        parent = self._reserve("Parent", self.group)
        child = self._reserve("Child", None, parent=parent)
        self.user.group_ids = [Command.link(self.group.id)]

        child_vendor = self._tag("Child Vendor", child)

        self.assertIn(child_vendor, self.Partner.search(self._domain()))

    def test_scopes_do_not_leak_into_each_other(self):
        self._reserve("Purchase Only", self.group, order_type="purchase")

        self.assertEqual(self._domain("sale.order"), Domain.TRUE)
        self.assertEqual(self._domain("purchase.order"), Domain.FALSE)

    def test_unscoped_category_reserves_every_order_type(self):
        self._reserve("Every Scope", self.group, order_type=False)

        self.assertEqual(self._domain("sale.order"), Domain.FALSE)
        self.assertEqual(self._domain("purchase.order"), Domain.FALSE)
