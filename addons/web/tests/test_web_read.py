"""Behavioral tests for ``web_read`` relational resolution.

``web_read`` is the primary data fetcher for the entire webclient, yet its
relational resolution (many2one sub-fields, x2many ``limit``/``order``,
deleted-target handling) had no direct behavioral coverage — it was only
exercised inside ``assertQueryCount`` perf tests that discard the return value.
"""

from odoo.tests import common


@common.tagged("post_install", "-at_install", "web_unit", "web_read")
class TestWebReadRelational(common.TransactionCase):
    def test_many2one_subfield_resolution(self):
        parent = self.env["res.partner"].create(
            {"name": "Parent Co", "is_company": True}
        )
        child = self.env["res.partner"].create(
            {"name": "Child", "parent_id": parent.id}
        )
        res = child.web_read(
            {"name": {}, "parent_id": {"fields": {"display_name": {}}}}
        )
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0]["name"], "Child")
        self.assertIsInstance(res[0]["parent_id"], dict)
        self.assertEqual(res[0]["parent_id"]["display_name"], "Parent Co")

    def test_many2one_to_deleted_target_is_false(self):
        parent = self.env["res.partner"].create(
            {"name": "ToDelete", "is_company": True}
        )
        child = self.env["res.partner"].create(
            {"name": "Orphan", "parent_id": parent.id}
        )
        self.env.flush_all()
        parent.unlink()  # parent_id ondelete='set null'
        child.invalidate_recordset()
        res = child.web_read(
            {"name": {}, "parent_id": {"fields": {"display_name": {}}}}
        )
        self.assertFalse(
            res[0]["parent_id"], "deleted m2o target must resolve to False"
        )

    def test_x2many_limit_resolves_fields_but_returns_all_ids(self):
        """Documented contract (web_read.py): the FULL id list is returned,
        sorted by ``order``; only the first ``limit`` co-records get their
        ``fields`` resolved — the rest come back as ``{"id": id}`` stubs."""
        parent = self.env["res.partner"].create({"name": "P", "is_company": True})
        for i in range(5):
            self.env["res.partner"].create({"name": f"C{i}", "parent_id": parent.id})
        self.env.flush_all()
        res = parent.web_read(
            {
                "child_ids": {"fields": {"name": {}}, "limit": 2, "order": "name desc"},
            }
        )
        child_ids = res[0]["child_ids"]
        self.assertEqual(len(child_ids), 5, "all related ids must be returned")
        resolved = [c for c in child_ids if "name" in c]
        stubs = [c for c in child_ids if "name" not in c]
        self.assertEqual(
            len(resolved), 2, "only `limit` co-records get fields resolved"
        )
        self.assertEqual(len(stubs), 3, "the rest are {id} stubs")
        # the resolved records are the first `limit` of the desc-sorted full list
        first_two = [c["name"] for c in child_ids[:2]]
        self.assertEqual(first_two, sorted(first_two, reverse=True), "order honored")

    def test_x2many_no_order_filters_inaccessible_corecords(self):
        """An x2many spec with ``fields`` but no ``order`` must drop co-records
        the user cannot read (record rules) instead of raising AccessError on
        the whole read.

        Regression: the no-``order`` branch called ``co_records.web_read(...)``
        without first filtering by access, so a single rule-restricted
        co-record aborted the entire read with AccessError. The ``order``
        branch was unaffected because ``search`` already enforces access.
        """
        Partner = self.env["res.partner"]
        ok1 = Partner.create({"name": "VisibleChild1"})
        secret = Partner.create({"name": "ZZSECRET child"})
        ok2 = Partner.create({"name": "VisibleChild2"})
        parent = Partner.create(
            {
                "name": "AccessParent",
                "child_ids": [(6, 0, (ok1 + secret + ok2).ids)],
            }
        )
        self.env.flush_all()

        # Global record rule hiding ZZSECRET* partners from every non-superuser.
        self.env["ir.rule"].create(
            {
                "name": "test hide secret partners",
                "model_id": self.env["ir.model"]._get("res.partner").id,
                "domain_force": "[('name', 'not ilike', 'ZZSECRET')]",
                "groups": [],
            }
        )
        user = self.env["res.users"].create(
            {
                "name": "x2m access tester",
                "login": "x2m_access_tester",
                "group_ids": [(6, 0, [self.env.ref("base.group_user").id])],
            }
        )
        # Sanity: the user genuinely cannot see the secret co-record.
        self.assertNotIn(secret.id, Partner.with_user(user).search([]).ids)

        # No 'order' in the spec — the path that previously raised AccessError.
        res = parent.with_user(user).web_read({"child_ids": {"fields": {"name": {}}}})

        returned_ids = [c["id"] for c in res[0]["child_ids"]]
        self.assertEqual(
            returned_ids,
            [ok1.id, ok2.id],
            "rule-hidden co-record must be filtered out, not raise AccessError",
        )
        self.assertNotIn(
            secret.id, returned_ids, "inaccessible co-record id must not leak"
        )


@common.tagged("post_install", "-at_install", "web_unit", "web_read")
class TestWebResequence(common.TransactionCase):
    """web_resequence must not silently bypass write() semantics.

    The cache-dirty fast path skips write() entirely, so a model that overrides
    write (guards, tracking, cache invalidation) must fall back to per-record
    write(). Regression for the fork optimization that dropped write().
    """

    def test_resequence_calls_write_on_overriding_model(self):
        from unittest.mock import patch

        Partner = self.env["res.partner"]  # overrides write()
        recs = Partner.create([{"name": f"P{i}", "color": 9} for i in range(3)])
        self.env.flush_all()

        real_write = type(Partner).write
        calls = []

        def counting_write(self, vals):
            if self._name == "res.partner":
                calls.append((tuple(self.ids), dict(vals)))
            return real_write(self, vals)

        with patch.object(type(Partner), "write", counting_write):
            recs.web_resequence({"id": {}}, field_name="color")

        # res.partner overrides write, so the fallback path must run it once
        # per record — the whole point of the fix.
        self.assertEqual(
            len(calls), 3, "write() must fire once per record on an overriding model"
        )
        self.assertEqual(recs.mapped("color"), [0, 1, 2])

    def test_resequence_persists_values(self):
        Partner = self.env["res.partner"]
        recs = Partner.create([{"name": f"Q{i}", "color": 5} for i in range(4)])
        recs.web_resequence({"id": {}}, field_name="color", offset=10)
        self.env.flush_all()
        self.assertEqual(recs.mapped("color"), [10, 11, 12, 13])


@common.tagged("post_install", "-at_install", "web_unit", "web_read")
class TestWebReadFieldContext(common.TransactionCase):
    """An x2many spec with `order` on a field whose context collides with the
    caller's env context must not raise TypeError (fork double-splat regression).
    """

    def test_ordered_x2many_with_active_test_context(self):
        # res.partner.child_ids declares context={'active_test': ...}; a caller
        # passing active_test in context previously triggered
        # "with_context() got multiple values for keyword argument 'active_test'".
        parent = self.env["res.partner"].create({"name": "Parent"})
        self.env["res.partner"].create(
            [{"name": "C1", "parent_id": parent.id},
             {"name": "C2", "parent_id": parent.id}]
        )
        self.env.flush_all()
        res = parent.with_context(active_test=False).web_read(
            {"child_ids": {"fields": {"display_name": {}}, "order": "id desc"}}
        )
        # Must return without raising; ordering honored.
        child_ids = [c["id"] for c in res[0]["child_ids"]]
        self.assertEqual(child_ids, sorted(child_ids, reverse=True))
