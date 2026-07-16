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
