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

        # Three records whose restricted-value order is deliberately the
        # reverse-ish of their id order, so "ordered by the restricted field"
        # and "ordered by id" are distinguishable.
        targets = cls.env["test_orm.model.some_access"].create(
            [{"a": 30}, {"a": 10}, {"a": 20}]
        )
        cls.ordered = cls.env["test_orm.model2.some_access"].create(
            [{"g_id": t.id} for t in targets]
        )
        cls.order_by_value = tuple(cls.ordered[i].id for i in (1, 2, 0))
        cls.order_by_id = tuple(sorted(cls.ordered.ids))

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

    def _search_ordered(self, model, order):
        """Ids of ``self.ordered`` as *model* returns them for *order*."""
        return tuple(model.search([("id", "in", self.ordered.ids)], order=order).ids)

    def test_order_by_restricted_field_does_not_order_by_it(self):
        """ORDER BY must not sequence rows on a value the user cannot read.

        Ordering leaks less than ``search`` or ``_read_group`` -- relative
        order rather than the values -- but it is still derived from data the
        user has no group for, and with ``limit``/``offset`` the ordering can
        be walked out record by record.
        """
        self.assertEqual(
            self._search_ordered(
                self.env["test_orm.model2.some_access"].sudo(), "g_a_restricted"
            ),
            self.order_by_value,
            "sudo must still order by the field, else the test proves nothing",
        )
        self.assertNotEqual(
            self._search_ordered(self.model, "g_a_restricted"),
            self.order_by_value,
        )

    def test_order_by_restricted_field_stays_deterministic(self):
        """Dropping the term must not leave the query without an ORDER BY.

        An unordered query makes ``limit``/``offset`` pagination repeat and
        skip rows, so the ordering degrades to the primary key rather than to
        whatever the database happens to return.
        """
        self.assertEqual(
            self._search_ordered(self.model, "g_a_restricted"), self.order_by_id
        )

    def test_order_by_restricted_field_emits_no_sql_for_it(self):
        """The restricted column must not reach the ORDER BY clause at all.

        The field is reached through a join, so what must be absent is the
        join alias the related traversal introduces for ``g_id``.
        """
        join_alias = f"{self.model._table}__g_id"
        allowed = self.env["test_orm.model2.some_access"].sudo()
        self.assertIn(
            join_alias,
            allowed._search([], order="g_a_restricted").order.code,
            "sudo must order through the join, else the test proves nothing",
        )

        query = self.model._search([], order="g_a_restricted")
        self.assertTrue(query.order, "the order must not be empty")
        self.assertNotIn(join_alias, query.order.code)

    def test_order_by_keeps_the_accessible_terms(self):
        """Only the inaccessible term is dropped, not the whole ordering."""
        self.assertEqual(
            self._search_ordered(self.model, "g_a_restricted, id desc"),
            tuple(reversed(self.order_by_id)),
        )

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
