from unittest.mock import patch

from odoo.exceptions import ValidationError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install")
class TestPartnerIdentifier(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Type = cls.env["res.partner.identifier.type"]
        cls.Identifier = cls.env["res.partner.identifier"]
        cls.Partner = cls.env["res.partner"]
        cls.mexico = cls.env.ref("base.mx")
        cls.rfc = cls.Type.create(
            {
                "name": "Kernel Test RFC",
                "code": "TEST_RFC",
                "country_ids": [(6, 0, cls.mexico.ids)],
                "pattern": r"[A-Z&Ñ]{3,4}[0-9]{6}[A-Z0-9]{3}",
                "synced_with_commercial": True,
            }
        )
        cls.curp = cls.Type.create(
            {
                "name": "Kernel Test CURP",
                "code": "TEST_CURP",
                "pattern": r"[A-Z]{4}[0-9]{6}[HM][A-Z]{5}[A-Z0-9]{2}",
            }
        )
        cls.company = cls.Partner.create(
            {
                "name": "Vantage SA de CV",
                "is_company": True,
                "country_id": cls.mexico.id,
            }
        )

    def test_punctuation_and_case_do_not_change_the_identifier(self):
        """The typed form is kept; comparison uses the normalized one."""
        self.company._update_identifier("TEST_RFC", "van-850101-qw1")

        identifier = self.company.identifier_ids
        self.assertEqual(identifier.value, "van-850101-qw1")
        self.assertEqual(identifier.normalized_value, "VAN850101QW1")

    def test_a_value_another_contact_holds_is_refused(self):
        """Spelling it differently must not get past the uniqueness rule."""
        self.company._update_identifier("TEST_RFC", "VAN-850101-QW1")
        impostor = self.Partner.create({"name": "Impostor SA", "is_company": True})

        with self.assertRaises(ValidationError):
            with self.cr.savepoint():
                impostor._update_identifier("TEST_RFC", "van850101qw1")

    def test_a_contacts_own_address_may_share_its_identifier(self):
        """One commercial entity is one holder, however many addresses it has."""
        self.company._update_identifier("TEST_RFC", "VAN850101QW1")
        address = self.Partner.create(
            {
                "name": "Vantage Warehouse",
                "parent_id": self.company.id,
                "type": "delivery",
            }
        )

        address._update_identifier("TEST_RFC", "VAN850101QW1")

        self.assertEqual(address._get_identifier("TEST_RFC"), "VAN850101QW1")

    def test_a_malformed_value_is_refused_by_the_types_own_format(self):
        with self.assertRaises(ValidationError):
            with self.cr.savepoint():
                self.company._update_identifier("TEST_CURP", "not-a-curp")

    def test_one_value_per_type_unless_the_type_allows_several(self):
        self.company._update_identifier("TEST_RFC", "VAN850101QW1")

        with self.assertRaises(ValidationError):
            with self.cr.savepoint():
                self.Identifier.create(
                    {
                        "partner_id": self.company.id,
                        "type_id": self.rfc.id,
                        "value": "ABC850101XY9",
                    }
                )

        self.rfc.multiple_per_contact = True
        second = self.Identifier.create(
            {
                "partner_id": self.company.id,
                "type_id": self.rfc.id,
                "value": "ABC850101XY9",
            }
        )
        self.assertIn(second, self.company.identifier_ids)

    def test_setting_a_value_twice_replaces_it(self):
        self.company._update_identifier("TEST_RFC", "VAN850101QW1")
        self.company._update_identifier("TEST_RFC", "ABC850101XY9")

        self.assertEqual(len(self.company.identifier_ids), 1)
        self.assertEqual(self.company._get_identifier("TEST_RFC"), "ABC850101XY9")

    def test_setting_an_empty_value_clears_it(self):
        self.company._update_identifier("TEST_RFC", "VAN850101QW1")

        self.company._update_identifier("TEST_RFC", False)

        self.assertFalse(self.company.identifier_ids)
        self.assertFalse(self.company._get_identifier("TEST_RFC"))

    def test_each_type_decides_whether_it_follows_the_commercial_entity(self):
        """The whole point of a per-type flag.

        `_synced_commercial_fields` is one list of column names for every
        contact, so it cannot say "a tax ID belongs to the company, a national
        number belongs to the person". This can.
        """
        self.company._update_identifier("TEST_RFC", "VAN850101QW1")
        person = self.Partner.create(
            {"name": "Nadia Okonkwo", "parent_id": self.company.id}
        )
        person._update_identifier("TEST_CURP", "OKON850101HDFXYZ01")

        person._commercial_sync_identifiers()

        self.assertEqual(person._get_identifier("TEST_RFC"), "VAN850101QW1")
        self.assertEqual(person._get_identifier("TEST_CURP"), "OKON850101HDFXYZ01")
        self.assertFalse(
            self.company._get_identifier("TEST_CURP"),
            "a personal identifier must not travel up to the company",
        )

    def test_a_synced_type_is_readable_from_a_child_without_being_copied(self):
        """Reading falls back to the commercial entity, so no copy is needed."""
        self.company._update_identifier("TEST_RFC", "VAN850101QW1")
        address = self.Partner.create(
            {"name": "Vantage Depot", "parent_id": self.company.id, "type": "delivery"}
        )

        self.assertEqual(address._get_identifier("TEST_RFC"), "VAN850101QW1")
        self.assertFalse(address.identifier_ids)

    def test_an_unsynced_type_does_not_fall_back(self):
        self.company._update_identifier("TEST_CURP", "OKON850101HDFXYZ01")
        child = self.Partner.create({"name": "Child", "parent_id": self.company.id})

        self.assertFalse(child._get_identifier("TEST_CURP"))

    def test_a_collision_inside_one_batch_is_caught(self):
        """The constraints query once for the whole recordset, not per row.

        Hoisting the search out of the loop is what makes an import of many
        contacts affordable, and it is also what makes this case work: two
        colliding rows created in the same call are both in the recordset, so
        neither is on disk yet when the other is checked.
        """
        rival = self.Partner.create({"name": "Rival SA", "is_company": True})

        with self.assertRaises(ValidationError):
            with self.cr.savepoint():
                self.Identifier.create(
                    [
                        {
                            "partner_id": self.company.id,
                            "type_id": self.rfc.id,
                            "value": "VAN850101QW1",
                        },
                        {
                            "partner_id": rival.id,
                            "type_id": self.rfc.id,
                            "value": "van-850101-qw1",
                        },
                    ]
                )

    def test_unrelated_identifiers_in_one_batch_are_all_accepted(self):
        """The batch path must not reject what is merely adjacent."""
        rival = self.Partner.create({"name": "Rival SA", "is_company": True})

        created = self.Identifier.create(
            [
                {
                    "partner_id": self.company.id,
                    "type_id": self.rfc.id,
                    "value": "VAN850101QW1",
                },
                {
                    "partner_id": rival.id,
                    "type_id": self.rfc.id,
                    "value": "RIV850101ZZ9",
                },
            ]
        )

        self.assertEqual(len(created), 2)

    def test_two_types_cannot_share_a_code(self):
        with self.assertRaises(Exception):
            with self.cr.savepoint():
                self.Type.create({"name": "Kernel Test RFC Twin", "code": "TEST_RFC"})

    def test_a_format_that_is_not_a_regular_expression_is_refused(self):
        with self.assertRaises(ValidationError):
            with self.cr.savepoint():
                self.Type.create(
                    {"name": "Broken", "code": "TEST_BROKEN", "pattern": "([A-Z"}
                )

    def test_a_code_specific_rule_runs_after_the_format(self):
        """`_validate_code_<code>` is the extension point a localization adds.

        Patched onto the registry class, not the recordset: recordsets carry
        `__slots__`, so an instance attribute raises rather than shadowing.
        """
        checked = []

        def _validate_code_test_rfc(self, value):
            checked.append(value)
            return value.startswith("VAN")

        with patch.object(
            type(self.rfc),
            "_validate_code_test_rfc",
            _validate_code_test_rfc,
            create=True,
        ):
            self.company._update_identifier("TEST_RFC", "VAN850101QW1")
            self.assertEqual(checked, ["VAN850101QW1"])

            with self.assertRaises(ValidationError):
                with self.cr.savepoint():
                    self.company._update_identifier("TEST_RFC", "ZZZ850101QW1")

    def test_a_value_with_non_ascii_letters_is_normalized_not_stripped(self):
        """A leading Ñ or an ampersand belongs to the RFC; normalizing must keep
        them, not delete them into a value the pattern then rejects."""
        self.company._update_identifier("TEST_RFC", "ÑAM-010101-AB1")
        identifier = self.company.identifier_ids.filtered(
            lambda i: i.type_id == self.rfc
        )
        self.assertEqual(identifier.value, "ÑAM-010101-AB1")
        self.assertEqual(identifier.normalized_value, "ÑAM010101AB1")

        amp = self.Partner.create({"name": "A&B SA", "is_company": True})
        amp._update_identifier("TEST_RFC", "A&B-010101-AB1")
        self.assertEqual(
            amp.identifier_ids.filtered(
                lambda i: i.type_id == self.rfc
            ).normalized_value,
            "A&B010101AB1",
        )

    def test_a_clash_with_an_unreadable_holder_raises_validation_not_access(self):
        """The uniqueness check must see holders in other companies (so it can
        refuse the value) without leaking the read as an AccessError."""
        company_b = self.env["res.company"].create({"name": "Other Co"})
        hidden = self.Partner.create(
            {"name": "Hidden Holder", "company_id": company_b.id}
        )
        self.Identifier.create(
            {
                "partner_id": hidden.id,
                "type_id": self.rfc.id,
                "value": "VAN850101QW1",
            }
        )
        manager = self.env["res.users"].create(
            {
                "name": "Partner Manager A",
                "login": "identifier_pm_a",
                "company_ids": [(6, 0, self.env.ref("base.main_company").ids)],
                "company_id": self.env.ref("base.main_company").id,
                "group_ids": [
                    (
                        6,
                        0,
                        [
                            self.env.ref("base.group_user").id,
                            self.env.ref("base.group_partner_manager").id,
                        ],
                    )
                ],
            }
        )
        mine = self.Partner.create({"name": "Mine A"})
        with self.assertRaises(ValidationError):
            with self.cr.savepoint():
                mine.with_user(manager)._update_identifier("TEST_RFC", "VAN850101QW1")

    def test_a_code_does_not_collide_with_a_model_method(self):
        """The code-specific rule is dispatched by name, so a type whose code
        happens to match a real method (e.g. "hook" -> _check_hook, or
        "pattern_compiles" -> the constraint) must not hijack validation."""
        for code in ("hook", "pattern_compiles"):
            with self.subTest(code=code):
                self.Type.create(
                    {
                        "name": f"Collide {code}",
                        "code": code,
                        "pattern": r"[A-Z]{3}[0-9]{3}",
                    }
                )
                partner = self.Partner.create(
                    {"name": f"Collide {code} Co", "is_company": True}
                )
                partner._update_identifier(code, "ABC123")
                self.assertEqual(partner._get_identifier(code), "ABC123")
