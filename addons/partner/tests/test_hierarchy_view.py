"""Tests for the res.partner hierarchy view."""

from lxml import etree

from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestPartnerHierarchyView(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Partner = cls.env["res.partner"]
        cls.view = cls.env.ref("partner.res_partner_view_hierarchy")

    def _arch(self):
        return etree.fromstring(
            self.Partner.get_view(self.view.id, "hierarchy")["arch"]
        )

    def test_action_offers_the_hierarchy_view(self):
        """The Contacts action lets the user switch to the hierarchy view."""
        action = self.env.ref("partner.action_partner")
        self.assertIn("hierarchy", action.view_mode.split(","))

    def test_view_walks_the_parent_child_tree(self):
        """The view navigates res.partner through parent_id and child_ids."""
        arch = self._arch()
        self.assertEqual(arch.tag, "hierarchy")
        self.assertEqual(arch.get("child_field"), "child_ids")
        self.assertEqual(arch.xpath("//templates/t/@t-name"), ["hierarchy-box"])

    def test_arch_only_uses_attributes_our_validator_accepts(self):
        """The arch validates here, without upstream's avatar_field or label.

        Both attributes come from the web_hierarchy half of the upstream commit,
        which our fork does not have: `_check_view_tag_hierarchy` rejects any
        attribute outside HIERARCHY_VALID_ATTRIBUTES.
        """
        arch = self._arch()
        self.assertNotIn("avatar_field", arch.attrib)
        self.assertNotIn("label", arch.attrib)
        # raises ValidationError if the arch uses an unknown attribute
        self.env["ir.ui.view"]._check_view_tag_hierarchy(arch, None, {"validate": True})

    def test_hierarchy_read_returns_a_company_with_its_contacts(self):
        """Reading one company through the view's child_field brings its contacts."""
        company = self.Partner.create({"name": "Hierarchy Co", "is_company": True})
        children = self.Partner.create(
            [
                {"name": "Hierarchy Contact 1", "parent_id": company.id},
                {"name": "Hierarchy Contact 2", "parent_id": company.id},
            ]
        )
        rows = self.Partner.hierarchy_read(
            [("id", "=", company.id)],
            {"name": {}, "child_ids": {}},
            "parent_id",
            "child_ids",
        )
        by_id = {row["id"]: row for row in rows}
        # the company comes back with its subtree, not alone
        self.assertEqual(sorted(by_id), sorted([company.id, *children.ids]))
        self.assertEqual(sorted(by_id[company.id]["child_ids"]), sorted(children.ids))
