from odoo.exceptions import AccessError
from odoo.fields import Command
from odoo.tests import TransactionCase, new_test_user, tagged


@tagged("post_install", "-at_install")
class TestScopedGrantFields(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company_a = cls.env.company
        cls.company_b = cls.env["res.company"].create({"name": "Scoped fields B"})
        cls.user = new_test_user(
            cls.env,
            login="scoped_fields",
            groups="base.group_user",
            company_ids=[Command.set((cls.company_a | cls.company_b).ids)],
        )
        cls.env["res.users.grant"].create(
            {
                "user_id": cls.user.id,
                "group_id": cls.env.ref("test_access_rights.test_group").id,
                "company_ids": [Command.set(cls.company_a.ids)],
            }
        )
        cls.record_b = cls.env["test_access_right.some_obj"].create(
            {"val": 1, "company_id": cls.company_b.id, "forbidden2": 7}
        )

    def read_forbidden2(self, *companies):
        env = self.env(
            user=self.user,
            context={"allowed_company_ids": [company.id for company in companies]},
        )
        return env["test_access_right.some_obj"].browse(self.record_b.id).forbidden2

    def test_a_field_group_held_in_one_company_shows_the_field_everywhere(self):
        # Known limit of P2, pinned so P5 changes it on purpose: a field's
        # groups= is asked of the companies in use, not of the record, so with
        # A and B in use a group held in A only shows the field on B's records
        # too; the record rules still decide which records are read at all
        self.assertEqual(self.read_forbidden2(self.company_a, self.company_b), 7)

    def test_without_the_group_s_company_in_use_the_field_is_hidden(self):
        with self.assertRaises(AccessError):
            self.read_forbidden2(self.company_b)
