"""``groups`` on a field must survive the routes that do not call ``__get__``.

``Field.__get__`` has always refused a field the user has no group for.  The
SQL-side routes reach the column differently, and for a NON-STORED RELATED
field they used to lose the restriction entirely:

* ``BaseModel._field_to_sql`` returns early for such a field and recurses onto
  its *target*, so it checks the target's ``groups`` and never the related
  field's own;
* ``DomainCondition._optimize_step`` runs the field's ``search`` method
  (``_search_related``), which rewrites the leaf into a condition on the
  target -- again dropping the restricted field.

Either route let a user without the group recover the value without ever
reading it: ``search`` narrows it by inference, ``_read_group`` returns it
outright.  Both are closed at the entry points that disclose values; see
``_field_to_sql`` for why the check cannot live in the SQL builder itself.
"""

from odoo.exceptions import AccessError
from odoo.tests.common import TransactionCase


class TestFieldGroupsInSql(TransactionCase):
    """``groups`` on a non-stored related field is enforced in SQL contexts."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Reading the model needs base.group_multi_company, which
        # ``res.users._sync_multi_company_group`` grants from the number of
        # allowed companies -- it strips the group from a single-company user,
        # so granting it directly would not stick.  group_erp_manager, which
        # the field is restricted to, is deliberately withheld.
        cls.companies = cls.env.company | cls.env["res.company"].create(
            {"name": "Second Company"}
        )
        cls.probe_user = cls._create_user("no_erp_manager", [])
        target = cls.env["test_orm.model.some_access"].create({"a": 42})
        cls.record = cls.env["test_orm.model2.some_access"].create({"g_id": target.id})
        cls.model = cls.env["test_orm.model2.some_access"].with_user(cls.probe_user)

    @classmethod
    def _create_user(cls, login, extra_group_xmlids):
        groups = [cls.env.ref("base.group_user").id] + [
            cls.env.ref(xmlid).id for xmlid in extra_group_xmlids
        ]
        return cls.env["res.users"].create(
            {
                "name": login,
                "login": login,
                "company_id": cls.env.company.id,
                "company_ids": [(6, 0, cls.companies.ids)],
                "group_ids": [(6, 0, groups)],
            }
        )

    def test_setup_is_the_case_under_test(self):
        """The field is restricted, its target is not, and the user lacks the group.

        Without all three the other assertions would pass for the wrong reason
        -- an unreadable model, or a restriction inherited from the target.
        """
        field = self.model._fields["g_a_restricted"]
        self.assertTrue(field.related and not field.store)
        self.assertTrue(field.groups)
        self.assertFalse(field.related_field.groups)
        self.assertTrue(self.model.has_access("read"))
        self.assertFalse(self.model._has_field_access(field, "read"))

    def test_get_is_denied(self):
        record = self.record.with_user(self.probe_user)
        with self.assertRaises(AccessError):
            _ = record.g_a_restricted

    def test_search_is_denied(self):
        with self.assertRaises(AccessError):
            self.model.search([("g_a_restricted", "=", 42)])

    def test_read_group_is_denied(self):
        with self.assertRaises(AccessError):
            self.model._read_group([], ["g_a_restricted"], ["__count"])

    def test_aggregate_is_denied(self):
        with self.assertRaises(AccessError):
            self.model._read_group([], [], ["g_a_restricted:sum"])

    def test_read_is_denied(self):
        with self.assertRaises(AccessError):
            self.record.with_user(self.probe_user).read(["g_a_restricted"])

    def test_superuser_is_unaffected(self):
        """The restriction is group-based, so sudo keeps working."""
        model = self.env["test_orm.model2.some_access"].sudo()
        self.assertEqual(self.record.sudo().g_a_restricted, 42)
        self.assertTrue(model.search([("g_a_restricted", "=", 42)]))
        model._read_group([], ["g_a_restricted"], ["__count"])

    def test_unrestricted_related_field_stays_usable(self):
        """The check must not deny related fields that carry no groups."""
        manager = self._create_user("erp_manager", ["base.group_erp_manager"])
        model = self.env["test_orm.model2.some_access"].with_user(manager)
        self.assertTrue(
            model._has_field_access(model._fields["g_a_restricted"], "read")
        )
        model.search([("g_a_restricted", "=", 42)])
        model._read_group([], ["g_a_restricted"], ["__count"])
