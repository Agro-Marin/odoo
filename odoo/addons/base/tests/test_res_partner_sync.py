from odoo import Command
from odoo.exceptions import AccessError
from odoo.tests.common import TransactionCase, new_test_user, tagged


@tagged("res_partner", "res_partner_sync")
class TestPartnerSyncCharacterization(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Partner = cls.env["res.partner"]
        cls.company_a = cls.env.ref("base.main_company")
        cls.company_b = cls.env["res.company"].create({"name": "Sync Char Co B"})
        cls.user_a = new_test_user(
            cls.env,
            login="sync_char_user_a",
            groups="base.group_user,base.group_partner_manager",
            company_id=cls.company_a.id,
            company_ids=[Command.set([cls.company_a.id])],
        )

    def test_downstream_commercial_sync_is_recursive(self):
        co = self.Partner.create(
            {
                "name": "Recur Co",
                "is_company": True,
                "vat": "V0",
                "company_registry": "REG0",
                "industry_id": self.env["res.partner.industry"]
                .create({"name": "Char Industry 0"})
                .id,
            }
        )
        c1 = self.Partner.create({"name": "c1", "parent_id": co.id})
        c2 = self.Partner.create({"name": "c2", "parent_id": c1.id})
        c3 = self.Partner.create({"name": "c3", "parent_id": c2.id})
        for child in (c1, c2, c3):
            self.assertEqual(child.commercial_partner_id, co)
            self.assertEqual(child.vat, "V0")

        new_industry = self.env["res.partner.industry"].create({"name": "Char Ind 1"})
        co.write(
            {"vat": "V1", "company_registry": "REG1", "industry_id": new_industry.id}
        )

        for child in (c1, c2, c3):
            self.assertEqual(child.vat, "V1", "vat must reach every descendant")
            self.assertEqual(
                child.company_registry, "REG1", "registry must reach every descendant"
            )
            self.assertEqual(
                child.industry_id, new_industry, "industry must reach every descendant"
            )

    def test_upstream_sync_asymmetry(self):
        co = self.Partner.create(
            {
                "name": "Asym Co",
                "is_company": True,
                "vat": "V0",
                "company_registry": "REG0",
            }
        )
        c1 = self.Partner.create({"name": "a1", "parent_id": co.id})
        c2 = self.Partner.create({"name": "a2", "parent_id": c1.id})

        c2.write({"vat": "V_UP"})
        self.assertEqual(co.vat, "V_UP", "vat propagates upstream to commercial entity")
        self.assertEqual(c1.vat, "V_UP", "and back down to siblings/ancestors")
        self.assertEqual(c2.vat, "V_UP")

        c2.write({"company_registry": "REG_LEAF"})
        self.assertEqual(
            co.company_registry, "REG0", "registry does NOT propagate upstream"
        )
        self.assertEqual(c1.company_registry, "REG0", "and siblings are left untouched")
        self.assertEqual(
            c2.company_registry, "REG_LEAF", "the local write on the leaf stands"
        )

    def test_upstream_address_sync_to_parent(self):
        company = self.Partner.create({"name": "Addr Co", "is_company": True})
        contact = self.Partner.create(
            {
                "name": "Addr Contact",
                "parent_id": company.id,
                "type": "contact",
                "street": "First Street",
                "city": "Town",
            }
        )
        self.assertEqual(company.street, "First Street")

        contact.write({"street": "Second Street"})
        self.assertEqual(
            company.street,
            "Second Street",
            "address edit propagates upstream to parent",
        )

    def test_cross_company_hidden_child_is_synced_via_sudo(self):
        co = self.Partner.with_user(self.user_a).create(
            {
                "name": "XCo",
                "is_company": True,
                "vat": "V0",
                "company_id": self.company_a.id,
            }
        )
        hidden_child = (
            self.env["res.partner"]
            .sudo()
            .create(
                {
                    "name": "HiddenChild",
                    "parent_id": co.id,
                    "company_id": self.company_b.id,
                }
            )
        )
        self.assertEqual(hidden_child.vat, "V0")

        self.assertFalse(
            self.env["res.partner"]
            .with_user(self.user_a)
            .search([("id", "=", hidden_child.id)]),
            "company-B child with no user must be invisible to the company-A user",
        )
        with self.assertRaises(AccessError):
            hidden_child.with_user(self.user_a).write({"function": "x"})

        co.with_user(self.user_a).write({"vat": "V1"})

        self.assertEqual(
            hidden_child.sudo().vat,
            "V1",
            "cross-company hidden child must be reached by sudo commercial sync",
        )

    def test_cross_company_visible_child_is_synced(self):
        co = self.Partner.with_user(self.user_a).create(
            {
                "name": "YCo",
                "is_company": True,
                "vat": "V0",
                "company_id": self.company_a.id,
            }
        )
        shared_child = self.Partner.with_user(self.user_a).create(
            {"name": "SharedChild", "parent_id": co.id, "company_id": False}
        )
        self.assertEqual(shared_child.vat, "V0")

        co.with_user(self.user_a).write({"vat": "V1"})
        self.assertEqual(
            shared_child.vat, "V1", "visible child is reached by commercial sync"
        )

    def test_load_import_inherits_from_parent(self):
        industry = self.env["res.partner.industry"].create({"name": "Load Char Ind"})
        fnames = [
            "id",
            "name",
            "is_company",
            "vat",
            "company_registry",
            "street",
            "city",
            "industry_id/.id",
            "parent_id/id",
        ]
        data = [
            [
                "load_char_co",
                "Load Char Co",
                "1",
                "BELOADCHAR",
                "LOADREG",
                "Parent Street",
                "ParentCity",
                str(industry.id),
                "",
            ],
            ["load_char_c1", "Load Char C1", "0", "", "", "", "", "", "load_char_co"],
            ["load_char_c2", "Load Char C2", "0", "", "", "", "", "", "load_char_co"],
        ]
        result = self.Partner.load(fnames, data)
        self.assertFalse(result["messages"], result["messages"])
        co, c1, c2 = self.Partner.browse(result["ids"])
        for child in (c1, c2):
            self.assertEqual(child.commercial_partner_id, co)
            self.assertEqual(child.vat, "BELOADCHAR", "vat inherited on import")
            self.assertEqual(
                child.company_registry, "LOADREG", "registry inherited on import"
            )
            self.assertEqual(
                child.industry_id, industry, "industry inherited on import"
            )
            self.assertEqual(
                child.street, "Parent Street", "address inherited on import"
            )
            self.assertEqual(child.city, "ParentCity")

    def test_load_import_first_contact_populates_empty_company(self):
        fnames = ["id", "name", "is_company", "parent_id/id", "type", "street", "city"]
        data = [
            ["load_char_co2", "Load Char Co2", "1", "", "contact", "", ""],
            [
                "load_char_ct2",
                "Load Char Ct2",
                "0",
                "load_char_co2",
                "contact",
                "Contact Street",
                "ContactCity",
            ],
        ]
        result = self.Partner.load(fnames, data)
        self.assertFalse(result["messages"], result["messages"])
        co2, ct2 = self.Partner.browse(result["ids"])
        self.assertEqual(
            co2.street, "Contact Street", "first contact address copied up on import"
        )
        self.assertEqual(co2.city, "ContactCity")
        self.assertEqual(ct2.street, "Contact Street")
