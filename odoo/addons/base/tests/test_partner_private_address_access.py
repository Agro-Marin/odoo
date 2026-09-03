from odoo.exceptions import AccessError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install")
class TestPrivateAddressAccess(TransactionCase):
    """A private address is a row, so a row rule is what guards it.

    Every read goes through `with_user`. A `TransactionCase` runs as superuser
    and `env.su` skips record rules entirely, so the same assertions written
    without `with_user` pass whether or not the rule exists.

    The field-level `groups=` that `hr` puts on `private_street` and its five
    siblings gates the ACCESSOR. It cannot gate this model, which is what
    `search` reaches -- and that is the whole reason this rule exists.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Partner = cls.env["res.partner"]

        cls.reader = cls.env["res.users"].create(
            {
                "name": "Ordinary Reader",
                "login": "private_address_reader",
                "group_ids": [(6, 0, [cls.env.ref("base.group_user").id])],
            }
        )
        cls.manager = cls.env["res.users"].create(
            {
                "name": "Contact Manager",
                "login": "private_address_manager",
                "group_ids": [
                    (
                        6,
                        0,
                        [
                            cls.env.ref("base.group_user").id,
                            cls.env.ref("base.group_partner_manager").id,
                        ],
                    )
                ],
            }
        )
        cls.subject = Partner.create({"name": "Subject Person"})
        cls.subject_home = Partner.create(
            {
                "parent_id": cls.subject.id,
                "type": "private",
                "street": "12 Rue Confidentielle",
                "city": "Brussels",
            }
        )
        cls.reader_home = Partner.create(
            {
                "parent_id": cls.reader.partner_id.id,
                "type": "private",
                "street": "3 Own Street",
                "city": "Ghent",
            }
        )
        cls.ordinary_child = Partner.create(
            {
                "parent_id": cls.subject.id,
                "type": "delivery",
                "street": "Warehouse Dock 4",
                "city": "Antwerp",
            }
        )

    def _visible(self):
        return self.env["res.partner"].with_user(self.reader).search([])

    def test_another_persons_private_address_is_not_readable(self):
        self.assertNotIn(self.subject_home, self._visible())

    def test_the_subject_reads_their_own_private_address(self):
        self.assertIn(self.reader_home, self._visible())

    def test_the_person_themselves_stays_readable(self):
        """The rule hides the private child, never the party it hangs from."""
        self.assertIn(self.subject, self._visible())

    def test_an_ordinary_address_of_the_same_parent_stays_readable(self):
        """Only `private` is withdrawn -- delivery, invoice and other are not."""
        self.assertIn(self.ordinary_child, self._visible())

    def test_the_rule_does_not_narrow_ordinary_contacts(self):
        """Everything a reader could see before the rule, they still can."""
        as_superuser = self.env["res.partner"].search([("type", "!=", "private")])
        as_reader = (
            self.env["res.partner"]
            .with_user(self.reader)
            .search([("type", "!=", "private")])
        )
        self.assertEqual(as_superuser, as_reader)

    def test_reading_the_columns_directly_is_refused_too(self):
        """`search` is not the only way in; a browse of a known id is another.

        Nothing here hands a reader that id, but a rule that filtered `search`
        and not `read` would be a rule in name only.
        """
        with self.assertRaises(AccessError):
            self.subject_home.with_user(self.reader).read(["street", "city"])

    def test_a_contact_manager_cannot_delete_another_persons_private_address(self):
        """Hidden rows were still deletable by id; the rule now covers unlink.

        Write is already refused because the ORM will not write a row the user
        cannot read, but unlink checked only the ACL, so any partner manager
        who obtained the id could remove someone else's home address.
        """
        with self.assertRaises(AccessError):
            self.subject_home.with_user(self.manager).unlink()
        self.assertTrue(self.subject_home.exists())

    def test_the_subject_deletes_their_own_private_address(self):
        own = self.env["res.partner"].create(
            {
                "parent_id": self.manager.partner_id.id,
                "type": "private",
                "street": "9 Removable Lane",
            }
        )
        own.with_user(self.manager).unlink()
        self.assertFalse(own.exists())

    def test_a_contact_manager_still_deletes_an_ordinary_address(self):
        other = self.env["res.partner"].create(
            {"parent_id": self.subject.id, "type": "delivery", "street": "Dock 5"}
        )
        other.with_user(self.manager).unlink()
        self.assertFalse(other.exists())

    def test_the_rule_is_global_and_must_stay_global(self):
        """A group-scoped rule here would be permissive, not restrictive.

        `_get_domain_accessible_records` ORs every applicable group rule
        together and only then ANDs the result with the global ones. A group
        rule whose domain is true for ordinary contacts -- which this domain is,
        by its first branch -- would therefore OR away any OTHER group-scoped
        restriction on res.partner rather than adding one of its own.

        `test_acl.TestIrRule.test_ir_rule_access_error_message` is the
        standing proof that this matters: it installs a deny-everything
        `base.group_user` rule on res.partner and asserts the denial holds.
        Scoping this rule to `base.group_user` makes that test fail, which is
        how the shape was found to be wrong.
        """
        rule = self.env.ref("base.res_partner_private_address_rule")
        self.assertTrue(rule["global"])
        self.assertFalse(rule.groups)

    def test_the_domain_names_parent_id_rather_than_child_of(self):
        """`child_of user.partner_id` reads as the natural spelling and is wider.

        A reader whose own partner is a company would gain every private
        address parented anywhere beneath it, which is the population this rule
        exists to withhold.
        """
        rule = self.env.ref("base.res_partner_private_address_rule")
        self.assertIn("parent_id", rule.domain_force)
        self.assertNotIn("child_of", rule.domain_force)
