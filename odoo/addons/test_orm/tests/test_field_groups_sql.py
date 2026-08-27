from odoo.exceptions import AccessError
from odoo.tests.common import TransactionCase


class TestFieldGroupsInSql(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.companies = cls.env.company | cls.env["res.company"].create(
            {"name": "Second Company"}
        )
        cls.probe_user = cls._create_user("no_erp_manager", [])
        target = cls.env["test_orm.model.some_access"].create({"a": 42})
        cls.record = cls.env["test_orm.model2.some_access"].create({"g_id": target.id})
        cls.model = cls.env["test_orm.model2.some_access"].with_user(cls.probe_user)

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
        return tuple(model.search([("id", "in", self.ordered.ids)], order=order).ids)

    def test_order_by_restricted_field_does_not_order_by_it(self):
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
        self.assertEqual(
            self._search_ordered(self.model, "g_a_restricted"), self.order_by_id
        )

    def test_order_by_restricted_field_emits_no_sql_for_it(self):
        # Inspects Query/SQL internals (`.order.code`) deliberately: the
        # claim under test is "no SQL for the restricted field", and there
        # is no public-API way to observe the *absence* of a join/order
        # term short of parsing the emitted SQL itself.
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
        self.assertEqual(
            self._search_ordered(self.model, "g_a_restricted, id desc"),
            tuple(reversed(self.order_by_id)),
        )

    def test_superuser_is_unaffected(self):
        model = self.env["test_orm.model2.some_access"].sudo()
        self.assertEqual(self.record.sudo().g_a_restricted, 42)
        self.assertTrue(model.search([("g_a_restricted", "=", 42)]))
        model._read_group([], ["g_a_restricted"], ["__count"])

    def test_unrestricted_related_field_stays_usable(self):
        manager = self._create_user("erp_manager", ["base.group_erp_manager"])
        model = self.env["test_orm.model2.some_access"].with_user(manager)
        self.assertTrue(
            model._has_field_access(model._fields["g_a_restricted"], "read")
        )
        model.search([("g_a_restricted", "=", 42)])
        model._read_group([], ["g_a_restricted"], ["__count"])

    def test_copy_data_leaves_out_a_field_the_caller_cannot_read(self):
        """Duplicating a record must not require reading what the group hides.

        `copy_data` reads every copyable field off the source record, so a
        stored, copied field carrying `groups` used to raise `AccessError` for
        anyone outside that group -- for a field the caller never named, on an
        operation they are otherwise allowed to perform. 107 fields in this
        workspace are stored, copied and group-restricted,
        `ir.attachment.access_token` among them, so this reached far past the
        model under test here.

        The field is left out of the vals rather than read under `sudo`:
        `copy_data` is a public, RPC-reachable method, and putting the value in
        what it returns would hand the caller exactly what the group hides. The
        copy therefore gets the field's default, which is what the many2many
        branch of the same method has always done with records the caller
        cannot read.
        """
        source = self.env["test_orm.model.some_access"].create({"a": 42, "d": 7})
        as_probe = source.with_user(self.probe_user)
        self.assertFalse(
            as_probe._has_field_access(as_probe._fields["d"], "read"),
            "the probe user must not be able to read `d` for this to mean anything",
        )

        [vals] = as_probe.copy_data()

        self.assertEqual(vals.get("a"), 42, "an accessible field must still be copied")
        self.assertNotIn(
            "d",
            vals,
            "a field the caller cannot read must not be copied, and must not "
            "be returned to them either",
        )

    def test_copy_data_keeps_a_restricted_field_for_someone_who_may_read_it(self):
        manager = self._create_user("erp_manager_copy", ["base.group_erp_manager"])
        source = self.env["test_orm.model.some_access"].create({"a": 42, "d": 7})
        [vals] = source.with_user(manager).copy_data()
        self.assertEqual(vals.get("d"), 7, "the group's own members must still copy it")
