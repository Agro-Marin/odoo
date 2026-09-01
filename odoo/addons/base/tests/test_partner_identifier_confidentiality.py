from odoo.exceptions import AccessError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install")
class TestIdentifierConfidentiality(TransactionCase):
    """The record rule, exercised as a real user.

    Every read goes through `with_user`. A `TransactionCase` runs as superuser
    by default, and `env.su` skips record rules entirely -- so the same
    assertions written without `with_user` pass whether or not the rule exists.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Type = cls.env["res.partner.identifier.type"]
        cls.public_type = cls.Type.create({"name": "Loyalty Number", "code": "LOYALTY"})
        cls.secret_type = cls.Type.create(
            {"name": "National Number", "code": "NATIONAL", "confidential": True}
        )
        cls.reader = cls.env["res.users"].create(
            {
                "name": "Ordinary Reader",
                "login": "identifier_reader",
                "group_ids": [(6, 0, [cls.env.ref("base.group_user").id])],
            }
        )
        cls.other = cls.env["res.partner"].create({"name": "Someone Else"})
        cls.own_public = cls.env["res.partner.identifier"].create(
            {
                "partner_id": cls.reader.partner_id.id,
                "type_id": cls.public_type.id,
                "value": "L-1",
            }
        )
        cls.own_secret = cls.env["res.partner.identifier"].create(
            {
                "partner_id": cls.reader.partner_id.id,
                "type_id": cls.secret_type.id,
                "value": "N-1",
            }
        )
        cls.other_public = cls.env["res.partner.identifier"].create(
            {"partner_id": cls.other.id, "type_id": cls.public_type.id, "value": "L-2"}
        )
        cls.other_secret = cls.env["res.partner.identifier"].create(
            {"partner_id": cls.other.id, "type_id": cls.secret_type.id, "value": "N-2"}
        )

    def _visible_to_reader(self):
        return self.env["res.partner.identifier"].with_user(self.reader).search([])

    def test_another_contacts_confidential_identifier_is_not_readable(self):
        self.assertNotIn(self.other_secret, self._visible_to_reader())

    def test_a_non_confidential_identifier_stays_readable_by_everyone(self):
        self.assertIn(self.other_public, self._visible_to_reader())

    def test_the_subject_reads_their_own_confidential_identifier(self):
        self.assertIn(self.own_secret, self._visible_to_reader())
        self.assertIn(self.own_public, self._visible_to_reader())

    def test_reading_the_value_directly_raises_rather_than_returning_it(self):
        with self.assertRaises(AccessError):
            self.other_secret.with_user(self.reader).read(["value"])

    def test_the_rule_is_a_no_op_for_identifiers_of_unmarked_types(self):
        """confidential defaults False, so landing the rule changes nothing."""
        self.assertFalse(self.public_type.confidential)
        everything = self.env["res.partner.identifier"].search(
            [("type_id", "=", self.public_type.id)]
        )
        self.assertEqual(
            everything,
            everything.with_user(self.reader).search(
                [("type_id", "=", self.public_type.id)]
            ),
        )


@tagged("post_install", "-at_install")
class TestPrivateAddressType(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env["res.partner"].create(
            {"name": "Acme Corp", "is_company": True, "city": "Metropolis"}
        )
        cls.home = cls.env["res.partner"].create(
            {
                "parent_id": cls.company.id,
                "type": "private",
                "street": "Home 1",
                "city": "Smallville",
            }
        )

    def test_a_private_address_is_a_selectable_type(self):
        self.assertEqual(self.home.type, "private")

    def test_its_own_label_is_not_the_generic_one(self):
        self.assertEqual(self.home.type_address_label, "Private Address")

    def test_it_is_distinguishable_in_the_complete_name(self):
        """Without "private" in _complete_name_displayed_types a nameless home
        address renders as the bare parent name, indistinguishable from it."""
        self.assertIn("private", self.env["res.partner"]._complete_name_displayed_types)
        self.assertNotEqual(self.home.complete_name, self.company.complete_name)

    def test_the_parent_does_not_overwrite_a_private_address(self):
        self.company.write({"street": "Corporate Plaza", "city": "Metropolis"})
        self.home.invalidate_recordset()
        self.assertEqual(self.home.street, "Home 1")
        self.assertEqual(self.home.city, "Smallville")

    def test_a_private_address_does_not_push_up_onto_its_parent(self):
        """The direction that would leak an employee's home onto the company."""
        self.home.write({"street": "Home 2", "city": "Bludhaven"})
        self.company.invalidate_recordset()
        self.assertNotEqual(self.company.street, "Home 2")
        self.assertNotEqual(self.company.city, "Bludhaven")

    def test_address_get_does_not_hand_out_a_private_address_by_default(self):
        found = self.company.address_get(["delivery"])
        self.assertNotIn(self.home.id, found.values())
