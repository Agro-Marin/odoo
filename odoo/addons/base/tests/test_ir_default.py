from datetime import datetime
from unittest.mock import patch

from psycopg import IntegrityError

from odoo.exceptions import AccessError, ValidationError
from odoo.tests.common import TransactionCase, new_test_user
from odoo.tools import mute_logger


class TestIrDefault(TransactionCase):
    def test_unique_scope_prevents_duplicate(self):
        """One ir.default per (field, user, company, condition) scope.

        ``set()`` updates the existing row rather than duplicating it, and a
        direct duplicate insert is rejected by the UNIQUE index (which stops the
        concurrent-``set()`` race from leaving permanent shadow rows).
        """
        IrDefault = self.env["ir.default"]
        field = self.env["ir.model.fields"]._get("res.partner", "ref")
        IrDefault.search([("field_id", "=", field.id)]).unlink()

        # set() twice for the same scope → exactly one row, latest value wins.
        IrDefault.set("res.partner", "ref", "A")
        IrDefault.set("res.partner", "ref", "B")
        rows = IrDefault.search(
            [
                ("field_id", "=", field.id),
                ("user_id", "=", False),
                ("company_id", "=", False),
                ("condition", "=", False),
            ]
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(IrDefault._get_model_defaults("res.partner").get("ref"), "B")

        # A direct duplicate of that scope violates the UNIQUE index.
        with (
            mute_logger("odoo.sql_db"),
            self.assertRaisesRegex(IntegrityError, "ir_default_unique_scope"),
            self.cr.savepoint(),
        ):
            IrDefault.create({"field_id": field.id, "json_value": '"C"'})
            IrDefault.flush_all()

    def test_defaults(self):
        """check the mechanism of user-defined defaults"""
        companyA = self.env.company
        companyB = companyA.create({"name": "CompanyB"})
        user1 = self.env.user
        user2 = user1.create({"name": "u2", "login": "u2"})
        user3 = user1.create(
            {
                "name": "u3",
                "login": "u3",
                "company_id": companyB.id,
                "company_ids": companyB.ids,
            }
        )

        # create some default value for some model
        IrDefault1 = self.env["ir.default"]
        IrDefault2 = IrDefault1.with_user(user2)
        IrDefault3 = IrDefault1.with_user(user3)

        # set a default value for all users
        IrDefault1.search([("field_id.model", "=", "res.partner")]).unlink()
        IrDefault1.set("res.partner", "ref", "GLOBAL", user_id=False, company_id=False)
        self.assertEqual(
            IrDefault1._get_model_defaults("res.partner"),
            {"ref": "GLOBAL"},
            "Can't retrieve the created default value for all users.",
        )
        self.assertEqual(
            IrDefault2._get_model_defaults("res.partner"),
            {"ref": "GLOBAL"},
            "Can't retrieve the created default value for all users.",
        )
        self.assertEqual(
            IrDefault3._get_model_defaults("res.partner"),
            {"ref": "GLOBAL"},
            "Can't retrieve the created default value for all users.",
        )

        # set a default value for current company (behavior of 'set default' from debug mode)
        IrDefault1.set("res.partner", "ref", "COMPANY", user_id=False, company_id=True)
        self.assertEqual(
            IrDefault1._get_model_defaults("res.partner"),
            {"ref": "COMPANY"},
            "Can't retrieve the created default value for company.",
        )
        self.assertEqual(
            IrDefault2._get_model_defaults("res.partner"),
            {"ref": "COMPANY"},
            "Can't retrieve the created default value for company.",
        )
        self.assertEqual(
            IrDefault3._get_model_defaults("res.partner"),
            {"ref": "GLOBAL"},
            "Unexpected default value for company.",
        )

        # set a default value for current user (behavior of 'set default' from debug mode)
        IrDefault2.set("res.partner", "ref", "USER", user_id=True, company_id=True)
        self.assertEqual(
            IrDefault1._get_model_defaults("res.partner"),
            {"ref": "COMPANY"},
            "Can't retrieve the created default value for user.",
        )
        self.assertEqual(
            IrDefault2._get_model_defaults("res.partner"),
            {"ref": "USER"},
            "Unexpected default value for user.",
        )
        self.assertEqual(
            IrDefault3._get_model_defaults("res.partner"),
            {"ref": "GLOBAL"},
            "Unexpected default value for company.",
        )

        # check default values on partners
        default1 = IrDefault1.env["res.partner"].default_get(["ref"]).get("ref")
        self.assertEqual(default1, "COMPANY", "Wrong default value.")
        default2 = IrDefault2.env["res.partner"].default_get(["ref"]).get("ref")
        self.assertEqual(default2, "USER", "Wrong default value.")
        default3 = IrDefault3.env["res.partner"].default_get(["ref"]).get("ref")
        self.assertEqual(default3, "GLOBAL", "Wrong default value.")

    def test_conditions(self):
        """check user-defined defaults with condition"""
        IrDefault = self.env["ir.default"]

        # default without condition
        IrDefault.search([("field_id.model", "=", "res.partner")]).unlink()
        IrDefault.set("res.partner", "ref", "X")
        self.assertEqual(IrDefault._get_model_defaults("res.partner"), {"ref": "X"})
        self.assertEqual(
            IrDefault._get_model_defaults("res.partner", condition="name=Agrolait"),
            {},
        )

        # default with a condition
        IrDefault.search([("field_id.model", "=", "res.partner")]).unlink()
        IrDefault.set("res.partner", "street", "X")
        IrDefault.set("res.partner", "street", "Mr", condition="name=Mister")
        self.assertEqual(IrDefault._get_model_defaults("res.partner"), {"street": "X"})
        self.assertEqual(
            IrDefault._get_model_defaults("res.partner", condition="name=Miss"),
            {},
        )
        self.assertEqual(
            IrDefault._get_model_defaults("res.partner", condition="name=Mister"),
            {"street": "Mr"},
        )

    def test_invalid(self):
        """check error cases with 'ir.default'"""
        IrDefault = self.env["ir.default"]
        with self.assertRaises(ValidationError):
            IrDefault.set("unknown_model", "unknown_field", 42)
        with self.assertRaises(ValidationError):
            IrDefault.set("res.partner", "unknown_field", 42)
        with self.assertRaises(ValidationError):
            IrDefault.set("res.partner", "type", "invalid_type")
        with self.assertRaises(ValidationError):
            IrDefault.set("res.partner", "partner_latitude", "foo")
        with self.assertRaises(ValidationError):
            IrDefault.set("res.partner", "color", 2147483648)

    def test_removal(self):
        """check defaults for many2one with their value being removed"""
        IrDefault = self.env["ir.default"]
        IrDefault.search([("field_id.model", "=", "res.partner")]).unlink()

        # set a record as a default value
        country_id = self.env["res.country"].create({"name": "country", "code": "ZZ"})
        IrDefault.set("res.partner", "country_id", country_id.id)
        self.assertEqual(
            IrDefault._get_model_defaults("res.partner"),
            {"country_id": country_id.id},
        )

        # delete the record, and check the presence of the default value
        country_id.unlink()
        self.assertEqual(IrDefault._get_model_defaults("res.partner"), {})

    def test_multi_company_defaults(self):
        """Check defaults in multi-company environment."""
        company_a = self.env["res.company"].create({"name": "C_A"})
        company_b = self.env["res.company"].create({"name": "C_B"})
        company_a_b = company_a + company_b
        company_b_a = company_b + company_a
        multi_company_user = self.env["res.users"].create(
            {
                "name": "u2",
                "login": "u2",
                "company_id": company_a.id,
                "company_ids": company_a_b.ids,
            }
        )
        IrDefault = self.env["ir.default"].with_user(multi_company_user)
        IrDefault.with_context(allowed_company_ids=company_a.ids).set(
            "res.partner", "ref", "CADefault", user_id=True, company_id=True
        )
        IrDefault.with_context(allowed_company_ids=company_b.ids).set(
            "res.partner", "ref", "CBDefault", user_id=True, company_id=True
        )
        self.assertEqual(
            IrDefault._get_model_defaults("res.partner")["ref"],
            "CADefault",
        )
        self.assertEqual(
            IrDefault.with_context(
                allowed_company_ids=company_a.ids
            )._get_model_defaults("res.partner")["ref"],
            "CADefault",
        )
        self.assertEqual(
            IrDefault.with_context(
                allowed_company_ids=company_b.ids
            )._get_model_defaults("res.partner")["ref"],
            "CBDefault",
        )
        self.assertEqual(
            IrDefault.with_context(
                allowed_company_ids=company_a_b.ids
            )._get_model_defaults("res.partner")["ref"],
            "CADefault",
        )
        self.assertEqual(
            IrDefault.with_context(
                allowed_company_ids=company_b_a.ids
            )._get_model_defaults("res.partner")["ref"],
            "CBDefault",
        )

    def test_json_format_invalid(self):
        """check the _check_json_format constraint"""
        IrDefault = self.env["ir.default"]
        field_id = self.env["ir.model.fields"].search(
            [("model", "=", "res.partner"), ("name", "=", "ref")]
        )
        with self.assertRaises(ValidationError):
            IrDefault.create(
                {
                    "field_id": field_id.id,
                    "json_value": '{"name":"John", }',
                }
            )
        # IDEF-C1: an out-of-int4-bounds integer default must be rejected by the
        # constraint too (not only by set()), since the constraint is the sole
        # guard on a direct create/write (e.g. from the form view).
        color_field = self.env["ir.model.fields"].search(
            [("model", "=", "res.partner"), ("name", "=", "color")]
        )
        with self.assertRaises(ValidationError):
            IrDefault.create(
                {
                    "field_id": color_field.id,
                    "json_value": "2147483648",
                }
            )

    def test_get(self):
        """_get returns the exact-scope default, or None when there is none."""
        IrDefault = self.env["ir.default"]
        IrDefault.search([("field_id.model", "=", "res.partner")]).unlink()

        # no default yet
        self.assertIsNone(IrDefault._get("res.partner", "ref"))

        # a global default round-trips
        IrDefault.set("res.partner", "ref", "GLOBAL")
        self.assertEqual(IrDefault._get("res.partner", "ref"), "GLOBAL")

        # _get matches an exact scope, it does not fall back: a user+company
        # default is only visible for that precise scope
        IrDefault.set("res.partner", "ref", "MINE", user_id=True, company_id=True)
        self.assertEqual(
            IrDefault._get("res.partner", "ref", user_id=True, company_id=True),
            "MINE",
        )
        # the ``True`` sentinels resolve to the current user / company
        self.assertEqual(
            IrDefault._get(
                "res.partner",
                "ref",
                user_id=self.env.uid,
                company_id=self.env.company.id,
            ),
            "MINE",
        )
        # the global default is still returned for the global scope
        self.assertEqual(IrDefault._get("res.partner", "ref"), "GLOBAL")
        # an unmatched scope yields None
        self.assertIsNone(
            IrDefault._get("res.partner", "ref", user_id=self.env.uid + 1000)
        )

    def test_discard_records(self):
        """discard_records drops many2one defaults pointing at the given records."""
        IrDefault = self.env["ir.default"]
        IrDefault.search([("field_id.model", "=", "res.partner")]).unlink()
        country = self.env["res.country"].create({"name": "ZZ-country", "code": "Z9"})
        IrDefault.set("res.partner", "country_id", country.id)
        self.assertEqual(
            IrDefault._get_model_defaults("res.partner"),
            {"country_id": country.id},
        )
        IrDefault.discard_records(country)
        self.assertEqual(IrDefault._get_model_defaults("res.partner"), {})

    def test_discard_values(self):
        """discard_values drops defaults whose stored value is in the given list."""
        IrDefault = self.env["ir.default"]
        IrDefault.search([("field_id.model", "=", "res.partner")]).unlink()

        IrDefault.set("res.partner", "ref", "DROP")
        IrDefault.discard_values("res.partner", "ref", ["OTHER", "DROP"])
        self.assertIsNone(IrDefault._get("res.partner", "ref"))

        # a value absent from the list leaves the default untouched
        IrDefault.set("res.partner", "ref", "KEEP")
        IrDefault.discard_values("res.partner", "ref", ["NOPE"])
        self.assertEqual(IrDefault._get("res.partner", "ref"), "KEEP")

    def test_set_datetime_value_coercion(self):
        """A ``date``/``datetime`` object is stored in its string form."""
        IrDefault = self.env["ir.default"]
        IrDefault.set("ir.cron", "nextcall", datetime(2021, 5, 6, 7, 8, 9))
        self.assertEqual(IrDefault._get("ir.cron", "nextcall"), "2021-05-06 07:08:09")

    def test_set_skips_write_when_value_unchanged(self):
        """Re-setting an identical value hits the no-op branch (no write/cache bust)."""
        IrDefault = self.env["ir.default"]
        IrDefault.search([("field_id.model", "=", "res.partner")]).unlink()
        IrDefault.set("res.partner", "ref", "SAME")

        with patch.object(type(IrDefault), "write", autospec=True) as mocked_write:
            IrDefault.set("res.partner", "ref", "SAME")
        self.assertEqual(
            mocked_write.call_count, 0, "an identical set() must not write"
        )

        # a genuine change still updates in place
        IrDefault.set("res.partner", "ref", "CHANGED")
        self.assertEqual(IrDefault._get("res.partner", "ref"), "CHANGED")

    def test_set_checks_field_write_access(self):
        """A user may only set a default for a field they are allowed to write."""
        # ``ir.mail_server.smtp_user`` is restricted to ``base.group_system``.
        model_name, field_name = "ir.mail_server", "smtp_user"

        # an unprivileged internal user can create their own defaults (record
        # rule), but not for a field they cannot write (field-level check)
        plain_user = new_test_user(
            self.env, login="ird_plain_user", groups="base.group_user"
        )
        with self.assertRaises(AccessError):
            self.env["ir.default"].with_user(plain_user).set(
                model_name, field_name, "smtp-login", user_id=True
            )

        # a system user (still not the superuser) is allowed
        system_user = new_test_user(
            self.env,
            login="ird_system_user",
            groups="base.group_user,base.group_system",
        )
        IrDefaultAsSystem = self.env["ir.default"].with_user(system_user)
        IrDefaultAsSystem.set(model_name, field_name, "smtp-login", user_id=True)
        self.assertEqual(
            IrDefaultAsSystem._get(model_name, field_name, user_id=True),
            "smtp-login",
        )

    def test_set_allows_writable_field_for_plain_user(self):
        """The access check does not over-block: a writable field is accepted."""
        plain_user = new_test_user(
            self.env, login="ird_writer", groups="base.group_user"
        )
        IrDefaultAsUser = self.env["ir.default"].with_user(plain_user)
        IrDefaultAsUser.set("res.partner", "comment", "hello", user_id=True)
        self.assertEqual(
            IrDefaultAsUser._get("res.partner", "comment", user_id=True), "hello"
        )
